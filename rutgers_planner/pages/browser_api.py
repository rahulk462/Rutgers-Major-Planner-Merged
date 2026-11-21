"""The What-If and planner JSON APIs, run inside the browser by Pyodide (GitHub Pages copy).

``static/pyworker.js`` unpacks ``rutgers_whatif``, ``gradplan``, the program files, configs and
course pack into Pyodide's file system, puts this file next to them as ``browser_api.py``, and
calls :func:`handle` for every ``/whatif/api/...`` and ``/plan/api/...`` request the pages make.
It answers exactly like the Flask routes in ``rutgers_planner/tools.py``.

Your record (``personal/data/``) lives in this browser's storage (IndexedDB) and never leaves
it. What needs your own computer (the Degree Navigator login window, discovery, scraping and
Schedule of Classes downloads) returns an error that says to switch to "My computer".
"""
from __future__ import annotations

import json
import threading
import traceback
import types

from rutgers_whatif import web as whatif_web


class _InlineThread:
    """Pyodide can't start threads, so What-If jobs (CSV import) run to completion right away."""

    def __init__(self, target=None, daemon=None, **_):
        self._target = target

    def start(self):
        if self._target:
            self._target()


whatif_web.threading = types.SimpleNamespace(Thread=_InlineThread, Lock=threading.Lock, Event=threading.Event)

LOCAL_ONLY = {
    "login": "Logging in to Degree Navigator",
    "check": "Checking your Degree Navigator session",
    "discover": "Discovering your audit pages",
    "scrape": "Scraping Degree Navigator",
    "reparse": "Re-parsing saved Degree Navigator pages",
    "soc": "Downloading Schedule of Classes terms",
}
NEEDS_COMPUTER = ("{what} needs the planner running on your computer, because it opens a browser "
                  "window there and keeps your session there. Start it with `python run.py --pages`, "
                  "then pick “My computer” at the top of this page.")

_planner = None


def planner():
    global _planner
    if _planner is None:
        from gradplan.web import App
        _planner = App(None, 10.0)
    return _planner


def _whatif(method: str, path: str, query: str, body):
    if method == "GET":
        return whatif_web.handle_get(path, query)
    if not isinstance(body, dict):
        return 400, {"error": "bad json"}
    if path.startswith("/api/run/") and path.rsplit("/", 1)[1] in LOCAL_ONLY:
        return 409, {"error": NEEDS_COMPUTER.format(what=LOCAL_ONLY[path.rsplit("/", 1)[1]])}
    return whatif_web.handle_post(path, body)


def _plan(method: str, path: str, query: str, body):
    from urllib.parse import parse_qs

    from gradplan.web import BadRequest

    try:
        if method == "GET" and path == "/api/setup":
            return 200, planner().setup((parse_qs(query).get("config") or [None])[0])
        if method == "POST" and path in ("/api/plan", "/api/whatif"):
            if not isinstance(body, dict):
                return 400, {"error": "Body must be a JSON object"}
            app = planner()
            return 200, (app.plan(body) if path == "/api/plan" else app.whatif(body))
        return 404, {"error": "not found"}
    except BadRequest as e:
        return 400, {"error": str(e)}
    except (FileNotFoundError, ValueError, KeyError) as e:
        return 400, {"error": f"{type(e).__name__}: {e}"}
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return 500, {"error": f"{type(e).__name__}: {e}"}


def handle(method: str, tool: str, path: str, query: str = "", body: str | None = None) -> str:
    """One API request -> JSON ``{"status": int, "body": ...}`` (the body as the server would send it)."""
    try:
        data = json.loads(body) if body else ({} if method == "POST" else None)
    except json.JSONDecodeError:
        return json.dumps({"status": 400, "body": {"error": "bad json"}})
    fn = {"whatif": _whatif, "plan": _plan}.get(tool)
    status, out = fn(method, path, query, data) if fn else (404, {"error": "not found"})
    return json.dumps({"status": status, "body": out}, default=str)
