"""Raster images via Pillow (+ pillow-heif for HEIC), small writers for what Pillow can only read
(PSD, CUR, XPM), and tracing pictures into SVG vectors (vtracer)."""

import functools
import importlib.util
import io
import re
import string
import struct
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

from ..errors import ConversionError
from ..registry import converter

PIL_FORMAT = {
    "png": "PNG", "jpg": "JPEG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP", "tiff": "TIFF",
    "ico": "ICO", "tga": "TGA", "avif": "AVIF", "ppm": "PPM", "jp2": "JPEG2000", "pcx": "PCX",
    "dds": "DDS", "qoi": "QOI", "icns": "ICNS", "pdf": "PDF", "sgi": "SGI", "xbm": "XBM",
    "eps": "EPS",  # written only: reading EPS takes Ghostscript (pdf.py)
}
if importlib.util.find_spec("pillow_heif"):  # without it, HEIC just isn't offered
    PIL_FORMAT["heic"] = "HEIF"


@functools.cache
def enable_heif() -> None:
    """Teach Pillow HEIC on first use; importing pillow-heif up front would slow every run."""
    if "heic" in PIL_FORMAT:
        import pillow_heif
        pillow_heif.register_heif_opener()



# ---- writers for formats Pillow reads but can't save

def write_psd(img: Image.Image, dst: Path) -> None:
    """Flattened Photoshop file: one image, no layers, raw channels (transparency as a 4th channel)."""
    img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
    w, h = img.size
    if max(w, h) > 30000:
        raise ConversionError("Photoshop files are at most 30,000 pixels on a side")
    head = b"8BPS" + struct.pack(">H6xHIIHH", 1, len(img.getbands()), h, w, 8, 3)
    planes = b"".join(band.tobytes() for band in img.split())
    # empty colour-mode, resources and layer sections; compression 0 = raw
    dst.write_bytes(head + struct.pack(">III", 0, 0, 0) + struct.pack(">H", 0) + planes)


def write_cur(img: Image.Image, dst: Path) -> None:
    """A Windows cursor is an icon with type 2 and a hotspot (top-left) instead of planes/bit depth."""
    img = img.convert("RGBA")
    side = max(*img.size, 32)  # 32 px is the smallest cursor Windows draws
    if img.size != (side, side):
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        img = sq
    buf = io.BytesIO()
    sizes = [(s, s) for s in (32, 48, 64, 96, 128) if s <= side]
    img.save(buf, "ICO", sizes=sizes, bitmap_format="bmp")
    data = bytearray(buf.getvalue())
    data[2] = 2
    for i in range(struct.unpack_from("<H", data, 4)[0]):
        struct.pack_into("<HH", data, 6 + 16 * i + 4, 0, 0)  # hotspot x, y
    dst.write_bytes(bytes(data))


_XPM_CHARS = "".join(c for c in string.printable[:94] if c not in '"\\')


def write_xpm(img: Image.Image, dst: Path) -> None:
    """X pixmap: C source text with a palette (up to 256 colours; transparent pixels are None)."""
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    pal_img = rgba.convert("RGB").quantize(255, dither=Image.Dither.NONE)
    palette = pal_img.getpalette()[: 3 * 255]
    px = list(pal_img.getdata())
    clear = 255  # index for transparent pixels
    px = [clear if a == 0 else v for v, a in zip(px, alpha.getdata())]
    used = sorted(set(px))
    cpp = 1 if len(used) <= len(_XPM_CHARS) else 2
    codes = [a + b for a in _XPM_CHARS for b in (_XPM_CHARS if cpp == 2 else [""])]
    code = {idx: codes[i] for i, idx in enumerate(used)}
    w, h = rgba.size
    lines = [f'"{w} {h} {len(used)} {cpp}"']
    for idx in used:
        color = "None" if idx == clear else "#{:02X}{:02X}{:02X}".format(*palette[3 * idx: 3 * idx + 3])
        lines.append(f'"{code[idx]} c {color}"')
    for y in range(h):
        lines.append('"' + "".join(code[v] for v in px[y * w:(y + 1) * w]) + '"')
    name = "".join(c if c.isalnum() else "_" for c in dst.stem) or "image"
    if name[0].isdigit():
        name = f"_{name}"
    dst.write_text(f"/* XPM */\nstatic char *{name}[] = {{\n" + ",\n".join(lines) + "};\n", encoding="ascii")


