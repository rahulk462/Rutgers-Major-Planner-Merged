"""Completed and in-progress courses from the What-If Scraper's Degree Navigator export.

Accepted inputs (any mix):

* ``audit.json`` written by the scraper: ``{"courses": [{code, credits, grade, term, ...}]}``
* ``whatif.sqlite``: the latest row of ``snapshots`` and its ``courses``
* ``manual_courses.json``: AP / transfer credit added by hand (a plain list)
* a CSV with columns ``code,title,credits,grade,term``
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .codes import normalize_code

GRADE_PASS = {"A", "B+", "B", "C+", "C", "D", "P", "PA", "S", "T", "TR", "TZ", "CR"}
NO_CREDIT = {"F", "W", "NC", "U", "INC", "IN", "WF", "NG", "AU", "R"}
IN_PROGRESS = {"", "IP", "PR", "TBA", "*", "-", "CURRENT", "IN PROGRESS", "REG", "REGISTERED"}
TRANSFER_RE = re.compile(r"\b(AP|transfer|test credit|IB|CLEP|TR|TZ)\b", re.I)


@dataclass
class Taken:
    code: str
    credits: float | None = None
    grade: str = ""
    term: str | None = None
    title: str = ""
    transfer: bool = False
    source: str = ""

    @property
    def status(self) -> str:
        g = (self.grade or "").strip().upper()
        if self.transfer or g in {"T", "TR", "TZ", "CR"}:
            return "passed"
        if g in IN_PROGRESS:
            return "in_progress"
        if g in NO_CREDIT:
            return "failed"
        return "passed"


def _row(d: dict, source: str) -> Taken | None:
    d = {str(k).strip().lower(): v for k, v in d.items()}
    code = normalize_code(str(d.get("code", "")))
    if not code:
        return None
    cr = d.get("credits")
    try:
        cr = float(cr) if cr not in (None, "") else None
    except ValueError:
        cr = None
    term = d.get("term")
    transfer = bool(d.get("transfer")) or bool(TRANSFER_RE.search(str(term or "")))
    return Taken(code=code, credits=cr, grade=str(d.get("grade") or "").strip(), term=term,
                 title=str(d.get("title") or ""), transfer=transfer, source=source)


def load_file(path: Path | str) -> list[Taken]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".sqlite", ".db", ".sqlite3"):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return []
            cur = con.execute("SELECT code, title, credits, grade, term, source FROM courses "
                              "WHERE snapshot_id = ?", (row[0],))
            cols = [c[0] for c in cur.description]
            return [t for r in cur.fetchall() if (t := _row(dict(zip(cols, r)), "sqlite"))]
        finally:
            con.close()
    if suffix == ".json":
        data = json.loads(path.read_text())
        rows = data.get("courses", []) if isinstance(data, dict) else data
        return [t for r in rows if (t := _row(r, path.name))]
    with path.open(newline="") as fh:
        return [t for r in csv.DictReader(fh) if (t := _row(r, path.name))]


def load(paths: list[Path | str], extra: list[dict] | None = None) -> list[Taken]:
    """Merge sources. A later passed grade beats an earlier failed one; duplicates collapse."""
    best: dict[str, Taken] = {}
    rank = {"passed": 3, "in_progress": 2, "failed": 1}
    rows: list[Taken] = []
    for p in paths:
        if Path(p).exists():
            rows.extend(load_file(p))
    rows.extend(t for r in (extra or []) if (t := _row(r, "config")))
    for t in rows:
        cur = best.get(t.code)
        if cur is None or rank[t.status] > rank[cur.status]:
            best[t.code] = t
    return list(best.values())
