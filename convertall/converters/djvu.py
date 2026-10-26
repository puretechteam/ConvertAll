"""DjVu (scanned books) via DjVuLibre: pages to PDF, and the hidden text layer to plain text."""

import shutil
from pathlib import Path

from .. import engines
from ..errors import ConversionError
from ..registry import converter


@converter(inputs={"djvu"}, outputs={"pdf"}, engine="djvulibre")
@converter(inputs={"djvu"}, outputs={"txt"}, engine="djvulibre", terminal=True)
def djvu_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    ddjvu = engines.require("djvulibre")
    # DjVuLibre's tools take ANSI paths on Windows: work on plain names
    local = dst.parent / "input.djvu"
    shutil.copyfile(src, local)
    if dst_fmt == "pdf":
        engines.run([ddjvu, "-format=pdf", "-quality=85", local.name, "output.pdf"],
                    timeout=1800, cwd=str(dst.parent))
        (dst.parent / "output.pdf").replace(dst)
    else:
        djvutxt = Path(ddjvu).with_name("djvutxt.exe")
        text = engines.run([djvutxt, local.name], timeout=600, cwd=str(dst.parent)).stdout
        if not text.strip():
            raise ConversionError("This DjVu file has no text layer (it was scanned without OCR)")
        dst.write_text(text, encoding="utf-8")