OWN_WRITERS = {"psd": write_psd, "cur": write_cur, "xpm": write_xpm}
WRITE = set(PIL_FORMAT) | set(OWN_WRITERS)
READ = (set(PIL_FORMAT) - {"pdf", "eps"}) | {"psd", "cur", "xpm"}
NO_ALPHA = {"jpg", "ppm", "pdf", "pcx", "xbm", "eps"}
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
    if fmt in ("heic", "avif", "webp", "dds", "qoi", "icns", "ico", "jp2", "tga", "bmp", "tiff", "png", "sgi") and (
            img.mode not in ("RGB", "RGBA", "L") or (fmt in ("heic", "avif", "dds", "qoi", "icns") and img.mode == "L")):
        return img.convert("RGBA" if has_alpha else "RGB")
    return img


def save_image(img: Image.Image, dst: Path, fmt: str, frames: list[Image.Image] | None = None,
               duration=None) -> None:
    if fmt in OWN_WRITERS:
        return OWN_WRITERS[fmt](img, dst)
    if fmt == "heic":
        enable_heif()
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


@converter(inputs=READ, outputs=WRITE - {"pdf", "eps"})
# an image PDF (or EPS) holds no text or vectors to chain into docx, dxf etc.
@converter(inputs=READ, outputs={"pdf", "eps"}, terminal=True)
def pillow_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    if src_fmt == "heic":
        enable_heif()
    with Image.open(src) as img:
        n = getattr(img, "n_frames", 1)
        if n > 1 and dst_fmt in ANIMATED:
            frames = [prepare(f.copy(), dst_fmt) for f in ImageSequence.Iterator(img)]
            save_image(frames[0], dst, dst_fmt, frames, img.info.get("duration"))
        else:
            first = ImageOps.exif_transpose(img) or img
            save_image(prepare(first, dst_fmt), dst, dst_fmt)


# ---- pictures -> SVG: trace the shapes into vector paths

@converter(inputs=READ - {"ico", "icns", "cur"}, outputs={"svg"}, cost=2, terminal=True)
def trace_to_svg(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import vtracer
    if src_fmt == "heic":
        enable_heif()
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img) or img
        img = img.convert("RGBA")
        if max(img.size) > 2000:  # tracing time grows with pixels; detail beyond this is noise
            img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
        # vtracer only drops transparent areas it happens to sample, so paint them in a colour the
        # picture doesn't use, trace with shapes cut out of each other, then delete that colour's
        # shapes: what's left are real holes.
        opaque = img.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        key = _unused_color(img) if opaque.getextrema()[0] == 0 else None
        flat = Image.new("RGB", img.size, key or (255, 255, 255))
        flat.paste(img.convert("RGB"), mask=opaque)
        buf = io.BytesIO()
        flat.save(buf, "PNG")
    svg = vtracer.convert_raw_image_to_svg(buf.getvalue(), img_format="png", colormode="color",
                                           hierarchical="cutout" if key else "stacked", mode="spline",
                                           filter_speckle=4, color_precision=6, layer_difference=16,
                                           corner_threshold=60, length_threshold=4.0, splice_threshold=45,
                                           path_precision=3)
    if key:
        svg = re.sub(r'<path [^>]*fill="#{:02X}{:02X}{:02X}"[^>]*/>\s*'.format(*key), "", svg)
    dst.write_text(svg, encoding="utf-8")


def _unused_color(img: Image.Image) -> tuple[int, int, int]:
    """A colour (that survives vtracer's 6-bit colour precision) no pixel of img comes close to."""
    small = img.convert("RGB").resize((min(img.width, 256), min(img.height, 256)))
    used = {(r >> 3, g >> 3, b >> 3) for r, g, b in small.getdata()}
    for cand in ((252, 0, 252), (0, 252, 252), (252, 252, 0), (4, 252, 128), (128, 4, 252), (252, 128, 4)):
        if (cand[0] >> 3, cand[1] >> 3, cand[2] >> 3) not in used:
            return cand
    return next((r * 8, g * 8, b * 8) for r in range(32) for g in range(32) for b in range(32)
                if (r, g, b) not in used)
