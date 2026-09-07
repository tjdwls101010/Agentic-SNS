// naver-blog-snippet: fetch
// GET only, four hosts, a fixed referer per host. Naver needs no token, so nothing else is sent.
await (async () => {
  const ALLOWED = {
    'm.blog.naver.com': [/^\/api\//, /^\/PostView\.naver$/, /^\/FeedList\.naver$/],
    'section.blog.naver.com': [/^\/ajax\//],
    'apis.naver.com': [/^\/commentBox\/cbox\/web_naver_list_json\.json$/],
    'blog.naver.com': [/^\/NBlogTop\.naver$/, /^\/[A-Za-z0-9_-]+$/]
  };
  const REFERER = {
    'm.blog.naver.com': 'https://m.blog.naver.com/',
    'section.blog.naver.com': 'https://section.blog.naver.com/',
    'apis.naver.com': 'https://m.blog.naver.com/',
    'blog.naver.com': 'https://blog.naver.com/'
  };
  const host = ARGS.host;
  const path = ARGS.path;
  if (typeof host !== 'string' || !Object.prototype.hasOwnProperty.call(ALLOWED, host)) throw new Error('Unsupported host');
  if (typeof path !== 'string' || !ALLOWED[host].some(pattern => pattern.test(path))) throw new Error('Unsupported reading route');
  if (ARGS.query !== undefined && (typeof ARGS.query !== 'string' || /[#\\]/.test(ARGS.query))) throw new Error('Unsupported query');
  const accept = ARGS.accept === 'html'
    ? 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    : 'application/json, text/plain, */*';
  const url = 'https://' + host + path + (ARGS.query ? '?' + ARGS.query : '');
  const response = await fetch(url, {
    method: 'GET', credentials: 'include', redirect: 'manual',
    headers: {
      'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
      'accept': accept,
      'accept-language': 'ko-KR,ko;q=0.9,en;q=0.8',
      'referer': REFERER[host]
    }
  });
  const received = await response.text();
  console.log(JSON.stringify({
    status: response.status, url: response.url, body: received,
    location: response.headers.get('location')
  }));
})();
