"""Keep what comes out of an archive inside its folder: entry names that are safe to write on
Windows, a disk-space budget that stops archive bombs, and a sweep that removes links."""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
from pathlib import Path

from . import cancel
from .errors import ConversionError

# Names Windows keeps for devices, with or without an extension ("CON", "nul.txt", "COM¹")
_DEVICES = ({"con", "prn", "aux", "nul", "conin$", "conout$", "clock$"}
            | {f"{d}{n}" for d in ("com", "lpt") for n in "123456789¹²³"})
_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"|?*]')  # ':' also opens alternate data streams
FOLD_CASE = os.name == "nt" or sys.platform == "darwin"  # "A.txt" and "a.txt" are one file
MARGIN = 256 << 20  # leave this much of the disk free


class Refused(ConversionError):
    """An archive ConvertAll won't extract (password, disk space, lying sizes). Final: another
    extractor wouldn't do better."""


def safe_name(name: str) -> str | None:
    """An archive entry name as a relative "a/b/c" path that stays inside the extraction folder
    and can be created on Windows, or None when it tries to climb out (".."). Leading slashes and
    drive letters are dropped, as unzip and tar do. Characters Windows doesn't allow become "_",
    and device names get a "_" in front, the way 7-Zip renames them, so every extractor gives the
    same names."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if parts and re.fullmatch(r"[A-Za-z]:", parts[0]):
        parts = parts[1:]
    if not parts or ".." in parts:
        return None
    clean = []
    for p in parts:
        p = _BAD_CHARS.sub("_", p)
        if p.rstrip(". ").split(".", 1)[0].rstrip(" ").lower() in _DEVICES:
            p = "_" + p
        if p[-1] in ". ":
            p = p.rstrip(". ") + "_"  # Windows drops a trailing dot or space
        clean.append(p)
    return "/".join(clean)


class Namer:
    """Hands out each entry's place in the folder. Names that clash (twice in the archive, or
    differing only in case on Windows) get " (1)", " (2)"... instead of overwriting each other."""

    def __init__(self) -> None:
        self.files: set[str] = set()
        self.dirs: set[str] = set()
        self.renamed = 0

    def _key(self, rel: str) -> str:
        return rel.lower() if FOLD_CASE else rel

    def claim(self, rel: str, is_dir: bool = False) -> str | None:
        """The name to write rel under, or None when a file already sits where its folder must go."""
        parts = rel.split("/")
        for i in range(1, len(parts)):
            if self._key("/".join(parts[:i])) in self.files:
                return None
        for i in range(1, len(parts)):
            self.dirs.add(self._key("/".join(parts[:i])))
        key = self._key(rel)
        if is_dir:
            if key in self.files:
                return None
            self.dirs.add(key)
            return rel
        if key in self.files or key in self.dirs:
            head, _, leaf = rel.rpartition("/")
            stem, dot, ext = leaf.rpartition(".") if "." in leaf.strip(".") else (leaf, "", "")
            n = 1
            while True:
                rel = f"{head}/" * bool(head) + f"{stem} ({n}){dot}{ext}"
                key = self._key(rel)
                if key not in self.files and key not in self.dirs:
                    break
                n += 1
            self.renamed += 1
        self.files.add(key)
        return rel


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class Budget:
    """Disk space for one extraction: everything written counts against the space that was free
    when it started (less a margin), so an archive bomb stops with a message instead of filling
    the drive."""

    def __init__(self, dest: Path, name: str):
        self.free = shutil.disk_usage(dest).free
        self.left = self.free - MARGIN
        self.name = name

    def _full(self, need: int) -> Refused:
        return Refused(f"{self.name} unpacks to {_size(need)}, more than the {_size(self.free)} "
                       f"free on that drive")

    def check(self, total: int) -> None:
        """Refuse up front when the archive's own sizes already don't fit."""
        if total > self.left:
            raise self._full(total)

    def take(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise self._full(self.free - MARGIN - self.left)


def copy_capped(fin, target: Path, limit: int | None, budget: Budget, label: str) -> None:
    """Copy one entry to target, stopping if it holds more than the archive said it would."""
    written = 0
    with open(target, "xb") as fout:  # x: a name that's somehow taken is never overwritten
        while chunk := fin.read(1 << 20):
            cancel.check()  # 1 MB at a time: a big archive stops within moments
            written += len(chunk)
            if limit is not None and written > limit:
                raise Refused(f"{label} holds more data than the archive says (it's damaged or "
                              f"made to fill the disk)")
            budget.take(len(chunk))
            fout.write(chunk)


INNER_LIMIT = 512 << 20  # one compressed file inside another (.svgz, .kmz): more is a bomb


def read_capped(fin, label: str, limit: int | None = None) -> bytes:
    """All of fin, refusing once it passes limit (INNER_LIMIT), so a small file that unpacks to
    gigabytes stops with a message instead of filling memory."""
    limit = INNER_LIMIT if limit is None else limit
    data = fin.read(limit + 1)
    if len(data) > limit:
        raise Refused(f"{label} unpacks to more than {_size(limit)} (it's damaged or made to fill memory)")
    return data


def local_file(base: Path, link: str) -> Path | None:
    """A file a document links to (a picture, an included file), when it's in the document's own
    folder or one level up (Text/ next to Images/). Absolute, network and further-out paths, and
    links with a scheme (http:, file:), give None."""
    from urllib.parse import unquote
    link = unquote(link.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
    if not link or link.startswith("/") or re.match(r"[A-Za-z][\w+.-]*:", link):
        return None
    base = base.resolve()
    path = (base / link).resolve()
    if not path.is_relative_to(base.parent) or not path.is_file():
        return None
    return path


def _is_link(entry: os.DirEntry) -> bool:
    st = entry.stat(follow_symlinks=False)
    return (entry.is_symlink() or stat.S_ISLNK(st.st_mode)
            or bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)))


def sweep(dest: Path) -> int:
    """Remove every symbolic link, junction, other reparse point or special file under dest,
    without following any of them. Returns how many were removed."""
    removed, stack = 0, [str(dest)]
    while stack:
        with os.scandir(stack.pop()) as it:
            for entry in it:
                if _is_link(entry):
                    try:
                        os.unlink(entry.path)
                    except (IsADirectoryError, PermissionError):
                        os.rmdir(entry.path)  # a junction or directory link: removes the link only
                    removed += 1
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
    return removed
