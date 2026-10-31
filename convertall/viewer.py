"""The 3D viewer: any model ConvertAll can turn into GLB, shown in a window you can turn around.

Loading goes through meshport's scene model. Formats meshport reads are loaded directly;
everything else (STL, OBJ, 3MF, STEP, ...) takes ConvertAll's own route to GLB first.
flatten() turns the scene into GPU-ready buffers, and ModelView draws them with Qt's RHI
(Direct3D 11 on Windows), which needs nothing beyond the Qt libraries the window already uses.
"""

from __future__ import annotations

import copy
import io
import math
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    QElapsedTimer,
    QObject,
    QPointF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QRhiBuffer,
    QRhiCommandBuffer,
    QRhiDepthStencilClearValue,
    QRhiGraphicsPipeline,
    QRhiSampler,
    QRhiShaderResourceBinding,
    QRhiShaderStage,
    QRhiTexture,
    QRhiVertexInputAttribute,
    QRhiVertexInputBinding,
    QRhiVertexInputLayout,
    QRhiViewport,
    QShader,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRhiWidget,
    QSlider,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from .errors import ConversionError

SHADERS = Path(__file__).resolve().parent / "assets" / "shaders"
MAX_TEXTURE = 2048         # bigger textures are scaled down for display
MAX_WIRE_TRIANGLES = 3_000_000  # above this, no wireframe (its edge list costs too much memory)
SMOOTH_ANGLE = 40.0        # models without normals: faces closer than this share a smooth normal
BOUND_SAMPLES = 24         # moments of an animation (and up to 4x as many keys) sampled for the bounds
BOUND_BUDGET = 0.5         # seconds those may take on a heavy model, which then samples fewer
UNITLESS = {"stl", "obj", "ply", "off", "3mf", "step", "iges", "brep"}  # sizes are in the file's own units

VERTEX = np.dtype([("pos", "<f4", 3), ("normal", "<f4", 3), ("uv", "<f4", 2), ("color", "u1", 4)])


def _native() -> set[str]:
    import meshport
    return {f for f, desc in meshport.FORMATS.items() if "write only" not in desc}


def load_scene(path: Path, fmt: str):
    """A meshport.Scene for any viewable file (Y up)."""
    import meshport

    from . import pipeline
    try:
        if fmt in _native():
            return meshport.load(path, fmt)
        with tempfile.TemporaryDirectory(prefix="convertall-view-", ignore_cleanup_errors=True) as tmp:
            return meshport.load(pipeline.convert(path, "glb", tmp, src_fmt=fmt), "glb")
    except meshport.MeshportError as e:
        raise ConversionError(str(e)) from None


# ---------------------------------------------------------------- scene -> buffers

@dataclass
class Texture:
    width: int
    height: int
    rgba: bytes


@dataclass
class Surface:
    name: str
    base_color: tuple = (0.8, 0.8, 0.8, 1.0)
    emissive: tuple = (0.0, 0.0, 0.0)
    roughness: float = 0.6
    metallic: float = 0.0
    alpha_mode: str = "OPAQUE"
    texture: Texture | None = None


@dataclass
class Batch:
    surface: int  # index into Model.surfaces
    first: int    # into Model.triangles (an index count, not a triangle count)
    count: int


class Part:
    """One mesh node's rows of Model.vertices, and what posing them over time needs. Rows share
    mesh vertices (a corner is split wherever its normal or UV differs), so a pose is worked out
    once per vertex and then spread to the rows."""

    def __init__(self, node, start: int, corners: np.ndarray, normals: np.ndarray):
        mesh = node.mesh
        self.node, self.start = node, start    # the meshport.Node of the scene as read, skins and all
        self.corners = corners                 # (R,) the mesh corner each row came from
        self.normals = normals                 # (R, 3) each row's normal in the node's own space
        self.verts, self.row_vertex = np.unique(mesh.corners[corners], return_inverse=True)
        self.count = len(corners)
        skin = node.skin
        if skin is not None:  # the vertices' influences, picked out once (float32 blends twice as fast)
            self.joints, self.weights = skin.indices[self.verts], skin.weights[self.verts].astype(np.float32)
        # each blend shape's change to the rows' normals: its own normal offsets, or (worked out the
        # first time it's used) how far each row's normal turns with the surface under it at full weight
        self.offsets: dict[int, np.ndarray] = {}
        self.rest: tuple | None = None

    def _offset(self, k: int) -> np.ndarray:
        if k not in self.offsets:
            mesh = self.node.mesh
            target = mesh.targets[k]
            if target.normals is not None:
                self.offsets[k] = target.normals[self.corners]
            else:  # smooth rows turn with their vertex's normal, flat ones with their face's
                if self.rest is None:
                    face = np.repeat(np.arange(len(mesh.face_sizes)), mesh.face_sizes)[self.corners]
                    faces, smooth = _surface_normals(mesh.positions, mesh)
                    by_face, by_vertex = faces[face], smooth[mesh.corners[self.corners]]
                    keep = np.einsum("ij,ij->i", self.normals, by_vertex) >= np.einsum("ij,ij->i", self.normals, by_face)
                    self.rest = face, keep, np.where(keep[:, None], by_vertex, by_face)
                face, keep, rest = self.rest
                faces, smooth = _surface_normals(mesh.positions + target.positions, mesh)
                now = np.where(keep[:, None], smooth[mesh.corners[self.corners]], faces[face])
                self.offsets[k] = _turn(self.normals, rest, now) - self.normals
        return self.offsets[k]

    def local_normals(self, weights) -> np.ndarray:
        """The rows' normals in the node's space with the blend shapes at these weights, the shapes'
        changes added in proportion (as glTF blends normal offsets)."""
        mesh = self.node.mesh
        weights = mesh.target_weights if weights is None else weights
        if not mesh.targets or weights is None:
            return self.normals
        out = self.normals
        for k, w in enumerate(np.asarray(weights, np.float64)):
            if w:
                out = out + w * self._offset(k)
        return out


def _surface_normals(points: np.ndarray, mesh) -> tuple[np.ndarray, np.ndarray]:
    """Unit normals of each face (Newell's) and each vertex (its faces' summed by area)."""
    sizes = mesh.face_sizes
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    face = np.repeat(np.arange(len(sizes)), sizes)
    nxt = np.arange(len(mesh.corners)) + 1
    nxt[starts + sizes - 1] = starts
    cross = np.cross(points[mesh.corners], points[mesh.corners[nxt]])
    faces = np.stack([np.bincount(face, cross[:, k], len(sizes)) for k in range(3)], 1)
    verts = np.stack([np.bincount(mesh.corners, faces[face, k], len(points)) for k in range(3)], 1)
    return _unit(faces), _unit(verts)


