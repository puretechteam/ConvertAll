"""Markdown and HTML, plus Word -> HTML. HTML -> Word/ODT/RTF is LibreOffice's job (documents.py)."""

import html
from pathlib import Path

from ..registry import converter

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{max-width:46em;margin:2em auto;padding:0 1em;font-family:system-ui,sans-serif;line-height:1.55}}
pre{{background:#f4f4f4;padding:.8em;overflow:auto}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:.3em .6em}}
img{{max-width:100%}}</style>
</head><body>
{body}
</body></html>
"""


def page(title: str, body: str) -> str:
    return _PAGE.format(title=html.escape(title), body=body)


@converter(inputs={"md"}, outputs={"html"})
def markdown_to_html(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import markdown
    text = src.read_text(encoding="utf-8-sig")
    body = markdown.markdown(text, extensions=["extra", "sane_lists"])
    dst.write_text(page(src.stem, body), encoding="utf-8")


@converter(inputs={"html"}, outputs={"md"})
def html_to_markdown(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    from bs4 import BeautifulSoup
    from markdownify import markdownify
    soup = BeautifulSoup(src.read_text(encoding="utf-8-sig", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    body = soup.body or soup
    md = markdownify(str(body), heading_style="ATX", bullets="-", strip=["span"])
    dst.write_text(md.strip() + "\n", encoding="utf-8")


# Word/LibreOffice character and paragraph *styles* (as opposed to direct formatting) that
# mammoth doesn't map by default. LibreOffice imports <em>/<code>/<pre> as these styles.
_DOCX_STYLES = """
r[style-name='Emphasis'] => em
r[style-name='Strong'] => strong
r[style-name='Strong Emphasis'] => strong
r[style-name='Source Text'] => code
r[style-name='Teletype'] => code
p[style-name='Preformatted Text'] => pre:separator('\\n')
p[style-name='Block Quotation'] => blockquote > p:fresh
p[style-name='Quotations'] => blockquote > p:fresh
p[style-name='Quote'] => blockquote > p:fresh
"""


@converter(inputs={"docx"}, outputs={"html"})
def docx_to_html(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import mammoth
    with src.open("rb") as f:
        result = mammoth.convert_to_html(f, style_map=_DOCX_STYLES)  # images embed as data: URIs
    dst.write_text(page(src.stem, result.value), encoding="utf-8")
