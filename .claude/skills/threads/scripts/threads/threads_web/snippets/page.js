// threads-snippet: page
// One GET of a Threads document from this tab (same origin, the browser's cookies), redirects not followed, so the
// skill learns the queries a screen preloads. Only the read surface's paths.
const path = String(args.path || '');
if (!/^\/(|search(\?[^#\\]*)?|following\/?|liked\/?|saved\/?|@[A-Za-z0-9_.]+(\/(threads|replies|reposts|media|post\/[A-Za-z0-9_-]+))?\/?|t\/[A-Za-z0-9_-]+\/?)$/.test(path)) {
  return {refused: 'not a read path', explicit: 0, resources: 0, statuses: [], signals: kit.pending(), location: location.href};
}
const before = await kit.settle(0);
if (before.statuses.includes(429) || kit.pending().length) {
  return {stopped: 'signal', explicit: 0, ...before, signals: kit.pending(), location: location.href};
}
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 45000);
try {
  const response = await fetch(path, {method: 'GET', credentials: 'include', redirect: 'manual', signal: controller.signal,
                                      headers: {accept: 'text/html,application/xhtml+xml'}});
  const text = await response.text();
  return {status: response.status, url: response.url, location_header: response.headers.get('location'), body: text.slice(0, 4000000),
          explicit: 1, ...(await kit.report())};
} catch (error) {
  return {network_error: String(error).slice(0, 200), explicit: 1, ...(await kit.report())};
} finally {
  clearTimeout(timer);
}
