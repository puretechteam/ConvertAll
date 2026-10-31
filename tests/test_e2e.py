"""End to end: real sample files through the real pipeline, and every output opened again to prove it's valid.

  pytest tests/test_e2e.py            every format -> its most common target (part of the normal run)
  pytest tests/test_e2e.py --e2e      every format -> every format it can reach (a few thousand, slow)
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from convertall import engines, pipeline, registry
from convertall.assurance import Report
from convertall.detect import COMICS
from convertall.errors import ConversionError
from convertall.formats import FORMATS, category, suggest

from .samples import SUB_CODEC, Samples


def expected_error(src: str, dst: str) -> str | None:
    """Conversions these samples can't do, and the error the user sees instead."""
    if category(dst) == "Subtitle" and category(src) in ("Video", "Audio") and src not in SUB_CODEC:
        return "has no subtitle track"  # only some sample videos carry one
    if src == "djvu" and dst == "txt":
        return "no text layer"  # the sample is a picture, never OCRed
    if src == "djvu" and dst == "dxf":
        return "No vector shapes"  # scanned pages, like any scanned PDF
    return None


def content_dependent(src: str, dst: str) -> str | None:
    """Conversions that work only when the data has the right columns: these samples may or may
    not, so either a result or this message is right."""
    if dst == "vcf" and src != "vcf":
        return "No contacts found"
    if dst == "ics" and src != "ics":
        return "No events found"
    return None


# ---------------------------------------------------------------- checking outputs

def _ffprobe() -> str | None:
    ff = engines.find("ffmpeg")
    probe = ff and Path(ff).with_name("ffprobe.exe" if ff.lower().endswith(".exe") else "ffprobe")
    return str(probe) if probe and probe.exists() else None


def check(path: Path, fmt: str) -> None:
    """Open what was written the way the next program would, and fail if it isn't valid fmt."""
    assert path.exists(), f"{path} missing"
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        assert files, f"{path} is an empty folder"
        for f in files:
            sub = f.suffix.lstrip(".").lower()
            if sub == fmt:
                check(f, fmt)
        return
    assert path.stat().st_size > 0, f"{path.name} is empty"
    cat = category(fmt)
    data = path.read_bytes()
    from convertall.converters import images
    if fmt in images.READ and fmt not in ("ico", "icns", "cur"):
        from PIL import Image
        with Image.open(path) as img:
            img.load()
            assert img.width > 0
    elif fmt in ("ico", "icns"):
        from PIL import Image
        with Image.open(path) as img:
            img.load()
    elif fmt == "svg":
        assert b"<svg" in data[:4000]
    elif fmt in ("fbx", "3ds"):
        import meshport
        assert meshport.load(path, fmt).meshes
    elif fmt in ("eps", "ps"):
        assert data.startswith((b"%!PS", b"\xc5\xd0\xd3\xc6")), data[:20]
    elif fmt == "dxf":
        import ezdxf
        assert len(ezdxf.readfile(path).modelspace()) > 0
    elif cat == "Map":
        from convertall.converters import maps
        m = maps.read_map(path, fmt)
        assert m.points or m.lines
    elif fmt in ("vcf", "ics"):
        from convertall.converters import contacts
        text = data.decode("utf-8")
        assert (contacts.read_vcards if fmt == "vcf" else contacts.read_events)(text)
    elif fmt == "pdf":
        import pymupdf
        with pymupdf.open(path) as doc:
            assert doc.page_count >= 1
    elif cat in ("Audio", "Video"):
        probe = _ffprobe()
        if probe:
            kinds = subprocess.run([probe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                    str(path)], capture_output=True, text=True, check=False).stdout.replace(",", " ").split()
            want = "audio" if cat == "Audio" else "video"
            assert want in kinds, f"{path.name} has no {want} stream ({kinds})"
    elif cat == "Subtitle":
        text = data.decode("utf-8", "replace")
        if fmt in ("srt", "vtt"):
            assert "-->" in text, text[:200]
        elif fmt in ("ass", "ssa"):
            assert "Dialogue:" in text, text[:200]
        assert "Second line" in text
    elif cat == "Ebook":
        import bookport
        book = bookport.read(path)
        assert book.word_count() > 0 or book.images(), f"{path.name} has no text or pages"
    elif fmt in ("docx", "xlsx", "pptx", "odt", "ods", "odp", "odg", "3mf"):
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
    elif fmt == "rtf":
        assert data.startswith(b"{\\rtf")
    elif fmt in COMICS:
        out = pipeline.extract(path, path.parent / f"_check_{fmt}")
        pages = [p for p in (out.rglob("*") if out.is_dir() else [out]) if p.suffix.lower() in (".jpg", ".png", ".webp")]
        assert pages, f"{path.name} has no pages"
    elif cat == "Data" or fmt in ("csv", "tsv"):
        from convertall.converters import data as data_mod
        assert data_mod.load(path, fmt) is not None
    elif fmt in ("txt", "md", "html") or cat == "Markup":
        assert data.decode("utf-8").strip()
    elif cat == "Font":
        from fontTools.ttLib import TTFont
        assert "A" in TTFont(path).getGlyphOrder()
    elif fmt in ("stl", "obj", "ply", "off", "glb", "gltf", "dae"):
        import trimesh
        scene = trimesh.load_scene(str(path))
        assert sum(len(getattr(g, "faces", ())) for g in scene.geometry.values()) > 0
    elif cat == "Archive":
        out = pipeline.extract(path, path.parent / f"_check_{fmt.replace('.', '_')}")
        assert out.exists() and (out.is_file() or any(out.iterdir()))


# ---------------------------------------------------------------- the matrix

def _pairs(full: bool) -> list[tuple[str, str]]:
    pairs = []
    for src in sorted(FORMATS):
        routes = registry.targets(src)
        if full:
            for dst, route in sorted(routes.items()):
                # "put any file in a zip" is the same for every format: tested once, for folders
                if route.edges[0].func.__name__ == "compress_convert" and src not in ("folder", "txt"):
                    continue
                pairs.append((src, dst))
        else:
            dst = suggest(src, routes)
            if dst:
                pairs.append((src, dst))
    return pairs


def pytest_generate_tests(metafunc):
    if "pair" in metafunc.fixturenames:
        full = metafunc.config.getoption("--e2e")
        pairs = _pairs(full)
        metafunc.parametrize("pair", pairs, ids=[f"{s}-to-{d}" for s, d in pairs])


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    return Samples(tmp_path_factory.mktemp("samples"))


def test_convert(pair, samples, tmp_path):
    src_fmt, dst_fmt = pair
    route = registry.find_route(src_fmt, dst_fmt)
    if route.missing_engines:
        pytest.skip(f"needs {', '.join(route.missing_engines)}")
    src = samples(src_fmt)
    if src is None:
        pytest.skip(f"can't make a {src_fmt} sample here")
    err = expected_error(src_fmt, dst_fmt)
    if err:
        with pytest.raises(ConversionError, match=err):
            pipeline.convert(src, dst_fmt, out_dir=tmp_path)
        return
    maybe = content_dependent(src_fmt, dst_fmt)
    report = Report()
    try:
        out = pipeline.convert(src, dst_fmt, out_dir=tmp_path, report=report)
    except ConversionError as exc:
        if maybe and maybe in str(exc):
            return
        raise
    check(out, dst_fmt)
    # the checks ConvertAll makes on every result: on these samples nothing may differ unexplained
    assert not report.warnings, report.lines()
