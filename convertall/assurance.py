"""Check a conversion: measure the file before and the result after (pages, frames, parts, length,
records...) and compare what should match. Only measured facts are reported, never a score; a
difference the route's notes explain is expected, any other is a warning. Nothing here changes a file.

  facts = inspect(path, fmt)     # {"pages": 12} / {"width": 800, ...}; None: not something we measure
  checks = verify(before, after, losses, found)
"""

from __future__ import annotations

import functools
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import engines
from .formats import category
from .losses import FEATURES, Loss, typical

READ_LIMIT = 200 * 2**20     # bigger files aren't read again just to check them
PIXEL_LIMIT = 64_000_000     # nor are bigger pictures decoded to look for transparency
DATA_LIMIT = 50 * 2**20

MESHPORT_READ = {"glb", "gltf", "fbx", "3ds", "usd", "usdz", "abc", "blend"}
TRIMESH_READ = {"stl", "obj", "ply", "off", "3mf", "dae"}
PAGED = {"pdf", "xps", "oxps"}
WORDS_IN = {"pdf", "docx", "odt", "rtf", "txt", "md", "html"}  # documents bookport counts words in too
NATIVE_ARCHIVES = {"zip", "tar", "tar.gz", "tar.bz2", "tar.xz", "7z"} | {"cbz", "cbt", "cb7"}


class Unreadable(Exception):
    """The result doesn't open the way a program reading that format would open it."""


# ---------------------------------------------------------------- measuring

def inspect(path: Path, fmt: str, words: bool = False) -> dict | None:
    """What can be measured of path as fmt; None when it isn't a kind of file measured here, or it
    is too big to read again quickly. Raises Unreadable when it should open and doesn't.
    words: also count the words of a document an ebook became (PDF, Word, text...)."""
    path = Path(path)
    if path.is_dir():
        return _folder(path, fmt)
    if path.stat().st_size > READ_LIMIT:
        return None
    reader = _reader(fmt)
    readers = [r for r in (reader, _book if words and fmt in WORDS_IN and reader is not _book else None) if r]
    if not readers:
        return None
    facts: dict = {}
    try:
        for r in readers:
            facts.update(r(path, fmt))
    except Unreadable:
        raise
    except Exception as exc:
        raise Unreadable(str(exc) or type(exc).__name__) from exc
    return facts


def measure(path: Path, fmt: str) -> dict | None:
    """inspect(), for a source: a file that won't open is the converter's business, not a check's."""
    try:
        return inspect(path, fmt)
    except Unreadable:
        return None


def _reader(fmt: str):
    from .converters import images
    cat = category(fmt)
    if fmt in images.READ or fmt in ("heic",):
        return _image
    if fmt in PAGED:
        return _pages
    if cat in ("Audio", "Video"):
        return _media if _ffprobe() else None
    if fmt in MESHPORT_READ:
        return _meshport
    if fmt in TRIMESH_READ:
        return _trimesh
    from .converters import data
    if fmt in data.TREE | data.TABLE:
        return _data
    if cat == "Subtitle":
        return _subtitles
    if fmt in ("ttf", "otf", "woff", "woff2"):
        return _font
    if fmt == "ttc":
        return _collection
    if fmt in NATIVE_ARCHIVES:
        return _archive
    if fmt == "dcm":
        return _dicom
    if cat == "Map":
        return _map
    if fmt in ("vcf", "ics"):
        return _contacts
    from .converters import ebooks
    if fmt in ebooks.BOOKS:
        return _book
    return None


def _image(path: Path, fmt: str) -> dict:
    from PIL import Image

    from .converters import images
    if fmt == "heic":
        images.enable_heif()
    with Image.open(path) as img:
        frames = 1 if fmt == "psd" else getattr(img, "n_frames", 1)
        facts = {"width": img.width, "height": img.height, "frames": frames, "photo_info": bool(img.getexif())}
        if frames > 1 and fmt in ("gif", "webp", "png", "avif"):
            total = 0
            for i in range(frames):
                img.seek(i)
                total += img.info.get("duration", 0) or 0
            facts["duration"] = round(total / 1000, 3)
            img.seek(0)
        # transparency is looked for where the reader shows it (Pillow reads cursors without it)
        if fmt != "cur" and img.width * img.height <= PIXEL_LIMIT:
            img.load()  # some readers (ICNS) say RGBA until the picture is decoded, then RGB
            has = img.mode in ("RGBA", "LA", "PA", "La") or "transparency" in img.info
            # the alpha channel itself when there is one; a copy of the whole picture only for palettes
            alpha = img.getchannel("A") if img.mode in ("RGBA", "LA", "La") else has and img.convert("RGBA").getchannel("A")
            facts["transparency"] = bool(has and alpha.getextrema()[0] < 255)
        img.load()
    return facts


