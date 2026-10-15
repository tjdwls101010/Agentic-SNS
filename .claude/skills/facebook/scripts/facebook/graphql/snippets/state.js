async (args) => {
  // facebook-snippet: state
  // What the dedicated tab is showing, who is logged in, and the tab's facebook.com requests since the last look
  // (all of them since the page loaded when args.fresh: the tab was just opened). Makes no request.
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
  let user = null;
  let runtime = false;
  try {
    runtime = typeof window.require === 'function';
    const value = window.require('CurrentUserInitialData').USER_ID;
    user = value === undefined || value === null ? null : String(value);
  } catch (_) { /* not a logged-in Facebook page */ }
  return {location: location.href, user_id: user, runtime, ...(await settle(0))};
}
