"""Ebooks via Calibre's ebook-convert."""

from pathlib import Path

from .. import engines
from ..detect import COMICS
from ..registry import converter

EBOOK_IN = {"epub", "mobi", "azw3", "azw", "fb2", "lit", "pdb", "lrf", "chm"}
EBOOK_OUT = {"epub", "mobi", "azw3", "fb2", "pdf", "docx", "txt"}
READER_OUT = {"epub", "mobi", "azw3"}


@converter(inputs=EBOOK_IN, outputs=EBOOK_OUT, engine="calibre")
@converter(inputs=COMICS, outputs=READER_OUT, engine="calibre", terminal=True)  # pages only: no text to chain
@converter(inputs={"html", "docx", "odt", "rtf", "txt"}, outputs=READER_OUT, engine="calibre")
@converter(inputs={"pdf"}, outputs=READER_OUT, engine="calibre", cost=2, first_only=True)
def calibre_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    engines.run([engines.require("calibre"), str(src), str(dst)])
