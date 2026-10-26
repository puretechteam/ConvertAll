"""ConvertAll window: drop files, pick a format, convert."""

from __future__ import annotations

import getpass
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QLockFile,
    QPoint,
    QPointF,
    QSettings,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QPainter,
    QPen,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, engines, pipeline, registry
from .converters.archives import NATIVE_EXTRACT
from .detect import detect
from .errors import ConversionError
from .formats import ALIASES, CATEGORIES, category, describe, label, suggest

ASSETS = Path(__file__).resolve().parent / "assets"  # PyInstaller places them here too
SERVER_NAME = f"ConvertAll-{getpass.getuser()}"
EXTRACT_SETTLE_MS = 1000  # right-click Extract on several archives: wait for all their processes

LIGHT = {"bg": "#f7f7f8", "surface": "#ffffff", "text": "#18181b", "muted": "#71717a", "border": "#d4d4d8",
         "accent": "#6366f1", "accent_text": "#ffffff", "accent_soft": "#eef2ff", "error": "#dc2626", "ok": "#16a34a"}
DARK = {"bg": "#18181b", "surface": "#232326", "text": "#f4f4f5", "muted": "#a1a1aa", "border": "#3f3f46",
        "accent": "#818cf8", "accent_text": "#0b0b10", "accent_soft": "#26264a", "error": "#f87171", "ok": "#4ade80"}

QSS = """
QWidget {{ background: {bg}; color: {text}; font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; }}
#title {{ font-size: 15pt; font-weight: 600; }}
#drop {{ background: {surface}; border: 2px dashed {border}; border-radius: 16px; }}
#drop[active="true"] {{ border-color: {accent}; background: {accent_soft}; }}
#drop QLabel {{ background: transparent; }}
#dropMain {{ font-size: 13pt; font-weight: 600; }}
#muted, #dropSub {{ color: {muted}; }}
#status[state="error"] {{ color: {error}; }}
#status[state="ok"] {{ color: {ok}; }}
QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 8px 16px; }}
QPushButton#picker {{ min-height: 20px; }}
QPushButton#picker[open="true"] {{ border-color: {accent}; }}
#popup {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
#popup QWidget {{ background: transparent; }}
#popup QLineEdit {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; padding: 7px 10px; }}
#popup QLineEdit:focus {{ border-color: {accent}; }}
#section {{ color: {muted}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#legend, #empty {{ color: {muted}; font-size: 8.5pt; }}
QPushButton#chip {{ background: {bg}; border: 1px solid {border}; border-radius: 7px; padding: 6px 0; font-size: 9pt; font-weight: 600; }}
QPushButton#chip:hover, QPushButton#chip:focus {{ border-color: {accent}; outline: none; }}
QPushButton#chip[needs="true"] {{ color: {muted}; border-style: dashed; }}
QPushButton#chip[selected="true"] {{ background: {accent}; color: {accent_text}; border-color: {accent}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: none; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton#primary {{ background: {accent}; color: {accent_text}; border: none; font-weight: 600; }}
QPushButton#primary:disabled {{ background: {border}; color: {muted}; }}
QPushButton#link {{ background: transparent; border: none; color: {accent}; padding: 2px 0; }}
QToolButton {{ background: transparent; border: none; font-size: 14pt; color: {muted}; padding: 0 6px; }}
QToolButton::menu-indicator {{ image: none; }}
QProgressBar {{ background: {border}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent_soft}; }}
"""


THEME = dict(DARK)  # the palette in use, for widgets that paint themselves


def is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply_theme(app: QApplication) -> None:
    THEME.update(DARK if is_dark() else LIGHT)
    app.setStyleSheet(QSS.format(**THEME))


