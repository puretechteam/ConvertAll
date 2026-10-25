from pathlib import Path

import pytest

from convertall import registry
from convertall.detect import detect, strip_ext
from convertall.errors import EngineMissingError, NoRouteError
from convertall.pipeline import convert, unique_path


# ---- detection & naming

@pytest.mark.parametrize("name,fmt", [
    ("a.PNG", "png"), ("a.jpeg", "jpg"), ("b.tif", "tiff"), ("c.tar.gz", "tar.gz"), ("c.tgz", "tar.gz"),
    ("d.yml", "yaml"), ("e.markdown", "md"), ("f.htm", "html"),
])
def test_detect_by_extension(tmp_path, name, fmt):
    p = tmp_path / name
    p.write_bytes(b"x")
    assert detect(p) == fmt


def test_detect_folder_and_magic(tmp_path, png):
    assert detect(tmp_path) == "folder"
    blob = tmp_path / "noext"
    blob.write_bytes(png.read_bytes())
    assert detect(blob) == "png"


def test_strip_ext(tmp_path):
    assert strip_ext(Path("x/photos.tar.gz")) == "photos"
    assert strip_ext(Path("x/song.mp3")) == "song"
    d = tmp_path / "my.folder"
    d.mkdir()
    assert strip_ext(d) == "my.folder"


def test_unique_path_never_overwrites(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "a (1).jpg").write_bytes(b"")
    (tmp_path / "b.tar.gz").write_bytes(b"")
    (tmp_path / "dir").mkdir()
    assert unique_path(tmp_path / "a.jpg").name == "a (2).jpg"
    assert unique_path(tmp_path / "b.tar.gz").name == "b (1).tar.gz"
    assert unique_path(tmp_path / "dir").name == "dir (1)"
    assert unique_path(tmp_path / "new.png").name == "new.png"


def test_convert_twice_keeps_both(png):
    first = convert(png, "jpg")
    second = convert(png, "jpg")
    assert first != second and first.exists() and second.exists()


# ---- routing

def test_direct_routes_preferred():
    assert len(registry.find_route("png", "jpg").edges) == 1


def test_multi_hop_route():
    route = registry.find_route("md", "pdf")
    assert route.edges[0].src == "md"
    assert route.edges[-1].dst == "pdf"


@pytest.mark.parametrize("src,dst", [
    ("png", "mp3"),    # no cross-media nonsense
    ("png", "docx"),   # an image PDF doesn't chain into Word
    ("json", "png"),   # too many category hops
    ("ttf", "otf"),    # outline conversion isn't supported
    ("mp3", "mp4"),
    ("folder", "gz"),  # gz holds a single file
])
def test_nonsense_routes_absent(src, dst):
    with pytest.raises(NoRouteError):
        registry.find_route(src, dst)


def test_anything_can_be_compressed():
    for fmt in ("exe", "bin", "png", "docx", "folder"):
        targets = registry.targets(fmt)
        assert {"zip", "7z", "tar.gz"} <= set(targets)


def test_repack_beats_nesting():
    """zip -> 7z should repack contents, not put the zip inside a 7z."""
    route = registry.find_route("zip", "7z")
    assert route.edges[0].func.__name__ == "repack"


def test_installed_engine_preferred(without_engine):
    without_engine("calibre")
    route = registry.find_route("epub", "pdf")
    assert route.edges[0].engine is None and not route.missing_engines


def test_missing_engine_reported(tmp_path, without_engine):
    without_engine("ffmpeg")
    f = tmp_path / "a.wav"
    f.write_bytes(b"RIFF")
    assert registry.find_route("wav", "mp3").missing_engines == ["ffmpeg"]
    with pytest.raises(EngineMissingError) as exc:
        convert(f, "mp3")
    assert exc.value.engines == ["ffmpeg"]
    assert not (tmp_path / "a.mp3").exists()


def test_common_targets_for_batch():
    common = registry.common_targets(["png", "mp4"])
    assert "jpg" in common and "zip" in common
    assert "mp3" not in common
