"""Shared paths and identifiers for the data pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CROSSWALKS = ROOT / "data" / "crosswalks"
PROCESSED = ROOT / "data" / "processed"

# Scope: Rutgers–New Brunswick only (Camden and Newark are intentionally excluded).
SCORECARD_UNITID = "186380"          # IPEDS UNITID, Rutgers University-New Brunswick
PSEO_INSTITUTION = "00262900"        # PSEO/OPEID-8 id, Rutgers - New Brunswick Campus
PSEO_STATE = "34"                    # New Jersey statewide aggregate in PSEO
INSTITUTION_NAME = "Rutgers University–New Brunswick"

# Scorecard CREDLEV 3 = bachelor's; PSEO degree_level 05 = baccalaureate.
SCORECARD_BACHELORS = "3"
PSEO_BACHELORS = "05"

# Where each raw file came from (used by fetch.py and shown on the Sources page).
SOURCES = {
    "scorecard_fos": {
        "url": "https://ed-public-download.scorecard.network/downloads/Most-Recent-Cohorts-Field-of-Study_10152026.zip",
        "path": RAW / "scorecard" / "Most-Recent-Cohorts-Field-of-Study_10152026.zip",
    },
    "pseoe_nj": {
        "url": "https://lehd.ces.census.gov/data/pseo/latest_release/nj/pseoe_nj.csv.gz",
        "path": RAW / "pseo" / "pseoe_nj.csv.gz",
    },
    "pseof_nj": {
        "url": "https://lehd.ces.census.gov/data/pseo/latest_release/nj/pseof_nj.csv.gz",
        "path": RAW / "pseo" / "pseof_nj.csv.gz",
    },
    "pseo_nj_institutions": {
        "url": "https://lehd.ces.census.gov/data/pseo/latest_release/nj/pseo_nj_institutions.csv",
        "path": RAW / "pseo" / "pseo_nj_institutions.csv",
    },
    "pseo_version": {
        "url": "https://lehd.ces.census.gov/data/pseo/latest_release/nj/version_pseo.txt",
        "path": RAW / "pseo" / "version_pseo.txt",
    },
    **{
        f"pseo_label_{name}": {
            "url": f"https://lehd.ces.census.gov/data/schema/latest/label_{name}.csv",
            "path": RAW / "pseo" / f"label_{name}.csv",
        }
        for name in [
            "industry", "geography_division", "cipcode", "degree_level",
            "agg_level_pseo", "flags", "inst_level", "geo_level", "geography",
        ]
    },
    "nyfed": {
        "url": "https://www.newyorkfed.org/medialibrary/Research/Interactives/Data/college-labor-market/College-labor-data",
        "path": RAW / "nyfed" / "college-labor-data.xlsx",
    },
    "bls_ep_occupation": {
        "url": "https://www.bls.gov/emp/ind-occ-matrix/occupation.xlsx",
        "path": RAW / "bls" / "occupation.xlsx",
    },
    "cip_soc": {
        "url": "https://nces.ed.gov/ipeds/cipcode/Files/CIP2020_SOC2018_Crosswalk.xlsx",
        "path": RAW / "nces" / "CIP2020_SOC2018_Crosswalk.xlsx",
    },
}

FDS_BASE = "https://careers46.rutgers.edu/Public/new_webpage_GradSurveyHome.cfm"
FDS_SCHOOLS = {
    "ALL": "All Rutgers–New Brunswick",
    "sas": "School of Arts and Sciences",
    "eng": "School of Engineering",
    "business": "Rutgers Business School",
    "sebs": "School of Environmental and Biological Sciences",
    "smlr": "School of Management and Labor Relations",
    "sci": "School of Communication and Information",
    "arts": "Mason Gross School of the Arts",
    "education": "Graduate School of Education",
    "bloustein": "Bloustein School of Planning and Public Policy",
    "pharm": "Ernest Mario School of Pharmacy",
    "ssw": "School of Social Work",
    "Psych": "Graduate School of Applied and Professional Psychology",
    "graduate": "School of Graduate Studies",
}
