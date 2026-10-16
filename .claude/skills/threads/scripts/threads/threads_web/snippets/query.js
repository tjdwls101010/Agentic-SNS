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
for (const suffix of ['.threads.graphql', '.graphql']) {
  try {
    const module = load(args.name + suffix);
    const params = module && module.params;
    if (params && /^\d+$/.test(String(params.id))) {
      if (params.operationKind !== 'query') return refuse('the live module is not a query');
      doc = String(params.id);
      flags = {};
      for (const [name, provider] of Object.entries(params.providedVariables || {})) flags[name] = provider.get();
      source = 'live';
      break;
    }
  } catch (_) { /* not loaded */ }
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
}
// A block the tab already saw (between calls, or before a reload) stops this call before it sends anything.
const before = await kit.settle(0);
if (before.statuses.includes(429) || kit.pending().length) {
  return {stopped: 'signal', explicit: 0, ...before, signals: kit.pending(), location: location.href};
}
let form;
try {
  form = Object.assign({}, load('getAsyncParams')('POST'));
  if (!form.fb_dtsg || !form.lsd) throw new Error('no token');
} catch (_) {
  return {network_error: 'the page has no request parameters', explicit: 0, ...(await kit.report(0))};
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
  return {status: response.status, url: response.url, body: text.slice(0, args.max_body || 4000000), used, explicit: 1, ...(await kit.report())};
} catch (error) {
  return {network_error: String(error).slice(0, 200), used, explicit: 1, ...(await kit.report())};
} finally {
  clearTimeout(timer);
}
