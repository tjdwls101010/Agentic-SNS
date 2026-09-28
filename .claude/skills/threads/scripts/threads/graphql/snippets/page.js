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
  emitEnvelope({status: response.status, url: response.url, body: received, location: response.headers.get('location')});
})();
