"""Runs the real config against the real SOC data pack in data/soc/."""

from pathlib import Path

from gradplan import export
from gradplan.planner import load_context, run
from gradplan import planner, selection
from gradplan.prereqs import satisfied
from gradplan.whatif import compare

CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "example.yaml"


def test_example_plan_is_valid(tmp_path):
    ctx = load_context(CONFIG)
    r = run(ctx, time_limit=20)
    assert r.report.ok, [i.message for i in r.report.issues if i.level == "error"]
    assert r.selection.unmet == []
    assert r.plan.method == ("cp-sat" if selection.HAVE_ORTOOLS else "greedy")
    # every planned course: prerequisites done earlier, offered that term
    for c, t in r.plan.placement.items():
        earlier = ctx.done | {d for d, tt in r.plan.placement.items() if tt < t}
        assert satisfied(ctx.catalog.get(c).prereq.tree, earlier, r.plan.courses_in(t))
        assert ctx.catalog.offered(c, t)
    for t in r.plan.used_terms():
        load = sum(ctx.catalog.get(c).credits for c in r.plan.courses_in(t)) + r.plan.filler.get(t, 0)
        assert load <= ctx.prefs.max_credits
    export.to_csv(r, tmp_path / "p.csv")
    export.to_html(r, tmp_path / "p.html")
    assert "01:198:344" in (tmp_path / "p.csv").read_text()


def test_greedy_also_valid():
    ctx = load_context(CONFIG)
    r = run(ctx, solver="greedy")
    assert r.report.ok, [i.message for i in r.report.issues if i.level == "error"]


def test_whatif_adds_statistics():
    ctx = load_context(CONFIG)
    rows = compare(ctx, {"base": ["cs-bs", "math-ba"], "plus stat": ["cs-bs", "math-ba", "stat-ba"]}, time_limit=20)
    base, stat = rows
    assert stat["new_courses"] > base["new_courses"]
    assert any(c.startswith("01:960:") for c in stat["extra_courses"])
    assert stat["double_counted"] >= base["double_counted"]


def test_soc_pack_has_real_prereqs():
    ctx = load_context(CONFIG)
    c = ctx.catalog.get("01:198:344")
    assert c.prereq.ok and "01:198:122" in str(c.prereq.tree)       # 112 mapped to new 122
    assert ctx.catalog.get("01:960:381").offering.label() == "Fall only"


def test_runs_without_ortools(monkeypatch):
    """With ortools missing, the heuristic selection + greedy scheduler still give a valid plan."""
    monkeypatch.setattr(selection, "HAVE_ORTOOLS", False)
    monkeypatch.setattr(planner, "HAVE_ORTOOLS", False)
    ctx = load_context(CONFIG)
    r = run(ctx)
    assert r.plan.method == "greedy" and r.selection.status == "heuristic"
    assert r.report.ok, [i.message for i in r.report.issues if i.level == "error"]
    assert r.selection.unmet == []
    assert any("OR-Tools" in n for n in r.plan.notes)
