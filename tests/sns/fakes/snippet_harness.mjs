// Run a platform's real browser JavaScript under Node with a fake page and record what it would send. The page's own
// app (X's webpack modules, a Relay runtime, ...) is a page model in page_<model>.mjs; this file is everything every
// platform's snippets share: the vm context, fetch, XMLHttpRequest, PerformanceObserver, sessionStorage and the case
// runner.
//
//   node snippet_harness.mjs <case.json>
//
// case: {"model": "webpack", "page": {...}, "calls": [{"source": "<composed page function file>", "args": {...},
//         "before": [entries], "during": [entries], "app": [{"url", "status", "body", "headers", "type"}],
//         "reload": true, "lost": true, "late_own": true, "same_url": true, "repeat": n}]}
// page (shared): location, cookie, html, fetch: [{status, body, headers, throw}] answered to the page function's own
//   fetches in order, buffered: [entries] finished before the kit was installed, fragment: false (the timing entry
//   of an own request carries no #fragment), no_own_entry: true (its timing entry never arrives), entries_api: true
//   (performance.getEntriesByType answers the buffered entries); the model's own keys are in its file.
// An entry is {"url", "status"}: a request the tab finished, as PerformanceObserver reports it. before: finished
//   between calls; during: finished while the call ran. The page function's fetch adds its own entry by itself. app:
//   requests the app makes before the call through the page's XHR, so a hook installed earlier sees them. reload: a new
//   window before the call, same sessionStorage (the tab reloaded); lost: a new window and an empty sessionStorage (a
//   new tab). no_own_entry: true on one call: its own timing entry never arrives (overrides the page's). late_own: the previous own request's timing entry arrives before this call; same_url: an app request to
//   that exact URL without a fragment arrives before it. repeat: run the call that many times (a load polling arm).
// Prints one JSON line: {"results": [...], "fetches": [{url, method, headers, credentials}], "locations": [...],
//   "storage": {...}, ...whatever the model reports (generator_calls, chunk_loads, ...)}.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath, pathToFileURL} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const pageSpec = spec.page || {};
const model = await import(pathToFileURL(path.join(here, `page_${spec.model}.mjs`)).href);
const fetches = [];
let pending = [], during = [];
let storage = new Map();
const responses = [...(pageSpec.fetch || [])];  // answers to the page function's fetches, across reloads
let ownEntry = true;  // whether the running call's own fetch adds its timing entry

function makeWindow() {
  const location = new URL(pageSpec.location || 'about:blank');
  location.assign = (url) => { location.href = url; };
  location.replace = (url) => { location.href = url; };
  const act = () => { pending.push(...during.splice(0)); };
  const sessionStorage = {getItem: k => storage.has(k) ? storage.get(k) : null, setItem: (k, v) => storage.set(k, String(v))};
  const realFetch = async (url, init = {}) => {
    const absolute = new URL(url, location.href).href;
    fetches.push({url: absolute, method: init.method || 'GET', headers: init.headers || {}, credentials: init.credentials || null});
    act();
    const entryName = pageSpec.fragment === false ? absolute.split('#')[0] : absolute;
    if (ownEntry) pending.push({url: entryName, status: 200});
    const response = responses.shift() || {status: 200, body: '{"data":{}}'};
    if (response.throw) throw new Error(response.throw);
    const headers = response.headers || {};
    const make = () => ({status: response.status, url: absolute.split('#')[0], text: async () => response.body,
                         headers: {get: (k) => (k.toLowerCase() in headers ? String(headers[k.toLowerCase()]) : null)},
                         clone: () => make()});
    return make();
  };
  class XMLHttpRequest {
    open(method, url) { this.url = url; }
    addEventListener(type, fn) { this.listener = fn; }
    getResponseHeader(k) { const h = this.__headers || {}; return k.toLowerCase() in h ? String(h[k.toLowerCase()]) : null; }
    send() { if (this.listener) this.listener(); }
  }
  class PerformanceObserver {
    constructor(callback) { this.callback = callback; }
    observe() {}
    takeRecords() { return pending.splice(0).map(e => ({name: e.url, responseStatus: e.status})); }
    disconnect() {}
  }
  const app = model.build(pageSpec);
  const document = {cookie: pageSpec.cookie === undefined ? '' : pageSpec.cookie, readyState: 'complete',
                    documentElement: {outerHTML: pageSpec.html || '<html></html>'},
                    querySelector: (selector) => app.querySelector(selector)};
  // entries_api: performance.getEntriesByType('resource') answers what is still in the timing buffer (the buffered entries)
  const buffer = () => (pageSpec.entries_api ? pending.map(e => ({name: e.url})) : []);
  const context = {fetch: realFetch, XMLHttpRequest, PerformanceObserver, location, sessionStorage, document,
                   performance: {now: () => 1234.5, getEntriesByType: () => buffer()}, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
                   JSON, Object, Array, String, Number, Boolean, Promise, Date, Math, Set, Map, encodeURIComponent,
                   decodeURIComponent, Error, RegExp, ...app.globals};
  context.window = context;
  context.self = context;
  return {context: vm.createContext(context), app};
}

let page = makeWindow();
for (const entry of pageSpec.buffered || []) pending.push(entry);

async function appRequest(context, request) {
  // The app's own request, through the page's XHR, so a hook installed earlier sees it.
  await vm.runInContext(`((r) => { const x = new window.XMLHttpRequest(); x.open('GET', r.url);
    Object.defineProperty(x, 'status', {value: r.status}); Object.defineProperty(x, 'responseURL', {value: r.url});
    Object.defineProperty(x, 'responseType', {value: r.type || ''});
    if (r.type === 'json') {  // as browsers do: the parsed body in response, and responseText throws
      Object.defineProperty(x, 'response', {value: JSON.parse(r.body || 'null')});
      Object.defineProperty(x, 'responseText', {get() { throw new Error('InvalidStateError'); }});
    } else {
      Object.defineProperty(x, 'responseText', {value: r.body || ''});
    }
    x.__headers = r.headers || {}; x.send(); })`, context)(request);
}

const results = [], locations = [];
for (const call of spec.calls) {
  if (call.reload) page = makeWindow();
  if (call.lost) { storage = new Map(); page = makeWindow(); }
  for (const entry of call.before || []) pending.push(entry);
  // late_own: the previous own request's entry arrives only now; same_url: an app request to that exact URL
  const last = fetches.length ? fetches[fetches.length - 1].url : null;
  if (call.late_own && last) pending.push({url: last, status: 200});
  if (call.same_url && last) pending.push({url: last.split('#')[0], status: 200});
  during = [...(call.during || [])];
  ownEntry = !(call.no_own_entry === undefined ? pageSpec.no_own_entry : call.no_own_entry);
  for (const request of call.app || []) await appRequest(page.context, request);
  const fn = vm.runInContext('(' + fs.readFileSync(call.source, 'utf8').trim().replace(/;\s*$/, '') + ')', page.context);
  for (let i = 0; i < (call.repeat || 1); i++) results.push(await fn(call.args || {}));
  pending.push(...during.splice(0));
  await new Promise(resolve => setTimeout(resolve, 20));
  locations.push(vm.runInContext('location.href', page.context));
}
process.stdout.write(JSON.stringify({results, fetches, locations, storage: Object.fromEntries(storage),
                                     ...model.outputs()}) + '\n');
