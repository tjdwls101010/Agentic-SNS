// reddit-snippet: fetch
// One GET from the logged-in browser: ARGS.path (+ ARGS.query) on www.reddit.com, or ARGS.url (a share link). The
// answer is printed as one envelope line; a body large enough to pass the REPL's measured 12 MiB line ceiling goes
// first as body_chunk lines (never splitting a surrogate pair).
await (async () => {
  let target;
  if (typeof ARGS.url === 'string') {
    if (!/^https:\/\/www\.reddit\.com\/[^\s\\?#]*$/.test(ARGS.url) || ARGS.url.split('/').some(p => p === '.' || p === '..')) {
      throw new Error('Unsafe Reddit URL');
    }
    target = ARGS.url;
  } else {
    const path = ARGS.path;
    if (typeof path !== 'string' || !/^\/(?!\/)[A-Za-z0-9_+./-]+$/.test(path) ||
        path.split('/').some(p => p === '..' || p === '.')) throw new Error('Invalid Reddit path');
    const query = Object.entries({...(ARGS.query || {}), raw_json: 1})
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');
    target = 'https://www.reddit.com' + path + '?' + query;
  }
  const response = await fetch(target, {
    method: 'GET', credentials: 'include', redirect: 'manual', headers: {accept: 'application/json'}
  });
  const received = await response.text();
  const ratelimit = {};
  for (const key of ['used', 'remaining', 'reset']) ratelimit[key] = response.headers.get('x-ratelimit-' + key);
  const envelope = {status: response.status, url: response.url || target, body: received,
    location: response.headers.get('location'), ratelimit};
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
