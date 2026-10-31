"""The 3D viewer: loading every model format, turning scenes into GPU buffers, and drawing them."""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
from meshport import Material, Mesh, Node, Scene

from convertall import viewer
from convertall.formats import viewable

from .samples import Samples

CUBE_POINTS = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
CUBE_FACES = [[1, 3, 2, 0], [6, 7, 5, 4], [4, 5, 1, 0], [3, 7, 6, 2], [2, 6, 4, 0], [5, 7, 3, 1]]  # outward


def cube(name="cube") -> Mesh:
    return Mesh(name, CUBE_POINTS.copy(), np.full(6, 4), np.array(CUBE_FACES).ravel())


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    return Samples(tmp_path_factory.mktemp("samples"))


def signed_volume(model: viewer.Model) -> float:
    p = model.vertices["pos"].astype(float)
    t = model.triangles.reshape(-1, 3)
    return float(np.einsum("ij,ij->i", p[t[:, 0]], np.cross(p[t[:, 1]], p[t[:, 2]])).sum() / 6)


# ---- scene -> buffers

def test_a_cube_without_normals_gets_sharp_edges():
    model = viewer.flatten(Scene([Node("box", mesh=cube())]))
    assert model.triangle_count == 12 and model.parts == 1
    assert len(model.vertices) == 24  # each corner keeps its face's normal: 90° edges stay sharp
    assert len(model.edges) == 2 * 12  # the quads' outlines, without the diagonals
    normals = model.vertices["normal"]
    assert np.allclose(np.abs(normals).max(1), 1) and np.allclose(np.linalg.norm(normals, axis=1), 1)
    assert np.allclose(model.lo, 0) and np.allclose(model.hi, 1)
    assert signed_volume(model) == pytest.approx(1.0)  # faces point outward


def test_a_sphere_without_normals_is_smooth():
    import trimesh
    ball = trimesh.creation.icosphere(2)
    mesh = Mesh("ball", ball.vertices, np.full(len(ball.faces), 3), ball.faces.ravel())
    model = viewer.flatten(Scene([Node("ball", mesh=mesh)]))
    assert len(model.vertices) == len(ball.vertices)  # shared corners merge back into one vertex each
    pos = model.vertices["pos"].astype(float)
    assert np.einsum("ij,ij->i", model.vertices["normal"], pos / np.linalg.norm(pos, axis=1, keepdims=True)).min() > 0.98


def test_mirrored_nodes_keep_facing_out_and_world_transforms_apply():
    mirror = np.diag([-1.0, 1, 1, 1])
    mirror[:3, 3] = (-2, 0, 0)
    model = viewer.flatten(Scene([Node("a", mesh=cube()), Node("b", mirror, cube("c"))]))
    assert model.parts == 2
    assert np.allclose(model.lo, (-3, 0, 0)) and np.allclose(model.hi, (1, 1, 1))
    assert signed_volume(model) == pytest.approx(2.0)


def test_skinned_meshes_show_where_their_skeleton_holds_them():
    from meshport import Morph, Skin
    mesh = cube()
    mesh.targets, mesh.target_weights = [Morph("Up", np.tile([0, 1.0, 0], (8, 1)))], np.array([0.5])
    bone = Node("bone", np.diag([1.0, 1, 1, 1]))
    bone.matrix[:3, 3] = (10, 0, 0)
    body = Node("body", mesh=mesh)  # its own transform plays no part once skinned
    body.matrix[:3, 3] = (-50, 0, 0)
    body.skin = Skin([bone], np.eye(4)[None], np.zeros((8, 1), int), np.ones((8, 1)))
    model = viewer.flatten(Scene([bone, body]))
    assert np.allclose(model.lo, (10, 0.5, 0)) and np.allclose(model.hi, (11, 1.5, 1))


