// sns-snippet: threads.page
// One GET of a Threads document from this tab (same origin, the browser's cookies), redirects not followed, so the
// skill learns the queries a screen preloads. Only the read surface's paths.
const path = String(args.path || '');
const refused = () => ({refused: 'not a read path', explicit: 0, resources: 0, statuses: [], signals: kit.pending(), location: location.href});
// The one list of readable paths is the skill's (targets.ROUTE_SOURCE): it arrives as args.route, and the path is judged
// the way targets.route_allowed judges it.
if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || path.includes('#') || !args.route) return refused();
let parsed;
try { parsed = new URL(path, location.origin); } catch (_) { return refused(); }
if (parsed.origin !== location.origin || !new RegExp('^(?:' + args.route + ')$').test(parsed.pathname)) return refused();
const gate = await kit.gate();
if (gate.stopped) return gate;
const before = gate.before;
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 45000);
try {
  const response = await fetch(path, {method: 'GET', credentials: 'include', redirect: 'manual', signal: controller.signal,
                                      headers: {accept: 'text/html,application/xhtml+xml'}});
  const text = await response.text();
  return {status: response.status, url: response.url, location_header: response.headers.get('location'), body: text.slice(0, 4000000),
          explicit: 1, ...(await kit.report(50, before))};
} catch (error) {
  return {network_error: String(error).slice(0, 200), explicit: 1, ...(await kit.report(50, before))};
} finally {
  clearTimeout(timer);
}
