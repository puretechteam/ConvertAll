"""What a route can't keep, the checks on every result, routes that keep more, mislabelled files,
settings and presets: through the real pipeline and the command line."""

from __future__ import annotations

import base64
import json
import struct

import pytest
from PIL import Image

from convertall import Report, assurance, losses, options, pipeline, registry
from convertall.cli import main
from convertall.detect import detect, mislabelled
from convertall.errors import ConversionError

from .conftest import needs
from .samples import Samples, picture


@pytest.fixture
def samples(tmp_path):
    return Samples(tmp_path / "samples")


def notes(src: str, dst: str, **opts) -> list[str]:
    return [n.text for n in registry.find_route(src, dst).explain(options=opts)]


def has(lines: list[str], *words: str) -> bool:
    return any(all(w in line for w in words) for line in lines)


# ---------------------------------------------------------------- notes on every kind of step

@pytest.mark.parametrize("src,dst,words", [
    ("png", "jpg", ("transparency", "white")), ("png", "jpg", ("lossy",)), ("gif", "jpg", ("first frame",)),
    ("png", "gif", ("256 colors",)), ("png", "xbm", ("black and white",)), ("psd", "png", ("Layers",)),
    ("exr", "png", ("brightness",)), ("heic", "bmp", ("photo details",)), ("png", "ico", ("square sizes",)),
    ("png", "svg", ("traced",)), ("svg", "png", ("pixels",)), ("pdf", "png", ("150 dpi",)),
    ("pdf", "png", ("own image", "folder")), ("pdf", "png", ("selected or searched",)), ("pdf", "eps", ("first page",)),
    ("docx", "txt", ("Plain text",)), ("eml", "html", ("Attachments",)), ("glb", "stl", ("parts are merged",)),
    ("glb", "stl", ("colors and textures",)), ("abc", "stl", ("no animation",)), ("step", "stl", ("curved surfaces",)),
    ("json", "csv", ("flat table",)), ("xlsx", "csv", ("first sheet",)), ("xlsx", "json", ("Formulas",)),
    ("ass", "srt", ("styling",)), ("wav", "mp3", ("lossy",)), ("mkv", "mp4", ("re-encoded",)),
    ("mp4", "gif", ("12 frames a second", "640 pixels")), ("mp3", "m4r", ("40 seconds",)), ("kml", "gpx", ("styles",)),
    ("dcm", "png", ("8 bits",)), ("dcm", "json", ("image itself",)), ("ttf", "otf", ("hinting",)),
    ("svg", "dxf", ("outlines",)), ("html", "md", ("Markdown keeps",)), ("srt", "sub", ("frames a second",)),
])
def test_route_says_what_it_cant_keep(src, dst, words):
    assert has(notes(src, dst), *words), notes(src, dst)


@pytest.mark.parametrize("src,dst", [
    ("png", "tiff"), ("gif", "png"), ("glb", "fbx"), ("glb", "gltf"), ("fbx", "glb"), ("flac", "wav"),
    ("srt", "vtt"), ("json", "yaml"), ("csv", "xlsx"), ("ttf", "woff2"), ("zip", "7z"),
])
def test_lossless_routes_say_nothing_lost(src, dst):
    assert notes(src, dst) == []


def test_a_feature_lost_once_is_said_once():
    # FBX -> GLB -> STL: the merge is said for the step that does it, never twice
    lines = notes("fbx", "stl")
    assert sum("merged" in n for n in lines) == 1


def test_settings_change_what_is_said():
    assert has(notes("pdf", "png", dpi=300), "300 dpi")
    assert has(notes("mp4", "gif", fps=8, video_size="480p"), "8 frames a second", "480p")
    assert has(notes("png", "jpg", max_size=800), "800 pixels")


# ---------------------------------------------------------------- choosing the route that keeps more