def test_materials_become_batches_with_see_through_ones_last():
    glass = Material("glass", base_color=(0.2, 0.5, 1, 0.3), alpha_mode="BLEND")
    paint = Material("paint", base_color=(1, 0, 0, 1))
    mesh = cube()
    mesh.face_materials = np.array([0, 0, 1, 1, 0, 1])
    shared = cube("shared")
    scene = Scene([Node("two", mesh=mesh, materials=[glass, paint]),
                   Node("again", np.diag([1, 1, 1, 1.0]), shared, [paint]), Node("plain", mesh=cube("p"))])
    model = viewer.flatten(scene)
    names = [model.surfaces[b.surface].name for b in model.batches]
    assert names[-1] == "glass" and sorted(names) == ["default", "glass", "paint"]
    counts = {model.surfaces[b.surface].name: b.count // 3 for b in model.batches}
    assert counts == {"glass": 6, "paint": 6 + 12, "default": 12}
    firsts = [b.first for b in model.batches]
    assert firsts == sorted(firsts) and sum(b.count for b in model.batches) == len(model.triangles)


def test_textures_are_decoded_once_and_shrunk():
    import io

    from meshport import Image
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (4096, 1024), (10, 200, 30)).save(buf, "PNG")
    img = Image("big", buf.getvalue())
    a, b = Material("a", base_color_texture=img), Material("b", base_color_texture=img)
    model = viewer.flatten(Scene([Node("x", mesh=cube(), materials=[a]), Node("y", mesh=cube("y"), materials=[b])]))
    tex = [s.texture for s in model.surfaces]
    assert tex[0] is tex[1] and (tex[0].width, tex[0].height) == (2048, 512)
    assert len(tex[0].rgba) == 2048 * 512 * 4


def test_a_broken_texture_doesnt_stop_the_model():
    from meshport import Image
    mat = Material("m", base_color_texture=Image("bad", b"\x89PNG not really"))
    model = viewer.flatten(Scene([Node("x", mesh=cube(), materials=[mat])]))
    assert model.surfaces[0].texture is None and model.triangle_count == 12


def test_an_empty_scene_is_an_error():
    with pytest.raises(viewer.ConversionError):
        viewer.flatten(Scene([Node("empty")]))


def test_stats_line():
    model = viewer.flatten(Scene([Node("box", np.diag([2.0, 1, 0.5, 1]), cube())]), "glb")
    assert model.stats() == "1 part · 12 triangles · 1 material · 2 × 1 × 0.5 m"
    assert viewer.flatten(Scene([Node("box", mesh=cube())]), "stl").stats().endswith("1 × 1 × 1")


# ---- every format the viewer can open

MODEL_FORMATS = ["glb", "gltf", "stl", "obj", "ply", "off", "3mf", "dae", "fbx", "3ds", "usd", "usdz", "abc",
                 "step", "iges", "brep"]


@pytest.mark.parametrize("fmt", MODEL_FORMATS)
def test_opens_every_model_format(samples, fmt):
    model = viewer.flatten(viewer.load_scene(samples(fmt), fmt), fmt)
    size = model.hi - model.lo
    if fmt in ("step", "iges", "brep"):  # a 40 x 30 x 5 plate, Z up in the file: flat on the ground here
        assert np.allclose(size, (40, 5, 30), atol=0.01)
    else:  # a 2 m box and a 1 m-radius ball beside it
        assert np.allclose(size, (6, 2, 2), atol=0.05)
    assert model.triangle_count > 12 and len(model.edges)


def test_opens_blend_files(samples):
    model = viewer.flatten(viewer.load_scene(samples("blend"), "blend"), "blend")
    assert model.parts == 5 and model.surfaces[0].texture is not None  # packed in the file


def test_unreadable_model_is_a_readable_error(tmp_path):
    bad = tmp_path / "broken.glb"
    bad.write_bytes(b"glTF\x02\x00\x00\x00 not really")
    with pytest.raises(viewer.ConversionError):
        viewer.load_scene(bad, "glb")


def test_viewable_formats():
    assert all(viewable(f) for f in MODEL_FORMATS + ["blend", "usd", "usdz", "abc"])
    assert not any(viewable(f) for f in ("dxf", "png", "pdf", "svg", "zip"))


# ---- camera