def reveal(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


# ---------------------------------------------------------------- background jobs

class Job(QThread):
    """Installs any missing engines, then converts (or extracts) each file."""
    progress = Signal(str)
    done = Signal(list, list)  # outputs, errors

    def __init__(self, files: list[Path], target: str | None, install: list[str]):
        super().__init__()
        self.files, self.target, self.install = files, target, install

    def run(self) -> None:
        outputs: list[Path] = []
        errors: list[str] = []
        for key in self.install:
            name = engines.ENGINES[key].name
            self.progress.emit(f"Installing {name}… (this can take a few minutes)")
            try:
                if not engines.install(key):
                    errors.append(f"Couldn't install {name}")
            except Exception as exc:  # noqa: BLE001 - the window must always hear back
                errors.append(str(exc) if isinstance(exc, ConversionError) else f"Couldn't install {name}: {exc}")
        if errors:
            self.done.emit(outputs, errors)
            return
        for i, f in enumerate(self.files, 1):
            count = f" {i} of {len(self.files)}" if len(self.files) > 1 else ""
            self.progress.emit(f"{'Extracting' if self.target is None else 'Converting'}{count} · {f.name}")
            try:
                out = pipeline.extract(f) if self.target is None else pipeline.convert(f, self.target)
                outputs.append(out)
            except (ConversionError, OSError) as exc:
                errors.append(f"{f.name}: {exc}")
            except Exception as exc:  # noqa: BLE001 - a surprise must not leave the window spinning forever
                errors.append(f"{f.name}: unexpected {type(exc).__name__}: {exc}")
        self.done.emit(outputs, errors)


class InstallJob(QThread):
    finished_ok = Signal(bool, str)

    def __init__(self, key: str):
        super().__init__()
        self.key = key

    def run(self) -> None:
        try:
            self.finished_ok.emit(engines.install(self.key), "")
        except Exception as exc:  # noqa: BLE001 - the dialog must always hear back
            self.finished_ok.emit(False, str(exc))


# ---------------------------------------------------------------- widgets

class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(190)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        self.main = QLabel("Drop files here")
        self.main.setObjectName("dropMain")
        self.sub = QLabel("or click to browse · folders work too")
        self.sub.setObjectName("dropSub")
        for w in (self.main, self.sub):
            w.setAlignment(Qt.AlignCenter)
            lay.addWidget(w)

    def show_files(self, files: list[Path], fmts: list[str]) -> None:
        if len(files) == 1:
            metrics = QFontMetrics(self.main.font())
            self.main.setText(metrics.elidedText(files[0].name, Qt.ElideMiddle, self.width() - 40))
            self.main.setToolTip(str(files[0]))
            self.sub.setText(describe(fmts[0]))
        else:
            self.main.setText(f"{len(files)} files")
            self.main.setToolTip("\n".join(str(f) for f in files[:30]))
            kinds = sorted({describe(f) for f in fmts})
            self.sub.setText(kinds[0] if len(kinds) == 1 else f"{len(kinds)} kinds of file")

    def _set_active(self, on: bool) -> None:
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, e):
        self._set_active(False)

    def dropEvent(self, e):
        self._set_active(False)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            names, _ = QFileDialog.getOpenFileNames(self, "Choose files to convert")
            if names:
                self.files_dropped.emit([Path(n) for n in names])


@dataclass
class Option:
    fmt: str            # "png"
    kind: str           # "Image"
    name: str           # "Portable Network Graphics", or "" when it would just repeat the extension
    needs: list[str]    # engines still to install, by display name


