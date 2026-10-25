"""Exotic images (camera RAW, GIMP, HDR, JPEG XL...) via ImageMagick."""

from pathlib import Path

from .. import engines
from ..registry import converter

RAW = {"dng", "cr2", "cr3", "nef", "arw", "orf", "rw2", "raf"}
EXOTIC_IN = RAW | {"xcf", "exr", "hdr", "jxl"}
EXOTIC_OUT = {"jxl", "exr", "hdr"}


@converter(inputs=EXOTIC_IN, outputs={"png", "jpg", "tiff"}, engine="imagemagick")
@converter(inputs={"psd"}, outputs={"png", "jpg", "tiff"}, engine="imagemagick", cost=2)
@converter(inputs={"png", "jpg", "tiff"}, outputs=EXOTIC_OUT, engine="imagemagick")
def magick_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    exe = engines.require("imagemagick")
    engines.run([exe, f"{src}[0]", "-auto-orient", str(dst)], timeout=600)
