"""Stopping a conversion part-way: a flag the steps look at, and the engines it kills.

The window's job holds a Token and runs its conversions inside using(token). Steps call check()
where stopping is safe (between files, between route steps, between chunks of an extraction);
engines.run() hands every program it starts to track(), so cancel() ends them at once instead of
waiting for them to finish."""

from __future__ import annotations

import contextlib
import contextvars
import subprocess
import sys
import threading

from .errors import ConversionError


class Cancelled(ConversionError):
    """The user stopped it. Not a failure: nothing is reported as wrong with the file."""

    def __init__(self, message: str = "Stopped"):
        super().__init__(message)


class Token:
    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._procs: set[subprocess.Popen] = set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            _kill(proc)

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()

    @contextlib.contextmanager
    def track(self, proc: subprocess.Popen):
        with self._lock:
            self._procs.add(proc)
        try:
            if self._event.is_set():  # cancelled while it was starting
                _kill(proc)
            yield proc
        finally:
            with self._lock:
                self._procs.discard(proc)


def _kill(proc: subprocess.Popen) -> None:
    """The program and everything it started: LibreOffice's soffice.exe runs soffice.bin, and
    killing only the first would leave the second converting (and holding the files)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    if proc.poll() is None:
        proc.kill()


_current: contextvars.ContextVar[Token | None] = contextvars.ContextVar("cancel", default=None)


@contextlib.contextmanager
def using(token: Token):
    """Run the conversions inside with this token: its cancel() reaches every step."""
    reset = _current.set(token)
    try:
        yield token
    finally:
        _current.reset(reset)


def current() -> Token | None:
    return _current.get()


def check() -> None:
    """Raise Cancelled if the conversion running on this thread was stopped."""
    token = _current.get()
    if token is not None:
        token.check()


@contextlib.contextmanager
def track(proc: subprocess.Popen):
    """Kill proc if the conversion running on this thread is stopped while it runs."""
    token = _current.get()
    if token is None:
        yield proc
    else:
        with token.track(proc):
            yield proc
