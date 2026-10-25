"""Converter registry and route finding.

Each converter function is registered as a set of edges (src format -> dst format).
Formats are nodes; converting means finding the cheapest chain of edges (max 3 hops).

Edge flags:
  terminal   - output can't feed another step (multi-page/lossy outputs, archives).
  first_only - edge may only be used as the first step (e.g. gif -> video, so png
               doesn't sneak into a video via gif).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import engines
from .errors import NoRouteError
from .formats import category

ConvertFn = Callable[[Path, Path, str, str], "Path | None"]

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

    @property
    def missing_engines(self) -> list[str]:
        seen: list[str] = []
        for e in self.edges:
            if e.engine and not engines.available(e.engine) and e.engine not in seen:
                seen.append(e.engine)
        return seen

    def __str__(self) -> str:
        return " -> ".join([self.src] + [e.dst for e in self.edges])


_edges: dict[str, list[Edge]] = defaultdict(list)


def converter(inputs, outputs, engine=None, cost=1, terminal=False, first_only=False):
    """Register fn(src_path, dst_path, src_fmt, dst_fmt) for every inputs x outputs pair.

    Use inputs={"*"} for "any file". The function may return a different path than
    dst_path (e.g. a folder of pages); otherwise dst_path is assumed.
    """
    def deco(fn: ConvertFn) -> ConvertFn:
        for i in inputs:
            for o in outputs:
                if i != o:
                    _edges[i].append(Edge(i, o, fn, engine, cost, terminal, first_only))
        return fn
    return deco


def _out_edges(fmt: str, hop: int) -> list[Edge]:
    edges = list(_edges.get(fmt, ()))
    if fmt != "folder":
        explicit = {e.dst for e in edges}
        edges += [Edge(fmt, e.dst, e.func, e.engine, e.cost, e.terminal, e.first_only)
                  for e in _edges.get(WILDCARD, ()) if e.dst != fmt and e.dst not in explicit]
    return [e for e in edges if hop == 0 or not e.first_only]


def all_routes(src: str) -> dict[str, Route]:
    """Cheapest route from src to every reachable format (layered search, <= MAX_HOPS)."""
    _ensure_loaded()
    best: dict[str, Route] = {}
    frontier: dict[str, Route] = {src: Route(src, src)}
    for hop in range(MAX_HOPS):
        nxt: dict[str, Route] = {}
        for fmt, route in frontier.items():
            visited = {src} | {e.dst for e in route.edges}
            cats = {category(f) for f in visited}
            for edge in _out_edges(fmt, hop):
                if edge.dst in visited or len(cats | {category(edge.dst)}) > MAX_CATEGORIES:
                    continue
                cand = Route(src, edge.dst, route.edges + [edge], route.cost + edge.effective_cost())
                cur = best.get(edge.dst)
                if cur is None or (cand.cost, len(cand.edges)) < (cur.cost, len(cur.edges)):
                    best[edge.dst] = cand
                if not edge.terminal:
                    n = nxt.get(edge.dst)
                    if n is None or cand.cost < n.cost:
                        nxt[edge.dst] = cand
        frontier = nxt
    return best


def find_route(src: str, dst: str) -> Route:
    route = all_routes(src).get(dst)
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
