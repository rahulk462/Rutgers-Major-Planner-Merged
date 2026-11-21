"""Join every source on CIP codes and write data/processed/*.json for the web app.

Run:  python -m pipeline.build
"""
from __future__ import annotations

import json
import math
import re
from datetime import date

import pandas as pd

from . import config, fds, national, pseo, scorecard
from .caveats import CAVEATS

UNDERGRAD_SCHOOLS = {"ALL", "sas", "eng", "business", "sebs", "smlr", "sci", "arts", "bloustein", "ssw"}


def clean(obj):
    """Make pandas/numpy values JSON-safe (NaN -> None, numpy scalars -> python)."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        obj = obj.item()
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        return int(obj) if obj.is_integer() else round(obj, 3)
    return obj


def slugify(cip4: str, title: str) -> str:
    return f"{cip4.replace('.', '')}-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def _row(df: pd.DataFrame, key: str, value: str) -> dict | None:
    sub = df[df[key] == value]
    return None if sub.empty else sub.iloc[0].to_dict()


def _years(rec: dict | None, years: list[str]) -> dict | None:
    if not rec:
        return None
    out = {}
    for y in years:
        vals = {p: rec.get(f"{y}_{p}") for p in ["p25", "p50", "p75", "n"]}
        if any(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in vals.values()):
            out[y] = vals
    return out or None


def _school_for(cip4: str, table: pd.DataFrame) -> str:
    best, best_len = "ALL", -1
    for prefix, school in zip(table["cip_prefix"], table["school"]):
        if cip4.startswith(prefix) and len(prefix) > best_len:
            best, best_len = school, len(prefix)
    return best


def _flows_for(cip2: str, fl: dict, lab: dict) -> dict | None:
    tot = fl["totals"][fl["totals"]["cip2"] == cip2]
    if tot.empty:
        return None
    t = tot.iloc[0]
    out = {"cip2": cip2, "employment": {}, "industries": [], "regions": []}
    for y in pseo.YEARS:
        emp, nme, inst = t[f"{y}_emp"], t[f"{y}_nme"], t[f"{y}_emp_instate"]
        if pd.notna(emp):
            out["employment"][y] = {
                "employed": emp,
                "not_employed": nme,
                "employed_share": emp / (emp + nme) * 100 if pd.notna(nme) and emp + nme else None,
                "in_state_share": inst / emp * 100 if pd.notna(inst) and emp else None,
            }

    def shares(df: pd.DataFrame, key: str, labels: dict) -> list[dict]:
        sub = df[df["cip2"] == cip2]
        rows = []
        for y in pseo.YEARS:
            total = sub[f"{y}_emp"].sum()
            for r in sub.itertuples():
                v = getattr(r, f"{y}_emp")
                if total and pd.notna(v):
                    rows.append({"code": getattr(r, key), "year": y, "count": v, "share": v / total * 100})
        if not rows:
            return []
        long = pd.DataFrame(rows)
        wide = long.pivot_table(index="code", columns="year", values="share").reset_index()
        counts = long[long["year"] == "y1"].set_index("code")["count"]
        result = []
        for r in wide.itertuples():
            result.append({
                "code": r.code, "label": labels.get(r.code, r.code),
                **{y: getattr(r, y, None) for y in pseo.YEARS},
                "count_y1": counts.get(r.code),
            })
        return sorted(result, key=lambda d: -(d.get("y1") or 0))

    out["industries"] = shares(fl["industry"], "industry", lab["industry"])
    out["regions"] = shares(fl["division"], "geography", lab["division"])
    return out


def build() -> dict:
    sc_rut, sc_nat = scorecard.build()
    pe = pseo.earnings()
    fl = pseo.flows()
    lab = pseo.labels()
    cip_labels = pd.read_csv(config.SOURCES["pseo_label_cipcode"]["path"], dtype=str)
    cip_labels = dict(zip(cip_labels["cipcode"], cip_labels["label"]))

    fds_recs = fds.load()
    fds_school = {r["school"]: r for r in fds_recs if r["major_id"] is None}
    fds_major_x = pd.read_csv(config.CROSSWALKS / "fds_major_cip.csv", dtype=str)
    fds_major = {}
    for r in fds_recs:
        if r["major_id"] is None:
            continue
        hit = fds_major_x[(fds_major_x["school"].str.lower() == (r["school"] or "").lower())
                          & (fds_major_x["major_id"] == r["major_id"])]
        if not hit.empty:
            fds_major.setdefault(hit.iloc[0]["cip4"], []).append(r)
    school_x = pd.read_csv(config.CROSSWALKS / "cip4_fds_school.csv", dtype=str)

    ny = national.nyfed_by_major()
    ny_x = national.nyfed_crosswalk()
    occ = national.bls_occupations()
    soc_x = national.cip_soc()
    nace_t = national.nace()

    rut_pseo = pe["rutgers"]
    cips = sorted(set(sc_rut["cip4"]) | set(rut_pseo["cip4"]))
    majors = []
    for cip4 in cips:
        sr = _row(sc_rut, "cip4", cip4)
        sn = _row(sc_nat, "cip4", cip4)
        pr = _row(rut_pseo, "cip4", cip4)
        pn = _row(pe["nj"], "cip4", cip4)
        title = (sr or sn or {}).get("cip_title") or cip_labels.get(cip4, cip4)
        cip2 = cip4[:2]
        cohorts = pe["rutgers_cohorts"][pe["rutgers_cohorts"]["cip4"] == cip4].sort_values("grad_cohort")
        school_code = _school_for(cip4, school_x)
        school_rec = fds_school.get(school_code) if school_code in UNDERGRAD_SCHOOLS else None
        major_recs = fds_major.get(cip4, [])

        candidates = [(sr or {}).get(k) for k in ["earn_1yr", "earn_4yr", "earn_5yr"]]
        candidates += [(pr or {}).get(k) for k in ["y1_p50", "y5_p50", "y10_p50"]]
        has_rutgers_earnings = any(pd.notna(v) for v in candidates if v is not None)
        rec = {
            "cip4": cip4,
            "slug": slugify(cip4, title),
            "title": title,
            "cip2": cip2,
            "cip2_title": cip_labels.get(cip2, cip2),
            "rutgers_majors": sorted(set(fds_major_x.loc[fds_major_x["cip4"] == cip4, "major_name"])),
            "has_rutgers_earnings": bool(has_rutgers_earnings),
            "scorecard": {
                "rutgers": sr and {k: v for k, v in sr.items() if k not in {"cip4", "cip_title"}},
                "national": sn and {k: v for k, v in sn.items() if k not in {"cip4", "cip_title"}},
            },
            "pseo": {
                "rutgers": _years(pr, pseo.YEARS),
                "nj": _years(pn, pseo.YEARS),
                "cohorts": [
                    {"cohort": int(r.grad_cohort), "span": int(r.grad_cohort_years),
                     "y1_p50": r.y1_p50, "y5_p50": r.y5_p50, "y10_p50": r.y10_p50,
                     "y1_n": r.y1_n}
                    for r in cohorts.itertuples()
                ],
                "flows": _flows_for(cip2, fl, lab),
            },
            "fds": {
                "school_code": school_code,
                "school_name": config.FDS_SCHOOLS.get(school_code, school_code),
                "school": school_rec,
                "majors": major_recs,
                "overall": fds_school.get("ALL"),
            },
            "nyfed": national.nyfed_for_cip(cip4, ny_x, ny),
            "bls": national.bls_for_cip(cip4, soc_x, occ),
            "nace": national.nace_for_cip(cip4, nace_t),
        }
        majors.append(clean(rec))

    meta = clean({
        "built": date.today().isoformat(),
        "institution": config.INSTITUTION_NAME,
        "scope_note": "Rutgers–New Brunswick only; Camden and Newark campuses are excluded.",
        "versions": {
            "scorecard": config.SOURCES["scorecard_fos"]["url"].rsplit("/", 1)[-1],
            "pseo": pseo.version(),
            "nyfed": national.nyfed_release_note(),
            "bls": f"Employment Projections {occ.attrs.get('years', '')}",
            "fds_class_years": sorted({r["class_year"] for r in fds_recs if r["class_year"]}),
        },
        "bls_total_growth": national.bls_total_growth(),
        "fds_overall": fds_school.get("ALL"),
        "fds_schools": [fds_school[k] for k in config.FDS_SCHOOLS if k in fds_school],
        "caveats": CAVEATS,
        "sources": {k: v["url"] for k, v in config.SOURCES.items()},
    })
    return {"majors": majors, "meta": meta}


def write(result: dict) -> None:
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    (config.PROCESSED / "majors.json").write_text(json.dumps(result["majors"], indent=1, ensure_ascii=False))
    (config.PROCESSED / "meta.json").write_text(json.dumps(result["meta"], indent=1, ensure_ascii=False))


def main() -> None:
    result = build()
    write(result)
    n = len(result["majors"])
    n_earn = sum(m["has_rutgers_earnings"] for m in result["majors"])
    print(f"Wrote {n} majors ({n_earn} with Rutgers earnings) to {config.PROCESSED}")


if __name__ == "__main__":
    main()