def _pages(path: Path, fmt: str) -> dict:
    import pymupdf
    with pymupdf.open(path) as doc:
        if not doc.page_count:
            raise Unreadable("it has no pages")
        return {"pages": doc.page_count}


def _ffprobe() -> str | None:
    ff = engines.find("ffmpeg")
    probe = ff and Path(ff).with_name("ffprobe.exe" if ff.lower().endswith(".exe") else "ffprobe")
    return str(probe) if probe and probe.exists() else None


def _media(path: Path, fmt: str) -> dict:
    out = subprocess.run([_ffprobe(), "-v", "error", "-protocol_whitelist", "file", "-show_entries",
                          "format=duration:stream=codec_type,width,height,disposition", "-of", "json", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                         timeout=60, creationflags=engines.NO_WINDOW, stdin=subprocess.DEVNULL)
    if out.returncode:
        raise Unreadable(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "FFmpeg can't read it")
    info = json.loads(out.stdout or "{}")
    # cover pictures in audio files are "video" streams too: they're attached pictures, not video
    streams = [s for s in info.get("streams", []) if not (s.get("disposition") or {}).get("attached_pic")]
    kinds = [s.get("codec_type") for s in streams]
    facts = {"audio_tracks": kinds.count("audio"), "video": kinds.count("video") > 0,
             "subtitle_tracks": kinds.count("subtitle")}
    try:
        facts["duration"] = round(float(info["format"]["duration"]), 3)
    except (KeyError, TypeError, ValueError):
        pass
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("width")), None)
    if video:
        facts["width"], facts["height"] = int(video["width"]), int(video["height"])
    want = "video" if category(fmt) == "Video" else "audio"
    if want == "audio" and not facts["audio_tracks"] or want == "video" and not facts["video"]:
        raise Unreadable(f"it has no {want} stream")
    return facts


def _meshport(path: Path, fmt: str) -> dict:
    import meshport
    import numpy as np
    scene = meshport.load(path, fmt)
    parts = triangles = 0
    rig = False
    for node, _ in scene.walk():
        mesh = getattr(node, "mesh", None)
        if mesh is None:
            continue
        parts += 1
        triangles += int(np.maximum(np.asarray(mesh.face_sizes) - 2, 0).sum())
        rig = rig or getattr(node, "skin", None) is not None or bool(mesh.targets)
    if not parts:
        raise Unreadable("it has no 3D geometry")
    facts = {"parts": parts, "triangles": triangles, "animation": bool(scene.animations), "rig": rig}
    bounds = (scene.deformed() if rig else scene).bounds()  # a rig's size is where its skeleton holds it
    if bounds is not None:
        facts["size"] = round(float(np.linalg.norm(np.subtract(bounds[1], bounds[0]))), 6)
    return facts


def _trimesh(path: Path, fmt: str) -> dict:
    import numpy as np
    import trimesh
    scene = trimesh.load_scene(str(path))
    nodes = scene.graph.nodes_geometry
    triangles = sum(len(getattr(scene.geometry[scene.graph[n][1]], "faces", ())) for n in nodes)
    if not triangles:
        raise Unreadable("it has no 3D geometry")
    parts = len(nodes)
    if fmt == "obj":  # trimesh joins an OBJ's objects into one as it reads them: count them in the text
        with path.open("rb") as f:
            names = {line.split(maxsplit=1)[-1].strip() for line in f if line.startswith((b"o ", b"g "))}
        parts = max(len(names), 1)
    facts = {"parts": parts, "triangles": triangles}
    if scene.bounds is not None:
        facts["size"] = round(float(np.linalg.norm(scene.bounds[1] - scene.bounds[0])), 6)
    return facts


