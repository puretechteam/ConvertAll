"""The window, driven offscreen: drop files, check what's preselected, convert."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtWidgets import QApplication

from convertall import gui

from .conftest import needs
from .samples import Samples


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


# ---- right-click "Extract with ConvertAll"


def test_forwarded_message_carries_the_extract_marker(tmp_path):
    a, b = tmp_path / "a.zip", tmp_path / "b.rar"
    assert gui.parse_message(f"{gui.EXTRACT_MARKER}\n{a}\n{b}\n") == ([a, b], True)
    assert gui.parse_message(f"{a}\n") == ([a], False)


def test_a_long_forwarded_file_list_arrives_whole(app, tmp_path):
    """A second ConvertAll process hands its files to the open window, as Explorer causes."""
    import json
    import subprocess
    import sys
    import time

    from PySide6.QtNetwork import QLocalServer
    name = f"ConvertAll-test-{os.getpid()}"
    server = QLocalServer()
    QLocalServer.removeServer(name)
    assert server.listen(name)
    got = []
    gui.listen(server, got.append)
    files = [str(tmp_path / f"file {i:05d} with a longish name é.txt") for i in range(5000)]  # ~400 KB
    (tmp_path / "files.json").write_text(json.dumps(files), encoding="utf-8")
    script = ("import json, sys; from PySide6.QtWidgets import QApplication; from convertall import gui; "
              "app = QApplication([]); files = json.load(open(sys.argv[1], encoding='utf-8')); "
              "sys.exit(0 if gui._forward_to_running(files, True, sys.argv[2]) else 1)")
    sender = subprocess.Popen([sys.executable, "-c", script, str(tmp_path / "files.json"), name],
                              env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    deadline = time.monotonic() + 30
    while not got and time.monotonic() < deadline:
        app.processEvents()
    assert sender.wait(10) == 0
    server.close()
    assert gui.parse_message(got[0]) == ([tmp_path / os.path.basename(f) for f in files], True)


def _run_now(win):
    """Jobs run on this thread so the test can wait for them."""
    win.run_job = lambda job: (setattr(win, "job", job), job.done.connect(win.job_done), job.run())


def test_right_clicked_archives_extract_as_one_batch(window, samples, tmp_path):
    from convertall.converters import archives
    zips = []
    for name in ("first", "second"):
        z = tmp_path / f"{name}.zip"
        archives.compress(samples("folder"), z, "zip")
        zips.append(z)
    _run_now(window)
    for z in zips:  # Explorer starts one process per file; each forwards its file
        window.add_files_from_other_instance([z], extract=True)
    assert window.extract_timer.isActive() and window.pending_extract == zips
    window.extract_timer.stop()
    window.extract_pending()
    assert len(window.outputs) == 2 and all(o.is_dir() for o in window.outputs)
    assert window.status.text() == "Done · 2 files"


def test_archives_arriving_mid_extraction_wait_their_turn(window, samples, tmp_path):
    window.job = object()  # something is running
    window.add_files_from_other_instance([samples("zip")], extract=True)
    window.extract_timer.stop()
    window.extract_pending()
    assert window.pending_extract  # kept for later
    window.job = None
    _run_now(window)
    window.job_done([], [])
    assert window.extract_timer.isActive()


def test_extract_refuses_what_isnt_an_archive(window, samples):
    window.add_files_from_other_instance([samples("png")], extract=True)
    window.extract_timer.stop()
    window.extract_pending()
    assert window.status.property("state") == "error" and "isn't an archive" in window.status.text()


def test_extract_menu_covers_archives_but_not_comics():
    exts = gui.extract_extensions()
    assert {"zip", "rar", "7z", "gz", "tgz", "iso", "jar", "001"} <= set(exts)
    assert not {"cbz", "cbr", "txt", "docx", "chm", "lit"} & set(exts)


@pytest.mark.skipif(not gui.sys.platform.startswith("win"), reason="Windows registry")
def test_registers_extract_on_archives_and_convert_elsewhere(monkeypatch):
    import winreg
    root = r"Software\ConvertAll-test"
    monkeypatch.setattr(gui, "_STAR_KEY", rf"{root}\*\shell\ConvertAll")
    monkeypatch.setattr(gui, "_DIR_KEY", rf"{root}\Directory\shell\ConvertAll")
    monkeypatch.setattr(gui, "_SFA", rf"{root}\SystemFileAssociations")
    monkeypatch.setattr(gui, "extract_extensions", lambda: ["zip", "rar"])

    def value(key, name=""):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{root}\SystemFileAssociations\.zip\shell\Other"):
            pass  # another app's verb on .zip: must survive our removal
        gui.install_context_menu()
        assert value(gui._STAR_KEY, "MUIVerb") == "Convert with ConvertAll"
        assert value(gui._STAR_KEY, "Version") == gui.__version__
        zip_verb = rf"{root}\SystemFileAssociations\.zip\shell\ConvertAll"
        assert value(zip_verb, "MUIVerb") == "Extract with ConvertAll"
        assert "--extract" in value(zip_verb + r"\command")
        assert not gui.context_menu_outdated()
        monkeypatch.setattr(gui, "__version__", "99.0.0")
        assert gui.context_menu_outdated()
        gui.remove_context_menu()
        assert not gui.context_menu_installed()
        with pytest.raises(OSError):
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, zip_verb))
        with pytest.raises(OSError):  # emptied keys we created are gone
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\SystemFileAssociations\.rar"))
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\SystemFileAssociations\.zip\shell\Other"))
    finally:
        import subprocess
        subprocess.run(["reg", "delete", rf"HKCU\{root}", "/f"], capture_output=True, check=False)