class FormatPicker(QPushButton):
    """Looks like a dropdown; opens a searchable grid of formats grouped by kind."""
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("picker")
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Output format")
        self.options: list[Option] = []
        self.suggested: list[str] = []
        self._current: str | None = None
        self.placeholder = "Choose a format"
        self.popup: FormatPopup | None = None
        self.clicked.connect(self.showPopup)

    # -- data

    def set_options(self, options: list[Option], current: str | None, suggested: list[str]) -> None:
        self.options = options
        self.suggested = [s for s in suggested if any(o.fmt == s for o in options)]
        self._current = current if any(o.fmt == current for o in options) else None
        self.update()

    def clear(self, placeholder: str) -> None:
        self.options, self.suggested, self._current, self.placeholder = [], [], None, placeholder
        self.update()

    def formats(self) -> list[str]:
        return [o.fmt for o in self.options]

    def current(self) -> str | None:
        return self._current

    def set_current(self, fmt: str) -> None:
        if fmt in self.formats() and fmt != self._current:
            self._current = fmt
            self.update()
            self.changed.emit(fmt)

    # -- popup

    def showPopup(self) -> None:
        if not self.options or not self.isEnabled():
            return
        self.popup = FormatPopup(self)
        self.popup.picked.connect(self.set_current)
        self.popup.closed.connect(lambda: self._set_open(False))
        self._set_open(True)
        self.popup.open_below(self)

    def _set_open(self, on: bool) -> None:
        self.setProperty("open", on)
        self.style().unpolish(self)
        self.style().polish(self)

    # -- drawing: bold extension, its full name in grey, a chevron

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # the frame from the stylesheet; the text is ours
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(12, 0, -34, 0)
        option = next((o for o in self.options if o.fmt == self._current), None)
        muted, text = QColor(THEME["muted"]), QColor(THEME["text"])
        if not self.isEnabled():
            text = muted
        bold = QFont(self.font())
        bold.setWeight(QFont.DemiBold)
        if option:
            p.setFont(bold)
            p.setPen(text)
            ext = option.fmt.upper()
            p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, ext)
            if option.name:
                x = QFontMetrics(bold).horizontalAdvance(ext) + 10
                p.setFont(self.font())
                p.setPen(muted)
                rest = r.adjusted(x, 0, 0, 0)
                p.drawText(rest, Qt.AlignVCenter | Qt.AlignLeft,
                           QFontMetrics(self.font()).elidedText(option.name, Qt.ElideRight, rest.width()))
        else:
            p.setPen(muted)
            p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, self.placeholder)
        # chevron
        cx, cy = self.width() - 20, self.height() / 2
        pen = QPen(muted, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPolyline([QPointF(cx - 4.5, cy - 2), QPointF(cx, cy + 2.5), QPointF(cx + 4.5, cy - 2)])
        p.end()


class FormatPopup(QWidget):
    """The panel under the picker: search, suggestions, then a grid of formats per kind."""
    picked = Signal(str)
    closed = Signal()
    COLUMNS = 4

    def __init__(self, picker: FormatPicker):
        super().__init__(picker, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.picker = picker
        self.chips: list[QPushButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 14)  # room for the shadow
        frame = QFrame()
        frame.setObjectName("popup")
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 110))
        frame.setGraphicsEffect(shadow)
        outer.addWidget(frame)

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {len(picker.options)} formats…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.rebuild)
        self.search.installEventFilter(self)
        lay.addWidget(self.search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)

        if any(o.needs for o in picker.options):
            legend = QLabel("Dashed formats need a free tool, installed once when you pick them.")
            legend.setObjectName("legend")
            legend.setWordWrap(True)
            lay.addWidget(legend)
        self.rebuild("")

    # -- content

    def rebuild(self, query: str) -> None:
        q = query.strip().lower().lstrip(".")
        options = self.picker.options
        if q:
            options = [o for o in options if q in o.fmt or q in o.name.lower() or q in o.kind.lower()]
        sections: list[tuple[str, list[Option]]] = []
        if not q and self.picker.suggested:
            by_fmt = {o.fmt: o for o in options}
            sections.append(("Suggested", [by_fmt[s] for s in self.picker.suggested]))
        kinds = list(dict.fromkeys(o.kind for o in options))
        for kind in kinds:
            sections.append((kind, sorted((o for o in options if o.kind == kind), key=lambda o: o.fmt)))

        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 4, 0)
        col.setSpacing(6)
        self.chips = []
        for title, opts in sections:
            head = QLabel(title.upper())
            head.setObjectName("section")
            col.addWidget(head)
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, o in enumerate(opts):
                grid.addWidget(self._chip(o), i // self.COLUMNS, i % self.COLUMNS)
            for c in range(self.COLUMNS):
                grid.setColumnStretch(c, 1)
            col.addLayout(grid)
            col.addSpacing(6)
        if not sections:
            none = QLabel(f"Nothing matches “{query.strip()}”")
            none.setObjectName("empty")
            none.setAlignment(Qt.AlignCenter)
            col.addWidget(none)
        col.addStretch()
        self.scroll.setWidget(body)
        if getattr(self, "anchor", None) is not None:
            self._place()

    def _chip(self, o: Option) -> QPushButton:
        chip = QPushButton(o.fmt.upper())
        chip.setObjectName("chip")
        chip.setCursor(Qt.PointingHandCursor)
        chip.setProperty("selected", o.fmt == self.picker.current())
        chip.setProperty("needs", bool(o.needs))
        tip = o.name or o.fmt.upper()
        if o.needs:
            tip += f"\nNeeds {' and '.join(o.needs)} (free, installed once)"
        chip.setToolTip(tip)
        chip.setProperty("fmt", o.fmt)
        chip.clicked.connect(lambda _=False, f=o.fmt: self._pick(f))
        chip.installEventFilter(self)
        self.chips.append(chip)
        return chip

    def _pick(self, fmt: str) -> None:
        self.picked.emit(fmt)
        self.close()

    # -- placement

    MAX_HEIGHT = 420

    def open_below(self, anchor: QWidget) -> None:
        self.anchor = anchor
        self.upwards = None  # decided once, so the panel doesn't jump sides while you type
        self._place()
        self.show()
        self.search.setFocus()

    def _place(self) -> None:
        """Fit the panel to its content (up to MAX_HEIGHT) and keep it against the picker:
        below it, or above when the screen has no room below."""
        anchor = self.anchor
        width = max(anchor.width() + 20, 340)
        self.layout().activate()
        chrome = self.height() - self.scroll.viewport().height() if self.isVisible() else 0
        if not chrome:
            frame = self.layout().itemAt(0).widget().layout()
            chrome = (frame.contentsMargins().top() + frame.contentsMargins().bottom()
                      + self.layout().contentsMargins().top() + self.layout().contentsMargins().bottom()
                      + sum(frame.itemAt(i).widget().sizeHint().height() + frame.spacing()
                            for i in range(frame.count()) if frame.itemAt(i).widget() is not self.scroll))
        content = self.scroll.widget().sizeHint().height()
        height = max(min(chrome + content + 4, self.MAX_HEIGHT), self.layout().minimumSize().height())
        screen = anchor.screen().availableGeometry()
        top_below = anchor.mapToGlobal(QPoint(0, anchor.height() - 2)).y()
        if self.upwards is None:
            self.upwards = top_below + self.MAX_HEIGHT > screen.bottom()
        y = anchor.mapToGlobal(QPoint(0, 8)).y() - height if self.upwards else top_below
        x = anchor.mapToGlobal(QPoint(-10, 0)).x()
        x = max(screen.left(), min(x, screen.right() - width))
        self.setGeometry(x, y, width, height)

    # -- keyboard: type to filter, Enter picks, arrows move through the grid, Esc closes

    def eventFilter(self, obj, event) -> bool:
        if event.type() != event.Type.KeyPress:
            return False
        key = event.key()
        visible = self.chips
        if obj is self.search:
            if key in (Qt.Key_Return, Qt.Key_Enter) and visible:
                self._pick(visible[0].property("fmt"))
                return True
            if key == Qt.Key_Down and visible:
                visible[0].setFocus()
                return True
            return False
        if obj in visible:
            i = visible.index(obj)
            step = {Qt.Key_Right: 1, Qt.Key_Left: -1, Qt.Key_Down: self.COLUMNS, Qt.Key_Up: -self.COLUMNS}.get(key)
            if step is not None:
                j = i + step
                if j < 0:
                    self.search.setFocus()
                else:
                    visible[min(j, len(visible) - 1)].setFocus()
                    self.scroll.ensureWidgetVisible(visible[min(j, len(visible) - 1)], 0, 30)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self._pick(obj.property("fmt"))
                return True
            if event.text() and event.text().isprintable():  # typing anywhere goes to the search box
                self.search.setFocus()
                self.search.insert(event.text())
                return True
        return False

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        self.closed.emit()
        super().hideEvent(event)


class EnginesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Engines")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        intro = QLabel("ConvertAll uses these free tools for some formats. "
                       "Missing ones are installed for you when you first need them.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        lay.addLayout(grid)
        self.jobs: list[InstallJob] = []
        for row, (eng, path) in enumerate(engines.status()):
            grid.addWidget(QLabel(f"<b>{eng.name}</b>"), row, 0)
            if path:
                st = QLabel("Installed")
                st.setToolTip(path)
                grid.addWidget(st, row, 1)
            else:
                btn = QPushButton(f"Install ({eng.size})")
                btn.clicked.connect(lambda _=False, k=eng.key, b=btn: self._install(k, b))
                grid.addWidget(btn, row, 1)

    def _install(self, key: str, btn: QPushButton) -> None:
        btn.setEnabled(False)
        btn.setText("Installing…")
        job = InstallJob(key)
        job.finished_ok.connect(lambda ok, err: btn.setText("Installed" if ok else (err or "Failed")))
        self.jobs.append(job)
        job.start()


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ConvertAll")
        self.setWindowIcon(QIcon(str(ASSETS / "icon.png")))
        self.resize(440, 470)
        self.setMinimumSize(380, 430)
        self.settings = QSettings("ConvertAll", "ConvertAll")
        self.files: list[Path] = []
        self.fmts: list[str] = []
        self.routes: dict[str, list[registry.Route]] = {}
        self.outputs: list[Path] = []
        self.job: Job | None = None
        self.last_add = 0.0
        self.pending_extract: list[Path] = []
        self.extract_timer = QTimer(self)
        self.extract_timer.setSingleShot(True)
        self.extract_timer.setInterval(EXTRACT_SETTLE_MS)
        self.extract_timer.timeout.connect(self.extract_pending)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("ConvertAll")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch()
        menu_btn = QToolButton()
        menu_btn.setText("⋯")
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        menu.addAction("Engines…", lambda: EnginesDialog(self).exec())
        self.ctx_action = QAction(self)
        self.ctx_action.triggered.connect(self.toggle_context_menu)
        menu.addAction(self.ctx_action)
        menu.addSeparator()
        menu.addAction("About ConvertAll", self.about)
        menu.aboutToShow.connect(self._refresh_ctx_label)
        menu_btn.setMenu(menu)
        head.addWidget(menu_btn)
        root.addLayout(head)

        self.drop = DropZone()
        self.drop.files_dropped.connect(self.set_files)
        root.addWidget(self.drop, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.picker = FormatPicker()
        self.picker.setEnabled(False)
        row.addWidget(self.picker, 1)
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setEnabled(False)
        self.convert_btn.clicked.connect(self.start_convert)
        row.addWidget(self.convert_btn)
        root.addLayout(row)

        self.extract_btn = QPushButton("Extract here")
        self.extract_btn.clicked.connect(self.start_extract)
        self.extract_btn.hide()
        root.addWidget(self.extract_btn)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        root.addWidget(self.bar)

        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        self.show_btn = QPushButton("Show in folder")
        self.show_btn.setObjectName("link")
        self.show_btn.setCursor(Qt.PointingHandCursor)
        self.show_btn.clicked.connect(lambda: self.outputs and reveal(self.outputs[0]))
        self.show_btn.hide()
        foot.addWidget(self.show_btn, 0, Qt.AlignTop)
        root.addLayout(foot)

    # ------------------------------------------------ files and formats

    def add_files_from_other_instance(self, paths: list[Path], extract: bool = False) -> None:
        """Explorer launches one process per selected file; gather them into one batch."""
        now = time.monotonic()
        if extract:
            # extract once the burst of processes has settled (each arrival restarts the wait)
            self.pending_extract = list(dict.fromkeys(self.pending_extract + paths))
            self.extract_timer.start()
        else:
            merged = self.files + paths if now - self.last_add < 2 and not self.job else paths
            self.set_files(list(dict.fromkeys(merged)))
        self.last_add = now
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def extract_pending(self) -> None:
        if self.job or not self.pending_extract:
            return  # job_done comes back for them
        paths, self.pending_extract = self.pending_extract, []
        self.set_files(paths)
        if not self.files:
            return
        if all(pipeline.can_extract(f) for f in self.fmts):
            self.start_extract()
        else:
            odd = next(p for p, f in zip(self.files, self.fmts) if not pipeline.can_extract(f))
            self.set_status(f"{odd.name} isn't an archive ConvertAll can extract", "error")

    def set_files(self, paths: list[Path]) -> None:
        if self.job:
            return
        paths = [p for p in paths if p.exists()]
        if not paths:
            return
        self.files = paths
        self.fmts = [detect(p) for p in paths]
        engines.refresh()  # pick up engines installed since the last drop
        self.drop.show_files(paths, self.fmts)
        self.routes = registry.common_targets(self.fmts)
        self.fill_picker()
        self.extract_btn.setVisible(all(pipeline.can_extract(f) for f in self.fmts))
        self.set_status("")
        self.show_btn.hide()
        self.bar.hide()

    def fill_picker(self) -> None:
        has_any = bool(self.routes)
        self.picker.setEnabled(has_any)
        self.convert_btn.setEnabled(has_any)
        if not has_any:
            self.picker.clear("No conversions for this file")
            return
        own = category(self.fmts[0])
        kind_order = {c: i for i, c in enumerate(sorted(CATEGORIES, key=lambda c: c != own))}  # own kind first
        options = []
        for dst in sorted(self.routes, key=lambda d: (kind_order.get(category(d), 99), d)):
            name = label(dst)
            needs = list(dict.fromkeys(engines.ENGINES[e].name for r in self.routes[dst] for e in r.missing_engines))
            options.append(Option(dst, category(dst), "" if name.upper() == dst.upper() else name, needs))
        remembered = self.settings.value(f"last/{self.fmts[0]}", "")
        common = suggest(self.fmts[0], self.routes)
        suggested = [f for f in dict.fromkeys([remembered, common]) if f in self.routes]
        self.picker.set_options(options, self.preselect() or options[0].fmt, suggested)

    def preselect(self) -> str | None:
        """What this user last turned this kind of file into, else what most people do with it."""
        remembered = self.settings.value(f"last/{self.fmts[0]}", "")
        if remembered in self.routes:
            return remembered
        return suggest(self.fmts[0], self.routes)

    # ------------------------------------------------ running

    def start_convert(self) -> None:
        target = self.picker.current()
        if not target:
            return
        self.settings.setValue(f"last/{self.fmts[0]}", target)
        missing = list(dict.fromkeys(e for r in self.routes[target] for e in r.missing_engines))
        if missing and not self.confirm_install(missing):
            return
        self.run_job(Job(self.files, target, missing))

    def start_extract(self) -> None:
        needs_7zip = any(f not in NATIVE_EXTRACT for f in self.fmts)
        missing = ["7zip"] if needs_7zip and not engines.available("7zip") else []
        if missing and not self.confirm_install(missing):
            return
        self.run_job(Job(self.files, None, missing))

    def confirm_install(self, keys: list[str]) -> bool:
        engs = [engines.ENGINES[k] for k in keys]
        names = " and ".join(f"{e.name} ({e.size})" for e in engs)
        box = QMessageBox(self)
        box.setWindowTitle("One-time setup")
        box.setIcon(QMessageBox.Question)
        box.setText(f"This conversion needs {names}.")
        box.setInformativeText("It's free and installs once, right from here. Install it now?")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("Install")
        return box.exec() == QMessageBox.Yes

    def run_job(self, job: Job) -> None:
        self.job = job
        for w in (self.picker, self.convert_btn, self.extract_btn):
            w.setEnabled(False)
        self.show_btn.hide()
        self.bar.setRange(0, 0)
        self.bar.show()
        job.progress.connect(lambda m: self.set_status(m))
        job.done.connect(self.job_done)
        job.start()

    def job_done(self, outputs: list[Path], errors: list[str]) -> None:
        self.job = None
        self.outputs = outputs
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.bar.hide()
        if self.files:
            self.routes = registry.common_targets(self.fmts)  # engines may have changed
            self.fill_picker()
            self.extract_btn.setEnabled(True)
        if errors:
            more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
            self.set_status(errors[0] + more, "error")
            self.status.setToolTip("\n".join(errors))
        elif len(outputs) == 1:
            self.set_status(f"Saved {outputs[0].name}", "ok")
        else:
            self.set_status(f"Done · {len(outputs)} files", "ok")
        self.show_btn.setVisible(bool(outputs))
        if self.pending_extract:  # more archives were right-clicked while this ran
            self.extract_timer.start()

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        self.status.setToolTip("")
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # ------------------------------------------------ menu actions

    def _refresh_ctx_label(self) -> None:
        self.ctx_action.setText("Remove from right-click menu" if context_menu_installed()
                                else "Add to right-click menu")

    def toggle_context_menu(self) -> None:
        try:
            if context_menu_installed():
                remove_context_menu()
                self.set_status("Removed from the right-click menu", "ok")
            else:
                install_context_menu()
                self.set_status("Added “Convert with ConvertAll” to the right-click menu, and "
                                "“Extract with ConvertAll” on archives "
                                "(Windows 11: under Show more options)", "ok")
        except OSError as exc:
            self.set_status(f"Couldn't change the right-click menu: {exc}", "error")

    def about(self) -> None:
        QMessageBox.about(self, "ConvertAll", f"<b>ConvertAll {__version__}</b><br>"
                          "Convert, compress or extract any file.<br><br>"
                          "Uses Pillow, PyMuPDF, py7zr, fontTools, trimesh, gmsh, ezdxf, pydicom, meshport, "
                          "packport, vtracer, pysubs2, pycdlib and, when needed, FFmpeg, 7-Zip, LibreOffice, "
                          "Calibre, ImageMagick, Blender, Pandoc, DjVuLibre and Ghostscript.")


# ---------------------------------------------------------------- Explorer right-click menu
# "Convert with ConvertAll" on every file and folder. Archives get "Extract with ConvertAll"
# instead: a verb under SystemFileAssociations\.<ext> with the same key name as the one under *
# replaces it for that extension, so Explorer shows one entry, never both.

_STAR_KEY = r"Software\Classes\*\shell\ConvertAll"
_DIR_KEY = r"Software\Classes\Directory\shell\ConvertAll"
_SFA = r"Software\Classes\SystemFileAssociations"
_VERB = r"shell\ConvertAll"


def extract_extensions() -> list[str]:
    """Extensions right-click extracts. Comics and other kinds that happen to be archives keep
    Convert: people turn a .cbz into a PDF far more often than they unpack it."""
    from .converters.archives import EXTRACTABLE
    fmts = {f for f in EXTRACTABLE if category(f) == "Archive"}
    exts = {f.rsplit(".", 1)[-1] for f in fmts} | {a for a, f in ALIASES.items() if f in fmts}
    return sorted(exts)


def _launch_command(*flags: str) -> str:
    args = "".join(f"{f} " for f in flags)
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {args}"%1"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" -m convertall --gui {args}"%1"'


def _icon_path() -> str:
    return sys.executable if getattr(sys, "frozen", False) else str(ASSETS / "icon.ico")


def context_menu_installed() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STAR_KEY))
        return True
    except OSError:
        return False


