const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const browser = path.resolve(__dirname, '../../../.claude/skills/facebook/scripts/browser');

async function run(name, args) {
  const calls = [], output = [];
  const context = {ARGS: args, console: {log: text => output.push(JSON.parse(text))},
    fetch: async (url, options) => {
      await new Promise(resolve => setImmediate(resolve));
      calls.push({url, ...options});
      return {status: 200, url: 'https://www.facebook.com/final', text: async () => '한글 & +'};
    }};
  // Aside wraps source in an AsyncFunction; it does not await an expression's result.
  const AsyncFunction = vm.runInNewContext('(async function () {}).constructor', context);
  await new AsyncFunction(fs.readFileSync(path.join(browser, name + '.js'), 'utf8'))();
  assert.equal(calls.length, 1);
  assert.deepEqual(output, [{status: 200, url: 'https://www.facebook.com/final', body: '한글 & +'}]);
  return calls[0];
}

test('home and page use navigation headers and one fetch', async () => {
  for (const name of ['tokens', 'page']) {
    const call = await run(name, {url: 'https://www.facebook.com/성진?q=a&b=+'});
    assert.equal(call.url, name === 'tokens' ? 'https://www.facebook.com/' : 'https://www.facebook.com/성진?q=a&b=+');
    assert.equal(call.headers['sec-fetch-mode'], 'navigate');
    assert.equal(call.headers['sec-fetch-dest'], 'document');
    assert.equal(call.headers['sec-fetch-site'], 'none');
    assert.equal(call.headers['upgrade-insecure-requests'], '1');
    assert.match(call.headers.accept, /text\/html/);
    assert.ok(call.headers['user-agent']);
    assert.ok(call.headers['accept-language']);
  }
});

test('GraphQL preserves &, + and Korean through form encoding', async () => {
  const tokens = {user_id: '123', fb_dtsg: 'a&+한', lsd: 'b+&글', jazoest: '254798', __spin_r: '456', __rev: '456'};
  const variables = {text: '서울 & 부산 + cafe', count: 3};
  const call = await run('graphql', {tokens, variables, name: 'TestQuery', doc_id: '789', referer: 'https://www.facebook.com/me'});
  assert.equal(call.url, 'https://www.facebook.com/api/graphql/');
  assert.equal(call.method, 'POST');
  const form = new URLSearchParams(call.body);
  for (const key of ['fb_dtsg', 'lsd', 'jazoest', '__spin_r', '__rev']) assert.equal(form.get(key), tokens[key]);
  for (const [key, value] of Object.entries({av: '123', __user: '123', __a: '1', __comet_req: '15', server_timestamps: 'true', fb_api_caller_class: 'RelayModern', fb_api_req_friendly_name: 'TestQuery', doc_id: '789'})) assert.equal(form.get(key), value);
  assert.deepEqual(JSON.parse(form.get('variables')), variables);
  assert.equal(call.headers['x-fb-lsd'], tokens.lsd);
  assert.equal(call.headers['x-fb-friendly-name'], 'TestQuery');
  assert.equal(call.headers.origin, 'https://www.facebook.com');
  assert.equal(call.headers.referer, 'https://www.facebook.com/me');
  assert.equal(call.headers['content-type'], 'application/x-www-form-urlencoded');
  assert.equal(call.headers['sec-fetch-mode'], 'cors');
  assert.equal(call.headers['sec-fetch-site'], 'same-origin');
  assert.equal(call.headers['sec-fetch-dest'], 'empty');
  assert.equal(call.headers.accept, '*/*');
  assert.ok(call.headers['user-agent']);
});

test('large GraphQL responses use ordered small stdout chunks without filesystem access', async () => {
  const output = [];
  const text = 'a'.repeat(512 * 1024 - 1) + '😀' + '한'.repeat(3_000_000);
  const context = {ARGS: {tokens: {}, variables: {}, name: 'ReadQuery', doc_id: '1', response_file: '/project/private/body.ndjson'},
    Buffer,
    console: {log: value => output.push(JSON.parse(value))},
    fetch: async () => ({status: 200, url: 'https://www.facebook.com/api/graphql/', text: async () => text})};
  const AsyncFunction = vm.runInNewContext('(async function () {}).constructor', context);
  await new AsyncFunction(fs.readFileSync(path.join(browser, 'graphql.js'), 'utf8'))();
  const envelope = output.pop();
  assert.equal(envelope.body_chunks, output.length);
  assert.equal(envelope.body, '');
  assert.equal(output.map(chunk => chunk.body).join(''), text);
  for (const [index, chunk] of output.entries()) {
    assert.equal(chunk.kind, 'body_chunk');
    assert.equal(chunk.index, index);
    const last = chunk.body.charCodeAt(chunk.body.length - 1);
    assert.ok(last < 0xD800 || last > 0xDBFF, 'a UTF-16 surrogate pair must not cross envelopes');
    assert.ok(Buffer.byteLength(JSON.stringify(chunk)) < 12 * 1024 * 1024);
  }
});
