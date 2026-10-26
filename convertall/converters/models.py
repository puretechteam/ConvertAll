"""3D models: mesh formats via trimesh, FBX and 3DS via meshport (both built in); Blend/USD/Alembic via Blender."""

from pathlib import Path

from .. import engines
from ..errors import ConversionError
from ..registry import converter

MESH = {"stl", "obj", "ply", "off", "glb", "gltf", "3mf", "dae"}
SCENE_EXPORT = {"glb", "gltf", "3mf", "stl", "obj", "ply"}  # these keep (or merge) parts themselves
# 3D-printing formats stand on a build plate: Z is up. Everything else here is glTF's Y-up,
# so these are turned on the way in and out (and not at all between two of them).
Z_UP = {"stl", "3mf"}
_Y_UP_TO_Z_UP = [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]  # (x, y, z) -> (x, -z, y)


def _load(src: Path, src_fmt: str | None = None, dst_fmt: str | None = None):
    import numpy as np
    import trimesh
    scene = trimesh.load_scene(str(src))
    if not scene.geometry:
        raise ConversionError("No 3D geometry found in this file")
    if not any(hasattr(g, "faces") and len(g.faces) for g in scene.geometry.values()):
        raise ConversionError("This file is a point cloud; only PLY can hold it")
    if (src_fmt in Z_UP) != (dst_fmt in Z_UP):
        turn = np.array(_Y_UP_TO_Z_UP, float)
        scene.apply_transform(turn if dst_fmt in Z_UP else turn.T)
    return scene


def _side_files_aware(export, dst: Path) -> Path:
    """Run export(path) in a scratch folder. OBJ writes .mtl/texture side files: if any appear,
    the result is a folder holding them all, otherwise just the file."""
    work = dst.parent / "_export"
    work.mkdir()
    export(work / dst.name)
    files = list(work.iterdir())
    if not files:
        raise ConversionError("The exporter produced no file")
    if len(files) == 1:
        files[0].rename(dst)
        return dst
    folder = dst.parent / f"{dst.stem} ({dst.suffix.lstrip('.')})"
    work.rename(folder)
    return folder


def _geometry_only(scene):
    """All parts merged into one mesh in world space, leaving out colors and textures.
    trimesh's own merge also combines every part's textures, which takes seconds on scenes
    with hundreds of textured parts, for formats (STL) that would throw them away anyway."""
    import numpy as np
    import trimesh
    verts, faces, offset = [], [], 0
    for node in scene.graph.nodes_geometry:
        matrix, name = scene.graph[node]
        g = scene.geometry[name]
        if not hasattr(g, "faces") or not len(g.faces):
            continue
        f = g.faces if np.linalg.det(matrix[:3, :3]) >= 0 else g.faces[:, ::-1]  # mirrored: keep faces outward
        verts.append(trimesh.transform_points(g.vertices, matrix))
        faces.append(f + offset)
        offset += len(g.vertices)
    return trimesh.Trimesh(np.concatenate(verts), np.concatenate(faces), process=False)


@converter(inputs=MESH, outputs=MESH - {"obj"})
@converter(inputs=MESH, outputs={"obj"}, terminal=True)  # may be a folder; chain via GLB instead
def mesh_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    import trimesh
    scene = _load(src, src_fmt, dst_fmt)
    if dst_fmt == "gltf":  # one self-contained file instead of .gltf + .bin buffers
        files = trimesh.exchange.gltf.export_gltf(scene, embed_buffers=True)
        dst.write_bytes(next(v for k, v in files.items() if k.endswith(".gltf")))
        return dst
    if dst_fmt == "stl":
        target = _geometry_only(scene)
    else:
        target = scene if dst_fmt in SCENE_EXPORT else scene.to_mesh()
    if dst_fmt == "obj":
        return _side_files_aware(lambda p: target.export(str(p)), dst)
    # Export to memory and write it ourselves: some exporters (pycollada) leave the file
    # handle open, which blocks moving the result on Windows.
    data = target.export(file_type=dst_fmt)
    dst.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return dst


