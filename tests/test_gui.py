"""The window, driven offscreen: drop files, check what's preselected, convert."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtWidgets import QApplication  # noqa: E402

from convertall import gui  # noqa: E402

from .conftest import needs  # noqa: E402
from .samples import Samples  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    monkeypatch.setattr(gui, "QSettings", lambda *a: settings)  # a new user, every time
    win = gui.Window()
    yield win
    win.close()


@pytest.fixture
def samples(tmp_path):
    return Samples(tmp_path / "samples")


def run(win):
    """Click Convert, but run the job on this thread so the test can wait for it."""
    jobs = []
    win.run_job = lambda job: (jobs.append(job), job.done.connect(win.job_done), job.run())
    win.start_convert()
    assert jobs, "nothing was started"
    return win.outputs


@pytest.mark.parametrize("fmt,expected", [
    ("cbz", "pdf"), ("cbt", "pdf"), ("png", "jpg"), ("jpg", "png"), ("heic", "jpg"), ("webp", "png"),
    ("json", "csv"), ("srt", "vtt"), ("ttf", "woff2"), ("step", "stl"), ("dcm", "jpg"), ("zip", "7z"),
    ("folder", "zip"), ("epub", "pdf"),
])
def test_new_user_gets_the_most_common_conversion(window, samples, fmt, expected):
    window.set_files([samples(fmt)])
    assert window.combo.currentData(QtCore.Qt.UserRole) == expected


@needs("ffmpeg")
def test_video_defaults_to_mp3(window, samples):
    window.set_files([samples("mp4")])
    assert window.combo.currentData(QtCore.Qt.UserRole) == "mp3"


def test_comic_to_pdf_from_the_window(window, samples):
    import pymupdf
    window.set_files([samples("cbz")])
    out, = run(window)
    assert out.suffix == ".pdf" and window.status.property("state") == "ok"
    with pymupdf.open(out) as doc:
        assert doc.page_count == 4


def test_remembers_what_this_user_picked(window, samples):
    png = samples("png")
    window.set_files([png])
    window.combo.setCurrentIndex(window.combo.findData("webp", QtCore.Qt.UserRole))
    out, = run(window)
    assert out.suffix == ".webp"
    window.set_files([png])
    assert window.combo.currentData(QtCore.Qt.UserRole) == "webp"
    window.set_files([samples("jpg")])  # another kind of file still gets the common pick
    assert window.combo.currentData(QtCore.Qt.UserRole) == "png"


def test_mixed_batch_offers_only_shared_targets(window, samples):
    window.set_files([samples("png"), samples("cbz")])
    offered = {window.combo.itemData(i, QtCore.Qt.UserRole) for i in range(window.combo.count())} - {None}
    assert {"pdf", "zip"} <= offered and "jpg" not in offered


def test_errors_are_shown_not_raised(window, tmp_path):
    bad = tmp_path / "broken.cbz"
    bad.write_bytes(b"PK\x03\x04 not really a zip")
    window.set_files([bad])
    assert window.combo.currentData(QtCore.Qt.UserRole) == "pdf"
    assert run(window) == []
    assert window.status.property("state") == "error" and "broken.cbz" in window.status.text()
