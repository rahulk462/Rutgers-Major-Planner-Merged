"""Write a plan as CSV, JSON, plain text and a single-file HTML page."""

from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path

from .planner import Result
from .prereqs import to_text
from .schedule import FILLER

CAVEAT = ("Draft to bring to your advisor, not an official audit. Credit limits, overload rules and "
          "double-counting policies vary by school: check the catalog or the dean's office. Offering "
          "patterns are estimated from past Schedule of Classes terms and are a guess, not a guarantee.")


def rows(r: Result) -> list[dict]:
    cat, plan, rep = r.ctx.catalog, r.plan, r.report
    out = []
    for t in plan.used_terms():
        for c in plan.courses_in(t):
            info = cat.get(c)
            out.append({
                "term": t.name, "code": c, "title": info.title, "credits": info.credits,
                "counts_toward": "; ".join(r.selection.requirements_of(c)),
                "offered": info.offering.label(cat.threshold),
                "critical": "yes" if c in rep.critical else "",
                "slack_offerings": rep.slack.get(c, ""),
                "next_offered_if_missed": rep.next_offered.get(c) or "",
                "chain_depth": r.depths.get(c, 0),
                "hard": "yes" if c in r.ctx.prefs.hard else "",
                "prerequisites": to_text(info.prereq.tree),
            })
        if plan.filler.get(t):
            out.append({"term": t.name, "code": FILLER, "title": "Open elective / SAS Core / minor",
                        "credits": plan.filler[t], "counts_toward": "total credits"})
    return out


CSV_FIELDS = ["term", "code", "title", "credits", "counts_toward", "offered", "critical",
              "slack_offerings", "next_offered_if_missed", "chain_depth", "hard", "prerequisites"]


def csv_text(r: Result) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    w.writeheader()
    for row in rows(r):
        w.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    return buf.getvalue()


def to_csv(r: Result, path: Path) -> Path:
    Path(path).write_text(csv_text(r))
    return Path(path)


def term_summary(r: Result) -> list[dict]:
    cat = r.ctx.catalog
    out = []
    for t in r.plan.used_terms():
        cs = r.plan.courses_in(t)
        cr = sum(cat.get(c).credits for c in cs)
        out.append({"term": t.name, "courses": cs, "course_credits": cr,
                    "elective_credits": r.plan.filler.get(t, 0),
                    "total_credits": cr + r.plan.filler.get(t, 0)})
    return out


def to_json(r: Result) -> dict:
    return {
        "programs": [p.id for p in r.programs],
        "method": r.plan.method, "status": r.plan.status,
        "graduation": r.grad_term.name if r.grad_term else None,
        "credits_earned": r.ctx.prefs.credits_earned,
        "terms": term_summary(r),
        "courses": rows(r),
        "critical_path": r.report.critical,
        "critical_chains": r.report.chains,
        "requirements": r.selection.assignment,
        "double_counted": r.selection.shared,
        "issues": [{"level": i.level, "course": i.code, "message": i.message} for i in r.report.issues],
        "caveat": CAVEAT,
    }


def to_text_report(r: Result) -> str:
    cat = r.ctx.catalog
    lines = [f"Plan for {', '.join(p.name for p in r.programs)}  ({r.plan.method}, {r.plan.status})",
             f"Graduation: {r.grad_term.name if r.grad_term else '-'}   "
             f"credits earned so far: {r.ctx.prefs.credits_earned:g}", ""]
    for s in term_summary(r):
        lines.append(f"{s['term']}  ({s['total_credits']:g} cr)")
        for c in s["courses"]:
            info = cat.get(c)
            mark = " *" if c in r.report.critical else ""
            lines.append(f"   {c}  {info.title[:42]:42} {info.credits:>4g}  {info.offering.label()}{mark}")
        if s["elective_credits"]:
            lines.append(f"   {'ELECTIVE':10}  {'open elective / SAS Core':42} {s['elective_credits']:>4g}")
    lines += ["", "* critical path: missing it in that term delays graduation"]
    if r.report.chains:
        lines.append("Critical chains: " + " | ".join(" -> ".join(ch) for ch in r.report.chains[:5]))
    if r.selection.shared:
        for k, v in r.selection.shared.items():
            lines.append(f"Double-counted ({k}): {len(v)}: {', '.join(v)}")
    lines.append("")
    for lvl in ("error", "risk", "info"):
        for i in r.report.issues:
            if i.level == lvl:
                lines.append(f"[{lvl}] {i.message}")
    lines += ["", CAVEAT]
    return "\n".join(lines)


def to_html(r: Result, path: Path, whatif: list[dict] | None = None) -> Path:
    data = to_json(r)
    if whatif:
        data["whatif"] = [{k: v for k, v in w.items() if k != "result"} for w in whatif]
    payload = json.dumps(data).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(
        " + ".join(p.name for p in r.programs)))
    Path(path).write_text(page)
    return Path(path)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Graduation plan</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;--accent:#cc0033;--risk:#b26b00;--err:#c62828;--ok:#2e7d32;--chip:#f0f0ec}
