(args) => {
  // The tab's own state shared by every page function, installed once per page load and kept across calls:
  // a ledger of the Threads-side requests the tab finished (with HTTP statuses), and the app's own responses that may
  // carry a block, kept for the skill to classify. Suspect responses are also written to this tab's sessionStorage, so
  // a reload of the same tab does not lose them. Static CDN files are not Threads requests and are not counted.
  const HOST = /^https:\/\/([a-z0-9-]+\.)*(threads\.com|threads\.net|instagram\.com|facebook\.com)\//;
  const SUSPECT = /checkpoint|challenge|consent_required|rate.?limit|too many request|try again later|login_required|session expired|csrf|"(?:error_code|error_subcode|code)"\s*:\s*"?(?:368|459|4|17|613|80004)\b/i;
  const STORE = 'threadsSkillSignals';
  let kit = window.__threadsSkill;
  if (!kit) {
    kit = {entries: [], read: 0, signals: [], installedAt: Date.now()};
    const keep = list => {
      for (const e of list) {
        if (!HOST.test(e.name)) continue;
        kit.entries.push({path: new URL(e.name).pathname.slice(0, 80), status: e.responseStatus || 0});
      }
    };
    kit.observer = new PerformanceObserver(list => keep(list.getEntries()));
    kit.observer.observe({type: 'resource', buffered: true});
    kit.keep = keep;
    const remember = (url, status, text) => {
      const body = String(text || '');
      if (status !== 429 && !SUSPECT.test(body.slice(0, 20000))) return;
      const signal = {url: String(url).slice(0, 200), status, body: body.slice(0, 4000), at: Date.now()};
      kit.signals.push(signal);
      try {
        const saved = JSON.parse(sessionStorage.getItem(STORE) || '[]');
        saved.push(signal);
        sessionStorage.setItem(STORE, JSON.stringify(saved.slice(-20)));
      } catch (_) { /* storage unavailable: the in-page list still holds it */ }
    };
    const watched = url => /\/(api\/graphql|graphql\/query)|^\/?$/.test((() => { try { return new URL(url, location.href).pathname; } catch (_) { return ''; } })());
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
  // Requests finished since the last look: their count and statuses, then marked read.
  kit.settle = async (wait = 50) => {
    await new Promise(resolve => setTimeout(resolve, wait));
    kit.keep(kit.observer.takeRecords());
    const fresh = kit.entries.slice(kit.read);
    kit.read = kit.entries.length;
    return {resources: fresh.length, statuses: fresh.map(e => e.status)};
  };
  kit.report = async (wait) => ({...(await kit.settle(wait)), signals: kit.pending(), location: location.href});
  return kit;
}
