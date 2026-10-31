"""Hostile and broken files, built here: what a downloaded file must not be able to do (read other
files, fill memory, run a program from the Downloads folder), and messages instead of tracebacks."""

import gzip
import io
import json
import shutil
import subprocess
import sys
import zipfile

import pytest
from PIL import Image

from convertall import assurance, engines, instance, pipeline, safety
from convertall.converters import maps, media, pandoc
from convertall.errors import ConversionError

needs_pandoc = pytest.mark.skipif(not engines.available("pandoc"), reason="needs Pandoc")
SECRET = "SECRET-TOKEN-4711"


def test_local_files_come_from_the_folder_or_one_up(tmp_path):
    (tmp_path / "secret.txt").write_text(SECRET)
    book = tmp_path / "book"
    (book / "Text").mkdir(parents=True)
    (book / "Images").mkdir()
    (book / "Images" / "a.png").write_bytes(b"png")
    (book / "Text" / "b.png").write_bytes(b"png")
    base = book / "Text"
    assert safety.local_file(base, "b.png") == (base / "b.png").resolve()
    assert safety.local_file(base, "../Images/a.png") == (book / "Images" / "a.png").resolve()
    assert safety.local_file(base, "b.png?x=1#top") == (base / "b.png").resolve()
    for bad in ("../../secret.txt", str(tmp_path / "secret.txt"), "C:/Windows/win.ini",
                "file:///C:/Windows/win.ini", "//server/share/a.png", "\\\\server\\share\\a.png",
                "http://example.com/a.png", "missing.png", "../Images"):
        assert safety.local_file(base, bad) is None, bad


def test_read_capped_stops_at_the_limit():
    assert safety.read_capped(io.BytesIO(b"x" * 10), "f", limit=10) == b"x" * 10
    with pytest.raises(safety.Refused, match="unpacks to more than"):
        safety.read_capped(io.BytesIO(b"x" * 11), "f", limit=10)


@needs_pandoc
def test_pandoc_include_lines_cant_read_other_files(tmp_path):
    (tmp_path / "secret.txt").write_text(SECRET)
    doc = tmp_path / "a" / "b" / "doc.rst"
    doc.parent.mkdir(parents=True)
    doc.write_text("Title\n=====\n\n.. include:: ../../secret.txt\n\nText.\n", encoding="utf-8")
    for fmt in ("md", "html"):
        out = pipeline.convert(doc, fmt, tmp_path / fmt)
        assert SECRET not in out.read_text(encoding="utf-8")
        assert "Text." in out.read_text(encoding="utf-8")


@needs_pandoc
@pytest.mark.parametrize("fmt", ["docx", "odt", "epub", "html"])
def test_pandoc_still_carries_pictures_from_the_folder(tmp_path, fmt):
    folder = tmp_path / "doc"
    (folder / "img").mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(folder / "img" / "pic.png")
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "outside.png")
    src = folder / "doc.rst"
    src.write_text("Title\n=====\n\n.. image:: img/pic.png\n\n.. image:: ../../outside.png\n", encoding="utf-8")
    out = pipeline.convert(src, fmt, tmp_path / "out")
    if fmt == "html":
        assert out.read_text(encoding="utf-8").count("data:image/png") == 1
    else:
        with zipfile.ZipFile(out) as z:
            assert sum(n.lower().endswith(".png") for n in z.namelist()) == 1
    assert not list((tmp_path / "out").glob("*.json"))


def test_embed_pictures_walks_deep_documents_without_recursion(tmp_path):
    Image.new("RGB", (4, 4)).save(tmp_path / "p.png")
    node = {"t": "Image", "c": [["", [], []], [], ["p.png", ""]]}
    ast = {"blocks": [node]}
    for _ in range(50_000):  # far deeper than Python's recursion limit
        ast = {"t": "Div", "c": [ast]}
    assert pandoc.embed_pictures(ast, tmp_path) == 1
    assert node["c"][2][0].startswith("data:image/png;base64,")


def test_svgz_bomb_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "INNER_LIMIT", 1 << 20)
    bomb = tmp_path / "bomb.svgz"
    bomb.write_bytes(gzip.compress(b"<svg xmlns='http://www.w3.org/2000/svg'>" + b" " * (3 << 20) + b"</svg>"))
    with pytest.raises(ConversionError, match="unpacks to more than"):
        pipeline.convert(bomb, "pdf", tmp_path / "out")


def test_damaged_svgz_says_so(tmp_path):
    bad = tmp_path / "bad.svgz"
    bad.write_bytes(gzip.compress(b"<svg/>" * 100)[:30])
    with pytest.raises(ConversionError, match="damaged"):
        pipeline.convert(bad, "pdf", tmp_path / "out")


def test_kmz_bomb_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "INNER_LIMIT", 1 << 20)
    bomb = tmp_path / "bomb.kmz"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", b"<kml>" + b" " * (3 << 20) + b"</kml>")
    with pytest.raises(ConversionError, match="unpacks to more than"):
        maps.read_kmz(bomb)


