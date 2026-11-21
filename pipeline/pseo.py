"""Census Post-Secondary Employment Outcomes (PSEO) for Rutgers–New Brunswick.

Earnings (pseoe) are published at CIP 4-digit; flows (pseof: industry and
Census-division destinations) only at CIP 2-digit.
"""
from __future__ import annotations

import pandas as pd

from . import config

# PSEO status flags that mean "a usable value was published".
GOOD_STATUS = {"1", "6", "7", "9", "10", "12"}
YEARS = ["y1", "y5", "y10"]


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(config.SOURCES[name]["path"], dtype=str)


def _num(df: pd.DataFrame, col: str, status_col: str) -> pd.Series:
    vals = pd.to_numeric(df[col], errors="coerce")
    ok = df[status_col].str.strip().isin(GOOD_STATUS)
    return vals.where(ok)


def _earn_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for y in YEARS:
        for p in ["p25", "p50", "p75"]:
            out[f"{y}_{p}"] = _num(df, f"{y}_{p}_earnings", f"status_{y}_earnings")
        out[f"{y}_n"] = _num(df, f"{y}_grads_earn", f"status_{y}_grads_earn")
    return out


def earnings(pseoe: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    e = pseoe if pseoe is not None else _read("pseoe_nj")
    e = e[(e["degree_level"] == config.PSEO_BACHELORS) & (e["cip_level"] == "4")]

    def pick(agg: str, inst: str) -> pd.DataFrame:
        sub = e[(e["agg_level_pseo"] == agg) & (e["institution"] == inst)]
        out = _earn_frame(sub)
        out.insert(0, "cip4", sub["cipcode"])
        if agg in {"36", "48"}:
            out.insert(1, "grad_cohort", sub["grad_cohort"])
            out.insert(2, "grad_cohort_years", pd.to_numeric(sub["grad_cohort_years"]))
        return out.reset_index(drop=True)

    return {
        "rutgers": pick("42", config.PSEO_INSTITUTION),          # all cohorts pooled
        "rutgers_cohorts": pick("48", config.PSEO_INSTITUTION),  # by graduation cohort
        "nj": pick("30", config.PSEO_STATE),                     # NJ statewide, all partners
    }


def _flow_counts(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for y in YEARS:
        out[f"{y}_emp"] = _num(df, f"{y}_grads_emp", f"status_{y}_grads_emp")
        out[f"{y}_emp_instate"] = _num(df, f"{y}_grads_emp_instate", f"status_{y}_grads_emp_instate")
        out[f"{y}_nme"] = _num(df, f"{y}_grads_nme", f"status_{y}_grads_nme")
    return out


def flows(pseof: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    f = pseof if pseof is not None else _read("pseof_nj")
    f = f[(f["institution"] == config.PSEO_INSTITUTION) & (f["degree_level"] == config.PSEO_BACHELORS)
          & (f["cip_level"] == "2") & (f["grad_cohort"] == "0000")]
    totals = f[f["agg_level_pseo"] == "40"]
    industry = f[f["agg_level_pseo"] == "88"]
    division = f[f["agg_level_pseo"] == "136"]

    def frame(sub: pd.DataFrame, key: str | None) -> pd.DataFrame:
        out = _flow_counts(sub)
        out.insert(0, "cip2", sub["cipcode"])
        if key:
            out.insert(1, key, sub[key])
        return out.reset_index(drop=True)

    return {
        "totals": frame(totals, None),
        "industry": frame(industry, "industry"),
        "division": frame(division, "geography"),
    }


def labels() -> dict[str, dict[str, str]]:
    ind = _read("pseo_label_industry")
    ind = ind[ind["ind_level"] == "S"]
    div = _read("pseo_label_geography_division")
    return {
        "industry": dict(zip(ind["industry"], ind["label"])),
        "division": dict(zip(div["geography"], div["label"].str.replace(" Division", "", regex=False))),
    }


def version() -> str:
    path = config.SOURCES["pseo_version"]["path"]
    return path.read_text().strip().splitlines()[0] if path.exists() else ""
