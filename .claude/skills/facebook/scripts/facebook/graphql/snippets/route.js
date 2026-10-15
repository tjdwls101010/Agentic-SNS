async (args) => {
  // facebook-snippet: route
  // Move this tab to another Facebook screen in-page (as a link click does), wait until the page is quiet, and
  // report the ids of the queries it loaded. Every facebook.com request the page makes meanwhile is counted.
  if (typeof args.path !== 'string' || !args.path.startsWith('/') || args.path.startsWith('//')) {
    return {refused: 'not a path on this site', explicit: 0, resources: 0};
  }
  // The tab's ledger of its own facebook.com requests and their HTTP statuses, kept across calls (installed once per
  // page load), so a request that finishes after one call is counted, and its status checked, by the next.
  const host = /^https:\/\/([a-z0-9-]+\.)*facebook\.com\//;
  const ledger = window.__facebookSkillLedger || (() => {
    const made = {entries: [], read: 0};
    const keep = list => { for (const entry of list) if (host.test(entry.name)) made.entries.push(entry.responseStatus || 0); };
    made.observer = new PerformanceObserver(list => keep(list.getEntries()));
    made.observer.observe({type: 'resource', buffered: true});
    keep(made.observer.takeRecords());
    made.keep = keep;
    if (!args.fresh) made.read = made.entries.length;  // what the tab did before the skill watched it is not counted
    window.__facebookSkillLedger = made;
    return made;
  })();
  const settle = async (wait = 50) => {
    await new Promise(resolve => setTimeout(resolve, wait));
    ledger.keep(ledger.observer.takeRecords());
    const statuses = ledger.entries.slice(ledger.read);
    ledger.read = ledger.entries.length;
    return {resources: statuses.length, statuses};
  };
  history.pushState({}, '', args.path);
  window.dispatchEvent(new PopStateEvent('popstate', {state: {}}));
  const deadline = Date.now() + 15000;
  const before = ledger.entries.length;
  let last = before, quietSince = Date.now();
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 250));
    ledger.keep(ledger.observer.takeRecords());
    if (ledger.entries.length !== last) { last = ledger.entries.length; quietSince = Date.now(); }
    if (ledger.entries.length > before && Date.now() - quietSince > 2500) break;
  }
  const live = {};
  for (const name of args.names || []) {
    try {
      const query = window.require(name + '.graphql');
      if (query && query.params && /^\d+$/.test(String(query.params.id))) {
        const flags = {};
        for (const [key, provider] of Object.entries(query.params.providedVariables || {})) flags[key] = provider.get();
        live[name] = {doc_id: String(query.params.id), flags};
      }
    } catch (_) { /* not loaded on this screen */ }
  }
  let user = null;
  try { user = String(window.require('CurrentUserInitialData').USER_ID); } catch (_) { /* logged out */ }
  return {location: location.href, user_id: user, live, explicit: 0, ...(await settle())};
}
