"""External conversion engines: find them, run them, install them with winget."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from .errors import ConversionError

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Engine:
    key: str
    name: str
    exe: str
    winget_id: str
    size: str
    paths: tuple[str, ...] = ()


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
    return [(e, find(e.key)) for e in ENGINES.values()]


def install(key: str, log: Callable[[str], None] | None = None) -> bool:
    """Install an engine with winget. Returns True if it's usable afterwards."""
    eng = ENGINES[key]
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
