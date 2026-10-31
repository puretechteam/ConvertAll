"""The window, driven offscreen: drop files, check what's preselected, convert."""

import itertools
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
    wait_for_previews(app)


def wait_for_previews(app):
    """Dropping a 3D model starts loading its preview on a thread: let it finish."""
    import sys
    viewer = sys.modules.get("convertall.viewer")
    for job in list(viewer._RUNNING) if viewer else []:
        job.wait()
    app.processEvents()


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


def test_a_closed_window_is_freed(app, tmp_path, monkeypatch, samples):
    """Nothing may keep the window alive once it's closed and dropped (a lambda holding it on a child's
    signal did): Python then destroyed it at exit, after Qt, and crashed."""
    import gc
    settings = QtCore.QSettings(str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat)
    monkeypatch.setattr(gui, "QSettings", lambda *a: settings)
    win = gui.Window()
    win.set_files([samples("png")])
    win.picker.set_current("webp")
    run(win)
    win.close()
    app.processEvents()
    del win
    gc.collect()
    assert not [o for o in gc.get_objects() if isinstance(o, gui.Window)]


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


def test_forwarded_message_carries_what_to_do(tmp_path):
    a, b = tmp_path / "a.zip", tmp_path / "b.rar"
    assert gui.parse_message(f"{gui.EXTRACT_MARKER}\n{a}\n{b}\n") == ([a, b], "extract")
    assert gui.parse_message(f"{gui.VIEW_MARKER}\n{a}\n") == ([a], "view")
    assert gui.parse_message(f"{a}\n") == ([a], "convert")
    assert gui.parse_message("") == ([], "convert")


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
    script = ("import json, sys; from convertall import instance; "  # no QApplication: the launcher has none
              "files = json.load(open(sys.argv[1], encoding='utf-8')); "
              "sys.exit(0 if instance.forward(files, 'extract', sys.argv[2]) else 1)")
    sender = subprocess.Popen([sys.executable, "-c", script, str(tmp_path / "files.json"), name],
                              env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    deadline = time.monotonic() + 30
    while not got and time.monotonic() < deadline:
        app.processEvents()
    assert sender.wait(10) == 0
    server.close()
    assert gui.parse_message(got[0]) == ([tmp_path / os.path.basename(f) for f in files], "extract")


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
    monkeypatch.setattr(gui, "view_extensions", lambda: ["glb"])

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
        view_verb = rf"{root}\SystemFileAssociations\.glb\shell\ConvertAllView"
        assert value(view_verb, "MUIVerb") == "View with ConvertAll"
        assert value(view_verb, "MultiSelectModel") == "Single"
        assert "--view" in value(view_verb + r"\command")
        assert not gui.context_menu_outdated()
        real = gui._launch_command
        monkeypatch.setattr(gui, "_launch_command", lambda *f: real(*f).replace("convertall", "moved"))
        assert gui.context_menu_outdated()  # the same version from another folder takes the menu over
        monkeypatch.setattr(gui, "__version__", "0.9.0")
        assert not gui.context_menu_outdated()  # ...but an older copy never does
        monkeypatch.setattr(gui, "__version__", "99.0.0")
        assert gui.context_menu_outdated()
        gui.remove_context_menu()
        assert not gui.context_menu_installed()
        with pytest.raises(OSError):
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, zip_verb))
        with pytest.raises(OSError):  # emptied keys we created are gone
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\SystemFileAssociations\.rar"))
        with pytest.raises(OSError):
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\SystemFileAssociations\.glb"))
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\SystemFileAssociations\.zip\shell\Other"))
    finally:
        import subprocess
        subprocess.run(["reg", "delete", rf"HKCU\{root}", "/f"], capture_output=True, check=False)


# ---- 3D preview and viewer


def _preview(window, app, path):
    window.set_files([path])
    wait_for_previews(app)
    return window.drop.preview


def test_dropping_a_model_previews_it(window, app, samples):
    panel = _preview(window, app, samples("glb"))
    assert panel is not None and not panel.isHidden() and panel.model is not None
    assert panel.model.triangle_count == 92 and "92 triangles" in window.drop.sub.text()
    assert not window.drop.expand_btn.isHidden()
    window.set_files([samples("png")])  # not a model: the preview goes away
    assert panel.isHidden() and panel.model is None
    assert window.drop.sub.text().startswith(gui.describe("png") + " · ")  # and its size


