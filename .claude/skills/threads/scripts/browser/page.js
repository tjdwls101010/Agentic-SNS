// threads-snippet: page
await (async () => {
  if (typeof ARGS.path !== 'string' || !/^\/(?:|search|liked\/?|saved\/?|@[A-Za-z0-9_.]+(?:\/(?:threads|replies|reposts|media|post\/[A-Za-z0-9_-]+))?\/?|t\/[A-Za-z0-9_-]+\/?)(?:\?[^#\\]*)?$/.test(ARGS.path)) throw new Error('Unsupported reading route');
  const response = await fetch('https://www.threads.com' + ARGS.path, {
    method: 'GET', credentials: 'include', redirect: 'manual',
    headers: {
      'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
      'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'accept-language': 'en-US,en;q=0.9',
      'sec-fetch-dest': 'document', 'sec-fetch-mode': 'navigate', 'sec-fetch-site': 'none',
      'upgrade-insecure-requests': '1'
    }
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