def _unit(v: np.ndarray) -> np.ndarray:
    length = np.linalg.norm(v, axis=1, keepdims=True)
    return np.divide(v, length, out=np.zeros_like(v), where=length > 0)


def _turn(n: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """n turned by the rotation that takes unit a to unit b, row by row (Rodrigues); rows where
    either is missing, or b points straight back, stay as they are."""
    v = np.cross(a, b)
    c = np.einsum("ij,ij->i", a, b)
    ok = (c > -0.999) & (np.abs(a).sum(1) > 0) & (np.abs(b).sum(1) > 0)
    vn = np.cross(v, n)
    out = n + vn + np.cross(v, vn) / np.where(ok, 1 + c, 1.0)[:, None]
    return np.where(ok[:, None], out, n)


class Motion:
    """What moves in a Model: its scene's animations ("takes") and the parts they move. pose()
    writes a moment of the chosen take into a copy of the model's vertices."""
    TOGETHER = "All together"

    def __init__(self, scene, parts: list[Part]):
        self.scene, self.parts = scene, parts
        self.takes = [a for a in scene.animations if a.channels]
        self.names = [a.name or f"Take {k + 1}" for k, a in enumerate(self.takes)]
        if len(self.takes) > 1:
            self.names.insert(0, self.TOGETHER)
        # several takes that move different things (as Blender exports each object's action) play together
        sets = [{id(c.node) for c in a.channels} for a in self.takes]
        apart = all(not (sets[i] & sets[j]) for i in range(len(sets)) for j in range(i))
        self.select(self.TOGETHER if len(self.takes) > 1 and apart else self.names[len(self.takes) > 1])

    def select(self, name: str) -> None:
        """Play a take by its name (or all of them together)."""
        from meshport import Animation
        self.name = name
        chosen = self.takes if name == self.TOGETHER else [self.takes[self.names.index(name) - (len(self.takes) > 1)]]
        self.start = min(float(c.times[0]) for a in chosen for c in a.channels)
        self.end = max(float(c.times[-1]) for a in chosen for c in a.channels)
        by_node: dict[int, list] = {}
        for a in chosen:
            for c in a.channels:
                by_node.setdefault(id(c.node), []).append(c)
        self._own = {k: Animation("", cs) for k, cs in by_node.items()}  # each node's channels, looked up once
        moved: set[int] = set()

        def walk(node, above: bool) -> None:
            here = above or id(node) in by_node
            if here:
                moved.add(id(node))
            for child in node.children:
                walk(child, here)
        for root in self.scene.roots:
            walk(root, False)
        self.moving = [p for p in self.parts if id(p.node) in moved or id(p.node) in by_node
                       or (p.node.skin is not None and any(id(j) in moved for j in p.node.skin.joints))]

    @property
    def duration(self) -> float:
        return self.end - self.start

    def worlds(self, t: float) -> dict[int, np.ndarray]:
        out: dict[int, np.ndarray] = {}

        def walk(node, parent) -> None:
            own = self._own.get(id(node))
            local = own.local_matrix(node, t) if own is not None else node.matrix
            world = local if parent is None else parent @ local
            out[id(node)] = world
            for child in node.children:
                walk(child, world)
        for root in self.scene.roots:
            walk(root, None)
        return out

    def pose(self, t: float, vertices: np.ndarray) -> None:
        """Move the moving parts' rows of vertices (a copy of Model.vertices) to time t."""
        worlds = self.worlds(t)
        for p in self.moving:
            node, mesh = p.node, p.node.mesh
            own = self._own.get(id(node))
            weights = own.weights(node, t) if own is not None else None
            morphed = mesh.morphed(weights)
            points, normals = morphed[p.verts], p.local_normals(weights)
            if node.skin is not None:
                skin = node.skin
                m = (np.array([worlds.get(id(j), np.eye(4)) for j in skin.joints]).reshape(-1, 4, 4)
                     @ skin.inverse_binds)[:, :3, :].reshape(-1, 12).astype(np.float32)
                blend = p.weights[:, :1] * m[p.joints[:, 0]]
                for k in range(1, p.joints.shape[1]):  # each vertex's joints, blended by weight
                    blend += p.weights[:, k:k + 1] * m[p.joints[:, k]]
                blend = blend.reshape(-1, 3, 4)
                pos = (np.einsum("vij,vj->vi", blend[:, :, :3], points) + blend[:, :, 3])[p.row_vertex]
                nrm = np.einsum("rij,rj->ri", blend[p.row_vertex, :, :3], normals)
            else:
                world = worlds[id(node)]
                pos = (points @ world[:3, :3].T + world[:3, 3])[p.row_vertex]
                nrm = normals @ np.linalg.inv(world[:3, :3])  # by the inverse transpose
            rows = slice(p.start, p.start + p.count)
            vertices["pos"][rows] = pos
            vertices["normal"][rows] = _unit(nrm)


@dataclass
class Model:
    vertices: np.ndarray          # VERTEX
    triangles: np.ndarray         # uint32, three per triangle, grouped by batch
    edges: np.ndarray             # uint32, two per line: the polygons' outlines
    batches: list[Batch]          # opaque first, then see-through
    surfaces: list[Surface]
    lo: np.ndarray
    hi: np.ndarray
    parts: int
    units: str = "m"              # "" when the file doesn't say
    motion: Motion | None = None  # when the model is animated

    @property
    def triangle_count(self) -> int:
        return len(self.triangles) // 3

    def stats(self) -> str:
        size = " × ".join(f"{v:.3g}" for v in self.hi - self.lo)
        parts = "1 part" if self.parts == 1 else f"{self.parts:,} parts"
        mats = "1 material" if len(self.surfaces) == 1 else f"{len(self.surfaces)} materials"
        moving = f" · {self.motion.duration:.3g} s animation" if self.motion is not None else ""
        return (f"{parts} · {self.triangle_count:,} triangles · {mats} · {size}{' ' + self.units if self.units else ''}"
                f"{moving}")


def flatten(scene, fmt: str = "") -> Model:
    """Every mesh in world space, de-duplicated into one vertex buffer, triangles grouped by material.
    Skinned meshes are bent where their skeleton stands, and blend shapes applied at their weights.
    An animated scene also gets a Motion, and bounds that hold it all the way through."""
    from meshport.geometry import transform_normals, transform_points, unique_rows

    original = scene
    scene = scene.deformed()
    animated = any(a.channels for a in original.animations)
    sources = [n for n, _ in original.walk()]  # deformed() copies nodes in the same order
    motion_parts: list[Part] = []

    surfaces: list[Surface] = []
    surface_of: dict[int, int] = {}
    textures: dict[int, Texture | None] = {}
    tris_by_surface: dict[int, list[np.ndarray]] = {}
    vertex_parts: list[np.ndarray] = []
    edge_parts: list[np.ndarray] = []
    base = 0
    parts = 0
    total_tris = sum(int((n.mesh.face_sizes - 2).sum()) for n, _ in scene.walk() if n.mesh is not None)
    want_edges = total_tris <= MAX_WIRE_TRIANGLES

    def surface(mat) -> int:
        key = id(mat) if mat is not None else 0
        if key not in surface_of:
            surface_of[key] = len(surfaces)
            surfaces.append(_surface(mat, textures))
        return surface_of[key]

    triangulated: dict[int, tuple[np.ndarray, np.ndarray]] = {}  # a mesh used by many nodes is cut up once

    for (node, world), source in zip(scene.walk(), sources):
        mesh = node.mesh
        if mesh is None or not len(mesh.corners) or not len(mesh.face_sizes):
            continue
        parts += 1
        pos = transform_points(world, mesh.positions)
        rows = np.zeros(len(mesh.corners), VERTEX)
        rows["pos"] = pos[mesh.corners]
        if mesh.normals is not None:
            rows["normal"] = transform_normals(world, mesh.normals)
        else:
            rows["normal"] = corner_normals(pos, mesh.face_sizes, mesh.corners)
        if mesh.uvs:
            rows["uv"] = mesh.uvs[0]
        rows["color"] = 255 if mesh.colors is None else np.round(np.clip(mesh.colors, 0, 1) * 255)
        key = rows.view(np.uint8).reshape(len(rows), VERTEX.itemsize)
        bends = animated and (source.skin is not None or bool(source.mesh.targets))
        if bends:  # vertices in one place now may move apart later: keep them apart
            key = np.hstack([key, mesh.corners.astype("<i8").view(np.uint8).reshape(-1, 8)])
        first, index = unique_rows(key)
        vertex_parts.append(rows[first])
        if animated:
            if source.mesh.normals is not None:
                local = source.mesh.normals[first]
            else:  # the same normals, worked out in the node's own space
                local = corner_normals(source.mesh.positions, mesh.face_sizes, mesh.corners)[first]
            motion_parts.append(Part(source, base, first, local))

        if id(mesh) not in triangulated:
            triangulated[id(mesh)] = mesh.triangles(), mesh.triangle_faces()
        tris, tri_faces = triangulated[id(mesh)]
        if np.linalg.det(world[:3, :3]) < 0:  # mirrored: keep faces turning the same way
            tris = tris[:, ::-1]
        tris = (index[tris] + base).astype(np.uint32)
        slots = mesh.face_materials[tri_faces] if mesh.face_materials is not None \
            else np.zeros(len(tris), np.int64)
        for slot in np.unique(slots):
            mat = node.materials[min(int(slot), len(node.materials) - 1)] if node.materials else None
            tris_by_surface.setdefault(surface(mat), []).append(tris[slots == slot].ravel())

        if want_edges:
            edge_parts.append(_outline(mesh, index) + base)
        base += len(first)

    if not vertex_parts:
        raise ConversionError("No 3D geometry found in this file")
    vertices = np.concatenate(vertex_parts)
    order = sorted(tris_by_surface, key=lambda s: surfaces[s].alpha_mode == "BLEND")
    batches, chunks, at = [], [], 0
    for s in order:
        chunk = np.concatenate(tris_by_surface[s])
        batches.append(Batch(s, at, len(chunk)))
        chunks.append(chunk)
        at += len(chunk)
    edges = np.concatenate(edge_parts).astype(np.uint32) if edge_parts else np.zeros(0, np.uint32)
    lo, hi = vertices["pos"].min(0).astype(np.float64), vertices["pos"].max(0).astype(np.float64)
    motion = Motion(original, motion_parts) if animated and motion_parts else None
    if motion is not None and motion.moving:
        posed = vertices.copy()  # the view frames, and the grid sits under, the whole animation
        keys = np.unique(np.concatenate([c.times for a in motion.takes for c in a.channels]))
        if len(keys) > BOUND_SAMPLES * 4:  # a key every frame: a spread of them is enough
            keys = keys[np.linspace(0, len(keys) - 1, BOUND_SAMPLES * 4).astype(int)]
        times = np.union1d(np.linspace(motion.start, motion.end, BOUND_SAMPLES), keys)
        began, stride = time.perf_counter(), 1
        for k, t in enumerate(times):
            if k % stride:
                continue
            motion.pose(float(t), posed)
            lo, hi = np.minimum(lo, posed["pos"].min(0)), np.maximum(hi, posed["pos"].max(0))
            if k == 0:  # what one pose costs sets how many fit the budget: a heavy model gets a spread of them
                stride = max(1, math.ceil(len(times) * (time.perf_counter() - began) / BOUND_BUDGET))
    elif motion is not None:
        motion = None  # its animations move nothing that shows
    return Model(vertices, np.concatenate(chunks), edges, batches, surfaces, lo, hi,
                 parts, "" if fmt in UNITLESS else "m", motion)


def _outline(mesh, index: np.ndarray) -> np.ndarray:
    """Each polygon edge once, as pairs of output vertices (shared edges aren't doubled)."""
    sizes, starts = mesh.face_sizes, mesh.face_starts
    c = np.arange(len(mesh.corners))
    nxt = c + 1
    last = starts + sizes - 1
    nxt[last] = starts
    a, b = mesh.corners[c], mesh.corners[nxt]
    pairs = np.unique(np.sort(np.stack([a, b], 1), 1), axis=0)
    corner_of = np.zeros(len(mesh.positions), np.int64)  # any corner on each position
    corner_of[mesh.corners[::-1]] = c[::-1]
    return index[corner_of[pairs]].ravel()


def corner_normals(pos: np.ndarray, face_sizes: np.ndarray, corners: np.ndarray,
                   angle: float = SMOOTH_ANGLE) -> np.ndarray:
    """Per-corner normals for a mesh that has none: smooth across faces that meet at less than
    `angle` degrees, sharp elsewhere (so a CAD part's edges stay crisp and a sphere stays round)."""
    sizes = np.asarray(face_sizes, np.int64)
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    face = np.repeat(np.arange(len(sizes)), sizes)
    c = np.arange(len(corners))
    nxt = c + 1
    nxt[starts + sizes - 1] = starts
    p, pn = pos[corners], pos[corners[nxt]]
    area_normal = np.zeros((len(sizes), 3))  # Newell: length is twice the polygon's area
    for k in range(3):
        area_normal[:, k] = np.bincount(face, np.cross(p, pn)[:, k], len(sizes))
    length = np.linalg.norm(area_normal, axis=1, keepdims=True)
    unit = np.divide(area_normal, length, out=np.zeros_like(area_normal), where=length > 0)

    order = np.argsort(corners, kind="stable")
    v = corners[order]
    group_start = np.concatenate(([0], np.flatnonzero(np.diff(v)) + 1))
    group_size = np.diff(np.concatenate((group_start, [len(v)])))
    k = np.repeat(group_size, group_size)
    if int((k.astype(np.int64)).sum()) > 30_000_000:  # a huge fan: give up smoothing, stay flat
        return unit[face]
    a = np.repeat(np.arange(len(v)), k)
    within = np.arange(len(a)) - np.repeat(np.cumsum(k) - k, k)
    b = np.repeat(np.repeat(group_start, group_size), k) + within
    ca, cb = order[a], order[b]
    fa, fb = face[ca], face[cb]
    keep = np.einsum("ij,ij->i", unit[fa], unit[fb]) >= math.cos(math.radians(angle))
    out = np.zeros((len(corners), 3))
    for k3 in range(3):
        out[:, k3] = np.bincount(ca[keep], area_normal[fb[keep], k3], len(corners))
    length = np.linalg.norm(out, axis=1, keepdims=True)
    flat = length[:, 0] == 0
    out = np.divide(out, length, out=np.zeros_like(out), where=length > 0)
    out[flat] = unit[face[flat]]
    return out


def _surface(mat, textures: dict) -> Surface:
    if mat is None:
        return Surface("default")
    return Surface(mat.name, tuple(mat.base_color), tuple(mat.emissive), float(mat.roughness),
                   float(mat.metallic), mat.alpha_mode, _texture(mat.base_color_texture, textures))


def _texture(image, cache: dict) -> Texture | None:
    if image is None or not image.data:
        return None
    if id(image) not in cache:
        try:
            from PIL import Image as PILImage
            with PILImage.open(io.BytesIO(image.data)) as im:
                im = im.convert("RGBA")
                im.thumbnail((MAX_TEXTURE, MAX_TEXTURE))
                cache[id(image)] = Texture(im.width, im.height, im.tobytes())
        except Exception:  # noqa: BLE001 - an unreadable texture shouldn't stop the model showing
            cache[id(image)] = None
    return cache[id(image)]


class LoadJob(QThread):
    """Loads and flattens a model off the GUI thread."""
    done = Signal(object, str)  # Model or None, error message

    def __init__(self, path: Path, fmt: str):
        super().__init__()
        self.path, self.fmt = path, fmt

    def run(self) -> None:
        try:
            self.done.emit(flatten(load_scene(self.path, self.fmt), self.fmt), "")
        except (ConversionError, OSError, MemoryError) as exc:
            self.done.emit(None, str(exc) or type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - the window must always hear back
            self.done.emit(None, f"Couldn't show this model ({type(exc).__name__}: {exc})")


# ---------------------------------------------------------------- camera

def _perspective(fovy: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy) / 2)
    return np.array([[f / aspect, 0, 0, 0], [0, f, 0, 0],
                     [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]])


def _look_at(eye: np.ndarray, target: np.ndarray, up=(0.0, 1.0, 0.0)) -> np.ndarray:
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


@dataclass
class Camera:
    target: np.ndarray = field(default_factory=lambda: np.zeros(3))
    distance: float = 1.0
    yaw: float = -35.0    # degrees around the up axis; 0 looks at the model's front (+Z side)
    pitch: float = 22.0   # degrees above the horizon
    radius: float = 1.0   # of the model's bounding sphere
    fov: float = 40.0

    def frame(self, lo: np.ndarray, hi: np.ndarray) -> None:
        self.target = (lo + hi) / 2
        self.radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-6)
        self.distance = self.radius / math.sin(math.radians(self.fov) / 2) * 1.05
        self.yaw, self.pitch = -35.0, 22.0

    def eye(self) -> np.ndarray:
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        return self.target + self.distance * np.array([math.cos(p) * math.sin(-y), math.sin(p),
                                                       math.cos(p) * math.cos(y)])

    def basis(self) -> tuple[np.ndarray, np.ndarray]:
        view = _look_at(self.eye(), self.target)
        return view[0, :3], view[1, :3]  # right, up

    def view_proj(self, aspect: float) -> np.ndarray:
        near = max(self.distance - self.radius * 1.5, self.distance * 0.002, 1e-6)
        far = self.distance + self.radius * 6
        return _perspective(self.fov, aspect, near, far) @ _look_at(self.eye(), self.target)

    def orbit(self, dx: float, dy: float) -> None:
        self.yaw -= dx * 0.4
        self.pitch = max(-89.0, min(89.0, self.pitch + dy * 0.4))

    def pan(self, dx: float, dy: float, height: int) -> None:
        right, up = self.basis()
        per_pixel = 2 * self.distance * math.tan(math.radians(self.fov) / 2) / max(height, 1)
        self.target = self.target - right * dx * per_pixel + up * dy * per_pixel

    def zoom(self, steps: float, toward: tuple[float, float] = (0.0, 0.0), aspect: float = 1.0) -> None:
        """steps > 0 moves closer. toward is the cursor in -1..1 view coordinates: the point under
        it stays put, as in map apps."""
        new = max(self.distance * 0.85 ** steps, self.radius * 1e-3)
        right, up = self.basis()
        half = math.tan(math.radians(self.fov) / 2) * self.distance
        under = self.target + right * toward[0] * half * aspect + up * toward[1] * half
        self.target = self.target + (under - self.target) * (1 - new / self.distance)
        self.distance = new


