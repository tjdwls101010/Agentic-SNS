// threads-snippet: query
// One read-only GraphQL request from this www.threads.com tab, sent the way the app sends it: the page's own request
// parameters and headers, the query id and provider values of the app's loaded module when it has one, else the
// skill's. Refuses a name that is not on the skill's read list, names a mutation, or whose live module is no query.
const load = window['req' + 'uire'];
const refuse = why => ({refused: why, explicit: 0, resources: 0, statuses: [], signals: kit.pending(), location: location.href});
if (!Array.isArray(args.allowed) || !args.allowed.includes(args.name) || !/^[A-Za-z0-9_]+Query$/.test(args.name) || /Mutation/.test(args.name)) {
  return refuse('not a read query');
}
if (location.origin !== 'https://www.threads.com') return refuse('not the Threads origin');
let doc = null, flags = null, source = null;
// <Name>$Parameters.threads holds a preloadable query's id and providers when its full definition is not loaded
for (const suffix of ['.threads.graphql', '.graphql', '$Parameters.threads']) {
  let params = null;
  try { const module = load(args.name + suffix); params = module && module.params; } catch (_) { /* not loaded */ }
  if (!params || !/^\d+$/.test(String(params.id))) continue;
  if (params.operationKind !== 'query') return refuse('the live module is not a query');
  const values = {};
  try {
    for (const [name, provider] of Object.entries(params.providedVariables || {})) values[name] = provider.get();
  } catch (_) {
    // without every provider value Threads fails the query: send nothing, so the id is learned again
    return {missing: 'a provider of the live module could not be read', used: {source: 'none'}, explicit: 0, ...(await kit.report(0))};
  }
  doc = String(params.id);
  flags = values;
  source = 'live';
  break;
}
if (!doc) {
  try {
    const operation = load(args.name + '_threadsRelayOperation');
    if (typeof operation === 'string' && /^\d+$/.test(operation)) { doc = operation; source = 'live_id'; }
  } catch (_) { /* not loaded */ }
}
const fallback = args.fallback || {};
if (!doc) {
  if (!/^\d+$/.test(String(fallback.doc_id || ''))) return {missing: 'no query id', used: {source: 'none'}, explicit: 0, ...(await kit.report(0))};
  doc = String(fallback.doc_id);
  source = 'stored';
}
let provided = flags;
if (!provided) {
  provided = {};
  for (const [name, module] of fallback.providers || []) {
    try { const p = load(module); provided[name] = typeof p.get === 'function' ? p.get() : p; } catch (_) { /* not loaded */ }
  }
  provided = {...(fallback.flags || {}), ...provided};
  // a query sent without one of its provider values fails at Threads: send nothing, so the id is learned again
  const unknown = (fallback.providers || []).map(([name]) => name).filter(name => !(name in provided));
  if (unknown.length) return {missing: 'no value for ' + unknown.slice(0, 3).join(', '), used: {source: 'none'}, explicit: 0, ...(await kit.report(0))};
}
// A block or login page, a 429 or a signal the tab already saw stops this call before it sends anything.
const gate = await kit.gate();
if (gate.stopped) return gate;
const before = gate.before;
let form;
try {
  form = Object.assign({}, load('getAsyncParams')('POST'));
  if (!form.fb_dtsg || !form.lsd) throw new Error('no token');
} catch (_) {
  return {network_error: 'the page has no request parameters', explicit: 0, ...(await kit.report(0, before))};
}
const current = load('CurrentUserInitialData');
Object.assign(form, {av: String(current.NON_FACEBOOK_USER_ID), fb_api_caller_class: 'RelayModern', fb_api_req_friendly_name: args.name,
                     server_timestamps: 'true', variables: JSON.stringify(Object.assign({}, args.variables, provided)), doc_id: doc});
const cookie = (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || '';
const headers = {'content-type': 'application/x-www-form-urlencoded', 'x-fb-friendly-name': args.name, 'x-csrftoken': cookie,
                 'x-ig-app-id': String(current.APP_ID), 'x-fb-lsd': String(form.lsd), 'x-asbd-id': String(args.asbd_id)};
if (args.root) headers['x-root-field-name'] = args.root;
const endpoint = args.endpoint === '/graphql/query' ? '/graphql/query' : '/api/graphql/';
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 45000);
const used = {source, doc_id: doc, flags: source === 'live' ? flags : null};
try {
  const response = await fetch(endpoint, {method: 'POST', credentials: 'include', body: new URLSearchParams(form).toString(),
                                          headers, signal: controller.signal});
  const text = await response.text();
  return {status: response.status, url: response.url, body: text.slice(0, args.max_body || 4000000), used, explicit: 1, ...(await kit.report(50, before))};
} catch (error) {
  return {network_error: String(error).slice(0, 200), used, explicit: 1, ...(await kit.report(50, before))};
} finally {
  clearTimeout(timer);
}
