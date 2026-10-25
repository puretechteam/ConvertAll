"""Raster images via Pillow (+ pillow-heif for HEIC)."""

from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

from ..registry import converter

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # HEIC just won't be offered
    pillow_heif = None

PIL_FORMAT = {
    "png": "PNG", "jpg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP", "tiff": "TIFF",
    "ico": "ICO", "tga": "TGA", "avif": "AVIF", "ppm": "PPM", "jp2": "JPEG2000", "pcx": "PCX",
    "dds": "DDS", "qoi": "QOI", "icns": "ICNS", "pdf": "PDF", "sgi": "SGI", "xbm": "XBM",
}
if pillow_heif:
    PIL_FORMAT["heic"] = "HEIF"

WRITE = set(PIL_FORMAT)
READ = (WRITE - {"pdf"}) | {"psd", "cur", "xpm"}
NO_ALPHA = {"jpg", "ppm", "pdf", "pcx", "xbm"}
ANIMATED = {"gif", "webp", "png", "avif", "tiff", "pdf"}
SAVE_OPTS = {
    "jpg": {"quality": 92, "optimize": True},
    "webp": {"quality": 90, "method": 6},
    "avif": {"quality": 80},
    "heic": {"quality": 90},
    "png": {"optimize": True},
    "tiff": {"compression": "tiff_lzw"},
    "pdf": {"resolution": 150},
}


def prepare(img: Image.Image, fmt: str) -> Image.Image:
    """Convert img's mode to something fmt can store."""
    if img.mode in ("I", "I;16", "I;16B", "F"):
        img = img.convert("I").point(lambda v: v / 256).convert("L") if img.mode != "F" else img.convert("L")
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if fmt in NO_ALPHA:
        if has_alpha:
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, "white")
            bg.paste(rgba, mask=rgba.getchannel("A"))
            img = bg
        if fmt == "xbm":  # black and white only
            return img.convert("1")
        return img if img.mode in ("RGB", "L") else img.convert("RGB")
    if fmt in ("heic", "avif", "webp", "dds", "qoi", "icns", "ico", "jp2", "tga", "bmp", "tiff", "png", "sgi"):
        if img.mode not in ("RGB", "RGBA", "L") or (fmt in ("heic", "avif", "dds", "qoi", "icns") and img.mode == "L"):
            return img.convert("RGBA" if has_alpha else "RGB")
    return img


def save_image(img: Image.Image, dst: Path, fmt: str, frames: list[Image.Image] | None = None,
               duration=None) -> None:
    opts = dict(SAVE_OPTS.get(fmt, {}))
    if frames and len(frames) > 1 and fmt in ANIMATED:
        opts.update(save_all=True, append_images=frames[1:])
        if fmt in ("gif", "webp", "png", "avif"):
            opts.update(duration=duration or 100, loop=0)
    if fmt == "ico":
        side = max(*img.size, 16)  # tiny images still get the smallest icon size
        opts["sizes"] = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side]
        if img.size != (side, side):  # icons must be square (and >= 16 px): pad, don't stretch
            sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            sq.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
            img = sq
    img.save(dst, PIL_FORMAT[fmt], **opts)


@converter(inputs=READ, outputs=WRITE - {"pdf"})
@converter(inputs=READ, outputs={"pdf"}, terminal=True)  # an image PDF has no text to chain into docx etc.
def pillow_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    with Image.open(src) as img:
        n = getattr(img, "n_frames", 1)
        if n > 1 and dst_fmt in ANIMATED:
            frames = [prepare(f.copy(), dst_fmt) for f in ImageSequence.Iterator(img)]
            save_image(frames[0], dst, dst_fmt, frames, img.info.get("duration"))
        else:
            first = ImageOps.exif_transpose(img) or img
            save_image(prepare(first, dst_fmt), dst, dst_fmt)
