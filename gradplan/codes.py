"""Course codes, code patterns and terms: the vocabulary every other module shares."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

CODE_RE = re.compile(r"\b(\d{2}):(\d{3}):(\d{3}[A-Z]?)\b")
SHORT_CODE_RE = re.compile(r"(?<![:\d])(\d{3}):(\d{3})(?![:\d])")


def normalize_code(text: str) -> str | None:
    """'01:198:111', '198:111' (assumes school 01) -> '01:198:111'."""
    m = CODE_RE.search(text or "")
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
    m = SHORT_CODE_RE.search(text or "")
    if m:
        return f"01:{m.group(1)}:{m.group(2)}"
    return None


def number(code: str) -> int:
    return int(re.match(r"\d+", code.split(":")[2]).group(0))


def level(code: str) -> int:
    """01:198:344 -> 300."""
    return (number(code) // 100) * 100


def subject(code: str) -> str:
    """01:198:344 -> 01:198."""
    return ":".join(code.split(":")[:2])


def matches(code: str, pattern: str) -> bool:
    """Patterns: exact code, '01:640:3xx' (a level), '01:198:*' (whole subject), '01:640:3xx+' (300 and up)."""
    if pattern == code:
        return True
    try:
        psub, pnum = pattern.rsplit(":", 1)
    except ValueError:
        return False
    if subject(code) != psub:
        return False
    if pnum == "*":
        return True
    m = re.fullmatch(r"(\d)xx(\+?)", pnum)
    if m:
        lv = int(m.group(1)) * 100
        return level(code) >= lv if m.group(2) else level(code) == lv
    return False


def is_pattern(p: str) -> bool:
    return "x" in p.split(":")[-1] or p.endswith("*")


SEASONS = {0: "Winter", 1: "Spring", 7: "Summer", 9: "Fall"}
SEASON_CODES = {v.lower(): k for k, v in SEASONS.items()}
SEASON_ORDER = [0, 1, 7, 9]          # a calendar year: winter session (Jan), spring, summer, fall


@total_ordering
@dataclass(frozen=True)
class Term:
    year: int
    season: int                       # SOC term code: 0 winter, 1 spring, 7 summer, 9 fall

    @classmethod
    def parse(cls, text: str | "Term") -> "Term":
        if isinstance(text, Term):
            return text
        s = str(text).strip()
        m = re.fullmatch(r"(\d{4})[_ -]?([0179])", s)
        if m:
            return cls(int(m.group(1)), int(m.group(2)))
        m = re.fullmatch(r"(?i)(winter|spring|summer|fall)\s*(\d{4})", s) or None
        if m:
            return cls(int(m.group(2)), SEASON_CODES[m.group(1).lower()])
        m = re.fullmatch(r"(?i)(\d{4})\s*(winter|spring|summer|fall)", s)
        if m:
            return cls(int(m.group(1)), SEASON_CODES[m.group(2).lower()])
        raise ValueError(f"Can't read term {text!r}; use e.g. 'Fall 2027' or '2027_9'")

    @property
    def key(self) -> str:
        return f"{self.year}_{self.season}"

    @property
    def name(self) -> str:
        return f"{SEASONS[self.season]} {self.year}"

    @property
    def is_regular(self) -> bool:
        return self.season in (1, 9)

    def _ord(self):
        return (self.year, SEASON_ORDER.index(self.season))

    def __lt__(self, other: "Term") -> bool:
        return self._ord() < other._ord()

    def next(self) -> "Term":
        i = SEASON_ORDER.index(self.season)
        if i == len(SEASON_ORDER) - 1:
            return Term(self.year + 1, SEASON_ORDER[0])
        return Term(self.year, SEASON_ORDER[i + 1])

    def __str__(self) -> str:
        return self.name


def term_range(start: Term, end: Term, seasons: set[int]) -> list[Term]:
    out, t = [], start
    while t <= end:
        if t.season in seasons:
            out.append(t)
        t = t.next()
    return out
