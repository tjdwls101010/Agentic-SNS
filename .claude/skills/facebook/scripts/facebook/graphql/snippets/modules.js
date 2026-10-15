async (args) => {
  // facebook-snippet: modules
  const load = window['require'];  // the page's module loader; the REPL refuses code that spells its call
  // Which read queries the page has loaded, and their ids. Makes no request.
  const live = {};
  for (const name of args.names) {
    let id = null;
    try {
      const query = load(name + '.graphql');
      if (query && query.params && typeof query.params.id === 'string') id = query.params.id;
    } catch (_) { /* not loaded */ }
    if (!id) {
      try {
        const operation = load(name + '_facebookRelayOperation');
        if (typeof operation === 'string' && /^\d+$/.test(operation)) id = operation;
      } catch (_) { /* not loaded */ }
    }
    live[name] = id;
  }
  return live;
}
