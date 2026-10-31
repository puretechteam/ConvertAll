"""3D models: mesh formats via trimesh; FBX, 3DS, USD, Alembic and .blend via meshport. All built in."""

from pathlib import Path

from ..errors import ConversionError
from ..registry import converter

MESH = {"stl", "obj", "ply", "off", "glb", "gltf", "3mf", "dae"}
SCENE_EXPORT = {"glb", "gltf", "3mf", "stl", "obj", "ply"}  # these keep (or merge) parts themselves
# 3D-printing formats stand on a build plate: Z is up. Everything else here is glTF's Y-up,
# so these are turned on the way in and out (and not at all between two of them).
Z_UP = {"stl", "3mf"}
_Y_UP_TO_Z_UP = [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]  # (x, y, z) -> (x, -z, y)


def _deforms(src: Path, src_fmt: str | None) -> bool:
    """Whether a glTF file has skins or blend shapes (which trimesh doesn't apply)."""
    import json
    import struct
    try:
        if (src_fmt or src.suffix.lstrip(".").lower()) == "glb":
            with open(src, "rb") as f:
                head = f.read(20)
                if head[:4] != b"glTF" or len(head) < 20:
                    return False
                doc = json.loads(f.read(struct.unpack_from("<I", head, 12)[0]))
        else:
            doc = json.loads(src.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, struct.error):
        return False
    return bool(doc.get("skins")) or any(p.get("targets") for m in doc.get("meshes", [])
                                         for p in m.get("primitives", []) if isinstance(p, dict))


def _load(src: Path, src_fmt: str | None = None, dst_fmt: str | None = None):
    import tempfile

    import numpy as np
    import trimesh
    if (src_fmt or src.suffix.lstrip(".").lower()) in ("glb", "gltf") and _deforms(src, src_fmt):
        # bend rigged meshes where their skeleton holds them (their own node plays no part), with
        # their blend shapes at their weights, before trimesh, which would place them by the node
        import meshport
        with tempfile.TemporaryDirectory(prefix="convertall-bent-", ignore_cleanup_errors=True) as tmp:
            bent = Path(tmp) / "bent.glb"
            try:
                meshport.save(meshport.load(src).deformed(), bent)
            except meshport.MeshportError as e:
                raise ConversionError(str(e)) from None
            scene = trimesh.load_scene(str(bent))
    else:
        scene = trimesh.load_scene(str(src))
        if (src_fmt or src.suffix.lstrip(".").lower()) == "obj" and len(scene.geometry) == 1:
            scene = _obj_parts(src, scene)
    if not scene.geometry:
        raise ConversionError("No 3D geometry found in this file")
    if not any(hasattr(g, "faces") and len(g.faces) for g in scene.geometry.values()):
        raise ConversionError("This file is a point cloud; only PLY can hold it")
    if (src_fmt in Z_UP) != (dst_fmt in Z_UP):
        turn = np.array(_Y_UP_TO_Z_UP, float)
        scene.apply_transform(turn if dst_fmt in Z_UP else turn.T)
    return scene


def _obj_parts(src: Path, scene):
    """trimesh reads an OBJ's objects ("o" or "g" sections) as one mesh: cut it back into them, by the
    triangles each section's faces make (in file order, as trimesh keeps them). Left as it is when the
    counts don't line up (trimesh dropped or joined faces)."""
    import numpy as np
    import trimesh
    sections: list[list] = []  # [name, triangles]
    tag = None
    with src.open("rb") as f:
        for line in f:
            if line.startswith((b"o ", b"g ")):
                kind = line[:1]
                if tag is None or kind == tag:  # the first kind used names the parts; the other is ignored
                    tag = kind
                    sections.append([line[2:].strip().decode("utf-8", "replace") or f"part {len(sections) + 1}", 0])
            elif line.startswith(b"f "):
                if not sections:
                    sections.append(["part 1", 0])
                sections[-1][1] += max(len(line.split()) - 3, 0)
    sections = [s for s in sections if s[1]]
    (node,) = scene.graph.nodes_geometry
    matrix, name = scene.graph[node]
    mesh = scene.geometry[name]
    if len(sections) < 2 or sum(n for _, n in sections) != len(getattr(mesh, "faces", ())):
        return scene
    parts, start = trimesh.Scene(), 0
    for label_, n in sections:
        part = mesh.submesh([np.arange(start, start + n)], append=True)
        parts.add_geometry(part, node_name=label_, geom_name=label_, transform=matrix)
        start += n
    return parts


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


GLTF = {"glb", "gltf"}  # glTF to glTF goes through meshport, which keeps all of it (trimesh drops animation)


@converter(inputs=MESH - GLTF, outputs=MESH - {"obj"})
@converter(inputs=GLTF, outputs=MESH - {"obj"} - GLTF)
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


# ---- FBX, 3DS, USD, Alembic and .blend via meshport (pure Python): to and from glTF, and on to
# everything else through GLB, the cheap hub (routes like usdz -> glb -> 3mf keep separate parts,
# where going through STL or PLY would merge everything into one mesh)

MESHPORT = {"fbx", "3ds", "usdz", "abc"}  # read and written as one file
MESHPORT_IN = MESHPORT | {"usd", "blend"}  # .blend is read only; .usd output may be a folder (below)


@converter(inputs=MESHPORT_IN, outputs={"glb", "gltf"} | MESHPORT)
@converter(inputs={"glb", "gltf"}, outputs=MESHPORT | {"glb", "gltf"})
def meshport_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    import meshport
    try:
        meshport.save(meshport.load(src, src_fmt), dst, dst_fmt)
    except meshport.MeshportError as e:
        raise ConversionError(str(e)) from None
    return dst


# .obj comes with a .mtl and textures, .usd with a textures folder: these may be folders, so they
# can only be the last step
@converter(inputs=MESHPORT_IN, outputs={"obj", "usd"}, terminal=True)
@converter(inputs={"glb", "gltf"}, outputs={"usd"}, terminal=True)
def meshport_to_files(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    import meshport
    try:
        scene = meshport.load(src, src_fmt)
        return _side_files_aware(lambda p: meshport.save(scene, p), dst)
    except meshport.MeshportError as e:
        raise ConversionError(str(e)) from None
