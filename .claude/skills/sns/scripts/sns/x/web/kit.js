// sns-snippet: x.kit
(args) => {
  // The tab's own state shared by every page function, installed once per page load (as early as the load allows)
  // and kept across calls:
  // - a ledger of the x.com / api.x.com requests the tab finished, from a page-global PerformanceObserver; an entry
  //   whose name carries a nonce this page issued (#xs-<nonce>) is the skill's own request and is counted apart;
  // - the app's own /i/api/ responses that matter for protection, kept as signals {path, status, codes, rate, html,
  //   at}: a 429 or remaining 0 (that operation's limit), X error codes, a challenge page; also in sessionStorage, so a
  //   reload of the same tab keeps them;
  // - cached access to the app: the webpack runtime, its operation index, the redux store, the signature generator
  //   and the bearer, each found once per page and found again when it goes missing.
  // The skill's own requests go through the fetch the page had before the hook, so the hook never sees them.
  const HOST = /^https:\/\/(x\.com|api\.x\.com|twitter\.com|api\.twitter\.com)\//;
  const LOCKED = /^\/account\/access(\/|$)/;
  const LOGIN = /^\/(i\/flow\/login|login)(\/|$)/;
  const STORE = 'xSkillSignals';
  const pathOf = url => { try { return new URL(url, location.href).pathname; } catch (_) { return ''; } };
  let kit = window.__xSkill;
  if (!kit) {
    // bufferIntact: the app's main bundle is still in the timing buffer, so X had not emptied it yet and the observer
    // (buffered) sees the whole load even when the app had already started
    let bufferIntact = false;
    try {
      bufferIntact = performance.getEntriesByType('resource').some(e => /\/responsive-web\/client-web\/main\./.test(e.name));
    } catch (_) { bufferIntact = false; }
    kit = {entries: [], read: 0, signals: [], issued: new Set(), installedAt: performance.now(),
           readyAtInstall: document.readyState, appAtInstall: !!self.webpackChunk_twitter_responsive_web, bufferIntact,
           fetch0: window.fetch.bind(window), cache: {}};
    const keep = list => {
      for (const e of list) {
        if (!HOST.test(e.name)) continue;
        const hash = e.name.indexOf('#xs-');
        const ours = hash >= 0 && kit.issued.has(e.name.slice(hash + 4));
        kit.entries.push({path: new URL(e.name).pathname.slice(0, 100), status: e.responseStatus || 0, ours});
      }
    };
    kit.keep = keep;
    kit.observer = new PerformanceObserver(list => keep(list.getEntries()));
    kit.observer.observe({type: 'resource', buffered: true});
    const codesOf = text => {
      try {
        const body = JSON.parse(text);
        return (Array.isArray(body && body.errors) ? body.errors : []).map(e => e && (e.code || (e.extensions || {}).code))
          .filter(c => typeof c === 'number');
      } catch (_) { return null; }
    };
    const remember = (url, status, text, header) => {
      const rate = ['limit', 'remaining', 'reset'].map(k => header('x-rate-limit-' + k));
      const limited = rate.every(v => v !== null && /^\d+$/.test(String(v)));
      const codes = codesOf(text) || [];
      const html = status === 403 && /<!doctype|<html|cf-/i.test(String(text).slice(0, 2000));
      const interesting = status === 429 || status === 401 || html || codes.length ||
        (limited && Number(rate[1]) === 0);
      if (!interesting) return;
      const signal = {path: pathOf(url).slice(0, 200), status, codes, html,
                      rate: limited ? {limit: Number(rate[0]), remaining: Number(rate[1]), reset: Number(rate[2])} : null,
                      at: Date.now()};
      kit.signals.push(signal);
      try {
        const saved = JSON.parse(sessionStorage.getItem(STORE) || '[]');
        saved.push(signal);
        sessionStorage.setItem(STORE, JSON.stringify(saved.slice(-30)));
      } catch (_) { /* storage unavailable: the in-page list still holds it */ }
    };
    const watched = url => pathOf(url).startsWith('/i/api/') || /^https:\/\/api\.x\.com\//.test(String(url));
    const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) { this.__xsUrl = String(url); return open.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function () {
      if (watched(this.__xsUrl || '')) {
        this.addEventListener('loadend', () => {
          try {
            const type = this.responseType;
            const text = type === '' || type === 'text' ? this.responseText
              : type === 'json' && this.response !== null ? JSON.stringify(this.response) : '';
            remember(this.responseURL || this.__xsUrl, this.status, text, k => this.getResponseHeader(k));
          } catch (_) { /* never break the app */ }
        });
      }
      return send.apply(this, arguments);
    };
    const appFetch = window.fetch;
    window.fetch = function (input) {
      const url = String(typeof input === 'string' ? input : (input && input.url) || '');
      const promise = appFetch.apply(this, arguments);
      if (watched(url)) {
        promise.then(r => r.clone().text().then(t => remember(r.url || url, r.status, t, k => r.headers.get(k))))
          .catch(() => {});
      }
      return promise;
    };
    window.__xSkill = kit;
  }
  const ack = typeof args.__ack === 'number' ? args.__ack : 0;
  if (ack) {
    kit.signals = kit.signals.filter(s => s.at > ack);
    try { sessionStorage.setItem(STORE, JSON.stringify(JSON.parse(sessionStorage.getItem(STORE) || '[]').filter(s => s.at > ack))); } catch (_) {}
  }
  kit.pending = () => {
    let saved = [];
    try { saved = JSON.parse(sessionStorage.getItem(STORE) || '[]'); } catch (_) {}
    const all = kit.signals.concat(saved).filter(s => s && s.at > ack);
    const seen = new Set();
    return all.filter(s => { const key = s.at + ' ' + s.path + ' ' + s.status; if (seen.has(key)) return false; seen.add(key); return true; });
  };
  kit.moved = () => LOCKED.test(location.pathname) ? location.pathname : (LOGIN.test(location.pathname) ? location.pathname : null);
  // Requests finished since the last look: the background ones counted, the skill's own told apart; then marked read.
  kit.settle = async (wait = 50) => {
    await new Promise(resolve => setTimeout(resolve, wait));
    kit.keep(kit.observer.takeRecords());
    const fresh = kit.entries.slice(kit.read);
    kit.read = kit.entries.length;
    const background = fresh.filter(e => !e.ours);
    return {resources: background.length, ours: fresh.length - background.length, statuses: background.map(e => e.status)};
  };
  kit.report = async (wait, before) => {
    const after = await kit.settle(wait);
    const earlier = before || {resources: 0, ours: 0, statuses: []};
    return {resources: earlier.resources + after.resources, ours: earlier.ours + after.ours,
            statuses: earlier.statuses.concat(after.statuses), signals: kit.pending(), location: location.href,
            moved: kit.moved(), user_id: kit.session().user_id};
  };
  // What stops a call before it sends: the tab on a lock or login page, a signal that names a lock code (64, 326),
  // a challenge page or a login code, or the asked operation's own limit. Other operations' limits are reported, not
  // stopped on: each is recorded for its own bucket.
  kit.gate = async (name) => {
    const before = await kit.settle(0);
    if (kit.moved()) return {stopped: 'location', explicit: 0, ...(await kit.report(0, before))};
    const strong = kit.pending().filter(s => s.html || s.status === 401 || (s.codes || []).some(c => [32, 64, 326].includes(c)));
    if (strong.length) return {stopped: 'signal', explicit: 0, ...(await kit.report(0, before))};
    const bucket = path => { const m = /^\/i\/api\/graphql\/[^/]+\/([A-Za-z0-9_]+)$/.exec(path || ''); return m ? m[1] : path; };
    const own = kit.pending().filter(s => bucket(s.path) === name && (s.status === 429 || (s.rate && s.rate.remaining === 0)));
    if (own.length) return {stopped: 'limit', explicit: 0, ...(await kit.report(0, before))};
    return {before};
  };
  // --- the app's own parts, found once per page ------------------------------------------------------------------
  kit.runtime = () => {
    if (kit.cache.runtime) return kit.cache.runtime;
    const chunks = self.webpackChunk_twitter_responsive_web;
    if (!chunks || typeof chunks.push !== 'function') return null;
    let found = null;
    chunks.push([['xskill-' + Math.random()], {}, r => { found = r; }]);
    kit.cache.runtime = found && found.m ? found : null;
    return kit.cache.runtime;
  };
  const DEFINITION = /queryId:"([^"]+)",operationName:"([^"]+)",operationType:"([^"]+)",metadata:\{featureSwitches:\[([^\]]*)\],fieldToggles:\[([^\]]*)\]/g;
  const list = text => text ? text.split(',').map(s => s.replace(/"/g, '').trim()).filter(Boolean) : [];
  kit.index = (fresh) => {
    if (kit.cache.index && !fresh) return kit.cache.index;
    const runtime = kit.runtime();
    if (!runtime) return null;
    const ops = {};
    for (const id of Object.keys(runtime.m)) {
      let source = '';
      try { source = runtime.m[id].toString(); } catch (_) { continue; }
      if (source.indexOf('operationName:"') < 0) continue;
      for (const m of source.matchAll(DEFINITION)) {
        ops[m[2]] = {queryId: m[1], type: m[3], featureSwitches: list(m[4]), fieldToggles: list(m[5]), module: id};
      }
    }
    kit.cache.index = {ops, modules: Object.keys(runtime.m).length};
    return kit.cache.index;
  };
  kit.generator = (fresh) => {
    if (kit.cache.generator && !fresh) return kit.cache.generator;
    const runtime = kit.runtime();
    if (!runtime) return null;
    for (const id of Object.keys(runtime.m)) {
      let source = '';
      try { source = runtime.m[id].toString(); } catch (_) { continue; }
      if (source.indexOf('rweb_client_transaction_id_enabled') < 0 || source.indexOf('"x-client-transaction-id"') < 0) continue;
      let exported = null;
      try { exported = runtime(id); } catch (_) { continue; }
      const candidates = Object.keys(exported || {}).filter(k => typeof exported[k] === 'function' && exported[k].length === 3);
      if (candidates.length === 1) { kit.cache.generator = exported[candidates[0]]; return kit.cache.generator; }
    }
    return null;
  };
  kit.bearer = () => {
    if (kit.cache.bearer) return kit.cache.bearer;
    const runtime = kit.runtime();
    if (!runtime) return null;
    const values = new Set();
    for (const id of Object.keys(runtime.m)) {
      let source = '';
      try { source = runtime.m[id].toString(); } catch (_) { continue; }
      if (source.indexOf('AAAAAAAAAAAAAAAAAAAAA') < 0) continue;
      for (const m of source.matchAll(/"(AAAAAAAAAAAAAAAAAAAAA[A-Za-z0-9%]{40,})"/g)) values.add(m[1]);
    }
    kit.cache.bearer = values.size === 1 ? decodeURIComponent([...values][0]) : null;  // two values: no guessing
    return kit.cache.bearer;
  };
  kit.store = () => {
    if (kit.cache.store && kit.cache.store.getState) return kit.cache.store;
    const root = document.querySelector('#react-root');
    const key = root && Object.keys(root).find(k => k.startsWith('__reactContainer$'));
    if (!key) return null;
    const stack = [root[key]];
    let visited = 0;
    while (stack.length && visited < 20000) {
      const fiber = stack.pop();
      visited += 1;
      if (!fiber) continue;
      const props = fiber.memoizedProps;
      if (props && props.store && typeof props.store.getState === 'function') { kit.cache.store = props.store; return props.store; }
      if (fiber.sibling) stack.push(fiber.sibling);
      if (fiber.child) stack.push(fiber.child);
    }
    return null;
  };
  kit.session = () => {
    const store = kit.store();
    let state = null;
    try { state = store ? store.getState() : null; } catch (_) { state = null; }
    const session = (state && state.session) || {};
    const switches = (state && state.featureSwitch && state.featureSwitch.user && state.featureSwitch.user.config) || null;
    return {user_id: session.user_id ? String(session.user_id) : null, language: session.language || null, switches};
  };
  // Load the lazily loaded chunks whose file name has the part `hint` (bundle.<Name>) from the static CDN, then index
  // again; makes no x.com request.
  kit.loadChunks = async (hint) => {
    const runtime = kit.runtime();
    if (!runtime || typeof runtime.e !== 'function' || typeof runtime.u !== 'function') return 0;
    let ids = [];
    try {
      ids = [...runtime.u.toString().matchAll(/(\d+):"([^"]+)"/g)].filter(m => m[2].split('~').includes(hint)).map(m => Number(m[1]));
    } catch (_) { return 0; }
    for (const id of ids) { try { await runtime.e(id); } catch (_) { /* the next index says whether it arrived */ } }
    kit.index(true);
    return ids.length;
  };
  return kit;
}