def test_camera_frames_the_model_and_zooms_toward_the_cursor():
    cam = viewer.Camera()
    cam.frame(np.array([0.0, 0, 0]), np.array([2.0, 2, 2]))
    assert np.allclose(cam.target, 1) and cam.distance > cam.radius
    before, far = cam.target.copy(), cam.distance
    cam.zoom(2)  # toward the middle of the view: straight in
    assert np.allclose(cam.target, before) and cam.distance == pytest.approx(far * 0.85 ** 2)
    cam.zoom(1, (1.0, 0.0))  # toward the right edge: the target moves right
    right, _ = cam.basis()
    assert np.dot(cam.target - before, right) > 0
    cam.orbit(0, 10_000)
    assert cam.pitch == 89.0
    m = cam.view_proj(1.5)
    clip = m @ np.append(cam.target, 1)
    assert abs(clip[0] / clip[3]) < 1 and abs(clip[1] / clip[3]) < 1  # what it looks at is on screen


# ---- drawing, on the real GPU path (Direct3D 11 on Windows; not under Qt's offscreen platform)

RENDER = r"""
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from convertall import viewer
app = QApplication([])
model = viewer.flatten(viewer.load_scene(sys.argv[1], "glb"), "glb")
view = viewer.ModelView({"bg": "#102030", "text": "#ffffff", "accent": "#ff00ff"})
view.setAttribute(Qt.WA_DontShowOnScreen)  # "shown", as in the app, but never on the screen
view.resize(320, 200)
view.show()
app.processEvents()
view.set_model(model)
plain = view.grabFramebuffer()
view.set_wireframe(True)
wired = view.grabFramebuffer()
bg = (0x10, 0x20, 0x30)
def rgb(img, x, y):
    c = img.pixelColor(x, y)
    return c.red(), c.green(), c.blue()
model_px = sum(rgb(plain, x, y) != bg for x in range(0, 320, 4) for y in range(0, 200, 4))
magenta = sum(rgb(wired, x, y)[0] > 150 and rgb(wired, x, y)[1] < 100 for x in range(320) for y in range(200))
print(plain.width(), plain.height(), rgb(plain, 1, 1) == bg, model_px, magenta)
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Direct3D")
def test_draws_the_model(samples):
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    out = subprocess.run([sys.executable, "-c", RENDER, str(samples("glb"))], capture_output=True, text=True,
                         env=env, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    w, h, corner_is_background, model_px, wire_px = out.stdout.split()
    assert (w, h, corner_is_background) == ("320", "200", "True")
    assert int(model_px) > 300  # the box and the ball cover a good part of the view
    assert int(wire_px) > 100   # wireframe lines in the accent color


# ---- animation

def _moving_scene():
    """A box sliding along x for 2 s, and a skinned box whose top a bone lifts while a blend shape
    pushes it sideways."""
    from meshport import Animation, Channel, Morph, Skin
    times = np.array([0.0, 1.0, 2.0])
    slider = Node("slider", mesh=cube("slide"))
    bone = Node("bone")
    mesh = cube("bent")
    mesh.targets = [Morph("Side", np.tile([0.5, 0, 0], (8, 1)))]
    top = mesh.positions[:, 1] > 0
    body = Node("body", mesh=mesh)
    body.skin = Skin([Node("root"), bone], np.array([np.eye(4), np.eye(4)]), np.where(top, 1, 0)[:, None],
                     np.ones((8, 1)))
    scene = Scene([slider, bone, body.skin.joints[0], body])
    scene.animations = [Animation("Move", [
        Channel(slider, "translation", times, np.array([[0, 0, 0], [3, 0, 0], [0, 0, 0.0]])),
        Channel(bone, "translation", times, np.array([[0, 0, 0], [0, 2, 0], [0, 1, 0.0]])),
        Channel(body, "weights", times, np.array([[0.0], [1.0], [0.5]]))])]
    return scene


def _distinct(p):
    return np.unique(np.round(np.asarray(p, float), 5), axis=0)


def test_animated_models_pose_as_meshport_does():
    scene = _moving_scene()
    model = viewer.flatten(scene)
    motion = model.motion
    assert motion is not None and (motion.start, motion.end) == (0.0, 2.0)
    assert {p.node.name for p in motion.moving} == {"slider", "body"}
    posed = model.vertices.copy()
    for t in (0.0, 0.4, 1.0, 1.7, 2.0):
        motion.pose(t, posed)
        expect = np.concatenate([p for _, p in scene.posed_points(t)])
        assert np.allclose(_distinct(posed["pos"]), _distinct(expect), atol=1e-4), t
        n = posed["normal"].astype(float)
        assert np.allclose(np.linalg.norm(n, axis=1), 1, atol=1e-4)
    assert model.hi[0] >= 4 - 1e-6 and model.hi[1] >= 3 - 1e-6  # framed for the whole animation
    assert "2 s animation" in model.stats()


def test_still_models_have_no_motion():
    scene = Scene([Node("box", mesh=cube())])
    assert viewer.flatten(scene).motion is None
    from meshport import Animation, Channel
    other = Node("empty")  # animated, but nothing that shows moves
    scene.roots.append(other)
    scene.animations = [Animation("A", [Channel(other, "translation", np.array([0, 1.0]), np.zeros((2, 3)))])]
    assert viewer.flatten(scene).motion is None


def test_takes_that_move_different_things_play_together():
    from meshport import Animation, Channel
    a, b = Node("a", mesh=cube()), Node("b", mesh=cube())
    times = np.array([0.0, 1.0])
    move = np.array([[0, 0, 0], [1, 0, 0.0]])
    scene = Scene([a, b], [Animation("A", [Channel(a, "translation", times, move)]),
                           Animation("B", [Channel(b, "translation", times * 3, move)])])
    motion = viewer.flatten(scene).motion
    assert motion.names == ["All together", "A", "B"] and motion.name == "All together" and motion.end == 3.0
    motion.select("A")
    assert motion.end == 1.0 and [p.node.name for p in motion.moving] == ["a"]
    scene.animations[1].channels[0].node = a  # both move the same thing: they're alternatives
    assert viewer.flatten(scene).motion.name == "A"


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_viewer_window_plays_and_scrubs():
    app = _app()
    model = viewer.flatten(_moving_scene())
    win = viewer.ViewerWindow({"bg": "#202020"}, Path("moving.glb"), "glb", model)
    try:
        player = win.player
        assert not win.controls.isHidden() and player.playing and win.play.text() == "Pause"
        assert win.take.isHidden()  # one take: nothing to choose
        win.play.setChecked(False)
        assert not player.playing and win.play.text() == "Play"
        win.timeline.setValue(win.STEPS // 2)  # half way: 1 s, the slider furthest along
        assert win.time == pytest.approx(1.0) and win.clock.text() == "1.00 / 2.00 s"
        slide = next(p for p in player.motion.moving if p.node.name == "slider")
        assert player.posed["pos"][slide.start:slide.start + slide.count, 0].max() == pytest.approx(4)
        assert win.panel.view._pose is player.posed
        player.seek(5.0)
        assert win.time == 2.0 and win.timeline.value() == win.STEPS
        win.play.setChecked(True)  # at the end: plays from the start again
        assert win.time == 0.0 and player.playing
        win.keyPressEvent(_key(" "))  # the space bar pauses
        assert not player.playing and not win.play.isChecked()
    finally:
        win.close()
        app.processEvents()
    still = viewer.ViewerWindow({"bg": "#202020"}, Path("box.glb"), "glb", viewer.flatten(Scene([Node("b", mesh=cube())])))
    assert still.controls.isHidden() and still.player is None
    still.close()


def _key(text: str):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QEvent.KeyPress, {" ": 0x20}[text], viewer.Qt.NoModifier, text)


def test_the_preview_plays_by_itself_and_a_window_plays_its_own_copy():
    app = _app()
    model = viewer.flatten(_moving_scene())
    panel = viewer.ViewerPanel({"bg": "#202020"})
    panel.show_model(model)
    try:
        assert panel.player is not None and panel.player.playing
        win = viewer.ViewerWindow({"bg": "#202020"}, Path("moving.glb"), "glb", model)
        assert win.player is not panel.player and win.player.motion is not panel.player.motion
        win.player.seek(1.5)
        assert panel.player.time != 1.5  # each plays its own moment, and its own take
        win.close()
        panel.clear()
        assert panel.player is None
        panel.show_model(viewer.flatten(Scene([Node("b", mesh=cube())])))
        assert panel.player is None  # still models aren't played
    finally:
        panel.deleteLater()
        app.processEvents()


def test_heavy_models_play_fewer_frames_and_hidden_ones_none():
    app = _app()
    panel = viewer.ViewerPanel({"bg": "#202020"})
    panel.show_model(viewer.flatten(_moving_scene()))
    player = panel.player
    try:
        posed = []
        player.motion.pose = lambda t, v: posed.append(t)  # nothing to see: the panel isn't shown
        player._tick()
        assert posed == []
        panel.view.isVisible = lambda: True
        slow = player.seek

        def heavy(t):
            import time as clock
            clock.sleep(0.04)  # a pose that takes 40 ms
            slow(t)
        player.seek = heavy
        player._tick()
        assert player.timer.interval() >= 90  # posing gets at most 40% of each frame
        player.seek = slow
        player._tick()
        assert player.timer.interval() == viewer.FRAME_MS
    finally:
        panel.clear()
        panel.deleteLater()
        app.processEvents()


def test_normals_turn_as_blend_shapes_bend_the_surface():
    from meshport import Animation, Channel, Morph
    plane = Mesh("plane", np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1.0]]), np.array([4]), np.array([0, 3, 2, 1]))
    plane.normals = np.tile([0, 1.0, 0], (4, 1))
    plane.targets = [Morph("Tilt", np.array([[0, 0, 0], [0, 1, 0], [0, 1, 0], [0, 0, 0.0]]))]  # x = 1 rises by 1
    node = Node("plane", mesh=plane)
    scene = Scene([node], [Animation("A", [Channel(node, "weights", np.array([0, 1.0]), np.array([[0.0], [1.0]]))])])
    model = viewer.flatten(scene)
    posed = model.vertices.copy()
    model.motion.pose(1.0, posed)  # fully tilted, 45 degrees about z
    assert np.allclose(posed["normal"], np.tile([-np.sqrt(0.5), np.sqrt(0.5), 0], (len(posed), 1)), atol=1e-5)
    model.motion.pose(0.0, posed)
    assert np.allclose(posed["normal"], np.tile([0, 1, 0], (len(posed), 1)), atol=1e-6)
    plane.targets[0].normals = np.tile([0, 0, 1.0], (4, 1))  # a target's own normal offsets are used as they are
    model = viewer.flatten(scene)
    posed = model.vertices.copy()
    model.motion.pose(1.0, posed)
    assert np.allclose(posed["normal"], np.tile([0, np.sqrt(0.5), np.sqrt(0.5)], (len(posed), 1)), atol=1e-5)


RENDER_MOVING = r"""
import sys
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from convertall import viewer
import meshport
app = QApplication([])
model = viewer.flatten(meshport.load(sys.argv[1]), "glb")
view = viewer.ModelView({"bg": "#102030", "text": "#ffffff", "accent": "#ff00ff"})
view.setAttribute(Qt.WA_DontShowOnScreen)
view.resize(320, 200)
view.show()
app.processEvents()
view.set_model(model)
posed = model.vertices.copy()
def drawn(t):
    model.motion.pose(t, posed)
    view.set_pose(posed)
    img = view.grabFramebuffer()
    return [x for x in range(0, 320, 2) if img.pixelColor(x, 100).lightness() > 90]  # the box, not the grid
start, end = drawn(0.0), drawn(1.0)
print(min(start), max(start), min(end), max(end))
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Direct3D")
def test_draws_the_model_where_its_animation_puts_it(tmp_path):
    import meshport
    from meshport import Animation, Channel
    box = Node("box", mesh=cube())
    scene = Scene([box], [Animation("Slide", [Channel(box, "translation", np.array([0, 1.0]),
                                                      np.array([[-3, 0, 0], [3, 0, 0.0]]))])])
    meshport.save(scene, tmp_path / "slide.glb")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    out = subprocess.run([sys.executable, "-c", RENDER_MOVING, str(tmp_path / "slide.glb")], capture_output=True,
                         text=True, env=env, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    _, right0, left1, _ = map(int, out.stdout.split())
    assert right0 < 160 < left1  # left of the middle at the start, right of it at the end
