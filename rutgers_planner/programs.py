"""One list of programs across the three tools.

The What-If tool (``rutgers_whatif/programs/*.json``) and the graduation planner
(``programs/*.yaml``) each define their own requirement files, under the same ids
(``cs-bs``, ``math-minor``, ...). The outcomes data is keyed by federal CIP code.
This module joins them so every page can link a program to the other two tools.
"""
from __future__ import annotations

# Program id prefix -> 4-digit CIP code in the outcomes data. Longest prefix wins.
CIP_BY_PREFIX = {
    "cs-": "11.01",        # Computer and Information Sciences, General (Rutgers: Computer Science)
    "math-": "27.01",      # Mathematics
    "stat-": "27.05",      # Statistics
    "statmath-": "27.05",  # Statistics - Mathematics is reported under Statistics
    "ds-": "30.70",        # Data Science
}

KIND_ORDER = {"major": 0, "minor": 1}


def cip_for(program_id: str) -> str | None:
    best = None
    for prefix, cip in CIP_BY_PREFIX.items():
        if program_id.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, cip)
    return best[1] if best else None


def registry(outcomes_index: dict | None = None) -> list[dict]:
    """Every program either tool knows, with where it can be opened and its field's outcomes summary."""
    from gradplan.web import list_programs as planner_programs
    from rutgers_whatif.requirements import load_programs as whatif_programs

    from .outcomes import summary

    out: dict[str, dict] = {}
    for pid, p in whatif_programs().items():
        out[pid] = {"id": pid, "name": p["name"], "kind": p.get("kind", "major"), "whatif": True, "planner": False}
    for p in planner_programs():
        row = out.setdefault(p["id"], {"id": p["id"], "name": p["name"], "kind": p.get("kind", "major"),
                                       "whatif": False})
        row["planner"] = True
    for row in out.values():
        row["cip4"] = cip_for(row["id"])
        m = (outcomes_index or {}).get(row["cip4"]) if row["cip4"] else None
        row["outcomes"] = summary(m) if m else None
    return sorted(out.values(), key=lambda r: (KIND_ORDER.get(r["kind"], 2), r["name"]))


def by_cip(programs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for p in programs:
        if p["cip4"]:
            groups.setdefault(p["cip4"], []).append(p)
    return groups
