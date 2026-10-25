"""Comics (CBZ/CBR/CB7/CBT, i.e. archives of page images) <-> PDF, and folders of images -> PDF."""

import io
import re
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from ..detect import COMICS
from ..errors import ConversionError
from ..registry import converter
from .archives import compress, extract_to
from .images import READ as PIL_READ, prepare
from .pdf import PDF_DPI

PAGE_EXT = {f".{e}" for e in PIL_READ} | {".jpeg", ".jpe", ".jfif", ".tif", ".heif"}
WRITABLE = COMICS - {"cbr"}


def _natural(p: Path) -> list:
    """'page2' before 'page10'."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.as_posix().lower())]


def _pages(root: Path) -> list[Path]:
    hidden = lambda p: any(part.startswith((".", "__MACOSX")) for part in p.relative_to(root).parts)  # noqa: E731
    pages = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in PAGE_EXT and not hidden(p)]
    return sorted(pages, key=lambda p: _natural(p.relative_to(root)))


def _page_bytes(path: Path) -> tuple[bytes, tuple[int, int]]:
    """JPEG and PNG pages go into the PDF untouched; anything else is re-encoded once."""
    with Image.open(path) as img:
        upright = img.getexif().get(0x0112, 1) in (0, 1)
        if img.format in ("JPEG", "PNG") and upright and img.mode in ("RGB", "L", "RGBA", "LA", "P", "1"):
            return path.read_bytes(), img.size
        img = ImageOps.exif_transpose(img) or img
        # lossy sources (WebP, AVIF, HEIC) stay JPEG; lossless ones (GIF, BMP, TIFF) become PNG
        fmt = "jpg" if img.format in ("WEBP", "AVIF", "HEIF", "JPEG", "MPO") else "png"
        out = io.BytesIO()
        prepare(img, fmt).save(out, "JPEG" if fmt == "jpg" else "PNG", quality=95)
        return out.getvalue(), img.size


def images_to_pdf(pages: list[Path], dst: Path) -> None:
    doc = pymupdf.open()
    scale = 72 / PDF_DPI
    for path in pages:
        try:
            data, (w, h) = _page_bytes(path)
        except Exception as exc:
            raise ConversionError(f"Couldn't read page {path.name}: {exc}") from exc
        page = doc.new_page(width=w * scale, height=h * scale)
        page.insert_image(page.rect, stream=data)
    doc.save(dst, garbage=3, deflate=True)


@converter(inputs=COMICS - {"cbr"}, outputs={"pdf"}, terminal=True)
@converter(inputs={"cbr"}, outputs={"pdf"}, engine="7zip", terminal=True)
def comic_to_pdf(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    work = dst.parent / "_pages"
    extract_to(src, work, src_fmt)
    pages = _pages(work)
    if not pages:
        raise ConversionError("No page images found in this comic")
    images_to_pdf(pages, dst)


@converter(inputs={"folder"}, outputs={"pdf"}, terminal=True)
def folder_to_pdf(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    """Every image in the folder (and subfolders), in name order, one per page."""
    pages = _pages(src)
    if not pages:
        raise ConversionError("No images found in this folder")
    images_to_pdf(pages, dst)


def _page_image(doc, page) -> tuple[bytes, str] | None:
    """The page's picture as stored, if the page is nothing but one full-page JPEG/PNG (scanned
    comics are), so PDF -> CBZ doesn't re-compress anything."""
    images = page.get_images(full=True)
    if len(images) != 1 or page.rotation or page.get_text().strip():
        return None
    xref, smask = images[0][0], images[0][1]
    rects = page.get_image_rects(xref)
    if smask or len(rects) != 1 or rects[0].get_area() < page.rect.get_area() * 0.95:
        return None
    info = doc.extract_image(xref)
    if info.get("ext") not in ("jpeg", "png") or info.get("colorspace") not in (1, 3):  # gray or RGB, not CMYK
        return None
    return info["image"], "jpg" if info["ext"] == "jpeg" else "png"


@converter(inputs={"pdf"}, outputs=WRITABLE, terminal=True)
def pdf_to_comic(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    work = dst.parent / "_pages"
    work.mkdir()
    zoom = PDF_DPI / 72
    with pymupdf.open(src) as doc:
        width = max(3, len(str(doc.page_count)))
        for i, page in enumerate(doc, 1):
            stored = _page_image(doc, page)
            if stored:
                data, ext = stored
                (work / f"{i:0{width}}.{ext}").write_bytes(data)
            else:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                pix.save(str(work / f"{i:0{width}}.jpg"), jpg_quality=92)
    compress(work, dst, dst_fmt)


@converter(inputs={"folder"}, outputs=WRITABLE, terminal=True)
def folder_to_comic(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    if not _pages(src):
        raise ConversionError("No images found in this folder")
    compress(src, dst, dst_fmt)
