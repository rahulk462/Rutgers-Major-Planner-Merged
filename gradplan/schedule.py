"""Place the chosen courses into terms: a greedy topological scheduler and a CP-SAT one.

Both respect prerequisites (corequisites may share a term), predicted offering
terms, per-term credit caps, locked courses, and a limit on "hard" courses per
term. Open credits ("free elective / SAS Core") are added so every regular term
meets the minimum load and the degree reaches its total-credit requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    from ortools.sat.python import cp_model
except ImportError:          # greedy() still works; cpsat() reports that it can't run
    cp_model = None

from .codes import Term, term_range
from .graph import coreq_codes, heights, plan_edges
from .prereqs import Leaf, Node, leaf_ok
from .soc import Catalog

FILLER = "ELECTIVE"


@dataclass
class Prefs:
    start: Term
    target: Term | None = None
    max_credits: float = 18
    min_credits: float = 12
    summer: bool = False
    winter: bool = False
    summer_max: float = 8
    winter_max: float = 4
    total_required: float = 120
    credits_earned: float = 0
    locked: dict[str, Term] = field(default_factory=dict)
    hard: set[str] = field(default_factory=set)
    max_hard_per_term: int = 1
    objective: str = "min_terms"          # or "balance"
    horizon_terms: int = 16               # how far past start to look (all seasons counted)
    fill_electives: bool = True

    def seasons(self) -> set[int]:
        s = {1, 9}
        if self.summer:
            s.add(7)
        if self.winter:
            s.add(0)
        return s

    def cap(self, t: Term) -> float:
        return {7: self.summer_max, 0: self.winter_max}.get(t.season, self.max_credits)

    def floor(self, t: Term) -> float:
        return self.min_credits if t.is_regular else 0

    def terms(self) -> list[Term]:
        end = self.start
        for _ in range(self.horizon_terms * 2):
            end = end.next()
        if self.target:
            # look a little past the target so a late plan is reported, not "infeasible"
            t2 = self.target
            for _ in range(8):
                t2 = t2.next()
            end = min(end, t2) if end > t2 else end
        return term_range(self.start, end, self.seasons())


@dataclass
class Plan:
    terms: list[Term]
    placement: dict[str, Term]                  # course -> term
    filler: dict[Term, float] = field(default_factory=dict)
    unscheduled: list[str] = field(default_factory=list)
    method: str = ""
    status: str = ""
    notes: list[str] = field(default_factory=list)

    def courses_in(self, t: Term) -> list[str]:
        return sorted(c for c, tt in self.placement.items() if tt == t)

    def last_term(self) -> Term | None:
        used = [t for t in self.terms if self.courses_in(t) or self.filler.get(t, 0) > 0]
        return max(used) if used else None

    def used_terms(self) -> list[Term]:
        last = self.last_term()
        return [t for t in self.terms if last and t <= last]


def _credits(catalog: Catalog, c: str) -> float:
    return catalog.get(c).credits


# ------------------------------------------------------------------- greedy

def greedy(courses: list[str], catalog: Catalog, done: set[str], prefs: Prefs) -> Plan:
    edges = plan_edges(catalog, courses, done)
    coreqs = {c: coreq_codes(catalog.get(c).prereq.tree) for c in courses}
    h = heights(edges)
    terms = prefs.terms()
    placed: dict[str, Term] = {}
    remaining = set(courses)
    locked = {c: t for c, t in prefs.locked.items() if c in remaining}
    notes: list[str] = []

    def ready(c: str, t: Term, this_term: set[str]) -> bool:
        for d in edges[c]:
            if d in placed and placed[d] < t:
                continue
            if d in this_term and d in coreqs[c]:
                continue
            return False
        return True

    def rank(c: str):
        off = catalog.get(c).offering
        per = off.per_year(catalog.threshold)
        return (-h.get(c, 0), per, -_credits(catalog, c), c)

    for t in terms:
        if not remaining:
            break
        load = 0.0
        hard = 0
        this: set[str] = set()
        # locked courses first
        for c, lt in locked.items():
            if lt == t and c in remaining:
                if not ready(c, t, this):
                    notes.append(f"{c} is locked to {t} but its prerequisites aren't planned before then")
                this.add(c)
                load += _credits(catalog, c)
                hard += c in prefs.hard
        changed = True
        while changed:
            changed = False
            cands = sorted((c for c in remaining - this - set(locked)
                            if catalog.offered(c, t) and ready(c, t, this)), key=rank)
            for c in cands:
                cr = _credits(catalog, c)
                if load + cr > prefs.cap(t):
                    continue
                if c in prefs.hard and hard >= prefs.max_hard_per_term:
                    continue
                this.add(c)
                load += cr
                hard += c in prefs.hard
                changed = True
                break                     # re-rank: a corequisite may now be ready
        for c in this:
            placed[c] = t
        remaining -= this
    plan = Plan(terms=terms, placement=placed, unscheduled=sorted(remaining), method="greedy",
                status="ok" if not remaining else "incomplete", notes=notes)
    if prefs.fill_electives:
        _fill(plan, catalog, prefs)
    return plan


def _fill(plan: Plan, catalog: Catalog, prefs: Prefs) -> None:
    """Add open elective credits: first up to each term's minimum, then until the total is met."""
    planned = sum(_credits(catalog, c) for c in plan.placement)
    need = prefs.total_required - prefs.credits_earned - planned
    last = plan.last_term()
    terms = [t for t in plan.terms if last is None or t <= last]
    load = {t: sum(_credits(catalog, c) for c in plan.courses_in(t)) for t in plan.terms}
    for t in terms:
        if not t.is_regular:
            continue
        add = max(0.0, prefs.floor(t) - load[t])
        if add:
            plan.filler[t] = plan.filler.get(t, 0) + add
            load[t] += add
            need -= add
    target_load = max(prefs.min_credits, 15)
    for pass_cap in (target_load, None):
        for t in plan.terms:
            if need <= 0:
                break
            if not t.is_regular:
                continue
            cap = prefs.cap(t) if pass_cap is None else min(prefs.cap(t), pass_cap)
            room = cap - load[t]
            if room > 0:
                add = min(room, need)
                plan.filler[t] = plan.filler.get(t, 0) + add
                load[t] += add
                need -= add
    if need > 0:
        plan.notes.append(f"{need:g} credits still short of {prefs.total_required:g} within the horizon")


