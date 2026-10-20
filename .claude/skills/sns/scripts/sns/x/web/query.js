// sns-snippet: x.query
// One read-only GraphQL request from this x.com tab, sent the way the app sends it: the query id, feature switches
// and field toggles of the app's own definition (the module index), the feature values of the app's store, the app's
// own signature generator and bearer, the app's header set; GET with JSON query parameters. Refuses a name that is not
// on the skill's read list or whose definition is not a query. The request URL carries a fresh nonce in its fragment
// (not sent to x.com) so the tab's ledger can tell this request apart; it goes through the fetch the page had before
// the hook.
const refuse = why => ({refused: why, explicit: 0, resources: 0, ours: 0, statuses: [], signals: kit.pending(), location: location.href});
const name = String(args.name || '');
if (!Array.isArray(args.allowed) || !args.allowed.includes(name) || !/^[A-Za-z0-9_]+$/.test(name)) return refuse('not a read operation');
if (location.origin !== 'https://x.com') return refuse('not the x.com origin');
let index = kit.index();
let def = index && index.ops[name];
let source = def ? 'live' : null;
if (!def && args.chunk_hint) {
  await kit.loadChunks(String(args.chunk_hint));
  index = kit.index();
  def = index && index.ops[name];
  source = def ? 'chunk' : null;
}
if (def && def.type !== 'query') return refuse('the app defines it as a ' + def.type);
const fallback = args.fallback || {};
if (!def) {
  if (!/^[A-Za-z0-9_-]+$/.test(String(fallback.query_id || ''))) return {missing: 'no query id', explicit: 0, ...(await kit.report(0))};
  def = {queryId: String(fallback.query_id), type: 'query', featureSwitches: fallback.features || [],
         fieldToggles: Object.keys(args.toggles || {})};
  source = 'stored';
}
const generator = kit.generator(!!args.fresh_generator);
const bearer = kit.bearer();
const session = kit.session();
const ct0 = (document.cookie.match(/(?:^|;\s*)ct0=([^;]+)/) || [])[1];
if (!generator || !bearer) return {missing: !generator ? 'the signature generator' : 'the bearer', explicit: 0, ...(await kit.report(0))};
if (!ct0 || !session.user_id) return {missing: 'a logged-in session', login: true, explicit: 0, ...(await kit.report(0))};
const gate = await kit.gate(name);
if (gate.stopped) return gate;
const before = gate.before;
const switches = session.switches || {};
const features = {};
for (const switchName of def.featureSwitches.concat(args.extra_features || [])) {
  const value = (switches[switchName] || {}).value;
  features[switchName] = value === undefined ? false : value;
}
const path = '/i/api/graphql/' + def.queryId + '/' + name;
const params = new URLSearchParams({variables: JSON.stringify(args.variables || {}), features: JSON.stringify(features)});
if (def.fieldToggles.length) {
  params.set('fieldToggles', JSON.stringify(Object.fromEntries(def.fieldToggles.map(t => [t, !!(args.toggles || {})[t]]))));
}
let transaction;
try { transaction = await generator('x.com', path, 'GET'); } catch (_) { transaction = null; }
if (!transaction) return {missing: 'a transaction id', explicit: 0, ...(await kit.report(0, before))};
const nonce = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
kit.issued.add(nonce);
const headers = {authorization: 'Bearer ' + bearer, 'x-twitter-auth-type': 'OAuth2Session', 'x-csrf-token': ct0,
                 'x-twitter-client-language': session.language || 'en', 'x-twitter-active-user': 'yes',
                 'content-type': 'application/json', 'x-client-transaction-id': transaction};
const used = {source, query_id: def.queryId, features: def.featureSwitches};
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), Math.max(1000, Number(args.timeout_ms) || 45000));
try {
  const response = await kit.fetch0(path + '?' + params.toString() + '#xs-' + nonce,
                                    {method: 'GET', headers, credentials: 'include', signal: controller.signal});
  const text = await response.text();
  const rate = {};
  for (const key of ['limit', 'remaining', 'reset']) {
    const value = response.headers.get('x-rate-limit-' + key);
    if (value !== null) rate['x-rate-limit-' + key] = value;
  }
  return {status: response.status, body: text.slice(0, Number(args.max_body) || 8000000), headers: rate, used, nonce,
          explicit: 1, ...(await kit.report(50, before))};
} catch (error) {
  return {network_error: String(error).slice(0, 200), used, nonce, explicit: 1, ...(await kit.report(50, before))};
} finally {
  clearTimeout(timer);
}
