"""One ConvertAll window per user. The first launch takes a lock and opens the window; later
launches (a right-click on more files) hand their files to it and exit. That hand-off needs only
QtCore and QtNetwork, so it runs before the window code and the converters are imported."""

from __future__ import annotations

import getpass
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalSocket

SERVER_NAME = f"ConvertAll-{getpass.getuser()}"

# A command-line flag, and the first line of a forwarded message, saying what to do with the
# files. Without one they're opened for converting.
EXTRACT_MARKER = "--extract"
VIEW_MARKER = "--view"
MODES = {EXTRACT_MARKER: "extract", VIEW_MARKER: "view"}
WAIT_S = 15  # how long a launch waits for the open window to answer


def forward(files: list[str], mode: str = "convert", server: str = SERVER_NAME) -> bool:
    """If ConvertAll is already open, hand it our files and let it handle them."""
    sock = QLocalSocket()
    sock.connectToServer(server)
    if not sock.waitForConnected(300):
        return False
    marker = [m for m, name in MODES.items() if name == mode]
    sock.write("\n".join(marker + files).encode("utf-8"))
    while sock.bytesToWrite() and sock.waitForBytesWritten(1000):
        pass  # a long list goes out in several writes; this process may exit right after
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.UnconnectedState:
        sock.waitForDisconnected(1000)
    return True


def parse_message(data: str) -> tuple[list[Path], str]:
    """(files, "convert" | "extract" | "view")"""
    lines = [ln for ln in data.splitlines() if ln.strip()]
    mode = MODES.get(lines[0], "convert") if lines else "convert"
    return [Path(p) for p in lines[mode != "convert":]], mode


def main(argv: list[str] | None = None) -> int:
    """Open the window, or hand the files to the one that's open."""
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if a != "--gui"]
    mode = next((MODES[a] for a in argv if a in MODES), "convert")
    files = [str(Path(a).resolve()) for a in argv if a not in MODES]
    lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{SERVER_NAME}.lock"))
    deadline = time.monotonic() + WAIT_S
    while not lock.tryLock(0):  # QLockFile frees a lock its owner left behind when it crashed
        if forward(files, mode):  # the open one may still be starting, or closing
            return 0
        if time.monotonic() > deadline:
            _busy()
            return 1
        time.sleep(0.1)
    from .gui import run
    return run(files, mode, lock)


def _busy() -> None:
    """The open window holds the lock but isn't answering: say so, rather than open a second."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841 - a dialog needs one
    QMessageBox.warning(None, "ConvertAll", "ConvertAll is already open but isn't answering. "
                        "Close it (or end it in Task Manager) and try again.")