def _data(path: Path, fmt: str) -> dict | None:
    if path.stat().st_size > DATA_LIMIT:
        return None
    from .converters import data as data_mod
    value = data_mod.load(path, fmt)
    tables = value if isinstance(value, dict) and value and all(isinstance(v, list) for v in value.values()) \
        else {"": value} if isinstance(value, list) else None
    if tables is None:
        return {"nested": _nested(value, top=True)}
    first = next(iter(tables.values()))
    return {"tables": len(tables), "records": len(first),
            "nested": any(_nested(r) for rows in tables.values() for r in rows[:1000])}


def _nested(value, top: bool = False) -> bool:
    """Whether a record (or, at the top, a document) holds lists or objects inside it."""
    if isinstance(value, dict):
        inner = value.values()
        return any(isinstance(v, (dict, list)) and (not top or _nested(v)) for v in inner)
    if isinstance(value, list):
        return any(isinstance(v, (dict, list)) for v in value)
    return False


def _subtitles(path: Path, fmt: str) -> dict:
    from .converters import subtitles
    # SAMI and others clear the screen with an empty cue: only cues that show text count
    return {"cues": len([e for e in subtitles._load(path, fmt) if not e.is_comment and e.plaintext.strip()])}


def _font(path: Path, fmt: str) -> dict:
    from fontTools.ttLib import TTFont
    with TTFont(path, lazy=True) as font:
        return {"glyphs": len(font.getGlyphOrder())}


def _collection(path: Path, fmt: str) -> dict:
    from fontTools.ttLib import TTCollection
    with TTCollection(path, lazy=True) as ttc:
        return {"fonts": len(ttc.fonts)}


def _archive(path: Path, fmt: str) -> dict:
    if fmt in ("zip", "cbz"):
        import zipfile
        with zipfile.ZipFile(path) as z:
            names = [i.filename for i in z.infolist() if not i.is_dir()]
    elif fmt in ("7z", "cb7"):
        import py7zr
        with py7zr.SevenZipFile(path) as z:
            names = [i.filename for i in z.list() if not i.is_directory]
    else:
        import tarfile
        with tarfile.open(path) as t:
            names = [m.name for m in t.getmembers() if m.isfile()]
    if fmt.startswith("cb"):
        from .converters.comics import PAGE_EXT
        hidden = lambda n: any(part.startswith((".", "__MACOSX")) for part in Path(n).parts)  # as comics.py
        return {"pages": sum(Path(n).suffix.lower() in PAGE_EXT and not hidden(n) for n in names)}
    return {"files": len(names)}


def _book(path: Path, fmt: str) -> dict:
    import bookport
    try:
        book = bookport.read(path, fmt)
    except bookport.DRMError:
        return {}  # protected: there's nothing to compare, and the conversion says why
    except bookport.BookportError as exc:
        raise Unreadable(str(exc)) from None
    return {"words": book.word_count()}


def _dicom(path: Path, fmt: str) -> dict:
    import pydicom
    ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    return {"frames": int(ds.get("NumberOfFrames", 1) or 1)}


def _map(path: Path, fmt: str) -> dict:
    from .converters import maps
    m = maps.read_map(path, fmt)
    return {"places": len(m.points), "tracks": len(m.lines)}


def _contacts(path: Path, fmt: str) -> dict:
    from .converters import contacts
    from .textfile import read_text
    text = read_text(path)
    return {"records": len(contacts.read_vcards(text) if fmt == "vcf" else contacts.read_events(text))}


def _folder(path: Path, fmt: str) -> dict | None:
    """A result that is a folder: pages or frames as images, fonts, or one model with its side files."""
    files = [p for p in path.rglob("*") if p.is_file()]
    if not files:
        raise Unreadable("the folder is empty")
    own = [p for p in files if p.name.lower().endswith("." + fmt)]
    if fmt == "folder":
        return {"files": len(files)}
    if len(own) == 1:
        return inspect(own[0], fmt)
    if not own:
        raise Unreadable(f"the folder holds no {fmt.upper()} files")
    if category(fmt) == "Font":
        return {"fonts": len(own)}
    first = inspect(own[0], fmt) or {}
    return {"pages": len(own), "frames": len(own),
            **{k: v for k, v in first.items() if k in ("width", "height", "transparency")}}


