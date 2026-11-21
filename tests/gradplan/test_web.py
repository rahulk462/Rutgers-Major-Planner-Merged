import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gradplan.web import App, make_handler


@pytest.fixture(scope="module")
def base():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(time_limit=10)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_and_setup(base):
    code, page = get(base + "/")
    assert code == 200 and b"Graduation Path Planner" in page
    code, raw = get(base + "/api/setup?config=example")
    d = json.loads(raw)
    assert d["config"] == "example" and "cs-bs" in {p["id"] for p in d["programs"]}
    assert d["student"]["taken"] and d["courses"]


def test_plan_with_ui_preferences(base):
    code, d = post(base + "/api/plan", {"config": "example", "programs": ["cs-bs", "math-ba"],
                                       "plan": {"locked": {"01:198:344": "Fall 2027"}, "max_credits": 17}})
    assert code == 200, d
    row = next(c for c in d["courses"] if c["code"] == "01:198:344")
    assert row["term"] == "Fall 2027"
    assert all(t["total_credits"] <= 17 for t in d["terms"] if t["term"].split()[0] in ("Spring", "Fall"))
    assert d["csv"].startswith("term,code,title")


def test_bad_input(base):
    assert post(base + "/api/plan", {"config": "example", "programs": []})[0] == 400
    code, d = post(base + "/api/plan", {"config": "example", "plan": {"start_term": "Fal 2027"}})
    assert code == 400 and "term" in d["error"]


def test_whatif(base):
    code, d = post(base + "/api/whatif", {"config": "example",
                                         "scenarios": {"CS": ["cs-bs"], "CS + Math minor": ["cs-bs", "math-minor"]}})
    assert code == 200, d
    assert [w["scenario"] for w in d["rows"]] == ["CS", "CS + Math minor"]
    assert d["rows"][1]["plan"]["terms"]
