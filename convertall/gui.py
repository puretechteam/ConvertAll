"""ConvertAll window: drop files, pick a format, convert."""

from __future__ import annotations

import getpass
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QFontMetrics, QGuiApplication, QIcon, QStandardItem, QStandardItemModel
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QProgressBar, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from . import __version__, engines, pipeline, registry
from .converters.archives import NATIVE_EXTRACT
from .detect import detect
from .errors import ConversionError
from .formats import CATEGORIES, category, describe, label, suggest

ASSETS = Path(__file__).resolve().parent / "assets"  # PyInstaller places them here too
SERVER_NAME = f"ConvertAll-{getpass.getuser()}"

LIGHT = dict(bg="#f7f7f8", surface="#ffffff", text="#18181b", muted="#71717a", border="#d4d4d8",
             accent="#6366f1", accent_text="#ffffff", accent_soft="#eef2ff", error="#dc2626", ok="#16a34a")
DARK = dict(bg="#18181b", surface="#232326", text="#f4f4f5", muted="#a1a1aa", border="#3f3f46",
            accent="#818cf8", accent_text="#0b0b10", accent_soft="#26264a", error="#f87171", ok="#4ade80")

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
QComboBox {{ combobox-popup: 0; background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 7px 10px; min-height: 20px; }}
QComboBox:disabled {{ color: {muted}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; selection-background-color: {accent_soft}; selection-color: {text}; outline: 0; padding: 4px; }}
QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 8px 16px; }}
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


def is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply_theme(app: QApplication) -> None:
    app.setStyleSheet(QSS.format(**(DARK if is_dark() else LIGHT)))


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
            except ConversionError as exc:
                errors.append(str(exc))
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
        self.done.emit(outputs, errors)


class InstallJob(QThread):
    finished_ok = Signal(bool, str)

    def __init__(self, key: str):
        super().__init__()
        self.key = key

    def run(self) -> None:
        try:
            self.finished_ok.emit(engines.install(self.key), "")
        except ConversionError as exc:
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


class EnginesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Engines")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        intro = QLabel("ConvertAll uses these free tools for some formats. "
                       "Missing ones are installed with winget when you first need them.")
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
        self.combo = QComboBox()
        self.combo.setMaxVisibleItems(18)
        self.combo.setEnabled(False)
        self.combo.addItem("Choose a format")
        row.addWidget(self.combo, 1)
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

    def add_files_from_other_instance(self, paths: list[Path]) -> None:
        """Explorer launches one process per selected file; gather them into one batch."""
        now = time.monotonic()
        merged = self.files + paths if now - self.last_add < 2 and not self.job else paths
        self.set_files(list(dict.fromkeys(merged)))
        self.last_add = now
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

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
        self.fill_combo()
        self.extract_btn.setVisible(all(pipeline.can_extract(f) for f in self.fmts))
        self.set_status("")
        self.show_btn.hide()
        self.bar.hide()

    def fill_combo(self) -> None:
        model = QStandardItemModel()
        by_cat: dict[str, list[str]] = {}
        for dst in self.routes:
            by_cat.setdefault(category(dst), []).append(dst)
        own = category(self.fmts[0])
        for cat in sorted(CATEGORIES, key=lambda c: c != own):  # the file's own kind first
            if cat not in by_cat:
                continue
            header = QStandardItem(cat.upper())
            header.setFlags(Qt.NoItemFlags)
            font = header.font()
            font.setBold(True)
            font.setPointSizeF(font.pointSizeF() * 0.85)
            header.setFont(font)
            model.appendRow(header)
            for dst in sorted(by_cat[cat]):
                missing = {e for r in self.routes[dst] for e in r.missing_engines}
                lab = label(dst)
                text = f"{dst.upper()}" + (f"   {lab}" if lab.upper() != dst.upper() else "")
                if missing:
                    text += "   · needs " + ", ".join(engines.ENGINES[k].name for k in missing)
                item = QStandardItem(text)
                item.setData(dst, Qt.UserRole)
                model.appendRow(item)
        self.combo.setModel(model)
        has_any = bool(self.routes)
        self.combo.setEnabled(has_any)
        self.convert_btn.setEnabled(has_any)
        if not has_any:
            self.combo.clear()
            self.combo.addItem("No conversions for this file")
            return
        rows = {model.item(i).data(Qt.UserRole): i for i in range(model.rowCount())}
        rows.pop(None, None)
        self.combo.setCurrentIndex(rows.get(self.preselect(), min(rows.values())))

    def preselect(self) -> str | None:
        """What this user last turned this kind of file into, else what most people do with it."""
        remembered = self.settings.value(f"last/{self.fmts[0]}", "")
        if remembered in self.routes:
            return remembered
        return suggest(self.fmts[0], self.routes)

    # ------------------------------------------------ running

    def start_convert(self) -> None:
        target = self.combo.currentData(Qt.UserRole)
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
        box.setInformativeText("It's free and installs once with winget. Install it now?")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("Install")
        return box.exec() == QMessageBox.Yes

    def run_job(self, job: Job) -> None:
        self.job = job
        for w in (self.combo, self.convert_btn, self.extract_btn):
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
            self.fill_combo()
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
                self.set_status("Added “Convert with ConvertAll” to the right-click menu "
                                "(Windows 11: under Show more options)", "ok")
        except OSError as exc:
            self.set_status(f"Couldn't change the right-click menu: {exc}", "error")

    def about(self) -> None:
        QMessageBox.about(self, "ConvertAll", f"<b>ConvertAll {__version__}</b><br>"
                          "Convert, compress or extract any file.<br><br>"
                          "Uses Pillow, PyMuPDF, py7zr, fontTools, trimesh, gmsh, ezdxf, pydicom and, "
                          "when needed, FFmpeg, 7-Zip, LibreOffice, Calibre, ImageMagick and Blender.")


# ---------------------------------------------------------------- Explorer right-click menu

_CTX_KEYS = (r"Software\Classes\*\shell\ConvertAll", r"Software\Classes\Directory\shell\ConvertAll")


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" -m convertall --gui "%1"'


def _icon_path() -> str:
    return sys.executable if getattr(sys, "frozen", False) else str(ASSETS / "icon.ico")


def context_menu_installed() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CTX_KEYS[0]))
        return True
    except OSError:
        return False


def install_context_menu() -> None:
    import winreg
    for key in _CTX_KEYS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, "Convert with ConvertAll")
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, _icon_path())
            winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _launch_command())


def remove_context_menu() -> None:
    import winreg
    for key in _CTX_KEYS:
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------- entry point

def _forward_to_running(files: list[str]) -> bool:
    """If ConvertAll is already open, hand it our files and let it handle them."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write("\n".join(files).encode("utf-8"))
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main(argv: list[str] | None = None) -> int:
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if a != "--gui"]
    files = [str(Path(a).resolve()) for a in argv]
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
            if _forward_to_running(files):
                return 0
            time.sleep(0.1)

    apply_theme(app)
    app.styleHints().colorSchemeChanged.connect(lambda _: apply_theme(app))
    win = Window()

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_connection():
        conn = server.nextPendingConnection()

        def read():
            data = bytes(conn.readAll()).decode("utf-8")
            paths = [Path(p) for p in data.splitlines() if p.strip()]
            if paths:
                win.add_files_from_other_instance(paths)
            else:
                win.raise_()
                win.activateWindow()
        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)
    server.newConnection.connect(on_connection)

    win.show()
    if files:
        QTimer.singleShot(0, lambda: win.add_files_from_other_instance([Path(f) for f in files]))
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