# ---------------------------------------------------------------- drawing

def _shader(name: str) -> QShader:
    return QShader.fromSerialized((SHADERS / f"{name}.qsb").read_bytes())


def _rgb(color: QColor, alpha: float = 1.0) -> list[float]:
    return [color.redF(), color.greenF(), color.blueF(), alpha]


def _grid(model: Model) -> np.ndarray:
    """A ground grid under the model: lines on a round step, about 10 across."""
    size = float(max(model.hi[0] - model.lo[0], model.hi[2] - model.lo[2], 1e-6)) * 1.6
    decade = 10 ** math.floor(math.log10(size / 10))
    step = next(decade * m for m in (1, 2, 5, 10) if size / (decade * m) <= 12)
    cx, cz = (model.lo[0] + model.hi[0]) / 2, (model.lo[2] + model.hi[2]) / 2
    n = math.ceil(size / step / 2)
    lines = np.arange(-n, n + 1) * step
    x0, x1, z0, z1 = cx - n * step, cx + n * step, cz - n * step, cz + n * step
    y = model.lo[1]
    pts = [((x0, y, cz + t), (x1, y, cz + t)) for t in lines] + [((cx + t, y, z0), (cx + t, y, z1)) for t in lines]
    out = np.zeros(len(pts) * 2, VERTEX)
    out["pos"] = np.array(pts).reshape(-1, 3)
    return out


