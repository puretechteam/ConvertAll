"""Converter registry and route finding.

Each converter function is registered as a set of edges (src format -> dst format).
Formats are nodes; converting means finding the cheapest chain of edges (max 3 hops).

Edge flags:
  terminal   - output can't feed another step (multi-page/lossy outputs, archives).
  first_only - edge may only be used as the first step (e.g. gif -> video, so png
               doesn't sneak into a video via gif).

An edge can also say what it leaves out (notes, see losses.py) and which settings it takes
(options, see options.py). A route costs what it loses as well as its steps, so the route
that keeps the most wins, even when it is a step longer.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import engines, losses
from .errors import NoRouteError
from .formats import category
from .losses import Loss

ConvertFn = Callable[[Path, Path, str, str], "Path | None"]
NotesFn = Callable[[str, str, dict], "Iterable[Loss]"]  # (src fmt, dst fmt, options) -> what it leaves out
OptionsFn = Callable[[str, str], "Iterable[str]"]       # (src fmt, dst fmt) -> setting keys it takes

WILDCARD = "*"
MAX_HOPS = 3
MAX_CATEGORIES = 3  # json -> csv -> pdf -> png drifts too far to be useful
MISSING_ENGINE_PENALTY = 10


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    func: ConvertFn
    engine: str | None = None
    cost: int = 1
    terminal: bool = False
    first_only: bool = False
    notes: NotesFn | None = None
    options: OptionsFn | None = None

    def losses(self, options: dict | None = None) -> list[Loss]:
        return list(self.notes(self.src, self.dst, options or {})) if self.notes else []

    def settings(self) -> list[str]:
        return list(self.options(self.src, self.dst)) if self.options else []

    def effective_cost(self) -> int:
        if self.engine and not engines.available(self.engine):
            return self.cost + MISSING_ENGINE_PENALTY
        return self.cost


@dataclass
class Route:
    src: str
    dst: str
    edges: list[Edge] = field(default_factory=list)
    cost: int = 0
    held: frozenset[str] = frozenset()  # the features still kept at the end (losses.py)
    lost: list[Loss] = field(default_factory=list)

    @property
    def missing_engines(self) -> list[str]:
        seen: list[str] = []
        for e in self.edges:
            if e.engine and not engines.available(e.engine) and e.engine not in seen:
                seen.append(e.engine)
        return seen

    @property
    def notes(self) -> list[str]:
        """What this route can't keep, in order, each line once."""
        return list(dict.fromkeys(n.text for n in self.lost))

    def explain(self, held: frozenset[str] | None = None, options: dict | None = None) -> list[Loss]:
        """What this route loses for a file with these features (the format's usual ones when None)."""
        held = losses.typical(self.src) if held is None else frozenset(held)
        out: list[Loss] = []
        for e in self.edges:
            lost, held = losses.step(e.losses(options), e.dst, held)
            out += lost
        return out

    @property
    def settings(self) -> list[str]:
        """The setting keys any step of this route takes."""
        return list(dict.fromkeys(k for e in self.edges for k in e.settings()))

    def __str__(self) -> str:
        return " -> ".join([self.src] + [e.dst for e in self.edges])


_edges: dict[str, list[Edge]] = defaultdict(list)


def converter(inputs, outputs, engine=None, cost=1, terminal=False, first_only=False, notes=None, options=None):
    """Register fn(src_path, dst_path, src_fmt, dst_fmt) for every inputs x outputs pair.

    Use inputs={"*"} for "any file". The function may return a different path than
    dst_path (e.g. a folder of pages); otherwise dst_path is assumed. notes(src, dst, options)
    gives what it leaves out (losses.Loss lines). options is the setting keys it takes, or a
    function (src, dst) -> keys; the function reads each with option(key).
    """
    if options is not None and not callable(options):
        keys = tuple(options)
        options = lambda s, d: keys
    def deco(fn: ConvertFn) -> ConvertFn:
        for i in inputs:
            for o in outputs:
                if i != o:
                    _edges[i].append(Edge(i, o, fn, engine, cost, terminal, first_only, notes, options))
        return fn
    return deco


# ---- what the running steps were asked for, and what they found (set by pipeline.convert)

_options: contextvars.ContextVar[dict] = contextvars.ContextVar("options", default={})  # noqa: B039 - never mutated
_found: contextvars.ContextVar[list | None] = contextvars.ContextVar("found", default=None)


def option(key: str, default=None):
    """A setting chosen for this conversion (options.py), or default."""
    value = _options.get().get(key)
    return default if value is None else value


def note(text: str) -> None:
    """Report something this conversion left out or changed, found while running (a link that
    wasn't archived, a name that had to change)."""
    found = _found.get()
    if found is not None and text not in found:
        found.append(text)


def running(options: dict, found: list) -> tuple:
    """Set the settings and the findings list for the steps about to run; reset(tokens) undoes it."""
    return _options.set(dict(options)), _found.set(found)


