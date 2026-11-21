"""Download the parts of Pyodide the Pages site needs: ``python -m rutgers_planner.pages.fetch_pyodide DIR``.

Streams the official release tarball from GitHub (checked against a pinned SHA-256) and keeps
only the runtime plus the four packages the tools import (PyYAML, Beautiful Soup, soupsieve,
sqlite3), about 15 MB instead of 390 MB. The site then serves Pyodide itself, so the pages
load no code from a third-party CDN.
"""
from __future__ import annotations

import hashlib
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "0.27.7"
URL = f"https://github.com/pyodide/pyodide/releases/download/{VERSION}/pyodide-{VERSION}.tar.bz2"
SHA256 = "08dd7f4fc4710110ea0fe2a7daa95bdf76001e596545267bc16dd760436ea755"
CORE = {"pyodide.js", "pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip",
        "pyodide-lock.json", "package.json"}
PACKAGES = ("pyyaml-", "beautifulsoup4-", "soupsieve-", "sqlite3-")


def wanted(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return base in CORE or (base.startswith(PACKAGES) and base.endswith(".whl"))


class _Hashing:
    """File-like wrapper that hashes the bytes as tarfile streams through them."""

    def __init__(self, raw):
        self.raw, self.h = raw, hashlib.sha256()

    def read(self, n=-1):
        b = self.raw.read(n)
        self.h.update(b)
        return b


def fetch(dest: Path, source: str | None = None) -> Path:
    dest = Path(dest)
    marker = dest / f".pyodide-{VERSION}"
    if marker.exists():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    raw = open(source, "rb") if source else urllib.request.urlopen(URL)  # noqa: SIM115
    stream = _Hashing(raw)
    with raw, tarfile.open(fileobj=stream, mode="r|bz2") as tar:
        for m in tar:
            if m.isfile() and wanted(m.name):
                f = tar.extractfile(m)
                (dest / m.name.rsplit("/", 1)[-1]).write_bytes(f.read())
        while stream.read(1 << 20):          # hash the rest of the archive too
            pass
    if stream.h.hexdigest() != SHA256:
        for p in dest.iterdir():
            p.unlink()
        raise SystemExit(f"Pyodide download doesn't match the pinned SHA-256 ({stream.h.hexdigest()})")
    missing = [c for c in CORE - {"package.json"} if not (dest / c).exists()]
    pkgs = [p for p in PACKAGES if not any(f.name.startswith(p) for f in dest.glob("*.whl"))]
    if missing or pkgs:
        raise SystemExit(f"Pyodide {VERSION} release is missing {missing + list(pkgs)}")
    marker.write_text(URL + "\n")
    return dest


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        raise SystemExit("usage: python -m rutgers_planner.pages.fetch_pyodide DIR [release.tar.bz2]")
    out = fetch(Path(argv[0]), argv[1] if len(argv) > 1 else None)
    size = sum(p.stat().st_size for p in out.iterdir())
    print(f"Pyodide {VERSION} in {out} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
