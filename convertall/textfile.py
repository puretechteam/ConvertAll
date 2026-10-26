"""Reading text files whose encoding nobody wrote down."""

from pathlib import Path


def decode(data: bytes) -> str:
    """UTF-8 (with or without a BOM) or BOM-marked UTF-16, else Windows-1252, which is what older
    files saved on Windows (subtitles, CSV exports, web pages) usually are. Never fails."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def read_text(path: Path) -> str:
    return decode(Path(path).read_bytes())