def test_cad_parts_preview_too(window, app, samples):
    panel = _preview(window, app, samples("step"))
    assert panel.model is not None and panel.model.units == ""


def test_several_files_get_no_preview(window, app, samples):
    window.set_files([samples("glb"), samples("stl")])
    assert window.drop.preview is None or window.drop.preview.isHidden()


def test_a_broken_model_says_so_in_the_preview(window, app, tmp_path):
    bad = tmp_path / "broken.glb"
    bad.write_bytes(b"glTF\x02\x00\x00\x00 cut short")
    panel = _preview(window, app, bad)
    assert panel.model is None and panel.message.text() and window.drop.expand_btn.isHidden()


def test_expanding_reuses_the_loaded_model(window, app, samples):
    from convertall import viewer
    panel = _preview(window, app, samples("glb"))
    window.drop.expand_btn.click()
    big = viewer._OPEN[-1]
    try:
        assert big.panel.model is panel.model and big.panel.job is None
        assert big.stats.text().startswith("2 parts · 92 triangles") and big.wire.isEnabled()
    finally:
        big.close()


def test_view_with_convertall_opens_models_and_passes_the_rest_on(window, app, samples):
    from convertall import viewer
    before = len(viewer._OPEN)
    window.open_viewers([samples("stl"), samples("png")])
    try:
        assert len(viewer._OPEN) == before + 1
        assert window.files == [samples("png")]  # not a model: opened for converting
    finally:
        wait_for_previews(app)
        viewer._OPEN[-1].close()


def test_view_menu_covers_models_and_cad():
    exts = gui.view_extensions()
    assert {"glb", "fbx", "stl", "obj", "3mf", "usdz", "blend", "step", "stp", "igs"} <= set(exts)
    assert not {"dxf", "png", "zip"} & set(exts)


def test_menu_offers_discord_and_about_links_to_it(window):
    menu_btn = next(b for b in window.findChildren(gui.IconButton) if b.icon == "menu")
    texts = [a.text() for a in menu_btn.menu().actions()]
    assert "Help and chat on Discord" in texts and gui.DISCORD == "https://discord.gg/dRMRGCG9Fk"
    box = window.about()
    try:
        assert gui.DISCORD in box.text()
        assert any(lbl.openExternalLinks() for lbl in box.findChildren(gui.QLabel) if gui.DISCORD in lbl.text())
    finally:
        box.close()


def test_icon_buttons_paint_in_both_themes(window):
    for palette in (gui.DARK, gui.LIGHT):
        gui.THEME.update(palette)
        for b in window.findChildren(gui.IconButton):
            assert not b.grab().isNull()


# ---- what a route can't keep, the checks, settings and presets

def _chip(popup, fmt):
    return next(c for c in popup.chips if c.property("fmt") == fmt)


def test_chip_tooltip_says_route_and_losses(window, samples):
    popup = _open(window, samples, "png")
    assert "transparency" in _chip(popup, "jpg").toolTip()
    assert "parts" not in _chip(popup, "webp").toolTip()


@needs("libreoffice")  # the Word sample is made by LibreOffice
def test_chip_tooltip_names_the_route_through_pdf(window, samples):
    window.set_files([samples("docx")])
    window.picker.click()
    tip = _chip(window.picker.popup, "png").toolTip()
    assert "(via PDF)" in tip and "150 dpi" in tip


def test_status_and_details_after_a_lossy_conversion(window, tmp_path):
    import json

    import trimesh
    a, b = trimesh.creation.box(), trimesh.creation.icosphere()
    b.apply_translation([3, 0, 0])
    glb = tmp_path / "two.glb"
    glb.write_bytes(trimesh.Scene({"box": a, "ball": b}).export(file_type="glb"))
    window.set_files([glb])
    window.picker.set_current("stl")
    assert run(window)
    assert window.status.property("state") == "ok"
    assert window.status.text() == "Saved two.stl" and "parts are merged" in window.note.text()
    assert "Parts: 2 → 1" in window.status.toolTip() and "Parts: 2 → 1" in window.note.toolTip()
    assert not window.details_btn.isHidden()
    dialog = window.show_details()
    texts = [w.text() for w in dialog.findChildren(gui.QLabel)]
    assert any("GLB → STL via trimesh" in t for t in texts) and "As noted" in texts
    report = json.loads(dialog.copy())
    assert report[0]["target"] == "stl" and report[0]["warnings"] == []
    assert json.loads(gui.QGuiApplication.clipboard().text()) == report
    dialog.close()


