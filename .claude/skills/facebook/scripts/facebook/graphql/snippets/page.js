async (args) => {
  // facebook-snippet: page
  // One GET of a facebook.com page from this tab (same origin, the browser's cookies), to find ids in its HTML.
  const host = /^https:\/\/([a-z0-9-]+\.)*facebook\.com\//;
  const count = () => performance.getEntriesByType('resource').filter(entry => host.test(entry.name)).length;
  const before = count();
  let url;
  try { url = new URL(args.url); } catch (_) { return {refused: 'not a URL', explicit: 0, resources: 0}; }
  if (url.origin !== location.origin) return {refused: 'not this origin', explicit: 0, resources: 0};
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(url.href, {method: 'GET', credentials: 'include', signal: controller.signal,
                                            headers: {accept: 'text/html,application/xhtml+xml'}});
    const text = await response.text();
    return {status: response.status, url: response.url, body: text, explicit: 1, resources: count() - before};
  } catch (error) {
    return {network_error: String(error).slice(0, 200), explicit: 1, resources: count() - before};
  } finally {
    clearTimeout(timer);
  }
}
