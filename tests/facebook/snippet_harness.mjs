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
  // Requests the page makes during a call, as PerformanceObserver reports them: page.observed lists their statuses.
  const observed = (pageSpec.observed || []).map((status, i) => ({name: 'https://www.facebook.com/ajax/o' + i,
                                                                  responseStatus: status}));
  class PerformanceObserver {
    constructor(callback) { this.callback = callback; this.delivered = false; }
    observe() {}
    takeRecords() { if (this.delivered) return []; this.delivered = true; return observed; }
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

async function runPage(source, args) {
  const context = vm.createContext(fakeWindow());
  const fn = vm.runInContext('(' + source.trim().replace(/;\s*$/, '') + ')', context);
  return await fn(args);
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

const result = spec.kind === 'program' ? await runProgram()
  : await runPage(fs.readFileSync(spec.source, 'utf8'), spec.args);
process.stdout.write(JSON.stringify({result, fetches}) + '\n');
