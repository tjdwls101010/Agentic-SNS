// facebook-snippet: mine
// Exactly one request; Transport owns pacing, budget, and raw-response classification.
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
const body = await response.text();
const wanted = new Set(ARGS.names || []);
const source = body.replace(/\\\//g, '/');
const queries = [];
const seen = new Set();
const operation = /__d\(\s*["']([A-Za-z0-9_]+)_facebookRelayOperation["']\s*,\s*\[\s*\]\s*,\s*\(?function\s*\([^)]*\)\s*\{\s*[A-Za-z_$][\w$]*\.exports\s*=\s*["'](\d+)["']\s*;?\s*\}/g;
for (const match of source.matchAll(operation)) {
  if (wanted.has(match[1]) && !seen.has(match[1])) {
    seen.add(match[1]);
    queries.push({name: match[1], doc_id: match[2]});
  }
}
// The HTML also lists hundreds of lazy Bootloader assets; only eager tags belong to this route.
const scripts = [...new Set([...source.matchAll(/<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/gi)]
  .map(match => match[1].replace(/&amp;/g, '&'))
  .filter(url => /^https:\/\/static\.(?:[a-z0-9-]+\.)*fbcdn\.net\/rsrc\.php\/[^\s"'<>]+\.js(?:\?|$)/.test(url)))];
const relay_provider_flags = {};
for (const script of body.matchAll(/<script\b[^>]*\btype\s*=\s*["']application\/json["'][^>]*>([\s\S]*?)<\/script>/gi)) {
  let value;
  try {value = JSON.parse(script[1]);} catch (_) {continue;}
  const stack = [value];
  while (stack.length) {
    const item = stack.pop();
    if (!item || typeof item !== 'object') continue;
    for (const [key, child] of Object.entries(item)) {
      if (/^__relay_internal__pv__[A-Za-z0-9_]+relayprovider$/.test(key) &&
          (typeof child === 'boolean' || Number.isInteger(child) ||
           typeof child === 'string' && /^[A-Z][A-Z_]{0,79}$/.test(child))) relay_provider_flags[key] = child;
      if (child && typeof child === 'object') stack.push(child);
    }
  }
}
console.log(JSON.stringify({status: response.status, url: response.url, body, queries, scripts, relay_provider_flags}));
