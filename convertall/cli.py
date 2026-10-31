"""convertall command line.

  convertall photo.heic --to png          convert (output lands next to the input)
  convertall *.wav --to mp3 -o out        batch, into a folder
  convertall report.docx --list           what can this become?
  convertall stuff --to 7z                compress a file or folder
  convertall archive.rar --extract        unpack
  convertall clip.mov --to gif --plan     show the route and what it can't keep, convert nothing
  convertall *.jpg --to webp --preset "Smaller for email and web"
  convertall photo.png --to jpg --quality 80 --json
  convertall view model.fbx               look at a 3D model, in a window
  convertall presets                      list presets and settings
  convertall engines [--install KEY]      show / install conversion engines
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

from . import __version__, assurance, engines, options, pipeline, registry
from .assurance import Report
from .detect import detect, mislabelled, normalize
from .errors import ConversionError, EngineMissingError
from .formats import CATEGORIES, category, describe, suggest, viewable


def _expand(patterns: list[str]) -> list[Path]:
    """Windows shells don't expand wildcards, so do it here."""
    paths: list[Path] = []
    for p in patterns:
        hits = glob.glob(p) if any(c in p for c in "*?[") else [p]
        paths += [Path(h) for h in hits]
    return paths


def _ask_install(keys: list[str], assume_yes: bool, out=None) -> bool:
    out = out or sys.stdout
    for key in keys:
        eng = engines.ENGINES[key]
        if not assume_yes:
            if not sys.stdin.isatty():
                print(f"{eng.name} is required. Re-run with -y to install it.", file=sys.stderr)
                return False
            # the question goes to stderr, so --json output stays only JSON
            print(f"{eng.name} ({eng.size}) is needed for this. Install it now? [y/N] ", end="", file=sys.stderr, flush=True)
            answer = input()
            if answer.strip().lower() not in ("y", "yes"):
                return False
        print(f"Installing {eng.name}...", file=out)
        try:
            ok = engines.install(key, log=lambda line: print("  " + line, file=out))
        except ConversionError as exc:
            print(f"Couldn't install {eng.name}: {exc}", file=sys.stderr)
            return False
        if not ok:
            print(f"Couldn't install {eng.name}.", file=sys.stderr)
            return False
    return True


def cmd_engines(args) -> int:
    if args.install:
        key = args.install.lower()
        shown = [e.key for e in engines.ENGINES.values() if not e.hidden]
        if key not in shown:
            print(f"Unknown engine '{key}'. Choose from: {', '.join(shown)}", file=sys.stderr)
            return 2
        return 0 if _ask_install([key], True) else 1
    for eng, path in engines.status():
        state = path if path else f"not installed  (convertall engines --install {eng.key}, {eng.size})"
        print(f"  {eng.name:<12} {state}")
    return 0


def cmd_list(paths: list[Path], as_json: bool = False) -> int:
    for path in paths:
        fmt = detect(path)
        routes = registry.targets(fmt)
        if as_json:
            _emit({"source": str(path), "source_format": fmt, "kind": describe(fmt),
                   "suggested": suggest(fmt, routes), "extract": pipeline.can_extract(fmt),
                   "targets": [{"format": dst, "category": category(dst), "route": _arrow(fmt, route),
                                "needs": [engines.ENGINES[k].name for k in route.missing_engines]}
                               for dst, route in sorted(routes.items())]})
            continue
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


def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str), flush=True)


def _arrow(fmt: str, route) -> str:
    return " → ".join([fmt.upper()] + [e.dst.upper() for e in route.edges])


