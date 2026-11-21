"""The What-If tool (/whatif) and the graduation planner (/plan) as blueprints.

Both tools keep their own one-page apps (``rutgers_whatif/web/index.html`` and
``gradplan/static/index.html``) and JSON APIs, so their standalone servers still
work. Here the pages are served with the shared site bar added and their API
calls pointed at ``/whatif/api/...`` and ``/plan/api/...``.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, url_for
from markupsafe import Markup

whatif_bp = Blueprint("whatif", __name__, url_prefix="/whatif")
planner_bp = Blueprint("planner", __name__, url_prefix="/plan")


def tool_page(page: Path, api_prefix: str, active: str, title: str) -> str:
    """The tool's own HTML with the site bar, shared data and API prefix spliced in."""
    from . import site_data

    html = page.read_text()
    nav = render_template("_nav.html", active=active)
    data = json.dumps(site_data()).replace("</", "<\\/")
    head = (f'<link rel="stylesheet" href="{url_for("static", filename="nav.css")}">\n'
            f'<script>window.RMP = {data};</script>\n')
    html = html.replace('<html lang="en">', f'<html lang="en" data-api="{api_prefix}">', 1)
    html = html.replace("</title>", " · Rutgers Major Planner</title>", 1)
    html = html.replace("</head>", head + "</head>", 1)
    html = html.replace("<body>", "<body>\n" + str(Markup(nav)), 1)
    return html


def _json_body() -> dict | None:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


# ---------------------------------------------------------------- What-If ----

@whatif_bp.route("/")
def page():
    from rutgers_whatif import web
    return tool_page(web.PAGE, "/whatif", "whatif", "What-if majors")


@whatif_bp.route("/api/<path:sub>", methods=["GET"])
def whatif_get(sub: str):
    from rutgers_whatif import web
    code, body = web.handle_get("/api/" + sub, request.query_string.decode())
    return jsonify(body), code


@whatif_bp.route("/api/<path:sub>", methods=["POST"])
def whatif_post(sub: str):
    from rutgers_whatif import web
    if request.mimetype != "application/json":
        return jsonify({"error": "send application/json"}), 415
    body = _json_body()
    if body is None:
        return jsonify({"error": "bad json"}), 400
    code, out = web.handle_post("/api/" + sub, body)
    return jsonify(out), code


# ---------------------------------------------------------------- Planner ----

def planner_app():
    from gradplan.web import App
    app = current_app.extensions.get("gradplan")
    if app is None:
        app = App(current_app.config.get("PLAN_CONFIG"), current_app.config.get("PLAN_TIME_LIMIT", 30.0))
        current_app.extensions["gradplan"] = app
    return app


def _guard(fn):
    from gradplan.web import BadRequest
    try:
        return jsonify(json.loads(json.dumps(fn(), default=str))), 200
    except BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except (FileNotFoundError, ValueError, KeyError) as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@planner_bp.route("/")
def page():  # noqa: F811 - one `page` endpoint per blueprint
    from gradplan.web import STATIC
    return tool_page(STATIC / "index.html", "/plan", "planner", "Graduation plan")


@planner_bp.route("/api/setup")
def planner_setup():
    return _guard(lambda: planner_app().setup(request.args.get("config")))


@planner_bp.route("/api/plan", methods=["POST"])
def planner_plan():
    body = _json_body()
    if body is None:
        return jsonify({"error": "Body must be a JSON object"}), 400
    return _guard(lambda: planner_app().plan(body))


@planner_bp.route("/api/whatif", methods=["POST"])
def planner_whatif():
    body = _json_body()
    if body is None:
        return jsonify({"error": "Body must be a JSON object"}), 400
    return _guard(lambda: planner_app().whatif(body))
