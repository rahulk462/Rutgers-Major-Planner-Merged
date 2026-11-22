# Rutgers Major Planner

One local website for choosing and planning a Rutgers–New Brunswick major. It combines three tools
that used to be separate projects:

| Step | Page | What it does | Came from |
|---|---|---|---|
| 1 | **Career outcomes** `/outcomes` | Earnings 1, 5 and 10 years out, employment, top employers and job growth for 103 majors, next to national and NJ benchmarks | [Major-To-Outcomes](https://github.com/rahulk462/Major-To-Outcomes) |
| 2 | **What-if majors** `/whatif` | Pulls **your own** Degree Navigator audit (or a course CSV), adds AP/transfer credit, and shows how far you are from each major and minor if you switch or add one | [Rutgers-What-If-Major](https://github.com/rahulk462/Rutgers-What-If-Major) |
| 3 | **Graduation plan** `/plan` | A term-by-term plan to graduation that respects prerequisites, when courses actually run and your credit limits, with the critical path and what-if scenarios | [Rutgers-Grad-Path-Planner](https://github.com/rahulk462/Rutgers-Grad-Path-Planner) |

## How the pieces fit together

* **One record.** The home page's *Your classes* panel saves your courses to `personal/data/` (git-ignored). The planner's
  `my-record` config reads the same files, so a scraped audit, an imported CSV, or classes and AP credit you add
  on the home page show up in the planner on reload.
* **One program list.** Both tools use the same program ids (`cs-bs`, `math-minor`, `ds-bs-cs`, ...).
  `rutgers_planner/programs.py` joins them and maps each to its federal CIP code in the outcomes data
  (CS → 11.01, Math → 27.01, Statistics → 27.05, Data Science → 30.70).
* **Links between steps.** What-If results have *Plan* and *Careers* links for every program; a plan
  shows a "Where these majors lead" card with earnings and job growth; each outcomes page for a field
  with defined requirements links to a what-if and a plan for it; the home page lists every program
  with links into all three tools.
* **One course pack.** The planner ships Schedule of Classes data for Spring 2023 – Spring 2027
  (`data/soc/soc_nb.json`). Until you download terms yourself, the What-If page uses it for course
  titles, prerequisites and the course lookup.

Every program, including the five Data Science tracks and the minor, can be opened in both tools.
The planner's Data Science files (`programs/ds-*.yaml`) are converted from the What-If definitions.
A few of their courses (Data in Context `04:547:225`, `04:547:321`, some upper-level chemistry) aren't in
the bundled course pack yet, so plans flag them as "offering unknown" and schedule them anyway.
(Note: `gradplan soc --subjects ...` replaces a term's offering list with just those subjects, so
re-download a term without `--subjects` to add courses to it.)

## Run it

```bash
git clone https://github.com/rahulk462/Rutgers-Major-Planner-Merged.git
cd Rutgers-Major-Planner-Merged
python3.12 -m venv .venv && source .venv/bin/activate    # 3.10–3.13 work; OR-Tools needs a supported version
pip install -e ".[solver,dev]"                            # or: pip install -r requirements.txt
playwright install chromium                               # only needed to log in to Degree Navigator
python run.py                                             # http://127.0.0.1:5000
```

Options: `--port 8080`, `--no-browser`, `--config config/me.yaml` (planner config selected first),
`--time-limit 30` (CP-SAT seconds per plan). Without OR-Tools (`pip install -e .`) the planner uses a
heuristic selection and the greedy scheduler, and says so on every plan.

The site listens on 127.0.0.1 only and refuses requests for any other host name or from other
websites, because the What-If tool holds your Degree Navigator session.

## Use it on GitHub Pages

The site is also published at **https://rahulk462.github.io/Rutgers-Major-Planner-Merged/**
(rebuilt by `.github/workflows/pages.yml` on every push to `main`). GitHub Pages only serves files,
so the What-if and Graduation plan pages have a **Runs on** switch at the top:

| | This browser (default) | My computer |
|---|---|---|
| Setup | none | `python run.py --pages` running locally |
| How it works | the same Python code runs in the page ([Pyodide](https://pyodide.org), served from this site, ~15 MB on first visit) | the page sends its API calls to `http://127.0.0.1:5000` |
| Career outcomes, what-if, course lookup, CSV import, AP credit, plans | yes | yes |
| Degree Navigator login / discover / scrape, SOC downloads | no (a web page can't open that window) | yes |
| Optimal CP-SAT plans | no, greedy planner | yes, if OR-Tools is installed |
| Where your record lives | this browser's storage (IndexedDB), never uploaded | `personal/` on your computer |

`--pages` lets exactly `https://rahulk462.github.io` call the local APIs (`--allow-origin URL` adds
another site, `RMP_PAGES_ORIGIN` changes the default). Without it the local server still refuses
every other website. Chrome may ask once to let the page reach devices on your network; allow it.
Use Chrome, Edge or Firefox for "My computer" (Safari blocks https pages from calling `http://127.0.0.1`).
Different port: `python run.py --pages --port 8080`, then type 8080 next to "My computer".

**One-time setup:** in the repo's *Settings → Pages*, set *Source* to **GitHub Actions**. Build it
yourself with `python -m rutgers_planner.pages --out _site --fetch-pyodide --base /` and serve
`_site/` with any static server. The build packs only git-tracked files and renders with an empty
record, so nothing in `personal/` is ever published.

### Getting your classes in

Everything happens in **Your classes** on the home page, and What-if and the planner both read it:

* **A. Sign in with Rutgers** (local server or "My computer" only). *Log in to Rutgers* opens the
  Rutgers login (NetID + Duo) in a separate browser window; you sign in there yourself (the tool never
  sees your password) and click *I'm done*. *Load my classes* then pulls your Degree Navigator audit:
  the first time, click through your audit pages in that window so the tool learns where they are;
  after that it just re-fetches them, 1–2 s apart.
* **B. Enter classes yourself**, no login needed: pick a course (code or name), the semester and your
  grade (or "Taking it now"), add AP exams by score, or paste a CSV (`code,title,credits,grade,term`,
  e.g. `examples/sample_courses.csv`). On GitHub Pages in "This browser" mode they are saved in your
  browser.

See [the What-If notes](#what-if-tool-details) for the ground rules.

## Command line

Each tool's command line still works from the repo root:

```bash
python -m rutgers_whatif whatif cs-ba math-minor --current cs-bs   # what-if report
python -m rutgers_whatif add-ap "Calculus BC" 5                    # AP credit
python -m gradplan plan --config config/my-record.yaml             # plan from your record
python -m gradplan plan                                            # sample transcript (config/example.yaml)
python -m gradplan whatif                                          # compare program combinations
python -m pipeline.build                                           # rebuild outcomes data (needs .[pipeline])
python -m rutgers_planner.pages --out _site --fetch-pyodide        # GitHub Pages build
pytest -q                                                          # all tests
```

`python -m rutgers_whatif serve` and `python -m gradplan serve` still start the old single-tool pages.

## Layout

```
rutgers_planner/   the website: Flask app, shared nav, home page, outcomes pages, program registry
  tools.py         serves the What-If and planner pages and their JSON APIs under /whatif and /plan
  outcomes.py      career-outcomes pages and /outcomes/api
  programs.py      program ids <-> tools <-> CIP codes
  pages/           GitHub Pages build, Pyodide download, and the in-browser API (browser_api.py)
  static/          shared CSS/JS; backend.js + pyworker.js run the tool pages on GitHub Pages
rutgers_whatif/    Degree Navigator login, scraping, parsing, what-if engine (programs/*.json)
gradplan/          prerequisites, offering patterns, course selection, CP-SAT / greedy scheduling
pipeline/          downloads and joins the outcomes sources into data/processed/
config/            planner configs (my-record.yaml, example.yaml) and course fixes
programs/          planner requirement files (YAML)
data/soc/          bundled Schedule of Classes pack
data/raw, data/crosswalks, data/processed   outcomes sources and the built JSON the site reads
personal/          YOUR record and Degree Navigator session (git-ignored, created on first run)
tests/             whatif/, gradplan/, outcomes/, site/
```

## What-If tool details

* **You log in yourself** in the window it opens; the session is saved to `personal/auth.json`
  (mode 600, git-ignored) and reused until Rutgers expires it. Set `RWI_HOME` to keep it elsewhere.
* **Only your own data**, only the pages you open during discovery, fetched slowly
  (`RWI_MIN_DELAY` / `RWI_MAX_DELAY`). Follow the [Rutgers acceptable use policy](https://policies.rutgers.edu/).
* Program definitions are condensed from department pages (sources in each file). Not modeled:
  admission-to-major rules, residency, the SAS Core, Math honors/actuarial tracks.

## Planner details

Prerequisites are parsed from SOC notes (fix odd ones in `config/prereq_overrides.yaml`), offering
patterns are estimated from past terms, and every finished plan is re-validated from scratch.
Preferences (credit limits, summer/winter, locked and avoided courses, double-counting caps,
scenarios) live in `config/*.yaml` and can be changed on the page; copy `example.yaml` to
`config/me.yaml` (git-ignored) for your own.

## Outcomes data

Sources: College Scorecard field of study (Oct 2026), Census PSEO (NJ, Aug 2026), the Rutgers
First-Destination Survey (via Internet Archive snapshots while the live site was down), NY Fed
recent-graduate tables, BLS Employment Projections 2025–35 with the NCES CIP→SOC crosswalk, and the
NACE Winter 2026 salary survey. Caveats for each source are on the *Sources & caveats* page.
Rutgers–Camden and Newark are excluded.

> This is a planning aid, not an official audit. Degree Navigator, the catalog and your advisor have
> the final word.