def cmd_plan(paths: list[Path], target: str, settings: dict, as_json: bool) -> int:
    """Each file's route, what it can't keep and the settings it takes, converting nothing."""
    failures = 0
    for path in paths:
        try:
            fmt = detect(path)
            facts = assurance.measure(path, fmt)
            held = assurance.features(facts, fmt)
            route = registry.find_route(fmt, target, held, settings)
        except (ConversionError, OSError) as exc:  # OSError: missing, locked or unreadable
            _fail(path, exc, "", as_json)
            failures += 1
            continue
        relabel = mislabelled(path)
        notes = list(dict.fromkeys(([relabel] if relabel else []) + [n.text for n in route.explain(held, settings)]))
        steps = [{"from": e.src, "to": e.dst, "tool": assurance.tool(e)} for e in route.edges]
        used = options.applying(settings, route.settings)
        needs = [engines.ENGINES[k].name for k in route.missing_engines]
        if as_json:
            _emit({"source": str(path), "source_format": fmt, "target": target,
                   "route": _arrow(fmt, route),
                   "steps": steps, "notes": notes, "settings": used, "takes": route.settings, "needs": needs,
                   "facts": facts or {}})
            continue
        tools = ", ".join(dict.fromkeys(st["tool"] for st in steps))
        print(f"{path.name}: {_arrow(fmt, route)} via {tools}")
        for line in notes:
            print(f"  {line}")
        if route.settings:
            print("  Settings: " + ", ".join(f"{k}={used[k]}" if k in used else k for k in route.settings))
        if needs:
            print(f"  Needs {' and '.join(needs)} (installed on first use)")
    return 1 if failures else 0


def cmd_convert(paths: list[Path], target: str | None, extract: bool, out: str | None, yes: bool,
                settings: dict | None = None, as_json: bool = False) -> int:
    failures = 0
    info = sys.stderr if as_json else sys.stdout  # with --json, stdout holds only the reports
    for i, path in enumerate(paths, 1):
        prefix = f"[{i}/{len(paths)}] " if len(paths) > 1 and not as_json else ""
        for attempt in range(2):
            try:
                notes: list[str] = []
                report = None
                if extract:
                    result = pipeline.extract(path, out, notes=notes)
                else:
                    report = Report()
                    result = pipeline.convert(path, target, out, report=report, options=settings)
                    notes = report.lines()[1:]
                if as_json:
                    _emit(report.to_dict() if report else {"source": str(path), "output": str(result), "notes": notes})
                else:
                    print(f"{prefix}{path.name} -> {result}")
                    for note in notes:
                        print(f"{prefix}  {note}")
                break
            except EngineMissingError as exc:
                if attempt == 0 and _ask_install(exc.engines, yes, info):
                    continue
                _fail(path, exc, prefix, as_json)
                failures += 1
                break
            except (ConversionError, OSError) as exc:
                _fail(path, exc, prefix, as_json)
                failures += 1
                break
    return 1 if failures else 0


def _fail(path: Path, exc: Exception, prefix: str, as_json: bool) -> None:
    if as_json:
        _emit({"source": str(path), "error": str(exc)})
    else:
        print(f"{prefix}{path.name}: {exc}", file=sys.stderr)


def cmd_presets() -> int:
    print("Presets (--preset NAME):")
    for name, values in options.all_presets().items():
        mine = "" if name in options.PRESETS else "  (yours)"
        print(f"  {name}{mine}: " + (", ".join(f"{k}={v}" for k, v in values.items()) or "ConvertAll's own settings"))
    print("\nSettings (each applies only where a conversion takes it; unset ones keep the defaults):")
    for st in options.SETTINGS.values():
        kind = "|".join(st.choices) if st.choices else f"{st.low}-{st.high}"
        print(f"  --{st.key.replace('_', '-'):<14} {kind:<34} {st.help}. Default: {st.auto}")
    return 0


