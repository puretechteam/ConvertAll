"""Ebooks through bookport: every format out and back, comics, documents, PDF settings, DRM."""

import zipfile

import bookport
import pymupdf
import pytest

from convertall import Report, pipeline, registry
from convertall.converters import ebooks
from convertall.errors import ConversionError

from .samples import TEXT, Samples


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    return Samples(tmp_path_factory.mktemp("books"))


@pytest.mark.parametrize("fmt", sorted(ebooks.BOOKS_OUT - {"epub"}))
def test_every_ebook_format_out_and_back(fmt, samples, tmp_path):
    report = Report()
    out = pipeline.convert(samples("epub"), fmt, tmp_path, report=report)
    assert [s["tool"].split()[0] for s in report.steps] == ["bookport"]
    back = pipeline.convert(out, "epub", tmp_path / "back")
    book = bookport.read(back)
    if fmt not in ("tcr", "pml"):  # formats with no place for a title
        assert book.metadata.title == "Sample"
    assert TEXT.lower() in book.text().lower()
    assert not report.warnings, report.lines()
    assert {c.name for c in report.checks} == {"Words"}


def test_comic_becomes_a_fixed_layout_book(samples, tmp_path):
    out = pipeline.convert(samples("cbz"), "epub", tmp_path)
    book = bookport.read(out)
    assert book.fixed_layout and len(book.images()) >= 4  # the four pages, the webp one included
    assert book.metadata.title == "Sample"  # from ComicInfo.xml


def test_documents_become_ebooks_but_keep_their_own_routes(samples, tmp_path):
    out = pipeline.convert(samples("docx"), "mobi", tmp_path) if samples("docx") else None
    if out:
        assert bookport.read(out).word_count() > 0
    # a Word file to PDF or Markdown to HTML is never laid out as an ebook
    assert registry.find_route("docx", "pdf").edges[0].func.__name__ != "book_convert"
    assert registry.find_route("md", "html").edges[0].func.__name__ != "book_convert"


def test_page_and_text_size(samples, tmp_path):
    def page(**opts):
        out = pipeline.convert(samples("epub"), "pdf", tmp_path / str(len(list(tmp_path.iterdir()))), options=opts)
        with pymupdf.open(out) as doc:
            return round(doc[0].rect.width), doc.page_count
    a4, phone = page(page_size="a4"), page(page_size="phone")
    assert a4[0] == 595 and phone[0] < 400  # A4 is 595 points wide
    assert page(page_size="phone", text_size="large")[1] >= phone[1]
    with pytest.raises(ConversionError, match="Page size"):
        pipeline.convert(samples("epub"), "pdf", tmp_path, options={"page_size": "huge"})
    assert set(registry.find_route("epub", "pdf").settings) == {"page_size", "text_size"}


def test_copy_protected_books_are_refused(tmp_path):
    src = tmp_path / "locked.epub"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="c.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("META-INF/encryption.xml",
                   '<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                   'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
                   '<enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>'
                   '<enc:CipherData><enc:CipherReference URI="ch1.xhtml"/></enc:CipherData></enc:EncryptedData></encryption>')
        z.writestr("c.opf", "<package/>")
    with pytest.raises(ConversionError, match="copy-protected"):
        pipeline.convert(src, "mobi", tmp_path / "out")


def test_markdown_and_tcr_say_what_they_leave_out():
    assert any("pictures are left out" in n for n in registry.find_route("epub", "md").notes)
    assert any("plain text" in n for n in registry.find_route("epub", "tcr").notes)


def _jpg(color) -> bytes:
    import io

    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 60), color).save(out, "JPEG" if color != "blue" else "WEBP")
    return out.getvalue()


def test_comic_pages_never_replace_each_other(tmp_path):
    """07.webp is turned into a JPG; that must not write over the 07.jpg beside it."""
    src = tmp_path / "pages.cbz"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("07.jpg", _jpg("red"))
        z.writestr("07.webp", _jpg("blue"))
        z.writestr("08.jpg", _jpg("green"))
        z.writestr("../escape.jpg", _jpg("red"))  # renamed or skipped, and the report says so
    report = Report()
    out = pipeline.convert(src, "epub", tmp_path / "out", report=report)
    assert len(bookport.read(out).images()) == 3  # the escaping one is left out
    assert any("escape" in n or "outside" in n or "renamed" in n.lower() or "left out" in n.lower()
               for n in report.notes), report.lines()


def test_books_are_read_as_the_planned_format(samples, tmp_path, monkeypatch):
    seen = []
    real = bookport.read
    monkeypatch.setattr(bookport, "read", lambda path, fmt=None, **kw: seen.append(fmt) or real(path, fmt, **kw))
    pipeline.convert(samples("epub"), "mobi", tmp_path)
    assert seen == ["epub"]


@pytest.mark.parametrize("fmt", sorted(ebooks.DOCS_OUT))
def test_ebooks_to_documents_are_checked_too(fmt, samples, tmp_path):
    """An ebook made into a PDF, Word file or text still gets its words counted."""
    report = Report()
    pipeline.convert(samples("epub"), fmt, tmp_path, report=report)
    words = [c for c in report.checks if c.name == "Words"]
    assert words and words[0].state == "ok", report.lines()
