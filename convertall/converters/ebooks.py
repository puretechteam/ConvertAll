"""Ebooks via bookport (pure Python, no Calibre): every ebook format to every other, ebooks to
PDF, Word, RTF, HTML, Markdown and text, and documents and comics into ebooks."""

from pathlib import Path

from ..detect import COMICS
from ..errors import ConversionError
from ..losses import loss
from ..registry import converter, note, option
from .archives import extract_to

BOOKS = {"epub", "mobi", "azw3", "azw", "fb2", "fbz", "lit", "pdb", "lrf", "chm", "htmlz", "txtz",
         "rb", "tcr", "snb", "pml", "pmlz"}
BOOKS_OUT = BOOKS - {"chm"}  # CHM is help files: read only
DOCS_OUT = {"pdf", "docx", "rtf", "txt", "md", "html"}
DOCS_IN = {"html", "txt", "md", "docx", "odt", "rtf"}  # into ebooks only: their own routes stay
COMIC_PAGES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}  # what bookport takes as a page


def _notes(src: str, dst: str, opts: dict) -> list:
    if dst == "tcr":
        return [loss("TCR holds plain text: formatting and pictures are left out", "formatting")]
    if dst == "md":
        return [loss("Markdown is one text file: pictures are left out", weight=0)]
    return []


def _pdf_options(src: str, dst: str) -> tuple:
    return ("page_size", "text_size") if dst == "pdf" else ()


def _write(book, dst: Path, dst_fmt: str) -> None:
    import bookport
    opts = {"page_size": option("page_size"), "text_size": option("text_size")} if dst_fmt == "pdf" else {}
    try:
        book.write(dst, dst_fmt, **opts)
    except bookport.BookportError as exc:
        raise ConversionError(str(exc)) from None


def _read(src: Path, src_fmt: str | None):
    """The book, read as the format the route planned (a .epub that is really a MOBI was found out
    already), or as what bookport finds when src_fmt is None (a folder of pages)."""
    import bookport
    try:
        return bookport.read(src, src_fmt)
    except bookport.DRMError as exc:
        raise ConversionError(f"This book is copy-protected (DRM), so it can't be converted: {exc}") from None
    except bookport.BookportError as exc:
        raise ConversionError(str(exc)) from None


@converter(inputs=BOOKS, outputs=BOOKS_OUT, notes=_notes)
# out of an ebook only when the file is one: a Word file to Markdown never detours through a book
@converter(inputs=BOOKS, outputs=DOCS_OUT, first_only=True, notes=_notes, options=_pdf_options)
@converter(inputs=DOCS_IN, outputs=BOOKS_OUT, notes=_notes)
@converter(inputs={"pdf"}, outputs=BOOKS_OUT, cost=2, first_only=True,
           notes=lambda s, d, o: [loss("The PDF is rebuilt as flowing text: the page layout is left out", weight=0)])
def book_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    _write(_read(src, src_fmt), dst, dst_fmt)


@converter(inputs=COMICS - {"cbr"}, outputs=BOOKS_OUT - {"txt", "txtz", "tcr", "pml", "pmlz"}, terminal=True)
@converter(inputs={"cbr"}, outputs=BOOKS_OUT - {"txt", "txtz", "tcr", "pml", "pmlz"}, engine="7zip", terminal=True)
def comic_to_book(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    """Each page becomes a page of a fixed-layout book. The archive is unpacked first, so every
    kind of comic works; pages in formats readers don't take (HEIC, TIFF, AVIF) become JPG or PNG."""
    from .comics import _page_bytes, _pages
    work = dst.parent / "_pages"
    found: list[str] = []
    extract_to(src, work, src_fmt, found)
    for line in found:
        note(line)
    pages = _pages(work)
    if not pages:
        raise ConversionError("No page images found in this comic")
    for page in pages:
        if page.suffix.lower() not in COMIC_PAGES:
            data, _size = _page_bytes(page)
            page.unlink()
            # "07.webp" becomes "07.webp.jpg": it sorts where it was and can't replace a "07.jpg"
            ext = ".jpg" if data[:2] == b"\xff\xd8" else ".png"
            target, n = page.with_name(page.name + ext), 1
            while target.exists():
                target, n = page.with_name(f"{page.name}-{n}{ext}"), n + 1
            target.write_bytes(data)
    book = _read(work, None)
    if book.metadata.title in ("", work.name):  # no ComicInfo.xml title: the file's name
        book.metadata.title = src.stem
    _write(book, dst, dst_fmt)