@pytest.mark.parametrize("data", [b"[1, 2]", b'{"type": "Feature", "geometry": {"type": "Point", "coordinates": ["a", "b"]}}',
                                  b'{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": 5}]}',
                                  b'{"type": "Feature", "geometry": {"type": "LineString", "coordinates": 7}}'])
def test_odd_geojson_gets_a_message(data):
    with pytest.raises(ConversionError, match="GeoJSON"):
        maps.read_geojson(data)


def test_programs_in_the_current_folder_are_never_used(tmp_path, monkeypatch):
    """Windows runs a program from the current folder before PATH; a Downloads folder holding a
    fake "pandoc.exe" must not be picked up."""
    shutil.copy(sys.executable, tmp_path / "ca-test-engine.exe")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)  # as if someone took it away
    monkeypatch.setenv("PATH", r"C:\Windows")
    monkeypatch.setattr(engines, "_registry_path", lambda: "")
    monkeypatch.setitem(engines.ENGINES, "catest", engines.Engine("catest", "Test", "ca-test-engine", "", ""))
    engines.refresh()
    try:
        assert engines.find("catest") is None
    finally:
        engines.refresh()


def test_ffmpeg_reads_local_files_only(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(engines, "require", lambda key: key)
    monkeypatch.setattr(engines, "run", lambda args, **kw: calls.append(args))
    media.ffmpeg(tmp_path / "a.m3u8", tmp_path / "a.mp4", [])
    args = calls[0]
    assert args[args.index("-protocol_whitelist") + 1] == "file"
    assert args.index("-protocol_whitelist") < args.index("-i")


def test_checking_audio_opens_no_console_window(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen.update(kw, args=args)
        return subprocess.CompletedProcess(args, 0, json.dumps(
            {"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]}), "")
    monkeypatch.setattr(assurance, "_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(assurance.subprocess, "run", fake_run)
    assert assurance._media(tmp_path / "a.mp3", "mp3")["audio_tracks"] == 1
    assert seen["creationflags"] == engines.NO_WINDOW
    assert seen["encoding"] == "utf-8"
    assert "-protocol_whitelist" in seen["args"]


def test_imagemagick_gets_a_plain_name_its_format_and_a_policy(tmp_path, monkeypatch):
    from convertall.converters import magick
    seen = {}

    def fake_run(args, **kw):
        work = tmp_path / "out" / "magick"
        seen.update(kw, args=args, policy=(work / "policy.xml").read_text(), files=sorted(p.name for p in work.iterdir()))
    monkeypatch.setattr(engines, "require", lambda key: "magick")
    monkeypatch.setattr(engines, "run", fake_run)
    src = tmp_path / "@weird [1] name.png"  # "@" reads a file list, "[1]" picks a frame
    src.write_bytes(b"x")
    (tmp_path / "out").mkdir()
    magick.magick_convert(src, tmp_path / "out" / "a.jxl", "png", "jxl")
    assert seen["args"][1] == "PNG:in.png[0]"
    assert seen["files"] == ["in.png", "policy.xml"]
    assert "MVG" in seen["policy"] and "@*" in seen["policy"]
    assert seen["env"]["MAGICK_CONFIGURE_PATH"] == str(tmp_path / "out" / "magick")
    assert not (tmp_path / "out" / "magick").exists()


@pytest.mark.skipif(not engines.available("imagemagick"), reason="needs ImageMagick")
def test_imagemagick_converts_a_file_named_for_another_format(tmp_path):
    from convertall.converters import magick
    src = tmp_path / "photo.jpg"  # a PNG with the wrong name: named outright, it's still read
    Image.new("RGB", (16, 16), "green").save(src, "PNG")
    out = tmp_path / "out" / "photo.tiff"
    out.parent.mkdir()
    magick.magick_convert(src, out, "png", "tiff")
    with Image.open(out) as im:
        assert im.size == (16, 16)


def test_a_launch_never_opens_a_second_window(monkeypatch, tmp_path):
    """The open window holds the lock but doesn't answer: say so instead of opening another."""
    from PySide6.QtCore import QLockFile
    monkeypatch.setattr(instance, "SERVER_NAME", "ConvertAll-test-busy")
    monkeypatch.setattr(instance.tempfile, "gettempdir", lambda: str(tmp_path))
    held = QLockFile(str(tmp_path / "ConvertAll-test-busy.lock"))
    assert held.tryLock(0)
    told = []
    monkeypatch.setattr(instance, "WAIT_S", 0.3)
    monkeypatch.setattr(instance, "_busy", lambda: told.append(True))
    monkeypatch.setattr(instance, "forward", lambda *a, **k: False)
    from convertall import gui
    monkeypatch.setattr(gui, "run", lambda *a: pytest.fail("opened a second window"))
    assert instance.main([]) == 1
    assert told == [True]
    held.unlock()
