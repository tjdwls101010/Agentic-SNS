// Run the skill's real browser JavaScript under Node with a fake x.com page and record what it would send.
//
//   node snippet_harness.mjs <case.json>
//
// case: {"calls": [{"source": "<composed page function file>", "args": {...}, "before": [entries], "during": [entries],
//                   "app": [{"url", "status", "body", "headers"}], "reload": true, "lost": true, "repeat": n}],
//        "page": {"location", "cookie", "html", "modules": {"<id>": "<factory source>"}, "exports": {"<id>": {...}},
//                 "chunks": {"<id>": {"name", "modules": {...}}}, "state": {...redux state} | null, "fetch": [{status,
//                 body, headers}], "buffered": [entries], "fragment": true}}
// An entry is {"url", "status"}: a request the tab finished, as PerformanceObserver reports it. buffered: finished
// before the kit was installed; before: finished between calls; during: finished while the call ran. The skill's own
// fetch adds its entry by itself (with its fragment, unless page.fragment is false). app: requests the app makes
// before the call through the page's XHR, so a hook installed earlier sees them. exports: what requiring a module
// returns; {"__generator": true} stands for the signature generator (host, path, method) => "TXID:<method>:<path>".
// reload: a new window before the call, same sessionStorage (the tab reloaded); lost: a new window and an empty
// sessionStorage (a new tab). late_own: the previous skill request's timing entry (with its fragment) arrives before
// this call; same_url: an app request to that exact URL without a fragment arrives before it. repeat: run the call that many times (a load polling arm). Prints one JSON line:
// {"results": [...], "fetches": [{url, method, headers, credentials}], "generator_calls": [[host, path, method]],
// "locations": [...], "storage": {...}, "chunk_loads": [ids]}.
import fs from 'node:fs';
import vm from 'node:vm';

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const pageSpec = spec.page || {};
const fetches = [], generatorCalls = [], chunkLoads = [];
let pending = [], during = [];
let storage = new Map();

function makeWindow() {
  const responses = [...(pageSpec.fetch || [])];
  const location = new URL(pageSpec.location || 'https://x.com/i/xskill');
  location.assign = (url) => { location.href = url; };
  location.replace = (url) => { location.href = url; };
  const modules = {};
  const source = (text) => ({toString: () => text});
  for (const [id, text] of Object.entries(pageSpec.modules || {})) modules[id] = source(text);
  const exportsOf = (id) => {
    const value = (pageSpec.exports || {})[id];
    if (!value) throw new Error('no module ' + id);
    const out = {};
    for (const [key, v] of Object.entries(value)) {
      if (v && v.__generator) {
        out[key] = async function (host, path, method) { generatorCalls.push([host, path, method]); return 'TXID:' + method + ':' + path; };
      } else if (v && v.__function) {
        out[key] = function () { return v.__function; };
      } else {
        out[key] = v;
      }
    }
    return out;
  };
  const runtime = (id) => exportsOf(id);
  runtime.m = modules;
  const chunkMap = Object.fromEntries(Object.entries(pageSpec.chunks || {}).map(([id, c]) => [id, c.name]));
  runtime.u = function (e) { return (chunkMap[e] || e) + '.js'; };
  runtime.u.toString = () => 'function(e){return""+({' + Object.entries(chunkMap).map(([id, n]) => id + ':"' + n + '"').join(',') + '}[e]||e)+".js"}';
  runtime.e = async (id) => {
    chunkLoads.push(id);
    const chunk = (pageSpec.chunks || {})[String(id)];
    if (chunk) for (const [mid, text] of Object.entries(chunk.modules || {})) modules[mid] = source(text);
  };
  const act = () => { pending.push(...during.splice(0)); };
  const sessionStorage = {getItem: k => storage.has(k) ? storage.get(k) : null, setItem: (k, v) => storage.set(k, String(v))};
  const realFetch = async (url, init = {}) => {
    const absolute = new URL(url, location.href).href;
    fetches.push({url: absolute, method: init.method || 'GET', headers: init.headers || {}, credentials: init.credentials || null});
    act();
    const entryName = pageSpec.fragment === false ? absolute.split('#')[0] : absolute;
    if (!pageSpec.no_own_entry) pending.push({url: entryName, status: 200});
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
  const state = pageSpec.state === undefined ? {session: {user_id: '1000000099', language: 'en'}, featureSwitch: {user: {config: {}}}} : pageSpec.state;
  const fiber = state === null ? {} : {child: {memoizedProps: {store: {getState: () => state}}}};
  const root = {['__reactContainer$test']: fiber};
  const document = {cookie: pageSpec.cookie === undefined ? 'ct0=SYNTHCSRF0000; twid=u%3D1000000099' : pageSpec.cookie,
                    readyState: 'complete', documentElement: {outerHTML: pageSpec.html || '<html></html>'},
                    querySelector: (sel) => sel === '#react-root' && pageSpec.react !== false ? root : null};
  // entries_api: performance.getEntriesByType('resource') answers what is still in the timing buffer (the buffered entries)
  const buffer = () => (pageSpec.entries_api ? pending.map(e => ({name: e.url})) : []);
  const context = {fetch: realFetch, XMLHttpRequest, PerformanceObserver, location, sessionStorage, document,
                   performance: {now: () => 1234.5, getEntriesByType: () => buffer()}, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
                   JSON, Object, Array, String, Number, Boolean, Promise, Date, Math, Set, Map, encodeURIComponent,
                   decodeURIComponent, Error, RegExp};
  if (pageSpec.webpack !== false) context.webpackChunk_twitter_responsive_web = {push: (entry) => { if (entry[2]) entry[2](runtime); }};
  context.window = context;
  context.self = context;
  return vm.createContext(context);
}

let page = makeWindow();
for (const entry of pageSpec.buffered || []) pending.push(entry);

async function appRequest(context, request) {
  // The app's own request, through the page's XHR, so a hook installed earlier sees it.
  await vm.runInContext(`((r) => { const x = new window.XMLHttpRequest(); x.open('GET', r.url);
    Object.defineProperty(x, 'status', {value: r.status}); Object.defineProperty(x, 'responseText', {value: r.body || ''});
    Object.defineProperty(x, 'responseType', {value: ''}); Object.defineProperty(x, 'responseURL', {value: r.url});
    x.__headers = r.headers || {}; x.send(); })`, context)(request);
}

const results = [], locations = [];
for (const call of spec.calls) {
  if (call.reload) { page = makeWindow(); }
  if (call.lost) { storage = new Map(); page = makeWindow(); }
  for (const entry of call.before || []) pending.push(entry);
  // late_own: the previous skill request's entry arrives only now; same_url: an app request to that exact URL
  const last = fetches.length ? fetches[fetches.length - 1].url : null;
  if (call.late_own && last) pending.push({url: last, status: 200});
  if (call.same_url && last) pending.push({url: last.split('#')[0], status: 200});
  during = [...(call.during || [])];
  for (const request of call.app || []) await appRequest(page, request);
  const fn = vm.runInContext('(' + fs.readFileSync(call.source, 'utf8').trim().replace(/;\s*$/, '') + ')', page);
  for (let i = 0; i < (call.repeat || 1); i++) results.push(await fn(call.args || {}));
  pending.push(...during.splice(0));
  await new Promise(resolve => setTimeout(resolve, 20));
  locations.push(vm.runInContext('location.href', page));
}
process.stdout.write(JSON.stringify({results, fetches, generator_calls: generatorCalls, chunk_loads: chunkLoads, locations,
                                     storage: Object.fromEntries(storage)}) + '\n');
