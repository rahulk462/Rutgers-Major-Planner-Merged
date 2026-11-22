// GitHub Pages copy of the site: where the What-If and planner pages send their API calls.
//
//   "This browser"  the Python code runs here, in Pyodide (static/pyworker.js). No install.
//                   Your record stays in this browser. Logging in to Degree Navigator and
//                   scraping aren't possible from a web page, so those buttons say so.
//   "My computer"   calls go to the planner running on your computer at http://127.0.0.1:PORT
//                   (start it with `python run.py --pages`). Everything works, including login
//                   and scraping, and your record stays in personal/ on your computer.
//
// The pages themselves are unchanged: they call fetch(API + '/api/...') as on the local site,
// and this file answers those calls.
(function () {
  'use strict';

  const SCRIPT = document.currentScript.src;
  const SITE = new URL('../', SCRIPT);                       // .../static/backend.js -> site root
  const VERSION = new URL(SCRIPT).search;                    // cache-buster from the build
  const API = new RegExp('^' + SITE.pathname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(whatif|plan)(/api/.*)$');
  const store = {
    get(k, d) { try { return localStorage.getItem('rmp:' + k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem('rmp:' + k, v); } catch { /* private mode */ } },
  };
  const q = new URLSearchParams(location.search);
  if (q.get('backend') === 'local' || q.get('backend') === 'browser') store.set('backend', q.get('backend'));
  if (/^\d{2,5}$/.test(q.get('port') || '')) store.set('port', q.get('port'));

  const mode = () => store.get('backend', 'browser');
  const port = () => store.get('port', '5000');
  const localBase = () => `http://127.0.0.1:${port()}/`;
  window.RMPBackend = { mode, localBase };                   // read by home.js
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

  // ---- Python in the browser -------------------------------------------------------------
  let worker = null, nextId = 1;
  const pending = new Map();
  function getWorker() {
    if (worker) return worker;
    worker = new Worker(new URL('static/pyworker.js', SITE).href + VERSION);
    worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === 'progress') return setNote(m.text ? m.text + ' (the first visit downloads about 15 MB)' : BROWSER_NOTE);
      const p = pending.get(m.id);
      if (p) { pending.delete(m.id); p(json(m.status, JSON.parse(m.body))); }
    };
    worker.onerror = (e) => setNote('Python in the browser failed to start: ' + (e.message || 'unknown error'), true);
    return worker;
  }
  function inBrowser(tool, path, query, method, body) {
    return new Promise((resolve) => {
      const id = nextId++;
      pending.set(id, resolve);
      getWorker().postMessage({ id, tool, path, query, method, body: typeof body === 'string' ? body : null });
    });
  }

  // ---- The planner on your computer --------------------------------------------------------
  const startHint = () => `Start it in the repo folder with:  python run.py --pages${port() === '5000' ? '' : ' --port ' + port()}`;
  async function onComputer(tool, path, search, init) {
    try {
      return await origFetch(localBase() + tool + path + search, { ...init, mode: 'cors', credentials: 'omit' });
    } catch {
      return json(503, { error: `Can't reach the planner on your computer at ${localBase()}. ${startHint()} (If it's already running, restart it with --pages.)` });
    }
  }

  const origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
    const m = url.origin === location.origin && url.pathname.match(API);
    if (!m) return origFetch(input, init);
    init = init || {};
    const method = (init.method || 'GET').toUpperCase();
    return mode() === 'local'
      ? onComputer(m[1], m[2], url.search, init)
      : inBrowser(m[1], m[2], url.search.slice(1), method, init.body);
  };

  // ---- The switch at the top of the page -----------------------------------------------------
  let noteEl = null;
  const BROWSER_NOTE = 'Your record stays in this browser. Logging in to Degree Navigator and scraping need “My computer”.';
  function setNote(text, bad) {
    if (!noteEl) return;
    noteEl.textContent = text;
    noteEl.classList.toggle('bad', !!bad);
  }

  async function checkComputer() {
    setNote('Looking for the planner on your computer…');
    try {
      const r = await origFetch(localBase() + 'whatif/api/status', { mode: 'cors', credentials: 'omit' });
      if (!r.ok) throw new Error(r.statusText);
      setNote(`Connected to ${localBase()}. Your record and the Degree Navigator login stay on your computer.`);
    } catch {
      setNote(`Can't reach the planner at ${localBase()}. ${startHint()}  (If it's already running, restart it with --pages.) Then reload this page.`, true);
    }
  }

  function drawBar() {
    const bar = document.createElement('div');
    bar.className = 'rmp-backend';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Where this page runs');
    bar.innerHTML = `
      <span class="rmp-backend-label">Runs on</span>
      <label><input type="radio" name="rmp-backend" value="browser"> This browser <span class="muted">(no install)</span></label>
      <label><input type="radio" name="rmp-backend" value="local"> My computer</label>
      <label class="rmp-port" title="Port of python run.py">port <input type="text" inputmode="numeric" size="5" maxlength="5"></label>
      <span class="rmp-backend-note" aria-live="polite"></span>`;
    noteEl = bar.querySelector('.rmp-backend-note');
    const portIn = bar.querySelector('.rmp-port input');
    portIn.value = port();
    bar.querySelector(`input[value="${mode()}"]`).checked = true;
    bar.querySelector('.rmp-port').hidden = mode() !== 'local';
    bar.addEventListener('change', (e) => {
      if (e.target.name === 'rmp-backend') store.set('backend', e.target.value);
      else if (e.target === portIn && /^\d{2,5}$/.test(portIn.value)) store.set('port', portIn.value);
      else return;
      location.reload();                                    // the page re-reads everything from the new place
    });
    const nav = document.querySelector('.rmp-bar');
    if (nav) nav.after(bar); else document.body.prepend(bar);
    if (mode() === 'local') checkComputer();
    else if (!noteEl.textContent) setNote(BROWSER_NOTE);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', drawBar);
  else drawBar();
})();