def test_loss_outweighs_a_step(monkeypatch):
    """A direct step that loses something loses to a two-step route that doesn't."""
    edges = registry._edges.copy()
    fake = registry.defaultdict(list)
    fake.update(edges)
    noop = lambda *a: None
    fake["aaa"] = [registry.Edge("aaa", "ccc", noop, notes=lambda s, d, o: [losses.loss("drops it", weight=losses.MINOR)]),
                   registry.Edge("aaa", "bbb", noop)]
    fake["bbb"] = [registry.Edge("bbb", "ccc", noop)]
    monkeypatch.setattr(registry, "_edges", fake)
    assert str(registry.find_route("aaa", "ccc")) == "aaa -> bbb -> ccc"
    # ...but an engine still to install costs more than any one loss
    fake["bbb"] = [registry.Edge("bbb", "ccc", noop, engine="libreoffice")]
    monkeypatch.setattr(registry.engines, "available", lambda key: False)
    assert str(registry.find_route("aaa", "ccc")) == "aaa -> ccc"


def test_gltf_to_glb_goes_through_meshport():
    assert registry.find_route("glb", "gltf").edges[0].func.__name__ == "meshport_convert"
    assert registry.find_route("gltf", "glb").edges[0].func.__name__ == "meshport_convert"


def _animated_gltf(path):
    """One triangle that slides along x over a second."""
    pos = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    times = struct.pack("<2f", 0, 1)
    moves = struct.pack("<6f", 0, 0, 0, 2, 0, 0)
    buf = pos + times + moves
    doc = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "buffers": [{"byteLength": len(buf), "uri": "data:application/octet-stream;base64," + base64.b64encode(buf).decode()}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 8},
                        {"buffer": 0, "byteOffset": 44, "byteLength": 24}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
                      {"bufferView": 1, "componentType": 5126, "count": 2, "type": "SCALAR", "min": [0], "max": [1]},
                      {"bufferView": 2, "componentType": 5126, "count": 2, "type": "VEC3"}],
        "animations": [{"samplers": [{"input": 1, "output": 2}], "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}]}],
    }
    path.write_text(json.dumps(doc))
    return path


def test_animation_survives_gltf_to_glb_and_is_reported_lost_in_stl(tmp_path):
    src = _animated_gltf(tmp_path / "slide.gltf")
    r = Report()
    out = pipeline.convert(src, "glb", tmp_path / "out", report=r)
    assert assurance.inspect(out, "glb")["animation"] is True
    assert {c.name: c.state for c in r.checks}["Parts"] == "ok" and not r.warnings
    r = Report()
    pipeline.convert(src, "stl", tmp_path / "out", report=r)
    assert has(r.notes, "no animation")
    assert {c.name: c.state for c in r.checks}.get("Animation", "expected") == "expected"


# ---------------------------------------------------------------- measuring and checking

def test_inspect_measures_each_kind(tmp_path, samples):
    img = tmp_path / "a.png"
    picture().save(img)
    assert assurance.inspect(img, "png") == {"width": 160, "height": 120, "frames": 1, "photo_info": False,
                                              "transparency": True}
    import pymupdf
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    doc.save(tmp_path / "three.pdf")
    assert assurance.inspect(tmp_path / "three.pdf", "pdf") == {"pages": 3}
    (tmp_path / "t.json").write_text(json.dumps({"a": [{"x": 1, "y": {"z": 2}}], "b": [{"x": 2}, {"x": 3}]}))
    assert assurance.inspect(tmp_path / "t.json", "json") == {"tables": 2, "records": 1, "nested": True}
    assert assurance.inspect(samples("srt"), "srt") == {"cues": 2}
    assert assurance.inspect(samples("ttf"), "ttf")["glyphs"] > 1
    assert assurance.inspect(samples("zip"), "zip")["files"] >= 1
    assert assurance.inspect(samples("gpx"), "gpx")["places"] >= 1
    assert assurance.inspect(tmp_path / "t.json", "xyz") is None  # not a kind measured here


def test_inspect_refuses_a_broken_result(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n not really")
    with pytest.raises(assurance.Unreadable):
        assurance.inspect(bad, "png")
    assert assurance.measure(bad, "png") is None  # a source that won't open is the converter's business


def test_verify_states():
    lost = [losses.loss("STL holds one mesh", "parts", affects=("parts",))]
    checks = {c.name: c for c in assurance.verify({"parts": 4, "triangles": 10, "size": 2.0},
                                                   {"parts": 1, "triangles": 9, "size": 2.0005}, lost)}
    assert checks["Parts"].state == "expected" and checks["Parts"].why == "STL holds one mesh"
    assert checks["Triangles"].state == "warning"
    assert checks["Size"].state == "ok"  # within 1/1000
    assert assurance.verify({"duration": 10.0}, {"duration": 10.3}, [])[0].state == "ok"
    assert assurance.verify({"duration": 10.0}, {"duration": 7.0}, [])[0].state == "warning"


def test_a_result_that_doesnt_open_is_kept_and_reported(tmp_path, monkeypatch):
    from convertall.converters import images
    monkeypatch.setitem(images.OWN_WRITERS, "psd", lambda img, dst: dst.write_bytes(b"8BPS garbage"))
    src = tmp_path / "a.png"
    picture().save(src)
    r = Report()
    out = pipeline.convert(src, "psd", tmp_path / "out", report=r)
    assert out.exists()  # kept, never deleted
    assert r.checks[0].state == "error" and "doesn't open as PSD" in r.warnings[0]
    assert r.summary().startswith("Check:")


def test_report_lines_and_json(tmp_path):
    src = tmp_path / "a.png"
    picture().save(src)
    r = Report()
    pipeline.convert(src, "jpg", tmp_path / "out", report=r)
    d = json.loads(json.dumps(r.to_dict(), default=str))
    assert d["route"] == "PNG → JPG" and d["steps"][0]["tool"].startswith("Pillow ")
    assert {c["name"]: c["state"] for c in d["checks"]} == {"Frames": "ok", "Width": "ok", "Height": "ok",
                                                             "Transparency": "expected"}
    assert r.lines()[0].startswith("PNG → JPG via Pillow")
    assert "Checked, the same: frames 1, width 160, height 120" in r.lines()


def test_unhappened_may_notes_are_dropped(tmp_path):
    src = tmp_path / "small.png"
    picture().save(src)
    r = Report()
    pipeline.convert(src, "webp", tmp_path / "out", report=r, options={"max_size": 1000})
    assert not has(r.notes, "scaled down")  # 160 px wide: nothing was scaled


# ---------------------------------------------------------------- files named for the wrong format

def test_a_jpeg_named_png_is_converted_as_a_jpeg(tmp_path):
    fake = tmp_path / "photo.png"
    picture().convert("RGB").save(fake, "JPEG")
    assert detect(fake) == "jpg"
    assert "really a JPG" in mislabelled(fake)
    r = Report()
    out = pipeline.convert(fake, "webp", tmp_path / "out", report=r)
    assert r.detected == "content" and has(r.notes, "really a JPG")
    with Image.open(out) as img:
        assert img.format == "WEBP"
    with pytest.raises(ConversionError, match="a JPG already"):
        pipeline.convert(fake, "jpg", tmp_path / "out")


def test_honest_names_and_unknown_content_stay(tmp_path):
    real = tmp_path / "a.png"
    picture().save(real)
    odd = tmp_path / "b.png"
    odd.write_bytes(b"nothing we know")
    assert detect(real) == "png" and mislabelled(real) is None
    assert detect(odd) == "png" and mislabelled(odd) is None  # no other format's signature: the name stands


# ---------------------------------------------------------------- what Pillow used to drop or get wrong

def test_photo_details_and_color_profile_come_along(tmp_path):
    from PIL import ImageCms
    src = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[0x010F], exif[0x0110], exif[0x0132], exif[0x0112] = "Camera Co", "Model 1", "2026:10:29 08:00:00", 6
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    picture().convert("RGB").save(src, "JPEG", exif=exif.tobytes(), icc_profile=icc)
    for fmt in ("png", "webp", "tiff", "heic", "avif"):
        out = pipeline.convert(src, fmt, tmp_path / fmt)
        if fmt == "heic":
            from convertall.converters.images import enable_heif
            enable_heif()
        with Image.open(out) as img:
            got = img.getexif()
            assert got.get(0x010F) == "Camera Co" and got.get(0x0132) == "2026:10:29 08:00:00", fmt
            assert got.get(0x0112, 1) == 1, fmt  # turned upright, so no longer "rotate 90"
            assert img.size == (120, 160), fmt
            assert img.info.get("icc_profile") == icc, fmt


def _layered_psd(path, size=(8, 6)):
    """A Photoshop file with two layers (red, blue) and a green flattened picture."""
    w, h = size

    def channels(rgb):
        return [bytes([c]) * (w * h) for c in rgb]
    layers = [("red", (255, 0, 0)), ("blue", (0, 0, 255))]
    records, data = b"", b""
    for name, rgb in layers:
        raw = name.encode()
        pname = bytes([len(raw)]) + raw
        pname += b"\0" * (-len(pname) % 4)
        extra = struct.pack(">II", 0, 0) + pname
        records += struct.pack(">iiiiH", 0, 0, h, w, 3)
        records += b"".join(struct.pack(">hI", i, 2 + w * h) for i in range(3))
        records += b"8BIMnorm" + bytes([255, 0, 0, 0]) + struct.pack(">I", len(extra)) + extra
        data += b"".join(struct.pack(">H", 0) + c for c in channels(rgb))
    info = struct.pack(">h", len(layers)) + records + data
    info += b"\0" * (len(info) % 2)
    section = struct.pack(">I", len(info)) + info + struct.pack(">I", 0)
    head = b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3) + struct.pack(">II", 0, 0)
    path.write_bytes(head + struct.pack(">I", len(section)) + section + struct.pack(">H", 0)
                     + b"".join(channels((0, 255, 0))))
    return path


def test_a_layered_photoshop_file_is_its_flattened_picture(tmp_path):
    src = _layered_psd(tmp_path / "layers.psd")
    with Image.open(src) as img:
        assert img.n_frames == 2  # Pillow sees the layers as frames
    for fmt in ("png", "gif", "webp"):
        out = pipeline.convert(src, fmt, tmp_path / fmt)
        with Image.open(out) as img:
            assert getattr(img, "n_frames", 1) == 1, fmt
            assert img.convert("RGB").getpixel((3, 3))[1] > 200, fmt  # green: the whole picture, not a layer


def test_several_sheets_to_csv_keep_the_first(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "People"
    wb.active.append(["name", "age"])
    wb.active.append(["Ada", 36])
    other = wb.create_sheet("Places")
    other.append(["city"])
    other.append(["London"])
    src = tmp_path / "book.xlsx"
    wb.save(src)
    r = Report()
    out = pipeline.convert(src, "csv", tmp_path / "out", report=r)
    assert out.read_text(encoding="utf-8-sig").splitlines() == ["name,age", "Ada,36"]
    assert has(r.notes, "first sheet")
    assert {c.name: c.state for c in r.checks} == {"Tables": "expected", "Records": "ok"}


# ---------------------------------------------------------------- settings

def _size(path):
    return path.stat().st_size


def test_quality_and_max_size(tmp_path):
    src = tmp_path / "big.png"
    Image.effect_mandelbrot((1200, 900), (-2, -1.2, 1, 1.2), 80).convert("RGB").save(src)
    default = pipeline.convert(src, "jpg", tmp_path / "a")
    low = pipeline.convert(src, "jpg", tmp_path / "b", options={"quality": 40})
    assert _size(low) < 0.7 * _size(default)
    small = pipeline.convert(src, "webp", tmp_path / "c", options={"max_size": 600})
    with Image.open(small) as img:
        assert img.size == (600, 450)


def test_dpi(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page(width=72 * 4, height=72 * 2)
    doc.save(tmp_path / "one.pdf")
    out = pipeline.convert(tmp_path / "one.pdf", "png", tmp_path / "o", options={"dpi": 300})
    with Image.open(out) as img:
        assert img.size == (1200, 600)


def test_cad_detail(samples, tmp_path):
    step = samples("step")
    counts = {}
    for level in ("coarse", "fine"):
        r = Report()
        out = pipeline.convert(step, "stl", tmp_path / level, report=r, options={"detail": level})
        counts[level] = assurance.inspect(out, "stl")["triangles"]
        assert r.settings == {"detail": level}
    assert counts["fine"] > 2 * counts["coarse"]


@needs("ffmpeg")
def test_media_settings(samples, tmp_path):
    mp4 = samples("mp4")
    gif = pipeline.convert(mp4, "gif", tmp_path / "g", options={"fps": 5})
    with Image.open(gif) as img:
        assert img.n_frames <= 11  # 2 s at 5 frames a second (12 by default: 24)
    small = pipeline.convert(mp4, "webm", tmp_path / "v", report=(r := Report()), options={"video_size": "360p"})
    assert assurance.inspect(small, "webm")["height"] <= 120  # 160x120 is smaller already: never enlarged
    assert r.settings == {"video_size": "360p"} and not r.warnings
    wav = samples("wav")
    rates = {b: _size(pipeline.convert(wav, "mp3", tmp_path / str(b), options={"bitrate": b})) for b in (64, 256)}
    assert rates[256] > 2.5 * rates[64]


def test_bad_settings_are_refused(tmp_path):
    src = tmp_path / "a.png"
    picture().save(src)
    with pytest.raises(ConversionError, match="from 1 to 100"):
        pipeline.convert(src, "jpg", tmp_path, options={"quality": 300})
    with pytest.raises(ConversionError, match="Unknown setting"):
        pipeline.convert(src, "jpg", tmp_path, options={"sharpness": 3})


def test_settings_a_route_doesnt_take_change_nothing(tmp_path):
    src = tmp_path / "a.png"
    picture().save(src)
    a = pipeline.convert(src, "bmp", tmp_path / "a")
    r = Report()
    b = pipeline.convert(src, "bmp", tmp_path / "b", report=r, options={"quality": 10, "dpi": 600, "bitrate": 64})
    assert a.read_bytes() == b.read_bytes() and r.settings == {}


def test_media_checks_start_once_ffmpeg_is_installed(tmp_path, monkeypatch):
    from convertall import engines
    monkeypatch.setattr(engines, "find", lambda key: None)
    assert assurance._ffprobe() is None
    (tmp_path / "ffmpeg.exe").write_bytes(b"")
    (tmp_path / "ffprobe.exe").write_bytes(b"")
    monkeypatch.setattr(engines, "find", lambda key: str(tmp_path / "ffmpeg.exe"))
    assert assurance._ffprobe() == str(tmp_path / "ffprobe.exe")  # no restart needed


# ---------------------------------------------------------------- presets

def test_builtin_presets_are_valid():
    for name, values in options.PRESETS.items():
        assert options.clean(values) == values, name


def test_save_load_delete_presets(tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERTALL_PRESETS", str(tmp_path / "presets.json"))
    options.save_preset("Archive scans", {"dpi": 400, "quality": 90})
    assert options.preset("archive scans") == {"dpi": 400, "quality": 90}
    assert "Archive scans" in options.all_presets()
    with pytest.raises(ValueError, match="built-in"):
        options.save_preset("Best quality", {"quality": 50})
    with pytest.raises(ValueError):
        options.save_preset("Bad", {"quality": "loud"})
    options.delete_preset("Archive scans")
    assert "Archive scans" not in options.all_presets()
    (tmp_path / "presets.json").write_text("{not json")
    assert options.user_presets() == {}  # a damaged file never breaks the app


# ---------------------------------------------------------------- the command line

def test_cli_plan_converts_nothing(tmp_path, capsys):
    src = tmp_path / "a.png"
    picture().save(src)
    assert main([str(src), "--to", "jpg", "--plan", "--quality", "80"]) == 0
    out = capsys.readouterr().out
    assert "PNG → JPG via Pillow" in out and "transparency" in out and "quality=80" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.png"]
    assert main([str(src), "--to", "jpg", "--plan", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["route"] == "PNG → JPG" and plan["takes"] == ["quality", "max_size"] and plan["facts"]["width"] == 160


def test_cli_json_reports(tmp_path, capsys):
    src = tmp_path / "a.png"
    picture().save(src)
    (tmp_path / "bad.png").write_bytes(b"nothing")
    assert main([str(src), str(tmp_path / "bad.png"), "--to", "jpg", "--json", "--preset", "Smaller for email and web",
                 "-o", str(tmp_path / "out")]) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["settings"] == {"quality": 75, "max_size": 1920} and lines[0]["warnings"] == []
    assert set(lines[0]) >= {"source", "output", "route", "steps", "notes", "checks", "seconds"}
    assert lines[1]["source"].endswith("bad.png") and lines[1]["error"]


def test_cli_text_shows_notes_and_checks(tmp_path, capsys):
    src = tmp_path / "a.png"
    picture().save(src)
    assert main([str(src), "--to", "jpg"]) == 0
    out = capsys.readouterr().out
    assert "JPG has no transparency" in out and "Checked, the same: frames 1" in out


def test_cli_settings_errors(tmp_path, capsys):
    src = tmp_path / "a.png"
    picture().save(src)
    assert main([str(src), "--to", "jpg", "--preset", "nope"]) == 2
    assert main([str(src), "--to", "jpg", "--video-quality", "huge"]) == 2
    assert main(["presets"]) == 0
    assert "Ready for 3D printing" in capsys.readouterr().out



# ---------------------------------------------------------------- found by checking every built-in route

def test_obj_objects_stay_separate_parts(samples, tmp_path):
    obj = samples("obj")
    assert assurance.inspect(obj, "obj")["parts"] == 2
    for fmt in ("glb", "3mf", "fbx"):
        r = Report()
        out = pipeline.convert(obj, fmt, tmp_path / fmt, report=r)
        assert assurance.inspect(out, fmt)["parts"] == 2, fmt  # trimesh alone made them one
        assert not r.warnings, r.lines()


def test_database_to_jsonl_and_plist(tmp_path):
    import plistlib
    import sqlite3
    db = tmp_path / "shop.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE zebra (n INTEGER)")
    con.executemany("INSERT INTO zebra VALUES (?)", [(1,), (2,)])
    con.execute("CREATE TABLE apple (n INTEGER)")
    con.execute("INSERT INTO apple VALUES (3)")
    con.commit()
    con.close()
    r = Report()
    out = pipeline.convert(db, "jsonl", tmp_path / "j", report=r)
    assert out.read_text(encoding="utf-8").splitlines() == ['{"n": 1}', '{"n": 2}']  # one record a line
    assert has(r.notes, "JSONL holds one table") and not r.warnings
    out = pipeline.convert(db, "plist", tmp_path / "p")
    assert list(plistlib.loads(out.read_bytes())) == ["zebra", "apple"]  # in the database's order


def test_sami_clearing_cues_arent_subtitles(samples, tmp_path):
    r = Report()
    pipeline.convert(samples("srt"), "smi", tmp_path, report=r)
    assert {c.name: (c.before, c.after) for c in r.checks}["Subtitles"] == (2, 2)


def test_big_counts_are_easy_to_read():
    from convertall.assurance import show
    assert (show(30682), show(1920), show(660000), show(6.63325), show(True)) == ("30,682", "1920", "660,000", "6.633", "yes")


@pytest.mark.parametrize("fmt", ["icns", "ico", "png", "webp", "gif", "tiff"])
def test_transparency_check_reads_every_picture_kind(fmt, tmp_path):
    """ICNS reports RGBA before decoding and RGB after; the check must not trip over that."""
    from PIL import Image

    from convertall import assurance
    for mode, see_through in (("RGB", False), ("RGBA", True)):
        im = Image.new(mode, (64, 64), (200, 30, 30) if mode == "RGB" else (200, 30, 30, 0))
        path = tmp_path / f"{mode}.{fmt}"
        im.save(path)
        facts = assurance.inspect(path, fmt)
        assert facts["width"] == (1024 if fmt == "icns" else 64)  # ICNS opens at its biggest size
        if fmt != "icns":  # ICNS keeps no transparency for this size in Pillow's writer
            assert facts["transparency"] == see_through, (fmt, mode)
