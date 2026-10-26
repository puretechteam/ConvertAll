"""Compress anything, extract any archive, and repack archives into other archive types."""

import bz2
import functools
import gzip
import io
import lzma
import re
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
from ..formats import category
from ..registry import converter


class _BrotliFile(io.RawIOBase):
    """brotli compresses and decompresses chunks but has no file object; this is one."""
    OUT_LIMIT = 1 << 20  # never inflate more than this per call: a tiny .br can unpack to gigabytes

    def __init__(self, path, mode: str = "rb", quality: int = 11):
        import brotli
        super().__init__()
        self._writing = "w" in mode
        self._f = open(path, "wb" if self._writing else "rb")
        self._codec = brotli.Compressor(quality=quality) if self._writing else brotli.Decompressor()
        self._buf = bytearray()

    def readable(self) -> bool:
        return not self._writing

    def writable(self) -> bool:
        return self._writing

    def write(self, b) -> int:
        self._f.write(self._codec.process(bytes(b)))
        return len(b)

    def read(self, n: int = -1) -> bytes:
        import brotli
        want = n if n >= 0 else 1 << 62
        try:
            while len(self._buf) < want:
                if self._codec.can_accept_more_data():
                    if self._codec.is_finished():
                        break
                    chunk = self._f.read(1 << 16)
                    if not chunk:
                        raise ConversionError("The Brotli file is cut short")
                else:
                    chunk = b""
                self._buf += self._codec.process(chunk, output_buffer_limit=self.OUT_LIMIT)
        except brotli.error as exc:
            raise ConversionError(f"Not a valid Brotli file: {exc}") from exc
        out, self._buf = bytes(self._buf[:want]), self._buf[want:]
        return out

    def close(self) -> None:
        if not self.closed:
            try:
                if self._writing:
                    self._f.write(self._codec.finish())
            finally:
                self._f.close()
        super().close()


def _lz4_open(path, mode="rb"):
    import lz4.frame
    return lz4.frame.open(path, mode)


def _lzma_alone_open(path, mode="rb"):
    return lzma.open(path, mode, format=lzma.FORMAT_ALONE)  # .lzma is the old LZMA-alone format


class _ZReader(io.RawIOBase):
    """Unix compress (.Z) as a readable file, decoded by packport chunk by chunk."""

    def __init__(self, path):
        import packport
        super().__init__()
        self._f = open(path, "rb")
        self._codec = packport.ZDecompressor()
        self._buf = bytearray()
        self._done = False

    def readable(self) -> bool:
        return True

    def read(self, n: int = -1) -> bytes:
        import packport
        want = n if n >= 0 else 1 << 62
        try:
            while len(self._buf) < want and not self._done:
                chunk = self._f.read(1 << 16)
                if chunk:
                    self._buf += self._codec.decompress(chunk)
                else:
                    self._buf += self._codec.flush()
                    self._done = True
        except packport.PackportError as exc:
            raise ConversionError(f"Not a valid .Z file: {exc}") from exc
        out, self._buf = bytes(self._buf[:want]), self._buf[want:]
        return out

    def close(self) -> None:
        if not self.closed:
            self._f.close()
        super().close()


def _z_open(path, mode="rb"):
    if "w" in mode:
        import packport
        return packport.ZWriter(path)
    return _ZReader(path)


# Single-file compressors: name -> open(path, mode)
STREAM = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open, "zst": zstd.open, "lz4": _lz4_open,
          "br": _BrotliFile, "lzma": _lzma_alone_open, "z": _z_open}
TAR_MODE = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}
TAR_STREAM = {"tar.zst": "zst", "tar.lz4": "lz4"}  # tar inside a compressor tarfile doesn't know
# Zip files under another name (apps, add-ons, packages): extracted and repacked as a ZIP
ZIP_BASED = {"zipx", "jar", "war", "ear", "apk", "aab", "xpi", "vsix", "nupkg", "whl", "appx", "msix",
             "ipa", "crx"}

NATIVE_EXTRACT = ({"zip", "cbz", "7z", "cb7", "tar", "cbt", "cpio"} | set(TAR_MODE) | set(TAR_STREAM)
                  | set(STREAM) | ZIP_BASED)
SEVENZIP_EXTRACT = {"rar", "cbr", "iso", "cab", "arj", "lzh", "dmg", "wim", "rpm", "deb", "msi", "msp", "vhd", "vhdx", "vmdk", "vdi", "qcow2", "img", "squashfs", "udf",
                    "apfs", "hfs", "xar", "pkg", "ar", "001", "r00", "chm", "lit"}
EXTRACTABLE = NATIVE_EXTRACT | SEVENZIP_EXTRACT

COMPRESS_OUT = {"zip", "7z", "iso", "rar", "cpio"} | set(TAR_MODE) | set(TAR_STREAM) | set(STREAM)
FOLDER_OUT = COMPRESS_OUT - set(STREAM)
SEVENZIP_OUT = {"wim"}  # written by 7-Zip itself
# A comic is an archive of page images; this is the container each one is meant to be
COMIC_CONTAINER = {"cbz": "zip", "cbr": "rar", "cb7": "7z", "cbt": "tar"}
CONTAINER = COMIC_CONTAINER | {f: "zip" for f in ZIP_BASED}


