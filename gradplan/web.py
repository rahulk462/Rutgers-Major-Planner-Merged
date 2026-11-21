"""Local web UI: ``python -m gradplan serve`` then open http://localhost:8000.

Standard library only (http.server). It listens on 127.0.0.1, so nothing outside
your computer can reach it. The page (gradplan/static/index.html) talks to a
small JSON API:

    GET  /api/setup?config=NAME   configs, programs, the config's preferences, transcript, courses
    POST /api/plan                 {config, programs, plan: {...}} -> plan JSON + CSV text
    POST /api/whatif               {config, plan, scenarios: {name: [ids]}} -> comparison rows
"""

from __future__ import annotations

import copy
import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from . import export
from .codes import SEASON_ORDER, Term
from .planner import ROOT, WHATIF_PREFIX, _path, context_from_config, run
from .selection import HAVE_ORTOOLS

STATIC = Path(__file__).resolve().parent / "static"
CONFIG_DIR = ROOT / "config"
PROGRAM_DIR = ROOT / "programs"

# Preference keys the page may override in the config's `plan:` block.
PLAN_KEYS = {
    "start_term": str, "target_graduation": str, "min_credits": float, "max_credits": float,
    "summer": bool, "winter": bool, "summer_max_credits": float, "winter_max_credits": float,
    "total_credits_required": float, "fill_electives": bool, "locked": dict, "hard_courses": list,
    "max_hard_per_term": int, "include": list, "exclude": list, "prefer": list, "avoid": list,
    "solver": str, "objective": str, "offering_threshold": float,
}

_lock = threading.Lock()          # one solve at a time; CP-SAT already uses every core


class BadRequest(Exception):
    pass


def list_configs(extra: list[Path]) -> dict[str, Path]:
    """Plan configs the page can pick: config/*.yaml that have a `plan:` block, plus --config files."""
    out: dict[str, Path] = {}
    for p in list(extra) + sorted(CONFIG_DIR.glob("*.yaml")):
        try:
            y = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if isinstance(y, dict) and "plan" in y:
            out.setdefault(p.stem, p.resolve())
    return out


def list_programs() -> list[dict]:
    out = []
    for p in sorted(PROGRAM_DIR.glob("*.yaml")):
        y = yaml.safe_load(p.read_text()) or {}
        out.append({"id": y.get("id", p.stem), "name": y.get("name", p.stem), "kind": y.get("kind", "major")})
    kinds = {"major": 0, "minor": 1}
    return sorted(out, key=lambda d: (kinds.get(d["kind"], 2), d["name"]))


def term_choices(first: int = 2025, last: int = 2034) -> list[str]:
    return [Term(y, s).name for y in range(first, last + 1) for s in SEASON_ORDER]


