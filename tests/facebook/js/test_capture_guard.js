const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const test = require('node:test');
const source = fs.readFileSync(path.resolve(__dirname, '../../../.claude/skills/facebook/scripts/browser/capture.js'), 'utf8');

async function capture({budget = 4, kind = 'fetch', status = 200, checkpoint = false} = {}) {
  const sent = [], output = [], pending = [];
  let closed = 0;
  const timers = new Set();
  const timer = (fn, ms) => { const id = setTimeout(() => {timers.delete(id); fn();}, ms); timers.add(id); return id; };
  const form = 'fb_api_req_friendly_name=CommentListComponentsRootQuery&doc_id=123&variables=%7B%7D';
  const url = 'https://www.facebook.com/api/graphql/';
  const body = checkpoint ? '{"checkpoint_url":"/checkpoint/"}' : '{}';
  class XHR {
    constructor() {this.listeners = {};}
    open(method, address) {this.address = address;}
    addEventListener(name, fn) {(this.listeners[name] ||= []).push(fn);}
    abort() {this.aborted = true; for (const fn of this.listeners.loadend || []) fn();}
    send() {
      sent.push({kind: 'xhr', at: Date.now()});
      timer(() => {
        Object.assign(this, {status, responseURL: url, responseText: body});
        for (const fn of this.listeners.loadend || []) fn();
      }, 15);
    }
  }
  const dom = vm.createContext({setTimeout: timer, clearTimeout, Date, URL, XMLHttpRequest: XHR,
    location: {href: 'https://www.facebook.com/synthetic/posts/1'},
    window: {fetch: async () => {
      sent.push({kind: 'fetch', at: Date.now()});
      await new Promise(resolve => timer(resolve, 15));
      return {status, url, clone: () => ({text: async () => body})};
    }},
    document: {documentElement: {outerHTML: '<html></html>'}, querySelectorAll: () => [{
      innerText: 'View comments', disabled: false, getAttribute: () => null, getClientRects: () => [1],
      click: () => {for (let i = 0; i < 3; i++) {
        if (kind === 'xhr' || (kind === 'mixed' && i === 1)) {const request = new XHR(); request.open('POST', url); request.send(form);}
        else pending.push(dom.window.fetch(url, {body: form}).catch(() => {}));
      }}
    }]}});
  const page = {evaluate: async (fn, arg) => {
    dom.argument = arg;
    return vm.runInContext('(' + fn.toString() + ')(argument)', dom);
  }};
  const context = vm.createContext({ARGS: {url: 'https://www.facebook.com/synthetic/posts/1',
    targets: ['CommentListComponentsRootQuery'], actions: ['open_comments'], request_budget: budget},
    Date, sleep: ms => new Promise(resolve => timer(resolve, ms)),
    openTab: async () => page, closeTab: async () => {closed++;}, console: {log: text => output.push(JSON.parse(text))}});
  try {
    const AsyncFunction = vm.runInContext('(async function(){}).constructor', context);
    await new AsyncFunction(source)();
    await Promise.all(pending);
    assert.equal(closed, 1);
    assert.equal(output.length, 1);
    return {sent, envelope: output[0], result: JSON.parse(output[0].body)};
  } finally {for (const id of timers) clearTimeout(id);}
}

for (const kind of ['fetch', 'xhr']) {
  test(`${kind}: budget one permits only bootstrap navigation`, async () => {
    const {sent, result} = await capture({budget: 1, kind});
    assert.equal(sent.length, 0);
    assert.equal(result.request_count, 1);
  });
  test(`${kind}: queued GraphQL requests are counted and paced`, async () => {
    const {sent, result} = await capture({kind});
    assert.equal(sent.length, 3);
    assert.equal(result.request_count, 4);
    assert.ok(sent[1].at - sent[0].at >= 1000);
    assert.ok(sent[2].at - sent[1].at >= 1000);
  });
  test(`${kind}: first 429 prevents every queued dispatch`, async () => {
    const {sent, result, envelope} = await capture({kind, status: 429});
    assert.equal(sent.length, 1);
    assert.equal(result.request_count, 2);
    assert.equal(envelope.status, 429);
    assert.equal(result.envelopes[0].status, 429);
  });
}
test('checkpoint is observed before the next queued request', async () => {
  const {sent, result, envelope} = await capture({checkpoint: true});
  assert.equal(sent.length, 1);
  assert.equal(result.request_count, 2);
  assert.match(envelope.url, /checkpoint/);
});

test('fetch and XHR share a single queue and the remaining budget', async () => {
  const {sent, result} = await capture({kind: 'mixed', budget: 3});
  assert.deepEqual(sent.map(request => request.kind), ['fetch', 'xhr']);
  assert.ok(sent[1].at - sent[0].at >= 1000);
  assert.equal(result.request_count, 3);
  assert.equal(result.failed, 'capture_budget');
  assert.equal(result.count_complete, true);
});
test('checkpoint takes precedence when a 429 body also contains a challenge', async () => {
  const {sent, result, envelope} = await capture({status: 429, checkpoint: true});
  assert.equal(sent.length, 1);
  assert.match(envelope.url, /checkpoint/);
  assert.ok(result.checkpoint_url);
});
test('stalled capture stops by 59 seconds, closes the tab, and marks its count incomplete', async () => {
  let now = 0, closed = 0, expire;
  const output = [];
  const context = vm.createContext({ARGS: {url: 'https://www.facebook.com/synthetic/posts/1',
    targets: ['CommentListComponentsRootQuery'], request_budget: 3},
    Date: {now: () => now},
    openTab: async () => ({evaluate: () => new Promise(() => {})}),
    closeTab: async () => {closed++;},
    sleep: ms => ms === 58000 ? new Promise(resolve => {expire = () => {now = 58000; resolve();};})
      : Promise.resolve().then(() => {now += ms;}),
    console: {log: text => output.push(JSON.parse(text))}});
  const AsyncFunction = vm.runInContext('(async function(){}).constructor', context);
  const running = new AsyncFunction(source)();
  await Promise.resolve();
  await Promise.resolve();
  expire();
  await running;
  assert.equal(closed, 1);
  assert.ok(now <= 59000);
  const result = JSON.parse(output[0].body);
  assert.equal(result.failed, 'capture_timeout');
  assert.equal(result.count_complete, false);
});