def compress(src: Path, dst: Path, fmt: str) -> None:
    """Pack a file or folder (folder name kept as the top-level entry; comics keep pages at the top)."""
    import py7zr
    arcname = src.name
    if fmt in COMICS:
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
    elif fmt in TAR_STREAM:
        with STREAM[TAR_STREAM[fmt]](dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            _tar_add(tf, src, arcname)
    elif fmt in STREAM:
        if src.is_dir():
            raise ConversionError(f"{fmt} holds a single file; use zip, 7z or tar for folders")
        opener = STREAM[fmt]
        if fmt == "br" and src.stat().st_size > 64 << 20:  # quality 11 runs at ~1 MB/s
            opener = functools.partial(_BrotliFile, quality=9)
        with src.open("rb") as fin, opener(dst, "wb") as fout:
            shutil.copyfileobj(fin, fout, 1 << 20)
    elif fmt == "iso":
        _write_iso(src, dst)
    elif fmt == "rar":
        _write_rar(src, dst, arcname)
    elif fmt == "cpio":
        import packport
        _packport(packport.write_cpio, dst, src, arcname)
    elif fmt in SEVENZIP_OUT:
        _sevenzip_add(src, dst, fmt)
    else:
        raise ConversionError(f"Can't create {fmt}")


def _tar_add(tf: tarfile.TarFile, src: Path, arcname: str) -> None:
    if arcname:
        tf.add(src, arcname)
    else:
        for p in sorted(src.iterdir()):
            tf.add(p, p.name)


def _packport(write, dst: Path, src: Path, arcname: str) -> None:
    import packport
    try:
        write(dst, packport.tree(src) if src.is_dir() and not arcname else [src])
    except packport.PackportError as exc:
        raise ConversionError(str(exc)) from None


def _write_rar(src: Path, dst: Path, arcname: str) -> None:
    """WinRAR's own Rar.exe when it's installed (real compression); otherwise packport, which
    writes stored (uncompressed) RAR 4. RAR's compression method is proprietary."""
    rar = engines.find("winrar")
    if rar:
        target = str(src / "*") if src.is_dir() and not arcname else str(src)
        engines.run([rar, "a", "-r", "-ep1", "-idq", "-y", "-m5", str(dst), target], timeout=3600)
        return
    import packport
    _packport(packport.write_rar, dst, src, arcname)


def _sevenzip_add(src: Path, dst: Path, fmt: str) -> None:
    exe = engines.require("7zip")
    engines.run([exe, "a", f"-t{fmt}", "-bd", "-y", str(dst), str(src)])


# ---- ISO 9660 (+ Joliet for Windows, Rock Ridge for Linux/macOS: both keep the real names)

def _iso_name(name: str, used: set[str], is_dir: bool) -> str:
    """A unique ISO 9660 level 3 name: A-Z 0-9 _, 30 characters, one dot for files."""
    stem, _, ext = name.rpartition(".") if not is_dir and "." in name.strip(".") else (name, "", "")
    clean = lambda s: re.sub(r"[^A-Z0-9_]", "_", s.upper())  # noqa: E731
    stem, ext = clean(stem) or "_", clean(ext)[:3]
    room = 31 if is_dir else 30 - len(ext) - 1
    cand, i = stem[:room], 1
    while cand in used:
        tag = f"_{i}"
        cand, i = stem[:room - len(tag)] + tag, i + 1
    used.add(cand)
    return cand if is_dir else f"{cand}.{ext}"


def _joliet_name(name: str, used: set[str]) -> str:
    """Joliet allows 64 characters (pycdlib counts them in UTF-8 bytes); long names keep their
    extension and stay unique."""
    def fit(s: str, room: int) -> str:
        while len(s.encode()) > room:
            s = s[:-1]
        return s
    stem, ext = name.rsplit(".", 1) if "." in name.strip(".") else (name, "")
    ext = fit(f".{ext}", 16) if ext else ""
    cand, i = fit(name, 64) if len(name.encode()) <= 64 else fit(stem, 64 - len(ext.encode())) + ext, 1
    while cand.lower() in used:
        tag = f"~{i}"
        cand, i = fit(stem, 64 - len(ext.encode()) - len(tag)) + tag + ext, i + 1
    used.add(cand.lower())
    return cand


def _write_iso(src: Path, dst: Path) -> None:
    import pycdlib
    iso = pycdlib.PyCdlib()
    vol = re.sub(r"[^A-Z0-9_]", "_", strip_ext(src).upper())[:32] or "CDROM"
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident=vol)
    try:
        def add(path: Path, iso_dir: str, joliet_dir: str, depth: int) -> None:
            used_iso: set[str] = set()
            used_joliet: set[str] = set()
            for p in sorted(path.iterdir()) if path.is_dir() else [path]:
                is_dir = p.is_dir()
                iso_path = f"{iso_dir}/{_iso_name(p.name, used_iso, is_dir)}"
                joliet_path = f"{joliet_dir}/{_joliet_name(p.name, used_joliet)}"
                if is_dir:
                    if depth >= 7:  # ISO 9660 stops at 8 levels
                        raise ConversionError(f"{p.name} is nested too deep for an ISO; use zip or 7z")
                    iso.add_directory(iso_path, rr_name=p.name, joliet_path=joliet_path)
                    add(p, iso_path, joliet_path, depth + 1)
                else:
                    iso.add_file(str(p), iso_path + ";1", rr_name=p.name, joliet_path=joliet_path)
        add(src, "", "", 0)
        iso.write(str(dst))
    finally:
        iso.close()


