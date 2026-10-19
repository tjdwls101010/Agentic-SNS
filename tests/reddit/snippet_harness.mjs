// Run the skill's real fetch snippet under Node with a fake fetch and record what it would send and print.
//
//   node snippet_harness.mjs <case.json>
//
// case: {"snippet": "<path to fetch.js>", "args": {...}, "response": {"status", "url", "body" | "body_repeat": [text, n],
//        "headers": {...}}}. Prints one JSON line: {"fetches": [{url, method, credentials, redirect, headers}],
//        "lines": [what the snippet printed], "error": message when it threw}.
import fs from 'node:fs';
import vm from 'node:vm';

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const fetches = [], lines = [];
const response = spec.response || {status: 200, body: '{}'};
const body = response.body_repeat ? response.body_repeat[0].repeat(response.body_repeat[1]) : (response.body ?? '');
const context = vm.createContext({
  fetch: async (url, init = {}) => {
    fetches.push({url, method: init.method || 'GET', credentials: init.credentials || null,
                  redirect: init.redirect || null, headers: init.headers || {}});
    const headers = response.headers || {};
    return {status: response.status ?? 200, url: response.url ?? url, text: async () => body,
            headers: {get: (k) => (k.toLowerCase() in headers ? headers[k.toLowerCase()] : null)}};
  },
  console: {log: (line) => lines.push(line)},
  Buffer, JSON, Object, String, Math, Error, encodeURIComponent,
});
const source = fs.readFileSync(spec.snippet, 'utf8');
let error = null;
try {
  await vm.runInContext('(async () => { const ARGS = ' + JSON.stringify(spec.args) + ';\n' + source + '\n})()', context);
} catch (e) {
  error = String(e && e.message || e);
}
process.stdout.write(JSON.stringify({fetches, lines, error}) + '\n');
