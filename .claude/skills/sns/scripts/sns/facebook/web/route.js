// sns-snippet: facebook.route
// Move this tab to another Facebook screen in-page (as a link click does), wait until the page is quiet, and report
// the ids of the queries it loaded. Every facebook.com request the page makes meanwhile is counted.
if (typeof args.path !== 'string' || !args.path.startsWith('/') || args.path.startsWith('//')) {
  return {refused: 'not a path on this site', explicit: 0, resources: 0};
}
// A rate limit the tab already saw (between calls, or on a reload) stops this call before it moves.
if (kit.unread().includes(429) || kit.limited()) return {stopped: 'rate_limit', explicit: 0, ...(await kit.settle(0))};
history.pushState({}, '', args.path);
window.dispatchEvent(new PopStateEvent('popstate', {state: {}}));
const deadline = Date.now() + 15000;
const entries = kit.ledger.entries;
const before = entries.length;
let last = before, quietSince = Date.now();
while (Date.now() < deadline) {
  await new Promise(resolve => setTimeout(resolve, 250));
  kit.ledger.keep(kit.ledger.observer.takeRecords());
  if (entries.length !== last) { last = entries.length; quietSince = Date.now(); }
  if (entries.length > before && Date.now() - quietSince > 2500) break;
}
const live = {};
for (const name of args.names || []) {
  try {
    const query = kit.load(name + '.graphql');
    if (query && query.params && /^\d+$/.test(String(query.params.id))) {
      const flags = {};
      for (const [key, provider] of Object.entries(query.params.providedVariables || {})) flags[key] = provider.get();
      live[name] = {doc_id: String(query.params.id), flags};
    }
  } catch (_) { /* not loaded on this screen */ }
}
return {location: location.href, user_id: kit.user(), live, explicit: 0, ...(await kit.settle())};