# ------------------------------------------------------------------- CP-SAT

def cpsat(courses: list[str], catalog: Catalog, done: set[str], prefs: Prefs,
          time_limit: float = 60.0, hint: Plan | None = None) -> Plan:
    terms = prefs.terms()
    T = len(terms)
    if cp_model is None:
        return Plan(terms=terms, placement={}, unscheduled=sorted(courses), method="cp-sat",
                    status="unavailable", notes=["CP-SAT needs the ortools package, which isn't installed"])
    m = cp_model.CpModel()
    sel = set(courses)
    cr = {c: int(round(_credits(catalog, c) * 2)) for c in courses}     # half-credit units
    x: dict[tuple[str, int], cp_model.IntVar] = {}
    for c in courses:
        allowed = [i for i, t in enumerate(terms) if catalog.offered(c, t)]
        if c in prefs.locked:
            lt = prefs.locked[c]
            allowed = [i for i, t in enumerate(terms) if t == lt]
        for i in allowed:
            x[(c, i)] = m.NewBoolVar(f"x[{c},{terms[i].key}]")
        m.AddExactlyOne([x[(c, i)] for i in allowed] or [m.NewConstant(0)])

    # done_before[c][i] = course c placed in a term < i ; done_by[c][i] = placed in a term <= i
    before: dict[tuple[str, int], cp_model.IntVar] = {}
    by: dict[tuple[str, int], cp_model.IntVar] = {}
    for c in courses:
        for i in range(T):
            b = m.NewBoolVar("")
            m.Add(b == sum(x[(c, j)] for j in range(i) if (c, j) in x))
            before[(c, i)] = b
            b2 = m.NewBoolVar("")
            m.Add(b2 == sum(x[(c, j)] for j in range(i + 1) if (c, j) in x))
            by[(c, i)] = b2

    false = m.NewConstant(0)

    def enc(n: Node, i: int, owner: str):
        if n is None:
            return True
        if isinstance(n, Leaf):
            if leaf_ok(n, done):
                return True
            src = by if n.coreq else before
            if n.or_higher:
                alts = [src[(c, i)] for c in sel if c != owner and leaf_ok(n, {c})]
                if not alts:
                    return false
                b = m.NewBoolVar("")
                m.AddBoolOr(alts + [b.Not()])
                return b
            if n.code in sel and n.code != owner:
                return src[(n.code, i)]
            return false
        kids = [enc(ch, i, owner) for ch in n.children]
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

    for c in courses:
        tree = catalog.get(c).prereq.tree
        for i in range(T):
            if (c, i) not in x:
                continue
            lit = enc(tree, i, c)
            if lit is not True:
                m.AddImplication(x[(c, i)], lit)

    active = [m.NewBoolVar(f"active[{t.key}]") for t in terms]
    for i in range(T - 1):
        m.AddImplication(active[i + 1], active[i])
    G = m.NewIntVar(0, T, "terms_used")
    m.Add(G == sum(active))
    fill = [m.NewIntVar(0, int(prefs.cap(t) * 2), f"fill[{t.key}]") for t in terms]
    loads = []
    hard_excess = []
    work = []
    for i, t in enumerate(terms):
        here = [(c, x[(c, i)]) for c in courses if (c, i) in x]
        for _, v in here:
            m.AddImplication(v, active[i])
        if not prefs.fill_electives:
            m.Add(fill[i] == 0)
        m.Add(fill[i] <= int(prefs.cap(t) * 2) * active[i])
        load = sum(cr[c] * v for c, v in here) + fill[i]
        m.Add(load <= int(prefs.cap(t) * 2))
        if prefs.fill_electives:
            m.Add(load >= int(prefs.floor(t) * 2) * active[i])
        loads.append(load)
        hs = [v for c, v in here if c in prefs.hard]
        if hs:
            e = m.NewIntVar(0, len(hs), "")
            m.Add(e >= sum(hs) - prefs.max_hard_per_term)
            hard_excess.append(e)
        w = m.NewIntVar(0, 200, f"work[{t.key}]")
        m.Add(w == sum((cr[c] + (4 if c in prefs.hard else 0)) * v for c, v in here))
        work.append(w)
    if prefs.fill_electives:
        m.Add(sum(cr.values()) + sum(fill) >= int((prefs.total_required - prefs.credits_earned) * 2))

    # workload balance over regular active terms
    max_w = m.NewIntVar(0, 200, "max_work")
    min_w = m.NewIntVar(0, 200, "min_work")
    for i, t in enumerate(terms):
        m.Add(max_w >= work[i])
        if t.is_regular:
            m.Add(min_w <= work[i] + 200 * (1 - active[i]))
    spread = m.NewIntVar(0, 200, "spread")
    m.Add(spread == max_w - min_w)
    late = []
    if prefs.target:
        tgt = sum(1 for t in terms if t <= prefs.target)
        over = m.NewIntVar(0, T, "terms_past_target")
        m.Add(over >= G - tgt)
        late.append(over)
    # earlier is better, most of all for courses that long chains build on
    h = heights(plan_edges(catalog, courses, done))
    unlocks = catalog.unlock_counts()
    weight = {c: 1 + 3 * h.get(c, 0) + min(4, unlocks.get(c, 0) // 3) for c in courses}
    earliness = sum(i * weight[c] * v for (c, i), v in x.items())

    if prefs.objective == "balance":
        m.Minimize(100_000 * sum(late) + 5_000 * sum(hard_excess) + 1_000 * max_w + 200 * spread
                   + 500 * G + earliness)
    else:
        m.Minimize(100_000 * G + 50_000 * sum(late) + 5_000 * sum(hard_excess) + 40 * spread
                   + 10 * max_w + 200 * earliness)

    if hint:
        for (c, i), v in x.items():
            m.AddHint(v, 1 if hint.placement.get(c) == terms[i] else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8
    st = solver.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Plan(terms=terms, placement={}, unscheduled=sorted(courses), method="cp-sat",
                    status=solver.StatusName(st),
                    notes=["CP-SAT found no plan that meets every constraint (see validation for why); "
                           "try more terms, summer/winter, a higher credit cap, or fewer locked courses"])
    placement = {c: terms[i] for (c, i), v in x.items() if solver.Value(v)}
    filler = {terms[i]: solver.Value(fill[i]) / 2 for i in range(T) if solver.Value(fill[i])}
    return Plan(terms=terms, placement=placement, filler=filler, method="cp-sat",
                status=solver.StatusName(st).lower())