def reset(tokens: tuple) -> None:
    _options.reset(tokens[0])
    _found.reset(tokens[1])


# ---- what the check already read of the source (set by pipeline.convert): a book, a 3D scene or
# a picture is parsed once and handed to the step that would read it again

_parsed: contextvars.ContextVar[dict | None] = contextvars.ContextVar("parsed", default=None)


@contextlib.contextmanager
def sharing():
    """Within it, keep() holds what was read of a file and take() hands it over once."""
    token = _parsed.set({})
    try:
        yield
    finally:
        _parsed.reset(token)


def _parse_key(path: Path, fmt: str | None, kind: str) -> tuple | None:
    try:
        st = path.stat()
        return str(path.resolve()), st.st_mtime_ns, st.st_size, fmt, kind
    except OSError:
        return None


def keep(path: Path, fmt: str | None, kind: str, value) -> None:
    """Remember value as what reading path as fmt gave (kind: "book", "scene"...)."""
    cache = _parsed.get()
    key = _parse_key(Path(path), fmt, kind) if cache is not None else None
    if key is not None:
        cache[key] = value


def take(path: Path, fmt: str | None, kind: str):
    """What keep() held for path, or None; it is handed over, not shared: the taker may change it."""
    cache = _parsed.get()
    key = _parse_key(Path(path), fmt, kind) if cache else None
    return cache.pop(key, None) if key is not None else None


def _out_edges(fmt: str, hop: int) -> list[Edge]:
    edges = list(_edges.get(fmt, ()))
    if fmt != "folder":
        explicit = {e.dst for e in edges}
        edges += [replace(e, src=fmt) for e in _edges.get(WILDCARD, ()) if e.dst != fmt and e.dst not in explicit]
    return [e for e in edges if hop == 0 or not e.first_only]


def _rank(r: Route) -> tuple[int, int, int]:
    return r.cost, losses.cost(r.lost), len(r.edges)


_route_cache: dict[tuple, dict[str, Route]] = {}


def all_routes(src: str, held: frozenset[str] | None = None, options: dict | None = None) -> dict[str, Route]:
    """Cheapest route from src to every reachable format (layered search, <= MAX_HOPS). A route
    costs its steps plus what it loses for a file with these features (the format's usual ones
    when None); a tie goes to the route that loses less, then to the shorter one."""
    _ensure_loaded()
    held = losses.typical(src) if held is None else frozenset(held)
    # A batch asks the same question for every file. The answer depends on which engines are
    # installed too (one still to install costs more), so that's part of the key.
    key = (id(_edges), sum(len(v) for v in _edges.values()), src, held,
           frozenset((options or {}).items()), engines.state())
    found = _route_cache.get(key)  # read once: another thread may clear the cache meanwhile
    if found is None:
        if len(_route_cache) > 256:
            _route_cache.clear()
        found = _route_cache[key] = _search(src, held, options)
    return dict(found)


def _search(src: str, held: frozenset[str], options: dict | None) -> dict[str, Route]:
    best: dict[str, Route] = {}
    frontier: dict[str, Route] = {src: Route(src, src, held=held)}
    for hop in range(MAX_HOPS):
        nxt: dict[str, Route] = {}
        for fmt, route in frontier.items():
            visited = {src} | {e.dst for e in route.edges}
            cats = {category(f) for f in visited}
            for edge in _out_edges(fmt, hop):
                if edge.dst in visited or len(cats | {category(edge.dst)}) > MAX_CATEGORIES:
                    continue
                lost, kept = losses.step(edge.losses(options), edge.dst, route.held)
                cand = Route(src, edge.dst, route.edges + [edge],
                             route.cost + edge.effective_cost() + losses.cost(lost), kept, route.lost + lost)
                cur = best.get(edge.dst)
                if cur is None or _rank(cand) < _rank(cur):
                    best[edge.dst] = cand
                if not edge.terminal:
                    n = nxt.get(edge.dst)
                    if n is None or _rank(cand) < _rank(n):
                        nxt[edge.dst] = cand
        frontier = nxt
    return best


def find_route(src: str, dst: str, held: frozenset[str] | None = None, options: dict | None = None) -> Route:
    route = all_routes(src, held, options).get(dst)
    if route is None:
        raise NoRouteError(f"Can't convert {src.upper()} to {dst.upper()}")
    return route


def targets(src: str) -> dict[str, Route]:
    return all_routes(src)


def common_targets(srcs: list[str]) -> dict[str, list[Route]]:
    """Formats every given source can reach, for batch conversions."""
    per = [all_routes(s) for s in dict.fromkeys(srcs)]
    if not per:
        return {}
    keys = set(per[0]).intersection(*per[1:])
    return {k: [p[k] for p in per] for k in keys}


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        _loaded = True
        from . import converters  # noqa: F401  (registers everything)
