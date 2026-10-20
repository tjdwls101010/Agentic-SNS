// The page model of a Meta Relay web app (threads.com; Facebook's own model is tests/sns/facebook/page_model.mjs until the
// two are reconciled): a module loader the page reaches as window.require, whose modules the case names. Used by
// snippet_harness.mjs (model "relay").
//
// page keys: modules {"<name>": value | {"params": {id, operationKind, providedVariables: {"<name>": value}}} |
//   {"__function": x} | {"__provider": value}} — what requiring the module returns. A params object gets its provided
//   variables turned into providers with get(); a value {"__throws": true} makes get() throw (a provider the page cannot
//   evaluate); {"__function": x} is a function returning x; {"__provider": v} is a provider whose get() returns v.
//   Requiring a name that is not listed throws, as the real loader does.
// outputs: none.
export function build(pageSpec) {
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
    if (value && typeof value === 'object' && '__provider' in value) {
      return {get: () => { if (value.__provider && value.__provider.__throws) throw new Error('provider failed'); return value.__provider; }};
    }
    return value;
  };
  const load = (name) => {
    if (!(name in modules)) throw new Error('Requiring unknown module "' + name + '"');
    return hydrate(modules[name]);
  };
  return {globals: pageSpec.require === false ? {} : {require: load}, querySelector: () => null};
}

export function outputs() {
  return {};
}
