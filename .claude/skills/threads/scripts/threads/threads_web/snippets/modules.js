// threads-snippet: modules
// Which read queries the tab has loaded right now, with their ids and whether each is a query. Makes no request.
const load = window['req' + 'uire'];
const live = {};
for (const name of args.names || []) {
  let found = null;
  for (const suffix of ['.threads.graphql', '.graphql']) {
    try {
      const params = load(name + suffix).params;
      if (params && /^\d+$/.test(String(params.id))) { found = {doc_id: String(params.id), kind: params.operationKind}; break; }
    } catch (_) { /* not loaded */ }
  }
  if (!found) {
    try { const id = load(name + '_threadsRelayOperation'); if (typeof id === 'string' && /^\d+$/.test(id)) found = {doc_id: id, kind: null}; } catch (_) {}
  }
  live[name] = found;
}
return {live, ...(await kit.report(0))};