class App:
    def __init__(self, default_config: Path | None = None, time_limit: float = 30.0):
        self.extra = [Path(default_config).resolve()] if default_config else []
        self.default = Path(default_config).stem if default_config else None
        self.time_limit = time_limit

    # ---- config handling -------------------------------------------------
    def configs(self) -> dict[str, Path]:
        return list_configs(self.extra)

    def read_config(self, name: str | None) -> tuple[str, Path, dict]:
        cfgs = self.configs()
        if not cfgs:
            raise BadRequest("No plan configs found in config/")
        if not name:
            name = self.default if self.default in cfgs else (
                "my-record" if "my-record" in cfgs else next(iter(cfgs)))
        if name not in cfgs:
            raise BadRequest(f"Unknown config {name!r}")
        path = cfgs[name]
        return name, path, yaml.safe_load(path.read_text()) or {}

    def merged(self, body: dict) -> tuple[dict, Path]:
        _, path, cfg = self.read_config(body.get("config"))
        cfg = copy.deepcopy(cfg)
        plan = cfg.setdefault("plan", {}) or {}
        cfg["plan"] = plan
        for k, v in (body.get("plan") or {}).items():
            if k not in PLAN_KEYS:
                continue
            typ = PLAN_KEYS[k]
            if v is None or v == "":
                if k == "target_graduation":
                    plan.pop(k, None)
                continue
            try:
                plan[k] = typ(v) if typ in (str, float, int, bool) else v
            except (TypeError, ValueError):
                raise BadRequest(f"Bad value for {k}: {v!r}")
            if typ in (list, dict) and not isinstance(v, typ):
                raise BadRequest(f"{k} must be a {typ.__name__}")
        for k in ("start_term", "target_graduation"):
            if plan.get(k):
                try:
                    Term.parse(plan[k])
                except ValueError as e:
                    raise BadRequest(str(e))
        for c, t in (plan.get("locked") or {}).items():
            try:
                Term.parse(t)
            except ValueError as e:
                raise BadRequest(f"Locked course {c}: {e}")
        if plan.get("min_credits", 0) > plan.get("max_credits", 18):
            raise BadRequest("Minimum credits per term is higher than the maximum")
        if "programs" in body:
            progs = [p for p in body["programs"] if isinstance(p, str)]
            if not progs:
                raise BadRequest("Pick at least one program")
            cfg["programs"] = progs
        if isinstance(body.get("double_counting"), dict):
            cfg["double_counting"] = body["double_counting"]
        return cfg, path.parent

    # ---- endpoints -------------------------------------------------------
    def setup(self, name: str | None) -> dict:
        name, path, cfg = self.read_config(name)
        ctx = context_from_config(copy.deepcopy(cfg), path.parent)
        st = cfg.get("student", {}) or {}
        files = []
        for p in st.get("transcript", []) or []:
            q = _path(path.parent, p)
            files.append({"path": str(q) if str(p).startswith(WHATIF_PREFIX) else p, "found": q.exists()})
        cat = ctx.catalog
        taken = [{"code": t.code, "title": t.title or cat.get(t.code).title, "status": t.status,
                  "credits": t.credits if t.credits is not None else cat.get(t.code).credits,
                  "term": t.term or ("AP / transfer" if t.transfer else "")} for t in ctx.taken]
        return {
            "configs": list(self.configs()),
            "config": name,
            "config_path": str(path),
            "programs": list_programs(),
            "selected": cfg.get("programs", []),
            "plan": cfg.get("plan", {}) or {},
            "scenarios": cfg.get("scenarios", {}) or {},
            "double_counting": cfg.get("double_counting", {}) or {},
            "student": {"credits_earned": ctx.prefs.credits_earned, "taken": taken, "files": files},
            "terms": term_choices(),
            "cpsat_available": HAVE_ORTOOLS,
            "courses": sorted(({"code": c.code, "title": c.title, "credits": c.credits}
                               for c in cat.courses.values()), key=lambda d: d["code"]),
        }

    def _solve(self, cfg: dict, base: Path, programs=None):
        ctx = context_from_config(cfg, base)
        with _lock:
            return run(ctx, programs, None, self.time_limit)

    def _plan_json(self, r) -> dict:
        d = export.to_json(r)
        d["notes"] = list(r.plan.notes)
        d["program_names"] = {p.id: p.name for p in r.programs}
        d["program_notes"] = {p.id: p.notes for p in r.programs}
        d["requirements_done"] = next((t.name for t in reversed(r.plan.used_terms()) if r.plan.courses_in(t)), None)
        d["csv"] = export.csv_text(r)
        d["text"] = export.to_text_report(r)
        return d

    def plan(self, body: dict) -> dict:
        cfg, base = self.merged(body)
        return self._plan_json(self._solve(cfg, base))

    def whatif(self, body: dict) -> dict:
        from .whatif import compare
        cfg, base = self.merged(body)
        scen = body.get("scenarios") or cfg.get("scenarios") or {}
        scen = {str(k): [p for p in v if isinstance(p, str)] for k, v in scen.items() if v}
        if not scen:
            raise BadRequest("Add at least one scenario with a program")
        ctx = context_from_config(cfg, base)
        with _lock:
            rows = compare(ctx, scen, None, self.time_limit)
        out = []
        for w in rows:
            item = {k: v for k, v in w.items() if k != "result"}
            item["plan"] = self._plan_json(w["result"])
            out.append(item)
        return {"rows": out, "baseline": out[0]["scenario"] if out else None}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "gradplan"

        def log_message(self, fmt, *args):      # quieter than the default
            if not str(args[1] if len(args) > 1 else "").startswith("2"):
                super().log_message(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data):
            self._send(code, json.dumps(data, default=str).encode(), "application/json")

        def _guard(self, fn):
            try:
                self._json(200, fn())
            except BadRequest as e:
                self._json(400, {"error": str(e)})
            except (FileNotFoundError, ValueError, KeyError) as e:
                self._json(400, {"error": f"{type(e).__name__}: {e}"})
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/setup":
                q = parse_qs(u.query)
                self._guard(lambda: app.setup((q.get("config") or [None])[0]))
            elif u.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "Body must be a JSON object"})
            routes = {"/api/plan": app.plan, "/api/whatif": app.whatif}
            fn = routes.get(u.path)
            if not fn:
                return self._json(404, {"error": "not found"})
            self._guard(lambda: fn(body))

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, config: str | None = None,
          open_browser: bool = True, time_limit: float = 30.0) -> None:
    app = App(Path(config) if config else None, time_limit)
    httpd = None
    for p in range(port, port + 20):              # next free port if 8000 is taken
        try:
            httpd = ThreadingHTTPServer((host, p), make_handler(app))
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"No free port between {port} and {port + 19}")
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{httpd.server_address[1]}/"
    print(f"Graduation planner running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