@media (prefers-color-scheme:dark){:root{--bg:#161617;--card:#1f1f21;--ink:#ececec;--muted:#a0a0a6;--line:#333336;--accent:#ff4d6d;--risk:#e0a040;--err:#ef6b6b;--ok:#6fbf73;--chip:#2a2a2d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}
.sub{color:var(--muted);margin:0 0 18px}.stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:120px}.stat b{display:block;font-size:20px}
.stat span{color:var(--muted);font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.term{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.term h3{margin:0 0 8px;font-size:15px;display:flex;justify-content:space-between}
.term h3 small{color:var(--muted);font-weight:500}.c{padding:6px 0;border-top:1px solid var(--line);font-size:13.5px}.c:first-of-type{border-top:0}
.c .code{font-variant-numeric:tabular-nums;font-weight:600}.c .t{color:var(--muted)}.crit{border-left:3px solid var(--accent);padding-left:7px;margin-left:-10px}
.tag{display:inline-block;background:var(--chip);border-radius:6px;padding:0 6px;font-size:12px;color:var(--muted);margin-right:4px}
.tag.cr{color:var(--accent)}.fill{color:var(--muted);font-style:italic}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
.wrap{overflow-x:auto}.lv-error{color:var(--err)}.lv-risk{color:var(--risk)}.lv-info{color:var(--muted)}
ul.issues{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 10px 10px 28px;margin:0}
.caveat{margin-top:28px;color:var(--muted);font-size:13px}
</style></head><body><main>
<h1>__TITLE__</h1><p class="sub" id="sub"></p>
<div class="stats" id="stats"></div>
<h2>Term by term</h2><div class="grid" id="terms"></div>
<h2>Critical path</h2><p class="sub">Courses with no slack: missing one in its planned term pushes graduation back.</p><div id="crit"></div>
<div id="wi"></div>
<h2>Requirements</h2><div class="wrap"><table id="reqs"><thead><tr><th>Program</th><th>Requirement</th><th>Courses</th></tr></thead><tbody></tbody></table></div>
<h2>Checks</h2><ul class="issues" id="issues"></ul>
<p class="caveat" id="cav"></p>
</main><script>
const D=__DATA__;const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('sub').textContent=`Graduation ${D.graduation||'-'} · ${D.method} solver (${D.status}) · programs: ${D.programs.join(', ')}`;
const nCourses=D.courses.filter(c=>c.code!=='ELECTIVE').length;const tot=D.terms.reduce((a,t)=>a+t.total_credits,0);
const nErr=D.issues.filter(i=>i.level==='error').length,nRisk=D.issues.filter(i=>i.level==='risk').length;
$('stats').innerHTML=[[D.terms.length,'terms left'],[nCourses,'courses to take'],[tot,'credits planned'],[D.credits_earned,'credits earned'],[D.critical_path.length,'critical courses'],[nErr?nErr+' errors':'valid',nRisk+' risks']].map(([b,s])=>`<div class="stat"><b>${esc(b)}</b><span>${esc(s)}</span></div>`).join('');
const byTerm={};D.courses.forEach(c=>(byTerm[c.term]=byTerm[c.term]||[]).push(c));
$('terms').innerHTML=D.terms.map(t=>`<div class="term"><h3>${esc(t.term)}<small>${t.total_credits} cr</small></h3>${(byTerm[t.term]||[]).map(c=>c.code==='ELECTIVE'?`<div class="c fill">${c.credits} cr open elective / SAS Core / minor</div>`:`<div class="c ${c.critical?'crit':''}"><span class="code">${esc(c.code)}</span> <span class="tag">${c.credits} cr</span>${c.critical?'<span class="tag cr">critical</span>':''}${c.hard?'<span class="tag">hard</span>':''}<br><span class="t">${esc(c.title)}</span><br><span class="tag">${esc(c.offered)}</span></div>`).join('')}</div>`).join('');
$('crit').innerHTML=D.critical_chains.length?'<ul class="issues">'+D.critical_chains.map(ch=>`<li>${ch.map(esc).join(' → ')}</li>`).join('')+'</ul>':'<p class="sub">Nothing is critical: every course has at least one later offering before graduation.</p>';
const tb=$('reqs').querySelector('tbody');Object.entries(D.requirements).forEach(([p,rs])=>Object.entries(rs).forEach(([r,cs])=>{tb.insertAdjacentHTML('beforeend',`<tr><td>${esc(p)}</td><td>${esc(r)}</td><td>${cs.map(esc).join(', ')||'<span class="lv-error">none</span>'}</td></tr>`)}));
$('issues').innerHTML=D.issues.length?D.issues.map(i=>`<li class="lv-${i.level}"><b>${i.level}</b> ${esc(i.message)}</li>`).join(''):'<li class="lv-info">No issues found.</li>';
if(D.whatif){$('wi').innerHTML='<h2>What-if comparison</h2><div class="wrap"><table><thead><tr><th>Scenario</th><th>Graduation</th><th>Last required course</th><th>Terms</th><th>Extra terms</th><th>New courses</th><th>New credits</th><th>Double-counted</th><th>Extra courses vs baseline</th></tr></thead><tbody>'+D.whatif.map(w=>`<tr><td>${esc(w.scenario)}</td><td>${esc(w.graduation)}</td><td>${esc(w.requirements_done)}</td><td>${w.terms}</td><td>${w.extra_terms>0?'+':''}${w.extra_terms}</td><td>${w.new_courses}</td><td>${w.new_credits}</td><td>${w.double_counted}</td><td>${w.extra_courses.map(esc).join(', ')}</td></tr>`).join('')+'</tbody></table></div>'}
$('cav').textContent=D.caveat;
</script></body></html>
"""
