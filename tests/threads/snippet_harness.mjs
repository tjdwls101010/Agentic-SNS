// Run the skill's real browser JavaScript under Node with a fake www.threads.com page and record what it would send.
//
//   node snippet_harness.mjs <case.json>
//
// case: {"calls": [{"source": "<composed page function file>", "args": {...}, "before": [entries], "during": [entries],
//                   "app": [{"url", "status", "body"}], "reload": true, "lost": true}],
//        "page": {"location", "modules": {"<name>": value | {"params": {...}}}, "cookie", "fetch": [{status, url, body,
//                 headers}], "html", "buffered": [entries]}}
// An entry is {"url", "status"}: a request the tab finished, as PerformanceObserver reports it. buffered: finished before
// the skill first looked; before: finished between calls; during: finished while the call acted (after a fetch).
// app: requests the app itself makes before the call (through the page's XHR, so a hook installed earlier sees them).
// reload: a new window before the call, same sessionStorage (the tab reloaded); lost: a new window and an empty
// sessionStorage (a new tab). Prints one JSON line: {"results": [...], "fetches": [{url, method, headers, body}],
// "locations": [the tab's address after each call], "storage": <the tab's sessionStorage>}.
import fs from 'node:fs';
import vm from 'node:vm';

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const pageSpec = spec.page || {};
const fetches = [];
let pending = [], during = [];
let storage = new Map();

function makeWindow() {
  const responses = [...(pageSpec.fetch || [])];
  const modules = pageSpec.modules || {};
  const hydrate = (value) => {
    if (value && typeof value === 'object' && value.params && value.params.providedVariables) {
      const provided = {};
      for (const [k, v] of Object.entries(value.params.providedVariables)) {
        provided[k] = {get: () => { if (v && v.__throws) throw new Error('provider failed'); return v; }};
      }
      return {...value, params: {...value.params, providedVariables: provided}};
    }
    if (value && typeof value === 'object' && value.__function) return () => value.__function;
    if (value && typeof value === 'object' && '__provider' in value) return {get: () => value.__provider};
    return value;
  };
  const require = (name) => {
    if (!(name in modules)) throw new Error('Requiring unknown module "' + name + '"');
    return hydrate(modules[name]);
  };
  const location = new URL(pageSpec.location || 'https://www.threads.com/search');
  location.assign = (url) => { location.href = url; };
  location.replace = (url) => { location.href = url; };
  const act = () => { pending.push(...during.splice(0)); };
  const sessionStorage = {getItem: k => storage.has(k) ? storage.get(k) : null, setItem: (k, v) => storage.set(k, String(v))};
  const realFetch = async (url, init = {}) => {
    const absolute = new URL(url, location.href).href;
    fetches.push({url: absolute, method: init.method || 'GET', headers: init.headers || {}, body: init.body || null,
                  credentials: init.credentials || null, redirect: init.redirect || null});
    act();
    const response = responses.shift() || {status: 200, url: absolute, body: ''};
    if (response.throw) throw new Error(response.throw);
    const make = () => ({status: response.status, url: response.url || absolute, text: async () => response.body,
                         headers: {get: (k) => (response.headers || {})[k.toLowerCase()] || null}, clone: () => make()});
    return make();
  };
  class XMLHttpRequest {
    open(method, url) { this.url = url; }
    addEventListener(type, fn) { this.listener = fn; }
    send() { if (this.listener) this.listener(); }
  }
  class PerformanceObserver {
    constructor(callback) { this.callback = callback; }
    observe() {}
    takeRecords() { return pending.splice(0).map(e => ({name: e.url, responseStatus: e.status})); }
    disconnect() {}
  }
  const document = {cookie: pageSpec.cookie || '', documentElement: {outerHTML: pageSpec.html || '<html></html>'}};
  // As in a browser, the global object is the window: a page that replaces window.fetch replaces fetch.
  const context = {require, fetch: realFetch, XMLHttpRequest, PerformanceObserver, location, sessionStorage, document,
                   performance: {timeOrigin: Date.now()}, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
                   JSON, Object, Array, String, Number, Promise, Date, Math, Set, Map, encodeURIComponent,
                   decodeURIComponent, Error, RegExp, Buffer};
  context.window = context;
  return vm.createContext(context);
}

let page = makeWindow();
for (const entry of pageSpec.buffered || []) pending.push(entry);

async function appRequest(context, request) {
  // The app's own request, through the page's XHR (as the app sends its GraphQL), so a hook installed earlier sees it.
  await vm.runInContext(`((r) => { const x = new window.XMLHttpRequest(); x.open('POST', r.url);
    Object.defineProperty(x, 'status', {value: r.status}); Object.defineProperty(x, 'responseText', {value: r.body});
    Object.defineProperty(x, 'responseURL', {value: r.url}); x.send(); })`, context)(request);
}

const results = [], locations = [];
for (const call of spec.calls) {
  if (call.reload) { page = makeWindow(); }
  if (call.lost) { storage = new Map(); page = makeWindow(); }
  for (const entry of call.before || []) pending.push(entry);
  during = [...(call.during || [])];
  for (const request of call.app || []) await appRequest(page, request);
  const fn = vm.runInContext('(' + fs.readFileSync(call.source, 'utf8').trim().replace(/;\s*$/, '') + ')', page);
  results.push(await fn(call.args || {}));
  pending.push(...during.splice(0));
  await new Promise(resolve => setTimeout(resolve, 20));  // let what the call scheduled (blank, navigate) happen
  locations.push(vm.runInContext('location.href', page));
}
process.stdout.write(JSON.stringify({results, fetches, locations, storage: Object.fromEntries(storage)}) + '\n');
