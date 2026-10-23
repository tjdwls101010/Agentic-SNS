// sns-snippet: aside.program
// The aside repl program around every call. ASIDE and ARGS are prepended as two JSON lines by aside/__init__.py.
// ASIDE.op: tabs (list them), evaluate (run the page function in ASIDE.tab), load (send ASIDE.tab to ASIDE.url, then
// run the page function until it answers), run (call the function with ARGS in the REPL itself, no tab: a fetch
// with the browser's cookies).
// Prints chunk lines and then exactly one result or error line; nothing from the page is written to disk.
await (async () => {
  const emit = (value) => {
    const text = JSON.stringify(value === undefined ? null : value);
    // One REPL log line holds about 12 MiB (measured); keep each line well below it.
    const size = 512 * 1024;
    if (text.length <= 4 * size) {
      console.log(JSON.stringify({kind: 'result', chunks: 0, body: text}));
      return;
    }
    let index = 0;
    for (let offset = 0; offset < text.length;) {
      let end = Math.min(offset + size, text.length);
      const last = text.charCodeAt(end - 1);
      if (end < text.length && last >= 0xD800 && last <= 0xDBFF) end--;
      console.log(JSON.stringify({kind: 'chunk', index: index++, body: text.slice(offset, end)}));
      offset = end;
    }
    console.log(JSON.stringify({kind: 'result', chunks: index, body: ''}));
  };
  const fail = (error, message) => console.log(JSON.stringify({kind: 'error', error, message: String(message).slice(0, 300)}));
  if (ASIDE.op === 'tabs') {
    const listed = await listBrowserTabs();
    emit(listed.map(tab => ({targetId: tab.targetId, url: tab.url})));
    return;
  }
  if (ASIDE.op === 'run') {
    try {
      emit(await (PAGE_FUNCTION)(ARGS));
    } catch (error) {
      fail('run_failed', error);
    }
    return;
  }
  let target = null;
  try {
    target = await attachBrowserTab(ASIDE.tab);
  } catch (error) {
    fail('tab_missing', error);
    return;
  }
  if (!target) {
    fail('tab_missing', 'no such tab');
    return;
  }
  if (ASIDE.op === 'load') {
    // Send the tab to ASIDE.url without a history entry, then run the page function again and again until it answers
    // (null: not yet), so it acts before the new page's own scripts. The old document stays for a moment after
    // location.replace, so the function runs only once the document is a new one (a new timeOrigin).
    const origin = () => target.evaluate(() => performance.timeOrigin);
    let before = null;
    try { before = await origin(); } catch (_) { /* no document to compare with */ }
    try { await target.evaluate(url => { location.replace(url); }, ASIDE.url); } catch (_) { /* the page is unloading */ }
    const until = Date.now() + (ASIDE.seconds || 20) * 1000;
    while (Date.now() < until) {
      try {
        if (before === null || await origin() !== before) {
          const answer = await target.evaluate(PAGE_FUNCTION, ARGS);
          if (answer !== null && answer !== undefined) { emit(answer); return; }
        }
      } catch (_) { /* between documents */ }
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    fail('load_timeout', 'the page did not load in time');
    return;
  }
  try {
    emit(await target.evaluate(PAGE_FUNCTION, ARGS));
  } catch (error) {
    fail('evaluate_failed', error);
  }
})();
