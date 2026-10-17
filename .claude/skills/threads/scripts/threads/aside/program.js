// The aside repl program around every call. ASIDE and ARGS are prepended as two JSON lines by browser.py.
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
  try {
    emit(await target.evaluate(PAGE_FUNCTION, ARGS));
  } catch (error) {
    fail('evaluate_failed', error);
  }
})();
