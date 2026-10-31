"""What a conversion can't keep, said plainly, and how much that weighs when choosing a route.

A *feature* is something a file can have that a format may not hold: transparency, several
parts in a 3D model, nested data, styled subtitles. Each step of a route keeps the features its
target can hold and loses the rest, with the feature's own sentence ("JPG has no transparency:
see-through areas become white"). A converter can also say what it leaves out itself, even when
the target could hold it (its notes, see registry.converter): those lines name the features
they take away, or none when they always apply.

Which features a file has comes from measuring it when it was (assurance.inspect); otherwise a
format's usual files are assumed to have its typical ones (a GLB has parts; a PNG isn't assumed
to be animated). A feature lost once isn't lost again further down the route.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .formats import category

MINOR, MAJOR = 2, 4  # added to a route's cost: any loss outweighs one more step


@dataclass(frozen=True)
class Loss:
    text: str
    drops: frozenset[str] = frozenset()  # features this takes away; empty: it always applies
    weight: int = MINOR
    affects: tuple[str, ...] = ()  # measured facts it changes (a check that differs for this reason is fine)


def loss(text: str, *drops: str, weight: int = MINOR, affects: tuple[str, ...] = ()) -> Loss:
    return Loss(text, frozenset(drops), weight, affects)


FormatTest = Callable[[str], bool]


@dataclass(frozen=True)
class Feature:
    text: Callable[[str], str]   # the line for a target (its extension) that can't hold it
    holds: FormatTest            # formats that keep it
    typical: FormatTest          # formats whose files usually have it
    weight: int = MINOR
    affects: tuple[str, ...] = ()


def _in(*groups: Iterable[str]) -> FormatTest:
    members = frozenset().union(*map(frozenset, groups))
    return lambda f: f in members


def _kinds(*kinds: str, also: Iterable[str] = (), but: Iterable[str] = ()) -> FormatTest:
    also, but = frozenset(also), frozenset(but)
    return lambda f: f not in but and (f in also or category(f) in kinds)


def _say(template: str, **special: str) -> Callable[[str], str]:
    return lambda dst: special.get(dst, template).format(DST=dst.upper())


RAW = {"dng", "cr2", "cr3", "nef", "arw", "orf", "rw2", "raf"}
# raster images: everything in the Image kind except vector drawings
VECTOR_IMAGES = {"svg", "eps", "ai", "emf", "wmf"}
RASTER = _kinds("Image", but=VECTOR_IMAGES)
PAGED = {"pdf", "xps", "oxps", "ps", "djvu", "tiff"}
MESH_PARTS = {"glb", "gltf", "obj", "3mf", "fbx", "3ds", "usd", "usdz", "abc", "blend"}
ANIMATED_3D = {"glb", "gltf", "fbx", "usd", "usdz", "abc", "blend"}
LOSSLESS_AUDIO = {"wav", "flac", "aiff", "wv", "caf", "au", "ape", "dsf", "dff"}
LOSSLESS_IMAGES = {"png", "bmp", "tiff", "tga", "qoi", "ppm", "psd", "pcx", "sgi", "xpm", "xbm", "ico", "icns",
                   "cur", "dds", "jp2", "gif", "exr", "hdr", "xcf"} | RAW
TREE = {"json", "jsonl", "yaml", "toml", "xml", "plist"}
WORKBOOKS = {"xlsx", "xls", "ods", "xlsm", "xlsb", "numbers"}

FEATURES: dict[str, Feature] = {
    "transparency": Feature(
        lambda d: f"{d.upper()} has no transparency: see-through areas "
                  + ("become white" if RASTER(d) or d in ("pdf", "eps") else "are filled in"),
        _in({"png", "webp", "gif", "tiff", "ico", "icns", "cur", "tga", "avif", "heic", "qoi", "dds", "psd", "xpm",
             "jp2", "sgi", "svg", "jxl", "exr", "xcf"}),
        _in({"png", "webp", "gif", "ico", "icns", "cur", "psd", "xcf", "svg", "qoi", "dds", "tga", "xpm"}),
        affects=("transparency",)),
    "frames": Feature(
        _say("{DST} holds one picture: only the first frame is kept"),
        _kinds("Video", also={"gif", "webp", "png", "avif", "tiff", "pdf"}),
        _in({"gif"}), affects=("frames",)),
    "colors": Feature(
        _say("{DST} holds at most 256 colors: smooth shading may band",
             xbm="XBM holds only black and white", xpm="XPM holds at most 255 colors: smooth shading may band"),
        lambda f: f not in ("gif", "xbm", "xpm"),
        _kinds("Image", "Video", but={"gif", "xbm", "xpm", "ico", "cur"} | VECTOR_IMAGES)),
    "layers": Feature(
        lambda d: "Layers are flattened into one picture",
        lambda f: False, _in({"psd", "xcf"})),
    "hdr": Feature(
        _say("{DST} holds normal brightness only: very bright and very dark detail is clipped"),
        _in({"exr", "hdr", "jxl"}), _in({"exr", "hdr"})),
    "photo_info": Feature(
        _say("{DST} can't hold photo details: the camera, date and place are left out"),
        _in({"jpg", "png", "webp", "avif", "heic", "tiff", "jxl"} | RAW), _in({"jpg", "heic"} | RAW)),
    "lossless": Feature(
        _say("{DST} is lossy: a little quality is lost"),
        _in(LOSSLESS_IMAGES, LOSSLESS_AUDIO, VECTOR_IMAGES), _in(LOSSLESS_IMAGES - {"gif", "ico", "cur", "icns"},
                                                                LOSSLESS_AUDIO)),
    "vectors": Feature(
        lambda d: "The drawing becomes pixels: it won't stay sharp when enlarged",
        lambda f: not RASTER(f) and category(f) not in ("Comic", "Video"),
        _in(VECTOR_IMAGES, {"dxf", "odg", "vsdx", "vsd", "cdr", "ps"})),
    "text": Feature(
        lambda d: "Text becomes part of the picture: it can't be selected or searched",
        lambda f: not RASTER(f) and category(f) not in ("Comic", "Video"),
        _kinds("Document", "Spreadsheet", "Presentation", "Ebook", "Email", "Markup",
               also={"pdf", "xps", "oxps", "ps", "txt", "html", "md", "rtf"}, but={"djvu"})),
    "pages": Feature(
        _say("{DST} holds one page: only the first page is kept"),
        lambda f: not RASTER(f) and f not in ("eps", "svg") or f in ("tiff", "gif", "webp", "png", "avif"),
        _kinds("Document", "Presentation", "Ebook", "Comic", also=PAGED - {"tiff"}),
        affects=("pages",)),
    "formatting": Feature(
        lambda d: "Plain text: formatting and pictures are left out",
        lambda f: f not in ("txt", "csv", "tsv"),
        _kinds("Document", "Presentation", "Ebook", "Email", "Markup", also={"html", "md", "rtf", "ipynb", "pdf"},
               but={"txt"})),
    "attachments": Feature(
        lambda d: "Attachments are listed by name: the files themselves are left out",
        _in({"eml", "msg"}), _in({"eml", "msg"})),
    "parts": Feature(
        _say("{DST} holds one mesh: all parts are merged into one"),
        _in(MESH_PARTS, {"step", "iges", "brep"}), _in(MESH_PARTS, {"step", "iges", "brep", "dae"}),
        weight=MAJOR, affects=("parts",)),
    "materials": Feature(
        _say("{DST} holds shape only: colors and textures are left out"),
        _in({"glb", "gltf", "obj", "fbx", "3ds", "usd", "usdz", "blend", "dae", "3mf", "ply"}),
        _in({"glb", "gltf", "obj", "fbx", "3ds", "usd", "usdz", "blend", "dae"})),
    "animation": Feature(
        _say("{DST} holds no animation: the model is saved as it stands"),
        _in(ANIMATED_3D), _in({"abc"}), affects=("animation",)),
    "rig": Feature(
        _say("{DST} has no skeletons or blend shapes: the model is saved bent as it stands",
             abc="ABC has no skeletons or blend shapes: the motion is kept as moving points"),
        _in(ANIMATED_3D - {"abc"}), lambda f: False, affects=("rig",)),
    "surfaces": Feature(
        lambda d: "Exact curved surfaces become a mesh of triangles",
        _in({"step", "iges", "brep"}), _in({"step", "iges", "brep"})),
    "nesting": Feature(
        _say("{DST} is a flat table: nested values become columns (like a.b) or JSON text",
             ini="INI holds one level of sections: deeper values are flattened"),
        _in(TREE), _in(TREE - {"jsonl"})),
    "sheets": Feature(
        _say("{DST} holds one table: only the first sheet (or table) is kept"),
        lambda f: f not in ("csv", "tsv", "jsonl"), _in(WORKBOOKS - {"numbers"}, {"sqlite"}),
        affects=("tables", "records")),
    "formulas": Feature(
        lambda d: "Formulas become their last saved values",
        _in(WORKBOOKS), _in(WORKBOOKS)),
    "styling": Feature(
        _say("{DST} has no styling: fonts, colors and positions are left out"),
        _in({"ass", "ssa"}), _in({"ass", "ssa"})),
    "tracks": Feature(
        lambda d: "Only one sound track is kept",
        _kinds("Video"), lambda f: False, affects=("audio_tracks",)),
    "subtitle_tracks": Feature(
        lambda d: "Only the first subtitle track is taken",
        _kinds("Video"), lambda f: False, affects=("subtitle_tracks",)),
}
# a model that loses its animation loses its skeleton with it: one line says both
COVERS = {"animation": ("rig",)}


def typical(fmt: str) -> frozenset[str]:
    """The features a file of this format usually has, when it hasn't been measured."""
    return frozenset(k for k, f in FEATURES.items() if f.typical(fmt))


def step(edge_notes: list[Loss], dst: str, held: frozenset[str]) -> tuple[list[Loss], frozenset[str]]:
    """What one step to dst loses, given the features still held: (losses, features held after)."""
    out: list[Loss] = []
    for n in edge_notes:
        if not n.drops or n.drops & held:
            out.append(n)
        held -= n.drops
    gone = [k for k in FEATURES if k in held and not FEATURES[k].holds(dst)]
    covered = {c for k in gone for c in COVERS.get(k, ())}
    for k in gone:
        f = FEATURES[k]
        if k not in covered:
            out.append(Loss(f.text(dst), frozenset({k}), f.weight, f.affects))
    return out, held - set(gone)


def cost(losses: Iterable[Loss]) -> int:
    return sum(n.weight for n in losses)
