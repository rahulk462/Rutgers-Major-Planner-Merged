"""The merged website: navigation, the three tools under one server, and the links between them."""
import json

import pytest

from rutgers_planner import create_app
from rutgers_planner.programs import cip_for, registry
from rutgers_whatif import config as rwi_config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point the What-If tool's record at an empty temp folder so tests never touch personal/.
    d = tmp_path / "data"
    for name, path in {"DATA_DIR": d, "SOC_DIR": d / "soc", "RAW_DIR": d / "raw", "AUDIT_JSON": d / "audit.json",
                       "DB_FILE": d / "whatif.sqlite", "PAGES_FILE": d / "dn_pages.json",
                       "AUTH_FILE": tmp_path / "auth.json", "MANUAL_FILE": d / "manual_courses.json"}.items():
        monkeypatch.setattr(rwi_config, name, path)
    rwi_config.ensure_dirs()
    app = create_app(plan_time_limit=10)
    app.testing = True
    return app.test_client()


def test_home_links_all_three_tools(client):
    html = client.get("/").data.decode()
    for href in ['href="/outcomes/"', 'href="/whatif/"', 'href="/plan/"']:
        assert href in html
    assert "Computer Science B.S." in html or "cs-bs" in html
    assert "/plan/?programs=cs-bs" in html and "/outcomes/major/11.01" in html


def test_tool_pages_get_site_bar_and_api_prefix(client):
    for url, prefix, marker in [("/whatif/", "/whatif", "Rutgers What-If"), ("/plan/", "/plan", "Graduation Path Planner")]:
        html = client.get(url).data.decode()
        assert marker in html
        assert f'data-api="{prefix}"' in html
        assert 'class="rmp-bar"' in html and "window.RMP =" in html
        assert 'aria-current="page"' in html


def test_outcomes_pages_share_the_bar(client):
    html = client.get("/outcomes/major/11.01").data.decode()
    assert 'class="rmp-bar"' in html
    assert "/plan/?programs=cs-bs" in html and "/whatif/?compare=cs-bs" in html
    assert "plannable" in client.get("/outcomes/").data.decode()


def test_program_registry_joins_tools_and_outcomes():
    from rutgers_planner.outcomes import load
    progs = {p["id"]: p for p in registry(load()[2])}
    assert progs["cs-bs"]["whatif"] and progs["cs-bs"]["planner"] and progs["cs-bs"]["cip4"] == "11.01"
    assert progs["ds-minor"]["whatif"] and progs["ds-minor"]["cip4"] == "30.70"
    # Every program is plannable, Data Science tracks included.
    assert all(p["whatif"] and p["planner"] for p in progs.values()), [k for k, p in progs.items() if not p["planner"]]
    assert progs["math-ba"]["outcomes"]["title"] == "Mathematics"
    assert cip_for("statmath-ba") == "27.05" and cip_for("nope") is None


def test_whatif_api_through_site(client):
    s = client.get("/whatif/api/status").get_json()
    assert s["audit"] is None and any(p["id"] == "cs-bs" for p in s["programs"])
    assert s["soc_bundled"] > 500          # bundled planner pack stands in for downloads
    r = client.post("/whatif/api/courses/add", json={"code": "01:640:151", "term": "AP", "credits": 4})
    assert r.status_code == 200 and r.get_json()["added"]["code"] == "01:640:151"
    w = client.get("/whatif/api/whatif?programs=math-minor").get_json()
    assert w["programs"][0]["id"] == "math-minor"
    d = client.get("/whatif/api/course?code=01:198:344").get_json()
    assert d["have_soc"] and d["known"]
    assert client.post("/whatif/api/courses/add", data="x", content_type="text/plain").status_code == 415


def test_planner_reads_the_whatif_record(client):
    # AP credit added on the What-If page shows up in the planner's my-record config.
    client.post("/whatif/api/courses/add", json={"code": "01:640:151", "term": "AP", "credits": 4})
    s = client.get("/plan/api/setup?config=my-record").get_json()
    assert s["config"] == "my-record"
    assert any(t["code"] == "01:640:151" for t in s["student"]["taken"])


def test_planner_builds_a_plan(client):
    r = client.post("/plan/api/plan", json={"config": "example", "programs": ["cs-minor"],
                                             "plan": {"solver": "greedy"}})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["graduation"] and d["terms"]
    assert client.post("/plan/api/plan", json={"config": "example", "programs": []}).status_code == 400


@pytest.mark.parametrize("pid", ["ds-bs-cs", "ds-ba-stat", "ds-minor"])
def test_planner_plans_data_science(client, pid):
    r = client.post("/plan/api/plan", json={"config": "example", "programs": [pid], "plan": {"solver": "greedy"}})
    assert r.status_code == 200, r.get_json()
    assert not [i for i in r.get_json()["issues"] if i["level"] == "error"]


def test_rejects_other_hosts_and_origins(client):
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    r = client.post("/whatif/api/run/login", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
