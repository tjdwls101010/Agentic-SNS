const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const browser = path.resolve(__dirname, '../../../.claude/skills/facebook/scripts/browser');
async function snippet(name, args, globals = {}) {
  const output = [];
  const context = vm.createContext({ARGS: args, console: {log: s => output.push(JSON.parse(s))}, ...globals});
  const AsyncFunction = vm.runInContext('(async function(){}).constructor', context);
  await new AsyncFunction(fs.readFileSync(path.join(browser, name + '.js'), 'utf8'))();
  assert.equal(output.length, 1);
  assert.equal(typeof output[0].status, 'number');
  assert.equal(typeof output[0].url, 'string');
  return name === 'mine' ? output[0] : {...JSON.parse(output[0].body), envelope: output[0]};
}
const names = ['CometNewsFeedPaginationQuery', 'ProfileCometTimelineFeedRefetchQuery',
  'ProfileCometAboutAppSectionQuery', 'SearchCometResultsPaginatedResultsQuery',
  'GroupsCometFeedRegularStoriesPaginationQuery', 'CometSinglePostDialogContentQuery'];
test('mine extracts six operation exports and only Facebook script URLs with one awaited fetch', async () => {
  const body = names.map((name, i) => `__d("${name}_facebookRelayOperation",[],(function(t,n,r,o,a,i){a.exports="${101 + i}"}),null);`).join('\n') +
    `__d("Other_facebookRelayOperation",[],function(a){a.exports="999"},null);` +
    '<script src="https://static.xx.fbcdn.net/rsrc.php/v4/a.js?x=1&amp;y=2"></script>' +
    '<script src="https://evil.example/a.js"></script>';
  let calls = 0;
  const result = await snippet('mine', {url: 'https://www.facebook.com/', names}, {fetch: async (url, options) => {
    calls++; assert.equal(options.headers['sec-fetch-mode'], 'navigate');
    return {status: 200, url, text: async () => body};
  }});
  assert.equal(calls, 1);
  assert.equal(result.body, body);
  assert.deepEqual(result.queries, names.map((name, i) => ({name, doc_id: String(101 + i)})));
  assert.deepEqual(result.scripts, ['https://static.xx.fbcdn.net/rsrc.php/v4/a.js?x=1&y=2']);
});

function pageHarness({failEvaluate = false, slowOpen = false, response = null, xhrStatus = 200} = {}) {
  let now = 0;
  let closed = 0;
  const clicked = [];
  const sent = [];
  const form = (name, id) => 'fb_api_req_friendly_name=' + name + '&doc_id=' + id +
    '&fb_dtsg=SECRET&variables=' + encodeURIComponent(JSON.stringify({feedbackID: 'PRIVATE',
      __relay_internal__pv__Examplerelayprovider: true}));
  const clock = {now: () => now};
  const settle = ms => Promise.resolve().then(() => {now += ms;});
  const schedule = (callback, ms) => {settle(ms).then(callback);};
  function XHR() {}
  XHR.prototype.open = function(method, url) {this.url = url;};
  XHR.prototype.abort = function() {if (this.listener) this.listener();};
  XHR.prototype.addEventListener = function(name, fn) {this.listener = fn;};
  XHR.prototype.send = function(body) {sent.push(body); Object.assign(this, {status: xhrStatus, responseURL: 'https://www.facebook.com/api/graphql/', responseText: '{}'}); if (this.listener) this.listener();};
  const dom = vm.createContext({Date: clock, URL, setTimeout: schedule, window: {fetch: async (...args) => {sent.push(args); return response || {status: 200, url: 'https://www.facebook.com/api/graphql/', clone: () => ({text: async () => '{}'})};}},
    XMLHttpRequest: XHR, location: {href: 'https://www.facebook.com/example/posts/123'}, document: {querySelectorAll: () => [
      ['Like', null], ['Reply', null], ['Write a comment', null],
      ['View comments', ['CommentListComponentsRootQuery', '201']],
      ['View more comments', ['CommentsListComponentsPaginationQuery', '202']],
      ['View 2 replies', ['Depth1CommentsListPaginationQuery', '203']],
    ].map(([label, request]) => ({innerText: label, textContent: label,
      getAttribute: () => null, getClientRects: () => [1], disabled: false,
      click() {clicked.push(label); if (request) {
        if (request[1] === '202') {
          const xhr = new XHR();
          xhr.open('POST', '/api/graphql/');
          xhr.send(form(...request));
        } else dom.window.fetch('/api/graphql/', {body: form(...request)}).catch(() => {});
      }}}))}});
  const page = {evaluate: async (fn, arg) => {
    if (failEvaluate) throw Error('SECRET failure');
    dom.argument = arg;
    return vm.runInContext('(' + fn.toString() + ')(argument)', dom);
  }};
  return {globals: {Date: clock, sleep: ms => ms > 1000 ? new Promise(() => {}) : settle(ms),
    openTab: async () => {if (slowOpen) now += 61000; return page;},
    closeTab: async p => {assert.equal(p, page); closed++;}},
    clicked, sent, closed: () => closed, now: () => now};
}
const targets = ['CommentListComponentsRootQuery', 'CommentsListComponentsPaginationQuery', 'Depth1CommentsListPaginationQuery'];
const captureArgs = {url: 'https://www.facebook.com/example/posts/123', targets, request_budget: 4,
  actions: ['open_comments', 'more_comments', 'expand_replies']};
