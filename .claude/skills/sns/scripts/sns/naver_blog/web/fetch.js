// sns-snippet: naver_blog.fetch
// One GET on the read surface, sent with the REPL's own fetch (the browser's cookies and user agent), a referer per
// host and no redirect followed. args = {host, path, query, accept}: query is an object the snippet form-encodes.
// It returns one envelope, which aside/program.js prints: {status, url, location, content_type, body, b64} (b64 for
// an image only; oversize instead of b64 when a picture is over 10 MB), or {error: 'refused'|'network', message}.
async (args) => {
  // routes:begin (the same table as routes.ROUTES; a test compares them)
  const ROUTES = {
    "m.blog.naver.com": [
      "^/api/current\\-user$",
      "^/api/search/v1/post$",
      "^/api/search/v2/blog$",
      "^/api/search/v1/moment$",
      "^/api/tags/search/post$",
      "^/api/v1/popular\\-keywords$",
      "^/api/related\\-keywords$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/contents\\-count$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/category\\-list$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/post\\-list$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/popular\\-post\\-list$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/notice\\-post\\-list$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/search/post$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/search/tag$",
      "^/PostView\\.naver$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/posts/[0-9]{1,40}/sympathy\\-users$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/v1/category\\-related\\-posts$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/posts/[0-9]{1,40}/comments\\-info$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/feed/v1$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/buddy\\-groups$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/my\\-buddies$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/me\\-buddies$",
      "^/api/blogs/[A-Za-z0-9_-]{1,64}/public\\-buddies$",
      "^/api/thismonthblog/year\\-month\\-list$",
      "^/api/thismonthblog/directory\\-blogid\\-list$",
      "^/api/blogs/profiles/profile\\-relation\\-list$",
      "^/api/blogs/posts/popular\\-post\\-list$"
    ],
    "apis.naver.com": [
      "^/commentBox/cbox/web_naver_list_json\\.json$"
    ],
    "section.blog.naver.com": [
      "^/ajax/DirectoryList\\.naver$",
      "^/ajax/DirectoryPostList\\.naver$",
      "^/ajax/DirectoryTopPostList\\.naver$"
    ],
    "blog.naver.com": [
      "^/[A-Za-z0-9_-]{1,64}$"
    ],
    "naver.me": [
      "^/[A-Za-z0-9]{1,32}$"
    ],
    "*.pstatic.net": [
      "^/[A-Za-z0-9._~%/-]{0,512}$"
    ]
  };
  // routes:end
  const IMAGE_SUFFIX = '.pstatic.net';
  const IMAGE_LIMIT = 10 * 1024 * 1024;
  const REFERER = {
    'm.blog.naver.com': 'https://m.blog.naver.com/',
    'section.blog.naver.com': 'https://section.blog.naver.com/',
    'apis.naver.com': 'https://m.blog.naver.com/',
    'blog.naver.com': 'https://blog.naver.com/'
  };
  const ACCEPT = {
    json: 'application/json, text/plain, */*',
    html: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    image: 'image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8'
  };
  const refuse = (message) => ({error: 'refused', message});
  const {host, path, query, accept} = args;
  const imageHost = typeof host === 'string' && host.endsWith(IMAGE_SUFFIX) && /^[a-z0-9-]+(\.[a-z0-9-]+)*$/.test(host);
  const patterns = Object.prototype.hasOwnProperty.call(ROUTES, host) ? ROUTES[host]
    : (imageHost ? ROUTES['*' + IMAGE_SUFFIX] : null);
  if (!patterns) return refuse('host');
  // Traversal is refused before matching: fetch() would normalize "/api/../PostWrite.naver" on its way out.
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || /\.\.|\\|%2e|%2f|%5c/i.test(path)
      || !patterns.some((pattern) => new RegExp(pattern).test(path))) return refuse('path');
  if (query !== undefined && query !== null && (typeof query !== 'object' || Array.isArray(query)
      || Object.values(query).some((v) => !['string', 'number', 'boolean'].includes(typeof v)))) return refuse('query');
  if (!Object.prototype.hasOwnProperty.call(ACCEPT, accept) || (accept === 'image') !== Boolean(imageHost)) return refuse('accept');
  const headers = {'accept': ACCEPT[accept], 'accept-language': 'ko-KR,ko;q=0.9,en;q=0.8'};
  if (REFERER[host]) headers['referer'] = REFERER[host];
  // Form-encoded like the Python side (a space is +), key order kept.
  const encode = (value) => encodeURIComponent(String(value)).replace(/%20/g, '+');
  const encoded = Object.entries(query || {}).map(([k, v]) => encode(k) + '=' + encode(v)).join('&');
  const url = 'https://' + host + path + (encoded ? '?' + encoded : '');
  let response;
  try {
    response = await fetch(url, {method: 'GET', credentials: 'include', redirect: 'manual', headers});
  } catch (error) {
    return {error: 'network', message: String(error && error.message || error).slice(0, 200)};
  }
  const base = {status: response.status, url: response.url || url, location: response.headers.get('location'),
                content_type: response.headers.get('content-type')};
  if (accept === 'image') {
    const declared = Number(response.headers.get('content-length') || 0);
    if (declared > IMAGE_LIMIT) return {...base, body: '', b64: null, oversize: declared};
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > IMAGE_LIMIT) return {...base, body: '', b64: null, oversize: bytes.length};
    return {...base, body: '', b64: bytes.toString('base64')};
  }
  return {...base, body: await response.text(), b64: null};
}
