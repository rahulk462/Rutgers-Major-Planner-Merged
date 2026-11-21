"""College Scorecard field-of-study data (IRS earnings for federal-aid recipients)."""
from __future__ import annotations

import zipfile

import pandas as pd

from . import config

EARN_YEARS = ["1YR", "4YR", "5YR", "7YR"]

RUTGERS_COLS = {
    "IPEDSCOUNT1": "completers_y1",
    "IPEDSCOUNT2": "completers_y2",
    "DEBT_ALL_STGP_EVAL_MDN": "median_debt",
    "EARN_COUNT_WNE_1YR": "n_1yr",
    "EARN_MDN_1YR": "earn_1yr",
    "EARN_COUNT_WNE_4YR": "n_4yr",
    "EARN_MDN_4YR": "earn_4yr",
    "EARN_COUNT_WNE_5YR": "n_5yr",
    "EARN_MDN_5YR": "earn_5yr",
    "EARN_COUNT_WNE_7YR": "n_7yr",
    "EARN_MDN_7YR": "earn_7yr",
    "EARN_IN_STATE_1YR": "in_state_1yr",
    "EARN_IN_STATE_5YR": "in_state_5yr",
}

NATIONAL_COLS = {
    f"EARN_{stat}_{yr}_NAT": f"{stat.lower()}_{yr.lower()}"
    for yr in EARN_YEARS
    for stat in ["MDN", "P25", "P75"]
} | {f"EARN_COUNT_WNE_{yr}_NAT": f"n_{yr.lower()}" for yr in EARN_YEARS}


def cip4_dotted(code: str) -> str:
    """Scorecard stores CIP as '0109'; the rest of the pipeline uses '01.09'."""
    code = str(code).strip().zfill(4)
    return f"{code[:2]}.{code[2:4]}"


def _num(series: pd.Series) -> pd.Series:
    # 'PS' = privacy suppressed; anything non-numeric becomes NaN.
    return pd.to_numeric(series.replace({"PS": None, "PrivacySuppressed": None}), errors="coerce")


def load_raw(path=None) -> pd.DataFrame:
    path = path or config.SOURCES["scorecard_fos"]["path"]
    with zipfile.ZipFile(path) as zf:
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(csv_name) as fh:
            return pd.read_csv(fh, dtype=str, low_memory=False)


def rutgers_programs(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw[(raw["UNITID"] == config.SCORECARD_UNITID) & (raw["CREDLEV"] == config.SCORECARD_BACHELORS)].copy()
    out = pd.DataFrame({
        "cip4": df["CIPCODE"].map(cip4_dotted),
        "cip_title": df["CIPDESC"].str.rstrip(". "),
    })
    for src, dst in RUTGERS_COLS.items():
        out[dst] = _num(df[src])
    return out.reset_index(drop=True)


def national_medians(raw: pd.DataFrame) -> pd.DataFrame:
    """National medians are repeated on every row of a CIP x credential; take one per CIP."""
    df = raw[raw["CREDLEV"] == config.SCORECARD_BACHELORS].drop_duplicates("CIPCODE").copy()
    out = pd.DataFrame({
        "cip4": df["CIPCODE"].map(cip4_dotted),
        "cip_title": df["CIPDESC"].str.rstrip(". "),
    })
    for src, dst in NATIONAL_COLS.items():
        out[dst] = _num(df[src])
    return out.reset_index(drop=True)


def build(path=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = load_raw(path)
    return rutgers_programs(raw), national_medians(raw)
