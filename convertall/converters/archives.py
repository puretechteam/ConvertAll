"""Compress anything, extract any archive, and repack archives into other archive types."""

import bz2
import gzip
import lzma
import shutil
import tarfile
import zipfile
from pathlib import Path


try:
    from compression import zstd  # Python 3.14+
except ImportError:
    from backports import zstd

from .. import engines
from ..detect import COMICS, strip_ext
from ..errors import ConversionError
from ..registry import converter

NATIVE_EXTRACT = {"zip", "cbz", "7z", "cb7", "tar", "cbt", "tar.gz", "tar.bz2", "tar.xz", "tar.zst",
                  "gz", "bz2", "xz", "zst"}
SEVENZIP_EXTRACT = {"rar", "cbr", "iso", "cab", "arj", "lzh", "dmg", "wim", "cpio", "rpm", "deb",
                    "z", "lzma", "msi", "vhd", "vhdx"}
EXTRACTABLE = NATIVE_EXTRACT | SEVENZIP_EXTRACT

STREAM = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open, "zst": zstd.open}
TAR_MODE = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}
COMPRESS_OUT = {"zip", "7z", "tar.zst"} | set(TAR_MODE) | set(STREAM)
FOLDER_OUT = COMPRESS_OUT - set(STREAM)
# A comic is an archive of page images; this is the container each one is meant to be
COMIC_CONTAINER = {"cbz": "zip", "cbr": "rar", "cb7": "7z", "cbt": "tar"}


def compress(src: Path, dst: Path, fmt: str) -> None:
    """Pack a file or folder (folder name kept as the top-level entry; comics keep pages at the top)."""
    import py7zr
    arcname = src.name
    if fmt in COMICS:
        if fmt == "cbr":
            raise ConversionError("RAR can't be created with free tools; use CBZ instead")
        fmt = COMIC_CONTAINER[fmt]
        if src.is_dir():
            arcname = ""
    if fmt == "zip":
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            if src.is_dir():
                if arcname:
                    zf.write(src, arcname)
                for p in sorted(src.rglob("*")):
                    zf.write(p, Path(arcname) / p.relative_to(src))
            else:
                zf.write(src, arcname)
    elif fmt == "7z":
        with py7zr.SevenZipFile(dst, "w") as z:
            if src.is_dir():
                for p, name in ([(src, arcname)] if arcname else [(p, p.name) for p in sorted(src.iterdir())]):
                    z.writeall(p, name)
            else:
                z.write(src, arcname)
    elif fmt in TAR_MODE:
        with tarfile.open(dst, TAR_MODE[fmt]) as tf:
            _tar_add(tf, src, arcname)
    elif fmt == "tar.zst":
        with zstd.open(dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            _tar_add(tf, src, arcname)
    elif fmt in STREAM:
        if src.is_dir():
            raise ConversionError(f"{fmt} holds a single file; use zip, 7z or tar.{fmt} for folders")
        with src.open("rb") as fin, STREAM[fmt](dst, "wb") as fout:
            shutil.copyfileobj(fin, fout, 1 << 20)
    else:
        raise ConversionError(f"Can't create {fmt}")


def _tar_add(tf: tarfile.TarFile, src: Path, arcname: str) -> None:
    if arcname:
        tf.add(src, arcname)
    else:
        for p in sorted(src.iterdir()):
            tf.add(p, p.name)


def _sevenzip_extract(src: Path, dest: Path) -> None:
    exe = engines.require("7zip")
    engines.run([exe, "x", "-y", "-bd", f"-o{dest}", str(src)])


def extract_to(src: Path, dest: Path, fmt: str) -> None:
    import py7zr
    dest.mkdir(parents=True, exist_ok=True)
    fmt = COMIC_CONTAINER.get(fmt, fmt)
    if fmt in SEVENZIP_EXTRACT:
        return _sevenzip_extract(src, dest)
    try:
        if fmt == "zip":
            with zipfile.ZipFile(src) as zf:
                zf.extractall(dest)  # zipfile strips ".." and absolute paths
        elif fmt == "7z":
            with py7zr.SevenZipFile(src) as z:
                z.extractall(dest)
        elif fmt == "tar.zst":
            with zstd.open(src, "rb") as f, tarfile.open(fileobj=f, mode="r|") as tf:
                tf.extractall(dest, filter="data")
        elif fmt.startswith("tar"):
            with tarfile.open(src) as tf:
                tf.extractall(dest, filter="data")
        elif fmt in STREAM:
            with STREAM[fmt](src, "rb") as fin, (dest / strip_ext(src)).open("wb") as fout:
                shutil.copyfileobj(fin, fout, 1 << 20)
        else:
            raise ConversionError(f"Can't extract {fmt}")
    except (NotImplementedError, py7zr.exceptions.UnsupportedCompressionMethodError,
            py7zr.exceptions.Bad7zFile, zipfile.BadZipFile, tarfile.TarError, zstd.ZstdError) as exc:
        # Unusual methods (Deflate64, PPMd, BCJ2...) -> let 7-Zip try if it's there
        if not engines.available("7zip"):
            raise ConversionError(f"Couldn't extract {src.name}: {exc}") from exc
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        _sevenzip_extract(src, dest)


@converter(inputs={"*"}, outputs=COMPRESS_OUT, terminal=True)
@converter(inputs={"folder"}, outputs=FOLDER_OUT, terminal=True)
def compress_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    compress(src, dst, dst_fmt)


def repack(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    work = dst.parent / "_extracted" / strip_ext(src)
    extract_to(src, work, src_fmt)
    entries = list(work.iterdir())
    root = entries[0] if len(entries) == 1 else work
    compress(root, dst, dst_fmt)


converter(inputs=NATIVE_EXTRACT - COMICS - set(STREAM), outputs=FOLDER_OUT, terminal=True)(repack)
converter(inputs=set(STREAM), outputs=COMPRESS_OUT, terminal=True)(repack)
converter(inputs=SEVENZIP_EXTRACT - COMICS, outputs=FOLDER_OUT, engine="7zip", terminal=True)(repack)
# comic -> comic keeps the pages, just in another container
converter(inputs=COMICS - {"cbr"}, outputs=COMICS - {"cbr"})(repack)
converter(inputs={"cbr"}, outputs=COMICS - {"cbr"}, engine="7zip")(repack)
