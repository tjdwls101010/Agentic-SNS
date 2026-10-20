// sns-snippet: facebook.page
// One GET of a facebook.com page from this tab (same origin, the browser's cookies), to find ids in its HTML.
let url;
try { url = new URL(args.url); } catch (_) { return {refused: 'not a URL', explicit: 0, resources: 0}; }
if (url.origin !== location.origin) return {refused: 'not this origin', explicit: 0, resources: 0};
// A rate limit the tab already saw (between calls, or on a reload) stops this call before it sends anything.
if (kit.unread().includes(429) || kit.limited()) return {stopped: 'rate_limit', explicit: 0, ...(await kit.settle(0))};
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 60000);
try {
  const response = await fetch(url.href, {method: 'GET', credentials: 'include', signal: controller.signal,
                                          headers: {accept: 'text/html,application/xhtml+xml'}});
  const text = await response.text();
  return {status: response.status, url: response.url, body: text, user_id: kit.user(), location: location.href, explicit: 1, ...(await kit.settle())};
} catch (error) {
  return {network_error: String(error).slice(0, 200), explicit: 1, ...(await kit.settle())};
} finally {
  clearTimeout(timer);
}
