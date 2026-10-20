// sns-snippet: facebook.query
// One read-only GraphQL request from this facebook.com page, with the page's own request parameters. Only the read
// queries the skill names (args.allowed, from queries.json) can be sent.
if (!Array.isArray(args.allowed) || !args.allowed.includes(args.name) || !args.variables || typeof args.variables !== 'object') {
  return {refused: 'not a read query', explicit: 0, resources: 0};
}
const r = kit.load;
let doc = null, flags = null, source = null;
try {
  const query = r(args.name + '.graphql');
  if (query && query.params && /^\d+$/.test(String(query.params.id))) {
    doc = String(query.params.id);
    flags = {};
    for (const [name, provider] of Object.entries(query.params.providedVariables || {})) flags[name] = provider.get();
    source = 'live';
  }
} catch (_) { doc = null; flags = null; }
if (!doc) {
  try {
    const operation = r(args.name + '_facebookRelayOperation');
    if (typeof operation === 'string' && /^\d+$/.test(operation)) { doc = operation; source = 'live_id'; }
  } catch (_) { /* not loaded */ }
}
const fallback = args.fallback || {};
if (!doc) {
  if (!/^\d+$/.test(String(fallback.doc_id || ''))) return {missing: 'no query id', used: {source: 'none'}, explicit: 0, resources: 0};
  doc = String(fallback.doc_id);
  source = 'stored';
}
// The query's own provider values win over the ones in the variables; a refused query id the page just gave is the
// client's to relearn, so what the page used is reported back.
const provided = flags || fallback.flags || {};
let form;
try {
  form = Object.assign({}, r('getAsyncParams')('POST'));
  if (!form.fb_dtsg) throw new Error('no token');
} catch (_) {
  // The fields the page itself sends when getAsyncParams is unavailable.
  const user = String(r('CurrentUserInitialData').USER_ID);
  const dtsg = r('DTSGInitialData').token;
  const spin = String(r('SiteData').__spin_r);
  let sum = 0;
  for (const char of dtsg) sum += char.codePointAt(0);
  form = {av: user, __user: user, __a: '1', __comet_req: '15', fb_dtsg: dtsg, jazoest: '2' + sum, lsd: r('LSD').token,
          __spin_r: spin, __rev: spin};
}
Object.assign(form, {fb_api_caller_class: 'RelayModern', fb_api_req_friendly_name: args.name,
                     variables: JSON.stringify(Object.assign({}, args.variables, provided)),
                     server_timestamps: 'true', doc_id: doc});
const body = Object.entries(form).map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');
// A rate limit the tab already saw (between calls, or on a reload) stops this call before it sends anything.
if (kit.unread().includes(429) || kit.limited()) return {stopped: 'rate_limit', explicit: 0, ...(await kit.settle(0))};
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 60000);
const used = {source, doc_id: doc, flags: source === 'live' ? flags : null};
try {
  const response = await fetch('/api/graphql/', {
    method: 'POST', credentials: 'include', body, signal: controller.signal,
    headers: {'content-type': 'application/x-www-form-urlencoded', 'x-fb-friendly-name': args.name,
              'x-fb-lsd': String(form.lsd || '')}});
  const text = await response.text();
  return {status: response.status, url: response.url, body: text, used, user_id: kit.user(), location: location.href, explicit: 1, ...(await kit.settle())};
} catch (error) {
  return {network_error: String(error).slice(0, 200), used, explicit: 1, ...(await kit.settle())};
} finally {
  clearTimeout(timer);
}
