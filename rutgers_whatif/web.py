"""Local web page for the tool: ``python -m rutgers_whatif serve``.

Standard library only. It listens on 127.0.0.1 so nothing outside your own
computer can reach it, and it rejects requests whose Host/Origin isn't
localhost (protects against other websites poking it from your browser).
Long jobs (login, discover, scrape, course download) run one at a time in a
background thread; the page polls /api/status to show their progress.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
PAGE = Path(__file__).parent / "web" / "index.html"


class _Log(io.TextIOBase):
    def __init__(self, sink: list[str]):
        self.sink = sink

    def write(self, s: str) -> int:
        for line in s.splitlines():
            if line.strip():
                self.sink.append(line)
        return len(s)


class Jobs:
    """At most one background job; the browser 'Done' button releases waits."""

    def __init__(self):
        self.lock = threading.Lock()
        self.name: str | None = None
        self.state = "idle"            # idle | running | waiting | done | error
        self.log: list[str] = []
        self.prompt = ""
        self.window: dict = {}
        self._continue = threading.Event()

    def wait_for_user(self, prompt: str, tick=None) -> None:
        """Block the job until the page's "I'm done" button; meanwhile poll ``tick`` for live status."""
        self.prompt = prompt.strip().rstrip(".").rstrip() + "."
        self.prompt = self.prompt.replace("press Enter", "click \u201cI'm done\u201d").replace(
            "Press Enter", "Click \u201cI'm done\u201d")
        self.state = "waiting"
        self._continue.clear()
        while not self._continue.wait(1.0):
            if tick:
                try:
                    self.window = tick()
                except Exception:  # noqa: BLE001
                    self.window = {"state": "closed", "url": ""}
                if self.window.get("state") == "closed":
                    break       # window closed: stop waiting, the job reports it
        if tick:
            try:
                self.window = tick()
            except Exception:  # noqa: BLE001
                self.window = {"state": "closed", "url": ""}
        self.state = "running"
        self.prompt = ""

    def release(self) -> bool:
        if self.state != "waiting":
            return False
        self._continue.set()
        return True

    def start(self, name: str, fn) -> bool:
        with self.lock:
            if self.state in ("running", "waiting"):
                return False
            self.name, self.state, self.log, self.prompt, self.window = name, "running", [], "", {}

        def target():
            try:
                with contextlib.redirect_stdout(_Log(self.log)):
                    fn()
                self.state = "done"
                self.log.append("Finished.")
            except BaseException as e:  # noqa: BLE001 - surface everything to the page
                self.state = "error"
                self.log.append(f"Error: {e}")
                if not isinstance(e, (SystemExit, RuntimeError, FileNotFoundError)) or \
                        e.__class__.__name__ == "Error":
                    self.log.append(traceback.format_exc(limit=3))

        threading.Thread(target=target, daemon=True).start()
        return True

    def to_dict(self) -> dict:
        return {"name": self.name, "state": self.state, "log": self.log[-200:], "prompt": self.prompt,
                "window": self.window}


JOBS = Jobs()


def status() -> dict:
    from . import soc
    from .requirements import load_programs

    cached = sorted(p.stem for p in config.SOC_DIR.glob("*_*_*.json")) if config.SOC_DIR.exists() else []
    audit = None
    if config.AUDIT_JSON.exists():
        a = json.loads(config.AUDIT_JSON.read_text())
        audit = {"fetched_at": a.get("fetched_at"), "source": a.get("source"),
                 "courses": len(a.get("courses", [])), "requirements": len(a.get("requirements", []))}
    from .storage import load_manual
    manual = load_manual()
    pages = json.loads(config.PAGES_FILE.read_text()) if config.PAGES_FILE.exists() else None
    return {
        "session_saved": config.AUTH_FILE.exists(),
        "discovered": None if pages is None else {"mode": pages.get("mode"),
                                                  "json": len(pages.get("json_endpoints", [])),
                                                  "html": len(pages.get("documents", []))},
        "audit": audit,
        "manual": {"courses": len(manual), "transfer": sum(1 for c in manual if c.transfer)},
        "soc_terms": cached,
        "soc_courses": len(soc.load_index()) if cached else 0,
        "soc_bundled": 0 if cached else len(soc.bundled_index()),
        "programs": [{"id": k, "name": v["name"], "kind": v.get("kind", "major")}
                     for k, v in load_programs().items()],
        "job": JOBS.to_dict(),
    }


