"""Program requirement definitions (YAML) and the rule types they use.

Rule types::

    required   every listed course                       courses: [...]
    choose     N courses from a list or pattern          count: N, from: [...], exclude: [...]
    credits    at least X credits from a list/pattern    min_credits: X, from: [...]
    level      N courses at a level or higher            count: N, subject: 01:640, min_level: 300
    one_set    finish any one of several sequences       sets: [[...], [...]]

``choose``/``credits``/``level`` take optional ``rules``: ``{min|max: K, from: [...]}`` limits on
the courses used, e.g. "at least 2 at 300+" or "at most 1 independent study".

Patterns: ``01:640:3xx`` (that level), ``01:640:3xx+`` (that level and up), ``01:198:*``.

Double counting: within one program a course fills at most one requirement (set
``overlap: true`` on a requirement to let it share). Between programs, limits
come from ``double_count`` in the program file (``{with: <id>, max: N}`` or
``max_shared: N`` for any other program) and from the plan config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .codes import is_pattern, matches

PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"


@dataclass
class Rule:
    from_: list[str]
    min: int | None = None
    max: int | None = None
    label: str = ""


@dataclass
class Requirement:
    id: str
    name: str
    type: str
    courses: list[str] = field(default_factory=list)      # required
    from_: list[str] = field(default_factory=list)        # choose / credits / level
    exclude: list[str] = field(default_factory=list)
    count: int = 0
    min_credits: float = 0
    sets: list[list[str]] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    overlap: bool = False

    def in_pool(self, code: str) -> bool:
        if any(matches(code, e) for e in self.exclude):
            return False
        if self.type == "required":
            return code in self.courses
        if self.type == "one_set":
            return any(code in s for s in self.sets)
        return any(matches(code, p) for p in self.from_)

    def explicit_codes(self) -> list[str]:
        if self.type == "required":
            return list(self.courses)
        if self.type == "one_set":
            return [c for s in self.sets for c in s]
        return [p for p in self.from_ if not is_pattern(p)]

    def patterns(self) -> list[str]:
        return [p for p in self.from_ if is_pattern(p)]


@dataclass
class Program:
    id: str
    name: str
    kind: str = "major"
    default_credits: float = 3
    requirements: list[Requirement] = field(default_factory=list)
    double_count: list[dict] = field(default_factory=list)
    max_shared: int | None = None
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def shared_limit(self, other: str) -> int | None:
        for d in self.double_count:
            if d.get("with") == other:
                return d.get("max")
        return self.max_shared


def _req(d: dict, eq_canon) -> Requirement:
    t = d.get("type", "required")
    if t == "all":
        t = "required"
    canon = (lambda xs: [eq_canon(x) if not is_pattern(x) else x for x in xs])
    frm = canon(d.get("from", []))
    if t == "level":
        subj = d["subject"]
        frm = [f"{subj}:{int(d.get('min_level', 300)) // 100}xx+"]
    return Requirement(
        id=d["id"], name=d.get("name", d["id"]), type=t,
        courses=canon(d.get("courses", [])), from_=frm, exclude=d.get("exclude", []),
        count=int(d.get("count", 0)), min_credits=float(d.get("min_credits", 0)),
        sets=[canon(s) for s in d.get("sets", [])],
        rules=[Rule(from_=canon(r["from"]), min=r.get("min"), max=r.get("max"), label=r.get("label", ""))
               for r in d.get("rules", [])],
        overlap=bool(d.get("overlap", False)))


def load_program(path: Path, eq_canon=lambda c: c) -> Program:
    d = yaml.safe_load(Path(path).read_text())
    return Program(id=d["id"], name=d.get("name", d["id"]), kind=d.get("kind", "major"),
                   default_credits=float(d.get("default_credits", 3)),
                   requirements=[_req(r, eq_canon) for r in d.get("requirements", [])],
                   double_count=d.get("double_count", []) or [], max_shared=d.get("max_shared"),
                   notes=d.get("notes", []) or [], sources=d.get("sources", []) or [])


def load_programs(ids: list[str], dirs: list[Path] | None = None, eq_canon=lambda c: c) -> list[Program]:
    dirs = dirs or [PROGRAMS_DIR]
    out = []
    for pid in ids:
        for d in dirs:
            p = Path(d) / f"{pid}.yaml"
            if p.exists():
                out.append(load_program(p, eq_canon))
                break
        else:
            raise FileNotFoundError(f"No program file {pid}.yaml in {', '.join(map(str, dirs))}")
    return out


def available_programs(dirs: list[Path] | None = None) -> list[tuple[str, str]]:
    out = []
    for d in dirs or [PROGRAMS_DIR]:
        for p in sorted(Path(d).glob("*.yaml")):
            y = yaml.safe_load(p.read_text())
            out.append((y["id"], y.get("name", y["id"])))
    return out