# ---- FBX and 3DS via meshport (pure Python): to and from glTF, and on to everything else through GLB

MESHPORT = {"fbx", "3ds"}


@converter(inputs=MESHPORT, outputs={"glb", "gltf"} | MESHPORT)
@converter(inputs={"glb", "gltf"}, outputs=MESHPORT)
def fbx_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    import meshport
    try:
        meshport.save(meshport.load(src, src_fmt), dst, dst_fmt)
    except meshport.MeshportError as e:
        raise ConversionError(str(e)) from None
    return dst


@converter(inputs=MESHPORT, outputs={"obj"}, terminal=True)  # .obj + .mtl + textures: may be a folder
def fbx_to_obj(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    import meshport
    try:
        scene = meshport.load(src, src_fmt)
        return _side_files_aware(lambda p: meshport.save(scene, p), dst)
    except meshport.MeshportError as e:
        raise ConversionError(str(e)) from None


# ---- Blender, for formats nothing lightweight reads or writes reliably

BLENDER_IN = {"blend", "usd", "usdz", "abc"}

_BLENDER_SCRIPT = r'''
import bpy, sys
src, dst, sf, df = sys.argv[sys.argv.index("--") + 1:]
ops = bpy.ops
IMPORT = {
    "glb": ops.import_scene.gltf, "gltf": ops.import_scene.gltf,
    "obj": ops.wm.obj_import, "stl": ops.wm.stl_import, "ply": ops.wm.ply_import,
    "usd": ops.wm.usd_import, "usdz": ops.wm.usd_import, "abc": ops.wm.alembic_import,
}
EXPORT = {
    "glb": lambda p: ops.export_scene.gltf(filepath=p, export_format="GLB"),
    "obj": lambda p: ops.wm.obj_export(filepath=p),
    "stl": lambda p: ops.wm.stl_export(filepath=p),
    "ply": lambda p: ops.wm.ply_export(filepath=p),
    "usd": lambda p: ops.wm.usd_export(filepath=p),
    "usdz": lambda p: ops.wm.usd_export(filepath=p),
    "abc": lambda p: ops.wm.alembic_export(filepath=p),
}
if sf == "blend":
    ops.wm.open_mainfile(filepath=src)
else:
    ops.wm.read_factory_settings(use_empty=True)
    IMPORT[sf](filepath=src)
if not any(o.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"} for o in bpy.data.objects):
    raise SystemExit("No 3D geometry found in this file")
EXPORT[df](dst)
'''


# GLB is the cheap hub: multi-hop routes (usdz -> glb -> 3mf) go through it and keep separate
# parts, instead of through STL/PLY, which merge everything into one mesh. OBJ and USD may come
# out as folders (textures as side files), so they can only be the last step.
@converter(inputs=BLENDER_IN, outputs={"glb"}, engine="blender")
@converter(inputs=BLENDER_IN, outputs={"stl", "ply", "usdz", "abc"}, engine="blender", cost=2)
@converter(inputs=BLENDER_IN, outputs={"obj", "usd"}, engine="blender", cost=2, terminal=True)
@converter(inputs={"glb", "gltf", "obj", "stl", "ply"}, outputs={"usdz", "abc"}, engine="blender")
@converter(inputs={"glb", "gltf", "obj", "stl", "ply"}, outputs={"usd"}, engine="blender", terminal=True)
def blender_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    exe = engines.require("blender")
    script = dst.parent / "_convert.py"
    script.write_text(_BLENDER_SCRIPT, encoding="utf-8")

    def export(path: Path) -> None:
        engines.run([exe, "-b", "--factory-startup", "-noaudio", "--python-exit-code", "1",
                     "--python", str(script), "--", str(src), str(path), src_fmt, dst_fmt], timeout=1800)
    return _side_files_aware(export, dst)
