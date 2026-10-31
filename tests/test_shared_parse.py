"""The check before converting reads the source; the conversion then takes what it read instead of
parsing the file a second time (registry.keep / take)."""

from pathlib import Path

import pytest

from convertall import Report, convert, registry

from .samples import Samples


@pytest.fixture
def samples(tmp_path):
    return Samples(tmp_path / "samples")


def _count_reads(monkeypatch, module, name, src: Path):
    """Count calls of module.name whose first argument is src."""
    real = getattr(module, name)
    calls = []

    def counting(path, *a, **k):
        if Path(str(path)).resolve() == src.resolve():
            calls.append(path)
        return real(path, *a, **k)
    monkeypatch.setattr(module, name, counting)
    return calls


@pytest.mark.parametrize("src_fmt, dst_fmt", [("mobi", "epub"), ("fb2", "pdf")])
def test_a_book_is_read_once(samples, tmp_path, monkeypatch, src_fmt, dst_fmt):
    import bookport
    src = samples(src_fmt)
    reads = _count_reads(monkeypatch, bookport, "read", src)
    convert(src, dst_fmt, out_dir=tmp_path / "out", report=Report())
    assert len(reads) == 1


@pytest.mark.parametrize("src_fmt, dst_fmt", [("fbx", "glb"), ("fbx", "obj")])
def test_a_3d_scene_is_read_once(samples, tmp_path, monkeypatch, src_fmt, dst_fmt):
    import meshport
    src = samples(src_fmt)
    reads = _count_reads(monkeypatch, meshport, "load", src)
    convert(src, dst_fmt, out_dir=tmp_path / "out", report=Report())
    assert len(reads) == 1


def test_a_mesh_is_read_once(samples, tmp_path, monkeypatch):
    import trimesh
    src = samples("ply")
    reads = _count_reads(monkeypatch, trimesh, "load_scene", src)
    convert(src, "stl", out_dir=tmp_path / "out", report=Report())
    assert len(reads) == 1


def test_a_picture_is_decoded_once(samples, tmp_path, monkeypatch):
    from PIL import Image
    src = samples("png")
    opens = _count_reads(monkeypatch, Image, "open", src)
    convert(src, "jpg", out_dir=tmp_path / "out", report=Report())
    assert len(opens) == 1


def test_without_a_report_nothing_is_kept_and_it_still_converts(samples, tmp_path):
    out = convert(samples("mobi"), "epub", out_dir=tmp_path / "out")
    assert out.exists()
    assert registry._parsed.get() is None


def test_what_was_kept_is_handed_over_once_and_forgotten_after(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one")
    registry.keep(f, "txt", "book", "outside")  # no conversion running: nothing is kept
    with registry.sharing():
        assert registry.take(f, "txt", "book") is None
        registry.keep(f, "txt", "book", "parsed")
        assert registry.take(f, "txt", "scene") is None  # another kind
        assert registry.take(f, "epub", "book") is None  # read as another format
        assert registry.take(f, "txt", "book") == "parsed"
        assert registry.take(f, "txt", "book") is None  # handed over, not shared
        registry.keep(f, "txt", "book", "old")
        f.write_text("changed, and longer")  # the file changed since it was read
        assert registry.take(f, "txt", "book") is None
    assert registry._parsed.get() is None
