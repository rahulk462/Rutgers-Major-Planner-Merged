"""National context: NY Fed recent-grad outcomes, BLS projections/wages, NACE salaries."""
from __future__ import annotations

import pandas as pd

from . import config

BACHELORS_PLUS = {"Bachelor's degree", "Master's degree", "Doctoral or professional degree"}


def _prefix_lookup(table: pd.DataFrame, cip4: str, col: str):
    """Longest matching CIP prefix wins ('14.19' beats '14')."""
    best, best_len = None, -1
    for prefix, value in zip(table["cip_prefix"], table[col]):
        if cip4.startswith(prefix) and len(prefix) > best_len:
            best, best_len = value, len(prefix)
    return best


# --- NY Fed -------------------------------------------------------------------

def nyfed_by_major() -> pd.DataFrame:
    path = config.SOURCES["nyfed"]["path"]
    raw = pd.read_excel(path, sheet_name="outcomes by major", header=None)
    header_row = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Major"][0]
    df = pd.read_excel(path, sheet_name="outcomes by major", header=header_row)
    df = df.rename(columns={
        "Major": "major",
        "Unemployment Rate": "unemployment_rate",
        "Underemployment Rate": "underemployment_rate",
        "Median Wage Early Career": "wage_early",
        "Median Wage Mid-Career": "wage_mid",
        "Share with Graduate Degree": "share_grad_degree",
    })
    df = df.dropna(subset=["major"])
    df["major"] = df["major"].astype(str).str.strip()
    return df[["major", "unemployment_rate", "underemployment_rate", "wage_early", "wage_mid", "share_grad_degree"]]


def nyfed_release_note() -> str:
    raw = pd.read_excel(config.SOURCES["nyfed"]["path"], sheet_name="outcomes by major", header=None)
    for v in raw.iloc[:12, 0].map(str):
        if v.startswith("Updated"):
            return v
    return ""


def nyfed_crosswalk() -> pd.DataFrame:
    return pd.read_csv(config.CROSSWALKS / "nyfed_major_cip.csv", dtype=str)


def nyfed_for_cip(cip4: str, xwalk: pd.DataFrame, table: pd.DataFrame) -> dict | None:
    major = _prefix_lookup(xwalk, cip4, "nyfed_major")
    if not major:
        return None
    row = table[table["major"] == major]
    if row.empty:
        return None
    rec = row.iloc[0].to_dict()
    overall = table[table["major"] == "Overall"]
    if not overall.empty:
        rec["overall"] = overall.iloc[0].drop("major").to_dict()
    return rec


# --- BLS employment projections + CIP->SOC ------------------------------------

def bls_occupations() -> pd.DataFrame:
    path = config.SOURCES["bls_ep_occupation"]["path"]
    df = pd.read_excel(path, sheet_name="Table 1.2", header=1)
    cols = list(df.columns)
    rename = {
        cols[0]: "title", cols[1]: "soc", cols[2]: "occ_type", cols[3]: "emp_base", cols[4]: "emp_proj",
        cols[7]: "emp_change", cols[8]: "pct_change", cols[10]: "openings", cols[11]: "median_wage",
        cols[12]: "entry_education",
    }
    df = df.rename(columns=rename)[list(rename.values())]
    df = df[df["occ_type"] == "Line item"].copy()
    for c in ["emp_base", "emp_proj", "emp_change", "pct_change", "openings", "median_wage"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Base/projection years from the sheet title, e.g. "2025–35".
    df.attrs["years"] = _projection_years(path)
    return df


def _projection_years(path) -> str:
    title = str(pd.read_excel(path, sheet_name="Table 1.2", header=None).iloc[0, 0])
    import re
    m = re.search(r"(\d{4})[–-](\d{2,4})", title)
    return f"{m.group(1)}–{m.group(2)}" if m else ""


def cip_soc() -> pd.DataFrame:
    df = pd.read_excel(config.SOURCES["cip_soc"]["path"], sheet_name="CIP-SOC", dtype=str)
    df = df.rename(columns={"CIP2020Code": "cip6", "SOC2018Code": "soc", "SOC2018Title": "soc_title"})
    df["cip4"] = df["cip6"].str.slice(0, 5)
    return df[["cip4", "cip6", "soc", "soc_title"]]


def bls_for_cip(cip4: str, xwalk: pd.DataFrame, occ: pd.DataFrame, top: int = 8) -> dict | None:
    socs = xwalk.loc[xwalk["cip4"] == cip4, "soc"].dropna().unique()
    socs = [s for s in socs if not s.startswith("99-")]
    linked = occ[occ["soc"].isin(socs)].copy()
    if linked.empty:
        return None
    pool = linked[linked["entry_education"].isin(BACHELORS_PLUS)]
    basis = "bachelor's-or-higher occupations" if not pool.empty else "all linked occupations"
    pool = pool if not pool.empty else linked
    base, proj = pool["emp_base"].sum(), pool["emp_proj"].sum()
    wages = pool.dropna(subset=["median_wage"])
    wage = (wages["median_wage"] * wages["emp_base"]).sum() / wages["emp_base"].sum() if not wages.empty else None
    occs = pool.sort_values("emp_base", ascending=False).head(top)
    return {
        "basis": basis,
        "years": occ.attrs.get("years", ""),
        "n_occupations": int(len(pool)),
        "employment_base_k": round(float(base), 1),
        "growth_pct": round(float((proj - base) / base * 100), 1) if base else None,
        "openings_k": round(float(pool["openings"].sum()), 1),
        "weighted_median_wage": round(float(wage)) if wage else None,
        "occupations": [
            {
                "soc": r.soc, "title": str(r.title).strip(), "employment_k": r.emp_base, "growth_pct": r.pct_change,
                "median_wage": None if pd.isna(r.median_wage) else int(r.median_wage),
                "entry_education": r.entry_education,
            }
            for r in occs.itertuples()
        ],
    }


# --- NACE -----------------------------------------------------------------------

def nace() -> pd.DataFrame:
    return pd.read_csv(config.CROSSWALKS / "nace_2026.csv", dtype={"cip2_list": str})


def nace_for_cip(cip4: str, table: pd.DataFrame) -> dict | None:
    best, best_len = None, -1
    for row in table.itertuples():
        for prefix in str(row.cip2_list).split(";"):
            if cip4.startswith(prefix) and len(prefix) > best_len:
                best, best_len = row, len(prefix)
    if best is None:
        return None
    return {"category": best.category, "avg_starting_salary": int(best.avg_starting_salary),
            "pct_change": best.pct_change, "source_url": best.source_url, "published": best.published}


def bls_total_growth() -> float | None:
    """Projected growth for 'Total, all occupations' (the benchmark shown next to each major)."""
    df = pd.read_excel(config.SOURCES["bls_ep_occupation"]["path"], sheet_name="Table 1.2", header=1)
    row = df[df.iloc[:, 1].astype(str).str.strip() == "00-0000"]
    return None if row.empty else float(pd.to_numeric(row.iloc[0, 8], errors="coerce"))
