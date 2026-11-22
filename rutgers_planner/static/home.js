// Home page "Your classes": sign in with Rutgers (separate browser window, run by the What-If tool on
// your computer) or type classes in by hand. Everything is saved through the What-If API into the one
// record that the What-if and Graduation plan pages read (personal/data/ on your computer, or this
// browser's storage on the GitHub Pages copy).
(function () {
  'use strict';
  const root = document.getElementById('record');
  if (!root) return;
  const API = root.dataset.api;                                // e.g. /whatif (calls go to /whatif/api/...)
  const STATIC = root.dataset.static === 'true';
  const inBrowser = () => STATIC && !(window.RMPBackend && window.RMPBackend.mode() === 'local');
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v);
    }
    for (const k of kids) e.append(k);
    return e;
  };
  const setStatus = (id, text, cls = '') => { const e = $(id); e.textContent = text || ''; e.className = 'rec-status ' + cls; };

  async function api(path, body) {
    const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const r = await fetch(API + path, opt);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }

  // ---- semesters for the "When" menu ------------------------------------------------------------
  const SEASONS = ['Winter', 'Spring', 'Summer', 'Fall'];
  function currentTerm(d = new Date()) {
    const m = d.getMonth();
    return { year: d.getFullYear(), season: m === 0 ? 0 : m <= 4 ? 1 : m <= 7 ? 2 : 3 };
  }
  function drawTerms() {
    const sel = $('f-term'), now = currentTerm();
    const taken = el('optgroup', { label: 'Rutgers semester' });
    let y = now.year, s = now.season + 1;
    if (s > 3) { s = 0; y += 1; }
    for (let i = 0; i < 34; i++) {                            // next term back about 8 years
      const name = `${SEASONS[s]} ${y}`;
      const o = el('option', { value: name, text: name });
      if (y === now.year && s === now.season) o.selected = true;
      taken.append(o);
      if (--s < 0) { s = 3; y -= 1; }
    }
    const credit = el('optgroup', { label: 'Credit from before Rutgers' });
    for (const t of ['AP', 'Transfer', 'IB', 'CLEP', 'Dual enrollment']) credit.append(el('option', { value: 'credit:' + t, text: t }));
    sel.replaceChildren(taken, credit);
    sel.addEventListener('change', syncGrade);
    syncGrade();
  }
  function syncGrade() {
    const credit = $('f-term').value.startsWith('credit:');
    const g = $('f-grade');
    g.disabled = credit;
    g.title = credit ? 'AP, transfer and test credit counts as earned (grade T)' : '';
  }

  // ---- course search + title preview ------------------------------------------------------------
  const CODE = /\d{2}:\d{3}:\d{3}|\b\d{3}:\d{3}\b/;
  let searchTimer, lookTimer;
  $('f-code').addEventListener('input', () => {
    clearTimeout(searchTimer); clearTimeout(lookTimer);
    const v = $('f-code').value.trim();
    if (CODE.test(v)) { lookTimer = setTimeout(() => preview(v), 300); return; }
    setStatus('f-title', '');
    if (v.length < 3) return;
    searchTimer = setTimeout(async () => {
      try {
        const r = await api('/api/search?q=' + encodeURIComponent(v));
        $('f-code-list').replaceChildren(...r.results.map((h) => el('option', { value: h.code, label: `${h.code} ${h.title}` })));
      } catch { /* search is optional */ }
    }, 250);
  });
  async function preview(code) {
    try {
      const d = await api('/api/course?code=' + encodeURIComponent(code));
      setStatus('f-title', d.known ? `${d.code} ${d.title || ''}${d.credits ? ` · ${d.credits} credits` : ''}` : `${d.code}: not in the course data, but you can still add it.`, d.known ? '' : 'warn');
    } catch (e) { setStatus('f-title', e.message, 'bad'); }
  }
  async function resolveCode(v) {
    if (CODE.test(v)) return v;
    const r = await api('/api/search?q=' + encodeURIComponent(v));
    if (!r.results.length) throw new Error(`No course matches “${v}”. Type its code, like 01:198:111.`);
    return r.results[0].code;
  }

  $('add-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const term = $('f-term').value, credit = term.startsWith('credit:');
    try {
      const code = await resolveCode($('f-code').value.trim());
      const body = { code, credits: $('f-credits').value };
      if (credit) Object.assign(body, { term: term.slice(7), transfer: true });
      else Object.assign(body, { term, grade: $('f-grade').value, transfer: false });
      const r = await api('/api/courses/add', body);
      const c = r.added;
      setStatus('st-manual', `Added ${c.code}${c.title ? ' ' + c.title : ''} (${c.term}${c.transfer ? '' : c.grade ? ', ' + c.grade : ', in progress'}).`, 'good');
      $('f-code').value = ''; $('f-credits').value = ''; setStatus('f-title', '');
      $('f-code').focus();
      refreshAll();
    } catch (e) { setStatus('st-manual', e.message, 'bad'); }
  });

  // ---- AP exams ----------------------------------------------------------------------------------
  let AP = null;
  async function loadAP() {
    try { AP = await api('/api/ap-exams'); } catch { $('ap-exam').closest('.ap-row').hidden = true; return; }
    $('ap-exam').replaceChildren(...AP.exams.map((e) => el('option', { value: e.exam, text: 'AP ' + e.exam })));
    $('ap-exam').addEventListener('change', previewAP); $('ap-score').addEventListener('change', previewAP);
    previewAP();
  }
  function previewAP() {
    const e = AP && AP.exams.find((x) => x.exam === $('ap-exam').value);
    if (!e) return;
    const got = e.awards[$('ap-score').value];
    setStatus('ap-preview', got ? `Counts as ${got.join(', ')} (${e.credits[$('ap-score').value]} credits).${e.note ? ' ' + e.note : ''}`
      : 'SAS gives no credit for a score of 3 or lower.', got ? '' : 'warn');
    $('btn-ap').disabled = !got;
  }
  $('btn-ap').addEventListener('click', async () => {
    try {
      const r = await api('/api/courses/add-ap', { exam: $('ap-exam').value, score: Number($('ap-score').value) });
      setStatus('st-manual', `Added ${r.added.map((c) => c.code).join(', ')} for AP ${$('ap-exam').value}.`, 'good');
      refreshAll();
    } catch (e) { setStatus('st-manual', e.message, 'bad'); }
  });

  // ---- CSV list ----------------------------------------------------------------------------------
  $('csv-file').addEventListener('change', async (e) => { const f = e.target.files[0]; if (f) $('csv-text').value = await f.text(); });
  $('btn-csv').addEventListener('click', () => run('import', { csv: $('csv-text').value }));

  // ---- your classes table -----------------------------------------------------------------------
  async function loadMine() {
    let r;
    try { r = await api('/api/courses'); } catch (e) {
      $('mine-body').replaceChildren(el('tr', {}, el('td', { colspan: '6', class: 'muted', text: e.message })));
      return;
    }
    const body = $('mine-body');
    if (!r.courses.length) {
      $('mine-sum').textContent = 'Your classes (none yet)';
      body.replaceChildren(el('tr', {}, el('td', { colspan: '6', class: 'muted', text: 'Nothing here yet. Sign in (A) or add classes (B).' })));
      return;
    }
    const mine = r.courses.filter((c) => c.source === 'manual').length;
    $('mine-sum').textContent = `Your classes (${r.courses.length}${mine ? `, ${mine} added by you` : ''})`;
    const order = (c) => (c.transfer ? '0' : '1') + termKey(c.term);
    const rows = [...r.courses].sort((a, b) => order(a).localeCompare(order(b)) || a.code.localeCompare(b.code));
    body.replaceChildren(...rows.map((c) => {
      const from = c.source === 'manual' ? 'added by you' : c.source === 'import' ? 'imported list' : 'Degree Navigator';
      const grade = c.transfer ? 'credit' : c.status === 'in_progress' ? 'in progress' : (c.grade || '–');
      const tr = el('tr', {},
        el('td', {}, el('span', { class: 'code-chip', text: c.code }), c.title || ''),
        el('td', { text: c.term || '–' }), el('td', { text: grade }),
        el('td', { class: 'num', text: c.credits == null ? '–' : String(c.credits) }),
        el('td', { class: 'muted', text: from }), el('td'));
      if (c.source === 'manual') {
        const b = el('button', { class: 'link-btn', type: 'button', text: 'Remove', 'aria-label': `Remove ${c.code}` });
        b.addEventListener('click', async () => {
          try { await api('/api/courses/remove', { code: c.code, term: c.term || '' }); refreshAll(); }
          catch (e) { setStatus('st-manual', e.message, 'bad'); }
        });
        tr.lastChild.append(b);
      }
      return tr;
    }));
  }
  function termKey(t) {
    const m = /(Winter|Spring|Summer|Fall)\s+(\d{4})/.exec(t || '');
    return m ? m[2] + SEASONS.indexOf(m[1]) : '0';
  }

  // ---- Rutgers login, discovery and scrape (jobs run by the What-If tool) -----------------------
  const JOB_LABEL = { login: 'Rutgers login', 'check-session': 'Checking your session', discover: 'Finding your audit pages',
    scrape: 'Loading your classes', reparse: 'Re-reading saved pages', import: 'Importing your list', soc: 'Downloading course data' };
  const WINDOW_TEXT = {
    login: ['That window is on the Rutgers sign-in page. Finish NetID + Duo there.', 'warn'],
    signed_in: ['Signed in. Click “I\'m done” to save your session.', 'good'],
    other: ['That window is on a non-Rutgers page. Go back to Degree Navigator there.', 'warn'],
    closed: ['The window was closed.', 'bad'],
  };
  let status = null, lastJob = null, watching = false, chainScrape = false, pollTimer = null;

  // GitHub Pages copy in "This browser" mode: a web page can't open the login window, so say how to get it.
  function lockLogin() {
    if (!inBrowser()) return false;
    $('login-unavailable').hidden = false;
    $('login-unavailable').textContent = 'Signing in with Rutgers needs this site running on your computer, because the login window opens there. '
      + 'Start it with “python run.py --pages”, then choose “My computer” at the top of this page. Until then, add your classes in B; they are saved in this browser.';
    for (const id of ['btn-login', 'btn-check', 'btn-pull', 'btn-rediscover']) $(id).disabled = true;
    setStatus('st-login', ''); $('pull-step').hidden = true;
    return true;
  }

  function drawStatus(s) {
    status = s;
    const audit = s.audit, manual = s.manual || { courses: 0 };
    const total = (audit ? audit.courses : 0) + manual.courses;
    const bits = [];
    if (audit) bits.push(`${audit.courses} from ${audit.source && audit.source.startsWith('import') ? 'an imported list' : 'Degree Navigator'} (${new Date(audit.fetched_at).toLocaleDateString()})`);
    if (manual.courses) bits.push(`${manual.courses} added by you`);
    $('rec-summary').textContent = total
      ? `${total} classes on record: ${bits.join(', ')}. What-if and the planner use them.`
      : 'No classes yet. Sign in with Rutgers or type them in below. You can use every page without signing in.';

    if (lockLogin()) return;
    setStatus('st-login', s.session_saved ? 'Session saved on this computer. Rutgers expires it after a while; log in again if loading fails.' : 'Not signed in.', s.session_saved ? 'good' : '');
    $('pull-step').hidden = false;
    $('btn-pull').textContent = s.discovered ? 'Refresh my classes' : 'Load my classes';
    $('btn-rediscover').hidden = !s.discovered;
    $('pull-hint').textContent = !s.session_saved ? 'Once you\'re signed in, load your classes from Degree Navigator.'
      : s.discovered ? 'Fetches your audit pages again, 1–2 s apart. Do this after grades post or you register.'
      : 'The first time, the window opens on Degree Navigator: click through your audit and course history there, then click “I\'m done”. Your classes are fetched right after.';
    if (audit && audit.source && !audit.source.startsWith('import')) setStatus('st-pull', `Last loaded ${new Date(audit.fetched_at).toLocaleString()}: ${audit.courses} classes, ${audit.requirements} requirement rows.`, 'good');
    drawJob(s.job);
  }

  function drawJob(job) {
    const busy = job.state === 'running' || job.state === 'waiting';
    for (const id of ['btn-login', 'btn-check', 'btn-pull', 'btn-rediscover', 'btn-csv']) $(id).disabled = busy || (id === 'btn-pull' && !status.session_saved);
    if (busy) watching = true;
    const box = $('job');
    box.hidden = !job.name || !watching;
    if (box.hidden) return;
    $('job-title').textContent = JOB_LABEL[job.name] || job.name;
    const label = { running: 'running…', waiting: 'waiting for you', done: 'finished', error: 'failed', idle: '' }[job.state] || '';
    $('job-state').textContent = '· ' + label;
    $('job-state').className = job.state === 'error' ? 'rec-status bad' : job.state === 'done' ? 'rec-status good' : 'rec-status warn';
    const usesWindow = job.name === 'login' || job.name === 'discover';
    $('winhelp').hidden = !(usesWindow && busy);
    $('waitbox').hidden = job.state !== 'waiting';
    $('prompt').textContent = job.prompt || '';
    const w = job.window || {}, wt = WINDOW_TEXT[w.state];
    let wtext = wt ? wt[0] : '';
    if (job.name === 'discover' && w.captured !== undefined) wtext += ` Recorded ${w.captured} responses so far.`;
    setStatus('winstate', wtext, wt ? wt[1] : '');
    $('log').textContent = (job.log || []).join('\n');
    if (job.state === 'error') { const d = box.querySelector('.job-log'); d.open = true; }

    const finished = lastJob && lastJob.busy && !busy && lastJob.name === job.name;
    lastJob = { name: job.name, busy };
    if (finished) {
      loadMine();
      if (job.name === 'discover' && job.state === 'done' && chainScrape) { chainScrape = false; run('scrape'); }
      else chainScrape = false;
      if (job.name === 'import' && job.state === 'done') $('csv-text').value = '';
    }
    clearTimeout(pollTimer);
    if (busy) pollTimer = setTimeout(refreshStatus, 1500);
  }

  async function refreshStatus() {
    try { drawStatus(await api('/api/status')); }
    catch (e) { setStatus('st-login', (STATIC ? '' : 'The site\'s server isn\'t answering: ') + e.message, 'bad'); }
  }
  function refreshAll() { refreshStatus(); loadMine(); }

  async function run(action, body = {}) {
    watching = true;
    try { await api('/api/run/' + action, body); }
    catch (e) {
      $('job').hidden = false; $('job-title').textContent = JOB_LABEL[action] || action;
      $('job-state').textContent = '· ' + e.message; $('job-state').className = 'rec-status bad';
    }
    lastJob = { name: action === 'check' ? 'check-session' : action, busy: true };
    refreshStatus();
  }

  $('btn-login').addEventListener('click', () => run('login'));
  $('btn-check').addEventListener('click', () => run('check'));
  $('btn-pull').addEventListener('click', () => {
    if (status && status.discovered) run('scrape');
    else { chainScrape = true; run('discover'); }
  });
  $('btn-rediscover').addEventListener('click', () => { chainScrape = true; run('discover'); });
  $('btn-done').addEventListener('click', async () => { try { await api('/api/done', {}); } catch { /* job may have ended */ } refreshStatus(); });

  lockLogin();
  drawTerms();
  loadAP();
  refreshAll();
})();
