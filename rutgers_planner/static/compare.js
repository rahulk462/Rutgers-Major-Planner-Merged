// Compare page for the GitHub Pages copy of the site. The Flask site renders ?c=11.01,27.01 on the
// server (templates/outcomes/compare.html); a static site can't, so this builds the same chart and
// table in the browser from the per-major JSON files the Pages build writes to static/outcomes/.
(function () {
  'use strict';

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const numOf = (v) => (v === null || v === undefined || typeof v === 'boolean' || v === '' || isNaN(Number(v)) ? null : Number(v));
  const money = (v) => { v = numOf(v); return v === null ? '—' : '$' + Math.round(v).toLocaleString('en-US'); };
  const pct = (v, d = 0) => { v = numOf(v); return v === null ? '—' : v.toFixed(d) + '%'; };
  const signed = (v) => { v = numOf(v); return v === null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; };
  const get = (o, ...keys) => keys.reduce((a, k) => (a && typeof a === 'object' ? a[k] : undefined), o);
  const fds = (m) => (m.fds && m.fds.majors && m.fds.majors.length ? m.fds.majors[0] : (m.fds || {}).school) || null;

  function table(majors, majorUrl) {
    const n = majors.length;
    const group = (t) => `<tr class="group"><th colspan="${n + 1}">${esc(t)}</th></tr>`;
    const row = (label, f, cls = 'num') => `<tr><th scope="row">${esc(label)}</th>${majors.map((m) => `<td class="${cls}">${f(m)}</td>`).join('')}</tr>`;
    const rows = [
      group('Earnings: College Scorecard (federal-aid recipients)'),
      row('RU–NB, 1 yr', (m) => money(get(m, 'scorecard', 'rutgers', 'earn_1yr'))),
      row('National, 1 yr', (m) => money(get(m, 'scorecard', 'national', 'mdn_1yr'))),
      row('RU–NB, 5 yr', (m) => money(get(m, 'scorecard', 'rutgers', 'earn_5yr'))),
      row('National, 5 yr', (m) => money(get(m, 'scorecard', 'national', 'mdn_5yr'))),
      row('Median debt', (m) => money(get(m, 'scorecard', 'rutgers', 'median_debt'))),
      group('Earnings: Census PSEO (all grads in covered jobs)'),
    ];
    for (const [y, lab] of [['y1', '1 yr'], ['y5', '5 yr'], ['y10', '10 yr']]) {
      rows.push(row(`RU–NB, ${lab}`, (m) => money(get(m, 'pseo', 'rutgers', y, 'p50'))));
      rows.push(row(`NJ statewide, ${lab}`, (m) => money(get(m, 'pseo', 'nj', y, 'p50')), 'num muted'));
    }
    rows.push(
      row('Employed 1 yr after (field)', (m) => pct(get(m, 'pseo', 'flows', 'employment', 'y1', 'employed_share'))),
      row('Top industry (field)', (m) => { const ind = get(m, 'pseo', 'flows', 'industries') || []; return ind.length ? esc(ind[0].label) : '—'; }, ''),
      group('Rutgers First-Destination Survey'),
      row('Starting salary', (m) => { const f = fds(m); return f ? `${money(f.median_salary)}<div class="muted small">${esc(m.fds.majors && m.fds.majors.length ? 'major' : m.fds.school_name)}, ${esc(f.class_year)}</div>` : '—'; }),
      row('Knowledge rate', (m) => pct((fds(m) || {}).knowledge_rate, 1)),
      row('Top employers', (m) => { const f = fds(m); return f ? esc((f.top_employers || []).slice(0, 3).join(', ')) : '—'; }, 'small'),
      group('National context'),
      row('Unemployment, recent grads', (m) => pct(get(m, 'nyfed', 'unemployment_rate'), 1)),
      row('Underemployment, recent grads', (m) => pct(get(m, 'nyfed', 'underemployment_rate'), 1)),
      row('Mid-career wage (national)', (m) => money(get(m, 'nyfed', 'wage_mid'))),
      row('Job growth, linked occupations', (m) => signed(get(m, 'bls', 'growth_pct'))),
      row('NACE 2026 avg. starting salary', (m) => m.nace ? `${money(m.nace.avg_starting_salary)}<div class="muted small">${esc(m.nace.category)}</div>` : '—'),
    );
    const head = majors.map((m, i) => `<th><span class="swatch s${i + 1}"></span><a href="${esc(majorUrl + m.cip4 + '/')}">${esc(m.title)}</a><div class="muted small">CIP ${esc(m.cip4)}</div></th>`).join('');
    return `<table class="data-table compare-table"><thead><tr><th></th>${head}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }

  async function init() {
    window.MTO.initCompareForm('compare-form', 'compare-c');
    const box = document.getElementById('static-compare');
    const want = [...new Set((new URLSearchParams(location.search).get('c') || '').split(',').map((c) => c.trim()).filter(Boolean))].slice(0, 3);
    const selects = document.querySelectorAll('#compare-form select[name=pick]');
    const known = new Set([...(selects[0] ? selects[0].options : [])].map((o) => o.value).filter(Boolean));
    const cips = want.filter((c) => known.has(c));
    cips.forEach((c, i) => { if (selects[i]) selects[i].value = c; });
    if (!box || !cips.length) return;

    let majors;
    try {
      majors = await Promise.all(cips.map((c) => fetch(box.dataset.src + encodeURIComponent(c) + '.json').then((r) => {
        if (!r.ok) throw new Error(`${c}: ${r.status}`);
        return r.json();
      })));
    } catch (e) {
      box.innerHTML = `<p class="muted">Couldn't load the majors (${esc(e.message)}).</p>`;
      return;
    }
    const empty = document.getElementById('compare-empty');
    if (empty && majors.length >= 2) empty.hidden = true;
    const majorUrl = box.dataset.major || '';
    const caveats = document.getElementById('compare-caveats');
    box.innerHTML = `
      <section class="panel">
        <h2>Earnings over time</h2>
        <p class="muted">Rutgers–NB medians. Solid lines: College Scorecard (1, 4, 5, 7 years). Dashed: Census PSEO (1, 5, 10 years).</p>
        <div class="chart-box"><canvas id="compare-chart" role="img" aria-label="Earnings comparison chart"></canvas></div>
      </section>
      <section class="panel"><div class="table-scroll">${table(majors, majorUrl)}</div></section>
      <section class="panel"><h2>Caveats</h2>${caveats ? caveats.innerHTML : ''}</section>`;
    window.MTO.compareChart('compare-chart', majors);
  }

  window.RMPCompare = { init };
})();
