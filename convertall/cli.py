"""convertall command line.

  convertall photo.heic --to png          convert (output lands next to the input)
  convertall *.wav --to mp3 -o out        batch, into a folder
  convertall report.docx --list           what can this become?
  convertall stuff --to 7z                compress a file or folder
  convertall archive.rar --extract        unpack
  convertall engines [--install KEY]      show / install conversion engines
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from . import __version__, engines, pipeline, registry
from .detect import detect, normalize
from .errors import ConversionError, EngineMissingError
from .formats import CATEGORIES, category, describe, suggest


def _expand(patterns: list[str]) -> list[Path]:
    """Windows shells don't expand wildcards, so do it here."""
    paths: list[Path] = []
    for p in patterns:
        hits = glob.glob(p) if any(c in p for c in "*?[") else [p]
        paths += [Path(h) for h in hits]
    return paths


def _ask_install(keys: list[str], assume_yes: bool) -> bool:
    for key in keys:
        eng = engines.ENGINES[key]
        if not assume_yes:
            if not sys.stdin.isatty():
                print(f"{eng.name} is required. Re-run with -y to install it via winget.", file=sys.stderr)
                return False
            answer = input(f"{eng.name} ({eng.size}) is needed for this. Install it with winget? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                return False
        print(f"Installing {eng.name}...")
        if not engines.install(key, log=lambda line: print("  " + line)):
            print(f"Couldn't install {eng.name}.", file=sys.stderr)
            return False
    return True


def cmd_engines(args) -> int:
    if args.install:
        key = args.install.lower()
        if key not in engines.ENGINES:
            print(f"Unknown engine '{key}'. Choose from: {', '.join(engines.ENGINES)}", file=sys.stderr)
            return 2
        return 0 if _ask_install([key], True) else 1
    for eng, path in engines.status():
        state = path if path else f"not installed  (convertall engines --install {eng.key}, {eng.size})"
        print(f"  {eng.name:<12} {state}")
    return 0


def cmd_list(paths: list[Path]) -> int:
    for path in paths:
        fmt = detect(path)
        routes = registry.targets(fmt)
        print(f"{path.name}  [{describe(fmt)}]")
        if not routes:
            print("  (nothing)")
        common = suggest(fmt, routes)
        if common:
            print(f"  {'Most common':<13} {common}")
        by_cat: dict[str, list[str]] = {}
        for dst, route in routes.items():
            by_cat.setdefault(category(dst), []).append(dst + ("*" if route.missing_engines else ""))
        for cat in CATEGORIES:
            if cat in by_cat:
                print(f"  {cat:<13} {' '.join(sorted(by_cat[cat]))}")
        if any(r.missing_engines for r in routes.values()):
            print("  * needs an engine that will be installed on first use")
        if pipeline.can_extract(fmt):
            print("  Archive       --extract")
    return 0


def cmd_convert(paths: list[Path], target: str | None, extract: bool, out: str | None, yes: bool) -> int:
    failures = 0
    for i, path in enumerate(paths, 1):
        prefix = f"[{i}/{len(paths)}] " if len(paths) > 1 else ""
        for attempt in range(2):
            try:
                if extract:
                    result = pipeline.extract(path, out)
                else:
                    result = pipeline.convert(path, target, out)
                print(f"{prefix}{path.name} -> {result}")
                break
            except EngineMissingError as exc:
                if attempt == 0 and _ask_install(exc.engines, yes):
                    continue
                print(f"{prefix}{path.name}: {exc}", file=sys.stderr)
                failures += 1
                break
            except (ConversionError, OSError) as exc:
                print(f"{prefix}{path.name}: {exc}", file=sys.stderr)
                failures += 1
                break
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if argv and argv[0] == "engines":
        p = argparse.ArgumentParser(prog="convertall engines", description="Show or install conversion engines")
        p.add_argument("--install", metavar="KEY", help=f"one of: {', '.join(engines.ENGINES)}")
        return cmd_engines(p.parse_args(argv[1:]))

    p = argparse.ArgumentParser(prog="convertall", description="Convert, compress or extract any file.",
                                epilog="Run 'convertall engines' to see installed conversion engines.")
    p.add_argument("files", nargs="+", help="files or folders (wildcards ok)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--to", "-t", metavar="FORMAT", help="target format, e.g. png, mp3, pdf, zip")
    mode.add_argument("--list", "-l", action="store_true", help="show what each file can become")
    mode.add_argument("--extract", "-x", action="store_true", help="extract archives")
    p.add_argument("-o", "--out", metavar="DIR", help="output folder (default: next to each input)")
    p.add_argument("-y", "--yes", action="store_true", help="install missing engines without asking")
    p.add_argument("--version", action="version", version=f"ConvertAll {__version__}")
    args = p.parse_args(argv)

    paths = _expand(args.files)
    missing = [str(x) for x in paths if not x.exists()]
    if missing or not paths:
        print(f"Not found: {', '.join(missing) or ' '.join(args.files)}", file=sys.stderr)
        return 2
    if args.list:
        return cmd_list(paths)
    return cmd_convert(paths, normalize(args.to) if args.to else None, args.extract, args.out, args.yes)


if __name__ == "__main__":
    sys.exit(main())
