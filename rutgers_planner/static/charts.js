/* Charts and small interactions for Major → Outcomes. Uses Chart.js 4 (global `Chart`). */
(function () {
  'use strict';

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const money = (v) => (v == null ? '—' : '$' + Math.round(v).toLocaleString('en-US'));
  const series = (i) => css(`--series-${i}`);

  function baseOptions(yTitle) {
    const text = css('--text-secondary');
    const grid = css('--grid');
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'start', labels: { color: text, usePointStyle: true, boxWidth: 8, filter: (i) => !i.text.startsWith('_') } },
        tooltip: {
          filter: (item) => !item.dataset.label.startsWith('_') && item.parsed.y != null,
          callbacks: { label: (c) => `${c.dataset.label}: ${money(c.parsed.y)}` },
        },
      },
      scales: {
        x: { type: 'linear', ticks: { color: text, stepSize: 1 }, grid: { display: false }, border: { color: grid } },
        y: { beginAtZero: true, title: { display: !!yTitle, text: yTitle, color: text },
             ticks: { color: text, callback: (v) => '$' + v / 1000 + 'k' }, grid: { color: grid }, border: { display: false } },
      },
    };
  }

  function line(label, color, points, opts = {}) {
    return Object.assign({
      label, data: points, borderColor: color, backgroundColor: color, borderWidth: 2,
      pointRadius: 4, pointHoverRadius: 6, pointBorderColor: css('--surface'), pointBorderWidth: 2,
      spanGaps: true, tension: 0,
    }, opts);
  }

  function band(color, lower, upper) {
    // Two invisible datasets; the second fills down to the first to draw a p25–p75 band.
    const fill = color + '22';
    return [
      { label: '_lo', data: lower, borderWidth: 0, pointRadius: 0, fill: false, spanGaps: true },
      { label: '_hi', data: upper, borderWidth: 0, pointRadius: 0, backgroundColor: fill, fill: '-1', spanGaps: true },
    ];
  }

  const pts = (pairs) => pairs.filter(([, y]) => y != null).map(([x, y]) => ({ x, y }));

  function scorecardPoints(m, who) {
    const s = (m.scorecard || {})[who] || {};
    const key = who === 'rutgers' ? (y) => s[`earn_${y}yr`] : (y) => s[`mdn_${y}yr`];
    return pts([1, 4, 5, 7].map((y) => [y, key(y)]));
  }

  function pseoPoints(m, who, p = 'p50') {
    const s = (m.pseo || {})[who] || {};
    return pts([[1, 'y1'], [5, 'y5'], [10, 'y10']].map(([x, k]) => [x, (s[k] || {})[p]]));
  }

  function earningsChart(id, m) {
    const el = document.getElementById(id);
    if (!el || !window.Chart) return;
    const ru = series(1), nat = series(2), nj = series(3);
    const ds = [
      ...band(ru, pseoPoints(m, 'rutgers', 'p25'), pseoPoints(m, 'rutgers', 'p75')),
      line('Rutgers–NB (Scorecard)', ru, scorecardPoints(m, 'rutgers')),
      line('National median (Scorecard)', nat, scorecardPoints(m, 'national')),
      line('Rutgers–NB (PSEO)', ru, pseoPoints(m, 'rutgers'), { borderDash: [6, 4], pointStyle: 'rectRounded' }),
      line('NJ statewide (PSEO)', nj, pseoPoints(m, 'nj'), { borderDash: [6, 4], pointStyle: 'rectRounded' }),
    ].filter((d) => d.data.length);
    const opts = baseOptions('Median annual earnings');
    opts.scales.x.min = 0; opts.scales.x.max = 10;
    opts.scales.x.title = { display: true, text: 'Years after graduation', color: css('--text-secondary') };
    new Chart(el, { type: 'line', data: { datasets: ds }, options: opts });
  }

  function cohortChart(id, m) {
    const el = document.getElementById(id);
    if (!el || !window.Chart) return;
    const c = (m.pseo || {}).cohorts || [];
    const ds = [
      line('1 year after', series(1), pts(c.map((r) => [r.cohort, r.y1_p50]))),
      line('5 years after', series(2), pts(c.map((r) => [r.cohort, r.y5_p50]))),
      line('10 years after', series(3), pts(c.map((r) => [r.cohort, r.y10_p50]))),
    ].filter((d) => d.data.length);
    const opts = baseOptions('');
    opts.scales.x.ticks.stepSize = 3;
    opts.scales.x.ticks.callback = (v) => String(v);
    opts.scales.x.title = { display: true, text: 'First year of graduating-class group', color: css('--text-secondary') };
    new Chart(el, { type: 'line', data: { datasets: ds }, options: opts });
  }

  function industryChart(id, m) {
    const el = document.getElementById(id);
    if (!el || !window.Chart) return;
    const rows = (((m.pseo || {}).flows || {}).industries || []).slice(0, 8);
    const short = (s) => s.replace(/ and Waste Management and Remediation Services/, '').replace(/, and Technical Services/, ' & Tech. Services');
    const text = css('--text-secondary');
    new Chart(el, {
      type: 'bar',
      data: {
        labels: rows.map((r) => short(r.label)),
        datasets: [
          { label: '1 year after', data: rows.map((r) => r.y1), backgroundColor: series(1), borderRadius: 4, borderColor: css('--surface'), borderWidth: 1 },
          { label: '5 years after', data: rows.map((r) => r.y5), backgroundColor: series(2), borderRadius: 4, borderColor: css('--surface'), borderWidth: 1 },
        ],
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', align: 'start', labels: { color: text, usePointStyle: true, boxWidth: 8 } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.x == null ? '—' : c.parsed.x.toFixed(1) + '%'}` } },
        },
        scales: {
          x: { ticks: { color: text, callback: (v) => v + '%' }, grid: { color: css('--grid') }, border: { display: false } },
          y: { ticks: { color: text, autoSkip: false }, grid: { display: false } },
        },
      },
    });
  }

  function compareChart(id, majors) {
    const el = document.getElementById(id);
    if (!el || !window.Chart || !majors.length) return;
    const ds = [];
    majors.forEach((m, i) => {
      const color = series(i + 1);
      const name = m.title.length > 38 ? m.title.slice(0, 36) + '…' : m.title;
      ds.push(line(`${name} (Scorecard)`, color, scorecardPoints(m, 'rutgers')));
      ds.push(line(`${name} (PSEO)`, color, pseoPoints(m, 'rutgers'), { borderDash: [6, 4], pointStyle: 'rectRounded' }));
    });
    const opts = baseOptions('Median annual earnings');
    opts.scales.x.min = 0; opts.scales.x.max = 10;
    opts.scales.x.title = { display: true, text: 'Years after graduation', color: css('--text-secondary') };
    new Chart(el, { type: 'line', data: { datasets: ds.filter((d) => d.data.length) }, options: opts });
  }

  function initSearch({ max, compareUrl }) {
    const q = document.getElementById('q');
    const onlyEarn = document.getElementById('only-earn');
    const table = document.getElementById('majors');
    const btn = document.getElementById('compare-btn');
    const rows = Array.from(table.tBodies[0].rows);
    const picked = [];

    function apply() {
      const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      rows.forEach((r) => {
        const okText = terms.every((t) => r.dataset.search.includes(t));
        const okEarn = !onlyEarn.checked || r.dataset.hasEarn === '1';
        r.hidden = !(okText && okEarn);
      });
    }

    function updateBtn() {
      btn.textContent = `Compare selected (${picked.length})`;
      btn.href = picked.length ? `${compareUrl}?c=${picked.join(',')}` : compareUrl;
      btn.setAttribute('aria-disabled', picked.length < 2 ? 'true' : 'false');
    }

    table.addEventListener('change', (e) => {
      if (!e.target.classList.contains('pick')) return;
      const cip = e.target.closest('tr').dataset.cip;
      if (e.target.checked) {
        if (picked.length >= max) { e.target.checked = false; return; }
        picked.push(cip);
      } else {
        picked.splice(picked.indexOf(cip), 1);
      }
      updateBtn();
    });

    let sortKey = null, dir = 1;
    table.tHead.addEventListener('click', (e) => {
      const th = e.target.closest('th[data-sort]');
      if (!th) return;
      const key = th.dataset.sort;
      dir = sortKey === key ? -dir : (key === 'title' ? 1 : -1);
      sortKey = key;
      const val = (r) => {
        const v = r.dataset[key];  // data-rutgers_1yr -> dataset.rutgers_1yr (underscores are kept)
        if (key === 'title') return v;
        return v === '' || v == null ? null : Number(v);
      };
      rows.sort((a, b) => {
        const va = val(a), vb = val(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
      });
      rows.forEach((r) => table.tBodies[0].appendChild(r));
      table.tHead.querySelectorAll('th').forEach((h) => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
    });

    q.addEventListener('input', apply);
    onlyEarn.addEventListener('change', apply);
    apply();
    updateBtn();
  }

  function initCompareForm(formId, hiddenId) {
    const form = document.getElementById(formId);
    if (!form) return;
    form.addEventListener('submit', () => {
      const picks = Array.from(form.querySelectorAll('select[name=pick]')).map((s) => s.value).filter(Boolean);
      document.getElementById(hiddenId).value = [...new Set(picks)].join(',');
      form.querySelectorAll('select[name=pick]').forEach((s) => (s.disabled = true));
    });
  }

  window.MTO = { earningsChart, cohortChart, industryChart, compareChart, initSearch, initCompareForm };
})();