def _destroy_surfaces(surfaces: list) -> None:
    """Per-material (bindings, uniform buffer, texture or None); a texture shared by several
    materials is destroyed once."""
    done: set[int] = set()
    for item in surfaces:
        for r in item:
            if r is not None and id(r) not in done:
                done.add(id(r))
                r.destroy()


class ModelView(QRhiWidget):
    """Draws a Model. Left-drag turns it, right- or middle-drag moves it, the wheel zooms toward
    the cursor. Double-click emits activated (the window decides: re-frame or open bigger)."""
    activated = Signal()
    failed = Signal(str)  # why nothing can be drawn

    def __init__(self, theme: dict, background_key: str = "bg", parent: QWidget | None = None):
        super().__init__(parent)
        self.theme, self.background_key = theme, background_key  # theme is the window's live palette
        self.setSampleCount(4)
        self.setMinimumSize(QSize(120, 90))
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.model: Model | None = None
        self.camera = Camera()
        self.wireframe = False
        self._dirty = False  # the model changed: rebuild GPU buffers
        self._last: QPointF | None = None
        self._res: dict = {}
        self._pending = None  # uploads waiting for the next frame
        self._keep: list = []  # image bytes the GPU upload still reads from
        self._ranges: dict = {}
        self._pose: np.ndarray | None = None  # the model's vertices as they're moved now
        self._pose_new = False                # ...and not drawn yet
        self._posed: bytes | None = None      # the bytes an upload still reads from
        self.renderFailed.connect(lambda: self.failed.emit(
            "3D preview isn't available on this PC (no Direct3D or OpenGL)"))

    def set_model(self, model: Model) -> None:
        self.model = model
        self._pose = None
        self.camera.frame(model.lo, model.hi)
        self._dirty = True
        self.update()

    def set_pose(self, vertices: np.ndarray) -> None:
        """Draw the model with these vertices (its own, moved) from the next frame on."""
        self._pose, self._pose_new = vertices, True
        self.update()

    def reset_view(self) -> None:
        if self.model is not None:
            self.camera.frame(self.model.lo, self.model.hi)
            self.update()

    def set_wireframe(self, on: bool) -> None:
        self.wireframe = on
        self.update()

    # -- input

    def mousePressEvent(self, e) -> None:
        self._last = e.position()
        self.setCursor(Qt.ClosedHandCursor)
        e.accept()

    def mouseReleaseEvent(self, e) -> None:
        self._last = None
        self.setCursor(Qt.OpenHandCursor)
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._last is None:
            return
        d = e.position() - self._last
        self._last = e.position()
        if e.buttons() & Qt.LeftButton and not e.modifiers() & Qt.ShiftModifier:
            self.camera.orbit(d.x(), d.y())
        else:
            self.camera.pan(d.x(), d.y(), self.height())
        self.update()

    def wheelEvent(self, e) -> None:
        steps = e.angleDelta().y() / 120
        if steps:
            p = e.position()
            toward = (2 * p.x() / max(self.width(), 1) - 1, 1 - 2 * p.y() / max(self.height(), 1))
            self.camera.zoom(steps, toward, self.width() / max(self.height(), 1))
            self.update()
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        self.activated.emit()
        e.accept()

    def keyPressEvent(self, e) -> None:
        step = {Qt.Key_Left: (-12, 0), Qt.Key_Right: (12, 0), Qt.Key_Up: (0, -12), Qt.Key_Down: (0, 12)}.get(e.key())
        if step:
            self.camera.orbit(*step)
        elif e.key() in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
            self.camera.zoom(1 if e.key() != Qt.Key_Minus else -1)
        elif e.key() in (Qt.Key_Home, Qt.Key_R):
            self.reset_view()
        else:
            return super().keyPressEvent(e)
        self.update()

    # -- GPU resources

    def initialize(self, cb) -> None:
        self._release()
        rhi = self.rhi()
        res = self._res
        res["camera"] = self._buffer(QRhiBuffer.Type.Dynamic, QRhiBuffer.UsageFlag.UniformBuffer, 128)
        res["wire_color"] = self._buffer(QRhiBuffer.Type.Dynamic, QRhiBuffer.UsageFlag.UniformBuffer, 16)
        res["grid_color"] = self._buffer(QRhiBuffer.Type.Dynamic, QRhiBuffer.UsageFlag.UniformBuffer, 16)
        res["sampler"] = rhi.newSampler(QRhiSampler.Filter.Linear, QRhiSampler.Filter.Linear,
                                        QRhiSampler.Filter.Linear, QRhiSampler.AddressMode.Repeat,
                                        QRhiSampler.AddressMode.Repeat)
        res["sampler"].create()
        res["white"] = rhi.newTexture(QRhiTexture.Format.RGBA8, QSize(1, 1))
        res["white"].create()
        self._pending = rhi.nextResourceUpdateBatch()
        white = QImage(1, 1, QImage.Format_RGBA8888)
        white.fill(Qt.white)
        self._pending.uploadTexture(res["white"], white)
        rpd = self.renderTarget().renderPassDescriptor()
        res["layout_srb"] = self._mesh_srb(res["white"], None)
        res["line_srb"] = self._line_srb(res["wire_color"])
        res["grid_srb"] = self._line_srb(res["grid_color"])
        res["opaque"] = self._pipeline(rpd, res["layout_srb"], "mesh", blend=False)
        res["blend"] = self._pipeline(rpd, res["layout_srb"], "mesh", blend=True)
        res["lines"] = self._pipeline(rpd, res["line_srb"], "line", blend=True)
        self._dirty = True

    def _buffer(self, kind, usage, size: int):
        buf = self.rhi().newBuffer(kind, usage, max(size, 4))
        if not buf.create():
            buf.destroy()
            return None
        return buf

    def _mesh_srb(self, texture, surface_buffer):
        stages = QRhiShaderResourceBinding.StageFlag.VertexStage | QRhiShaderResourceBinding.StageFlag.FragmentStage
        srb = self.rhi().newShaderResourceBindings()
        srb.setBindings([
            QRhiShaderResourceBinding.uniformBuffer(0, stages, self._res["camera"]),
            QRhiShaderResourceBinding.uniformBuffer(
                1, QRhiShaderResourceBinding.StageFlag.FragmentStage, surface_buffer or self._res["wire_color"]),
            QRhiShaderResourceBinding.sampledTexture(
                2, QRhiShaderResourceBinding.StageFlag.FragmentStage, texture, self._res["sampler"]),
        ])
        srb.create()
        return srb

    def _line_srb(self, color_buffer):
        srb = self.rhi().newShaderResourceBindings()
        srb.setBindings([
            QRhiShaderResourceBinding.uniformBuffer(0, QRhiShaderResourceBinding.StageFlag.VertexStage,
                                                    self._res["camera"]),
            QRhiShaderResourceBinding.uniformBuffer(1, QRhiShaderResourceBinding.StageFlag.FragmentStage,
                                                    color_buffer),
        ])
        srb.create()
        return srb

    def _pipeline(self, rpd, srb, shader: str, blend: bool):
        p = self.rhi().newGraphicsPipeline()
        p.setShaderStages([QRhiShaderStage(QRhiShaderStage.Type.Vertex, _shader(f"{shader}.vert")),
                           QRhiShaderStage(QRhiShaderStage.Type.Fragment, _shader(f"{shader}.frag"))])
        layout = QRhiVertexInputLayout()
        layout.setBindings([QRhiVertexInputBinding(VERTEX.itemsize)])
        attrs = [QRhiVertexInputAttribute(0, 0, QRhiVertexInputAttribute.Format.Float3, 0)]
        if shader == "mesh":
            attrs += [QRhiVertexInputAttribute(0, 1, QRhiVertexInputAttribute.Format.Float3, 12),
                      QRhiVertexInputAttribute(0, 2, QRhiVertexInputAttribute.Format.Float2, 24),
                      QRhiVertexInputAttribute(0, 3, QRhiVertexInputAttribute.Format.UNormByte4, 32)]
            # pushed back a little, so wireframe lines drawn on the surface aren't hidden by it
            p.setDepthBias(1)
            p.setSlopeScaledDepthBias(1.0)
        else:
            p.setTopology(QRhiGraphicsPipeline.Topology.Lines)
        layout.setAttributes(attrs)
        p.setVertexInputLayout(layout)
        p.setShaderResourceBindings(srb)
        p.setRenderPassDescriptor(rpd)
        p.setSampleCount(self.sampleCount())
        p.setDepthTest(True)
        p.setDepthOp(QRhiGraphicsPipeline.CompareOp.LessOrEqual)
        p.setDepthWrite(not blend or shader == "line")
        if blend:
            t = QRhiGraphicsPipeline.TargetBlend()
            t.enable = True
            t.srcColor = QRhiGraphicsPipeline.BlendFactor.SrcAlpha
            t.dstColor = QRhiGraphicsPipeline.BlendFactor.OneMinusSrcAlpha
            t.srcAlpha = QRhiGraphicsPipeline.BlendFactor.One
            t.dstAlpha = QRhiGraphicsPipeline.BlendFactor.OneMinusSrcAlpha
            p.setTargetBlends([t])
        p.create()
        return p

    def _upload_model(self, u) -> bool:
        """(Re)create the model's buffers, textures and per-material bindings."""
        for key in ("vertices", "indices"):
            if key in self._res:
                self._res.pop(key).destroy()
        _destroy_surfaces(self._res.pop("surfaces", []))
        self._keep = []
        m = self.model
        grid = _grid(m)
        vertices = np.concatenate([m.vertices, grid])
        grid_index = np.arange(len(m.vertices), len(vertices), dtype=np.uint32)
        indices = np.concatenate([m.triangles, m.edges, grid_index])
        self._ranges = {"edges": (len(m.triangles), len(m.edges)), "grid": (len(m.triangles) + len(m.edges), len(grid_index))}
        kind = QRhiBuffer.Type.Static if m.motion is not None else QRhiBuffer.Type.Immutable  # Static: re-uploaded
        vb = self._buffer(kind, QRhiBuffer.UsageFlag.VertexBuffer, vertices.nbytes)
        ib = self._buffer(QRhiBuffer.Type.Immutable, QRhiBuffer.UsageFlag.IndexBuffer, indices.nbytes)
        if vb is None or ib is None:
            for b in (vb, ib):
                if b is not None:
                    b.destroy()
            self.model = None
            self.failed.emit(f"This model is too big for this PC's graphics card "
                             f"({m.triangle_count:,} triangles)")
            return False
        u.uploadStaticBuffer(vb, vertices.tobytes())
        u.uploadStaticBuffer(ib, indices.tobytes())
        self._res["vertices"], self._res["indices"] = vb, ib

        rhi = self.rhi()
        surfaces = []
        textures: dict[int, object] = {}
        for s in m.surfaces:
            tex = self._res["white"]
            if s.texture is not None:
                if id(s.texture) not in textures:
                    t = rhi.newTexture(QRhiTexture.Format.RGBA8, QSize(s.texture.width, s.texture.height), 1,
                                       QRhiTexture.Flag.MipMapped | QRhiTexture.Flag.UsedWithGenerateMips)
                    t.create()
                    img = QImage(s.texture.rgba, s.texture.width, s.texture.height, QImage.Format_RGBA8888)
                    self._keep.append((s.texture.rgba, img))
                    u.uploadTexture(t, img)
                    u.generateMips(t)
                    textures[id(s.texture)] = t
                tex = textures[id(s.texture)]
            buf = self._buffer(QRhiBuffer.Type.Dynamic, QRhiBuffer.UsageFlag.UniformBuffer, 48)
            cutoff = 0.5 if s.alpha_mode == "MASK" else -1.0
            data = np.array([*s.base_color, *s.emissive, 0.0,
                             1.0 if s.texture is not None else 0.0, cutoff, s.roughness, s.metallic], np.float32)
            u.updateDynamicBuffer(buf, 0, 48, data.tobytes())
            surfaces.append((self._mesh_srb(tex, buf), buf, tex if tex is not self._res["white"] else None))
        self._res["surfaces"] = surfaces
        return True

    def render(self, cb) -> None:
        u = self._pending or self.rhi().nextResourceUpdateBatch()
        self._pending = None
        bg = QColor(self.theme.get(self.background_key, "#202020"))
        dark = bg.lightnessF() < 0.5
        if self.model is not None and self._dirty:
            self._dirty = False
            self._pose_new = self._upload_model(u) and self._pose is not None  # buffers rebuilt: pose again
        if self.model is not None and self._pose_new and "vertices" in self._res:
            self._posed = self._pose.tobytes()
            u.uploadStaticBuffer(self._res["vertices"], 0, len(self._posed), self._posed)
            self._pose_new = False

        size = self.renderTarget().pixelSize()
        if self.model is not None:
            corr = np.array(self.rhi().clipSpaceCorrMatrix().data(), np.float64).reshape(4, 4).T
            view_proj = corr @ self.camera.view_proj(size.width() / max(size.height(), 1))
            eye = self.camera.eye()
            right, up = self.camera.basis()
            light = (eye - self.camera.target) / max(self.camera.distance, 1e-9) + up * 0.6 - right * 0.4
            sky = [0.34, 0.35, 0.38, 1] if dark else [0.38, 0.39, 0.42, 1]
            ground = [0.12, 0.11, 0.11, 1] if dark else [0.16, 0.15, 0.15, 1]
            camera = np.concatenate([view_proj.T.ravel(), [*eye, 1], [*light, 0], sky, ground]).astype(np.float32)
            u.updateDynamicBuffer(self._res["camera"], 0, 128, camera.tobytes())
            wire, grid = QColor(self.theme.get("accent", "#6366f1")), QColor(self.theme.get("text", "#000000"))
            u.updateDynamicBuffer(self._res["wire_color"], 0, 16, np.array(_rgb(wire, 0.9), np.float32).tobytes())
            u.updateDynamicBuffer(self._res["grid_color"], 0, 16,
                                  np.array(_rgb(grid, 0.12 if dark else 0.14), np.float32).tobytes())

        cb.beginPass(self.renderTarget(), bg, QRhiDepthStencilClearValue(1.0, 0), u)
        if self.model is not None:
            cb.setViewport(QRhiViewport(0, 0, size.width(), size.height()))
            vertex_input = [(self._res["vertices"], 0)]
            index_format = QRhiCommandBuffer.IndexFormat.IndexUInt32

            def draw(pipeline, srb, first: int, count: int) -> None:
                if count:
                    cb.setGraphicsPipeline(pipeline)
                    cb.setShaderResources(srb)
                    cb.setVertexInput(0, vertex_input, self._res["indices"], 0, index_format)
                    cb.drawIndexed(count, 1, first)

            draw(self._res["lines"], self._res["grid_srb"], *self._ranges["grid"])
            for b in self.model.batches:
                see_through = self.model.surfaces[b.surface].alpha_mode == "BLEND"
                draw(self._res["blend" if see_through else "opaque"], self._res["surfaces"][b.surface][0],
                     b.first, b.count)
            if self.wireframe:
                draw(self._res["lines"], self._res["line_srb"], *self._ranges["edges"])
        cb.endPass()

    def releaseResources(self) -> None:
        self._release()

    def _release(self) -> None:
        _destroy_surfaces(self._res.pop("surfaces", []))
        for r in self._res.values():
            r.destroy()
        self._res = {}
        self._pending = None
        self._dirty = self.model is not None


