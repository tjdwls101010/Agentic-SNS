// facebook-snippet: page
await (async () => {
  const response = await fetch(ARGS.url, {
    method: 'GET', credentials: 'include',
    headers: {
      'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
      'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'accept-language': 'en-US,en;q=0.9',
      'sec-fetch-dest': 'document', 'sec-fetch-mode': 'navigate', 'sec-fetch-site': 'none',
      'upgrade-insecure-requests': '1'
    }
  });
  console.log(JSON.stringify({status: response.status, url: response.url, body: await response.text()}));
})();
