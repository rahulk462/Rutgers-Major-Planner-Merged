"""The GitHub Pages copy of the site (rutgers_planner/pages) and the opt-in CORS for it."""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from rutgers_planner import create_app

REPO = Path(__file__).resolve().parents[2]
PAGES = "https://rahulk462.github.io"


def test_other_websites_are_refused_by_default():
    c = create_app().test_client()
    r = c.get("/whatif/api/status", headers={"Origin": PAGES})
    assert r.status_code == 403 and "Access-Control-Allow-Origin" not in r.headers


def test_allowed_origin_gets_cors_and_preflight():
    c = create_app(allow_origins=[PAGES + "/"]).test_client()
    r = c.options("/plan/api/plan", headers={"Origin": PAGES, "Access-Control-Request-Method": "POST",
                                             "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 204
    assert r.headers["Access-Control-Allow-Origin"] == PAGES
    assert r.headers["Access-Control-Allow-Private-Network"] == "true"
    r = c.get("/api/programs", headers={"Origin": PAGES})
    assert r.status_code == 200 and r.headers["Access-Control-Allow-Origin"] == PAGES
    # Only the listed origin, and only the APIs.
    assert c.get("/api/programs", headers={"Origin": "https://evil.github.io"}).status_code == 403
    assert "Access-Control-Allow-Origin" not in c.get("/", headers={"Origin": PAGES}).headers


def test_bad_origin_rejected():
    with pytest.raises(ValueError):
        create_app(allow_origins=["rahulk462.github.io"])


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    env = {**os.environ, "GITHUB_REPOSITORY": ""}
    subprocess.run([sys.executable, "-m", "rutgers_planner.pages", "--out", str(out), "--base", "/Repo-Name/"],
                   cwd=REPO, env=env, check=True, capture_output=True)
    return out


def test_build_writes_every_page_under_the_base(site):
    for p in ["index.html", "404.html", ".nojekyll", "outcomes/index.html", "outcomes/compare/index.html",
              "outcomes/sources/index.html", "outcomes/major/11.01/index.html", "whatif/index.html",
              "plan/index.html", "static/site.css", "static/backend.js", "static/pyworker.js",
              "static/outcomes/11.01.json", "static/py-app.zip"]:
        assert (site / p).exists(), p
    home = (site / "index.html").read_text()
    assert 'href="/Repo-Name/outcomes/"' in home and 'href="/Repo-Name/outcomes/major/11.01/"' in home
    assert "runs in your browser" in home
    assert 'href="/' not in home.replace('href="/Repo-Name/', "")


def test_tool_pages_load_the_backend_switch(site):
    for page, api in [("whatif", "/Repo-Name/whatif"), ("plan", "/Repo-Name/plan")]:
        html = (site / page / "index.html").read_text()
        assert f'data-api="{api}"' in html
        assert "/Repo-Name/static/backend.js?v=" in html


def test_home_page_has_the_switch_and_class_entry(site):
    html = (site / "index.html").read_text()
    assert 'data-api="/Repo-Name/whatif"' in html and 'data-static="true"' in html
    assert "/Repo-Name/static/backend.js?v=" in html and "/Repo-Name/static/home.js?v=" in html
    assert (site / "static/home.js").exists() and (site / "static/home.css").exists()


def test_compare_page_renders_in_the_browser(site):
    html = (site / "outcomes/compare/index.html").read_text()
    assert 'id="static-compare"' in html and "compare.js?v=" in html
    assert 'data-major="/Repo-Name/outcomes/major/"' in html


def test_nothing_personal_is_published(site):
    names = zipfile.ZipFile(site / "static/py-app.zip").namelist()
    assert "browser_api.py" in names and "rutgers_whatif/web.py" in names and "gradplan/web.py" in names
    assert "data/soc/soc_nb.json" in names and "programs/cs-bs.yaml" in names
    assert not [n for n in names if n.startswith("personal/") or n.endswith((".sqlite", "auth.json"))]
    assert not list(site.rglob("personal")) and not list(site.rglob("*.sqlite"))


def test_browser_api_answers_like_the_server(site, tmp_path):
    """Runs browser_api (what Pyodide runs) with plain Python against the packed app."""
    app = tmp_path / "app"
    zipfile.ZipFile(site / "static/py-app.zip").extractall(app)
    script = """
import json, sys
sys.path.insert(0, sys.argv[1])
import browser_api as b
call = lambda *a: json.loads(b.handle(*a))
csv = open(sys.argv[2]).read()
out = {
  "status": call("GET", "whatif", "/api/status", "", None),
  "import": call("POST", "whatif", "/api/run/import", "", json.dumps({"csv": csv})),
  "login": call("POST", "whatif", "/api/run/login", "", "{}"),
  "add": call("POST", "whatif", "/api/courses/add", "", json.dumps({"code": "01:198:205", "term": "Fall 2025", "grade": "B+", "transfer": False})),
  "after": call("GET", "whatif", "/api/status", "", None),
  "whatif": call("GET", "whatif", "/api/whatif", "programs=cs-bs", None),
  "setup": call("GET", "plan", "/api/setup", "", None),
  "plan": call("POST", "plan", "/api/plan", "", json.dumps({"programs": ["cs-bs"], "plan": {"solver": "greedy"}})),
}
print(json.dumps({k: {"status": v["status"], "keys": sorted(v["body"])[:40] if isinstance(v["body"], dict) else None,
                      "error": (v["body"] or {}).get("error") if isinstance(v["body"], dict) else None,
                      "audit": (v["body"] or {}).get("audit") if isinstance(v["body"], dict) else None,
                      "job": (v["body"] or {}).get("job") if isinstance(v["body"], dict) else None}
                  for k, v in out.items()}))
"""
    env = {**os.environ, "RWI_HOME": str(tmp_path / "personal"), "RWI_AUTH_FILE": str(tmp_path / "auth.json")}
    r = subprocess.run([sys.executable, "-c", script, str(app), str(REPO / "examples/sample_courses.csv")],
                       cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["status"]["status"] == 200 and out["status"]["audit"] is None
    assert out["import"]["status"] == 202
    assert out["after"]["job"]["state"] == "done" and out["after"]["audit"]["courses"] == 12
    assert out["login"]["status"] == 409 and "python run.py --pages" in out["login"]["error"]
    assert out["add"]["status"] == 200, out["add"]
    assert out["whatif"]["status"] == 200
    assert out["setup"]["status"] == 200, out["setup"]
    assert out["plan"]["status"] == 200, out["plan"]
