"""Command line: ``python -m gradplan <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .codes import Term

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "example.yaml"


def _ctx(args):
    from .planner import load_context
    over = {}
    for k in ("start_term", "target_graduation", "max_credits", "min_credits", "objective"):
        v = getattr(args, k, None)
        if v is not None:
            over[k] = v
    if getattr(args, "summer", False):
        over["summer"] = True
    if getattr(args, "winter", False):
        over["winter"] = True
    return load_context(args.config, over)


def cmd_plan(args):
    from . import export
    from .planner import run
    ctx = _ctx(args)
    r = run(ctx, args.programs or None, args.solver, args.time_limit)
    print(export.to_text_report(r))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    export.to_csv(r, out / "plan.csv")
    (out / "plan.json").write_text(json.dumps(export.to_json(r), indent=2))
    export.to_html(r, out / "plan.html")
    print(f"\nWrote {out/'plan.csv'}, {out/'plan.json'}, {out/'plan.html'}")
    return 0 if r.report.ok else 1


def cmd_whatif(args):
    from . import export
    from .whatif import compare
    ctx = _ctx(args)
    scen = ctx.config.get("scenarios") or {}
    if args.scenario:
        scen = {s.split("=")[0]: s.split("=")[1].split(",") for s in args.scenario}
    if not scen:
        print("No scenarios: add `scenarios:` to the config or pass --scenario 'Name=cs-bs,math-ba'")
        return 2
    rows = compare(ctx, scen, args.solver, args.time_limit)
    hdr = f"{'scenario':28} {'graduation':12} {'last req.':12} {'terms':>5} {'+terms':>6} {'courses':>7} {'credits':>7} {'shared':>6}"
    print(hdr)
    print("-" * len(hdr))
    for w in rows:
        print(f"{w['scenario'][:28]:28} {w['graduation']:12} {w['requirements_done']:12} {w['terms']:>5} {w['extra_terms']:>+6} "
              f"{w['new_courses']:>7} {w['new_credits']:>7g} {w['double_counted']:>6}")
        if w["extra_courses"]:
            print(f"    extra vs baseline: {', '.join(w['extra_courses'])}")
        if w["errors"]:
            print(f"    {w['errors']} validation error(s): run `plan` with these programs for details")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    export.to_html(rows[0]["result"], out / "whatif.html", rows)
    (out / "whatif.json").write_text(json.dumps([{k: v for k, v in w.items() if k != "result"} for w in rows], indent=2))
    for w in rows:
        slug = "".join(ch if ch.isalnum() else "-" for ch in w["scenario"].lower()).strip("-")
        export.to_csv(w["result"], out / f"plan-{slug}.csv")
    print("\n'last req.' = last term with a required course; later terms only add open credits toward 120.")
    print(f"\nWrote {out/'whatif.html'} and one CSV per scenario in {out}/")
    return 0


def cmd_prereqs(args):
    from .graph import depth
    from .prereqs import to_text
    ctx = _ctx(args)
    cat = ctx.catalog
    codes = args.codes or sorted(cat.all_codes())
    flagged = 0
    for c in codes:
        info = cat.get(c)
        if args.flagged and not info.prereq.flags:
            continue
        flagged += bool(info.prereq.flags)
        print(f"{c}  {info.title[:40]:40}  depth {depth(cat, c)}  remaining {depth(cat, c, frozenset(ctx.done))}")
        print(f"    offered: {info.offering.label()}")
        print(f"    prereq:  {to_text(info.prereq.tree)}")
        if info.prereq.flags:
            print(f"    FLAG:    {'; '.join(info.prereq.flags)}   raw: {info.prereq.raw[:200]}")
    if args.flagged:
        print(f"\n{flagged} course(s) need a manual fix in config/prereq_overrides.yaml")
    return 0


def cmd_soc(args):
    from .soc import DEFAULT_PACK, build_pack
    terms = [Term.parse(t) for t in args.terms]
    subjects = set(args.subjects) if args.subjects else None
    pack = build_pack(terms, subjects, out=Path(args.out) if args.out else DEFAULT_PACK)
    print(f"Pack now covers {len(pack['terms'])} terms and {len(pack['catalog'])} courses")
    return 0


def cmd_programs(args):
    from .programs import available_programs
    for pid, name in available_programs():
        print(f"{pid:14} {name}")
    return 0


def cmd_serve(args):
    from .web import serve
    serve(args.host, args.port, args.config, not args.no_browser, args.time_limit)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gradplan", description="Rutgers semester-by-semester graduation planner")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--config", default=str(DEFAULT_CONFIG), help="plan config YAML")
        p.add_argument("--start-term", dest="start_term")
        p.add_argument("--target", dest="target_graduation")
        p.add_argument("--max-credits", dest="max_credits", type=float)
        p.add_argument("--min-credits", dest="min_credits", type=float)
        p.add_argument("--summer", action="store_true", help="allow summer terms")
        p.add_argument("--winter", action="store_true", help="allow winter sessions")
        p.add_argument("--objective", choices=["min_terms", "balance"])
        p.add_argument("--solver", choices=["cpsat", "greedy"])
        p.add_argument("--time-limit", type=float, default=60.0)
        p.add_argument("--out", default="out")

    p = sub.add_parser("plan", help="build, validate and export a plan")
    common(p)
    p.add_argument("--programs", nargs="*", help="program ids (default: from the config)")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("whatif", help="compare program combinations")
    common(p)
    p.add_argument("--scenario", action="append", help="'Name=prog1,prog2' (repeatable)")
    p.set_defaults(fn=cmd_whatif)

    p = sub.add_parser("prereqs", help="show parsed prerequisites, chain depth and offering pattern")
    common(p)
    p.add_argument("codes", nargs="*")
    p.add_argument("--flagged", action="store_true", help="only prerequisites the parser couldn't read")
    p.set_defaults(fn=cmd_prereqs)

    p = sub.add_parser("soc", help="download Schedule of Classes terms into the data pack")
    p.add_argument("terms", nargs="+", help="e.g. 'Fall 2026' 2027_1")
    p.add_argument("--subjects", nargs="*", help="e.g. 01:198 01:640 (default: all)")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_soc)

    p = sub.add_parser("serve", help="start the web UI on http://localhost:8000")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    p.add_argument("--config", help="plan config to select first (default: config/my-record.yaml)")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.add_argument("--time-limit", type=float, default=30.0, help="CP-SAT seconds per plan")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("programs", help="list program definitions")
    p.set_defaults(fn=cmd_programs)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except ModuleNotFoundError as e:
        if e.name in ("yaml", "ortools"):
            print(f"Missing Python package {e.name!r}. From the repo folder run:\n"
                  "    python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt\n"
                  "then try again (activate the venv in every new terminal).", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
