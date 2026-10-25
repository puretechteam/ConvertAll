import json
import shutil

import numpy as np
import pytest
import trimesh
from PIL import Image

from convertall import engines
from convertall.detect import detect
from convertall.errors import ConversionError
from convertall.pipeline import convert

from .conftest import needs


def _scene_stats(path):
    if path.is_dir():
        path = next(p for p in path.iterdir() if p.suffix in (".obj", ".usd"))
    scene = trimesh.load_scene(str(path))
    return len(scene.geometry), sum(len(g.faces) for g in scene.geometry.values())


@pytest.fixture
def glb(tmp_path):
    """Two parts, one textured, so formats that keep parts/materials can be checked."""
    box = trimesh.creation.box((2, 2, 2))
    box.visual = trimesh.visual.TextureVisuals(uv=np.random.rand(len(box.vertices), 2),
                                               image=Image.new("RGB", (32, 32), "orange"))
    ball = trimesh.creation.icosphere(2)
    ball.apply_translation((4, 0, 0))
    path = tmp_path / "model.glb"
    trimesh.Scene({"box": box, "ball": ball}).export(path)
    return path


# ---- meshes (trimesh)

@pytest.mark.parametrize("fmt,parts", [("stl", 1), ("ply", 1), ("off", 1), ("dae", 1),
                                       ("gltf", 2), ("3mf", 2), ("obj", 2)])
def test_mesh_formats(glb, fmt, parts):
    out = convert(glb, fmt)
    assert _scene_stats(out) == (parts, 332)


def test_obj_with_texture_is_a_folder(glb):
    out = convert(glb, "obj")
    assert out.is_dir() and {p.suffix for p in out.iterdir()} >= {".obj", ".mtl", ".png"}


def test_gltf_is_self_contained(glb, tmp_path):
    out = convert(glb, "gltf", out_dir=tmp_path / "g")
    assert [p.name for p in (tmp_path / "g").iterdir()] == ["model.gltf"]
    assert "data:application/octet-stream;base64" in out.read_text()


def test_empty_model_is_an_error(tmp_path):
    empty = tmp_path / "empty.obj"
    empty.write_text("# nothing\n")
    with pytest.raises(ConversionError):
        convert(empty, "stl")


# ---- CAD (gmsh / ezdxf)

@pytest.fixture(scope="module")
def cad_parts(tmp_path_factory):
    import gmsh
    d = tmp_path_factory.mktemp("cad")
    gmsh.initialize(interruptible=False)
    gmsh.option.setNumber("General.Terminal", 0)
    box = gmsh.model.occ.addBox(0, 0, 0, 40, 30, 5)
    boss = gmsh.model.occ.addCylinder(20, 15, 5, 0, 0, 10, 6)
    gmsh.model.occ.fuse([(3, box)], [(3, boss)])
    gmsh.model.occ.synchronize()
    for ext in ("step", "iges", "brep"):
        gmsh.write(str(d / f"part.{ext}"))
    gmsh.finalize()
    return d


@pytest.mark.parametrize("ext", ["step", "iges", "brep"])
def test_cad_to_watertight_stl(cad_parts, tmp_path, ext):
    mesh = trimesh.load(convert(cad_parts / f"part.{ext}", "stl", out_dir=tmp_path))
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(40 * 30 * 5 + np.pi * 36 * 10, rel=0.01)


def test_step_chains_to_other_mesh_formats(cad_parts, tmp_path):
    assert _scene_stats(convert(cad_parts / "part.step", "3mf", out_dir=tmp_path))[1] > 100


def test_dxf_renders(tmp_path):
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True)
    msp.add_circle((50, 30), 20, dxfattribs={"color": 1})
    dxf = tmp_path / "plan.dxf"
    doc.saveas(dxf)
    assert "<svg" in convert(dxf, "svg").read_text()
    assert convert(dxf, "pdf").read_bytes().startswith(b"%PDF")
    with Image.open(convert(dxf, "png")).convert("RGB") as img:
        colors = {c for _, c in img.getcolors(1 << 20)}
        assert (255, 255, 255) in colors and any(r > 200 and g < 80 for r, g, b in colors)  # white bg, red circle


# ---- DICOM (pydicom)

def _sample(name, tmp_path):
    from pydicom.data import get_testdata_file
    src = get_testdata_file(name)
    if not src:
        pytest.skip(f"{name} not bundled with pydicom")
    dst = tmp_path / name
    shutil.copy(src, dst)
    return dst


@pytest.mark.parametrize("name", ["CT_small.dcm", "MR_small.dcm", "US1_J2KR.dcm", "SC_rgb_rle.dcm",
                                  "MR_small_jpeg_ls_lossless.dcm"])
def test_dicom_to_png(tmp_path, name):
    with Image.open(convert(_sample(name, tmp_path), "png")) as img:
        lo, hi = img.convert("L").getextrema()
        assert hi - lo > 100  # actually windowed into a visible range


def test_dicom_multiframe(tmp_path):
    src = _sample("emri_small.dcm", tmp_path)
    folder = convert(src, "png")
    assert folder.is_dir() and len(list(folder.iterdir())) == 10
    with Image.open(convert(src, "gif")) as gif:
        assert gif.n_frames == 10


def test_dicom_detect_without_extension_and_metadata(tmp_path):
    src = _sample("CT_small.dcm", tmp_path)
    bare = tmp_path / "IM0001"
    shutil.copy(src, bare)
    assert detect(bare) == "dcm"
    meta = json.loads(convert(src, "json").read_text(encoding="utf-8"))
    assert meta["Modality"] == "CT" and "PixelData" not in meta


def test_dicom_unsupported_compression_is_clear(tmp_path):
    with pytest.raises(ConversionError, match="can't decode"):
        convert(_sample("JPEG-LL.dcm", tmp_path), "png")


# ---- Blender (skipped when not installed)

@needs("blender")
def test_blender_roundtrips(glb, tmp_path):
    for fmt in ("fbx", "usdz", "abc"):
        out = convert(glb, fmt)
        back = convert(out, "glb", out_dir=tmp_path / fmt)
        assert _scene_stats(back)[1] == 332


@needs("blender")
def test_blend_file_and_usd_folder(glb, tmp_path):
    script = tmp_path / "save.py"
    blend = tmp_path / "scene.blend"
    script.write_text("import bpy, sys\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
                      f"bpy.ops.import_scene.gltf(filepath=r'{glb}')\n"
                      f"bpy.ops.wm.save_as_mainfile(filepath=r'{blend}')\n")
    engines.run([engines.find("blender"), "-b", "--factory-startup", "--python-exit-code", "1",
                 "--python", str(script)])
    assert _scene_stats(convert(blend, "3mf"))[0] == 2  # routed via GLB, parts kept
    usd = convert(glb, "usd")
    assert usd.is_dir() and (usd / "model.usd").exists()  # textures travel alongside
