// Web worker for the GitHub Pages copy of the site: runs the What-If and planner Python code in
// Pyodide (self-hosted under <site>/pyodide/), so those pages work without a server.
// Your record is kept in this browser's IndexedDB (mounted at personal/) and never uploaded.
/* global loadPyodide */
'use strict';

const SITE = new URL('../', self.location.href);            // .../static/pyworker.js -> site root
const PYODIDE = new URL('pyodide/', SITE).href;
const APP_ZIP = new URL('static/py-app.zip', SITE).href + self.location.search;
const HOME = '/home/pyodide/personal';

const say = (text) => self.postMessage({ type: 'progress', text });

function syncfs(py, populate) {
  return new Promise((resolve) => py.FS.syncfs(populate, (err) => {
    if (err) console.warn('Saving your record in this browser failed:', err);
    resolve();
  }));
}

const ready = (async () => {
  say('Loading Python…');
  importScripts(PYODIDE + 'pyodide.js');
  const py = await loadPyodide({ indexURL: PYODIDE, env: { HOME: '/home/pyodide', RWI_HOME: HOME } });
  say('Loading the planner…');
  const [, zip] = await Promise.all([
    py.loadPackage(['pyyaml', 'beautifulsoup4', 'sqlite3'], { messageCallback: () => {} }),
    fetch(APP_ZIP).then((r) => { if (!r.ok) throw new Error('py-app.zip: ' + r.status); return r.arrayBuffer(); }),
  ]);
  py.unpackArchive(zip, 'zip', { extractDir: '/app' });
  py.FS.mkdirTree(HOME);
  try {
    py.FS.mount(py.FS.filesystems.IDBFS, {}, HOME);
    await syncfs(py, true);
  } catch (e) {
    console.warn('No browser storage; your record lasts until you close the tab.', e);
  }
  py.runPython("import sys; sys.path.insert(0, '/app'); import browser_api");
  say('');
  return { py, handle: py.globals.get('browser_api').handle };
})();

let queue = Promise.resolve();

self.onmessage = (ev) => {
  const { id, tool, method, path, query, body } = ev.data;
  queue = queue.then(async () => {
    try {
      const { py, handle } = await ready;
      const out = JSON.parse(handle(method, tool, path, query || '', body ?? null));
      if (method !== 'GET') await syncfs(py, false);
      self.postMessage({ type: 'reply', id, status: out.status, body: JSON.stringify(out.body) });
    } catch (e) {
      self.postMessage({ type: 'reply', id, status: 500, body: JSON.stringify({ error: 'Python in the browser failed: ' + (e && e.message || e) }) });
    }
  });
};