test('capture uses only explicit comment read controls, intercepts fetch and XHR, and closes tab', async () => {
  const h = pageHarness();
  const result = await snippet('capture', captureArgs, h.globals);
  assert.equal(h.closed(), 1);
  assert.deepEqual(h.clicked, ['View comments', 'View more comments', 'View 2 replies']);
  assert.deepEqual(result.queries.map(q => q.doc_id), ['201', '202', '203']);
  assert.equal(result.queries[0].variables.feedbackID, 'PRIVATE');
  assert.equal(JSON.stringify(result).includes('SECRET'), false);
  assert.equal(result.failed, null);
  assert.equal(result.request_count, 4);
  assert.equal(result.count_complete, true);
});
test('capture closes tab on evaluate failure and never reports raw errors', async () => {
  const h = pageHarness({failEvaluate: true});
  const result = await snippet('capture', captureArgs, h.globals);
  assert.equal(h.closed(), 1);
  assert.equal(result.failed, 'capture_failed');
  assert.equal(JSON.stringify(result).includes('SECRET'), false);
});
test('capture rejects write actions before opening a tab', async () => {
  const result = await snippet('capture', {...captureArgs, actions: ['like']},
    {openTab: () => {throw Error('must not open');}});
  assert.equal(result.failed, 'invalid_capture_arguments');
});
test('capture stops after deadline and closes a late opened tab', async () => {
  const h = pageHarness({slowOpen: true});
  const result = await snippet('capture', captureArgs, h.globals);
  assert.equal(result.failed, 'capture_timeout');
  assert.equal(h.closed(), 1);
  assert.deepEqual(h.clicked, []);
});

test('mine tolerates quote/spacing variants but excludes near-match hosts and unrelated exports', async () => {
  const body =
    `__d( '${names[0]}_facebookRelayOperation', [], function (a) { a.exports = '301'; }, null);` +
    `__d('Other_facebookRelayOperation', [], function(a){a.exports='777'}, null);` +
    '"https:\\/\\/static.xx.fbcdn.net\\/rsrc.php\\/v4\\/a.js" ' +
    '"https://static.evilfbcdn.net/rsrc.php/b.js"';
  const result = await snippet('mine', {url: 'https://static.xx.fbcdn.net/rsrc.php/a.js', names: [names[0]]},
    {fetch: async url => ({status: 200, url, text: async () => body})});
  assert.deepEqual(result.queries, [{name: names[0], doc_id: '301'}]);
  assert.deepEqual(result.scripts, []);
});

test('a stalled evaluate hits the 58 second deadline and cleanup finishes by 59 seconds', async () => {
  let now = 0;
  let closed = 0;
  let fireDeadline;
  const resultPromise = snippet('capture', captureArgs, {
    Date: {now: () => now},
    openTab: async () => ({evaluate: () => new Promise(() => {})}),
    closeTab: async () => {closed++;},
    sleep: ms => ms === 58000 ? new Promise(resolve => {fireDeadline = () => {now = 58000; resolve();};})
      : Promise.resolve().then(() => {now += ms;}),
  });
  await Promise.resolve();
  await Promise.resolve();
  fireDeadline();
  const result = await resultPromise;
  assert.equal(result.failed, 'capture_timeout');
  assert.equal(closed, 1);
  assert.ok(now <= 59000);
  assert.equal(result.count_complete, false);
});
test('cleanup failure is explicit and still produces exactly one result', async () => {
  const h = pageHarness();
  h.globals.closeTab = async () => {throw Error('SECRET');};
  const result = await snippet('capture', captureArgs, h.globals);
  assert.equal(result.failed, 'capture_cleanup_failed');
  assert.equal(JSON.stringify(result).includes('SECRET'), false);
});

