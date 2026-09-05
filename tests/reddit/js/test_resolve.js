const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
async function run(url, locations) {
  const source = fs.readFileSync(path.join(__dirname, '../../../.claude/skills/reddit/scripts/browser/resolve.js'), 'utf8');
  const calls = [], logs = [];
  const promise = vm.runInNewContext('(async()=>{' + source + '})()', {
    ARGS: {url}, Buffer, console: {log: x => logs.push(JSON.parse(x))},
    fetch: async (url, options) => {
      assert.equal(options.redirect, 'manual');
      const location = locations[calls.length];
      calls.push(url);
      return {status: location ? 302 : 200, url,
        headers: {get: k => k === 'location' ? location : k === 'x-ratelimit-remaining' ? '0' : null}, text: async () => 'ok'};
    }
  });
  return {promise, calls, logs};
}
test('one hop exposes redirect and rate headers without following it', async () => {
  const result = await run('https://www.reddit.com/r/python/s/abc', ['/comments/abc']);
  await result.promise;
  assert.equal(result.calls.length, 1);
  assert.equal(result.logs[0].status, 302);
  assert.equal(result.logs[0].location, '/comments/abc');
  assert.equal(result.logs[0].url, 'https://www.reddit.com/r/python/s/abc');
  assert.equal(result.logs[0].ratelimit.remaining, '0');
});
test('unsafe initial URLs are refused; redirects are exposed without following', async () => {
  const bad = ['https://evil.com/x', 'http://www.reddit.com/x', 'https://www.reddit.com:443/x',
    'https://user@www.reddit.com/x', 'https://www.reddit.com.evil/x', '//evil.com/x',
    'https://www.reddit.com/\\evil.com/x', 'https://www.reddit.com/%2f%2fevil.com'];
  for (const url of bad) {
    const initial = await run(url, []);
    await assert.rejects(initial.promise);
    assert.equal(initial.calls.length, 0);
    const redirect = await run('https://www.reddit.com/r/python/s/abc', [url]);
    await redirect.promise;
    assert.equal(redirect.calls.length, 1);
    assert.equal(redirect.logs[0].location, url);
  }
});
test('encoded tracking query is safe while encoded path escapes are refused', async () => {
  const result = await run('https://www.reddit.com/r/python/s/abc?utm_source=a%20b',
    ['/comments/abc?utm_source=a%20b']);
  await result.promise;
  assert.equal(result.calls.length, 1);
  assert.equal(result.logs[0].location, '/comments/abc?utm_source=a%20b');
});
