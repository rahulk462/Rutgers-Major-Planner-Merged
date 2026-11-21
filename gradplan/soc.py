"""Rutgers Schedule of Classes (SOC) data: download, cache, and estimate offering patterns.

    https://sis.rutgers.edu/soc/api/courses.json?year=2026&term=1&campus=NB
    term codes: 0 winter, 1 spring, 7 summer, 9 fall

One request returns every course in a term (~4,500 for NB, ~20 MB). We keep a
slim "pack" (``data/soc/soc_nb.json``) with, per course, the title, credits and
prerequisite text, plus which courses ran in each term. Offering patterns are
estimated from that history. They are a guess, not a guarantee.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .codes import SEASONS, Term
from .prereqs import ParseResult, map_codes, parse

SOC_API = "https://sis.rutgers.edu/soc/api/courses.json"
DEFAULT_PACK = Path(__file__).resolve().parent.parent / "data" / "soc" / "soc_nb.json"


# ---------------------------------------------------------------- download

def fetch_term(year: int, term: int, campus: str = "NB", timeout: int = 180) -> list[dict]:
    url = f"{SOC_API}?year={year}&term={term}&campus={campus}"
    req = urllib.request.Request(url, headers={"User-Agent": "gradplan/0.1 (personal degree planner)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def build_pack(terms: list[Term], subjects: set[str] | None = None, campus: str = "NB",
               out: Path = DEFAULT_PACK, delay: float = 2.0, merge: bool = True) -> dict:
    """Download each term (politely, one at a time) and write the slim pack.

    ``subjects`` are like '01:198'; None keeps every course. With ``merge`` the
    new terms are added to an existing pack."""
    pack = load_pack(out) if (merge and out.exists()) else {"terms": [], "catalog": {}, "offerings": {}}
    for i, t in enumerate(sorted(terms)):
        if i:
            time.sleep(delay)
        rows = fetch_term(t.year, t.season, campus)
        offered = []
        for c in rows:
            code = c.get("courseString")
            if not code:
                continue
            if subjects and ":".join(code.split(":")[:2]) not in subjects:
                continue
            offered.append(code)
            pack["catalog"][code] = {
                "title": ((c.get("expandedTitle") or "").strip() or (c.get("title") or "").strip()),
                "credits": c.get("credits"),
                "prereq": c.get("preReqNotes") or "",
                "core": sorted({cc.get("code") or cc.get("coreCode") for cc in (c.get("coreCodes") or [])} - {None}),
            }
        pack["offerings"][t.key] = sorted(set(offered))
        if t.key not in pack["terms"]:
            pack["terms"].append(t.key)
    pack["terms"] = sorted(pack["terms"], key=lambda k: Term.parse(k))
    pack["campus"] = campus
    pack["source"] = SOC_API
    pack["fetched"] = time.strftime("%Y-%m-%d")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, separators=(",", ":")))
    return pack


def load_pack(path: Path | str = DEFAULT_PACK) -> dict:
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- equivalents

class Equivalents:
    """Groups of codes that satisfy each other (renumbered or honors versions).
    The first code of each group is the one the planner schedules."""

    def __init__(self, groups: list[list[str]] | None = None):
        self.groups = [list(g) for g in (groups or [])]
        self._canon: dict[str, str] = {}
        for g in self.groups:
            for c in g:
                self._canon[c] = g[0]

    def canon(self, code: str) -> str:
        return self._canon.get(code, code)

    def members(self, code: str) -> list[str]:
        c = self.canon(code)
        for g in self.groups:
            if g[0] == c:
                return g
        return [code]


# ---------------------------------------------------------------- offerings

@dataclass
class Offering:
    """How often a course ran in the observed terms, per season."""
    seen: dict[int, int] = field(default_factory=dict)       # season -> terms offered
    observed: dict[int, int] = field(default_factory=dict)   # season -> terms observed (since first offered)
    years: dict[int, set[int]] = field(default_factory=dict)  # season -> years offered
    last: str | None = None
    has_data: bool = True

    def freq(self, season: int) -> float:
        n = self.observed.get(season, 0)
        return self.seen.get(season, 0) / n if n else 0.0

    def parity(self, season: int) -> int | None:
        """Every-other-year pattern (returns the year parity it runs in), if the data shows one."""
        yrs = sorted(self.years.get(season, ()))
        n_obs = self.observed.get(season, 0)
        if len(yrs) >= 1 and n_obs >= 3 and 0.25 <= self.freq(season) <= 0.75:
            par = {y % 2 for y in yrs}
            if len(par) == 1:
                return par.pop()
        return None

    def predicts(self, term: Term, threshold: float = 0.5) -> bool:
        if not self.has_data:
            return term.season in (1, 9)          # unknown: assume a regular-term course
        par = self.parity(term.season)
        if par is not None:
            return term.year % 2 == par
        return self.freq(term.season) >= threshold

    def per_year(self, threshold: float = 0.5) -> int:
        """How many regular (fall/spring) terms per year it is predicted to run."""
        if not self.has_data:
            return 2
        n = 0
        for s in (1, 9):
            if self.parity(s) is not None:
                n += 0.5
            elif self.freq(s) >= threshold:
                n += 1
        return n

    def label(self, threshold: float = 0.5) -> str:
        if not self.has_data:
            return "no offering data (assumed fall & spring)"
        parts = []
        for s in (9, 1, 7, 0):
            par = self.parity(s)
            if par is not None:
                parts.append(f"{SEASONS[s]} in {'even' if par == 0 else 'odd'} years")
            elif self.freq(s) >= threshold:
                parts.append(SEASONS[s])
        if not parts:
            return f"rarely offered (last {Term.parse(self.last).name if self.last else 'never'})"
        if parts == ["Fall"]:
            return "Fall only"
        if parts == ["Spring"]:
            return "Spring only"
        if parts == ["Fall", "Spring"]:
            return "Fall & Spring"
        return " / ".join(parts)


def estimate_offerings(pack: dict, codes: list[str], eq: Equivalents) -> dict[str, Offering]:
    """Offering pattern per (canonical) code, merging equivalent codes' histories."""
    terms = [Term.parse(k) for k in pack["terms"]]
    sets = {k: set(v) for k, v in pack["offerings"].items()}
    out: dict[str, Offering] = {}
    for code in codes:
        members = set(eq.members(code)) | {code}
        offered_terms = [t for t in terms if sets.get(t.key, set()) & members]
        off = Offering()
        if not offered_terms:
            off.has_data = False
            out[code] = off
            continue
        first = min(offered_terms)
        for t in terms:
            if t < first:           # before the course (or its new number) existed
                continue
            off.observed[t.season] = off.observed.get(t.season, 0) + 1
            if t in offered_terms:
                off.seen[t.season] = off.seen.get(t.season, 0) + 1
                off.years.setdefault(t.season, set()).add(t.year)
        off.last = max(offered_terms).key
        out[code] = off
    return out


