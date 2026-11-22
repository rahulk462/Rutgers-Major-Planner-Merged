"""python -m rutgers_planner.pages --out _site [--base /Repo-Name/] [--pyodide DIR | --no-pyodide]"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# What the in-browser What-If and planner need (paths relative to the repo; only git-tracked files).
APP_FILES = (
    re.compile(r"^rutgers_whatif/.*\.(py|json|html)$"),
    re.compile(r"^gradplan/.*\.(py|html)$"),
    re.compile(r"^programs/[^/]+\.yaml$"),
    re.compile(r"^config/[^/]+\.yaml$"),
    re.compile(r"^data/soc/soc_nb\.json$"),
    re.compile(r"^examples/[^/]+\.csv$"),
)
NEVER = re.compile(r"(^|/)(personal|\.env[^/]*|auth\.json|[^/]*\.auth\.json|storage_state[^/]*\.json)$"
                   r"|^personal/|\.(sqlite3?|db)$|^config/me\.yaml$")


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
        return sorted(f for f in out.decode().split("\0") if f)
    except (OSError, subprocess.CalledProcessError):
        # Not a git checkout: walk the tree, never descending into personal/.
        return sorted(str(p.relative_to(REPO)).replace(os.sep, "/") for p in REPO.rglob("*")
                      if p.is_file() and "personal" not in p.relative_to(REPO).parts and "__pycache__" not in p.parts)


def app_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in tracked_files():
            if NEVER.search(f) or not any(r.match(f) for r in APP_FILES):
                continue
            z.writestr(zipfile.ZipInfo(f, (2020, 1, 1, 0, 0, 0)), (REPO / f).read_bytes(),
                       compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(zipfile.ZipInfo("browser_api.py", (2020, 1, 1, 0, 0, 0)),
                   (Path(__file__).parent / "browser_api.py").read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


def out_path(url: str) -> str:
    """/outcomes/major/11.01 -> outcomes/major/11.01/index.html (GitHub Pages adds the slash)."""
    p = url.strip("/")
    return f"{p}/index.html" if p else "index.html"


def build(out: Path, base: str, pyodide: Path | None) -> dict:
    # Never render anyone's record into the public site: point the What-If data at an empty folder.
    empty = Path(tempfile.mkdtemp(prefix="rmp-pages-"))
    os.environ["RWI_HOME"] = str(empty)
    os.environ["RWI_AUTH_FILE"] = str(empty / "auth.json")
    if "rutgers_whatif.config" in sys.modules:
        raise RuntimeError("build the Pages site in a fresh process (python -m rutgers_planner.pages)")

    from rutgers_planner import create_app
    from rutgers_planner.outcomes import load

    base = "/" + base.strip("/") + "/" if base.strip("/") else "/"
    app = create_app(plan_time_limit=10)
    app.config["STATIC_SITE"] = True
    client = app.test_client()
    majors = load()[0]

    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)

    zip_bytes = app_zip()
    version = hashlib.sha256(zip_bytes + b"".join(
        (REPO / "rutgers_planner/static" / f).read_bytes() for f in ("backend.js", "pyworker.js", "compare.js", "home.js", "home.css"))).hexdigest()[:10]

    # Links to /outcomes/... pages get their trailing slash so GitHub Pages doesn't redirect.
    b = re.escape(base)
    slash = re.compile(rf"(?<=[\"'])({b}outcomes/(?:compare|sources|major/[^\"'?#/<>\s]+))(?=[?#\"'])")
    versioned = re.compile(rf"({b}static/(?:backend\.js|compare\.js|home\.js|home\.css))(?=[\"'])")

    urls = ["/", "/outcomes/", "/outcomes/compare", "/outcomes/sources", "/whatif/", "/plan/"]
    urls += [f"/outcomes/major/{m['cip4']}" for m in majors]
    for url in urls:
        r = client.get(url, base_url="http://127.0.0.1" + base.rstrip("/"))
        if r.status_code != 200:
            raise RuntimeError(f"{url}: HTTP {r.status_code}")
        html = slash.sub(r"\1/", r.data.decode())
        html = versioned.sub(rf"\1?v={version}", html)
        dest = out / out_path(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html)

    shutil.copytree(REPO / "rutgers_planner" / "static", out / "static", dirs_exist_ok=True)
    (out / "static" / "outcomes").mkdir()
    for m in majors:
        (out / "static" / "outcomes" / f"{m['cip4']}.json").write_text(json.dumps(m, separators=(",", ":")))
    (out / "static" / "py-app.zip").write_bytes(zip_bytes)
    shutil.copy(out / "index.html", out / "404.html")
    (out / ".nojekyll").write_text("")

    if pyodide:
        shutil.copytree(pyodide, out / "pyodide", ignore=shutil.ignore_patterns(".pyodide-*"))
    shutil.rmtree(empty, ignore_errors=True)
    return {"pages": len(urls), "version": version, "base": base,
            "bytes": sum(p.stat().st_size for p in out.rglob("*") if p.is_file())}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rutgers_planner.pages", description="Build the GitHub Pages copy of the site.")
    ap.add_argument("--out", default="_site", help="output folder (default: _site, replaced)")
    repo = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1]
    ap.add_argument("--base", default=f"/{repo}/" if repo else "/",
                    help="URL path the site is served under, e.g. /Rutgers-Major-Planner-Merged/ (default: from GITHUB_REPOSITORY, else /)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--pyodide", type=Path, help="folder from `python -m rutgers_planner.pages.fetch_pyodide DIR`")
    g.add_argument("--fetch-pyodide", action="store_true", help="download Pyodide into .cache/pyodide first")
    a = ap.parse_args(argv)

    pyo = a.pyodide
    if a.fetch_pyodide:
        from .fetch_pyodide import fetch
        pyo = fetch(REPO / ".cache" / "pyodide")
    if pyo is None:
        print("note: no --pyodide, so What-if and the planner only work in 'My computer' mode", file=sys.stderr)
    info = build(Path(a.out).resolve(), a.base, pyo)
    print(f"Built {info['pages']} pages under {info['base']} in {a.out} ({info['bytes'] / 1e6:.1f} MB, version {info['version']})")


if __name__ == "__main__":
    main()
