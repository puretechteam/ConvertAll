"""Exotic images (camera RAW, GIMP, HDR, JPEG XL...) via ImageMagick.

ImageMagick can also read scripts and text files as images (MVG, MSL, "@file" lists, URLs). A
downloaded file must never get that far, so the input is copied to a plain name, read with its
format named outright ("XCF:in.xcf"), and a policy turns those readers off."""

import shutil
from pathlib import Path

from .. import engines
from ..registry import converter, option

RAW = {"dng", "cr2", "cr3", "nef", "arw", "orf", "rw2", "raf"}
EXOTIC_IN = RAW | {"xcf", "exr", "hdr", "jxl"}
EXOTIC_OUT = {"jxl", "exr", "hdr"}
POLICY = """<policymap>
  <policy domain="coder" rights="none" pattern="{MVG,MSL,TEXT,TXT,URL,HTTP,HTTPS,FTP,EPHEMERAL,SHOW,WIN,SCREENSHOT,CLIPBOARD}" />
  <policy domain="path" rights="none" pattern="@*" />
</policymap>
"""


@converter(inputs=EXOTIC_IN, outputs={"png", "jpg", "tiff"}, engine="imagemagick",
           options=lambda s, d: ("quality",) if d == "jpg" else ())
@converter(inputs={"psd"}, outputs={"png", "jpg", "tiff"}, engine="imagemagick", cost=2)
@converter(inputs={"png", "jpg", "tiff"}, outputs=EXOTIC_OUT, engine="imagemagick")
def magick_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    exe = engines.require("imagemagick")
    work = dst.parent / "magick"
    work.mkdir(exist_ok=True)
    (work / "policy.xml").write_text(POLICY, encoding="utf-8")
    local = work / f"in.{src_fmt}"
    shutil.copyfile(src, local)
    quality = ["-quality", str(int(option("quality")))] if dst_fmt == "jpg" and option("quality") else []
    try:
        engines.run([exe, f"{src_fmt.upper()}:{local.name}[0]", "-auto-orient", *quality, str(dst)],
                    timeout=600, cwd=str(work), env={"MAGICK_CONFIGURE_PATH": str(work)})
    finally:
        shutil.rmtree(work, ignore_errors=True)
