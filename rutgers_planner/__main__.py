"""python -m rutgers_planner [--port 5000] [--no-browser] [--config config/me.yaml]"""
from __future__ import annotations

import argparse
import threading
import webbrowser


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rutgers_planner", description="Run the Rutgers Major Planner website locally.")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    ap.add_argument("--config", help="plan config the planner selects first (default: config/my-record.yaml)")
    ap.add_argument("--time-limit", type=float, default=30.0, help="CP-SAT seconds per plan")
    ap.add_argument("--pages", action="store_true",
                    help="let the GitHub Pages copy of the site use this server (What-If login, scraping, your record)")
    ap.add_argument("--allow-origin", action="append", default=[], metavar="URL",
                    help="another website allowed to use this server, e.g. https://you.github.io (repeatable)")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args(argv)

    from rutgers_whatif import config

    from . import PAGES_ORIGIN, create_app

    origins = list(a.allow_origin) + ([PAGES_ORIGIN] if a.pages else [])
    config.ensure_dirs()
    try:
        app = create_app(a.config, a.time_limit, allow_origins=origins)
    except ValueError as e:
        ap.error(str(e))
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Rutgers Major Planner is running at {url}  (Ctrl+C to stop)")
    for o in sorted(app.config["ALLOW_ORIGINS"]):
        print(f"  also answering the copy of the site at {o} (choose 'My computer' there)")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    # 127.0.0.1 only: the What-If tool keeps your Degree Navigator session on this computer.
    app.run(host="127.0.0.1", port=a.port, debug=a.debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