# ---------------------------------------------------------------- what a file has

# measured fact -> the feature it shows (losses.py) and the test for "has it"
SHOWS = {"transparency": ("transparency", bool), "frames": ("frames", lambda n: n > 1),
         "pages": ("pages", lambda n: n > 1), "parts": ("parts", lambda n: n > 1),
         "animation": ("animation", bool), "rig": ("rig", bool), "tables": ("sheets", lambda n: n > 1),
         "nested": ("nesting", bool), "audio_tracks": ("tracks", lambda n: n > 1),
         "subtitle_tracks": ("subtitle_tracks", lambda n: n > 1), "photo_info": ("photo_info", bool)}


def features(facts: dict | None, fmt: str) -> frozenset[str]:
    """The features this file has: measured where they were, the format's usual ones otherwise."""
    have = set(typical(fmt))
    for fact, (feature, test) in SHOWS.items():
        if facts and fact in facts and FEATURES[feature].holds(fmt):
            (have.add if test(facts[fact]) else have.discard)(feature)
    return frozenset(have)


# ---------------------------------------------------------------- comparing

NAMES = {"pages": "Pages", "frames": "Frames", "duration": "Length", "width": "Width", "height": "Height",
         "transparency": "Transparency", "parts": "Parts", "triangles": "Triangles", "size": "Size",
         "animation": "Animation", "rig": "Skeleton or blend shapes", "tables": "Tables", "records": "Records",
         "cues": "Subtitles", "glyphs": "Glyphs", "fonts": "Fonts", "files": "Files", "places": "Places",
         "tracks": "Tracks", "audio_tracks": "Sound tracks", "words": "Words"}
# facts that should come through a conversion unchanged, and how close counts as the same
SAME = {"pages": 0, "frames": 0, "width": 0, "height": 0, "parts": 0, "triangles": 0, "tables": 0,
        "records": 0, "cues": 0, "glyphs": 0, "fonts": 0, "files": 0, "places": 0, "tracks": 0,
        "audio_tracks": 0, "words": 0}
KEPT = ("transparency", "animation", "rig")
GROWS = ("parts",)  # more is no loss: a part with two materials can become two  # a file that had these should still have them


@dataclass
class Check:
    name: str
    before: object
    after: object
    state: str = "ok"   # ok, expected (differs as the notes say), warning (differs, unexplained), error
    why: str = ""

    def text(self) -> str:
        if self.state == "error":
            return f"{self.name}: {self.why}"
        if self.before is None:
            return f"{self.name}: {show(self.after)}"
        if self.before == self.after:
            return f"{self.name}: {show(self.before)}"
        return f"{self.name}: {show(self.before)} → {show(self.after)}"


def show(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.4g}" if abs(v) < 1000 else f"{v:.0f}"  # 6.633, 12.35, 4096: never 1.2e+04
    if isinstance(v, int) and abs(v) >= 10_000:
        return f"{v:,}"  # 30,682 words, 660,000 triangles; picture sizes (1920) stay as they are
    return str(v)


def _close(key: str, a, b) -> bool:
    if key == "duration":
        return abs(a - b) <= max(0.5, 0.02 * a)
    if key == "size":
        return abs(a - b) <= 1e-3 * max(abs(a), abs(b), 1e-9)
    if key in ("width", "height"):
        return abs(a - b) <= 1  # video encoders round to even sizes
    if key == "words":  # formats split words a little differently (a dash, a note mark, a heading)
        return abs(a - b) <= max(20, 0.03 * a)
    return a == b


def verify(before: dict | None, after: dict | None, lost: list[Loss], found: list[str] = (),
           video: bool = False) -> list[Check]:
    """Compare a source's facts with its result's. lost: what the route said it would lose; found:
    what the converters reported while running (those explain any count they touch)."""
    if not before or not after:
        return []
    explains: dict[str, str] = {}
    for n in lost:
        for key in n.affects:
            explains.setdefault(key, n.text)
    checks: list[Check] = []
    for key in [k for k in NAMES if k in before and k in after]:
        a, b = before[key], after[key]
        if key in KEPT:
            if a and not b:
                why = explains.get(key)
                checks.append(Check(NAMES[key], a, b, "expected" if why else "warning", why or ""))
            continue
        if key not in SAME and key not in ("duration", "size"):
            continue
        if (a == b if key in ("width", "height") and not video else _close(key, a, b)) or key in GROWS and b > a:
            checks.append(Check(NAMES[key], a, b))
            continue
        why = explains.get(key) or (found[0] if found and key in ("files", "pages") else "")
        checks.append(Check(NAMES[key], a, b, "expected" if why else "warning", why))
    return checks