# ---------------------------------------------------------------- widgets

_RUNNING: set[LoadJob] = set()
_OPEN: list[QWidget] = []  # viewer windows, kept alive while they show
FRAME_MS = 16              # a frame of playback, at most 60 a second
POSE_SHARE = 0.4           # of each frame posing may take; a heavy model plays fewer frames instead
SLOWEST_MS = 250           # ...but never fewer than 4 a second


class Player(QObject):
    """Plays a Model's Motion on a ModelView, looping: its own choice of take and moment (the
    model's Motion is shared, by the preview and the big viewer). Posing runs on the GUI thread,
    so a heavy model plays fewer frames a second rather than slowing the app down, and nothing is
    posed while the view is hidden."""
    moved = Signal(float)   # the moment shown
    toggled = Signal(bool)  # playing or not

    def __init__(self, view: ModelView, model: Model):
        super().__init__(view)
        self.view, self.model = view, model
        self.motion = copy.copy(model.motion)
        self.posed = model.vertices.copy()
        self.time = self.motion.start
        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()

    @property
    def playing(self) -> bool:
        return self.timer.isActive()

    def play(self) -> None:
        if self.time >= self.motion.end:  # played to the end: from the start again
            self.seek(self.motion.start)
        self.clock.restart()
        self.timer.start()
        self.toggled.emit(True)

    def pause(self) -> None:
        self.timer.stop()
        self.toggled.emit(False)

    def stop(self) -> None:
        self.timer.stop()

    def seek(self, t: float) -> None:
        m = self.motion
        self.time = min(max(float(t), m.start), m.end)
        m.pose(self.time, self.posed)
        self.view.set_pose(self.posed)
        self.moved.emit(self.time)

    def select(self, name: str) -> None:
        """Play another take (by its name), from its start."""
        self.motion.select(name)
        self.posed = self.model.vertices.copy()  # what the last take moved goes back to rest
        self.seek(self.motion.start)

    def _tick(self) -> None:
        elapsed = self.clock.restart() / 1000.0
        if not self.view.isVisible():
            return  # nobody can see it: spend nothing
        m = self.motion
        t = self.time + elapsed
        if t > m.end:  # loops
            t = m.start + (t - m.start) % m.duration
        began = time.perf_counter()
        self.seek(t)
        cost = (time.perf_counter() - began) * 1000
        self.timer.setInterval(int(min(SLOWEST_MS, max(FRAME_MS, cost / POSE_SHARE))))

