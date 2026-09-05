const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../../../.claude/skills/threads/scripts/browser');

async function run(name, args, response = {}) {
  const calls = [], logs = [];
  const source = fs.readFileSync(path.join(root, name + '.js'), 'utf8');
  await vm.runInNewContext('(async()=>{' + source + '})()', {
    ARGS: args, URL, URLSearchParams, Buffer,
    console: {log: text => logs.push(JSON.parse(text))},
    fetch: async (url, options) => {
      calls.push({url, options});
      return {status: response.status || 200, url,
        headers: {get: key => key === 'location' ? response.location || null : null},
        text: async () => response.body || '{}'};
    }
  });
  return {calls, logs};
}

test('page sends navigation headers and leaves each redirect to the budgeted caller', async () => {
  const {calls, logs} = await run('page', {path: '/@fixture'}, {status: 302, location: '/@other'});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://www.threads.com/@fixture');
  assert.equal(calls[0].options.redirect, 'manual');
  assert.equal(calls[0].options.headers['sec-fetch-mode'], 'navigate');
  assert.equal(Object.keys(calls[0].options.headers).length, 7);
  assert.equal(logs[0].location, '/@other');
});

test('graphql form has exactly two fields and credentials are headers only', async () => {
  const {calls} = await run('graphql', {name: 'BarcelonaFeedDirectQuery', doc_id: '123', variables: {after: null}, csrf: 'fixture', referer: 'https://www.threads.com/'});
  const form = new URLSearchParams(calls[0].options.body);
  assert.deepEqual([...form.keys()].sort(), ['doc_id', 'variables']);
  assert.equal(calls[0].options.headers['x-csrftoken'], 'fixture');
  assert.equal(calls[0].options.redirect, 'manual');
});

test('page and query reject out-of-scope traffic before fetch', async () => {
  await assert.rejects(run('page', {path: '//evil.test/'}));
  await assert.rejects(run('page', {path: '/activity'}));
  await assert.rejects(run('graphql', {name: 'WriteMutation', doc_id: '123', variables: {}}));
});

test('large escaped response survives ordered chunk transfer', async () => {
  const body = '"😀'.repeat(1600000);
  const {logs} = await run('page', {path: '/'}, {body});
  const envelope = logs.pop();
  assert.equal(envelope.body_chunks, logs.length);
  assert.equal(logs.map((r, i) => {assert.equal(r.index, i); return r.body;}).join(''), body);
});
