// The page model of X (x.com): its webpack runtime with module factories whose source holds the operation
// definitions, the signature generator and the bearer; chunks loaded by id; the redux store found through the React
// root. Used by snippet_harness.mjs (model "webpack").
//
// page keys: modules {"<id>": "<factory source>"}, exports {"<id>": {...}} (what requiring a module returns;
//   {"__generator": true} stands for the signature generator (host, path, method) => "TXID:<method>:<path>",
//   {"__function": x} for a function returning x), chunks {"<id>": {"name", "modules": {...}}}, state {...redux state}
//   or null (no store), react: false (no React root), webpack: false (no webpack runtime).
// outputs: generator_calls [[host, path, method]], chunk_loads [ids].
const generatorCalls = [], chunkLoads = [];

export function build(pageSpec) {
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
  const state = pageSpec.state === undefined ? {session: {user_id: '1000000099', language: 'en'}, featureSwitch: {user: {config: {}}}} : pageSpec.state;
  const fiber = state === null ? {} : {child: {memoizedProps: {store: {getState: () => state}}}};
  const root = {['__reactContainer$test']: fiber};
  const globals = {};
  if (pageSpec.webpack !== false) globals.webpackChunk_twitter_responsive_web = {push: (entry) => { if (entry[2]) entry[2](runtime); }};
  return {globals, querySelector: (selector) => (selector === '#react-root' && pageSpec.react !== false ? root : null)};
}

export function outputs() {
  return {generator_calls: generatorCalls, chunk_loads: chunkLoads};
}