def cmd_view(paths: list[Path]) -> int:
    """Open each model in the 3D viewer. The installed terminal tool has no window code of its
    own, so it hands the files to ConvertAll.exe next to it."""
    for path in paths:
        if not path.is_file() or not viewable(detect(path)):
            print(f"{path.name} isn't a 3D model or CAD part ConvertAll can show", file=sys.stderr)
            return 2
    files = [str(p.resolve()) for p in paths]
    if getattr(sys, "frozen", False):
        app = Path(sys.executable).with_name("ConvertAll.exe")
        if not app.is_file():
            print(f"ConvertAll.exe isn't next to {Path(sys.executable).name}, so there's no window to show "
                  "the model in", file=sys.stderr)
            return 1
        subprocess.Popen([str(app), "--view", *files])
        return 0
    from .instance import main as gui_main
    return gui_main(["--view", *files])


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            # a pipe or file gets UTF-8 (what scripts reading --json expect); a console keeps its own
            piped = not stream.isatty()
            stream.reconfigure(**({"encoding": "utf-8"} if piped else {}), errors="replace")

    if argv and argv[0] == "engines":
        p = argparse.ArgumentParser(prog="convertall engines", description="Show or install conversion engines")
        shown = [e.key for e in engines.ENGINES.values() if not e.hidden]
        p.add_argument("--install", metavar="KEY", help=f"one of: {', '.join(shown)}")
        return cmd_engines(p.parse_args(argv[1:]))

    if argv and argv[0] == "presets":
        return cmd_presets()

    if argv and argv[0] == "view":
        p = argparse.ArgumentParser(prog="convertall view", description="Show 3D models in a window")
        p.add_argument("files", nargs="+", help="3D models or CAD parts")
        paths = _expand(p.parse_args(argv[1:]).files)
        missing = [str(x) for x in paths if not x.exists()]
        if missing or not paths:
            print(f"Not found: {', '.join(missing) or ' '.join(argv[1:])}", file=sys.stderr)
            return 2
        return cmd_view(paths)

    p = argparse.ArgumentParser(prog="convertall", description="Convert, compress or extract any file.",
                                epilog="Run 'convertall engines' to see installed conversion engines, "
                                       "'convertall view FILE' to look at a 3D model, or "
                                       "'convertall presets' for presets and settings.")
    p.add_argument("files", nargs="+", help="files or folders (wildcards ok)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--to", "-t", metavar="FORMAT", help="target format, e.g. png, mp3, pdf, zip")
    mode.add_argument("--list", "-l", action="store_true", help="show what each file can become")
    mode.add_argument("--extract", "-x", action="store_true", help="extract archives")
    p.add_argument("-o", "--out", metavar="DIR", help="output folder (default: next to each input)")
    p.add_argument("-y", "--yes", action="store_true", help="install missing engines without asking")
    p.add_argument("--plan", action="store_true", help="show each file's route and what it can't keep; convert nothing")
    p.add_argument("--json", action="store_true", help="one JSON report per file on stdout (route, notes, checks)")
    group = p.add_argument_group("settings", "Each applies only where a conversion takes it; unset ones keep the "
                                             "defaults. 'convertall presets' lists them all.")
    group.add_argument("--preset", metavar="NAME", help='a named set of settings, e.g. "Smaller for email and web"')
    for st in options.SETTINGS.values():
        group.add_argument(f"--{st.key.replace('_', '-')}", dest=st.key, metavar="|".join(st.choices) or "N",
                           help=f"{st.help} (default: {st.auto})")
    p.add_argument("--version", action="version", version=f"ConvertAll {__version__}")
    args = p.parse_args(argv)

    paths = _expand(args.files)
    missing = [str(x) for x in paths if not x.exists()]
    if missing or not paths:
        print(f"Not found: {', '.join(missing) or ' '.join(args.files)}", file=sys.stderr)
        return 2
    if args.list:
        return cmd_list(paths, args.json)
    try:
        settings = options.preset(args.preset) if args.preset else {}
        settings.update(options.clean({k: getattr(args, k) for k in options.SETTINGS}))
    except KeyError:
        print(f"No preset named '{args.preset}'. Run 'convertall presets' to see them.", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.plan:
        if not args.to:
            print("--plan needs --to FORMAT", file=sys.stderr)
            return 2
        return cmd_plan(paths, normalize(args.to), settings, args.json)
    return cmd_convert(paths, normalize(args.to) if args.to else None, args.extract, args.out, args.yes,
                       settings, args.json)


if __name__ == "__main__":
    sys.exit(main())
