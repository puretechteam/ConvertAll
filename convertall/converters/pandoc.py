"""Markup languages via Pandoc: LaTeX, reStructuredText, Org, AsciiDoc and MediaWiki, to and from
Markdown, HTML, Word, OpenDocument and EPUB."""

from pathlib import Path

from .. import engines
from ..registry import converter

READER = {"tex": "latex", "rst": "rst", "org": "org", "adoc": "asciidoc", "wiki": "mediawiki",
          "md": "markdown", "html": "html", "docx": "docx", "odt": "odt", "epub": "epub"}
WRITER = READER | {"md": "gfm"}  # GitHub-flavoured Markdown: what most Markdown readers expect
MARKUP = {"tex", "rst", "org", "adoc", "wiki"}
HUB = {"md", "html", "docx", "odt", "epub"}
STANDALONE = {"html", "tex"}  # a whole document (head, preamble), not a fragment


@converter(inputs=MARKUP, outputs=HUB | MARKUP, engine="pandoc")
@converter(inputs=HUB, outputs=MARKUP, engine="pandoc")
def pandoc_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    args = [engines.require("pandoc"), "-f", READER[src_fmt], "-t", WRITER[dst_fmt],
            f"--resource-path={src.parent}", "-o", str(dst)]
    if dst_fmt in STANDALONE:
        args.append("--standalone")
    if dst_fmt == "html":
        args.append("--embed-resources")  # pictures inside the page, so it's one file
    engines.run([*args, str(src)], timeout=600)
