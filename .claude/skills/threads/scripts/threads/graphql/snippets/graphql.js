// threads-snippet: graphql
await (async () => {
  // Python sends the registry's current names as ARGS.admitted; this check stands on its own: only a named Query,
  // never anything that names a mutation, and never a name the caller did not admit.
  if (!Array.isArray(ARGS.admitted) || !ARGS.admitted.includes(ARGS.name) || !/^[A-Za-z0-9_]+Query$/.test(ARGS.name) ||
      /Mutation/.test(ARGS.name) || !/^\d+$/.test(ARGS.doc_id)) throw new Error('Unsupported read query');
  const form = {doc_id: ARGS.doc_id, variables: JSON.stringify(ARGS.variables)};
  const body = Object.entries(form).map(([key, value]) => encodeURIComponent(key) + '=' + encodeURIComponent(value)).join('&');
  const response = await fetch('https://www.threads.com/graphql/query', {
    method: 'POST', credentials: 'include', redirect: 'manual', body,
    headers: {'content-type': 'application/x-www-form-urlencoded', 'x-csrftoken': ARGS.csrf,
      'x-ig-app-id': '238260118697367', 'x-fb-friendly-name': ARGS.name,
      'origin': 'https://www.threads.com', 'referer': ARGS.referer}
  });
  const received = await response.text();
  emitEnvelope({status: response.status, url: response.url, body: received, location: response.headers.get('location')});
})();
