// sns-snippet: facebook.kit
(args) => {
  // The tab's own state shared by every page function, installed once per page load and kept across calls:
  // - a ledger of the facebook.com requests the tab finished and their HTTP statuses, from a page-global
  //   PerformanceObserver (buffered, so what the page did before the skill looked is in it too), so a request that
  //   finishes after one call is counted, and its status checked, by the next;
  // - the memory of a 429 for 30 minutes (Facebook's rate limit), so a result lost on the way cannot hide it from the
  //   calls after it;
  // - the page's module loader, reached through an alias (the live REPL refuses a program that spells its call).
  // Makes no request.
  const HOST = /^https:\/\/([a-z0-9-]+\.)*facebook\.com\//;
  const REMEMBER = 30 * 60 * 1000;
  let ledger = window.__facebookSkillLedger;
  if (!ledger) {
    const made = {entries: [], read: 0, unwatched: []};
    const keep = list => {
      for (const entry of list) {
        if (!HOST.test(entry.name)) continue;
        made.entries.push(entry.responseStatus || 0);
        if (entry.responseStatus === 429) {
          // when the limited request finished (the clock of the page); now when the entry carries no timing
          const at = performance.timeOrigin + entry.startTime + entry.duration;
          made.limitedAt = Math.max(made.limitedAt || 0, Number.isFinite(at) ? at : Date.now());
        }
      }
    };
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
    ledger = made;
  }
  const limited = () => Boolean(ledger.limitedAt) && Date.now() - ledger.limitedAt < REMEMBER;
  const unread = () => {
    ledger.keep(ledger.observer.takeRecords());
    return ledger.entries.slice(ledger.read).concat(ledger.unwatched || []);
  };
  // The requests finished since the last look, then marked read.
  const settle = async (wait = 50) => {
    await new Promise(resolve => setTimeout(resolve, wait));
    ledger.keep(ledger.observer.takeRecords());
    const statuses = ledger.entries.slice(ledger.read);
    const unwatched = ledger.unwatched || [];
    ledger.read = ledger.entries.length;
    ledger.unwatched = [];
    return {resources: statuses.length, statuses, unwatched, limited: limited(), limited_at: ledger.limitedAt || null};
  };
  const user = () => {
    try {
      const value = window['require']('CurrentUserInitialData').USER_ID;
      return value === undefined || value === null ? null : String(value);
    } catch (_) { return null; }  // not a logged-in Facebook page
  };
  return {ledger, limited, unread, settle, user, load: window['require']};
}
