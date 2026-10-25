"""Fonts via fontTools: TTF/OTF <-> WOFF/WOFF2."""

from pathlib import Path

from fontTools.ttLib import TTFont

from ..errors import ConversionError
from ..registry import converter

FLAVOR = {"ttf": None, "otf": None, "woff": "woff", "woff2": "woff2"}


@converter(inputs={"ttf", "otf", "woff", "woff2"}, outputs={"woff", "woff2"})
@converter(inputs={"woff", "woff2"}, outputs={"ttf", "otf"}, first_only=True)  # no ttf -> woff -> otf
def font_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    font = TTFont(src)
    if dst_fmt in ("ttf", "otf"):
        is_cff = font.sfntVersion == "OTTO"
        if is_cff != (dst_fmt == "otf"):
            right = "OTF" if is_cff else "TTF"
            raise ConversionError(f"This font has {'CFF' if is_cff else 'TrueType'} outlines; convert it to {right}")
    font.flavor = FLAVOR[dst_fmt]
    font.save(dst)