# ---------------------------------------------------------------- the report

@dataclass
class Report:
    source: str = ""
    source_format: str = ""
    detected: str = "extension"      # or "content": the extension said something else
    target: str = ""
    output: str = ""
    steps: list[dict] = field(default_factory=list)   # {"from", "to", "tool"}
    settings: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    seconds: float = 0.0
    started: float = field(default_factory=time.perf_counter, repr=False)

    @property
    def warnings(self) -> list[str]:
        return [c.text() for c in self.checks if c.state in ("warning", "error")]

    @property
    def route(self) -> str:
        return " → ".join([self.source_format.upper()] + [s["to"].upper() for s in self.steps])

    def summary(self) -> str:
        """One short line for a status bar: the first thing that didn't match, else the first note."""
        if self.warnings:
            return "Check: " + self.warnings[0]
        return self.notes[0] if self.notes else ""

    def lines(self) -> list[str]:
        """The whole report as text lines (tooltips, the command line)."""
        tools = ", ".join(dict.fromkeys(s["tool"] for s in self.steps if s.get("tool")))
        out = [f"{self.route}" + (f" via {tools}" if tools else "")]
        out += self.notes
        same = [c for c in self.checks if c.state == "ok" and c.before == c.after]
        if same:
            out.append("Checked, the same: " + ", ".join(f"{c.name.lower()} {show(c.after)}" for c in same))
        out += [("Didn't match: " if c.state in ("warning", "error") else
                 "Changed as noted: " if c.state == "expected" else "Changed: ") + c.text()
                for c in self.checks if c not in same]
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("started")
        d["route"] = self.route
        d["warnings"] = self.warnings
        return d


# which library does a built-in step's work (an engine-backed step names its engine)
TOOLS = {
    "pillow_convert": "Pillow", "trace_to_svg": "vtracer", "pages_to_images": "PyMuPDF", "svg_to_image": "PyMuPDF",
    "to_pdf": "PyMuPDF", "to_text": "PyMuPDF", "html_to_pdf": "PyMuPDF", "illustrator_to_pdf": "PyMuPDF",
    "comic_to_pdf": "PyMuPDF", "folder_to_pdf": "PyMuPDF", "pdf_to_comic": "PyMuPDF", "cad_to_stl": "gmsh",
    "dxf_render": "ezdxf", "vectors_to_dxf": "ezdxf", "font_convert": "fontTools", "split_collection": "fontTools",
    "pysubs2_convert": "pysubs2", "srt_vtt": "ConvertAll", "dicom_to_image": "pydicom", "dicom_to_json": "pydicom",
    "mesh_convert": "trimesh", "meshport_convert": "meshport", "meshport_to_files": "meshport",
    "markdown_to_html": "Markdown", "docx_to_html": "mammoth", "ipynb_to_html": "Markdown",
    "book_convert": "bookport", "comic_to_book": "bookport",
}
DISTRIBUTIONS = {"Pillow": "pillow", "PyMuPDF": "pymupdf", "Markdown": "markdown"}


@functools.cache
def _version(name: str) -> str:
    import importlib
    from importlib import metadata
    try:  # a package's own __version__ first: an editable install's metadata can lag behind
        own = getattr(importlib.import_module(name), "__version__", None) if name in ("meshport", "packport", "bookport") else None
        if own:
            return str(own)
        return metadata.version(DISTRIBUTIONS.get(name, name))
    except metadata.PackageNotFoundError:
        return ""


def tool(edge) -> str:
    """Who did a step: "FFmpeg", "Pillow 11.0.0", "ConvertAll"."""
    if edge.engine:
        return engines.ENGINES[edge.engine].name
    name = TOOLS.get(edge.func.__name__, "ConvertAll")
    if name == "ConvertAll":
        return name
    v = _version(name)
    return f"{name} {v}" if v else name
