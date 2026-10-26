"""PDF, XPS, SVG and light ebook handling via PyMuPDF (no external engine)."""

import html
from pathlib import Path

from PIL import Image

from ..errors import ConversionError
from ..registry import converter
from .images import WRITE as RASTER_OUT, prepare, save_image

RASTER_OUT = RASTER_OUT - {"pdf"}
PAGED = {"pdf", "xps", "oxps"}
PDF_DPI = 150


@converter(inputs={"xps", "oxps"}, outputs={"pdf"})
@converter(inputs={"svg"}, outputs={"pdf"}, terminal=True)  # picture-only PDFs: don't chain on
@converter(inputs={"epub", "fb2", "mobi"}, outputs={"pdf"}, cost=2)
def to_pdf(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import pymupdf
    with pymupdf.open(src) as doc:
        dst.write_bytes(doc.convert_to_pdf())


@converter(inputs={"ai"}, outputs={"pdf"})
def illustrator_to_pdf(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    """Illustrator saves a full PDF inside .ai files unless "Create PDF compatible file" was off."""
    import pymupdf
    if not src.read_bytes()[:1024].lstrip().startswith(b"%PDF"):
        raise ConversionError("This .ai file was saved without PDF compatibility, so only Illustrator can open it")
    with pymupdf.open(src, filetype="pdf") as doc:
        doc.save(dst, garbage=3, deflate=True)


def _render(page, fmt: str, zoom: float, alpha: bool) -> Image.Image:
    import pymupdf
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=alpha)
    mode = "RGBA" if pix.alpha else "RGB"
    return prepare(Image.frombytes(mode, (pix.width, pix.height), pix.samples), fmt)


def _save_page(page, path: Path, fmt: str) -> None:
    if fmt == "svg":  # vector stays vector; text becomes outlines so it looks the same everywhere
        path.write_text(page.get_svg_image(text_as_path=True), encoding="utf-8")
    else:
        save_image(_render(page, fmt, PDF_DPI / 72, False), path, fmt)


@converter(inputs=PAGED, outputs=RASTER_OUT | {"svg"}, terminal=True)
def pages_to_images(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> Path:
    """One page -> one image file. Several pages -> a folder of page images."""
    import pymupdf
    with pymupdf.open(src) as doc:
        if doc.page_count == 1:
            _save_page(doc[0], dst, dst_fmt)
            return dst
        folder = dst.parent / f"{dst.stem} ({dst_fmt} pages)"
        folder.mkdir()
        width = len(str(doc.page_count))
        for i, page in enumerate(doc, 1):
            _save_page(page, folder / f"page-{i:0{width}}.{dst_fmt}", dst_fmt)
        return folder


@converter(inputs={"svg"}, outputs=RASTER_OUT)
def svg_to_image(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import pymupdf
    with pymupdf.open(src) as doc:
        page = doc[0]
        longest = max(page.rect.width, page.rect.height) or 1
        zoom = max(1.0, 1024 / longest)  # small icons render crisp, big drawings stay native
        save_image(_render(page, dst_fmt, zoom, True), dst, dst_fmt)


@converter(inputs=PAGED | {"epub", "fb2", "mobi"}, outputs={"txt"}, terminal=True)
def to_text(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import pymupdf
    with pymupdf.open(src) as doc:
        dst.write_text("\n\n".join(page.get_text().strip() for page in doc), encoding="utf-8")


_CSS = "* {font-family: sans-serif; font-size: 11pt; line-height: 1.4} pre, code {font-family: monospace}"


@converter(inputs={"html", "txt"}, outputs={"pdf"}, cost=2)
def html_to_pdf(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import pymupdf
    text = src.read_text(encoding="utf-8", errors="replace")
    if src_fmt == "txt":
        text = f"<pre style='white-space: pre-wrap'>{html.escape(text)}</pre>"
    story = pymupdf.Story(html=text, user_css=_CSS, archive=str(src.parent))
    page_rect = pymupdf.paper_rect("a4")
    content = page_rect + (54, 54, -54, -54)
    writer = pymupdf.DocumentWriter(str(dst))
    more = True
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(content)
        story.draw(device)
        writer.end_page()
    writer.close()
