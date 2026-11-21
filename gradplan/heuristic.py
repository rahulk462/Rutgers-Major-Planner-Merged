"""Course selection without OR-Tools: a greedy stand-in for the CP-SAT model in selection.py.

Used automatically when ``ortools`` isn't installed (e.g. a Python version it has no
wheels for yet). It fills each requirement with the cheapest eligible courses, reusing
courses you've done or already picked first, respects one-requirement-per-course inside
a program and the between-program sharing caps, then closes over prerequisites by
picking the cheapest branch of each prerequisite tree. Results are good but not
guaranteed minimal; install ortools for the optimal selection.
"""

from __future__ import annotations

from .codes import matches
from .prereqs import Leaf, leaf_ok
from .programs import Program, Requirement
from .soc import Catalog

ORDER = {"required": 0, "one_set": 1, "choose": 2, "level": 2, "credits": 3}


class _State:
    def __init__(self, programs, catalog, done, cands, policies, costfn):
        self.programs, self.catalog = programs, catalog
        self.done, self.cands = set(done), set(cands) - set(done)
        self.chosen: set[str] = set()
        self.cost = costfn
        self.assigned: dict[str, dict[str, str]] = {p.id: {} for p in programs}  # pid -> code -> rid
        self.assignment: dict[str, dict[str, list[str]]] = {p.id: {r.id: [] for r in p.requirements} for p in programs}
        self.limits = self._limits(policies or {})

    def _limits(self, policies):
        out = {}
        default, pairs = policies.get("max_shared"), policies.get("pairs", {}) or {}
        ps = self.programs
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                p, q = ps[i], ps[j]
                lim = pairs.get(f"{p.id}+{q.id}", pairs.get(f"{q.id}+{p.id}"))
                if lim is None:
                    lims = [x for x in (p.shared_limit(q.id), q.shared_limit(p.id), default) if x is not None]
                    lim = min(lims) if lims else None
                out[frozenset((p.id, q.id))] = lim
        return out

    def have(self) -> set[str]:
        return self.done | self.chosen

    def eff_cost(self, c: str) -> float:
        if c in self.have():
            return 0
        return self.cost(c)

    def can_use(self, c: str, p: Program, r: Requirement) -> bool:
        if c not in self.done and c not in self.cands:
            return False
        if c in self.assigned[p.id] and not r.overlap:
            return False
        for q in self.programs:
            if q.id == p.id or c not in self.assigned[q.id]:
                continue
            lim = self.limits.get(frozenset((p.id, q.id)))
            if lim is not None and self.shared(p.id, q.id) >= lim:
                return False
        return True

    def shared(self, a: str, b: str) -> int:
        return len(set(self.assigned[a]) & set(self.assigned[b]))

    def use(self, c: str, p: Program, r: Requirement):
        if c not in self.done:
            self.chosen.add(c)
        if not r.overlap or c not in self.assigned[p.id]:
            self.assigned[p.id][c] = r.id
        if c not in self.assignment[p.id][r.id]:
            self.assignment[p.id][r.id].append(c)

    def pool(self, r: Requirement) -> list[str]:
        return [c for c in self.done | self.cands if r.in_pool(c)]


def _rank(st: _State, cs, p: Program):
    # cheapest first; among equals prefer courses other programs already use (sharing)
    others = {c for q in st.programs if q.id != p.id for c in st.assigned[q.id]}
    return sorted(cs, key=lambda c: (st.eff_cost(c), c not in others, c))


