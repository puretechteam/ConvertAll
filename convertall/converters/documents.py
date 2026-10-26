"""Office documents via headless LibreOffice."""

import os
import shutil
from pathlib import Path

from .. import engines
from ..errors import ConversionError
from ..registry import converter

WRITER_IN = {"doc", "docx", "odt", "rtf", "wpd", "pages", "txt", "docm", "dotx", "dot", "wps", "hwp"}
WRITER_OUT = {"pdf", "docx", "doc", "odt", "rtf", "txt"}
CALC_IN = {"xls", "xlsx", "ods", "numbers", "csv", "xlsm", "xlsb", "xltx", "dbf"}
CALC_OUT = {"pdf", "xlsx", "xls", "ods", "csv"}
IMPRESS_IN = {"ppt", "pptx", "odp", "key", "pptm", "ppsx", "pps", "potx"}
IMPRESS_OUT = {"pdf", "pptx", "ppt", "odp"}
DRAW_IN = {"vsdx", "vsd", "pub", "odg", "cdr"}
METAFILE = {"emf", "wmf"}

FILTERS = {
    "txt": "txt:Text (encoded):UTF8",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "doc": "doc:MS Word 97",
    "xls": "xls:MS Excel 97",
    "ppt": "ppt:MS PowerPoint 97",
}


def _soffice() -> str:
    exe = engines.require("libreoffice")
    com = Path(exe).with_suffix(".com")  # console launcher waits for the conversion to finish
    return str(com) if com.exists() else exe


def _profile_uri() -> str:
    """A private LibreOffice profile so conversions work even while LibreOffice is open."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ConvertAll" / "libreoffice-profile"
    base.mkdir(parents=True, exist_ok=True)
    return base.as_uri()


def soffice_convert(src: Path, dst: Path, dst_fmt: str, infilter: str | None = None) -> None:
    outdir = dst.parent / "_lo"
    outdir.mkdir(exist_ok=True)
    cmd = [_soffice(), "--headless", "--norestore", "--nolockcheck", "--nodefault",
           f"-env:UserInstallation={_profile_uri()}"]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    cmd += ["--convert-to", FILTERS.get(dst_fmt, dst_fmt), "--outdir", str(outdir), str(src)]
    proc = engines.run(cmd, timeout=600)
    produced = [p for p in outdir.iterdir() if p.suffix.lower() == f".{dst_fmt}"]
    if not produced:
        raise ConversionError(f"LibreOffice couldn't convert this file. {proc.stdout.strip()[-300:]}")
    shutil.move(str(produced[0]), str(dst))


@converter(inputs=WRITER_IN, outputs=WRITER_OUT, engine="libreoffice")
@converter(inputs=CALC_IN, outputs=CALC_OUT, engine="libreoffice")
@converter(inputs=IMPRESS_IN, outputs=IMPRESS_OUT, engine="libreoffice")
def office_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    soffice_convert(src, dst, dst_fmt)


# Diagrams, Publisher files and metafiles: PDF keeps them as vectors; PNG/SVG are page 1 only
@converter(inputs=DRAW_IN, outputs={"pdf", "odg"}, engine="libreoffice")
@converter(inputs=DRAW_IN | METAFILE, outputs={"png", "svg"}, engine="libreoffice")
@converter(inputs=METAFILE, outputs={"pdf"}, engine="libreoffice", terminal=True)
def draw_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    soffice_convert(src, dst, dst_fmt)


@converter(inputs={"html"}, outputs={"docx", "odt", "rtf", "doc"}, engine="libreoffice")
def html_to_writer(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    soffice_convert(src, dst, dst_fmt, infilter="HTML (StarWriter)")  # Writer, not Writer/Web


@converter(inputs={"pdf"}, outputs={"docx", "odt"}, engine="libreoffice", cost=2, first_only=True)
def pdf_to_writer(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    soffice_convert(src, dst, dst_fmt, infilter="writer_pdf_import")