# ---------------------------------------------------------------- catalog

@dataclass
class Course:
    code: str
    title: str = ""
    credits: float = 3.0
    prereq: ParseResult = field(default_factory=lambda: ParseResult(None))
    offering: Offering = field(default_factory=Offering)
    in_catalog: bool = True
    core: list[str] = field(default_factory=list)
    credits_known: bool = True


class Catalog:
    def __init__(self, pack: dict, eq: Equivalents | None = None,
                 overrides: dict[str, str] | None = None, threshold: float = 0.5,
                 extra: dict[str, dict] | None = None):
        self.pack = pack
        self.eq = eq or Equivalents()
        self.threshold = threshold
        raw = dict(pack["catalog"])
        for code, info in (extra or {}).items():     # hand-written course facts
            raw[code] = {**raw.get(code, {}), **info}
        self.courses: dict[str, Course] = {}
        canon_codes = sorted({self.eq.canon(c) for c in raw} | {g[0] for g in self.eq.groups})
        offerings = estimate_offerings(pack, canon_codes, self.eq)
        for code in canon_codes:
            info = raw.get(code) or next((raw[m] for m in self.eq.members(code) if m in raw), None)
            if info is None:
                continue
            ov = (overrides or {}).get(code)
            if ov is not None:
                pr = parse(str(ov), source="override")
            else:
                pr = parse(info.get("prereq", ""))
            pr.tree = map_codes(pr.tree, self.eq.canon)
            cr = info.get("credits")
            known = cr not in (None, "", 0, 0.0)
            self.courses[code] = Course(code=code, title=info.get("title", ""),
                                        credits=float(cr) if known else 3.0,
                                        prereq=pr, offering=offerings[code], core=info.get("core", []),
                                        credits_known=known)
        self.terms_seen = [Term.parse(k) for k in pack["terms"]]

    def __contains__(self, code: str) -> bool:
        return self.eq.canon(code) in self.courses

    def get(self, code: str, default_credits: float = 3.0) -> Course:
        c = self.eq.canon(code)
        if c in self.courses:
            return self.courses[c]
        return Course(code=c, title="(not in SOC data)", credits=default_credits,
                      offering=Offering(has_data=False), in_catalog=False)

    def offered(self, code: str, term: Term) -> bool:
        return self.get(code).offering.predicts(term, self.threshold)

    def unlock_counts(self) -> dict[str, int]:
        """How many catalog courses list each course as a prerequisite."""
        if not hasattr(self, "_unlocks"):
            from .prereqs import codes
            cnt: dict[str, int] = {}
            for c in self.courses.values():
                for p in codes(c.prereq.tree):
                    cnt[p] = cnt.get(p, 0) + 1
            self._unlocks = cnt
        return self._unlocks

    def all_codes(self) -> list[str]:
        return list(self.courses)
