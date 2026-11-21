"""Prerequisite DAG: chain depth, which planned courses a course actually relies on,
and cycle detection."""

from __future__ import annotations

from functools import lru_cache

from .prereqs import Leaf, Node, Op, leaf_ok
from .soc import Catalog


def depth(catalog: Catalog, code: str, done: frozenset[str] = frozenset()) -> int:
    """Longest chain of prerequisites below ``code``. With ``done`` given, courses
    already finished stop the chain (the remaining depth). AND takes the longest
    branch, OR the shortest (you only need one alternative)."""

    @lru_cache(maxsize=None)
    def d(c: str, stack: frozenset[str]) -> int:
        if c in done:
            return -1
        if c in stack:          # a cycle in the SOC data; break it
            return 0
        tree = catalog.get(c).prereq.tree
        if tree is None:
            return 0
        return 1 + ev(tree, stack | {c})

    def ev(n: Node, stack: frozenset[str]) -> int:
        if isinstance(n, Leaf):
            if leaf_ok(n, set(done)):
                return -1
            if n.code not in catalog:
                return 0
            return d(n.code, stack)
        vals = [ev(ch, stack) for ch in n.children]
        return max(vals) if n.op == "and" else min(vals)

    return max(0, d(code, frozenset()))


def needed(tree: Node, done: set[str], avail: set[str]) -> set[str] | None:
    """The courses from ``avail`` (planned, not yet taken) that satisfy ``tree`` together
    with ``done``. Returns None when the tree can't be satisfied. For OR it prefers
    alternatives that are already done, then the one needing the fewest planned courses."""
    if tree is None:
        return set()
    if isinstance(tree, Leaf):
        if leaf_ok(tree, done):
            return set()
        if tree.code in avail:
            return {tree.code}
        if tree.or_higher:
            alt = sorted(a for a in avail if leaf_ok(tree, {a}))
            return {alt[0]} if alt else None
        return None
    parts = [needed(c, done, avail) for c in tree.children]
    if tree.op == "and":
        if any(p is None for p in parts):
            return None
        out: set[str] = set()
        for p in parts:
            out |= p
        return out
    ok = [p for p in parts if p is not None]
    if not ok:
        return None
    return min(ok, key=lambda s: (len(s), sorted(s)))


def coreq_codes(tree: Node) -> set[str]:
    if tree is None:
        return set()
    if isinstance(tree, Leaf):
        return {tree.code} if tree.coreq else set()
    out: set[str] = set()
    for c in tree.children:
        out |= coreq_codes(c)
    return out


def plan_edges(catalog: Catalog, courses: list[str], done: set[str]) -> dict[str, set[str]]:
    """For each planned course, the planned courses it depends on (the DAG we schedule)."""
    avail = set(courses)
    edges = {}
    for c in courses:
        n = needed(catalog.get(c).prereq.tree, done, avail - {c})
        edges[c] = n or set()
    return edges


def find_cycle(edges: dict[str, set[str]]) -> list[str] | None:
    color: dict[str, int] = {}
    path: list[str] = []

    def visit(u: str) -> list[str] | None:
        color[u] = 1
        path.append(u)
        for v in edges.get(u, ()):
            if color.get(v) == 1:
                return path[path.index(v):] + [v]
            if color.get(v) is None:
                r = visit(v)
                if r:
                    return r
        color[u] = 2
        path.pop()
        return None

    for u in edges:
        if color.get(u) is None:
            r = visit(u)
            if r:
                return r
    return None


def heights(edges: dict[str, set[str]]) -> dict[str, int]:
    """Longest chain of planned courses that build on each course (0 = nothing waits on it)."""
    succ: dict[str, set[str]] = {c: set() for c in edges}
    for c, pre in edges.items():
        for p in pre:
            succ.setdefault(p, set()).add(c)

    memo: dict[str, int] = {}

    def h(c: str, stack: frozenset[str]) -> int:
        if c in memo:
            return memo[c]
        if c in stack:
            return 0
        v = max((1 + h(s, stack | {c}) for s in succ.get(c, ())), default=0)
        memo[c] = v
        return v

    return {c: h(c, frozenset()) for c in edges}


def tree_uses_op(n: Node) -> bool:
    return isinstance(n, Op)