def _fill(st: _State, p: Program, r: Requirement) -> int:
    """Fill one requirement; return how far short it is."""
    pool = st.pool(r)
    used = st.assignment[p.id][r.id]
    cr = lambda c: st.catalog.get(c, p.default_credits).credits  # noqa: E731
    in_rule = lambda c, rule: any(matches(c, pat) for pat in rule.from_)  # noqa: E731

    def rule_ok(c):
        for rule in r.rules:
            if rule.max is not None and in_rule(c, rule) and sum(in_rule(u, rule) for u in used) >= rule.max:
                return False
        return True

    if r.type == "required":
        short = 0
        for c in r.courses:
            if st.can_use(c, p, r):
                st.use(c, p, r)
            else:
                short += 1
        return short
    if r.type == "one_set":
        best = None
        for s in r.sets:
            if all(st.can_use(c, p, r) for c in s):
                cost = sum(st.eff_cost(c) for c in s)
                if best is None or cost < best[0]:
                    best = (cost, s)
        if best is None:
            return 1
        for c in best[1]:
            st.use(c, p, r)
        return 0
    # rule minimums first ("at least 2 from 01:198:4xx")
    for rule in r.rules:
        if rule.min is None:
            continue
        for c in _rank(st, [c for c in pool if in_rule(c, rule)], p):
            if sum(in_rule(u, rule) for u in used) >= rule.min:
                break
            if c not in used and st.can_use(c, p, r) and rule_ok(c):
                st.use(c, p, r)
    if r.type in ("choose", "level"):
        for c in _rank(st, pool, p):
            if len(used) >= r.count:
                break
            if c not in used and st.can_use(c, p, r) and rule_ok(c):
                st.use(c, p, r)
        return max(0, r.count - len(used))
    if r.type == "credits":
        for c in _rank(st, pool, p):
            if sum(cr(u) for u in used) >= r.min_credits:
                break
            if c not in used and st.can_use(c, p, r) and rule_ok(c):
                st.use(c, p, r)
        return max(0, int(round(r.min_credits - sum(cr(u) for u in used))))
    return 0


def _need(st: _State, node, owner: str, seen: frozenset) -> tuple[float, set[str]] | None:
    """Cheapest set of new courses that satisfies a prerequisite tree, or None if impossible."""
    have = st.have()
    if node is None:
        return 0, set()
    if isinstance(node, Leaf):
        if leaf_ok(node, have):
            return 0, set()
        if node.or_higher:
            alts = [c for c in st.cands if c != owner and c not in seen and leaf_ok(node, {c})]
        else:
            alts = [node.code] if node.code in st.cands and node.code != owner and node.code not in seen else []
        best = None
        for c in alts:
            sub = _need(st, st.catalog.get(c).prereq.tree, c, seen | {c})
            if sub is None:
                continue
            cost = st.cost(c) + sub[0]
            if best is None or cost < best[0]:
                best = (cost, {c} | sub[1])
        return best
    kids = [_need(st, ch, owner, seen) for ch in node.children]
    if node.op == "and":
        if any(k is None for k in kids):
            return None
        return sum(k[0] for k in kids), set().union(*[k[1] for k in kids]) if kids else set()
    kids = [k for k in kids if k is not None]
    return min(kids, key=lambda k: (k[0], sorted(k[1]))) if kids else None


def select_heuristic(programs: list[Program], catalog: Catalog, done: set[str], candidates: set[str],
                     include: set[str], policies: dict | None, costfn):
    from .selection import Selection, _unmet_detail
    st = _State(programs, catalog, done, candidates, policies, costfn)
    st.chosen |= {c for c in include if c in st.cands}
    unmet = []
    for p in programs:
        for r in sorted(p.requirements, key=lambda r: ORDER.get(r.type, 9)):
            short = _fill(st, p, r)
            if short:
                unmet.append({"program": p.id, "requirement": r.id, "name": r.name, "short_by": short,
                              "detail": _unmet_detail(r, st.assignment[p.id][r.id], short)})
            for rule in r.rules:
                if rule.min is not None:
                    n = sum(any(matches(u, pat) for pat in rule.from_) for u in st.assignment[p.id][r.id])
                    if n < rule.min:
                        unmet.append({"program": p.id, "requirement": r.id, "name": rule.label or r.name,
                                      "short_by": rule.min - n, "detail": rule.label})
    # prerequisite closure
    changed = True
    while changed:
        changed = False
        for c in sorted(st.chosen):
            sub = _need(st, catalog.get(c).prereq.tree, c, frozenset({c}))
            if sub and sub[1] - st.chosen:
                st.chosen |= sub[1]
                changed = True
    sel = Selection(status="heuristic")
    sel.new_courses = sorted(st.chosen)
    sel.assignment = {pid: {rid: sorted(cs) for rid, cs in reqs.items()} for pid, reqs in st.assignment.items()}
    sel.unmet = unmet
    ids = [p.id for p in programs]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            codes = sorted(set(st.assigned[ids[i]]) & set(st.assigned[ids[j]]))
            if codes:
                sel.shared[f"{ids[i]}+{ids[j]}"] = codes
    sel.objective = sum(costfn(c) for c in st.chosen)
    return sel
