"""Glue: read the config, load everything, select courses, schedule, validate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import transcript
from .codes import Term
from .graph import depth
from .programs import Program, load_programs
from .schedule import Plan, Prefs, cpsat, greedy
from .selection import HAVE_ORTOOLS, Selection, select
from .soc import Catalog, Equivalents, load_pack
from .validate import Report, validate

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Context:
    config: dict
    base: Path
    catalog: Catalog
    eq: Equivalents
    taken: list[transcript.Taken]
    done: set[str]
    in_progress: set[str]
    prefs: Prefs
    policies: dict


@dataclass
class Result:
    programs: list[Program]
    selection: Selection
    plan: Plan
    report: Report
    ctx: Context
    greedy_plan: Plan | None = None
    depths: dict[str, int] = field(default_factory=dict)

    @property
    def grad_term(self) -> Term | None:
        return self.plan.last_term()


WHATIF_PREFIX = "whatif:"


def whatif_data_dir() -> Path:
    """Where the What-If tool in this repo keeps your record (personal/data/, or $RWI_HOME/data)."""
    try:
        from rutgers_whatif import config as rwi
        return Path(rwi.DATA_DIR)
    except ImportError:  # planner used on its own
        return ROOT / "personal" / "data"


def _path(base: Path, p: str) -> Path:
    """Config paths are relative to the config file; ``whatif:NAME`` means the What-If tool's data folder."""
    if str(p).startswith(WHATIF_PREFIX):
        return whatif_data_dir() / str(p)[len(WHATIF_PREFIX):]
    q = Path(p).expanduser()
    return q if q.is_absolute() else (base / q)


def load_context(config_path: Path | str, overrides: dict | None = None) -> Context:
    config_path = Path(config_path)
    cfg = yaml.safe_load(config_path.read_text()) or {}
    for k, v in (overrides or {}).items():
        if v is not None:
            cfg.setdefault("plan", {})[k] = v
    return context_from_config(cfg, config_path.parent)


def context_from_config(cfg: dict, base: Path) -> Context:
    """Build a Context from an already-read config dict; relative paths resolve against `base`."""
    eq_file = _path(base, cfg.get("equivalents", str(ROOT / "config" / "equivalents.yaml")))
    groups = [g["codes"] for g in (yaml.safe_load(eq_file.read_text()) or {}).get("groups", [])] if eq_file.exists() else []
    eq = Equivalents(groups)
    ov_file = _path(base, cfg.get("prereq_overrides", str(ROOT / "config" / "prereq_overrides.yaml")))
    overrides_pr = (yaml.safe_load(ov_file.read_text()) or {}) if ov_file.exists() else {}
    overrides_pr = {k: v for k, v in (overrides_pr.get("overrides") or {}).items()}
    facts_file = _path(base, cfg.get("course_facts_file", str(ROOT / "config" / "course_facts.yaml")))
    facts = (yaml.safe_load(facts_file.read_text()) or {}).get("courses", {}) if facts_file.exists() else {}
    facts.update(cfg.get("course_facts") or {})
    pk = cfg.get("soc_pack", str(ROOT / "data" / "soc" / "soc_nb.json"))
    plan_cfg = cfg.get("plan", {}) or {}
    catalog = Catalog(load_pack(_path(base, pk)), eq, overrides_pr,
                      threshold=float(plan_cfg.get("offering_threshold", 0.5)),
                      extra=facts)

    st = cfg.get("student", {}) or {}
    taken = transcript.load([_path(base, p) for p in st.get("transcript", [])], st.get("extra_courses"))
    done = {eq.canon(t.code) for t in taken if t.status in ("passed", "in_progress")}
    in_prog = {eq.canon(t.code) for t in taken if t.status == "in_progress"}
    earned = st.get("credits_earned")
    if earned is None:
        earned = sum((t.credits if t.credits is not None else catalog.get(t.code).credits)
                     for t in taken if t.status in ("passed", "in_progress"))

    prefs = Prefs(
        start=Term.parse(plan_cfg.get("start_term", "Spring 2027")),
        target=Term.parse(plan_cfg["target_graduation"]) if plan_cfg.get("target_graduation") else None,
        max_credits=float(plan_cfg.get("max_credits", 18)),
        min_credits=float(plan_cfg.get("min_credits", 12)),
        summer=bool(plan_cfg.get("summer", False)),
        winter=bool(plan_cfg.get("winter", False)),
        summer_max=float(plan_cfg.get("summer_max_credits", 8)),
        winter_max=float(plan_cfg.get("winter_max_credits", 4)),
        total_required=float(plan_cfg.get("total_credits_required", 120)),
        credits_earned=float(earned),
        locked={eq.canon(c): Term.parse(t) for c, t in (plan_cfg.get("locked") or {}).items()},
        hard={eq.canon(c) for c in plan_cfg.get("hard_courses", []) or []},
        max_hard_per_term=int(plan_cfg.get("max_hard_per_term", 1)),
        objective=plan_cfg.get("objective", "min_terms"),
        horizon_terms=int(plan_cfg.get("horizon_terms", 12)),
        fill_electives=bool(plan_cfg.get("fill_electives", True)),
    )
    return Context(config=cfg, base=base, catalog=catalog, eq=eq, taken=taken, done=done,
                   in_progress=in_prog, prefs=prefs, policies=cfg.get("double_counting", {}) or {})


def run(ctx: Context, program_ids: list[str] | None = None, solver: str | None = None,
        time_limit: float = 60.0) -> Result:
    cfg = ctx.config
    plan_cfg = cfg.get("plan", {}) or {}
    ids = program_ids or cfg.get("programs", [])
    dirs = [_path(ctx.base, d) for d in cfg.get("program_dirs", [])] + [ROOT / "programs"]
    programs = load_programs(ids, dirs, ctx.eq.canon)
    canon = ctx.eq.canon
    sel = select(programs, ctx.catalog, ctx.done,
                 exclude={canon(c) for c in plan_cfg.get("exclude", []) or []},
                 include={canon(c) for c in plan_cfg.get("include", []) or []} | set(ctx.prefs.locked),
                 prefer={canon(c) for c in plan_cfg.get("prefer", []) or []},
                 avoid=plan_cfg.get("avoid", []) or [],
                 policies=ctx.policies)
    courses = sel.new_courses
    g = greedy(courses, ctx.catalog, ctx.done, ctx.prefs)
    solver = solver or plan_cfg.get("solver", "cpsat")
    plan = g
    if not HAVE_ORTOOLS:
        if solver == "cpsat":
            g.notes.append("OR-Tools isn't installed, so this plan uses the greedy scheduler and a heuristic "
                           "course selection. Install ortools (Python 3.10-3.13 recommended) for optimal plans.")
        solver = "greedy"
    if solver == "cpsat":
        c = cpsat(courses, ctx.catalog, ctx.done, ctx.prefs, time_limit=time_limit, hint=g)
        if c.placement or not courses:
            plan = c
        else:
            g.notes.extend(c.notes)
            g.notes.append("Fell back to the greedy plan because CP-SAT found no feasible schedule")
    rep = validate(plan, ctx.catalog, programs, ctx.done, ctx.in_progress, ctx.prefs, ctx.policies)
    for u in sel.unmet:
        rep.add("error", None, f"Can't satisfy {u['program']} / {u['name']} with known courses: {u['detail']}")
    fdone = frozenset(ctx.done)
    depths = {c: depth(ctx.catalog, c, fdone) for c in courses}
    return Result(programs=programs, selection=sel, plan=plan, report=rep, ctx=ctx,
                  greedy_plan=g if plan is not g else None, depths=depths)
