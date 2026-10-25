"""Figure out what format a file is: extension first, magic bytes as fallback."""

from pathlib import Path

from .formats import ALIASES, FORMATS, MULTI_EXT

# puremagic extension -> our format key, for files with missing/unknown extensions
_MAGIC_MAP = {"jpeg": "jpg", "tif": "tiff", "htm": "html", "mpeg": "mpg", "tgz": "tar.gz"}

COMICS = {"cbz", "cbr", "cb7", "cbt"}
# Comic files are often renamed archives (a ".cbr" that is really a zip): trust the content
_COMIC_MAGIC = ((b"PK\x03\x04", "cbz"), (b"PK\x05\x06", "cbz"), (b"Rar!\x1a\x07", "cbr"),
                (b"7z\xbc\xaf\x27\x1c", "cb7"))


def normalize(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return ALIASES.get(ext, ext)


def detect(path: str | Path) -> str:
    path = Path(path)
    if path.is_dir():
        return "folder"
    name = path.name.lower()
    for multi in MULTI_EXT:
        if name.endswith("." + multi):
            return multi
    ext = normalize(path.suffix)
    if ext in COMICS:
        return _comic_kind(path) or ext
    if ext in FORMATS:
        return ext
    sniffed = _sniff(path)
    if sniffed:
        return sniffed
    return ext or "bin"


def _comic_kind(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            head = f.read(262)
    except OSError:
        return None
    for magic, kind in _COMIC_MAGIC:
        if head.startswith(magic):
            return kind
    return "cbt" if head[257:262] == b"ustar" else None


def _sniff(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            head = f.read(132)
        if head[128:132] == b"DICM":  # DICOM files often have no extension at all
            return "dcm"
        if head.startswith(b"SQLite format 3\x00"):  # .db files are often SQLite
            return "sqlite"
    except OSError:
        return None
    try:
        import puremagic
        for match in puremagic.magic_file(str(path)):
            ext = normalize(_MAGIC_MAP.get(match.extension.lstrip("."), match.extension))
            if ext in FORMATS:
                return ext
    except Exception:
        pass
    return None


def strip_ext(path: Path) -> str:
    """'photos.tar.gz' -> 'photos', 'song.mp3' -> 'song'."""
    name = path.name
    if path.is_dir():
        return name
    low = name.lower()
    for multi in MULTI_EXT:
        if low.endswith("." + multi):
            return name[: -len(multi) - 1]
    return path.stem or name