def registered_version() -> str | None:
    """The ConvertAll version that registered the right-click menu (None before 1.1)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STAR_KEY) as k:
            return winreg.QueryValueEx(k, "Version")[0]
    except OSError:
        return None


def _version_tuple(v: str | None) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in (v or "0").split("."))
    except ValueError:
        return (0,)


def context_menu_outdated() -> bool:
    return context_menu_installed() and _version_tuple(registered_version()) < _version_tuple(__version__)


def _set_verb(key: str, text: str, command: str) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, text)
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, _icon_path())
        winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)


def install_context_menu() -> None:
    import winreg
    remove_context_menu()  # also drops extensions an older build registered
    for key in (_STAR_KEY, _DIR_KEY):
        _set_verb(key, "Convert with ConvertAll", _launch_command())
    for ext in extract_extensions():
        _set_verb(rf"{_SFA}\.{ext}\{_VERB}", "Extract with ConvertAll", _launch_command("--extract"))
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STAR_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Version", 0, winreg.REG_SZ, __version__)


def _delete(key: str, only_if_empty: bool = False) -> None:
    import winreg
    try:
        if only_if_empty:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                subkeys, values, _ = winreg.QueryInfoKey(k)
            if subkeys or values:
                return
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except FileNotFoundError:
        pass


def remove_context_menu() -> None:
    import winreg
    for key in (_STAR_KEY, _DIR_KEY):
        _delete(key + r"\command")
        _delete(key)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SFA) as k:
            exts = [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]
    except FileNotFoundError:
        exts = []
    for ext in exts:
        base = rf"{_SFA}\{ext}"
        _delete(rf"{base}\{_VERB}\command")
        _delete(rf"{base}\{_VERB}")
        _delete(rf"{base}\shell", only_if_empty=True)  # leave other apps' entries alone
        _delete(base, only_if_empty=True)


# ---------------------------------------------------------------- entry point

EXTRACT_MARKER = "--extract"  # first line of a forwarded message: extract these, don't convert


def _forward_to_running(files: list[str], extract: bool = False, server: str = SERVER_NAME) -> bool:
    """If ConvertAll is already open, hand it our files and let it handle them."""
    sock = QLocalSocket()
    sock.connectToServer(server)
    if not sock.waitForConnected(300):
        return False
    sock.write("\n".join([EXTRACT_MARKER] * extract + files).encode("utf-8"))
    while sock.bytesToWrite() and sock.waitForBytesWritten(1000):
        pass  # a long list goes out in several writes; this process may exit right after
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.UnconnectedState:
        sock.waitForDisconnected(1000)
    return True


def parse_message(data: str) -> tuple[list[Path], bool]:
    lines = [ln for ln in data.splitlines() if ln.strip()]
    extract = bool(lines) and lines[0] == EXTRACT_MARKER
    return [Path(p) for p in lines[extract:]], extract


def listen(server: QLocalServer, handle) -> None:
    """Call handle(message) for each message another ConvertAll process sends. A long file list
    can arrive in pieces, so each is handled once its sender hangs up."""
    def on_connection():
        conn = server.nextPendingConnection()
        buf = bytearray()

        def read():
            buf.extend(bytes(conn.readAll()))

        def done():
            if conn.property("handled"):
                return
            conn.setProperty("handled", True)
            read()
            handle(buf.decode("utf-8", "replace"))
            conn.deleteLater()
        conn.readyRead.connect(read)
        conn.disconnected.connect(done)
        if conn.state() == QLocalSocket.UnconnectedState:  # it was over before we got here
            done()
    server.newConnection.connect(on_connection)


def main(argv: list[str] | None = None) -> int:
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if a != "--gui"]
    extract = EXTRACT_MARKER in argv
    files = [str(Path(a).resolve()) for a in argv if a != EXTRACT_MARKER]
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ConvertAll")
    app.setStyle("Fusion")
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ConvertAll.ConvertAll")
    # One window: the first process to take the lock serves; later ones hand over their files.
    lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{SERVER_NAME}.lock"))
    if not lock.tryLock(0):
        for _ in range(40):
            if _forward_to_running(files, extract):
                return 0
            time.sleep(0.1)

    # An update brings new right-click entries; refresh a menu an older build registered.
    # Only the installed app does this, so running from source never repoints the menu.
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        try:
            if context_menu_outdated():
                install_context_menu()
        except OSError:
            pass

    apply_theme(app)
    app.styleHints().colorSchemeChanged.connect(lambda _: apply_theme(app))
    win = Window()

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_message(text: str):
        paths, extract_them = parse_message(text)
        if paths:
            win.add_files_from_other_instance(paths, extract_them)
        else:
            win.raise_()
            win.activateWindow()
    listen(server, on_message)

    win.show()
    if files:
        QTimer.singleShot(0, lambda: win.add_files_from_other_instance([Path(f) for f in files], extract))
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