class ViewerPanel(QWidget):
    """A ModelView with a message in its place while loading, or when something goes wrong. An
    animated model gets a Player, which starts playing it."""
    loaded = Signal(object)  # Model
    activated = Signal()     # the model was double-clicked

    def __init__(self, theme: dict, background_key: str = "bg"):
        super().__init__()
        self.theme, self.background_key = theme, background_key
        self.player: Player | None = None
        self.stack = QStackedLayout(self)
        self.message = QLabel()
        self.message.setObjectName("muted")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        self.stack.addWidget(self.message)
        self.view: ModelView | None = None  # made on first use: creating it switches the window to GPU drawing
        self.model: Model | None = None
        self.job: LoadJob | None = None
        self.path: Path | None = None

    def load(self, path: Path, fmt: str) -> None:
        self.path, self.model = path, None
        self.show_message("Loading 3D preview…")
        job = LoadJob(path, fmt)
        job.done.connect(self._loaded)  # a bound slot: dropped if this panel is closed first
        _RUNNING.add(job)  # a QThread must outlive its run, even if the panel goes away
        job.finished.connect(lambda: _RUNNING.discard(job))
        self.job = job
        job.start()

    def _loaded(self, model: Model | None, error: str) -> None:
        if self.sender() is not self.job:
            return  # another file was dropped meanwhile
        self.job = None
        if model is None:
            self.show_message(error)
        else:
            self.show_model(model)
            self.loaded.emit(model)

    def show_model(self, model: Model) -> None:
        self.model = model
        if self.view is None:
            self.view = ModelView(self.theme, self.background_key)
            self.view.activated.connect(self.activated)
            self.view.failed.connect(self.show_message)
            self.stack.addWidget(self.view)
        self.view.set_model(model)
        self.stack.setCurrentWidget(self.view)
        self._drop_player()
        if model.motion is not None and model.motion.duration > 0:
            self.player = Player(self.view, model)
            self.player.seek(self.player.motion.start)
            self.player.play()

    def _drop_player(self) -> None:
        if self.player is not None:
            self.player.stop()
            self.player.deleteLater()
            self.player = None

    def show_message(self, text: str) -> None:
        self.message.setText(text)
        self.stack.setCurrentWidget(self.message)

    def clear(self) -> None:
        self.path, self.model, self.job = None, None, None
        self._drop_player()
        self.show_message("")


