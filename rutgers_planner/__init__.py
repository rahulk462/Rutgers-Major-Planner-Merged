"""Rutgers Major Planner: one local website for three tools.

* ``/outcomes`` career outcomes by major (from Major-To-Outcomes)
* ``/whatif``   your Degree Navigator audit across majors and minors (from Rutgers-What-If-Major)
* ``/plan``     a semester-by-semester graduation plan (from Rutgers-Grad-Path-Planner)

The tools share one course record (``personal/data/``), one program list and the
bundled Schedule of Classes pack. Start it with ``python run.py`` or
``python -m rutgers_planner``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, url_for

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def allowed_hosts() -> set[str]:
    extra = {h.strip() for h in os.environ.get("RMP_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return LOCAL_HOSTS | extra


def nav_items() -> list[tuple]:
    return [
        ("outcomes", "Career outcomes", url_for("outcomes.home"), "1"),
        ("whatif", "What-if majors", url_for("whatif.page"), "2"),
        ("planner", "Graduation plan", url_for("planner.page"), "3"),
    ]


def record_status() -> dict:
    """What the What-If tool has saved, for the home page."""
    from rutgers_whatif import config

    out = {"courses": 0, "manual": 0, "source": None, "when": None}
    if config.AUDIT_JSON.exists():
        try:
            a = json.loads(config.AUDIT_JSON.read_text())
            out["courses"] = len(a.get("courses", []))
            out["source"] = a.get("source")
            if a.get("fetched_at"):
                out["when"] = datetime.fromisoformat(str(a["fetched_at"]).replace("Z", "+00:00")).strftime("%b %d, %Y")
        except (ValueError, OSError):
            pass
    if config.MANUAL_FILE.exists():
        try:
            out["manual"] = len(json.loads(config.MANUAL_FILE.read_text()))
            out["courses"] += out["manual"]
        except (ValueError, OSError):
            pass
    return out


def site_data() -> dict:
    """Shared data handed to the tool pages as ``window.RMP``: programs and their links."""
    from .outcomes import load
    from .programs import registry

    progs = registry(load()[2])
    return {
        "programs": {p["id"]: p for p in progs},
        "links": {"home": url_for("home"), "whatif": url_for("whatif.page"), "plan": url_for("planner.page"),
                  "outcomes": url_for("outcomes.home"),
                  "major": url_for("outcomes.major", cip4="CIP").replace("CIP", "")},
    }


def create_app(plan_config: str | None = None, plan_time_limit: float = 30.0) -> Flask:
    from . import outcomes, tools
    from .programs import registry

    app = Flask(__name__)
    app.config["PLAN_CONFIG"] = plan_config
    app.config["PLAN_TIME_LIMIT"] = plan_time_limit
    app.json.sort_keys = False
    app.register_blueprint(outcomes.bp)
    app.register_blueprint(tools.whatif_bp)
    app.register_blueprint(tools.planner_bp)
    for name, fn in (("money", outcomes.money), ("pct", outcomes.pct), ("num", outcomes.num)):
        app.add_template_filter(fn, name)

    @app.before_request
    def local_only():
        # The What-If tool holds your Degree Navigator session and can open browser windows,
        # so only answer requests addressed to this computer, and refuse cross-site requests.
        hosts = allowed_hosts()
        h = request.host or ""
        host = h[1:].split("]")[0] if h.startswith("[") else h.rsplit(":", 1)[0]
        if host not in hosts:
            return jsonify({"error": "forbidden host"}), 403
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).hostname not in hosts:
            return jsonify({"error": "forbidden origin"}), 403
        return None

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.path.startswith(("/whatif/api", "/plan/api")):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.context_processor
    def inject_nav():
        return {"nav_items": nav_items(), "active": getattr(request, "blueprint", None) or "home"}

    @app.route("/")
    def home():
        from gradplan.selection import HAVE_ORTOOLS
        majors, _, index = outcomes.load()
        return render_template("home.html", programs=registry(index), record=record_status(),
                               n_majors=len(majors), cpsat=HAVE_ORTOOLS)

    @app.route("/api/programs")
    def api_programs():
        return jsonify(registry(outcomes.load()[2]))

    @app.route("/favicon.ico")
    def favicon():
        return "", 204

    return app
