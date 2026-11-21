"""Choose which courses to take (and which requirement each one fills) with CP-SAT.

The model, for the programs you're pursuing together:

* ``take[c]`` for each candidate course not yet done; courses already done count as 1.
* ``use[c,p,r]``: course c fills requirement r of program p (only if you have/take c).
* Within a program a course fills at most one requirement (unless ``overlap: true``).
* Between two programs, the number of shared courses is capped where a limit is set.
* Prerequisites close over the choice: if you take c, its prerequisite tree must be
  satisfiable by courses you've done or also take.
* Objective: fewest new credits, with small penalties for rarely-offered courses and
  deep prerequisite chains. Each requirement gets a heavily penalised slack so the
  model always solves and reports exactly what it couldn't satisfy.

The same model with no candidates is the requirement audit used by validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    from ortools.sat.python import cp_model
    HAVE_ORTOOLS = True
except ImportError:          # no wheel for this Python yet: fall back to heuristic.py
    cp_model = None
    HAVE_ORTOOLS = False

from .codes import matches, number
from .graph import depth
from .prereqs import Leaf, Node, leaf_ok
from .programs import Program, Requirement
from .soc import Catalog

SLACK_COST = 100_000


@dataclass
class Selection:
    new_courses: list[str] = field(default_factory=list)
    assignment: dict[str, dict[str, list[str]]] = field(default_factory=dict)  # prog -> req -> codes
    unmet: list[dict] = field(default_factory=list)
    shared: dict[str, list[str]] = field(default_factory=dict)                 # "p+q" -> codes
    status: str = ""
    objective: float = 0.0

    def requirements_of(self, code: str) -> list[str]:
        out = []
        for p, reqs in self.assignment.items():
            for r, codes in reqs.items():
                if code in codes:
                    out.append(f"{p}:{r}")
        return out


def rarity_penalty(catalog: Catalog, code: str) -> int:
    c = catalog.get(code)
    if not c.in_catalog:
        return 25
    if not c.offering.has_data:
        return 8
    if not c.credits_known:
        return 25
    per = c.offering.per_year(catalog.threshold)
    if per >= 2:
        return 0
    if per >= 1:
        return 3
    if per > 0:
        return 6
    return 40


def candidate_pool(programs: list[Program], catalog: Catalog, done: set[str],
                   exclude: set[str], include: set[str], max_closure: int = 800) -> set[str]:
    pool: set[str] = set(include)
    regular = [c for c in catalog.all_codes() if number(c) < 500]
    for p in programs:
        for r in p.requirements:
            pool.update(c for c in r.explicit_codes() if not any(matches(c, e) for e in r.exclude))
            for pat in r.patterns():
                for c in regular:
                    if matches(c, pat) and r.in_pool(c) and catalog.get(c).offering.per_year(catalog.threshold) > 0:
                        pool.add(c)
    # prerequisite closure: add NB courses the chosen ones may need
    frontier = list(pool)
    while frontier and len(pool) < max_closure:
        c = frontier.pop()
        tree = catalog.get(c).prereq.tree
        for lf in _leaves(tree):
            if lf.or_higher or lf.code in pool or lf.code in done or lf.code not in catalog:
                continue
            pool.add(lf.code)
            frontier.append(lf.code)
    return {c for c in pool if c not in done and c not in exclude}


def _leaves(n: Node):
    if n is None:
        return
    if isinstance(n, Leaf):
        yield n
        return
    for ch in n.children:
        yield from _leaves(ch)


class _Builder:
    def __init__(self, programs: list[Program], catalog: Catalog, done: set[str],
                 candidates: set[str], policies: dict | None = None):
        self.m = cp_model.CpModel()
        self.programs, self.catalog, self.done = programs, catalog, set(done)
        self.cands = sorted(candidates - self.done)
        self.policies = policies or {}
        self.take = {c: self.m.NewBoolVar(f"take[{c}]") for c in self.cands}
        self.use: dict[tuple[str, str, str], cp_model.IntVar] = {}
        self.slack: dict[tuple[str, str], cp_model.IntVar] = {}
        self.rule_slack: dict[tuple[str, str, int], cp_model.IntVar] = {}
        self._false = self.m.NewConstant(0)

    def have(self, c: str):
        if c in self.done:
            return 1
        return self.take.get(c, 0)

    def credits(self, c: str, default: float) -> int:
        info = self.catalog.get(c, default)
        return int(round(info.credits if info.in_catalog else default))

    def pool(self, r: Requirement) -> list[str]:
        return sorted(c for c in (self.done | set(self.cands)) if r.in_pool(c))

    def build(self):
        m = self.m
        for p in self.programs:
            per_course: dict[str, list] = {}
            for r in p.requirements:
                pool = self.pool(r)
                for c in pool:
                    v = m.NewBoolVar(f"use[{c},{p.id},{r.id}]")
                    h = self.have(c)
                    if isinstance(h, int):
                        if h == 0:
                            m.Add(v == 0)
                    else:
                        m.AddImplication(v, h)
                    self.use[(c, p.id, r.id)] = v
                    if not r.overlap:
                        per_course.setdefault(c, []).append(v)
                self._requirement(p, r, pool)
            for c, vs in per_course.items():
                if len(vs) > 1:
                    m.Add(sum(vs) <= 1)
        self._double_count()
        self._prereqs()

    def _requirement(self, p: Program, r: Requirement, pool: list[str]):
        m = self.m
        u = lambda c: self.use[(c, p.id, r.id)]  # noqa: E731
        s = m.NewIntVar(0, 1000, f"slack[{p.id},{r.id}]")
        self.slack[(p.id, r.id)] = s
        if r.type == "required":
            need = [u(c) for c in r.courses if c in pool]
            m.Add(sum(need) + s >= len(r.courses))
        elif r.type in ("choose", "level"):
            m.Add(sum(u(c) for c in pool) + s >= r.count)
        elif r.type == "credits":
            m.Add(sum(self.credits(c, p.default_credits) * u(c) for c in pool) + s >= int(r.min_credits))
        elif r.type == "one_set":
            ys = []
            for i, st in enumerate(r.sets):
                y = m.NewBoolVar(f"set[{p.id},{r.id},{i}]")
                for c in st:
                    if c in pool:
                        m.AddImplication(y, u(c))
                    else:
                        m.Add(y == 0)
                ys.append(y)
            m.Add(sum(ys) + s >= 1)
        for i, rule in enumerate(r.rules):
            members = [u(c) for c in pool if any(matches(c, pat) for pat in rule.from_)]
            if rule.min is not None:
                rs = m.NewIntVar(0, 100, f"rslack[{p.id},{r.id},{i}]")
                self.rule_slack[(p.id, r.id, i)] = rs
                m.Add(sum(members) + rs >= rule.min)
            if rule.max is not None:
                m.Add(sum(members) <= rule.max)

    def _used(self, c: str, pid: str):
        vs = [v for (cc, pp, _), v in self.use.items() if cc == c and pp == pid]
        return vs

    def _double_count(self):
        m = self.m
        progs = self.programs
        default = self.policies.get("max_shared")
        pairs = self.policies.get("pairs", {})
        self.shared_vars: dict[tuple[str, str], dict[str, cp_model.IntVar]] = {}
        for i in range(len(progs)):
            for j in range(i + 1, len(progs)):
                p, q = progs[i], progs[j]
                limit = pairs.get(f"{p.id}+{q.id}", pairs.get(f"{q.id}+{p.id}"))
                if limit is None:
                    lims = [x for x in (p.shared_limit(q.id), q.shared_limit(p.id), default) if x is not None]
                    limit = min(lims) if lims else None
                sv = {}
                for c in sorted(self.done | set(self.cands)):
                    up, uq = self._used(c, p.id), self._used(c, q.id)
                    if not up or not uq:
                        continue
                    b = m.NewBoolVar(f"shared[{c},{p.id},{q.id}]")
                    # b == used_p AND used_q
                    m.Add(sum(up) + sum(uq) - 1 <= b)
                    m.Add(b <= sum(up))
                    m.Add(b <= sum(uq))
                    sv[c] = b
                if limit is not None and sv:
                    m.Add(sum(sv.values()) <= int(limit))
                self.shared_vars[(p.id, q.id)] = sv

    def _prereqs(self):
        for c in self.cands:
            lit = self._enc(self.catalog.get(c).prereq.tree, c)
            if lit is True:
                continue
            self.m.AddImplication(self.take[c], lit)

    def _enc(self, n: Node, owner: str):
        """A literal that, when true, guarantees the subtree is satisfied (True if it already is)."""
        m = self.m
        if n is None:
            return True
        if isinstance(n, Leaf):
            if leaf_ok(n, self.done):
                return True
            if n.or_higher:
                alts = [self.take[c] for c in self.cands if c != owner and leaf_ok(n, {c})]
                if not alts:
                    return self._false
                b = m.NewBoolVar("")
                m.AddBoolOr(alts + [b.Not()])
                return b
            if n.code in self.take and n.code != owner:
                return self.take[n.code]
            return self._false
        kids = [self._enc(ch, owner) for ch in n.children]
        if n.op == "and":
            kids = [k for k in kids if k is not True]
            if not kids:
                return True
            b = m.NewBoolVar("")
            for k in kids:
                m.AddImplication(b, k)
            return b
        if any(k is True for k in kids):
            return True
        b = m.NewBoolVar("")
        m.AddBoolOr(kids + [b.Not()])
        return b


def select(programs: list[Program], catalog: Catalog, done: set[str], *, exclude: set[str] = frozenset(),
           include: set[str] = frozenset(), prefer: set[str] = frozenset(), avoid: list[str] = (),
           policies: dict | None = None,
           time_limit: float = 30.0, candidates: set[str] | None = None) -> Selection:
    if candidates is None:
        candidates = candidate_pool(programs, catalog, done, set(exclude), set(include))
    if not HAVE_ORTOOLS:
        from .heuristic import select_heuristic
        dflt = programs[0].default_credits if programs else 3
        fdone = frozenset(done)

        def costfn(c):
            w = round(catalog.get(c, dflt).credits) * 10 + rarity_penalty(catalog, c) + 2 * depth(catalog, c, fdone)
            if c in prefer:
                w -= 15
            if any(matches(c, a) for a in avoid):
                w += 60
            return w
        return select_heuristic(programs, catalog, done, set(candidates), set(include), policies, costfn)
    b = _Builder(programs, catalog, done, candidates, policies)
    b.build()
    m = b.m
    for c in include:
        if c in b.take:
            m.Add(b.take[c] == 1)
    dflt = programs[0].default_credits if programs else 3
    fdone = frozenset(done)
    cost = []
    for c, v in b.take.items():
        w = b.credits(c, dflt) * 10 + rarity_penalty(catalog, c) + 2 * depth(catalog, c, fdone)
        if c in prefer:
            w -= 15
        if any(matches(c, a) for a in avoid):
            w += 60
        cost.append(w * v)
    cost += [SLACK_COST * s for s in b.slack.values()]
    cost += [SLACK_COST // 2 * s for s in b.rule_slack.values()]
    m.Minimize(sum(cost))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1        # small model; one worker keeps results reproducible
    solver.parameters.random_seed = 0
    st = solver.Solve(m)
    sel = Selection(status=solver.StatusName(st))
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return sel
    sel.objective = solver.ObjectiveValue()
    sel.new_courses = sorted(c for c, v in b.take.items() if solver.Value(v))
    for (c, pid, rid), v in b.use.items():
        if solver.Value(v):
            sel.assignment.setdefault(pid, {}).setdefault(rid, []).append(c)
    for p in programs:
        for r in p.requirements:
            sel.assignment.setdefault(p.id, {}).setdefault(r.id, [])
            s = solver.Value(b.slack[(p.id, r.id)])
            if s:
                sel.unmet.append({"program": p.id, "requirement": r.id, "name": r.name, "short_by": s,
                                  "detail": _unmet_detail(r, sel.assignment[p.id][r.id], s)})
            for i, rule in enumerate(r.rules):
                key = (p.id, r.id, i)
                if key in b.rule_slack and solver.Value(b.rule_slack[key]):
                    sel.unmet.append({"program": p.id, "requirement": r.id, "name": rule.label or r.name,
                                      "short_by": solver.Value(b.rule_slack[key]), "detail": rule.label})
    for (pid, qid), sv in b.shared_vars.items():
        codes = sorted(c for c, v in sv.items() if solver.Value(v))
        if codes:
            sel.shared[f"{pid}+{qid}"] = codes
    return sel


def _unmet_detail(r: Requirement, used: list[str], short: int) -> str:
    if r.type == "required":
        missing = [c for c in r.courses if c not in used]
        return "missing " + ", ".join(missing)
    if r.type == "credits":
        return f"{short} credits short"
    if r.type == "one_set":
        return "no sequence completed"
    return f"{short} more course(s) needed"


def audit(programs: list[Program], catalog: Catalog, have: set[str], policies: dict | None = None) -> Selection:
    """Check requirements against a fixed set of courses (no new courses chosen)."""
    return select(programs, catalog, have, policies=policies, candidates=set(), time_limit=15)