# ---- extraction

def _sevenzip_extract(src: Path, dest: Path) -> None:
    exe = engines.require("7zip")
    engines.run([exe, "x", "-y", "-bd", f"-o{dest}", str(src)])


def extract_to(src: Path, dest: Path, fmt: str) -> None:
    import py7zr
    dest.mkdir(parents=True, exist_ok=True)
    fmt = CONTAINER.get(fmt, fmt)
    if fmt in SEVENZIP_EXTRACT:
        return _sevenzip_extract(src, dest)
    try:
        if fmt == "zip":
            with zipfile.ZipFile(src) as zf:
                zf.extractall(dest)  # zipfile strips ".." and absolute paths
        elif fmt == "7z":
            with py7zr.SevenZipFile(src) as z:
                z.extractall(dest)
        elif fmt in TAR_STREAM:
            with STREAM[TAR_STREAM[fmt]](src, "rb") as f, tarfile.open(fileobj=f, mode="r|") as tf:
                tf.extractall(dest, filter="data")
        elif fmt.startswith("tar"):
            with tarfile.open(src) as tf:
                tf.extractall(dest, filter="data")
        elif fmt in STREAM:
            with STREAM[fmt](src, "rb") as fin, (dest / strip_ext(src)).open("wb") as fout:
                shutil.copyfileobj(fin, fout, 1 << 20)
        elif fmt == "cpio":
            _extract_cpio(src, dest)
        else:
            raise ConversionError(f"Can't extract {fmt}")
    except (NotImplementedError, ConversionError, py7zr.exceptions.UnsupportedCompressionMethodError,
            py7zr.exceptions.Bad7zFile, zipfile.BadZipFile, tarfile.TarError, zstd.ZstdError,
            lzma.LZMAError, EOFError, RuntimeError) as exc:
        # Unusual methods (Deflate64, PPMd, BCJ2...) -> let 7-Zip try if it's there
        if not engines.available("7zip"):
            raise ConversionError(f"Couldn't extract {src.name}: {exc}") from exc
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        _sevenzip_extract(src, dest)


def _extract_cpio(src: Path, dest: Path) -> None:
    import stat

    import packport
    try:
        members = packport.read_cpio(src)
    except packport.PackportError as exc:
        raise ConversionError(str(exc)) from None  # old binary/odc CPIO: 7-Zip takes over
    root = dest.resolve()
    for m in members:
        target = (dest / m.name).resolve()
        if root not in target.parents or stat.S_ISLNK(m.mode):
            continue  # nothing outside the folder, no links
        if m.is_dir:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(m.data)


@converter(inputs={"*"}, outputs=COMPRESS_OUT, terminal=True)
@converter(inputs={"folder"}, outputs=FOLDER_OUT, terminal=True)
def compress_convert(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    compress(src, dst, dst_fmt)


converter(inputs={"*", "folder"}, outputs=SEVENZIP_OUT, engine="7zip", terminal=True)(compress_convert)


def repack(src: Path, dst: Path, src_fmt: str, dst_fmt: str) -> None:
    work = dst.parent / "_extracted" / strip_ext(src)
    extract_to(src, work, src_fmt)
    entries = list(work.iterdir())
    root = entries[0] if len(entries) == 1 else work
    compress(root, dst, dst_fmt)


# Only real archives repack; a .chm or .lit (also readable by 7-Zip) is converted as an ebook
_NATIVE_ARCHIVES = {f for f in NATIVE_EXTRACT - COMICS - set(STREAM) if category(f) == "Archive"}
_SEVENZIP_ARCHIVES = {f for f in SEVENZIP_EXTRACT - COMICS if category(f) == "Archive"}
converter(inputs=_NATIVE_ARCHIVES, outputs=FOLDER_OUT, terminal=True)(repack)
converter(inputs=_NATIVE_ARCHIVES | _SEVENZIP_ARCHIVES, outputs=SEVENZIP_OUT, engine="7zip",
          terminal=True)(repack)
converter(inputs=set(STREAM), outputs=COMPRESS_OUT, terminal=True)(repack)
converter(inputs=_SEVENZIP_ARCHIVES, outputs=FOLDER_OUT, engine="7zip", terminal=True)(repack)
# comic -> comic keeps the pages, just in another container
converter(inputs=COMICS - {"cbr"}, outputs=COMICS)(repack)
converter(inputs={"cbr"}, outputs=COMICS - {"cbr"}, engine="7zip")(repack)
