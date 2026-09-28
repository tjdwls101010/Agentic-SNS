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
  const envelope = {status: response.status, url: response.url, body: received, location: response.headers.get('location')};
  // Keep each log line below the measured 12 MiB ceiling without writing personal data to disk.
  if (received.length > 1000000 && Buffer.byteLength(JSON.stringify(envelope)) > 8 * 1024 * 1024) {
    let index = 0;
    for (let offset = 0; offset < received.length;) {
      let end = Math.min(offset + 512 * 1024, received.length);
      const last = received.charCodeAt(end - 1);
      if (end < received.length && last >= 0xD800 && last <= 0xDBFF) end--;
      console.log(JSON.stringify({kind: 'body_chunk', index: index++, body: received.slice(offset, end)}));
      offset = end;
    }
    envelope.body = '';
    envelope.body_chunks = index;
  }
  console.log(JSON.stringify(envelope));
})();
