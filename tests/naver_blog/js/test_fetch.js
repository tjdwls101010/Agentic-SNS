// The real snippet runs against a mock fetch: what it refuses is the reading surface.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SNIPPET = fs.readFileSync(
  path.join(__dirname, '../../../.claude/skills/naver-blog/scripts/browser/fetch.js'), 'utf8');

async function runSnippet(args, response = {}) {
  const calls = [];
  const logs = [];
  const context = {
    ARGS: args,
    console: {log: line => logs.push(line)},
    fetch: async (url, init) => {
      calls.push({url, init});
      return {
        status: response.status ?? 200,
        url: response.finalUrl ?? url,
        headers: {get: name => (response.headers || {})[name] ?? null},
        text: async () => response.body ?? '{"isSuccess":true}'
      };
    }
  };
  vm.createContext(context);
  await vm.runInContext(`(async () => {\n${SNIPPET}\n})()`, context);
  return {calls, logs};
}

test('a request goes to the asked-for host and path with its query attached', async () => {
  const {calls, logs} = await runSnippet(
    {host: 'm.blog.naver.com', path: '/api/search/v1/post', query: 'keyword=%ED%8C%8C%EC%9D%B4%EC%8D%AC&page=1'});
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].url,
    'https://m.blog.naver.com/api/search/v1/post?keyword=%ED%8C%8C%EC%9D%B4%EC%8D%AC&page=1');
  const envelope = JSON.parse(logs[logs.length - 1]);
  assert.strictEqual(envelope.status, 200);
});

test('every request is a GET; the snippet offers no other method', async () => {
  const {calls} = await runSnippet({host: 'm.blog.naver.com', path: '/api/blogs/x'});
  assert.strictEqual(calls[0].init.method, 'GET');
  assert.ok(!('body' in calls[0].init));
  assert.strictEqual(calls[0].init.credentials, 'include');
  assert.strictEqual(calls[0].init.redirect, 'manual');
});

test('each host carries its own fixed referer, which is the whole header contract', async () => {
  const expected = {
    'm.blog.naver.com': 'https://m.blog.naver.com/',
    'section.blog.naver.com': 'https://section.blog.naver.com/',
    'apis.naver.com': 'https://m.blog.naver.com/',
    'blog.naver.com': 'https://blog.naver.com/'
  };
  const paths = {
    'm.blog.naver.com': '/api/blogs/x',
    'section.blog.naver.com': '/ajax/DirectoryList.naver',
    'apis.naver.com': '/commentBox/cbox/web_naver_list_json.json',
    'blog.naver.com': '/naverofficial'
  };
  for (const [host, referer] of Object.entries(expected)) {
    const {calls} = await runSnippet({host, path: paths[host]});
    assert.strictEqual(calls[0].init.headers.referer, referer, host);
  }
});

test('a host outside the four is refused before any request', async () => {
  for (const host of ['example.com', 'cafe.naver.com', 'news.naver.com', 'nid.naver.com', '']) {
    await assert.rejects(runSnippet({host, path: '/api/blogs/x'}), /Unsupported host/, host);
  }
});

test('a path outside each host allowlist is refused before any request', async () => {
  const refused = [
    ['m.blog.naver.com', '/PostWrite.naver'],
    ['m.blog.naver.com', '/api'],
    ['section.blog.naver.com', '/BuddyPostList.naver'],
    ['apis.naver.com', '/commentBox/cbox/web_naver_create_json.json'],
    ['blog.naver.com', '/naverofficial/224400531915']
  ];
  for (const [host, p] of refused) {
    await assert.rejects(runSnippet({host, path: p}), /Unsupported reading route/, `${host}${p}`);
  }
});

test('a query may not smuggle a fragment or a backslash past the path check', async () => {
  await assert.rejects(runSnippet({host: 'm.blog.naver.com', path: '/api/blogs/x', query: 'a=1#/../evil'}),
    /Unsupported query/);
  await assert.rejects(runSnippet({host: 'm.blog.naver.com', path: '/api/blogs/x', query: 'a=1\\2'}),
    /Unsupported query/);
});

test('a redirect is reported in the envelope rather than followed', async () => {
  const {logs} = await runSnippet(
    {host: 'blog.naver.com', path: '/naver_diary'},
    {status: 302, headers: {location: '/NBlogTop.naver?blogId=naverofficial'}, body: ''});
  const envelope = JSON.parse(logs[logs.length - 1]);
  assert.strictEqual(envelope.status, 302);
  assert.strictEqual(envelope.location, '/NBlogTop.naver?blogId=naverofficial');
});

test('html reads ask for html and json reads do not', async () => {
  const html = await runSnippet({host: 'm.blog.naver.com', path: '/PostView.naver', accept: 'html'});
  assert.match(html.calls[0].init.headers.accept, /text\/html/);
  const json = await runSnippet({host: 'm.blog.naver.com', path: '/api/blogs/x'});
  assert.match(json.calls[0].init.headers.accept, /application\/json/);
});
