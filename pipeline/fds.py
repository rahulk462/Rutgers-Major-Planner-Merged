"""Rutgers–New Brunswick First-Destination Survey (careers46.rutgers.edu).

The public pages are plain HTML. `scrape_live()` fetches them directly when the
site is up; `load_wayback()` parses the Internet Archive copies saved in
data/raw/rutgers_fds/ (the live site was returning a ColdFusion error page on
2026-11-21, so the committed data comes from the archive).
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from . import config

_MONEY = r"\$([\d,]+)"
_PCT = r"(\d+(?:\.\d+)?)%"


def _money(s: str | None) -> int | None:
    return int(s.replace(",", "")) if s else None


def _list_after(soup: BeautifulSoup, heading: str) -> list[str]:
    """Rows of the small table whose header cell reads `heading`."""
    node = soup.find(string=re.compile(re.escape(heading)))
    if not node:
        return []
    table = node.find_parent("table")
    if not table:
        return []
    items = []
    for td in table.find_all("td")[1:]:
        txt = td.get_text(" ", strip=True)
        if txt and txt != heading:
            items.append(txt)
    return items


def parse_page(html: str, url: str = "") -> dict:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    qs = parse_qs(urlparse(url).query) if url else {}
    rec: dict = {
        "url": url,
        "school": (qs.get("school") or [None])[0],
        "major_id": (qs.get("major_id") or [None])[0],
        "major_name": None,
        "class_year": None,
        "outcomes_rate": None,
        "employed": None,
        "further_study": None,
        "alternative": None,
        "median_salary": None,
        "salary_n": None,
        "avg_additional_salary": None,
        "knowledge_rate": None,
        "top_employers": [],
        "top_grad_schools": [],
        "majors_offered": [],
    }
    if rec["school"] and rec["school"].lower() == "all":
        rec["school"] = "ALL"

    m = re.search(r"Class of (\d{4}) First-Destination Survey", text)
    if m:
        rec["class_year"] = int(m.group(1))

    sel = soup.select_one("select#majorname option[selected]")
    if sel:
        rec["major_name"] = re.sub(r"^\d+\s*-\s*", "", sel.get_text(strip=True)).strip()
    for opt in soup.select("select#majorname option"):
        oq = parse_qs(urlparse(opt.get("value", "")).query)
        if "major_id" in oq:
            name = re.sub(r"^\d+\s*-\s*", "", opt.get_text(strip=True)).strip()
            rec["majors_offered"].append({"major_id": oq["major_id"][0], "name": name})

    block = text[text.find("Career Outcomes Rate:"):] if "Career Outcomes Rate:" in text else ""
    m = re.search(r"Median Starting Salary:\s*" + _MONEY + r"\s*n\s*=\s*([\d,]+)", block)
    if m:
        rec["median_salary"] = _money(m.group(1))
        rec["salary_n"] = _money(m.group(2))
    m = re.search(r"Average Additional Salary:\s*(?:" + _MONEY + r"|N/A)?\s*" + r"\s*".join([_PCT] * 4), block)
    if m:
        rec["avg_additional_salary"] = _money(m.group(1))
        rec["outcomes_rate"], rec["employed"], rec["further_study"], rec["alternative"] = (
            float(m.group(i)) for i in range(2, 6))
    m = re.search(r"Knowledge Rate:\s*" + _PCT, block)
    if m:
        rec["knowledge_rate"] = float(m.group(1))

    rec["top_employers"] = _list_after(soup, "Top Hiring Employers:")
    rec["top_grad_schools"] = _list_after(soup, "Top Schools for Furthering Education:")
    return rec


def has_stats(rec: dict) -> bool:
    return rec.get("median_salary") is not None or rec.get("outcomes_rate") is not None


def load_wayback() -> list[dict]:
    """Parse every archived page; keep the newest snapshot with stats per (school, major)."""
    base = config.RAW / "rutgers_fds"
    pages: list[tuple[str, str, str]] = []  # (url, timestamp, html)
    for name in ["fds_schools_wayback.json", "fds_majors_wayback.json"]:
        path = base / name
        if not path.exists():
            continue
        blob = json.loads(path.read_text())
        entries = blob.get("pages", blob)
        for url, page in entries.items():
            if page.get("status") == 200 and page.get("html"):
                ts = page.get("ts") or ""
                pages.append((url, ts, page["html"]))

    best: dict[tuple, dict] = {}
    for url, ts, html in pages:
        rec = parse_page(html, url)
        if not has_stats(rec):
            continue
        rec["source"] = "wayback"
        rec["snapshot"] = ts
        key = ((rec["school"] or "").lower(), rec["major_id"])
        prev = best.get(key)
        if prev is None or (rec["class_year"] or 0, ts) > (prev["class_year"] or 0, prev["snapshot"]):
            best[key] = rec
    return sorted(best.values(), key=lambda r: ((r["school"] or "").lower(), r["major_id"] or ""))


def scrape_live(delay: float = 1.0, session=None) -> list[dict]:
    """Fetch every school page, then every major page listed in its dropdown."""
    import requests

    s = session or requests.Session()
    s.headers.setdefault("User-Agent", "major-to-outcomes research scraper (educational project)")
    out = []
    for school in config.FDS_SCHOOLS:
        url = f"{config.FDS_BASE}?school={school}"
        r = s.get(url, timeout=30)
        rec = parse_page(r.text, url)
        if not has_stats(rec):
            continue
        rec["source"] = "live"
        out.append(rec)
        for maj in rec["majors_offered"]:
            time.sleep(delay)
            murl = f"{config.FDS_BASE}?school={school}&major_id={maj['major_id']}"
            mr = s.get(murl, timeout=30)
            mrec = parse_page(mr.text, murl)
            if has_stats(mrec):
                mrec["source"] = "live"
                out.append(mrec)
        time.sleep(delay)
    return out


def load() -> list[dict]:
    """Prefer a live scrape (data/raw/rutgers_fds/fds_live.json) when one exists, else the archive copies."""
    live = config.RAW / "rutgers_fds" / "fds_live.json"
    if live.exists():
        recs = [r for r in json.loads(live.read_text()) if has_stats(r)]
        if recs:
            return recs
    return load_wayback()
