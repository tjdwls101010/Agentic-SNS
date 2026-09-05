const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../../.claude/skills/reddit/scripts/browser/fetch.js'), 'utf8');
async function run(args, response = {}) {
  const calls = [], logs = [];
  await vm.runInNewContext('(async()=>{' + source + '})()', {
    ARGS: args, Buffer, console: {log: x => logs.push(JSON.parse(x))},
    fetch: async (url, options) => {
      calls.push({url, options});
      return {status: response.status || 200, url, headers: {get: key => ({
        'x-ratelimit-used': '100', 'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '12',
        location: '/user/example/saved.json'
      })[key] || null}, text: async () => response.body || '{}'};
    }
  });
  return {calls, logs};
}
test('fetch uses fixed origin, raw_json, GET and manual redirects', async () => {
  const {calls, logs} = await run({path: '/search.json', query: {q: 'a & b', raw_json: 0}}, {status: 302});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://www.reddit.com/search.json?q=a%20%26%20b&raw_json=1');
  assert.equal(calls[0].options.method, 'GET');
  assert.equal(calls[0].options.redirect, 'manual');
  assert.equal(logs[0].status, 302);
  assert.equal(logs[0].ratelimit.remaining, '0');
  assert.equal(logs[0].location, '/user/example/saved.json');
});
test('fetch refuses full URLs and path escapes before network', async () => {
  for (const p of ['https://evil.com/x', '//evil.com/x', '/a/../x.json', '/%2e%2e/x.json', '/x\\a.json', '/x.json?q=x']) {
    await assert.rejects(run({path: p}));
  }
  await assert.rejects(run({url: 'https://www.reddit.com/hot.json'}));
});
test('large escaped Unicode bodies survive chunk emission', async () => {
  const body = '\u0000😀'.repeat(1500000);
  const {logs} = await run({path: '/hot.json'}, {body});
  assert.ok(logs.length > 2);
  assert.equal(logs.at(-1).body_chunks, logs.length - 1);
  assert.equal(logs.slice(0, -1).map(x => x.body).join(''), body);
  assert.ok(logs.every(x => Buffer.byteLength(JSON.stringify(x)) < 12 * 1024 * 1024));
});
