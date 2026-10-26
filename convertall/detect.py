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


# Signatures puremagic doesn't know (or confuses), checked first
_SIGNATURES = (
    (b"\xc5\xd0\xd3\xc6", "eps"), (b"AT&TFORM", "djvu"), (b"\x04\x22\x4d\x18", "lz4"), (b"\x1f\x9d", "z"),
    (b"070701", "cpio"), (b"070702", "cpio"), (b"070707", "cpio"), (b"xar!", "xar"), (b"KDMV", "vmdk"),
    (b"QFI\xfb", "qcow2"), (b"conectix", "vhd"), (b"vhdxfile", "vhdx"), (b"ITSF", "chm"),
    (b"<<< Oracle VM VirtualBox Disk Image >>>", "vdi"), (b"!<arch>\n", "ar"),
)
# Text formats recognised by what they start with (after any BOM and blank space)
_TEXT_STARTS = ((b"BEGIN:VCARD", "vcf"), (b"BEGIN:VCALENDAR", "ics"), (b"WEBVTT", "vtt"))


def _sniff(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            head = f.read(512)
        if head[128:132] == b"DICM":  # DICOM files often have no extension at all
            return "dcm"
        if head.startswith(b"SQLite format 3\x00"):  # .db files are often SQLite
            return "sqlite"
        if head.startswith(b"%!PS"):
            return "eps" if b"EPSF" in head.split(b"\n", 1)[0] else "ps"
        for magic, fmt in _SIGNATURES:
            if head.startswith(magic):
                return fmt
        text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
        for start, fmt in _TEXT_STARTS:
            if text.upper().startswith(start):
                return fmt
        if text.startswith(b"<"):  # <?xml or a bare root tag
            for tag, fmt in ((b"<gpx", "gpx"), (b"<kml", "kml"), (b"<tt ", "ttml"), (b"<tt>", "ttml")):
                if tag in head:
                    return fmt
    except OSError:
        return None
    try:
        import puremagic
        for match in puremagic.magic_file(str(path)):
            ext = normalize(_MAGIC_MAP.get(match.extension.lstrip("."), match.extension))
            if ext in FORMATS:
                return ext
    except Exception:  # noqa: BLE001, S110 - puremagic chokes on some files; then it's unknown
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
