async (args) => {
  // facebook-snippet: page
  // One GET of a facebook.com page from this tab (same origin, the browser's cookies), to find ids in its HTML.
  let url;
  try { url = new URL(args.url); } catch (_) { return {refused: 'not a URL', explicit: 0, resources: 0}; }
  if (url.origin !== location.origin) return {refused: 'not this origin', explicit: 0, resources: 0};
  // The tab's ledger of its own facebook.com requests and their HTTP statuses, kept across calls (installed once per
  // page load), so a request that finishes after one call is counted, and its status checked, by the next.
  const host = /^https:\/\/([a-z0-9-]+\.)*facebook\.com\//;
  const ledger = window.__facebookSkillLedger || (() => {
    const made = {entries: [], read: 0, unwatched: []};
    const keep = list => { for (const entry of list) if (host.test(entry.name)) made.entries.push(entry.responseStatus || 0); };
    made.observer = new PerformanceObserver(list => keep(list.getEntries()));
    made.observer.observe({type: 'resource', buffered: true});
    keep(made.observer.takeRecords());
    made.keep = keep;
    if (!args.fresh) {
      // What the tab did before the skill watched it (a reload, an earlier visit) is not counted; its statuses are
      // still reported once, so a rate limit there is not missed.
      made.unwatched = made.entries.slice();
      made.read = made.entries.length;
    }
    window.__facebookSkillLedger = made;
    return made;
  })();
  const unread = () => {
    ledger.keep(ledger.observer.takeRecords());
    return ledger.entries.slice(ledger.read).concat(ledger.unwatched || []);
  };
  const settle = async (wait = 50) => {
    await new Promise(resolve => setTimeout(resolve, wait));
    ledger.keep(ledger.observer.takeRecords());
    const statuses = ledger.entries.slice(ledger.read);
    const unwatched = ledger.unwatched || [];
    ledger.read = ledger.entries.length;
    ledger.unwatched = [];
    return {resources: statuses.length, statuses, unwatched};
  };
  // A rate limit the tab already saw (between calls, or on a reload) stops this call before it sends anything.
  if (unread().includes(429)) return {stopped: 'rate_limit', explicit: 0, ...(await settle(0))};
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
