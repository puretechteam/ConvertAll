"""Run a conversion route step by step, and write results without ever overwriting."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .detect import detect, strip_ext
from .errors import ConversionError, EngineMissingError
from .formats import MULTI_EXT
from .registry import Route, find_route

# Single-stream compressors keep the original name: notes.txt -> notes.txt.gz
STREAM_COMPRESSORS = {"gz", "bz2", "xz"}


def unique_path(path: Path) -> Path:
    """path, or 'name (1).ext', 'name (2).ext'... if it already exists."""
    if not path.exists():
        return path
    name = path.name
    ext = ""
    if not path.is_dir():
        low = name.lower()
        multi = next((m for m in MULTI_EXT if low.endswith("." + m)), None)
        ext = name[-len(multi) - 1:] if multi else path.suffix
    base = name[: len(name) - len(ext)] if ext else name
    i = 1
    while True:
        cand = path.with_name(f"{base} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1


def step_name(cur: Path, base: str, dst_fmt: str) -> str:
    if dst_fmt in STREAM_COMPRESSORS:
        return f"{cur.name}.{dst_fmt}"
    return f"{base}.{dst_fmt}"


def plan(src: str | Path, dst_fmt: str, src_fmt: str | None = None) -> Route:
    return find_route(src_fmt or detect(src), dst_fmt)


def convert(src: str | Path, dst_fmt: str, out_dir: str | Path | None = None,
            src_fmt: str | None = None) -> Path:
    """Convert src to dst_fmt. Returns the path written (a file, or a folder for multi-page output)."""
    src = Path(src).resolve()
    if not src.exists():
        raise ConversionError(f"{src} doesn't exist")
    route = plan(src, dst_fmt, src_fmt)
    if route.missing_engines:
        raise EngineMissingError(route.missing_engines)
    out = Path(out_dir).resolve() if out_dir else src.parent
    out.mkdir(parents=True, exist_ok=True)
    base = strip_ext(src)

    # a library still holding a temp file open must not fail a conversion that already succeeded
    with tempfile.TemporaryDirectory(prefix="convertall-", ignore_cleanup_errors=True) as tmp:
        cur = src
        for i, edge in enumerate(route.edges):
            step_dir = Path(tmp) / f"step{i}"
            step_dir.mkdir()
            target = step_dir / step_name(cur, base, edge.dst)
            try:
                result = edge.func(cur, target, edge.src, edge.dst) or target
            except ConversionError:
                raise
            except Exception as exc:  # library errors -> readable message
                raise ConversionError(f"{edge.src.upper()} -> {edge.dst.upper()} failed: {exc}") from exc
            if not Path(result).exists():
                raise ConversionError(f"{edge.src.upper()} -> {edge.dst.upper()} produced no output")
            cur = Path(result)
        final = unique_path(out / cur.name)
        shutil.move(str(cur), str(final))
    return final


def can_extract(fmt: str) -> bool:
    from .converters.archives import EXTRACTABLE
    return fmt in EXTRACTABLE


def extract(src: str | Path, out_dir: str | Path | None = None, src_fmt: str | None = None) -> Path:
    """Extract an archive next to it (or into out_dir). A lone top-level folder isn't double-nested."""
    from .converters.archives import extract_to
    src = Path(src).resolve()
    fmt = src_fmt or detect(src)
    if not can_extract(fmt):
        raise ConversionError(f"{src.name} isn't an archive ConvertAll can extract")
    out = Path(out_dir).resolve() if out_dir else src.parent
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".convertall-", dir=out))
    try:
        extract_to(src, tmp, fmt)
        entries = list(tmp.iterdir())
        if len(entries) == 1:
            final = unique_path(out / entries[0].name)
            shutil.move(str(entries[0]), str(final))
        else:
            final = unique_path(out / strip_ext(src))
            tmp.rename(final)
        return final
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
