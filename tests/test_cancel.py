"""Stopping a conversion: Cancel, and closing the window while one runs. Engines are killed (with
whatever they started), nothing half-made is left, and the window closes cleanly."""

import os
import subprocess
import sys
import threading
import time
import zipfile

import pytest

from convertall import cancel, engines, pipeline, registry
from convertall.converters import documents
from convertall.errors import ConversionError


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             creationflags=engines.NO_WINDOW, check=False).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _slow_engine(tmp_path, grandchild: bool = False) -> tuple[list[str], list]:
    """A command that writes its pid (and, with grandchild, starts a second program that does too)
    and then runs for 30 s."""
    pids = tmp_path / "pids.txt"
    script = tmp_path / "engine.py"
    script.write_text(f"""import os, subprocess, sys, time
if {grandchild!r} and len(sys.argv) == 1:
    subprocess.Popen([sys.executable, __file__, "child"])
with open({str(pids)!r}, "a") as f:
    f.write(str(os.getpid()) + " ")
time.sleep(30)
""")

    def read() -> list[int]:
        return [int(x) for x in pids.read_text().split()] if pids.exists() else []
    return [sys.executable, str(script)], read


@pytest.mark.parametrize("grandchild", [False, True], ids=["engine", "engine-and-its-child"])
def test_cancel_kills_a_running_engine_within_a_second(tmp_path, grandchild):
    cmd, pids = _slow_engine(tmp_path, grandchild)
    token = cancel.Token()
    started = time.monotonic()
    with cancel.using(token):
        deadline = started + 10
        timer = threading.Thread(target=lambda: (_wait_for(lambda: len(pids()) == 1 + grandchild, deadline),
                                                 token.cancel()))
        timer.start()
        with pytest.raises(cancel.Cancelled):
            engines.run(cmd)
        timer.join()
    stopped = time.monotonic()
    assert stopped - started < 10
    time.sleep(0.3)
    assert len(pids()) == 1 + grandchild
    assert not [p for p in pids() if _alive(p)]  # the engine, and what it started, are gone


def _wait_for(cond, deadline: float) -> None:
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_cancelled_engine_stops_within_one_second_of_cancel(tmp_path):
    cmd, pids = _slow_engine(tmp_path)
    token = cancel.Token()
    when = {}

    def stop():
        _wait_for(lambda: pids(), time.monotonic() + 10)
        when["cancel"] = time.monotonic()
        token.cancel()
    t = threading.Thread(target=stop)
    t.start()
    with cancel.using(token), pytest.raises(cancel.Cancelled):
        engines.run(cmd)
    took = time.monotonic() - when["cancel"]
    t.join()
    assert took < 1.0, f"engine took {took:.2f} s to stop"


def test_engine_timeout_still_kills_and_raises(tmp_path):
    cmd, pids = _slow_engine(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        engines.run(cmd, timeout=1)
    time.sleep(0.3)
    assert pids() and not _alive(pids()[0])


def test_engine_failures_still_say_why():
    with pytest.raises(ConversionError, match="boom"):
        engines.run([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
    assert engines.run([sys.executable, "-c", "print('hello')"]).stdout.strip() == "hello"


def _fake_route(monkeypatch, func):
    route = registry.Route("txt", "pdf", [registry.Edge("txt", "pdf", func)])
    monkeypatch.setattr(pipeline, "find_route", lambda *a, **k: route)


def _temp_dirs() -> set[str]:
    import tempfile
    from pathlib import Path
    return {p.name for p in Path(tempfile.gettempdir()).glob("convertall-*")}


def test_cancelled_conversion_writes_nothing_and_cleans_up(tmp_path, monkeypatch):
    cmd, pids = _slow_engine(tmp_path)

    def slow(src, dst, a, b):
        engines.run(cmd)
        dst.write_text("done")
    _fake_route(monkeypatch, slow)
    src = tmp_path / "in.txt"
    src.write_text("x")
    out = tmp_path / "out"
    before = _temp_dirs()
    token = cancel.Token()
    t = threading.Thread(target=lambda: (_wait_for(pids, time.monotonic() + 10), token.cancel()))
    t.start()
    with cancel.using(token), pytest.raises(cancel.Cancelled):
        pipeline.convert(src, "pdf", out_dir=out)
    t.join()
    assert not list(out.iterdir())
    assert _temp_dirs() <= before


def test_cancel_during_the_last_step_keeps_nothing(tmp_path, monkeypatch):
    token = cancel.Token()

    def quick(src, dst, a, b):
        dst.write_text("done")
        token.cancel()  # stopped just as the step finished
    _fake_route(monkeypatch, quick)
    src = tmp_path / "in.txt"
    src.write_text("x")
    with cancel.using(token), pytest.raises(cancel.Cancelled):
        pipeline.convert(src, "pdf", out_dir=tmp_path / "out")
    assert not list((tmp_path / "out").iterdir())


class _StopAfter(cancel.Token):
    """Cancels itself once the extraction has looked at the flag n times."""

    def __init__(self, n: int):
        super().__init__()
        self.n = n

    def check(self) -> None:
        self.n -= 1
        if self.n < 0:
            self.cancel()
        super().check()


def test_cancelled_extraction_leaves_no_hidden_folder(tmp_path):
    arc = tmp_path / "big.zip"
    with zipfile.ZipFile(arc, "w", zipfile.ZIP_STORED) as z:
        for i in range(6):
            z.writestr(f"part{i}.bin", os.urandom(3 << 20))  # 3 MB each: several chunks
    out = tmp_path / "out"
    with cancel.using(_StopAfter(4)), pytest.raises(cancel.Cancelled):
        pipeline.extract(arc, out_dir=out)
    assert not list(out.iterdir())  # no ".convertall-*" left in the user's folder


def test_libreoffice_wait_stops_on_cancel_and_has_a_limit(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    with documents._one_at_a_time(profile):  # another conversion holds LibreOffice
        result = {}

        def wait(limit):
            try:
                with documents._one_at_a_time(profile, limit=limit):
                    result["got"] = True
            except Exception as exc:  # noqa: BLE001 - the test looks at what it was
                result["exc"] = exc

        token = cancel.Token()
        started = time.monotonic()
        t = threading.Thread(target=lambda: _in_token(token, lambda: wait(60)))
        t.start()
        time.sleep(0.3)
        token.cancel()
        t.join(5)
        assert isinstance(result.get("exc"), cancel.Cancelled)
        assert time.monotonic() - started < 2

        result.clear()
        started = time.monotonic()
        wait(0.5)
        assert isinstance(result.get("exc"), ConversionError) and "still busy" in str(result["exc"])
        assert 0.4 < time.monotonic() - started < 3
    with documents._one_at_a_time(profile, limit=1):  # free again once the other one is done
        pass


def _in_token(token, fn):
    with cancel.using(token):
        fn()
