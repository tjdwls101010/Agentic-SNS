const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../../.claude/skills/threads/scripts/threads/aside/envelope.js'), 'utf8');

function emit(envelope) {
  const logs = [];
  vm.runInNewContext(source + '\nemitEnvelope(ENVELOPE);', {ENVELOPE: envelope, Buffer,
    console: {log: text => logs.push(JSON.parse(text))}});
  return logs;
}

test('a small response is one envelope line', () => {
  const logs = emit({status: 200, url: 'https://www.threads.com/', body: 'synthetic', location: null});
  assert.deepEqual(logs, [{status: 200, url: 'https://www.threads.com/', body: 'synthetic', location: null}]);
});

test('a large escaped response arrives as ordered chunks that rebuild it exactly', () => {
  const body = '"😀'.repeat(1600000);
  const logs = emit({status: 200, url: 'https://www.threads.com/', body, location: null});
  const envelope = logs.pop();
  assert.equal(envelope.body, '');
  assert.equal(envelope.body_chunks, logs.length);
  assert.ok(logs.length > 1);
  assert.equal(logs.map((record, index) => {assert.equal(record.index, index); return record.body;}).join(''), body);
});
