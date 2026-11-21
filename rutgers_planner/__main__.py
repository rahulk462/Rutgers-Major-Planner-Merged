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
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args(argv)

    from rutgers_whatif import config

    from . import create_app

    config.ensure_dirs()
    app = create_app(a.config, a.time_limit)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Rutgers Major Planner is running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    # 127.0.0.1 only: the What-If tool keeps your Degree Navigator session on this computer.
    app.run(host="127.0.0.1", port=a.port, debug=a.debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
