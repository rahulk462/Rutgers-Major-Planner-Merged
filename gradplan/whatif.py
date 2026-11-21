"""What-if comparisons: plan several program combinations and compare them."""

from __future__ import annotations

from .planner import Context, Result, run


def compare(ctx: Context, scenarios: dict[str, list[str]], solver: str | None = None,
            time_limit: float = 45.0) -> list[dict]:
    results: dict[str, Result] = {name: run(ctx, ids, solver, time_limit) for name, ids in scenarios.items()}
    base_name = next(iter(scenarios))
    base = results[base_name]
    base_terms = len(base.plan.used_terms())
    base_courses = set(base.selection.new_courses)
    rows = []
    for name, r in results.items():
        terms = len(r.plan.used_terms())
        new = set(r.selection.new_courses)
        shared = sorted({c for codes in r.selection.shared.values() for c in codes})
        course_terms = [t for t in r.plan.used_terms() if r.plan.courses_in(t)]
        rows.append({
            "requirements_done": course_terms[-1].name if course_terms else "-",
            "scenario": name,
            "programs": scenarios[name],
            "graduation": r.grad_term.name if r.grad_term else "-",
            "terms": terms,
            "extra_terms": terms - base_terms,
            "new_courses": len(new),
            "new_credits": sum(r.ctx.catalog.get(c).credits for c in new),
            "extra_courses": sorted(new - base_courses),
            "dropped_courses": sorted(base_courses - new),
            "double_counted": len(shared),
            "double_counted_courses": shared,
            "errors": sum(1 for i in r.report.issues if i.level == "error"),
            "risks": sum(1 for i in r.report.issues if i.level == "risk"),
            "result": r,
        })
    return rows