test('capture rejects unsafe URLs before opening a tab', async () => {
  for (const url of ['https://facebook.com.evil.example/posts/1', 'https://user@facebook.com/posts/1',
    'http://facebook.com/posts/1']) {
    const result = await snippet('capture', {...captureArgs, url}, {openTab: () => {throw Error('must not open');}});
    assert.equal(result.failed, 'invalid_capture_arguments');
  }
});
test('late open completion after the watchdog still closes the acquired tab', async () => {
  let now = 0;
  let opened;
  let fireDeadline;
  let closed = 0;
  const page = {evaluate: () => {throw Error('expired work must stop');}};
  const pending = snippet('capture', captureArgs, {
    Date: {now: () => now},
    openTab: () => new Promise(resolve => {opened = resolve;}),
    closeTab: async p => {assert.equal(p, page); closed++;},
    sleep: () => new Promise(resolve => {fireDeadline = () => {now = 58000; resolve();};}),
  });
  fireDeadline();
  const result = await pending;
  assert.equal(result.failed, 'capture_timeout');
  opened(page);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(closed, 1);
});

for (const [label, status, url, body] of [
  ['rate limit', 429, 'https://www.facebook.com/api/graphql/', '{}'],
  ['checkpoint', 200, 'https://www.facebook.com/checkpoint/', '{}'],
  ['challenge JSON', 200, 'https://www.facebook.com/api/graphql/', '{"challenge_url":"PRIVATE"}'],
]) {
  test('capture reports ' + label + ' and stops further actions', async () => {
    const h = pageHarness({response: {status, url, clone: () => ({text: async () => body})}});
    const result = await snippet('capture', captureArgs, h.globals);
    assert.equal(result.failed, 'capture_blocked');
    assert.equal(result.envelopes.length, 1);
    assert.equal(h.closed(), 1);
    assert.deepEqual(h.clicked, ['View comments']);
    assert.equal(result.envelope.status, status);
  });
}

test('multi-megabyte mining uses small URL-only arguments and preserves failure envelopes', async () => {
  const args = {url: 'https://static.xx.fbcdn.net/rsrc.php/large.js', names};
  const body = 'x'.repeat(2 * 1024 * 1024);
  let calls = 0;
  const result = await snippet('mine', args, {fetch: async url => {
    calls++;
    return {status: 429, url, text: async () => body};
  }});
  assert.ok(JSON.stringify(args).length < 1000);
  assert.equal(calls, 1);
  assert.equal(result.status, 429);
  assert.equal(result.body.length, 2 * 1024 * 1024);
});

test('XHR 429 is reported before attempting reply expansion', async () => {
  const h = pageHarness({xhrStatus: 429});
  const result = await snippet('capture', captureArgs, h.globals);
  assert.equal(result.envelope.status, 429);
  assert.equal(result.failed, 'capture_blocked');
  assert.deepEqual(h.clicked, ['View comments', 'View more comments']);
  assert.equal(h.closed(), 1);
});

test('mine follows eager script tags but not the entire lazy Bootloader catalog', async () => {
  const eager = 'https://static.xx.fbcdn.net/rsrc.php/eager.js';
  const lazy = 'https://static.xx.fbcdn.net/rsrc.php/lazy.js';
  const body = `<script src="${eager}"></script><script src="${eager}"></script>` +
    `<script>var bootloader={asset:"${lazy}"};</script>`;
  const result = await snippet('mine', {url:'https://www.facebook.com/', names},
    {fetch: async url => ({status:200, url, text:async () => body})});
  assert.deepEqual(result.scripts, [eager]);
});

test('mine reads provider values from JSON prefetch metadata, not strings in user content', async () => {
  const flag = '__relay_internal__pv__CurrentClientrelayprovider';
  const decoy = '__relay_internal__pv__UserTextrelayprovider';
  const metadata = {prefetch:{variables:{[flag]:false}}, message:{text:`"${decoy}":true`}};
  const body = '<!doctype html><script type="application/json" data-sjs>' + JSON.stringify(metadata) + '</script>';
  const result = await snippet('mine', {url:'https://www.facebook.com/', names},
    {fetch:async url => ({status:200,url,text:async()=>body})});
  assert.deepEqual(result.relay_provider_flags, {[flag]:false});
});
