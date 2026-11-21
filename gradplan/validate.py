"""Re-check a finished plan from scratch and find its critical path.

Validation doesn't trust the scheduler: it re-evaluates every prerequisite tree
against what is finished before each term, checks offering predictions, credit
caps, locks, and re-runs the requirement audit on done + planned courses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph import plan_edges
from .prereqs import satisfied
from .programs import Program
from .schedule import Plan, Prefs
from .selection import audit
from .soc import Catalog


@dataclass
class Issue:
    level: str          # "error" | "risk" | "info"
    code: str | None
    message: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)
    slack: dict[str, int] = field(default_factory=dict)      # course -> terms it could slip
    next_offered: dict[str, str | None] = field(default_factory=dict)
    chains: list[list[str]] = field(default_factory=list)
    unmet: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def add(self, level, code, msg):
        self.issues.append(Issue(level, code, msg))


def critical_path(plan: Plan, catalog: Catalog, done: set[str], prefs: Prefs) -> tuple[dict, dict, list]:
    """Slack of each course: how many of its offerings it could slip past without moving the
    graduation term (credit caps ignored). Slack 0 = missing it delays graduation."""
    courses = list(plan.placement)
    terms = plan.used_terms()
    if not terms:
        return {}, {}, []
    idx = {t: i for i, t in enumerate(terms)}
    edges = plan_edges(catalog, courses, done)
    succ: dict[str, set[str]] = {c: set() for c in courses}
    for c, pre in edges.items():
        for p in pre:
            succ[p].add(c)
    G = len(terms) - 1
    latest: dict[str, int] = {}

    def lat(c: str) -> int:
        if c in latest:
            return latest[c]
        latest[c] = G                      # cycle guard
        bound = G
        for s in succ[c]:
            bound = min(bound, lat(s) - 1)
        if c in prefs.locked:
            bound = min(bound, idx.get(prefs.locked[c], bound))
        i = bound
        while i >= 0 and not catalog.offered(c, terms[i]):
            i -= 1
        latest[c] = i
        return i

    slack, nxt = {}, {}
    for c in courses:
        s = idx[plan.placement[c]]
        L = lat(c)
        slack[c] = sum(1 for i in range(s + 1, L + 1) if catalog.offered(c, terms[i]))
        later = [t for t in plan.terms if t > plan.placement[c] and catalog.offered(c, t)]
        nxt[c] = later[0].name if later else None
    # chains of zero-slack courses linked by prerequisites
    crit = {c for c, v in slack.items() if v == 0}
    chains = []
    roots = [c for c in crit if not (edges[c] & crit)]
    def walk(c, path):
        kids = sorted(succ[c] & crit, key=lambda k: plan.placement[k])
        if not kids:
            chains.append(path)
            return
        for k in kids:
            walk(k, path + [k])
    for r in sorted(roots, key=lambda k: plan.placement[k]):
        walk(r, [r])
    chains.sort(key=len, reverse=True)
    return slack, nxt, chains


def validate(plan: Plan, catalog: Catalog, programs: list[Program], done: set[str],
             in_progress: set[str], prefs: Prefs, policies: dict | None = None) -> Report:
    rep = Report()
    placed = plan.placement
    for c in plan.unscheduled:
        rep.add("error", c, f"{c} could not be placed in any term within the planning horizon")
    for note in plan.notes:
        rep.add("risk", None, note)
    for t in plan.used_terms():
        here = plan.courses_in(t)
        earlier = done | {c for c, tt in placed.items() if tt < t}
        for c in here:
            info = catalog.get(c)
            if not satisfied(info.prereq.tree, earlier, same_term=set(here)):
                rep.add("error", c, f"{c} in {t}: prerequisites not met before that term")
            if not info.in_catalog:
                rep.add("risk", c, f"{c} isn't in the downloaded SOC data: offering and prerequisites unknown")
            elif not info.offering.has_data:
                rep.add("risk", c, f"{c}: no offering history, assumed fall & spring")
            elif not catalog.offered(c, t):
                rep.add("error", c, f"{c} in {t}: not predicted to be offered then ({info.offering.label()})")
            if info.in_catalog and not info.credits_known:
                rep.add("risk", c, f"{c}: SOC lists no fixed credits; assumed {info.credits:g}")
            if info.prereq.flags:
                rep.add("risk", c, f"{c}: prerequisite text needs a manual check ({'; '.join(info.prereq.flags)})")
        load = sum(catalog.get(c).credits for c in here) + plan.filler.get(t, 0)
        if load > prefs.cap(t) + 1e-9:
            rep.add("error", None, f"{t}: {load:g} credits is over the {prefs.cap(t):g} cap")
        if t.is_regular and prefs.fill_electives and load < prefs.floor(t) - 1e-9:
            rep.add("risk", None, f"{t}: {load:g} credits is under the {prefs.floor(t):g} minimum")
        nh = sum(1 for c in here if c in prefs.hard)
        if nh > prefs.max_hard_per_term:
            rep.add("risk", None, f"{t}: {nh} hard courses together ({', '.join(c for c in here if c in prefs.hard)})")
    for c, lt in prefs.locked.items():
        if c in placed and placed[c] != lt:
            rep.add("error", c, f"{c} was locked to {lt} but is planned for {placed[c]}")
        if c not in placed and c not in done:
            rep.add("info", c, f"{c} is locked but isn't needed by the plan's requirements (not added)")
    if prefs.target and plan.last_term() and plan.last_term() > prefs.target:
        rep.add("risk", None, f"Graduation lands in {plan.last_term()}, after the target {prefs.target}")
    for c in sorted(in_progress):
        rep.add("info", c, f"{c} is in progress and assumed passed")

    total = prefs.credits_earned + sum(catalog.get(c).credits for c in placed) + sum(plan.filler.values())
    if prefs.fill_electives and total + 1e-9 < prefs.total_required:
        rep.add("error", None, f"Plan reaches {total:g} credits, short of {prefs.total_required:g}")

    # requirements, from scratch
    have = done | set(placed)
    a = audit(programs, catalog, have, policies)
    rep.unmet = a.unmet
    for u in a.unmet:
        rep.add("error", None, f"{u['program']} / {u['name']}: {u['detail']}")

    rep.slack, rep.next_offered, rep.chains = critical_path(plan, catalog, done, prefs)
    rep.critical = sorted((c for c, s in rep.slack.items() if s == 0), key=lambda c: (placed[c], c))
    for c in rep.critical:
        off = catalog.get(c).offering
        if off.per_year(catalog.threshold) <= 1:
            rep.add("risk", c, f"{c} is on the critical path and runs {off.label()}: "
                               f"missing it in {placed[c]} delays graduation")
    return rep
