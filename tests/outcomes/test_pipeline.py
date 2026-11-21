import json

import pytest

from pipeline import build, config, fds, national, scorecard

PROCESSED = config.PROCESSED / "majors.json"


def test_cip4_dotted():
    assert scorecard.cip4_dotted("0109") == "01.09"
    assert scorecard.cip4_dotted("1101") == "11.01"
    assert scorecard.cip4_dotted("109") == "01.09"


def test_prefix_lookup_prefers_longest_match():
    import pandas as pd
    t = pd.DataFrame({"cip_prefix": ["14", "14.19"], "nyfed_major": ["General Engineering", "Mechanical Engineering"]})
    assert national._prefix_lookup(t, "14.19", "nyfed_major") == "Mechanical Engineering"
    assert national._prefix_lookup(t, "14.08", "nyfed_major") == "General Engineering"
    assert national._prefix_lookup(t, "52.01", "nyfed_major") is None


def test_clean_handles_nan_and_numpy():
    import numpy as np
    out = build.clean({"a": float("nan"), "b": np.int64(3), "c": [np.float64(2.5), 4.0]})
    assert out == {"a": None, "b": 3, "c": [2.5, 4]}


FDS_HTML = """
<html><body>The information below contains data from the Class of 2024 First-Destination Survey.
<select id="majorname"><option value="x?school=sas&majorname=ALL">Filter by major</option>
<option value="https://careers46.rutgers.edu/public/new_webpage_GradSurveyHome.cfm?school=sas&amp;major_id=198" selected>198 - Computer Science </option></select>
<table><tr><td>Career Outcomes Rate:</td><td>Employed (FT/PT):</td><td>Further Study:</td><td>Alternative Plans:</td>
<td>Median Starting Salary:</td><td>$90,000</td><td>n = 168</td><td>Average Additional Salary:</td><td>$18,827</td></tr>
<tr><td>76%</td><td>64%</td><td>11%</td><td>0%</td></tr><tr><td>Knowledge Rate: <strong>88.4% </strong></td></tr></table>
<table><tr><td>Top Hiring Employers:</td></tr><tr><td>Amazon</td></tr><tr><td>ADP</td></tr></table>
<table><tr><td>Top Schools for Furthering Education:</td></tr><tr><td>Rutgers University</td></tr></table>
</body></html>"""


def test_fds_parse_page():
    rec = fds.parse_page(FDS_HTML, "https://careers46.rutgers.edu/Public/new_webpage_GradSurveyHome.cfm?school=sas&major_id=198")
    assert rec["school"] == "sas" and rec["major_id"] == "198"
    assert rec["major_name"] == "Computer Science"
    assert rec["class_year"] == 2024
    assert rec["median_salary"] == 90000 and rec["salary_n"] == 168
    assert (rec["outcomes_rate"], rec["employed"], rec["further_study"], rec["alternative"]) == (76, 64, 11, 0)
    assert rec["knowledge_rate"] == 88.4
    assert rec["top_employers"] == ["Amazon", "ADP"]
    assert rec["top_grad_schools"] == ["Rutgers University"]


def test_fds_parse_handles_na_additional_salary():
    html = FDS_HTML.replace("$18,827", "N/A")
    rec = fds.parse_page(html)
    assert rec["avg_additional_salary"] is None
    assert rec["outcomes_rate"] == 76


def test_fds_error_page_has_no_stats():
    rec = fds.parse_page("<html><body>Our site seems to be experiencing a system error.</body></html>")
    assert not fds.has_stats(rec)


@pytest.fixture(scope="module")
def majors():
    if not PROCESSED.exists():
        pytest.skip("run `python -m pipeline.build` first")
    return json.loads(PROCESSED.read_text())


def test_processed_majors_are_unique_and_well_formed(majors):
    cips = [m["cip4"] for m in majors]
    assert len(cips) == len(set(cips))
    assert all(len(c) == 5 and c[2] == "." for c in cips)
    assert sum(m["has_rutgers_earnings"] for m in majors) > 50


def test_known_values_for_computer_science(majors):
    cs = next(m for m in majors if m["cip4"] == "11.01")
    assert cs["scorecard"]["rutgers"]["earn_1yr"] > 0
    assert cs["scorecard"]["national"]["mdn_4yr"] > 0
    assert cs["pseo"]["rutgers"]["y10"]["p50"] > cs["pseo"]["rutgers"]["y1"]["p50"]
    assert cs["fds"]["majors"] and cs["fds"]["majors"][0]["major_name"] == "Computer Science"
    assert cs["nyfed"]["major"] == "Computer Science"


def test_scope_is_new_brunswick_only():
    raw = scorecard.load_raw()
    rut, _ = scorecard.build()
    nb = raw[(raw.UNITID == config.SCORECARD_UNITID) & (raw.CREDLEV == "3")]
    assert len(rut) == len(nb)
    assert set(raw[raw.UNITID == config.SCORECARD_UNITID].INSTNM) == {"Rutgers University-New Brunswick"}
