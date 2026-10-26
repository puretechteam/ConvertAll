"""External conversion engines: find them, run them, install them with winget (or, for the one
engine winget doesn't carry, download its official release)."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .errors import ConversionError

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Engine:
    key: str
    name: str
    exe: str
    winget_id: str  # "" when winget doesn't have it (see DOWNLOADERS)
    size: str
    paths: tuple[str, ...] = ()
    hidden: bool = False  # used when present, never offered (paid software)


# Engines ConvertAll unpacks into its own folder: per user, no installer, no admin prompt
ENGINE_HOME = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ConvertAll", "engines")


ENGINES: dict[str, Engine] = {e.key: e for e in [
    Engine("ffmpeg", "FFmpeg", "ffmpeg", "Gyan.FFmpeg", "~200 MB", (
        r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe",
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe",
        r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe",
    )),
    Engine("7zip", "7-Zip", "7z", "7zip.7zip", "~6 MB", (
        r"%ProgramFiles%\7-Zip\7z.exe",
        r"%ProgramFiles(x86)%\7-Zip\7z.exe",
    )),
    Engine("libreoffice", "LibreOffice", "soffice", "TheDocumentFoundation.LibreOffice", "~350 MB", (
        r"%ProgramFiles%\LibreOffice\program\soffice.exe",
        r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe",
    )),
    Engine("calibre", "Calibre", "ebook-convert", "calibre.calibre", "~400 MB", (
        r"%ProgramFiles%\Calibre2\ebook-convert.exe",
        r"%ProgramFiles(x86)%\Calibre2\ebook-convert.exe",
    )),
    Engine("imagemagick", "ImageMagick", "magick", "ImageMagick.ImageMagick", "~100 MB", (
        r"%ProgramFiles%\ImageMagick-*\magick.exe",
    )),
    Engine("blender", "Blender", "blender", "BlenderFoundation.Blender", "~400 MB", (
        r"%ProgramFiles%\Blender Foundation\Blender*\blender.exe",
    )),
    Engine("pandoc", "Pandoc", "pandoc", "JohnMacFarlane.Pandoc", "~200 MB", (
        r"%LOCALAPPDATA%\Pandoc\pandoc.exe",
        r"%ProgramFiles%\Pandoc\pandoc.exe",
    )),
    Engine("djvulibre", "DjVuLibre", "ddjvu", "DjVuLibre.DjView", "~30 MB", (
        r"%ProgramFiles(x86)%\DjVuLibre\ddjvu.exe",
        r"%ProgramFiles%\DjVuLibre\ddjvu.exe",
    )),
    Engine("ghostscript", "Ghostscript", "gswin64c", "", "~65 MB", (
        os.path.join(ENGINE_HOME, "ghostscript", "bin", "gswin64c.exe"),
        r"%ProgramFiles%\gs\gs*\bin\gswin64c.exe",
    )),
    Engine("winrar", "WinRAR", "rar", "", "", (
        r"%ProgramFiles%\WinRAR\Rar.exe",
        r"%ProgramFiles(x86)%\WinRAR\Rar.exe",
    ), hidden=True),
]}

_cache: dict[str, str | None] = {}


def _registry_path() -> str:
    """PATH as stored in the registry, which picks up installs made after we started."""
    if sys.platform != "win32":
        return ""
    import winreg
    parts = []
    for root, sub in ((winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(root, sub) as key:
                parts.append(os.path.expandvars(winreg.QueryValueEx(key, "Path")[0]))
        except OSError:
            pass
    return os.pathsep.join(parts)


def find(key: str) -> str | None:
    if key in _cache:
        return _cache[key]
    eng = ENGINES[key]
    found = shutil.which(eng.exe) or shutil.which(eng.exe, path=_registry_path())
    if not found:
        for pattern in eng.paths:
            hits = sorted(glob.glob(os.path.expandvars(pattern)), reverse=True)
            if hits:
                found = hits[0]
                break
    _cache[key] = found
    return found


def available(key: str) -> bool:
    return find(key) is not None


def require(key: str) -> str:
    exe = find(key)
    if not exe:
        from .errors import EngineMissingError
        raise EngineMissingError([key])
    return exe


def refresh() -> None:
    _cache.clear()


def status() -> list[tuple[Engine, str | None]]:
    return [(e, find(e.key)) for e in ENGINES.values() if not e.hidden]


def installable(key: str) -> bool:
    return bool(ENGINES[key].winget_id) or key in DOWNLOADERS


# ---- Ghostscript: Artifex publishes it on GitHub, not winget

GS_RELEASES = "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases/latest"
GS_KNOWN = ("https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/gs10080w64.exe",
            "52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50")


def _latest_ghostscript() -> tuple[str, str]:
    """(url, sha256) of the newest 64-bit Windows build; the known-good one if GitHub can't say."""
    try:
        with urllib.request.urlopen(GS_RELEASES, timeout=20) as r:
            release = json.load(r)
        asset = next(a for a in release["assets"] if a["name"].endswith("w64.exe"))
        algo, digest = asset["digest"].split(":", 1)
        if algo == "sha256":
            return asset["browser_download_url"], digest
    except Exception:
        pass
    return GS_KNOWN


def _download_ghostscript(log: Callable[[str], None] | None) -> None:
    """Download the official release, check its SHA-256, and unpack only its programs (bin:
    gswin64c.exe and the DLL, which has fonts and startup files built in)."""
    url, sha256 = _latest_ghostscript()
    if not available("7zip"):
        install("7zip", log)
    with tempfile.TemporaryDirectory(prefix="convertall-gs-") as tmp:
        setup = os.path.join(tmp, "gs.exe")
        if log:
            log(f"Downloading {url.rsplit('/', 1)[-1]}")
        h = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as r, open(setup, "wb") as f:
            while chunk := r.read(1 << 20):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != sha256:
            raise ConversionError("The Ghostscript download didn't match its published checksum")
        dest = os.path.join(ENGINE_HOME, "ghostscript")
        shutil.rmtree(dest, ignore_errors=True)
        run([require("7zip"), "x", "-y", "-bd", f"-o{dest}", setup, "bin"])


DOWNLOADERS: dict[str, Callable[[Callable[[str], None] | None], None]] = {
    "ghostscript": _download_ghostscript,
}


def install(key: str, log: Callable[[str], None] | None = None) -> bool:
    """Install an engine with winget. Returns True if it's usable afterwards."""
    eng = ENGINES[key]
    if key in DOWNLOADERS:
        try:
            DOWNLOADERS[key](log)
        except OSError as exc:
            raise ConversionError(f"Couldn't download {eng.name}: {exc}") from exc
        refresh()
        return available(key)
    if not eng.winget_id:
        raise ConversionError(f"{eng.name} can't be installed from ConvertAll")
    if not shutil.which("winget"):
        raise ConversionError("winget isn't available; install App Installer from the Microsoft Store")
    cmd = ["winget", "install", "-e", "--id", eng.winget_id, "--silent",
           "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    assert proc.stdout
    for line in proc.stdout:
        line = line.strip().split("\r")[-1].strip()
        if line and log:
            log(line)
    proc.wait()
    refresh()
    return available(key)


def run(args: list[str], timeout: float | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run an engine command, raising ConversionError with the tail of its output on failure."""
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NO_WINDOW, timeout=timeout, cwd=cwd)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ConversionError("\n".join(msg[-6:]) or f"{args[0]} failed ({proc.returncode})")
    return proc
