// reddit-snippet: resolve
await (async () => {
  function safe(value) {
    if (typeof value !== 'string' || !/^https:\/\/www\.reddit\.com\//.test(value) ||
        /[\\\s]/.test(value) || value.split(/[?#]/)[0].includes('%') || value.split(/[?#]/)[0].split('/').some(p => p === '.' || p === '..')) {
      throw new Error('Unsafe Reddit redirect');
    }
    return value;
  }
  const response = await fetch(safe(ARGS.url), {
    method: 'GET', credentials: 'include', redirect: 'manual', headers: {accept: 'application/json'}
  });
  // Python validates the location and budgets every subsequent network hop.
  const received = await response.text();
  const ratelimit = {};
  for (const key of ['used', 'remaining', 'reset']) ratelimit[key] = response.headers.get('x-ratelimit-' + key);
  const envelope = {status: response.status, url: response.url, body: received,
    location: response.headers.get('location'), ratelimit};
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
