// sns-snippet: facebook.modules
// Which read queries the page has loaded, and their ids. Makes no request.
const live = {};
for (const name of args.names) {
  let id = null;
  try {
    const query = kit.load(name + '.graphql');
    if (query && query.params && typeof query.params.id === 'string') id = query.params.id;
  } catch (_) { /* not loaded */ }
  if (!id) {
    try {
      const operation = kit.load(name + '_facebookRelayOperation');
      if (typeof operation === 'string' && /^\d+$/.test(operation)) id = operation;
    } catch (_) { /* not loaded */ }
  }
  live[name] = id;
}
return live;
