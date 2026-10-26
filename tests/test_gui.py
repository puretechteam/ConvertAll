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
    assert window.picker.current() == expected


@needs("ffmpeg")
def test_video_defaults_to_mp3(window, samples):
    window.set_files([samples("mp4")])
    assert window.picker.current() == "mp3"


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
    window.picker.set_current("webp")
    out, = run(window)
    assert out.suffix == ".webp"
    window.set_files([png])
    assert window.picker.current() == "webp"
    window.set_files([samples("jpg")])  # another kind of file still gets the common pick
    assert window.picker.current() == "png"


def test_mixed_batch_offers_only_shared_targets(window, samples):
    window.set_files([samples("png"), samples("cbz")])
    offered = set(window.picker.formats())
    assert {"pdf", "zip"} <= offered and "jpg" not in offered


def test_errors_are_shown_not_raised(window, tmp_path):
    bad = tmp_path / "broken.cbz"
    bad.write_bytes(b"PK\x03\x04 not really a zip")
    window.set_files([bad])
    assert window.picker.current() == "pdf"
    assert run(window) == []
    assert window.status.property("state") == "error" and "broken.cbz" in window.status.text()


# ---- the format panel


def _open(window, samples, fmt="jpg"):
    window.set_files([samples(fmt)])
    window.picker.click()
    popup = window.picker.popup
    assert popup is not None and popup.isVisible()
    return popup


def _chip_formats(popup):
    return [c.property("fmt") for c in popup.chips]


def test_panel_groups_formats_and_suggests_first(window, samples):
    popup = _open(window, samples)
    fmts = _chip_formats(popup)
    assert fmts[0] == "png"  # the Suggested row comes first
    assert sorted(set(fmts)) == sorted(window.picker.formats())
    selected = [c.property("fmt") for c in popup.chips if c.property("selected")]
    assert set(selected) == {"png"}


def test_search_filters_and_enter_picks(window, samples):
    popup = _open(window, samples)
    popup.search.setText(".web")
    assert _chip_formats(popup) == ["webp", "webm"] or set(_chip_formats(popup)) <= {"webp", "webm"}
    from PySide6.QtTest import QTest
    QTest.keyClick(popup.search, QtCore.Qt.Key_Return)
    assert window.picker.current() == "webp" and not popup.isVisible()


def test_search_by_full_name(window, samples):
    popup = _open(window, samples)
    popup.search.setText("bitmap")
    assert "bmp" in _chip_formats(popup)


def test_arrow_keys_move_through_the_grid(window, samples):
    from PySide6.QtTest import QTest
    popup = _open(window, samples)
    QTest.keyClick(popup.search, QtCore.Qt.Key_Down)
    assert popup.focusWidget() is popup.chips[0] or QApplication.focusWidget() is popup.chips[0]
    QTest.keyClick(popup.chips[0], QtCore.Qt.Key_Down)  # one row down = COLUMNS chips on
    QTest.keyClick(popup.chips[gui.FormatPopup.COLUMNS], QtCore.Qt.Key_Return)
    assert window.picker.current() == popup.chips[gui.FormatPopup.COLUMNS].property("fmt")


def test_formats_needing_an_install_are_marked(window, samples, monkeypatch):
    real = gui.engines.find
    monkeypatch.setattr(gui.engines, "find", lambda k: None if k == "libreoffice" else real(k))
    gui.engines.refresh()
    popup = _open(window, samples, "pdf")
    doc = next(c for c in popup.chips if c.property("fmt") == "doc")
    assert doc.property("needs") is True and "LibreOffice" in doc.toolTip()
    assert any(lbl.objectName() == "legend" for lbl in popup.findChildren(gui.QLabel))


def test_no_conversions_disables_the_picker(window, tmp_path):
    odd = tmp_path / "mystery.qqq"
    odd.write_bytes(b"\x00\x01 nothing anyone knows")
    window.set_files([odd])
    if not window.routes:
        assert not window.picker.isEnabled() and window.picker.current() is None
