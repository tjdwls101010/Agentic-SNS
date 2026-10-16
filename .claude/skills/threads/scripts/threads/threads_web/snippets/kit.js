(args) => {
  // The tab's own state shared by every page function, installed once per page load and kept across calls:
  // a ledger of the Threads-side requests the tab finished (with HTTP statuses), and the responses that may carry a
  // block or a logout, kept for the skill to classify: a JSON body's error fields (whole), a document's block or login
  // markers (the patterns come from the skill), a move to a checkpoint or login page, or a 429. They are also written
  // to this tab's sessionStorage, so a reload of the same tab does not lose them. Static CDN files are not counted.
  const HOST = /^https:\/\/([a-z0-9-]+\.)*(threads\.com|threads\.net|instagram\.com|facebook\.com)\//;
  const MOVED = /^\/(challenge|checkpoint|accounts\/login|login)(\/|$)/;
  const ERROR_FIELDS = ['errors', 'error', 'error_code', 'error_subcode', 'checkpoint_url', 'checkpoint_required', 'challenge_required'];
  const STORE = 'threadsSkillSignals';
  const pathOf = url => { try { return new URL(url, location.href).pathname; } catch (_) { return ''; } };
  let kit = window.__threadsSkill;
  if (!kit) {
    kit = {entries: [], read: 0, signals: [], markers: (args.__markers || []).map(source => new RegExp(source, 'i'))};
    const keep = list => {
      for (const e of list) {
        if (!HOST.test(e.name)) continue;
        kit.entries.push({path: new URL(e.name).pathname.slice(0, 80), status: e.responseStatus || 0});
      }
    };
    kit.observer = new PerformanceObserver(list => keep(list.getEntries()));
    kit.observer.observe({type: 'resource', buffered: true});
    kit.keep = keep;
    kit.found = text => kit.markers.map(r => (String(text).match(r) || [])[0]).filter(Boolean);
    const summarize = text => {
      // JSON: its error fields as they are (null when it has none); a non-JSON body: undefined
      let value;
      try { value = JSON.parse(String(text).replace(/^\s*for\s*\(;;\);/, '')); } catch (_) { return undefined; }
      if (!value || typeof value !== 'object') return null;
      const kept = {};
      for (const key of ERROR_FIELDS) if (key in value) kept[key] = value[key];
      if (!('data' in value) && typeof value.message === 'string') { kept.message = value.message; kept.status = value.status; }
      return Object.keys(kept).length ? JSON.stringify(kept) : null;
    };
    const remember = (url, status, text) => {
      const summary = summarize(text);
      const excerpt = summary === undefined ? kit.found(text).join('\n') : '';
      if (status !== 429 && !MOVED.test(pathOf(url)) && !summary && !excerpt) return;
      const signal = {url: String(url).slice(0, 200), status, summary: summary || null, excerpt: excerpt || null, at: Date.now()};
      kit.signals.push(signal);
      try {
        const saved = JSON.parse(sessionStorage.getItem(STORE) || '[]');
        saved.push(signal);
        sessionStorage.setItem(STORE, JSON.stringify(saved.slice(-20)));
      } catch (_) { /* storage unavailable: the in-page list still holds it */ }
    };
    const watched = url => /^\/(api\/graphql\/?|graphql\/query|search|@[^/]+.*|t\/.*|)$/.test(pathOf(url)) || MOVED.test(pathOf(url));
    const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) { this.__threadsUrl = String(url); return open.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function () {
      if (watched(this.__threadsUrl || '')) {
        this.addEventListener('loadend', () => { try { remember(this.responseURL || this.__threadsUrl, this.status, this.responseText); } catch (_) {} });
      }
      return send.apply(this, arguments);
    };
    const original = window.fetch;
    window.fetch = function (input) {
      const url = String(typeof input === 'string' ? input : (input && input.url) || '');
      const promise = original.apply(this, arguments);
      if (watched(url)) promise.then(r => r.clone().text().then(t => remember(r.url || url, r.status, t))).catch(() => {});
      return promise;
    };
    window.__threadsSkill = kit;
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
    return all.filter(s => { const key = s.at + ' ' + s.url; if (seen.has(key)) return false; seen.add(key); return true; });
  };
  kit.moved = () => MOVED.test(location.pathname);
  // Requests finished since the last look: their count and statuses, then marked read.
  kit.settle = async (wait = 50) => {
    await new Promise(resolve => setTimeout(resolve, wait));
    kit.keep(kit.observer.takeRecords());
    const fresh = kit.entries.slice(kit.read);
    kit.read = kit.entries.length;
    return {resources: fresh.length, statuses: fresh.map(e => e.status)};
  };
  kit.report = async (wait, before) => {
    const after = await kit.settle(wait);
    const earlier = before || {resources: 0, statuses: []};
    return {resources: earlier.resources + after.resources, statuses: earlier.statuses.concat(after.statuses),
            signals: kit.pending(), location: location.href};
  };
  // What a call may not do: send while the tab shows a block or login page, or holds an unclassified signal or a 429.
  kit.gate = async () => {
    const before = await kit.settle(0);
    if (kit.moved()) return {stopped: 'location', explicit: 0, ...(await kit.report(0, before))};
    if (before.statuses.includes(429) || kit.pending().length) return {stopped: 'signal', explicit: 0, ...(await kit.report(0, before))};
    return {before};
  };
  return kit;
}
