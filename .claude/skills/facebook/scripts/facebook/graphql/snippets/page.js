async (args) => {
  // facebook-snippet: page
  // One GET of a facebook.com page from this tab (same origin, the browser's cookies), to find ids in its HTML.
  let url;
  try { url = new URL(args.url); } catch (_) { return {refused: 'not a URL', explicit: 0, resources: 0}; }
  if (url.origin !== location.origin) return {refused: 'not this origin', explicit: 0, resources: 0};
  // Every facebook.com request this tab makes during the call, with its HTTP status, as the browser records it.
  const host = /^https:\/\/([a-z0-9-]+\.)*facebook\.com\//;
  const statuses = [];
  const watcher = new PerformanceObserver(list => {
    for (const entry of list.getEntries()) if (host.test(entry.name)) statuses.push(entry.responseStatus || 0);
  });
  watcher.observe({type: 'resource', buffered: false});
  const settle = async () => {
    await new Promise(resolve => setTimeout(resolve, 50));
    for (const entry of watcher.takeRecords()) if (host.test(entry.name)) statuses.push(entry.responseStatus || 0);
    watcher.disconnect();
    return {resources: statuses.length, statuses};
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(url.href, {method: 'GET', credentials: 'include', signal: controller.signal,
                                            headers: {accept: 'text/html,application/xhtml+xml'}});
    const text = await response.text();
    return {status: response.status, url: response.url, body: text, explicit: 1, ...(await settle())};
  } catch (error) {
    return {network_error: String(error).slice(0, 200), explicit: 1, ...(await settle())};
  } finally {
    clearTimeout(timer);
  }
}
