import json
import sqlite3

import pytest

from gradplan import transcript
from gradplan.codes import Term, matches
from gradplan.graph import depth
from gradplan.programs import Program, Requirement, Rule
from gradplan.prereqs import satisfied
from gradplan.schedule import Plan, Prefs, cpsat, greedy
from gradplan.selection import HAVE_ORTOOLS, audit, select
from gradplan.soc import Offering
from gradplan.validate import validate

needs_ortools = pytest.mark.skipif(not HAVE_ORTOOLS, reason="CP-SAT needs ortools")


def prog(pid, *reqs, **kw):
    return Program(id=pid, name=pid, requirements=list(reqs), **kw)


def test_patterns_and_terms():
    assert matches("01:640:354", "01:640:3xx")
    assert not matches("01:640:454", "01:640:3xx")
    assert matches("01:640:454", "01:640:3xx+")
    assert matches("01:198:111", "01:198:*")
    assert Term.parse("Fall 2026") < Term.parse("2027_0") < Term.parse("Spring 2027")
    assert Term.parse("Spring 2027").next() == Term(2027, 7)


def test_offering_patterns(toy_catalog):
    assert toy_catalog.get("01:198:301").offering.label() == "Fall only"
    assert toy_catalog.offered("01:198:301", Term(2027, 9))
    assert not toy_catalog.offered("01:198:301", Term(2027, 1))
    off = Offering(seen={9: 2}, observed={9: 4}, years={9: {2023, 2025}})
    assert off.parity(9) == 1 and off.predicts(Term(2027, 9)) and not off.predicts(Term(2026, 9))


def test_equivalents_canonicalize(toy_catalog):
    assert toy_catalog.eq.canon("01:198:099") == "01:198:101"
    assert "01:198:099" in toy_catalog


def test_depth(toy_catalog):
    assert depth(toy_catalog, "01:198:302") == 4         # 101 -> 102 -> 201 -> 301 -> 302
    assert depth(toy_catalog, "01:198:302", frozenset({"01:198:101", "01:198:102"})) == 2


CORE = Requirement(id="core", name="core", type="required", courses=["01:198:101", "01:198:102", "01:198:201"])
ELECT = Requirement(id="el", name="electives", type="choose", count=2,
                    from_=["01:198:3xx"], rules=[Rule(from_=["01:198:302"], max=0)])


def test_selection_closes_prereqs(toy_catalog):
    sel = select([prog("cs", CORE, ELECT)], toy_catalog, done=set())
    assert not sel.unmet
    assert {"01:198:101", "01:198:102", "01:198:201"} <= set(sel.new_courses)
    el = sel.assignment["cs"]["el"]
    assert len(el) == 2 and "01:198:302" not in el
    # cheapest electives: 3-credit ones without extra prerequisites
    assert set(el) <= {"01:198:310", "01:198:320", "01:198:330"}
    for c in sel.new_courses:
        assert satisfied(toy_catalog.get(c).prereq.tree, set(sel.new_courses))


def test_one_set_credits_and_level(toy_catalog):
    sci = Requirement(id="sci", name="sci", type="one_set", sets=[["01:750:201", "01:750:202"], ["01:640:151", "01:640:152"]])
    cr = Requirement(id="cr", name="cr", type="credits", min_credits=6, from_=["01:198:3xx+"])
    sel = select([prog("p", sci, cr)], toy_catalog, done={"01:640:151"})
    assert not sel.unmet
    assert sel.assignment["p"]["sci"] == ["01:640:151", "01:640:152"]
    assert sum(toy_catalog.get(c).credits for c in sel.assignment["p"]["cr"]) >= 6


def test_double_count_cap(toy_catalog):
    a = prog("a", Requirement(id="m", name="m", type="choose", count=2, from_=["01:198:310", "01:198:320", "01:198:330"]))
    b = prog("b", Requirement(id="m", name="m", type="choose", count=2, from_=["01:198:310", "01:198:320", "01:198:330"]))
    done = {"01:198:101", "01:198:102"}
    free = select([a, b], toy_catalog, done)
    assert len(free.new_courses) == 2 and len(free.shared["a+b"]) == 2
    capped = select([a, b], toy_catalog, done, policies={"max_shared": 1})
    assert len(capped.new_courses) == 3 and len(capped.shared["a+b"]) == 1


