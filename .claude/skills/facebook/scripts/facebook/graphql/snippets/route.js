async (args) => {
  // facebook-snippet: route
  // Move this tab to another Facebook screen in-page (as a link click does), wait until the page is quiet, and
  // report the ids of the queries it loaded. Every facebook.com request the page makes meanwhile is counted.
  const host = /^https:\/\/([a-z0-9-]+\.)*facebook\.com\//;
  const count = () => performance.getEntriesByType('resource').filter(entry => host.test(entry.name)).length;
  const before = count();
  if (typeof args.path !== 'string' || !args.path.startsWith('/') || args.path.startsWith('//')) {
    return {refused: 'not a path on this site', explicit: 0, resources: 0};
  }
  history.pushState({}, '', args.path);
  window.dispatchEvent(new PopStateEvent('popstate', {state: {}}));
  const deadline = Date.now() + 15000;
  let last = before, quietSince = Date.now();
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 250));
    const now = count();
    if (now !== last) { last = now; quietSince = Date.now(); }
    if (now > before && Date.now() - quietSince > 2500) break;
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
  return {location: location.href, user_id: user, live, explicit: 0, resources: count() - before};
}