def run_whatif(programs: list[str], current: list[str]) -> dict:
    from . import soc, storage, whatif
    from .requirements import load_programs

    progs = load_programs()
    ids = [p for p in programs if p in progs] or list(progs)
    cur = [c for c in current if c in progs]
    try:
        courses = storage.load_courses()
    except FileNotFoundError:
        courses = []        # nothing entered yet: compare as if you haven't taken anything
    report = whatif.compare(progs, ids, courses, soc.load_index(), current=cur)
    report["courses"] = [c.to_dict() for c in courses]
    return report


def start_job(action: str, body: dict) -> tuple[bool, str]:
    from . import auth, discover, scrape, soc, storage

    if action == "login":
        return JOBS.start("login", lambda: auth.login(wait=JOBS.wait_for_user)), "login"
    if action == "check":
        def check():
            print("Session is valid." if auth.check_session() else "Session expired. Log in again.")
        return JOBS.start("check-session", check), "check"
    if action == "discover":
        return JOBS.start("discover", lambda: discover.run(wait=JOBS.wait_for_user)), "discover"
    if action == "scrape":
        return JOBS.start("scrape", lambda: scrape.run(mode=body.get("mode") or None)), "scrape"
    if action == "reparse":
        return JOBS.start("reparse", lambda: scrape.reparse()), "reparse"
    if action == "soc":
        year = int(body.get("year"))
        terms = body.get("terms") or ["spring", "fall"]

        def fetch():
            for t in terms:
                print(f"Downloading {year} {t} ...")
                print(f"  saved {soc.fetch_term(year, t)}")
        return JOBS.start("soc", fetch), "soc"
    if action == "import":
        text = body.get("csv", "")
        if not text.strip():
            return False, "empty CSV"
        config.ensure_dirs()
        tmp = config.DATA_DIR / "uploaded_courses.csv"
        tmp.write_text(text)

        def do_import():
            courses = storage.import_courses(tmp)
            storage.save(courses, [], source="import:web")
            print(f"Imported {len(courses)} courses.")
        return JOBS.start("import", do_import), "import"
    return False, f"unknown action {action}"


JOB_NAMES = ("login", "check", "discover", "scrape", "reparse", "soc", "import")


