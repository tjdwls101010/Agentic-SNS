// Run the skill's real browser JavaScript under Node with a fake page and record what it would send.
//
//   node snippet_harness.mjs <case.json>
//
// case: {"kind": "page" | "program", "source": "<path to the .js file>", "args": {...}, "page": {...}}
//   page: {"location": "https://www.facebook.com/", "modules": {"<name>": value or {"params": {...}}},
//          "fetch": [{"status", "url", "body"}] (responses in order), "resources": [entry counts, one per read],
//          "observed": [statuses of the facebook.com requests made during the call]}
// For kind "program", the aside REPL globals (listBrowserTabs, attachBrowserTab, console) are faked and the page
// function inside is the snippet named by "function".
// Prints one JSON line: {"result": <what the code returned or printed>, "fetches": [{url, method, headers, body}]}.
import fs from 'node:fs';
import vm from 'node:vm';

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const fetches = [];
const pageSpec = spec.page || {};
const pending = [], during = [];
let finished = 0;
const entry = (status) => ({name: 'https://www.facebook.com/ajax/o' + finished++, responseStatus: status});
const finish = (call) => {
  for (const status of call.before || []) pending.push(entry(status));
  for (const status of call.observed || []) during.push(entry(status));
};
for (const status of pageSpec.buffered || []) pending.push(entry(status));
let resourceCalls = 0;
const resources = pageSpec.resources || [0];

function fakeWindow() {
  const responses = [...(pageSpec.fetch || [])];
  const modules = pageSpec.modules || {};
  const hydrate = (value) => {
    if (value && typeof value === 'object' && value.params && value.params.providedVariables) {
      const provided = {};
      for (const [k, v] of Object.entries(value.params.providedVariables)) provided[k] = {get: () => v};
      return {...value, params: {...value.params, providedVariables: provided}};
    }
    if (value && typeof value === 'object' && value.__function) return () => value.__function;
    return value;
  };
  const require = (name) => {
    if (!(name in modules)) throw new Error('Requiring unknown module "' + name + '"');
    return hydrate(modules[name]);
  };
  const location = new URL(pageSpec.location || 'https://www.facebook.com/');
  const history = {pushState: (state, title, url) => { const next = new URL(url, location.href); location.href = next.href; }};
  const window = {require, requireLazy: () => {}, dispatchEvent: () => true, location, history};
  const fetch = async (url, init = {}) => {
    const absolute = new URL(url, location.href).href;
    fetches.push({url: absolute, method: init.method || 'GET', headers: init.headers || {}, body: init.body || null,
                  credentials: init.credentials || null});
    const response = responses.shift() || {status: 200, url: absolute, body: ''};
    if (response.throw) throw new Error(response.throw);
    return {status: response.status, url: response.url || absolute, text: async () => response.body};
  };
  // Requests the tab finishes, as PerformanceObserver reports them. page.buffered: finished before the page was
  // first watched; a call's before: finished between calls; a call's observed: finished during the call (after a
  // ledger the call installs has taken its first records).
  class PerformanceObserver {
    constructor(callback) { this.callback = callback; this.installing = false; }
    observe() { this.installing = true; }
    takeRecords() {
      if (this.installing) { this.installing = false; return pending.splice(0); }
      return pending.splice(0).concat(during.splice(0));
    }
    disconnect() {}
  }
  const performance = {getEntriesByType: () => {
    const count = resources[Math.min(resourceCalls++, resources.length - 1)];
    return Array.from({length: count}, (_, i) => ({name: 'https://www.facebook.com/ajax/x' + i}));
  }};
  return {window, fetch, performance, PerformanceObserver, location, history, PopStateEvent: class { constructor(type) { this.type = type; } },
          URL, AbortController, setTimeout, clearTimeout, JSON, Object, Array, String, Number, Promise, Date, Math,
          encodeURIComponent, decodeURIComponent, Error, RegExp, Buffer};
}

let sharedContext = null;
async function runPage(source, args) {
  const context = sharedContext || vm.createContext(fakeWindow());
  const fn = vm.runInContext('(' + source.trim().replace(/;\s*$/, '') + ')', context);
  return await fn(args);
}

async function runSequence() {
  sharedContext = vm.createContext(fakeWindow());  // one page across calls, as the dedicated tab is
  const results = [];
  for (const call of spec.calls) {
    finish(call);
    results.push(await runPage(fs.readFileSync(call.source, 'utf8'), call.args));
  }
  return results;
}

async function runProgram() {
  const printed = [];
  const pageFn = fs.readFileSync(spec.function, 'utf8');
  const program = fs.readFileSync(spec.source, 'utf8').replace('PAGE_FUNCTION', pageFn);
  const tabs = pageSpec.tabs || [{targetId: 'T1', url: 'https://www.facebook.com/'}];
  const context = vm.createContext({
    ASIDE: spec.aside, ARGS: spec.args, JSON, String, Promise, Math,
    console: {log: (line) => printed.push(line)},
    listBrowserTabs: async () => tabs,
    attachBrowserTab: async (id) => {
      if (!tabs.some(t => t.targetId === id)) throw new Error('no tab ' + id);
      return {evaluate: async (fn, args) => {
        if (spec.evaluate_returns !== undefined) return spec.evaluate_returns;
        return await runPage(fn.toString(), args);
      }};
    },
  });
  await vm.runInContext('(async () => {' + program + '})()', context);
  return printed;
}

if (spec.kind === 'page') finish(pageSpec);
const result = spec.kind === 'program' ? await runProgram() : spec.kind === 'sequence' ? await runSequence()
  : await runPage(fs.readFileSync(spec.source, 'utf8'), spec.args);
process.stdout.write(JSON.stringify({result, fetches}) + '\n');