class ViewerWindow(QWidget):
    """The big viewer: the model, a few buttons and what's in it, and for an animated model a
    player: play and pause (or the space bar), a timeline to scrub, and which take to play."""
    STEPS = 1000  # the timeline's resolution

    def __init__(self, theme: dict, path: Path, fmt: str, model: Model | None = None):
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"{path.name} · ConvertAll")
        self.resize(960, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        self.wire = QPushButton("Wireframe")
        self.wire.setCheckable(True)
        self.wire.setEnabled(False)
        reset = QPushButton("Reset view")
        self.stats = QLabel("")
        self.stats.setObjectName("muted")
        bar.addWidget(self.wire)
        bar.addWidget(reset)
        bar.addSpacing(8)
        bar.addWidget(self.stats, 1)
        lay.addLayout(bar)
        self.panel = ViewerPanel(theme, "bg")
        self.panel.loaded.connect(self._show_stats)
        self.panel.activated.connect(lambda: self.panel.view.reset_view())
        lay.addWidget(self.panel, 1)
        self.controls = QWidget()
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.play = QPushButton("Play")
        self.play.setCheckable(True)
        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setRange(0, self.STEPS)
        self.clock = QLabel("")
        self.clock.setObjectName("muted")
        self.take = QComboBox()
        row.addWidget(self.play)
        row.addWidget(self.timeline, 1)
        row.addWidget(self.clock)
        row.addWidget(self.take)
        self.controls.hide()
        lay.addWidget(self.controls)
        self.hint = QLabel("Drag to turn · right-drag to move · scroll to zoom · double-click to reset")
        self.hint.setObjectName("muted")
        lay.addWidget(self.hint)
        self.player: Player | None = None
        self._resume = False  # playing when the timeline was grabbed
        self.play.toggled.connect(self._play)
        self.timeline.valueChanged.connect(self._scrub)
        self.timeline.sliderPressed.connect(self._grab)
        self.timeline.sliderReleased.connect(self._let_go)
        self.take.currentTextChanged.connect(self._choose)
        self.wire.toggled.connect(lambda on: self.panel.view and self.panel.view.set_wireframe(on))
        reset.clicked.connect(lambda: self.panel.view and self.panel.view.reset_view())
        if model is not None:
            self.panel.show_model(model)
            self._show_stats(model)
        else:
            self.panel.load(path, fmt)
        _OPEN.append(self)  # Qt deletes the window on close; Python must not before
        self.destroyed.connect(lambda *_: _OPEN.remove(self) if self in _OPEN else None)

    def _show_stats(self, model: Model) -> None:
        self.stats.setText(model.stats())
        self.wire.setEnabled(len(model.edges) > 0)
        self._setup_player(model)

    # -- animation

    def _setup_player(self, model: Model) -> None:
        self.player = self.panel.player
        self.controls.setVisible(self.player is not None)
        if self.player is None:
            return
        self.hint.setText(self.hint.text() + " · space to play or pause")
        motion = self.player.motion
        self.take.blockSignals(True)
        self.take.clear()
        self.take.addItems(motion.names)
        self.take.setCurrentText(motion.name)
        self.take.blockSignals(False)
        self.take.setVisible(len(motion.names) > 1)
        self.player.moved.connect(self._moved)
        self.player.toggled.connect(self._toggled)
        self._moved(self.player.time)
        self._toggled(self.player.playing)

    @property
    def time(self) -> float:
        return self.player.time if self.player is not None else 0.0

    def _play(self, on: bool) -> None:
        if self.player is not None and on != self.player.playing:
            self.player.play() if on else self.player.pause()
        self.play.setText("Pause" if on else "Play")

    def _toggled(self, on: bool) -> None:
        self.play.blockSignals(True)
        self.play.setChecked(on)
        self.play.blockSignals(False)
        self.play.setText("Pause" if on else "Play")

    def _moved(self, t: float) -> None:
        m = self.player.motion
        self.clock.setText(f"{t - m.start:.2f} / {m.duration:.2f} s")
        if not self.timeline.isSliderDown():
            self.timeline.blockSignals(True)
            self.timeline.setValue(round((t - m.start) / m.duration * self.STEPS))
            self.timeline.blockSignals(False)

    def _scrub(self, value: int) -> None:
        if self.player is not None:
            m = self.player.motion
            self.player.seek(m.start + value / self.STEPS * m.duration)

    def _grab(self) -> None:
        self._resume = self.play.isChecked()
        self.play.setChecked(False)

    def _let_go(self) -> None:
        if self._resume:
            self.play.setChecked(True)

    def _choose(self, name: str) -> None:
        if self.player is not None and name in self.player.motion.names:
            self.player.select(name)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Space and self.player is not None:
            self.play.toggle()
        else:
            super().keyPressEvent(e)
