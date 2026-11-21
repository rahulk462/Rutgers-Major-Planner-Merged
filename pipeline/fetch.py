"""Download the raw source files listed in config.SOURCES and scrape the Rutgers FDS.

Run:  python -m pipeline.fetch            # download anything missing
      python -m pipeline.fetch --force    # re-download everything
      python -m pipeline.fetch --fds      # also scrape careers46.rutgers.edu (live)

Some government sites block generic clients; if a download fails, open the URL in a
browser and save the file to the path printed here.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config, fds

HEADERS = {"User-Agent": "Mozilla/5.0 (major-to-outcomes data pipeline; educational use)"}


def download(force: bool = False) -> list[str]:
    import requests

    failures = []
    for key, src in config.SOURCES.items():
        path = src["path"]
        if path.exists() and not force:
            print(f"  ok      {key}: {path.relative_to(config.ROOT)}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
            print(f"  fetched {key}: {len(r.content):,} bytes")
        except Exception as exc:  # noqa: BLE001 - report and keep going
            failures.append(key)
            print(f"  FAILED  {key}: {exc}\n          save {src['url']}\n          to   {path}", file=sys.stderr)
    return failures


def scrape_fds() -> None:
    recs = fds.scrape_live()
    if not recs:
        print("  FDS site returned no data (it may be down); keeping archived copies.", file=sys.stderr)
        return
    out = config.RAW / "rutgers_fds" / "fds_live.json"
    out.write_text(json.dumps(recs, indent=1))
    print(f"  scraped {len(recs)} FDS pages -> {out.relative_to(config.ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--fds", action="store_true", help="scrape the live First-Destination Survey pages")
    args = ap.parse_args()
    failures = download(args.force)
    if args.fds:
        scrape_fds()
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
