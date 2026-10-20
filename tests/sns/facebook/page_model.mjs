// The page model of Facebook (www.facebook.com): the page's module loader (`require`, reached by the snippets through
// an alias), the modules a test puts in it, history.pushState moving the page's location, and a virtual clock so the
// route function's 15-second wait does not take 15 seconds. Used by snippet_harness.mjs as model "facebook" (the test
// runner copies this file beside the harness under that name).
//
// page keys: modules {"<name>": value | {"params": {id, providedVariables: {name: value}}} | {"__function": x}}
//   (what loading the module returns; a __function is a function returning x), virtual_time: true (the clock the
//   snippets read, Date.now, and setTimeout move together without waiting).
// outputs: pushes [the paths history.pushState moved to], popstates (count).
const pushes = [];
let popstates = 0;

export function build(pageSpec) {
  const modules = pageSpec.modules || {};
  const hydrate = (value) => {
    if (value && typeof value === 'object' && value.params && value.params.providedVariables) {
      const provided = {};
      for (const [k, v] of Object.entries(value.params.providedVariables)) provided[k] = {get: () => v};
      return {...value, params: {...value.params, providedVariables: provided}};
    }
    if (value && typeof value === 'object' && value.__function !== undefined) return () => value.__function;
    return value;
  };
  const load = (name) => {
    if (!(name in modules)) throw new Error('Requiring unknown module "' + name + '"');
    return hydrate(modules[name]);
  };
  const location = new URL(pageSpec.location || 'https://www.facebook.com/');
  const history = {pushState: (state, title, url) => { pushes.push(url); location.href = new URL(url, location.href).href; }};
  class PopStateEvent { constructor(type) { this.type = type; } }
  const globals = {require: load, requireLazy: () => {}, history, location, PopStateEvent,
                   dispatchEvent: () => { popstates += 1; return true; },
                   performance: {now: () => 1234.5, getEntriesByType: () => []}};
  if (pageSpec.virtual_time) {
    let now = Date.now();
    globals.Date = {now: () => now};
    globals.setTimeout = (fn, ms) => { now += ms || 0; return setImmediate(fn); };
  }
  return {globals, querySelector: () => null};
}

export function outputs() {
  return {pushes, popstates};
}
