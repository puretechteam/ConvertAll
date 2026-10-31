"""Markup languages via Pandoc: LaTeX, reStructuredText, Org, AsciiDoc and MediaWiki, to and from
Markdown, HTML, Word, OpenDocument and EPUB.

Pandoc runs sandboxed: it reads only the file it's given, so an include line in a downloaded file
(".. include:: C:/Users/.../passwords.txt") can't copy other files into the result. Pictures still
come along: ConvertAll reads the ones in the file's own folder or one level up (safety.local_file)
and hands them to Pandoc inside the document."""

import base64
import json
import mimetypes
from pathlib import Path

from .. import engines
from ..registry import converter
from ..safety import local_file

READER = {"tex": "latex", "rst": "rst", "org": "org", "adoc": "asciidoc", "wiki": "mediawiki",
          "md": "markdown", "html": "html", "docx": "docx", "odt": "odt", "epub": "epub"}
WRITER = READER | {"md": "gfm"}  # GitHub-flavoured Markdown: what most Markdown readers expect
MARKUP = {"tex", "rst", "org", "adoc", "wiki"}
HUB = {"md", "html", "docx", "odt", "epub"}
STANDALONE = {"html", "tex"}  # a whole document (head, preamble), not a fragment
EMBEDS = {"html", "docx", "odt", "epub"}  # outputs that carry their pictures inside
PICTURE_LIMIT = 64 << 20  # per picture
GUESS = (".png", ".jpg", ".jpeg", ".gif", ".svg")  # LaTeX leaves the extension off


def _picture(base: Path, link: str) -> str | None:
    """The picture link points at, as a data: URI, or None when it's not one we may read."""
    path = local_file(base, link)
    if path is None and not Path(link).suffix:
        path = next((p for p in (local_file(base, link + ext) for ext in GUESS) if p), None)
    mime = path and mimetypes.guess_type(path.name)[0]
    if not mime or not mime.startswith("image/") or path.stat().st_size > PICTURE_LIMIT:
        return None
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def embed_pictures(ast: dict, base: Path) -> int:
    """Swap each local picture link in a Pandoc document (its JSON form) for the picture itself.
    Returns how many were embedded."""
    found, stack = 0, [ast]
    while stack:  # no recursion: a deeply nested document can't overflow the stack
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("t") == "Image" and isinstance(node.get("c"), list) and len(node["c"]) == 3:
                target = node["c"][2]
                if isinstance(target, list) and target and isinstance(target[0], str):
                    uri = _picture(base, target[0])
                    if uri:
                        target[0] = uri
                        found += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


@converter(inputs=MARKUP, outputs=HUB | MARKUP, engine="pandoc")
@converter(inputs=HUB, outputs=MARKUP, engine="pandoc")
def pandoc_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    exe = engines.require("pandoc")
    ast_file = dst.with_name(dst.stem + ".pandoc.json")
    args = [exe, "--sandbox", "-f", "json", "-t", WRITER[dst_fmt], "-o", str(dst)]
    if dst_fmt in STANDALONE:
        args.append("--standalone")
    if dst_fmt == "html":
        args.append("--embed-resources")  # pictures inside the page, so it's one file
    try:
        engines.run([exe, "--sandbox", "-f", READER[src_fmt], "-t", "json", "-o", str(ast_file), str(src)],
                    timeout=600)
        if dst_fmt in EMBEDS:
            ast = json.loads(ast_file.read_text(encoding="utf-8"))
            if embed_pictures(ast, src.parent):
                ast_file.write_text(json.dumps(ast), encoding="utf-8")
        engines.run([*args, str(ast_file)], timeout=600)
    finally:
        ast_file.unlink(missing_ok=True)