def test_a_check_that_fails_turns_the_status_amber(window, tmp_path, monkeypatch):
    from convertall.converters import images
    monkeypatch.setitem(images.OWN_WRITERS, "psd", lambda img, dst: dst.write_bytes(b"8BPS garbage"))
    src = tmp_path / "a.png"
    src.write_bytes((Samples(tmp_path / "s"))("png").read_bytes())
    window.set_files([src])
    window.picker.set_current("psd")
    assert run(window)  # the file is kept
    assert window.status.property("state") == "warn" and "doesn't open as PSD" in window.note.text()


def test_options_show_only_what_the_format_takes(window, samples):
    window.set_files([samples("png")])
    panel = window.options_panel
    window.picker.set_current("jpg")
    assert not panel.isHidden() and list(panel.widgets) == ["quality", "max_size"]
    window.picker.set_current("bmp")
    assert list(panel.widgets) == ["max_size"]
    window.picker.set_current("zip")
    assert panel.isHidden()  # nothing to set: no panel at all
    assert not panel.body.isVisible()  # collapsed until asked
    assert panel.head.text() == "Options" and panel.summary() == "Default"


def test_options_and_presets_reach_the_conversion(window, samples, tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERTALL_PRESETS", str(tmp_path / "presets.json"))
    src = samples("png")
    window.set_files([src])
    window.picker.set_current("jpg")
    panel = window.options_panel
    panel.head.click()
    assert panel.body.isVisibleTo(window)
    assert panel.preset_names()[0] == "Default" and panel.pills["Default"].isChecked()
    panel.pills["Smaller for email and web"].click()
    assert panel.chosen()["quality"] == 75 and panel.widgets["quality"].value() == 75
    assert panel.widgets["max_size"].value() == 1920 and panel.widgets["max_size"].currentText() == "1920 px"
    assert panel.summary() == "Smaller for email and web"
    assert panel.pills["Smaller for email and web"].isChecked() and panel.save_pill is None
    jobs = []
    window.run_job = lambda job: jobs.append(job)
    window.start_convert()
    assert jobs[0].settings == {"quality": 75, "max_size": 1920}  # the preset's video and sound settings stay out
    box = panel.widgets["quality"]
    box.setValue(60)
    assert panel.widgets["quality"] is box  # typing in a box never rebuilds it under the cursor
    assert panel.current_preset() == "" and panel.save_pill is not None  # your own: offered for saving
    assert not any(p.isChecked() for p in panel.pills.values())
    monkeypatch.setattr(gui.QInputDialog, "getText", lambda *a, **k: ("Mine", True))
    panel._save_as()
    assert gui.options.preset("Mine")["quality"] == 60 and panel.current_preset() == "Mine"
    assert not panel.delete_btn.isHidden()
    panel._delete()
    assert "Mine" not in gui.options.all_presets()
    panel._reset()
    assert panel.chosen() == {} and panel.widgets["quality"].value() is None  # "Auto"
    assert panel.widgets["max_size"].currentText() == "Original"
    # a quality kept from photos changes nothing for an ebook's PDF: the pills say Default, as the header does
    panel.widgets["quality"].setValue(60)
    window.set_files([samples("epub")])
    window.picker.set_current("pdf")
    assert set(panel.keys) == {"page_size", "text_size"} and panel.summary() == "Default"
    assert panel.pills["Default"].isChecked() and panel.save_pill is None


def test_number_settings_take_a_listed_or_typed_value(window, samples):
    window.set_files([samples("png")])
    window.picker.set_current("jpg")
    panel = window.options_panel
    box = panel.widgets["max_size"]
    assert box.itemText(0) == "Original" and "1920 px" in [box.itemText(i) for i in range(box.count())]
    box.lineEdit().setText("1500")
    box.lineEdit().editingFinished.emit()
    assert panel.chosen() == {"max_size": 1500} and box.currentText() == "1500 px"
    box.lineEdit().setText("12 parsecs")  # not a number in range: back to what it was
    box.lineEdit().editingFinished.emit()
    assert panel.chosen() == {"max_size": 1500} and box.currentText() == "1500 px"
    box.lineEdit().setText("")
    box.lineEdit().editingFinished.emit()
    assert panel.chosen() == {} and box.currentText() == "Original"
    slider = panel.widgets["quality"]
    slider.bar.setValue(80)
    assert panel.chosen() == {"quality": 80} and slider.label.text() == "80"
    slider.bar.setValue(0)
    assert panel.chosen() == {} and slider.label.text() == "Auto"
    assert slider.label.toolTip() == "Auto (92 for JPG)"


def test_settings_say_only_what_applies(window, samples):
    src = samples("mp4")
    if src is None:
        pytest.skip("needs FFmpeg to make a sample video")
    window.set_files([src])
    window.picker.set_current("webm")
    panel = window.options_panel
    fps, quality = panel.widgets["fps"], panel.widgets["video_quality"]
    assert fps.itemText(0) == "Original"  # not "(12 for GIF)": this is WebM
    assert [quality.itemText(i) for i in range(quality.count())] == ["Balanced", "Smaller", "Best"]
    window.picker.set_current("gif")
    assert panel.widgets["fps"].itemText(0) == "Original (12 for GIF)"


def test_the_window_never_gets_smaller_than_what_it_shows(window, samples):
    window.show()
    window.set_files([samples("mp4") or samples("png")])
    window.picker.set_current("gif" if "gif" in window.picker.formats() else "jpg")
    window.options_panel.head.click()
    window.resize(window.width(), 200)
    gui.QApplication.processEvents()
    lay = window.layout()
    widgets = [lay.itemAt(i).widget() or lay.itemAt(i).layout() for i in range(lay.count())]
    shown = [w.geometry() for w in widgets if w is not None and (not hasattr(w, "isVisible") or w.isVisible())]
    assert all(a.bottom() < b.top() for a, b in itertools.pairwise(shown))  # nothing overlaps
    assert window.height() >= window.minimumSizeHint().height()


def test_options_are_remembered(app, tmp_path, monkeypatch, samples):
    settings = QtCore.QSettings(str(tmp_path / "s.ini"), QtCore.QSettings.IniFormat)
    monkeypatch.setattr(gui, "QSettings", lambda *a: settings)
    first = gui.Window()
    first.set_files([samples("png")])
    first.picker.set_current("jpg")
    first.options_panel.widgets["quality"].setValue(70)
    first.close()
    second = gui.Window()
    assert second.options_panel.chosen() == {"quality": 70}
    second.close()


@pytest.mark.skipif(not gui.sys.platform.startswith("win"), reason="Windows shortcut")
def test_start_menu_shortcut(tmp_path, monkeypatch):
    lnk = tmp_path / "Programs" / "ConvertAll.lnk"
    monkeypatch.setattr(gui, "start_menu_path", lambda: lnk)
    assert not gui.start_menu_installed()
    gui.install_start_menu()
    assert gui.start_menu_installed() and lnk.read_bytes()[:4] == b"L\0\0\0"  # a real shell link
    gui.remove_start_menu()
    assert not gui.start_menu_installed()


def test_preset_is_judged_by_what_this_conversion_takes(window, samples, tmp_path, monkeypatch):
    """Quality 75 and max size 1920 are "Smaller for email and web" for a JPG, even though that
    preset also sets video and sound settings a picture doesn't take."""
    monkeypatch.setenv("CONVERTALL_PRESETS", str(tmp_path / "presets.json"))
    window.set_files([samples("png")])
    window.picker.set_current("jpg")
    panel = window.options_panel
    panel.widgets["quality"].setValue(75)
    panel.widgets["max_size"].setValue(1920)
    assert panel.current_preset() == "Smaller for email and web"
    panel.widgets["quality"].setValue(74)
    assert panel.current_preset() == ""


def test_installing_an_engine_refreshes_the_formats(window, samples, monkeypatch):
    window.set_files([samples("png")])
    filled = []
    monkeypatch.setattr(gui.EnginesDialog, "exec", lambda self: 0)
    monkeypatch.setattr(window, "fill_picker", lambda: filled.append(True))
    window.show_engines()
    assert filled == [True]


def test_start_menu_error_without_a_message(monkeypatch, tmp_path):
    monkeypatch.setattr(gui, "start_menu_path", lambda: tmp_path / "x.lnk")
    monkeypatch.setattr(gui.subprocess, "run", lambda *a, **k: gui.subprocess.CompletedProcess(a, 1, "", "  \n"))
    with pytest.raises(OSError, match="couldn't write the shortcut"):
        gui.install_start_menu()


# ---- Cancel, and closing the window while a conversion runs

def _slow_route(monkeypatch, tmp_path):
    """txt -> pdf through an engine that runs 30 s (unless killed); returns a function that
    gives the engine's pid once it has started."""
    import sys

    from convertall import engines, pipeline, registry
    pid_file = tmp_path / "engine.pid"
    script = tmp_path / "engine.py"
    script.write_text(f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(30)\n")

    def slow(src, dst, a, b):
        engines.run([sys.executable, str(script)])
        dst.write_text("done")
    route = registry.Route("txt", "pdf", [registry.Edge("txt", "pdf", slow)])
    monkeypatch.setattr(pipeline, "find_route", lambda *a, **k: route)
    return lambda: int(pid_file.read_text()) if pid_file.exists() and pid_file.read_text() else None


def _pump(app, until, seconds=10):
    import time
    deadline = time.monotonic() + seconds
    while not until() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return until()


def _start_slow_job(app, window, tmp_path, monkeypatch, files=1):
    pid = _slow_route(monkeypatch, tmp_path)
    srcs = []
    for i in range(files):
        src = tmp_path / f"in{i}.txt"
        src.write_text("x")
        srcs.append(src)
    window.show()
    window.files, window.fmts = srcs, ["txt"] * files
    job = gui.Job(srcs, "pdf", [])
    window.run_job(job)
    assert _pump(app, lambda: pid() is not None), "the engine never started"
    return job, pid(), srcs


def _engine_alive(pid):
    import subprocess
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
    return str(pid) in out.stdout


@pytest.mark.skipif(os.name != "nt", reason="checks the engine with tasklist")
def test_closing_mid_conversion_stops_it_and_closes(app, window, tmp_path, monkeypatch):
    job, pid, _ = _start_slow_job(app, window, tmp_path, monkeypatch)
    assert window.convert_btn.text() == "Cancel" and window.convert_btn.isEnabled()
    monkeypatch.setattr(window, "confirm_stop", lambda: True)  # "Stop and close"
    import time
    asked = time.monotonic()
    window.close()
    assert not window.isVisible()  # gone from the screen at once
    assert _pump(app, lambda: window.job is None)
    assert time.monotonic() - asked < 2
    assert job.isFinished() or job.wait(2000)
    assert not _engine_alive(pid)
    assert not (tmp_path / "in0.pdf").exists()


@pytest.mark.skipif(os.name != "nt", reason="checks the engine with tasklist")
def test_keep_converting_leaves_the_job_running_then_cancel_stops_it(app, window, tmp_path, monkeypatch):
    job, pid, _ = _start_slow_job(app, window, tmp_path, monkeypatch, files=3)
    monkeypatch.setattr(window, "confirm_stop", lambda: False)  # "Keep converting"
    window.close()
    assert window.isVisible() and job.isRunning() and _engine_alive(pid)
    window.convert_clicked()  # the Convert button is Cancel while it runs
    assert window.convert_btn.text() == "Stopping…" and not window.convert_btn.isEnabled()
    assert _pump(app, lambda: window.job is None)
    assert not _engine_alive(pid)
    assert window.status.text() == "Stopped" and window.note.text() == "Nothing was saved"
    assert window.convert_btn.text() == "Convert"
    assert not list(tmp_path.glob("in*.pdf"))


def test_cancel_between_files_keeps_the_ones_done(window, tmp_path, monkeypatch):
    from convertall import pipeline
    srcs = []
    for i in range(3):
        src = tmp_path / f"in{i}.txt"
        src.write_text("x")
        srcs.append(src)
    job = gui.Job(srcs, "pdf", [])

    def convert(f, target, report=None, options=None):
        out = f.with_suffix(".pdf")
        out.write_text("done")
        job.cancel()  # Cancel clicked while the first file was converting: it still finishes
        return out
    monkeypatch.setattr(pipeline, "convert", convert)
    window.files, window.fmts = srcs, ["txt"] * 3
    _run_now(window)
    window.run_job(job)
    assert [p.name for p in window.outputs] == ["in0.pdf"]
    assert window.status.text() == "Stopped"
    assert window.note.text() == "1 saved, 2 not converted"
