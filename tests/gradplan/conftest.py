import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from gradplan.soc import Catalog, Equivalents  # noqa: E402

TERMS = ["2024_1", "2024_9", "2025_1", "2025_7", "2025_9", "2026_1", "2026_9"]
ALL = TERMS
FALL = [t for t in TERMS if t.endswith("_9")]
SPRING = [t for t in TERMS if t.endswith("_1")]


def make_pack(courses: dict) -> dict:
    """courses: code -> (credits, prereq text, [term keys offered])"""
    offerings = {t: [] for t in TERMS}
    catalog = {}
    for code, (cr, pre, terms) in courses.items():
        catalog[code] = {"title": code, "credits": cr, "prereq": pre, "core": []}
        for t in terms:
            offerings[t].append(code)
    return {"terms": TERMS, "catalog": catalog, "offerings": offerings}


@pytest.fixture
def toy_catalog():
    pack = make_pack({
        "01:198:101": (4, "", ALL),
        "01:198:102": (4, "(01:198:101 INTRO )", ALL),
        "01:198:201": (4, "(01:198:102 DATA )", ALL),
        "01:198:301": (4, "(01:198:201 SYS )", FALL),          # fall only
        "01:198:302": (4, "(01:198:301 X ) and (01:198:102 Y )", SPRING),
        "01:198:310": (3, "(01:198:102 DATA )", ALL),
        "01:198:320": (3, "(01:198:102 DATA )", ALL),
        "01:198:330": (3, "", ALL),
        "01:640:151": (4, "", ALL),
        "01:640:152": (4, "(01:640:151 C1 )", ALL),
        "01:640:350": (3, "(01:640:152 C2 )", ALL),
        "01:750:201": (4, "", ALL),
        "01:750:202": (4, "(01:750:201 P1 )", SPRING),
    })
    return Catalog(pack, Equivalents([["01:198:101", "01:198:099"]]))
