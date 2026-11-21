"""Career outcomes by major (Rutgers–New Brunswick vs. national), as a blueprint at /outcomes.

Reads ``data/processed/majors.json`` and ``meta.json``, built by ``python -m pipeline.build``.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template, request
from jinja2 import Undefined

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
MAX_COMPARE = 3

bp = Blueprint("outcomes", __name__, url_prefix="/outcomes")


@lru_cache(maxsize=1)
def load() -> tuple[list[dict], dict, dict[str, dict]]:
    majors = json.loads((DATA / "majors.json").read_text())
    meta = json.loads((DATA / "meta.json").read_text())
    return majors, meta, {m["cip4"]: m for m in majors}


def summary(m: dict) -> dict:
    """The few fields the search table (and the other tools' outcome cards) need."""
    sr = (m["scorecard"] or {}).get("rutgers") or {}
    sn = (m["scorecard"] or {}).get("national") or {}
    pr = (m["pseo"] or {}).get("rutgers") or {}
    return {
        "cip4": m["cip4"],
        "title": m["title"],
        "rutgers_majors": m.get("rutgers_majors", []),
        "cip2_title": m["cip2_title"],
        "school": m["fds"]["school_name"],
        "rutgers_1yr": sr.get("earn_1yr"),
        "national_1yr": sn.get("mdn_1yr"),
        "rutgers_5yr": sr.get("earn_5yr"),
        "national_5yr": sn.get("mdn_5yr"),
        "pseo_y10": (pr.get("y10") or {}).get("p50"),
        "growth_pct": (m.get("bls") or {}).get("growth_pct"),
        "completers": sr.get("completers_y2") or sr.get("completers_y1"),
    }


def as_number(v) -> float | None:
    """Template helper: None, missing (Undefined) and non-numeric values all render as a dash."""
    if isinstance(v, (bool, Undefined)) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_compare(raw: str | None, index: dict) -> list[str]:
    cips = []
    for c in (raw or "").split(","):
        c = c.strip()
        if c and c in index and c not in cips:
            cips.append(c)
    return cips[:MAX_COMPARE]


def money(v):
    v = as_number(v)
    return "—" if v is None else f"${v:,.0f}"


def pct(v, digits=0):
    v = as_number(v)
    return "—" if v is None else f"{v:.{digits}f}%"


def num(v):
    v = as_number(v)
    return "—" if v is None else f"{v:,.0f}"


def _plannable() -> dict[str, list[dict]]:
    from .programs import by_cip, registry
    return by_cip(registry())


@bp.app_context_processor
def inject_meta():
    return {"meta": load()[1]}


@bp.route("/")
def home():
    majors, _, _ = load()
    return render_template("outcomes/index.html", rows=[summary(m) for m in majors], plannable=_plannable())


@bp.route("/major/<cip4>")
def major(cip4: str):
    _, meta, index = load()
    m = index.get(cip4)
    if not m:
        abort(404)
    return render_template("outcomes/major.html", m=m, caveats=meta["caveats"],
                           programs=_plannable().get(cip4, []))


@bp.route("/compare")
def compare():
    majors, meta, index = load()
    cips = parse_compare(request.args.get("c"), index)
    return render_template(
        "outcomes/compare.html", majors=[index[c] for c in cips], caveats=meta["caveats"],
        all_rows=[summary(m) for m in majors], max_compare=MAX_COMPARE,
    )


@bp.route("/sources")
def sources():
    _, meta, _ = load()
    return render_template("outcomes/sources.html", caveats=meta["caveats"])


@bp.route("/api/majors")
def api_majors():
    q = (request.args.get("q") or "").lower().strip()
    rows = [summary(m) for m in load()[0]]
    if q:
        rows = [r for r in rows if q in " ".join([r["cip4"], r["title"], *r["rutgers_majors"]]).lower()]
    return jsonify(rows)


@bp.route("/api/major/<cip4>")
def api_major(cip4: str):
    m = load()[2].get(cip4)
    if not m:
        abort(404)
    return jsonify(m)