def test_unmet_reported(toy_catalog):
    r = Requirement(id="x", name="x", type="required", courses=["01:999:101"])
    sel = audit([prog("p", r)], toy_catalog, set())
    assert sel.unmet and "01:999:101" in sel.unmet[0]["detail"]


def _prefs(**kw):
    base = dict(start=Term(2027, 1), max_credits=8, min_credits=0, total_required=0, fill_electives=False,
                horizon_terms=8)
    base.update(kw)
    return Prefs(**base)


CHAIN = ["01:198:101", "01:198:102", "01:198:201", "01:198:301", "01:198:302", "01:198:330"]


@pytest.mark.parametrize("scheduler", [greedy, pytest.param(cpsat, marks=needs_ortools)])
def test_schedulers_respect_constraints(toy_catalog, scheduler):
    prefs = _prefs(max_credits=8, locked={"01:198:330": Term(2028, 1)})
    plan = scheduler(CHAIN, toy_catalog, set(), prefs)
    assert not plan.unscheduled
    rep = validate(plan, toy_catalog, [], set(), set(), prefs)
    assert rep.ok, [i.message for i in rep.issues]
    p = plan.placement
    assert p["01:198:101"] < p["01:198:102"] < p["01:198:201"] < p["01:198:301"] < p["01:198:302"]
    assert p["01:198:301"].season == 9 and p["01:198:302"].season == 1
    assert p["01:198:330"] == Term(2028, 1)
    # the 101->302 chain has no slack: all of it is critical
    assert {"01:198:301", "01:198:302"} <= set(rep.critical)


@needs_ortools
def test_cpsat_not_worse_than_greedy(toy_catalog):
    prefs = _prefs(max_credits=8)
    g = greedy(CHAIN, toy_catalog, set(), prefs)
    c = cpsat(CHAIN, toy_catalog, set(), prefs)
    assert c.last_term() <= g.last_term()


@needs_ortools
def test_fillers_reach_total(toy_catalog):
    prefs = _prefs(max_credits=18, min_credits=12, total_required=40, fill_electives=True)
    plan = cpsat(["01:198:101", "01:198:102"], toy_catalog, set(), prefs)
    total = sum(toy_catalog.get(c).credits for c in plan.placement) + sum(plan.filler.values())
    assert total >= 40
    rep = validate(plan, toy_catalog, [], set(), set(), prefs)
    assert rep.ok


def test_validation_catches_bad_plan(toy_catalog):
    t = Term(2027, 1)
    bad = Plan(terms=[t, t.next().next().next()], placement={"01:198:102": t, "01:198:301": t})
    rep = validate(bad, toy_catalog, [prog("cs", CORE)], set(), set(), _prefs())
    msgs = " ".join(i.message for i in rep.issues if i.level == "error")
    assert "prerequisites not met" in msgs
    assert "not predicted to be offered" in msgs
    assert "missing" in msgs                      # core requirement unmet


def test_transcript_sources(tmp_path):
    (tmp_path / "a.csv").write_text("code,title,credits,grade,term\n01:640:151,Calc,4,T,AP\n198:111,Intro,4,,Fall 2026\n"
                                    "01:198:205,DS,4,F,Spring 2026\n")
    (tmp_path / "m.json").write_text(json.dumps([{"code": "01:198:205", "grade": "B", "term": "Fall 2026"}]))
    db = tmp_path / "w.sqlite"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, fetched_at TEXT, source TEXT);"
                      "CREATE TABLE courses (snapshot_id INT, code TEXT, title TEXT, credits REAL, grade TEXT, "
                      "term TEXT, status TEXT, source TEXT);"
                      "INSERT INTO snapshots VALUES (1,'x','dn');"
                      "INSERT INTO courses VALUES (1,'01:640:250','LA',3,'A','Fall 2025','passed','dn');")
    con.commit()
    con.close()
    taken = {t.code: t for t in transcript.load([tmp_path / "a.csv", tmp_path / "m.json", db])}
    assert taken["01:640:151"].status == "passed" and taken["01:640:151"].transfer
    assert taken["01:198:111"].status == "in_progress"
    assert taken["01:198:205"].status == "passed"          # later pass beats the F
    assert taken["01:640:250"].status == "passed"
