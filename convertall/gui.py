"""ConvertAll window: drop files, pick a format, convert."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, cancel, engines, options, pipeline, registry
from .assurance import Report, show
from .detect import detect
from .errors import ConversionError
from .formats import (
    ALIASES,
    CATEGORIES,
    FORMATS,
    category,
    describe,
    label,
    suggest,
    viewable,
)
from .instance import EXTRACT_MARKER, SERVER_NAME, VIEW_MARKER, parse_message

ASSETS = Path(__file__).resolve().parent / "assets"  # PyInstaller places them here too
DISCORD = "https://discord.gg/dRMRGCG9Fk"  # help, ideas and chat
ENGINE_RECHECK_S = 10  # a drop looks for newly installed engines at most this often (it walks PATH)
NOTES_SETTLE_MS = 120  # the format list's notes follow a setting once it's been still this long
EXTRACT_SETTLE_MS = 1000  # right-click Extract on several archives: wait for all their processes

LIGHT = {"bg": "#f7f7f8", "surface": "#ffffff", "text": "#18181b", "muted": "#71717a", "border": "#d4d4d8",
         "accent": "#6366f1", "accent_text": "#ffffff", "accent_soft": "#eef2ff", "error": "#dc2626", "ok": "#16a34a",
         "warn": "#b45309"}
DARK = {"bg": "#18181b", "surface": "#232326", "text": "#f4f4f5", "muted": "#a1a1aa", "border": "#3f3f46",
        "accent": "#818cf8", "accent_text": "#0b0b10", "accent_soft": "#26264a", "error": "#f87171", "ok": "#4ade80",
        "warn": "#fbbf24"}

CONTROL = 38  # height of the picker, Convert and other main-window buttons
FIELD = 32    # height of a setting's box

QSS = """
QWidget {{ background: {bg}; color: {text}; font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 6px; padding: 6px 8px; }}
#title {{ font-size: 15pt; font-weight: 600; }}
#drop {{ background: {surface}; border: 2px dashed {border}; border-radius: 16px; }}
#drop[active="true"] {{ border-color: {accent}; background: {accent_soft}; }}
#drop QLabel, #drop QWidget#badge {{ background: transparent; }}
#dropMain {{ font-size: 12pt; font-weight: 600; }}
#muted, #dropSub, #note {{ color: {muted}; }}
#status {{ font-weight: 600; }}
#status[state="error"] {{ color: {error}; }}
#status[state="ok"] {{ color: {ok}; }}
#status[state="warn"] {{ color: {warn}; }}
#options {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
#options QLabel, #options QWidget#optionsBody {{ background: transparent; }}
#options QLabel {{ color: {muted}; }}
#options QComboBox {{ background: {bg}; }}
#options QLabel#value {{ color: {text}; font-weight: 600; }}
#options QLabel#value[auto="true"] {{ color: {muted}; font-weight: 400; }}
QPushButton#pill {{ background: {bg}; border: 1px solid {border}; border-radius: 13px; padding: 0 12px; min-height: 24px; max-height: 24px; font-size: 9pt; }}
QPushButton#pill:hover {{ border-color: {accent}; }}
QPushButton#pill:checked {{ background: {accent_soft}; border-color: {accent}; color: {accent}; }}
QPushButton#pill[add="true"] {{ background: transparent; border-style: dashed; color: {muted}; }}
QPushButton#pill[add="true"]:hover {{ color: {accent}; border-color: {accent}; }}
QComboBox QLineEdit {{ background: transparent; border: none; padding: 0; }}
#divider {{ background: {border}; border: none; }}
#details QLabel, #details QWidget#card {{ background: transparent; }}
#details QFrame#card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
#details QLabel#cardTitle {{ font-weight: 600; }}
#details QLabel#cell {{ padding: 3px 0; }}
#details QLabel#mark {{ border-radius: 9px; padding: 1px 8px; font-size: 8.5pt; font-weight: 600; }}
#details QLabel#mark[state="same"] {{ color: {muted}; background: {bg}; }}
#details QLabel#mark[state="changed"], #details QLabel#mark[state="expected"] {{ color: {accent}; background: {accent_soft}; }}
#details QLabel#mark[state="bad"] {{ color: {bg}; background: {warn}; }}
#checkBad {{ color: {warn}; }}
#ok {{ color: {ok}; }}
QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 0 16px; min-height: 30px; }}
QPushButton#picker[open="true"] {{ border-color: {accent}; }}
QLineEdit {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 6px 10px; selection-background-color: {accent}; selection-color: {accent_text}; }}
QLineEdit:focus {{ border-color: {accent}; }}
QComboBox {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 0 10px; min-height: 28px; }}
QComboBox:hover, QComboBox:focus, QComboBox:on {{ border-color: {accent}; }}
QComboBox:disabled {{ color: {muted}; }}
QComboBox::drop-down {{ border: none; width: 30px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{icon_chevron}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; padding: 4px; outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 0 8px; border-radius: 6px; color: {text}; }}
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{ background: {accent_soft}; color: {text}; }}
QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {accent}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QMessageBox QPushButton, QDialogButtonBox QPushButton {{ min-width: 64px; }}
#popup {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
#popup QWidget {{ background: transparent; }}
#popup QLineEdit {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; padding: 7px 10px; }}
#popup QLineEdit:focus {{ border-color: {accent}; }}
#section {{ color: {muted}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#legend, #empty {{ color: {muted}; font-size: 8.5pt; }}
QPushButton#chip {{ background: {bg}; border: 1px solid {border}; border-radius: 7px; padding: 0; min-height: 30px; max-height: 30px; font-size: 9pt; font-weight: 600; }}
QPushButton#chip:hover, QPushButton#chip:focus {{ border-color: {accent}; outline: none; }}
QPushButton#chip[needs="true"] {{ color: {muted}; border-style: dashed; }}
QPushButton#chip[selected="true"] {{ background: {accent}; color: {accent_text}; border-color: {accent}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: none; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:checked {{ border-color: {accent}; color: {accent}; background: {accent_soft}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton#primary {{ background: {accent}; color: {accent_text}; border: none; font-weight: 600; }}
QPushButton#primary:disabled {{ background: {border}; color: {muted}; }}
QPushButton#link {{ background: transparent; border: none; color: {accent}; padding: 1px 0; min-height: 0; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QToolButton {{ background: transparent; border: none; font-size: 14pt; color: {muted}; padding: 0 6px; }}
QToolButton::menu-indicator {{ image: none; }}
QProgressBar {{ background: {border}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 7px 20px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
"""


THEME = dict(DARK)  # the palette in use, for widgets that paint themselves


def is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


# Small line icons the stylesheet uses (a dropdown's chevron), drawn in
# the theme's colors. PNG, at 1x and 2x: the app ships without Qt's SVG reader.
ICON_LINES = {
    "chevron": [((4, 6), (8, 10), (12, 6))],
}


def _theme_icons(color: str) -> dict[str, str]:
    folder = Path(tempfile.gettempdir()) / "ConvertAll-icons"
    folder.mkdir(exist_ok=True)
    paths = {}
    for name, lines in ICON_LINES.items():
        base = folder / f"{name}-{color.lstrip('#')}"
        for scale, suffix in ((1, ""), (2, "@2x")):
            target = base.with_name(base.name + suffix + ".png")
            if target.exists():
                continue
            img = QImage(16 * scale, 16 * scale, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(color), 1.6 * scale)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            for line in lines:
                p.drawPolyline([QPointF(x * scale, y * scale) for x, y in line])
            p.end()
            img.save(str(target))
        paths[f"icon_{name}"] = base.with_name(base.name + ".png").as_posix()
    return paths


def apply_theme(app: QApplication) -> None:
    THEME.update(DARK if is_dark() else LIGHT)
    pal = QPalette()
    roles = {"bg": (QPalette.Window, QPalette.AlternateBase), "surface": (QPalette.Base, QPalette.Button, QPalette.ToolTipBase),
             "text": (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.ToolTipText, QPalette.BrightText),
             "accent": (QPalette.Highlight, QPalette.Link, QPalette.LinkVisited), "accent_text": (QPalette.HighlightedText,),
             "muted": (QPalette.PlaceholderText,), "border": (QPalette.Mid, QPalette.Dark, QPalette.Shadow)}
    for key, rs in roles.items():  # dialogs and anything the stylesheet doesn't reach use the same colors
        for r in rs:
            pal.setColor(r, QColor(THEME[key]))
    for r in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, r, QColor(THEME["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS.format(**THEME, **_theme_icons(THEME["muted"])))
    viewer = sys.modules.get("convertall.viewer")  # 3D views paint their own background
    if viewer is not None:
        for w in app.allWidgets():
            if isinstance(w, viewer.ModelView):
                w.update()


def _set_open(button: QWidget, on: bool) -> None:
    """Keep a menu button highlighted while its menu is showing."""
    button.setProperty("open", on)
    button.update()


def reveal(path: Path) -> None:
    if sys.platform == "win32":
        explorer = Path(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe")
        subprocess.Popen([str(explorer), f"/select,{path}"])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


# ---------------------------------------------------------------- background jobs

class Job(QThread):
    """Installs any missing engines, then converts (or extracts) each file. cancel() stops it:
    the engine running is killed, the file it was on is left unwritten, the rest are skipped."""
    progress = Signal(str)
    done = Signal(list, list, list, list)  # outputs, errors, notes, reports (assurance.Report)

    def __init__(self, files: list[Path], target: str | None, install: list[str], settings: dict | None = None):
        super().__init__()
        self.files, self.target, self.install = files, target, install
        self.settings = settings or {}
        self.token = cancel.Token()

    def cancel(self) -> None:
        self.token.cancel()

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled

    def run(self) -> None:
        with cancel.using(self.token):
            self._run()

    def _run(self) -> None:
        outputs: list[Path] = []
        errors: list[str] = []
        notes: list[str] = []
        reports: list[Report] = []
        for key in self.install:
            if self.cancelled:  # an install is never cut short; the next one just doesn't start
                break
            name = engines.ENGINES[key].name
            self.progress.emit(f"Installing {name}… (this can take a few minutes)")
            try:
                if not engines.install(key):
                    errors.append(f"Couldn't install {name}")
            except Exception as exc:  # noqa: BLE001 - the window must always hear back
                errors.append(str(exc) if isinstance(exc, ConversionError) else f"Couldn't install {name}: {exc}")
        if errors or self.cancelled:
            self.done.emit(outputs, errors, notes, reports)
            return
        for i, f in enumerate(self.files, 1):
            if self.cancelled:
                break
            count = f" {i} of {len(self.files)}" if len(self.files) > 1 else ""
            self.progress.emit(f"{'Extracting' if self.target is None else 'Converting'}{count} · {f.name}")
            try:
                found: list[str] = []
                if self.target is None:
                    out = pipeline.extract(f, notes=found)
                else:
                    report = Report()
                    out = pipeline.convert(f, self.target, report=report, options=self.settings)
                    reports.append(report)
                    found = [report.summary()] if report.summary() else []
                outputs.append(out)
                notes += [f"{f.name}: {n}" for n in found]
            except cancel.Cancelled:
                break
            except (ConversionError, OSError) as exc:
                errors.append(f"{f.name}: {exc}")
            except Exception as exc:  # noqa: BLE001 - a surprise must not leave the window spinning forever
                errors.append(f"{f.name}: unexpected {type(exc).__name__}: {exc}")
        self.done.emit(outputs, errors, notes, reports)


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

class IconButton(QToolButton):
    """A small round-cornered button with an icon drawn in the theme's colors: "menu" (three
    lines) or "expand" (four corners pointing out). Drawn, not a font glyph, so it looks the
    same on every PC and follows light and dark mode."""

    def __init__(self, icon: str, tooltip: str, size: int = 32, filled: bool = False, parent=None):
        super().__init__(parent)
        self.icon, self.filled = icon, filled  # filled: a solid plate, for sitting on top of a 3D view
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover, down = self.underMouse(), self.isDown() or self.property("open") is True
        if self.filled or hover or down:
            fill = QColor(THEME["accent_soft"] if (hover or down) else THEME["bg"])
            if self.filled and not (hover or down):
                fill.setAlpha(225)
            p.setBrush(fill)
            p.setPen(QPen(QColor(THEME["accent"] if hover or down else THEME["border"]), 1))
            p.drawRoundedRect(r, 8, 8)
        color = QColor(THEME["accent"] if hover or down else THEME["text"])
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        if self.icon == "menu":
            half = self.width() * 0.22
            for dy in (-5.0, 0.0, 5.0):
                p.drawLine(QPointF(cx - half, cy + dy), QPointF(cx + half, cy + dy))
        else:  # expand: four corner marks pointing outward
            e, a = self.width() * 0.24, self.width() * 0.13  # reach of the corners, length of each arm
            path = QPainterPath()
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                corner = QPointF(cx + sx * e, cy + sy * e)
                path.moveTo(corner.x() - sx * a, corner.y())
                path.lineTo(corner)
                path.lineTo(corner.x(), corner.y() - sy * a)
            p.drawPath(path)
        p.end()


def file_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return ""


THUMB_MAX_BYTES = 300 * 2**20  # bigger pictures just get the badge
_THUMB_JOBS: set = set()  # a QThread must outlive its run, even if a newer file replaced it


def _thumbnail(path: Path, fmt: str, w: int, h: int) -> QImage | None:
    """A small picture of an image or a PDF's first page, or None."""
    if path.stat().st_size > THUMB_MAX_BYTES:
        return None
    if fmt == "pdf":
        import pymupdf
        with pymupdf.open(path) as doc:
            page = doc[0]
            zoom = min(w / page.rect.width, h / page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
    if category(fmt) != "Image" or fmt in ("svg", "eps", "ps", "ai", "emf", "wmf"):
        return None
    from PIL import Image, ImageOps

    if fmt in ("heic", "avif"):
        from .converters.images import enable_heif
        enable_heif()
    with Image.open(path) as img:
        img.draft("RGB", (w, h))  # JPEG: decode at a fraction of the size
        img = ImageOps.exif_transpose(img)
        img.thumbnail((w, h))
        img = img.convert("RGBA")
        return QImage(img.tobytes(), img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()


class ThumbJob(QThread):
    done = Signal(object, object)  # path, QImage or None

    def __init__(self, path: Path, fmt: str, size: tuple[int, int]):
        super().__init__()
        self.path, self.fmt, self.size = path, fmt, size

    def run(self) -> None:
        try:
            image = _thumbnail(self.path, self.fmt, *self.size)
        except Exception:  # noqa: BLE001 - no picture is fine: the badge stays
            image = None
        self.done.emit(self.path, image)


class Badge(QWidget):
    """What's in the drop zone, drawn: an arrow into a tray (nothing yet), a page with the
    extension on it (one file), pages stacked (several), or a small picture of the file."""
    THUMB = (240, 120)

    ICON = 76

    def __init__(self):
        super().__init__()
        self.setObjectName("badge")
        self.kind, self.text, self.picture = "empty", "", None
        self.setMinimumHeight(self.ICON)
        self.setMaximumHeight(self.ICON)

    def set(self, kind: str, text: str = "") -> None:
        self.kind, self.text, self.picture = kind, text, None
        self.setMinimumHeight(self.ICON)
        self.setMaximumHeight(self.ICON)
        self.update()

    def set_picture(self, image: QImage) -> None:
        """Shown up to THUMB, and smaller when the window is short (never under the file's name)."""
        self.picture = QPixmap.fromImage(image)
        self.picture.setDevicePixelRatio(max(1.0, image.width() / self.THUMB[0], image.height() / self.THUMB[1]))
        self.setMinimumHeight(48)
        self.setMaximumHeight(int(self.picture.deviceIndependentSize().height()) + 2)
        self.update()

    def sizeHint(self):
        return QSize(self.THUMB[0], self.maximumHeight())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        cx, cy = self.width() / 2, self.height() / 2
        accent, border, surface = QColor(THEME["accent"]), QColor(THEME["border"]), QColor(THEME["bg"])
        if self.picture is not None:
            size = self.picture.deviceIndependentSize()
            fit = min(1.0, (self.height() - 2) / size.height(), (self.width() - 2) / size.width())
            w, h = size.width() * fit, size.height() * fit
            r = QRectF(cx - w / 2, cy - h / 2, w, h)
            clip = QPainterPath()
            clip.addRoundedRect(r, 8, 8)
            p.setClipPath(clip)
            p.drawPixmap(r, self.picture, QRectF(self.picture.rect()))
            p.setClipping(False)
            p.setPen(QPen(border, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        elif self.kind == "empty":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(THEME["accent_soft"]))
            p.drawEllipse(QPointF(cx, cy), 30, 30)
            pen = QPen(accent, 2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(QPointF(cx, cy - 12), QPointF(cx, cy + 4))
            p.drawPolyline([QPointF(cx - 6, cy - 6), QPointF(cx, cy - 12), QPointF(cx + 6, cy - 6)])
            p.drawPolyline([QPointF(cx - 12, cy + 2), QPointF(cx - 12, cy + 11), QPointF(cx + 12, cy + 11),
                            QPointF(cx + 12, cy + 2)])
        else:
            w, h, fold = 50.0, 64.0, 13.0
            pages = 3 if self.kind == "many" else 1
            for i in reversed(range(pages)):  # the ones behind peek out to the upper right
                x, y = cx - w / 2 + i * 6, cy - h / 2 - i * 5
                page = QPainterPath()
                page.moveTo(x, y)
                page.lineTo(x + w - fold, y)
                page.lineTo(x + w, y + fold)
                page.lineTo(x + w, y + h)
                page.lineTo(x, y + h)
                page.closeSubpath()
                p.setBrush(surface)
                p.setPen(QPen(border, 1.5))
                p.drawPath(page)
                if i == 0:
                    corner = QPainterPath()
                    corner.moveTo(x + w - fold, y)
                    corner.lineTo(x + w - fold, y + fold)
                    corner.lineTo(x + w, y + fold)
                    p.drawPath(corner)
            font = QFont(self.font())
            font.setWeight(QFont.Bold)
            font.setPointSizeF(8.5 if len(self.text) <= 4 else 7)
            p.setFont(font)
            p.setPen(accent)
            p.drawText(QRectF(cx - w / 2, cy - 2, w, 22), Qt.AlignCenter, self.text)
        p.end()


class DropZone(QFrame):
    """Where files are dropped. One 3D model shows in it, live: drag to turn it. A picture or a
    PDF shows small; anything else as a page with its extension."""
    files_dropped = Signal(list)
    expand = Signal()  # open the 3D preview in its own window

    def __init__(self):
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(180)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(0)
        self.lay.addStretch(1)
        self.badge = Badge()
        self.lay.addWidget(self.badge)
        self.lay.addSpacing(12)
        self.main = QLabel("Drop files here")
        self.main.setObjectName("dropMain")
        self.sub = QLabel("or click to browse · folders work too")
        self.sub.setObjectName("dropSub")
        for w in (self.main, self.sub):
            w.setAlignment(Qt.AlignCenter)
            self.lay.addWidget(w)
        self.lay.addStretch(1)
        self.preview = None  # a viewer.ViewerPanel, made the first time a model is dropped
        self.expand_btn: QToolButton | None = None
        self.preview_fmt = ""
        self.thumb_for: Path | None = None

    def show_files(self, files: list[Path], fmts: list[str]) -> None:
        if len(files) == 1:
            metrics = QFontMetrics(self.main.font())
            self.main.setText(metrics.elidedText(files[0].name, Qt.ElideMiddle, max(self.width() - 40, 200)))
            self.main.setToolTip(str(files[0]))
            size = f" · {file_size(files[0].stat().st_size)}" if files[0].is_file() else ""
            self.sub.setText(describe(fmts[0]) + size)
            self.badge.set("file", fmts[0].upper() if files[0].is_file() else "DIR")
        else:
            self.main.setText(f"{len(files)} files")
            self.main.setToolTip("\n".join(str(f) for f in files[:30]))
            kinds = sorted({describe(f) for f in fmts})
            self.sub.setText(kinds[0] if len(kinds) == 1 else f"{len(kinds)} kinds of file")
            self.badge.set("many", str(len(files)))
        self.thumb_for = None
        if len(files) == 1 and viewable(fmts[0]):
            self.show_preview(files[0], fmts[0])
        else:
            self.hide_preview()
            if len(files) == 1 and files[0].is_file():
                self.thumb_for = files[0]
                job = ThumbJob(files[0], fmts[0], Badge.THUMB)
                job.done.connect(self._thumb_ready)  # a bound slot: dropped if the window goes first
                _THUMB_JOBS.add(job)
                job.finished.connect(lambda: _THUMB_JOBS.discard(job))
                job.start()

    def _thumb_ready(self, path: Path, image: QImage | None) -> None:
        if image is not None and not image.isNull() and path == self.thumb_for:
            self.badge.set_picture(image)

    def show_preview(self, path: Path, fmt: str) -> None:
        if self.preview is None:
            from .viewer import ViewerPanel
            self.preview = ViewerPanel(THEME, "surface")
            self.preview.setCursor(Qt.ArrowCursor)
            self.preview.loaded.connect(self._preview_loaded)
            self.preview.activated.connect(self.expand)
            self.lay.insertWidget(1, self.preview, 1)
            self.expand_btn = IconButton("expand", "Open in a bigger window", 30, filled=True, parent=self)
            self.expand_btn.clicked.connect(self.expand)
        self.badge.hide()  # the preview takes the room, the labels go under it
        self.lay.setStretch(0, 0)
        self.lay.setStretch(self.lay.count() - 1, 0)
        self.preview_fmt = fmt
        self.preview.show()
        self.preview.load(path, fmt)
        self.expand_btn.hide()

    def hide_preview(self) -> None:
        self.badge.show()
        self.lay.setStretch(0, 1)
        self.lay.setStretch(self.lay.count() - 1, 1)
        if self.preview is not None and not self.preview.isHidden():
            self.preview.clear()
            self.preview.hide()
            self.expand_btn.hide()

    def _preview_loaded(self, model) -> None:
        moving = " · animated" if self.preview.player is not None else ""
        self.sub.setText(f"{describe(self.preview_fmt)} · {model.triangle_count:,} triangles{moving}")
        self.expand_btn.show()
        self._place_expand()

    def _place_expand(self) -> None:
        if self.expand_btn is not None:
            self.expand_btn.move(self.width() - self.expand_btn.width() - 12, 12)
            self.expand_btn.raise_()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_expand()

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
    via: list[str] = None    # formats the route passes through ("pdf"), when it isn't one step
    notes: list[str] = None  # what the route can't keep (losses.py), for the usual file


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
            legend = QLabel("Dashed formats need a free tool, installed once when you pick them. "
                            "Point at a format to see what it keeps.")
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
        if o.via:
            tip += f" (via {', '.join(v.upper() for v in o.via)})"
        if o.needs:
            tip += f"\nNeeds {' and '.join(o.needs)} (free, installed once)"
        for n in o.notes or ():
            tip += f"\n· {n}"
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
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(14)
        intro = QLabel("ConvertAll uses these free tools for some formats. "
                       "Missing ones are installed for you when you first need them.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        lay.addWidget(intro)
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        lay.addLayout(grid)
        self.jobs: list[InstallJob] = []
        for row, (eng, path) in enumerate(engines.status()):
            name = QLabel(eng.name)
            name.setMinimumHeight(30)
            grid.addWidget(name, row, 0)
            if path:
                st = QLabel("Installed")
                st.setObjectName("ok")
                st.setToolTip(path)
                grid.addWidget(st, row, 1, Qt.AlignRight)
            else:
                btn = QPushButton(f"Install ({eng.size})")
                btn.clicked.connect(lambda _=False, k=eng.key, b=btn: self._install(k, b))
                grid.addWidget(btn, row, 1, Qt.AlignRight)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.setFixedHeight(34)
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)

    def _install(self, key: str, btn: QPushButton) -> None:
        btn.setEnabled(False)
        btn.setText("Installing…")
        job = InstallJob(key)
        job.finished_ok.connect(lambda ok, err: btn.setText("Installed" if ok else (err or "Failed")))
        self.jobs.append(job)
        job.start()


class ComboRows(QStyledItemDelegate):
    """Rows that follow the stylesheet, and separators drawn as a thin line."""

    @staticmethod
    def _separator(index) -> bool:
        return index.data(Qt.AccessibleDescriptionRole) == "separator"

    def paint(self, painter, option, index) -> None:
        if self._separator(index):
            y = option.rect.center().y()
            painter.setPen(QPen(QColor(THEME["border"]), 1))
            painter.drawLine(option.rect.left() + 6, y, option.rect.right() - 6, y)
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option, index):
        return QSize(0, 9) if self._separator(index) else super().sizeHint(option, index)


class Disclosure(QPushButton):
    """A header that opens and closes what's under it: a chevron, its title, and on the right a
    short summary of what's inside (accented when it isn't the default)."""

    def __init__(self, title: str):
        super().__init__(title)
        self.setObjectName("disclosure")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(title)
        self.setFixedHeight(CONTROL - 2)
        self.setAttribute(Qt.WA_Hover)
        self.summary, self.accented = "", False

    def set_summary(self, text: str, accented: bool) -> None:
        self.summary, self.accented = text, accented
        self.setAccessibleDescription(text)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hover = self.underMouse() and self.isEnabled()
        text = QColor(THEME["text"] if self.isEnabled() else THEME["muted"])
        muted = QColor(THEME["muted"])
        pen = QPen(QColor(THEME["accent"]) if hover else muted, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        x, cy = 18.0, self.height() / 2
        if self.isChecked():  # pointing down: open
            p.drawPolyline([QPointF(x - 4, cy - 2), QPointF(x, cy + 2), QPointF(x + 4, cy - 2)])
        else:
            p.drawPolyline([QPointF(x - 2, cy - 4), QPointF(x + 2, cy), QPointF(x - 2, cy + 4)])
        bold = QFont(self.font())
        bold.setWeight(QFont.DemiBold)
        p.setFont(bold)
        p.setPen(QColor(THEME["accent"]) if hover else text)
        title_w = QFontMetrics(bold).horizontalAdvance(self.text())
        p.drawText(QRectF(32, 0, title_w + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.setFont(self.font())
        p.setPen(QColor(THEME["accent"]) if self.accented else muted)
        room = QRectF(32 + title_w + 16, 0, self.width() - title_w - 32 - 16 - 14, self.height())
        p.drawText(room, Qt.AlignVCenter | Qt.AlignRight,
                   QFontMetrics(self.font()).elidedText(self.summary, Qt.ElideRight, int(room.width())))
        p.end()


class FlowLayout(QLayout):
    """Lays its widgets out in rows, wrapping to the next row when one is full (preset pills)."""

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent)
        self.items: list = []
        self.gap = gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self.items.append(item)

    def count(self) -> int:
        return len(self.items)

    def itemAt(self, i: int):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i: int):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        widest = max((it.sizeHint().width() for it in self.items if not it.isEmpty()), default=0)
        width = max(self.geometry().width(), 340)  # the height the rows take at about the width they get
        return QSize(widest, self._place(QRect(0, 0, width, 0), move=False))

    def _place(self, rect, move: bool) -> int:
        x, y, row = rect.x(), rect.y(), 0
        for it in self.items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if row and x + hint.width() > rect.x() + rect.width():
                x, y, row = rect.x(), y + row + self.gap, 0
            if move:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.gap
            row = max(row, hint.height())
        return y + row - rect.y()


def auto_text(st: options.Setting, target: str | None) -> str:
    """What "not set" says, without a hint about another format ("Original", not "Original (12 for GIF)" for WebM)."""
    if " (" in st.auto and (not target or target.upper() not in st.auto.upper()):
        return st.auto.split(" (")[0]
    return st.auto


class SliderSetting(QWidget):
    """A number on a slider, with its value beside it; all the way left is "not set"."""
    changed = Signal(object)  # the value, or None

    def __init__(self, st: options.Setting, auto: str):
        super().__init__()
        self.st, self.auto = st, auto
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.bar = QSlider(Qt.Horizontal)
        self.bar.setRange(st.low - 1, st.high)
        self.bar.setPageStep(5)
        self.bar.setCursor(Qt.PointingHandCursor)
        self.label = QLabel()
        self.label.setObjectName("value")
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bold = QFont(self.label.font())
        bold.setWeight(QFont.DemiBold)
        self.short_auto = auto.split(" (")[0]  # "Auto"; the rest of "Auto (92 for JPG)" is in the tooltip
        self.label.setFixedWidth(max(QFontMetrics(bold).horizontalAdvance(t) for t in (self.short_auto, f"{st.high}{st.unit}")) + 6)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.label)
        self.setFixedHeight(FIELD)
        self.bar.valueChanged.connect(lambda _: (self._label(), self.changed.emit(self.value())))

    def value(self):
        v = self.bar.value()
        return v if v >= self.st.low else None

    def setValue(self, value) -> None:
        self.bar.setValue(self.st.low - 1 if value is None else value)

    def show_value(self, value) -> None:
        self.bar.blockSignals(True)
        self.setValue(value)
        self.bar.blockSignals(False)
        self._label()

    def _label(self) -> None:
        v = self.value()
        self.label.setText(self.short_auto if v is None else f"{v}{self.st.unit}")
        self.label.setToolTip(self.auto if v is None else "")
        self.label.setProperty("auto", v is None)
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)


class ChoiceSetting(QComboBox):
    """One of a list: a setting's choices, or for a number its usual values, where any other
    number can be typed too. The first entry is "not set"."""
    changed = Signal(object)

    def __init__(self, st: options.Setting, auto: str):
        super().__init__()
        self.setItemDelegate(ComboRows(self))
        self.setFixedHeight(FIELD)
        self.st, self._value = st, None
        self.addItem(auto, None)
        entries = [(st.shown(c), c) for c in st.choices] or \
                  [(f"{n}{st.unit}", n) for n in st.common]
        for text, data in entries:
            if text != auto:  # the default is already the first entry ("Balanced", "150 dpi")
                self.addItem(text, data)
        self.activated.connect(lambda i: self.setValue(self.itemData(i)))
        if not st.choices:
            self.setEditable(True)
            self.setInsertPolicy(QComboBox.NoInsert)
            self.lineEdit().setPlaceholderText(f"{st.low} to {st.high}{st.unit}")
            self.lineEdit().editingFinished.connect(self._typed)

    def value(self):
        return self._value

    def setValue(self, value) -> None:
        self.show_value(value)
        self.changed.emit(value)

    def show_value(self, value) -> None:
        self._value = value
        i = self.findData(value) if value is not None else 0
        self.blockSignals(True)
        if i >= 0:
            self.setCurrentIndex(i)
        elif self.isEditable():
            self.setCurrentIndex(-1)
            self.setEditText(f"{value}{self.st.unit}")
        self.blockSignals(False)

    def _typed(self) -> None:
        text = self.lineEdit().text().strip()
        if text in ("", self.itemText(0)):
            value = None
        else:
            try:
                value = self.st.check(text)
            except ValueError:  # not a number in range: back to what it was
                self.show_value(self._value)
                return
        if value != self._value:
            self.setValue(value)
        else:
            self.show_value(value)


class OptionsPanel(QWidget):
    """A collapsed "Options" card under the picker: presets as one-click pills, then the
    settings the chosen format's route takes (options.py). Unset settings keep ConvertAll's
    defaults. Remembered between runs."""
    changed = Signal()
    DEFAULT = options.DEFAULT

    def __init__(self, settings: QSettings):
        super().__init__()
        self.store = settings
        self.values: dict = {}
        try:
            self.values = options.clean(json.loads(self.store.value("options/values", "{}") or "{}"))
        except (ValueError, TypeError):
            self.values = {}
        self.keys: list[str] = []
        self.target: str | None = None
        self.widgets: dict[str, QWidget] = {}
        self.pills: dict[str, QPushButton] = {}
        self.save_pill: QPushButton | None = None
        self._pill_state = None
        self.grew = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("options")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.head = Disclosure("Options")
        self.head.toggled.connect(self._toggle)
        lay.addWidget(self.head)
        self.body = QWidget()
        self.body.setObjectName("optionsBody")
        self.body.hide()
        lay.addWidget(self.body)
        form = QVBoxLayout(self.body)
        form.setContentsMargins(14, 0, 14, 14)
        form.setSpacing(12)
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        form.addWidget(line)
        self.pill_box = QWidget()
        self.pill_box.setObjectName("optionsBody")
        self.flow = FlowLayout(self.pill_box, 6)
        form.addWidget(self.pill_box)
        self.grid = QGridLayout()  # a row per setting
        self.grid.setContentsMargins(0, 2, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(1, 1)
        form.addLayout(self.grid)
        self.rows: list[QWidget] = []
        self.delete_btn = QPushButton("Delete this preset")
        self.delete_btn.setObjectName("link")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self._delete)
        form.addWidget(self.delete_btn, 0, Qt.AlignRight)
        self._fill_presets()
        self._refresh_head()

    # -- what's chosen

    def chosen(self) -> dict:
        return dict(self.values)

    def current_preset(self) -> str:
        """The preset these settings are, judged by what this conversion takes: settings kept from
        another kind of file change nothing here."""
        def here(vals: dict) -> dict:
            return {k: v for k, v in vals.items() if k in self.keys}
        mine = here(self.values)
        if not mine:
            return self.DEFAULT
        return next((name for name, vals in options.all_presets().items()
                     if name != self.DEFAULT and here(vals) == mine), "")

    # -- showing

    def show_for(self, keys: list[str], target: str | None = None) -> None:
        keys = [k for k in keys if k in options.SETTINGS]
        self.setVisible(bool(keys))
        if keys == self.keys and target == self.target and self.widgets:
            self._fill_presets()  # the same rows: keep them (one may be being typed in)
            self._refresh_head()
            return
        self.keys, self.target = keys, target
        for w in self.rows:
            self.grid.removeWidget(w)
            w.deleteLater()
        self.rows, self.widgets = [], {}
        for row, key in enumerate(self.keys):
            st = options.SETTINGS[key]
            name = QLabel(st.label)
            name.setToolTip(st.help)
            name.setMinimumHeight(FIELD)
            self.grid.addWidget(name, row, 0)
            auto = auto_text(st, target)
            w = SliderSetting(st, auto) if st.slider else ChoiceSetting(st, auto)
            w.show_value(self.values.get(key))
            w.changed.connect(lambda v, k=key: self._set(k, v))
            w.setToolTip(st.help if auto == st.auto else f"{st.help}. Left as {st.auto}")
            w.setAccessibleName(st.label)
            self.grid.addWidget(w, row, 1)
            self.widgets[key] = w
            self.rows += [name, w]
        self._fill_presets()
        self._refresh_head()

    def _sync(self) -> None:
        """Show self.values in the rows (after a preset or a reset), without each change echoing back."""
        for key, w in self.widgets.items():
            w.show_value(self.values.get(key))

    def _set(self, key: str, value) -> None:
        if value is None:
            self.values.pop(key, None)
        else:
            self.values[key] = value
        self._saved()

    def _saved(self) -> None:
        self.store.setValue("options/values", json.dumps(self.values))
        self._fill_presets()
        self._refresh_head()
        self.changed.emit()

    def summary(self) -> str:
        """What the header says on its right: the preset, what's changed, or "Default"."""
        shown = {k: v for k, v in self.values.items() if k in self.keys}
        name = self.current_preset()
        if not shown:
            return self.DEFAULT
        if name and name != self.DEFAULT:
            return name
        if len(shown) == 1:
            (key, value), = shown.items()
            st = options.SETTINGS[key]
            return f"{st.label} {value if not st.choices else st.shown(value)}{st.unit}"
        return f"{len(shown)} changed"

    def _refresh_head(self) -> None:
        self.head.set_summary(self.summary(), self.summary() != self.DEFAULT)
        self.delete_btn.setVisible(self.current_preset() in options.user_presets())

    def _toggle(self, on: bool) -> None:
        """Open or close; the window grows to fit, and gives that height back on closing."""
        win = self.window()
        before = win.height()
        self.body.setVisible(on)
        self._refresh_head()
        if not win.isVisible():
            return
        win.layout().activate()
        need = win.minimumSizeHint().height()
        if on and before < need:
            self.grew = need - before
            win.resize(win.width(), need)
        elif not on and self.grew:
            win.resize(win.width(), max(win.height() - self.grew, win.minimumSizeHint().height()))
            self.grew = 0

    # -- presets: a pill each; the one in use is lit; "+ Save as preset" when the settings are your own

    def preset_names(self) -> list[str]:
        """Default, then the presets that change something this format takes."""
        current = self.current_preset()
        return [self.DEFAULT] + [name for name, vals in options.all_presets().items()
                                 if (set(vals) & set(self.keys) or name == current) and name != self.DEFAULT]

    def _fill_presets(self) -> None:
        names, current = self.preset_names(), self.current_preset()
        state = (tuple(names), current, tuple(self.keys))
        if state == self._pill_state:
            return
        self._pill_state = state
        while self.flow.count():
            w = self.flow.takeAt(0).widget()
            w.deleteLater()
        self.pills = {}
        for name in names:
            pill = self._pill(name)
            pill.setCheckable(True)
            pill.setChecked(name == current)
            vals = options.all_presets().get(name, {})
            here = [f"{options.SETTINGS[k].label} {v}{options.SETTINGS[k].unit}" for k, v in vals.items() if k in self.keys]
            pill.setToolTip("ConvertAll's own settings" if name == self.DEFAULT else ", ".join(here))
            pill.clicked.connect(lambda _=False, n=name: self.pick(n))
            self.pills[name] = pill
        self.save_pill = None
        if not current:
            self.save_pill = self._pill("+  Save as preset")
            self.save_pill.setProperty("add", True)
            self.save_pill.setToolTip("Keep these settings under a name, for the window and the command line")
            self.save_pill.clicked.connect(self._save_as)
        self.pill_box.updateGeometry()

    def _pill(self, text: str) -> QPushButton:
        pill = QPushButton(text)
        pill.setObjectName("pill")
        pill.setCursor(Qt.PointingHandCursor)
        self.flow.addWidget(pill)
        return pill

    def pick(self, name: str) -> None:
        if name == self.DEFAULT:
            self._reset()
        elif name in options.all_presets():
            self.values = dict(options.all_presets()[name])
            self._sync()
            self._saved()

    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save as preset", "Name for these settings:")
        try:
            if ok:
                options.save_preset(name, self.values)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Save as preset", str(exc))
        self._fill_presets()
        self._refresh_head()

    def _delete(self) -> None:
        options.delete_preset(self.current_preset())
        self._pill_state = None
        self._fill_presets()
        self._refresh_head()

    def _reset(self) -> None:
        self.values = {}
        self._sync()
        self._saved()


CHECK_MARKS = {"same": "Same", "changed": "Changed", "expected": "As noted", "bad": "Didn't match"}


class DetailsDialog(QDialog):
    """After converting: each file's route, what it couldn't keep, and what was checked."""

    def __init__(self, parent, reports: list[Report]):
        super().__init__(parent)
        self.setObjectName("details")
        self.setWindowTitle("Conversion details")
        self.reports = reports
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 4, 0)
        col.setSpacing(12)
        for r in reports[:50]:
            col.addWidget(self._card(r))
        col.addStretch()
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        self.copy_btn = QPushButton("Copy report")
        self.copy_btn.setToolTip("The full report as JSON, for a bug report or your records")
        self.copy_btn.clicked.connect(self._copied)
        buttons.addWidget(self.copy_btn)
        buttons.addStretch()
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        for b in (self.copy_btn, close):
            b.setFixedHeight(34)
        lay.addLayout(buttons)
        body.setFixedWidth(540 - 18 - 18)  # wrapped lines measure at the real width
        height = body.sizeHint().height()
        body.setMinimumWidth(0)
        body.setMaximumWidth(16777215)
        self.resize(540, min(620, height + 18 + 14 + 34 + 16 + 4))

    def _card(self, r: Report) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        c = QVBoxLayout(card)
        c.setContentsMargins(16, 14, 16, 14)
        c.setSpacing(6)
        title = QLabel(f"{Path(r.source).name}  →  {Path(r.output).name}")
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        c.addWidget(title)
        tools = ", ".join(dict.fromkeys(st["tool"] for st in r.steps))
        seconds = f"{r.seconds:.2f} s" if r.seconds < 10 else f"{r.seconds:.0f} s"
        c.addWidget(self._muted(f"{r.route} via {tools} · {seconds}"))
        if r.settings:
            c.addWidget(self._muted("Settings: " + ", ".join(
                f"{options.SETTINGS[k].label.lower()} {v}{options.SETTINGS[k].unit}" for k, v in r.settings.items())))
        if r.notes:
            c.addSpacing(6)
            c.addWidget(self._section("Couldn't keep"))
            for n in r.notes:
                note = QLabel(f"•  {n}")
                note.setWordWrap(True)
                c.addWidget(note)
        c.addSpacing(6)
        if not r.checks:
            c.addWidget(self._muted("Nothing ConvertAll measures in this kind of file"))
            return card
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(2)
        for i, head in enumerate(("Checked", "Before", "After", "")):
            grid.addWidget(self._section(head), 0, i)
        for row, check in enumerate(r.checks, 1):
            state = ("same" if check.before == check.after else "changed") if check.state == "ok" \
                else "expected" if check.state == "expected" else "bad"
            cells = (check.name, "" if check.before is None else show(check.before),
                     check.why if check.state == "error" else "" if check.after is None else show(check.after))
            for i, text in enumerate(cells):
                cell = QLabel(text)
                cell.setObjectName("checkBad" if state == "bad" else "cell")
                cell.setWordWrap(i == 2)
                grid.addWidget(cell, row, i)
            mark = QLabel(CHECK_MARKS[state])
            mark.setObjectName("mark")
            mark.setProperty("state", state)
            grid.addWidget(mark, row, 3, Qt.AlignRight | Qt.AlignVCenter)
        grid.setColumnStretch(2, 1)
        c.addLayout(grid)
        return card

    @staticmethod
    def _section(text: str) -> QLabel:
        label_ = QLabel(text.upper())
        label_.setObjectName("section")
        return label_

    def _copied(self) -> None:
        self.copy()
        self.copy_btn.setText("Copied")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy report"))

    @staticmethod
    def _muted(text: str) -> QLabel:
        label_ = QLabel(text)
        label_.setObjectName("muted")
        label_.setWordWrap(True)
        return label_

    def copy(self) -> str:
        text = json.dumps([r.to_dict() for r in self.reports], indent=2, ensure_ascii=False, default=str)
        QGuiApplication.clipboard().setText(text)
        return text


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ConvertAll")
        self.setWindowIcon(QIcon(str(ASSETS / "icon.png")))
        self.resize(460, 500)
        self.setMinimumWidth(400)  # the height follows what's showing: nothing ever overlaps
        self.settings = QSettings("ConvertAll", "ConvertAll")
        self.files: list[Path] = []
        self.probed = float("-inf")  # when engines were last looked for (ENGINE_RECHECK_S)
        self.fmts: list[str] = []
        self.routes: dict[str, list[registry.Route]] = {}
        self.outputs: list[Path] = []
        self.job: Job | None = None
        self.close_when_done = False  # closed while converting: it closes once the job has stopped
        self.last_add = 0.0
        self.pending_extract: list[Path] = []
        self.extract_timer = QTimer(self)
        self.extract_timer.setSingleShot(True)
        self.extract_timer.setInterval(EXTRACT_SETTLE_MS)
        self.extract_timer.timeout.connect(self.extract_pending)
        # a slider drag changes a setting many times a second; the format list's notes follow once it rests
        self.notes_timer = QTimer(self)
        self.notes_timer.setSingleShot(True)
        self.notes_timer.setInterval(NOTES_SETTLE_MS)
        self.notes_timer.timeout.connect(self.refresh_notes)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 20)
        root.setSpacing(14)

        head = QHBoxLayout()
        title = QLabel("ConvertAll")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch()
        menu_btn = IconButton("menu", "Menu")
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        menu.addAction("Engines…", self.show_engines)
        self.ctx_action = QAction(self)
        self.ctx_action.triggered.connect(self.toggle_context_menu)
        menu.addAction(self.ctx_action)
        self.start_action = QAction(self)
        self.start_action.triggered.connect(self.toggle_start_menu)
        if sys.platform == "win32":
            menu.addAction(self.start_action)
        menu.addSeparator()
        menu.addAction("Help and chat on Discord", lambda: QDesktopServices.openUrl(QUrl(DISCORD)))
        menu.addAction("About ConvertAll", self.about)
        menu.aboutToShow.connect(self._refresh_ctx_label)
        menu.aboutToShow.connect(lambda: _set_open(menu_btn, True))
        menu.aboutToHide.connect(lambda: _set_open(menu_btn, False))
        menu_btn.setMenu(menu)
        head.addWidget(menu_btn)
        root.addLayout(head)

        self.drop = DropZone()
        self.drop.files_dropped.connect(self.set_files)
        self.drop.expand.connect(self.expand_preview)
        root.addWidget(self.drop, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.picker = FormatPicker()
        self.picker.setEnabled(False)
        self.picker.setFixedHeight(CONTROL)
        row.addWidget(self.picker, 1)
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setEnabled(False)
        self.convert_btn.setFixedSize(108, CONTROL)
        self.convert_btn.clicked.connect(self.convert_clicked)
        row.addWidget(self.convert_btn)
        root.addLayout(row)

        self.options_panel = OptionsPanel(self.settings)
        self.options_panel.hide()
        root.addWidget(self.options_panel)
        # bound methods, not lambdas that hold self: a lambda on a child's signal keeps the window
        # alive after it closes, until Python's exit, where it crashed tearing down after Qt
        self.picker.changed.connect(self._format_picked)
        self.options_panel.changed.connect(self.notes_timer.start)

        self.extract_btn = QPushButton("Extract here")
        self.extract_btn.setFixedHeight(CONTROL)
        self.extract_btn.setToolTip("Unpack it into a folder next to it")
        self.extract_btn.clicked.connect(self.start_extract)
        self.extract_btn.hide()
        root.addWidget(self.extract_btn)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        root.addWidget(self.bar)

        # After a run: what happened (colored), the links, and under them what the route
        # couldn't keep. Hidden while there's nothing to say, so no empty band is left over.
        self.foot = QWidget()
        foot = QGridLayout(self.foot)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setHorizontalSpacing(14)
        foot.setVerticalSpacing(2)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 0, 0)
        links = QHBoxLayout()
        links.setSpacing(14)
        self.show_btn = QPushButton("Show in folder")
        self.details_btn = QPushButton("Details")
        self.details_btn.setToolTip("The route, what it couldn't keep and what was checked")
        for b in (self.show_btn, self.details_btn):
            b.setObjectName("link")
            b.setCursor(Qt.PointingHandCursor)
            b.hide()
            links.addWidget(b)
        self.show_btn.clicked.connect(self.show_output)
        self.details_btn.clicked.connect(self.show_details)
        foot.addLayout(links, 0, 1, Qt.AlignTop | Qt.AlignRight)
        self.note = QLabel("")
        self.note.setObjectName("note")
        self.note.setWordWrap(True)
        self.note.hide()
        foot.addWidget(self.note, 1, 0, 1, 2)
        foot.setColumnStretch(0, 1)
        self.foot.hide()
        root.addWidget(self.foot)
        self.reports: list[Report] = []

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
        self.show()  # hidden when this process was started just to view a model
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def open_viewers(self, paths: list[Path]) -> None:
        """Right-click "View with ConvertAll": a viewer window per model. Anything else that
        arrives this way opens in the main window, to be converted."""
        others = []
        for p in paths:
            if not p.exists():
                continue
            fmt = detect(p)
            if viewable(fmt):
                self.open_viewer(p, fmt)
            else:
                others.append(p)
        if others:
            self.add_files_from_other_instance(others)

    def open_viewer(self, path: Path, fmt: str, model=None):
        from .viewer import ViewerWindow
        win = ViewerWindow(THEME, path, fmt, model)
        win.setWindowIcon(self.windowIcon())
        win.show()
        win.raise_()
        win.activateWindow()
        return win

    def expand_preview(self) -> None:
        if self.files and self.drop.preview is not None:
            win = self.open_viewer(self.files[0], self.fmts[0], self.drop.preview.model)
            player = self.drop.preview.player
            if player is not None and player.playing:  # one copy playing at a time: the big one
                player.pause()
                win.destroyed.connect(lambda *_: self.drop.preview.player is player and player.play())

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

    def show_engines(self) -> None:
        EnginesDialog(self).exec()
        engines.refresh()  # one may have been installed: its formats join the list now
        self.probed = time.monotonic()
        if self.files and not self.job:
            self.routes = registry.common_targets(self.fmts)
            self.fill_picker()

    def set_files(self, paths: list[Path]) -> None:
        if self.job:
            return
        paths = [p for p in paths if p.exists()]
        if not paths:
            return
        self.files = paths
        self.fmts = [detect(p) for p in paths]
        if time.monotonic() - self.probed > ENGINE_RECHECK_S:  # pick up engines installed meanwhile
            engines.refresh()
            self.probed = time.monotonic()
        self.drop.show_files(paths, self.fmts)
        self.routes = registry.common_targets(self.fmts)
        self.fill_picker()
        self.extract_btn.setVisible(all(pipeline.can_extract(f) for f in self.fmts))
        self.show_btn.hide()
        self.details_btn.hide()
        self.set_status("")
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
        chosen = self.options_panel.chosen()
        for dst in sorted(self.routes, key=lambda d: (kind_order.get(category(d), 99), d)):
            name = label(dst)
            routes = self.routes[dst]
            needs = list(dict.fromkeys(engines.ENGINES[e].name for r in routes for e in r.missing_engines))
            via = list(dict.fromkeys(e.dst for r in routes for e in r.edges[:-1]))
            notes = list(dict.fromkeys(n.text for r in routes for n in r.explain(options=chosen)))
            options.append(Option(dst, category(dst), "" if name.upper() == dst.upper() else name, needs, via, notes))
        remembered = self.settings.value(f"last/{self.fmts[0]}", "")
        common = suggest(self.fmts[0], self.routes)
        suggested = [f for f in dict.fromkeys([remembered, common]) if f in self.routes]
        self.picker.set_options(options, self.preselect() or options[0].fmt, suggested)
        self.update_options()

    def _format_picked(self, _fmt) -> None:
        self.update_options()

    def show_output(self) -> None:
        if self.outputs:
            reveal(self.outputs[0])

    def update_options(self) -> None:
        """Show the settings the chosen format's route takes (none: no panel at all)."""
        target = self.picker.current()
        keys = list(dict.fromkeys(k for r in self.routes.get(target, ()) for k in r.settings)) if target else []
        self.options_panel.show_for(keys, target)

    def refresh_notes(self) -> None:
        """Settings change what a route says (pages drawn at 300 dpi): rebuild the picker's tooltips."""
        self.notes_timer.stop()
        if self.routes and not self.job:
            current = self.picker.current()
            self.fill_picker()
            if current:
                self.picker.set_current(current)

    def preselect(self) -> str | None:
        """What this user last turned this kind of file into, else what most people do with it."""
        remembered = self.settings.value(f"last/{self.fmts[0]}", "")
        if remembered in self.routes:
            return remembered
        return suggest(self.fmts[0], self.routes)

    # ------------------------------------------------ running

    def convert_clicked(self) -> None:
        """While a job runs, the Convert button is its Cancel button."""
        if isinstance(self.job, Job):
            self.cancel_job()
        else:
            self.start_convert()

    def cancel_job(self) -> None:
        if not isinstance(self.job, Job) or self.job.cancelled:
            return
        self.job.cancel()
        self.convert_btn.setEnabled(False)
        self.convert_btn.setText("Stopping…")
        self.set_status("Stopping…")

    def confirm_stop(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("ConvertAll")
        box.setIcon(QMessageBox.Question)
        box.setText("Stop converting and close?")
        box.setInformativeText("The file being converted now isn't saved; the ones already done are kept.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("Stop and close")
        box.button(QMessageBox.Cancel).setText("Keep converting")
        return box.exec() == QMessageBox.Yes

    def closeEvent(self, event) -> None:
        """Closing mid-job asks first, then stops the job and closes once it has: Qt would
        otherwise tear the window down under a running thread and leave its engine running."""
        job = self.job
        if isinstance(job, Job) and job.isRunning():
            if not self.close_when_done and not self.confirm_stop():
                event.ignore()
                return
            self.close_when_done = True
            self.cancel_job()
            self.hide()
            event.ignore()  # job_done closes it for real
            return
        super().closeEvent(event)

    def start_convert(self) -> None:
        if self.notes_timer.isActive():
            self.refresh_notes()
        target = self.picker.current()
        if not target:
            return
        self.settings.setValue(f"last/{self.fmts[0]}", target)
        missing = list(dict.fromkeys(e for r in self.routes[target] for e in r.missing_engines))
        if missing and not self.confirm_install(missing):
            return
        keys = {k for r in self.routes[target] for k in r.settings}
        self.run_job(Job(self.files, target, missing, options.applying(self.options_panel.chosen(), keys)))

    def start_extract(self) -> None:
        from .converters.archives import NATIVE_EXTRACT
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
        for w in (self.picker, self.extract_btn, self.options_panel):
            w.setEnabled(False)
        self.convert_btn.setText("Cancel")
        self.convert_btn.setEnabled(True)
        self.show_btn.hide()
        self.details_btn.hide()
        self.bar.setRange(0, 0)
        self.bar.show()
        job.progress.connect(self.set_status)
        job.done.connect(self.job_done)
        job.start()

    def job_done(self, outputs: list[Path], errors: list[str], notes: list[str] | None = None,
                 reports: list[Report] | None = None) -> None:
        extracting = self.job is not None and self.job.target is None
        stopped = isinstance(self.job, Job) and self.job.cancelled
        self.job = None
        self.convert_btn.setText("Convert")
        if self.close_when_done:
            # hidden while it stopped, so closing it isn't "the last window closed": quit unless
            # a 3D viewer is still open
            self.close()
            app = QApplication.instance()
            if app and app.quitOnLastWindowClosed() and not any(
                    w.isVisible() for w in app.topLevelWidgets() if w.isWindow() and w is not self):
                app.quit()
            return
        self.outputs = outputs
        self.reports = reports or []
        self.options_panel.setEnabled(True)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.bar.hide()
        if self.files:
            self.routes = registry.common_targets(self.fmts)  # engines may have changed
            self.fill_picker()
            self.extract_btn.setEnabled(True)
        self.show_btn.setVisible(bool(outputs))
        self.details_btn.setVisible(bool(self.reports))
        if stopped:
            left = len(self.files) - len(outputs)
            self.set_status("Stopped", "warn",
                            f"{len(outputs)} saved, {left} not converted" if outputs else "Nothing was saved")
        elif errors:
            more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
            first, _, why = errors[0].partition(": ")
            if first in {f.name for f in self.files}:  # "name: why" from one file
                self.set_status(f"Couldn't {'extract' if extracting else 'convert'} {first}", "error", why + more)
            else:  # an engine that wouldn't install
                self.set_status(errors[0], "error", more.strip())
            self.set_tip("\n".join(errors))
        else:
            done = f"Saved {outputs[0].name}" if len(outputs) == 1 else f"Done · {len(outputs)} files"
            warned = [r for r in self.reports if r.warnings]
            if notes:  # what a route couldn't keep, entries left out or renamed: shown, but not as a failure
                more = f" (+{len(notes) - 1} more)" if len(notes) > 1 else ""
                self.set_status(done, "warn" if warned else "ok", f"{notes[0].split(': ', 1)[-1]}{more}")
                self.set_tip("\n".join(notes))
            else:
                self.set_status(done, "ok")
            if len(self.reports) == 1:
                self.set_tip("\n".join(self.reports[0].lines()))
        if self.pending_extract:  # more archives were right-clicked while this ran
            self.extract_timer.start()

    def show_details(self) -> QDialog:
        dialog = DetailsDialog(self, self.reports)
        dialog.open()
        return dialog

    def set_status(self, text: str, state: str = "", note: str = "") -> None:
        """The line under the controls (colored by state), and a muted note under it."""
        self.status.setText(text)
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.set_tip("")
        self.foot.setVisible(bool(text or note) or not self.show_btn.isHidden())

    def set_tip(self, text: str) -> None:
        self.status.setToolTip(text)
        self.note.setToolTip(text)

    # ------------------------------------------------ menu actions

    def _refresh_ctx_label(self) -> None:
        self.ctx_action.setText("Remove from right-click menu" if context_menu_installed()
                                else "Add to right-click menu")
        self.start_action.setText("Remove from Start menu" if start_menu_installed() else "Add to Start menu")

    def toggle_start_menu(self) -> None:
        try:
            if start_menu_installed():
                remove_start_menu()
                self.set_status("Removed from the Start menu", "ok")
            else:
                install_start_menu()
                self.set_status("Added to the Start menu", "ok", "Type “ConvertAll” in Start to open it")
        except OSError as exc:
            self.set_status("Couldn't change the Start menu", "error", str(exc))

    def toggle_context_menu(self) -> None:
        try:
            if context_menu_installed():
                remove_context_menu()
                self.set_status("Removed from the right-click menu", "ok")
            else:
                install_context_menu()
                self.set_status("Added to the right-click menu", "ok",
                                "“Convert with ConvertAll” on every file, “Extract with ConvertAll” on "
                                "archives and “View with ConvertAll” on 3D models (Windows 11: under "
                                "Show more options)")
        except OSError as exc:
            self.set_status("Couldn't change the right-click menu", "error", str(exc))

    def about(self) -> QMessageBox:
        box = QMessageBox(self)
        box.setWindowTitle("ConvertAll")
        box.setIconPixmap(self.windowIcon().pixmap(48, 48))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b>ConvertAll {__version__}</b><br>"
                    "Convert, compress or extract any file.<br><br>"
                    "Uses Pillow, PyMuPDF, py7zr, fontTools, trimesh, gmsh, ezdxf, pydicom, meshport, "
                    "packport, bookport, vtracer, pysubs2, pycdlib and, when needed, FFmpeg, 7-Zip, "
                    "LibreOffice, ImageMagick, Pandoc, DjVuLibre and Ghostscript.<br><br>"
                    f'Questions, ideas or just chatting: <a href="{DISCORD}">ConvertAll on Discord</a>')
        for text in box.findChildren(QLabel):
            text.setOpenExternalLinks(True)  # the Discord link opens in the browser
        box.open()
        return box


# ---------------------------------------------------------------- Explorer right-click menu
# "Convert with ConvertAll" on every file and folder. Archives get "Extract with ConvertAll"
# instead: a verb under SystemFileAssociations\.<ext> with the same key name as the one under *
# replaces it for that extension, so Explorer shows one entry, never both. 3D models also get
# "View with ConvertAll", under a key of its own, so their Convert stays.

_STAR_KEY = r"Software\Classes\*\shell\ConvertAll"
_DIR_KEY = r"Software\Classes\Directory\shell\ConvertAll"
_SFA = r"Software\Classes\SystemFileAssociations"
_VERB = r"shell\ConvertAll"
_VIEW_VERB = r"shell\ConvertAllView"


def extract_extensions() -> list[str]:
    """Extensions right-click extracts. Comics and other kinds that happen to be archives keep
    Convert: people turn a .cbz into a PDF far more often than they unpack it."""
    from .converters.archives import EXTRACTABLE
    fmts = {f for f in EXTRACTABLE if category(f) == "Archive"}
    exts = {f.rsplit(".", 1)[-1] for f in fmts} | {a for a, f in ALIASES.items() if f in fmts}
    return sorted(exts)


def view_extensions() -> list[str]:
    """Extensions that get "View with ConvertAll": every 3D model and CAD solid."""
    fmts = {f for f in FORMATS if viewable(f)}
    return sorted(fmts | {a for a, f in ALIASES.items() if f in fmts})


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


def registered_command() -> str | None:
    """What the right-click "Convert" runs: which copy of ConvertAll the menu belongs to."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STAR_KEY + r"\command") as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None


def context_menu_outdated() -> bool:
    """True when the menu should point here: this is a newer version, or the same version
    moved or reinstalled elsewhere. An older copy never takes the menu back."""
    if not context_menu_installed():
        return False
    mine, theirs = _version_tuple(__version__), _version_tuple(registered_version())
    return mine > theirs or (mine == theirs and registered_command() != _launch_command())


def _set_verb(key: str, text: str, command: str, multi: str = "Player") -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, text)
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, _icon_path())
        winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, multi)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)


def install_context_menu() -> None:
    import winreg
    remove_context_menu()  # also drops extensions an older build registered
    for key in (_STAR_KEY, _DIR_KEY):
        _set_verb(key, "Convert with ConvertAll", _launch_command())
    for ext in extract_extensions():
        _set_verb(rf"{_SFA}\.{ext}\{_VERB}", "Extract with ConvertAll", _launch_command(EXTRACT_MARKER))
    for ext in view_extensions():  # "Single": shown only when one file is selected
        _set_verb(rf"{_SFA}\.{ext}\{_VIEW_VERB}", "View with ConvertAll", _launch_command(VIEW_MARKER), "Single")
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
        for verb in (_VERB, _VIEW_VERB):
            _delete(rf"{base}\{verb}\command")
            _delete(rf"{base}\{verb}")
        _delete(rf"{base}\shell", only_if_empty=True)  # leave other apps' entries alone
        _delete(base, only_if_empty=True)


# ---------------------------------------------------------------- Start menu shortcut

def start_menu_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ConvertAll.lnk"


def start_menu_installed() -> bool:
    return start_menu_path().exists()


def install_start_menu() -> None:
    """A Start menu shortcut to this copy of ConvertAll. Windows writes .lnk files through COM,
    which PowerShell reaches in one line; the paths travel as variables, never quoted into it."""
    if getattr(sys, "frozen", False):
        target, args, workdir = sys.executable, "", str(Path(sys.executable).parent)
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        target, args, workdir = str(pythonw if pythonw.exists() else sys.executable), "-m convertall --gui", ""
    lnk = start_menu_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CA_LNK); "
              "$s.TargetPath = $env:CA_TARGET; $s.Arguments = $env:CA_ARGS; $s.WorkingDirectory = $env:CA_DIR; "
              "$s.IconLocation = $env:CA_ICON; $s.Description = 'Convert, compress or extract any file'; $s.Save()")
    env = {**os.environ, "CA_LNK": str(lnk), "CA_TARGET": target, "CA_ARGS": args, "CA_DIR": workdir,
           "CA_ICON": _icon_path()}
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    proc = subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                          capture_output=True, text=True, creationflags=engines.NO_WINDOW, check=False)
    if proc.returncode or not lnk.exists():
        lines = (proc.stderr or "").strip().splitlines() or ["PowerShell couldn't write the shortcut"]
        raise OSError(lines[-1])


def remove_start_menu() -> None:
    start_menu_path().unlink(missing_ok=True)


# ---------------------------------------------------------------- entry point

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
    """Open the window, or hand the files to the one that's open (instance.py)."""
    from .instance import main as start
    return start(argv)


def run(files: list[str], mode: str, lock) -> int:
    """The window, for the process that holds the one-window lock."""
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ConvertAll")
    app.setStyle("Fusion")
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ConvertAll.ConvertAll")

    # An update brings new right-click entries, and a moved app a new path: refresh a menu that
    # an older build or another folder registered. Only the installed app does this, so running
    # from source never repoints the menu.
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
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)  # only this user can hand us files
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_message(text: str):
        paths, how = parse_message(text)
        if how == "view":
            win.open_viewers(paths)
        elif paths:
            win.add_files_from_other_instance(paths, how == "extract")
        else:
            win.show()
            win.raise_()
            win.activateWindow()
    listen(server, on_message)

    if mode == "view" and files:  # just the model, in a window of its own; the main one stays hidden
        QTimer.singleShot(0, lambda: win.open_viewers([Path(f) for f in files]))
    else:
        win.show()
        if files:
            QTimer.singleShot(0, lambda: win.add_files_from_other_instance([Path(f) for f in files],
                                                                           mode == "extract"))
        else:  # load the converters while the window waits for a file, not before it shows
            QTimer.singleShot(150, registry._ensure_loaded)
    code = app.exec()
    if isinstance(win.job, Job) and win.job.isRunning():  # quit some other way mid-job: stop it first
        win.job.cancel()
        win.job.wait()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
