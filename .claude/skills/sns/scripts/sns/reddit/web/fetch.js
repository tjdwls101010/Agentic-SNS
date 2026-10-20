// sns-snippet: reddit.fetch
// One GET from the logged-in browser, run in the REPL with the browser's cookies (no tab): args.path (+ args.query) on
// www.reddit.com, or args.url (a share link). It returns the answer as one envelope {status, url, body, location,
// ratelimit: {used, remaining, reset}}; aside/program.js prints it, in chunks when it is large.
async (args) => {
  let target;
  if (typeof args.url === 'string') {
    if (!/^https:\/\/www\.reddit\.com\/[^\s\\?#]*$/.test(args.url) || args.url.split('/').some(p => p === '.' || p === '..')) {
      throw new Error('Unsafe Reddit URL');
    }
    target = args.url;
  } else {
    const path = args.path;
    if (typeof path !== 'string' || !/^\/(?!\/)[A-Za-z0-9_+./-]+$/.test(path) ||
        path.split('/').some(p => p === '..' || p === '.')) throw new Error('Invalid Reddit path');
    const query = Object.entries({...(args.query || {}), raw_json: 1})
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v)).join('&');
    target = 'https://www.reddit.com' + path + '?' + query;
  }
  const response = await fetch(target, {
    method: 'GET', credentials: 'include', redirect: 'manual', headers: {accept: 'application/json'}
  });
  const body = await response.text();
  const ratelimit = {};
  for (const key of ['used', 'remaining', 'reset']) ratelimit[key] = response.headers.get('x-ratelimit-' + key);
  return {status: response.status, url: response.url || target, body, location: response.headers.get('location'), ratelimit};
}
