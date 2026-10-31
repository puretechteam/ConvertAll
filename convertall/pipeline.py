"""Run a conversion route step by step, and write results without ever overwriting."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from . import assurance, cancel, registry
from .assurance import Report
from .detect import detect, mislabelled, strip_ext
from .errors import ConversionError, EngineMissingError
from .formats import MULTI_EXT, category
from .options import clean as clean_options
from .registry import Route, find_route

# Single-stream compressors keep the original name: notes.txt -> notes.txt.gz
STREAM_COMPRESSORS = {"gz", "bz2", "xz", "zst", "lz4", "br", "lzma", "z"}


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
        return f"{cur.name}.{'Z' if dst_fmt == 'z' else dst_fmt}"  # Unix compress is always .Z
    return f"{base}.{dst_fmt}"


def plan(src: str | Path, dst_fmt: str, src_fmt: str | None = None, options: dict | None = None) -> Route:
    return find_route(src_fmt or detect(src), dst_fmt, options=options)


def convert(src: str | Path, dst_fmt: str, out_dir: str | Path | None = None,
            src_fmt: str | None = None, report: Report | None = None, options: dict | None = None) -> Path:
    """Convert src to dst_fmt. Returns the path written (a file, or a folder for multi-page output).

    options: settings for the steps that take them (options.py); unset ones keep each format's
    defaults. report, when given, is filled in: the route, what it can't keep, and the checks
    made on the result (assurance.py). Checking never fails a conversion: a result that doesn't
    match is kept, and its report says what differs."""
    src = Path(src).resolve()
    if not src.exists():
        raise ConversionError(f"{src} doesn't exist")
    try:
        options = clean_options(options or {})
    except ValueError as exc:
        raise ConversionError(str(exc)) from None
    relabel = None if src_fmt else mislabelled(src)
    src_fmt = src_fmt or detect(src)
    if relabel and src_fmt == dst_fmt:
        raise ConversionError(f"{src.name} is a {dst_fmt.upper()} already: only its name says "
                              f"{src.suffix.lower()} (rename it to keep it as it is)")
    # what the check reads of the source is handed to the step that reads it again (registry.keep)
    with registry.sharing():
        before = assurance.measure(src, src_fmt) if report is not None else None
        held = assurance.features(before, src_fmt) if before is not None else None
        route = planned = find_route(src_fmt, dst_fmt, options=options)
        if held is not None:  # what this very file has can make another route keep more of it
            route = find_route(src_fmt, dst_fmt, held, options)
            if route.missing_engines and not planned.missing_engines:
                route = planned
        if route.missing_engines:
            raise EngineMissingError(route.missing_engines)
        out = Path(out_dir).resolve() if out_dir else src.parent
        out.mkdir(parents=True, exist_ok=True)
        base = strip_ext(src)
        found: list[str] = []

        # a library still holding a temp file open must not fail a conversion that already succeeded
        with tempfile.TemporaryDirectory(prefix="convertall-", ignore_cleanup_errors=True) as tmp:
            cur = src
            tokens = registry.running(options, found)
            try:
                for i, edge in enumerate(route.edges):
                    cancel.check()
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
            finally:
                registry.reset(tokens)
            cancel.check()  # stopped during the last step: write nothing
            final = unique_path(out / cur.name)
            shutil.move(str(cur), str(final))
    if report is not None:
        _fill(report, src, src_fmt, relabel, route, held, options, found, before, final)
    return final


def _fill(report: Report, src: Path, src_fmt: str, relabel: str | None, route: Route, held, options: dict,
          found: list[str], before: dict | None, final: Path) -> None:
    lost = route.explain(held, options)
    report.source, report.source_format, report.target = str(src), src_fmt, route.dst
    report.detected = "content" if relabel else "extension"
    report.output = str(final)
    report.settings = {k: v for k, v in options.items() if k in route.settings}
    report.steps = [{"from": e.src, "to": e.dst, "tool": assurance.tool(e)} for e in route.edges]
    try:
        after = assurance.inspect(final, route.dst, words=bool(before and "words" in before))
        report.checks = assurance.verify(before, after, lost, found, video=category(route.dst) == "Video")
    except assurance.Unreadable as exc:
        report.checks = [assurance.Check("Opens", None, None, "error",
                                         f"the result doesn't open as {route.dst.upper()} ({exc})")]
    # a "may" that the checks show didn't happen to this file ("pictures bigger than 1920 pixels are
    # scaled down", and it was smaller) isn't worth saying
    same = {c.name for c in report.checks if c.state == "ok"}
    lost = [n for n in lost if not (n.affects and not n.drops and
                                    all(assurance.NAMES.get(k) in same for k in n.affects if k in assurance.NAMES))]
    report.notes = list(dict.fromkeys(([relabel] if relabel else []) + [n.text for n in lost] + found))
    report.seconds = round(time.perf_counter() - report.started, 3)


def can_extract(fmt: str) -> bool:
    from .converters.archives import EXTRACTABLE
    return fmt in EXTRACTABLE


def extract(src: str | Path, out_dir: str | Path | None = None, src_fmt: str | None = None,
            notes: list[str] | None = None) -> Path:
    """Extract an archive next to it (or into out_dir). A lone top-level folder isn't double-nested.
    notes, when given, gets a line for anything left out or renamed (links, unsafe names)."""
    from .converters.archives import extract_to
    src = Path(src).resolve()
    fmt = src_fmt or detect(src)
    if not can_extract(fmt):
        raise ConversionError(f"{src.name} isn't an archive ConvertAll can extract")
    out = Path(out_dir).resolve() if out_dir else src.parent
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".convertall-", dir=out))
    try:
        try:
            extract_to(src, tmp, fmt, notes)
        except ConversionError:
            raise
        except Exception as exc:  # library errors on a damaged archive -> a readable message
            raise ConversionError(f"Couldn't extract {src.name}: {exc}") from exc
        cancel.check()
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
