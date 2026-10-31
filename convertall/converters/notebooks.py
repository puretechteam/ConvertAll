"""Jupyter notebooks (.ipynb, which is JSON) to Markdown and HTML: text cells as written, code
cells as code blocks, and their saved outputs (text, tables, pictures) below them."""

import base64
import html
import json
from pathlib import Path

from ..errors import ConversionError
from ..registry import converter
from ..textfile import read_text
from .markup import page


def _text(value) -> str:
    return "".join(value) if isinstance(value, list) else str(value or "")


def _load(src: Path) -> tuple[list[dict], str]:
    try:
        nb = json.loads(read_text(src))
        cells = nb["cells"] if "cells" in nb else [c for ws in nb["worksheets"] for c in ws["cells"]]  # v3
    except (ValueError, KeyError, TypeError) as exc:
        raise ConversionError(f"Not a Jupyter notebook: {exc}") from None
    lang = (nb.get("metadata", {}).get("kernelspec", {}).get("language")
            or nb.get("metadata", {}).get("language_info", {}).get("name") or "python")
    return cells, lang


def _outputs(cell: dict, as_html: bool) -> list[str]:
    """Each saved output as a Markdown (or HTML) snippet, richest form first."""
    parts = []
    for out in cell.get("outputs", []):
        kind = out.get("output_type")
        data = out.get("data", {})
        if kind == "stream":
            text = _text(out.get("text"))
        elif kind == "error":
            text = f"{out.get('ename', 'Error')}: {out.get('evalue', '')}"
        else:
            text = None
        if text is not None:
            parts.append(f"<pre>{html.escape(text)}</pre>" if as_html else f"```\n{text.rstrip()}\n```")
            continue
        image = next((m for m in ("image/png", "image/jpeg", "image/gif") if m in data), None)
        if image:
            b64 = _text(data[image]).replace("\n", "")
            uri = f"data:{image};base64,{b64}"
            parts.append(f'<img src="{uri}" alt="output">' if as_html else f"![output]({uri})")
        elif "image/svg+xml" in data:
            svg = _text(data["image/svg+xml"])
            uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
            parts.append(f'<img src="{uri}" alt="output">' if as_html else f"![output]({uri})")
        elif as_html and "text/html" in data:
            parts.append(_text(data["text/html"]))  # pandas tables and the like
        elif "text/markdown" in data:
            parts.append(_text(data["text/markdown"]))
        elif "text/plain" in data:
            text = _text(data["text/plain"])
            parts.append(f"<pre>{html.escape(text)}</pre>" if as_html else f"```\n{text.rstrip()}\n```")
    return parts


def notebook_markdown(src: Path) -> str:
    cells, lang = _load(src)
    blocks = []
    for cell in cells:
        source = _text(cell.get("source", cell.get("input", ""))).rstrip()
        kind = cell.get("cell_type")
        if kind == "markdown":
            blocks.append(source)
        elif kind == "code":
            if source:
                blocks.append(f"```{lang}\n{source}\n```")
            blocks += _outputs(cell, as_html=False)
        elif source:  # raw cells
            blocks.append(source)
    return "\n\n".join(b for b in blocks if b) + "\n"


@converter(inputs={"ipynb"}, outputs={"md"})
def ipynb_to_md(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    dst.write_text(notebook_markdown(src), encoding="utf-8")


@converter(inputs={"ipynb"}, outputs={"html"})
def ipynb_to_html(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    import markdown
    cells, lang = _load(src)
    body = []
    for cell in cells:
        source = _text(cell.get("source", cell.get("input", ""))).rstrip()
        kind = cell.get("cell_type")
        if kind == "markdown":
            body.append(markdown.markdown(source, extensions=["extra", "sane_lists"]))
        elif kind == "code":
            if source:
                body.append(f'<pre><code class="language-{lang}">{html.escape(source)}</code></pre>')
            body += _outputs(cell, as_html=True)
        elif source:
            body.append(f"<pre>{html.escape(source)}</pre>")
    dst.write_text(page(src.stem, "\n".join(body)), encoding="utf-8")
