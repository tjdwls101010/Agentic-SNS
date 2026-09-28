const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const scripts = path.resolve(__dirname, '../../../.claude/skills/threads/scripts/threads');
const cases = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../fixtures/route_cases.json'), 'utf8'));

async function visit(route) {
  const source = fs.readFileSync(path.join(scripts, 'aside/envelope.js'), 'utf8') + '\n' +
    fs.readFileSync(path.join(scripts, 'graphql/snippets/page.js'), 'utf8');
  const calls = [];
  await vm.runInNewContext('(async()=>{' + source + '})()', {
    ARGS: {path: route}, Buffer, console: {log: () => {}},
    fetch: async url => { calls.push(url); return {status: 200, url, headers: {get: () => null}, text: async () => ''}; }
  });
  return calls;
}

for (const route of cases.allowed) {
  test(`page.js reads ${route}`, async () => assert.equal((await visit(route)).length, 1));
}
for (const route of cases.refused) {
  test(`page.js refuses ${route}`, async () => assert.rejects(visit(route)));
}
