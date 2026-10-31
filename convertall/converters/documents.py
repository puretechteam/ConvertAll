"""Office documents via headless LibreOffice."""

import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from .. import cancel, engines
from ..errors import ConversionError
from ..losses import loss
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


def _profile() -> Path:
    """A private LibreOffice profile so conversions work even while LibreOffice is open."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ConvertAll" / "libreoffice-profile"
    base.mkdir(parents=True, exist_ok=True)
    return base


LOCK_WAIT_S = 900  # longer than one conversion may take (600 s): past it, the other one is stuck


@contextmanager
def _one_at_a_time(profile: Path, limit: float = LOCK_WAIT_S):
    """One LibreOffice per profile: a second one started on it while the first runs fails (1),
    so conversions in other ConvertAll processes wait for a lock beside the profile. The wait
    stops when the conversion is cancelled, and after limit seconds."""
    deadline = time.monotonic() + limit
    with open(profile.parent / "libreoffice-profile.lock", "a+b") as f:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                cancel.check()
                if time.monotonic() > deadline:
                    raise ConversionError("LibreOffice is still busy with another conversion; "
                                          "try again when it has finished") from None
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            # flock is released when the file closes


def soffice_convert(src: Path, dst: Path, dst_fmt: str, infilter: str | None = None) -> None:
    outdir = dst.parent / "_lo"
    outdir.mkdir(exist_ok=True)
    profile = _profile()
    cmd = [_soffice(), "--headless", "--norestore", "--nolockcheck", "--nodefault",
           f"-env:UserInstallation={profile.as_uri()}"]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    cmd += ["--convert-to", FILTERS.get(dst_fmt, dst_fmt), "--outdir", str(outdir), str(src)]
    with _one_at_a_time(profile):
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


_PDF_REBUILT = [loss("The PDF is rebuilt as editable text: the layout may shift", weight=0)]


# LibreOffice opens a PDF as positioned text boxes. Pandoc reads those from DOCX but skips them in
# ODT, so an ODT made from a PDF is an end result: routes onward (to Markdown, LaTeX...) take DOCX.
@converter(inputs={"pdf"}, outputs={"docx"}, engine="libreoffice", cost=2, first_only=True,
           notes=lambda s, d, o: _PDF_REBUILT)
@converter(inputs={"pdf"}, outputs={"odt"}, engine="libreoffice", cost=2, terminal=True,
           notes=lambda s, d, o: _PDF_REBUILT)
def pdf_to_writer(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    soffice_convert(src, dst, dst_fmt, infilter="writer_pdf_import")