def handle_get(path: str, query: str = "") -> tuple[int, object]:
    """JSON API for GET requests, shared by this server and the merged website.

    Returns (status code, JSON-able body). ``path`` is relative to the API root (``/api/...``).
    """
    try:
        if path == "/api/status":
            return 200, status()
        if path == "/api/ap-exams":
            from . import storage
            return 200, storage.ap_table()
        if path == "/api/courses":
            from . import soc, storage
            cat = soc.load_index()
            try:
                courses = storage.load_courses()
            except FileNotFoundError:
                courses = []
            rows = []
            for c in sorted(courses, key=lambda c: (not c.transfer, c.code)):
                d = c.to_dict()
                d["title"] = d["title"] or (cat.get(c.code) or {}).get("title", "")
                rows.append(d)
            return 200, {"courses": rows}
        if path in ("/api/course", "/api/search"):
            from . import lookup, soc, storage, whatif
            from .requirements import load_programs
            q = parse_qs(query)
            cat = soc.load_index()
            if path == "/api/search":
                return 200, {"results": lookup.search((q.get("q") or [""])[0], cat), "have_soc": bool(cat)}
            try:
                passed = whatif.passed_codes(storage.load_courses())
            except FileNotFoundError:
                passed = set()
            d = lookup.describe((q.get("code") or [""])[0], cat, load_programs(), passed)
            d["have_courses"] = config.AUDIT_JSON.exists()
            d["have_soc"] = bool(cat)
            return 200, d
        if path == "/api/whatif":
            q = parse_qs(query)
            progs = [p for v in q.get("programs", []) for p in v.split(",") if p]
            cur = [p for v in q.get("current", []) for p in v.split(",") if p]
            return 200, run_whatif(progs, cur)
    except FileNotFoundError as e:
        return 409, {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return 500, {"error": str(e)}
    return 404, {"error": "not found"}


def add_course(body: dict):
    """Add one course by hand: AP/transfer credit (the default) or a class you took at Rutgers.

    ``{"code", "term", "credits", "title", "grade", "transfer"}``. Without ``"transfer": false``
    it is AP / test / transfer credit (grade T). With it, ``term`` is a semester like "Fall 2024"
    and ``grade`` a letter grade, P, W..., or empty for a class you are taking now.
    """
    from . import soc, storage
    from .courses import normalize_code, normalize_term

    cr = body.get("credits")
    credits = float(cr) if cr not in (None, "") else None
    if credits is not None and not 0 <= credits <= 12:
        raise ValueError("credits must be between 0 and 12")
    title = str(body.get("title") or "")
    transfer = body.get("transfer", True) is not False
    if transfer:
        return storage.add_manual(str(body.get("code", "")), grade=str(body.get("grade") or "T"),
                                  credits=credits, term=str(body.get("term") or "AP"), title=title)
    term = normalize_term(str(body.get("term") or ""))
    if not term:
        raise ValueError("pick the semester you took it, like Fall 2024")
    grade = str(body.get("grade") or "").strip().upper()
    if grade and not GRADE_OK.match(grade):
        raise ValueError(f"{grade!r} isn't a Rutgers grade (A, B+, B, C+, C, D, F, P, W, or empty if you're taking it now)")
    known = soc.load_index().get(normalize_code(str(body.get("code", ""))) or "") or {}
    if credits is None and known.get("credits"):
        credits = float(known["credits"])
    return storage.add_manual(str(body.get("code", "")), grade=grade, credits=credits, term=term,
                              title=title or known.get("title", ""), transfer=False)


GRADE_OK = re.compile(r"^(A|B\+|B|C\+|C|D|F|P|PA|S|U|W|NC|INC|IP)$")


def handle_post(path: str, body: dict) -> tuple[int, object]:
    """JSON API for POST requests (body already decoded), shared like :func:`handle_get`."""
    if path in ("/api/courses/add", "/api/courses/remove", "/api/courses/add-ap"):
        from . import storage
        try:
            if path.endswith("add-ap"):
                added = storage.add_ap_exam(str(body.get("exam", "")), int(body.get("score") or 0))
                return 200, {"added": [c.to_dict() for c in added]}
            if path.endswith("add"):
                return 200, {"added": add_course(body).to_dict()}
            term = body.get("term")
            return 200, {"removed": storage.remove_manual(str(body.get("code", "")),
                                                          None if term in (None, "") else str(term))}
        except ValueError as e:
            return 400, {"error": str(e)}
    if path == "/api/done":
        return 200, {"released": JOBS.release()}
    if path.startswith("/api/run/"):
        try:
            ok, msg = start_job(path.rsplit("/", 1)[1], body)
        except (TypeError, ValueError) as e:
            return 400, {"error": str(e)}
        if not ok:
            return 409, {"error": "another job is running" if msg in JOB_NAMES else msg}
        return 202, {"started": msg}
    return 404, {"error": "not found"}


class Handler(BaseHTTPRequestHandler):
    server_version = "rutgers-whatif"

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ALLOWED_HOSTS:
            return False
        return True

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        return self._json(*handle_get(url.path, url.query))

    def do_POST(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._json(415, {"error": "send application/json"})
        length = min(int(self.headers.get("Content-Length") or 0), 2_000_000)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        if not isinstance(body, dict):
            return self._json(400, {"error": "bad json"})
        return self._json(*handle_post(urlparse(self.path).path, body))


def serve(port: int = 8000, open_browser: bool = True) -> None:
    config.ensure_dirs()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Rutgers What-If is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
