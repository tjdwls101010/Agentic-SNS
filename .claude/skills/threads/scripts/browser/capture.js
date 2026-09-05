// threads-snippet: capture
// Aside supports openTab/evaluate/closeTab; no request listeners or init scripts.
// Budget counts one bootstrap navigation and intercepted GraphQL dispatches, not assets.
// Instance variables live only in this result for immediate replay, never in cache.
const actions = ARGS.actions || ['author', 'followers', 'following', 'scroll_following', 'search', 'liked', 'saved'];
const supported = ['author', 'followers', 'following', 'scroll_following', 'search', 'liked', 'saved'];
const result = {queries: [], missing: [], envelopes: [], request_count: 0, count_complete: false, failed: null};
if (!Number.isInteger(ARGS.request_budget) || ARGS.request_budget < 1 || ARGS.request_budget > 60 ||
    !/^https:\/\/www\.threads\.com\/@[A-Za-z0-9_.]+\/post\/[A-Za-z0-9_-]+$/.test(ARGS.url || '') ||
    !Array.isArray(ARGS.targets) || !Array.isArray(actions) ||
    actions.length > 7 || actions.some(action => !supported.includes(action))) {
  result.failed = 'invalid_capture_arguments';
} else {
  let page = null;
  let expired = false;
  const deadline = Date.now() + 58000; // Cleanup has one second; the whole capture stays within 59 seconds.
  const checkTime = () => {
    if (expired || Date.now() >= deadline) {expired = true; throw new Error('capture_timeout');}
  };
  try {
    const work = async () => {
      result.request_count = 1;
      const opened = await openTab(ARGS.url);
      if (expired) {await closeTab(opened); return;}
      page = opened;
      checkTime();
      await page.evaluate(config => {
        const state = {queries: [], envelopes: [], pending: [], attempts: [], observed_names: [], request_count: 1, stopped: false, failed: null};
        const deadline = Date.now() + config.remaining_ms;
        let tail = Promise.resolve();
        let nextAllowed = Date.now() + 1000;
        const graphql = input => {
          try {
            const url = new URL(typeof input === 'string' ? input : input.url, location.href);
            return /(?:^|\.)threads\.com$/.test(url.hostname) && /^\/graphql\/query\/?$/.test(url.pathname);
          } catch (_) {return false;}
        };
        const enqueue = (dispatch, cancelled = () => false) => {
          const request = tail.then(async () => {
            const stop = () => {
              if (Date.now() >= deadline) {state.stopped = true; state.failed ||= 'capture_timeout';}
              if (state.request_count >= config.request_budget) {state.stopped = true; state.failed ||= 'capture_budget';}
              if (state.stopped || cancelled()) throw new Error('capture_stopped');
            };
            stop();
            await new Promise(resolve => setTimeout(resolve, Math.max(0, nextAllowed - Date.now())));
            stop();
            state.request_count++;
            try {return await dispatch();}
            catch (_) {state.stopped = true; state.failed ||= 'capture_failed'; throw new Error('capture_failed');}
            finally {nextAllowed = Date.now() + 1000;}
          });
          tail = request.catch(() => {});
          state.pending.push(tail);
          return request;
        };
        state.drain = async () => {let previous; do {previous = tail; await previous;} while (previous !== tail);};
        const observe = (status, url, body) => {
          let payload = {};
          try {payload = JSON.parse(body);} catch (_) {}
          const errors = {errors: payload.errors, error: payload.error, error_code: payload.error_code, error_subcode: payload.error_subcode};
          const codes = [], messages = [];
          const walk = (value, key = '') => {
            if (Array.isArray(value)) value.forEach(child => walk(child, key));
            else if (value && typeof value === 'object') Object.entries(value).forEach(([k, v]) => walk(v, k));
            else if (/code/.test(key) && /^\d+$/.test(String(value))) codes.push(Number(value));
            else if (typeof value === 'string' && !['path', 'line', 'column'].includes(key)) messages.push(value.toLowerCase());
          };
          walk(errors);
          const message = messages.join(' ');
          const checkpoint = /\/(?:checkpoint|challenge)(?:\/|\?|$)/.test(url || '') || codes.some(c => [368, 459].includes(c)) ||
            /checkpoint|challenge|consent_required/.test(message) || Boolean(payload.checkpoint_url || payload.challenge_url) || /<form\b[^>]*action=["'][^"']*\/(?:challenge|checkpoint)/i.test(body);
          const limited = status === 429 || codes.some(c => [4, 17, 613, 80004].includes(c)) || /rate limit|too many request|try again later/.test(message);
          if (!(checkpoint || limited) || (state.envelopes.length && !checkpoint)) return;
          if (checkpoint) state.envelopes.length = 0;
          state.stopped = true;
          state.failed = 'capture_blocked';
          state.envelopes.push({status, url: checkpoint ? 'https://www.threads.com/checkpoint/' : 'https://www.threads.com/graphql/query',
            body: JSON.stringify({error: {code: checkpoint ? 368 : 4}})});
        };
        state.observe = observe;
        observe(200, location.href, document.documentElement ? document.documentElement.outerHTML : '');
        window.__threadsRefresh = state;
        const record = body => {
          try {
            if (typeof body !== 'string' || body.length > 1000000) return;
            const fields = Object.create(null);
            for (const part of body.split('&')) {
              const at = part.indexOf('=');
              if (at < 0) continue;
              fields[decodeURIComponent(part.slice(0, at))] = decodeURIComponent(part.slice(at + 1).replace(/\+/g, ' '));
            }
            const name = fields.fb_api_req_friendly_name;
            if (/^[A-Za-z0-9_]{1,200}$/.test(name || '') && !state.observed_names.includes(name)) state.observed_names.push(name);
            if (!config.targets.includes(name) || !/^\d+$/.test(fields.doc_id || '')) return;
            const variables = JSON.parse(fields.variables || '{}');
            if (!variables || Array.isArray(variables) || typeof variables !== 'object') return;
            if (!state.queries.some(q => q.name === name) && state.queries.length < 6)
              state.queries.push({name, doc_id: fields.doc_id, variables});
          } catch (_) { /* Malformed requests are not candidates. */ }
        };
        const originalFetch = window.fetch;
        window.fetch = function(input, init) {
          if (!graphql(input)) return originalFetch.apply(this, arguments);
          const receiver = this, args = arguments;
          const signal = (init && init.signal) || (input && input.signal);
          return enqueue(async () => {
            record(init && init.body);
            const response = await originalFetch.apply(receiver, args);
            observe(response.status, response.url, '');
            observe(response.status, response.url, await response.clone().text());
            return response;
          }, () => signal && signal.aborted);
        };
        const originalOpen = XMLHttpRequest.prototype.open;
        const originalSend = XMLHttpRequest.prototype.send;
        const originalAbort = XMLHttpRequest.prototype.abort;
        const requests = new WeakMap();
        XMLHttpRequest.prototype.open = function(method, url) {
          const previous = requests.get(this);
          if (previous) previous.aborted = true;
          requests.set(this, {graphql: graphql(url), aborted: false});
          return originalOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.abort = function() {
          const request = requests.get(this);
          if (request) request.aborted = true;
          return originalAbort.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function(body) {
          const request = requests.get(this);
          if (!request || !request.graphql) return originalSend.apply(this, arguments);
          const xhr = this;
          enqueue(() => new Promise((resolve, reject) => {
            record(body);
            xhr.addEventListener('loadend', () => {
              try {
                observe(xhr.status, xhr.responseURL, '');
                const body = xhr.responseType === 'json' ? JSON.stringify(xhr.response) : xhr.responseText;
                observe(xhr.status, xhr.responseURL, body);
                if (!xhr.status) {state.stopped = true; state.failed ||= 'capture_failed';}
                resolve();
              } catch (_) {reject(new Error('capture_failed'));}
            }, {once: true});
            try {originalSend.call(xhr, body);} catch (_) {reject(new Error('capture_failed'));}
          }), () => request.aborted).catch(() => {originalAbort.call(xhr);});
        };
        state.click = action => {
          const attempt = {action, clicked: false};
          state.attempts.push(attempt);
          if (state.stopped) return false;
          // 성진: Exact English/Korean read labels may miss other locales; add only observed navigation labels, never follow/like action buttons.
          const root = action === 'following' ? document.querySelector('[role="dialog"]') : document;
          if (!root) return false;
          if (action === 'search') {
            const input = document.querySelector('input[type="search"], input[placeholder*="Search"], input[placeholder*="검색"]');
            if (input) {
              Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'python');
              input.dispatchEvent(new Event('input', {bubbles: true}));
              attempt.clicked = true;
              return true;
            }
          }
          const labels = {followers: /^(?:Followers|팔로워)(?:\s|$)|^[\d,.MK만천]+ followers$/i, following: /^(?:Following|팔로잉)(?:\s|$)/i};
          const selector = action === 'following' ? '[role="tab"]' : 'a[href], button, [role="button"]';
          for (const el of root.querySelectorAll(selector)) {
            const text = (el.getAttribute('aria-label') || el.innerText || '').trim().split('\n')[0].trim();
            const href = (el.getAttribute('href') || '').replace(/\/$/, '');
            const destination = action === 'author' ? '/@' + config.author : '/' + action;
            const match = ['author', 'liked', 'saved', 'search'].includes(action) ? href === destination : labels[action] && labels[action].test(text);
            if (match && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && el.getClientRects().length) {
              attempt.clicked = true; el.click(); return true;
            }
          }
          return false;
        };
      }, {request_budget: ARGS.request_budget, targets: ARGS.targets, author: ARGS.url.split('/@')[1].split('/')[0], remaining_ms: Math.max(0, deadline - Date.now())});
      const observePage = async () => {
        const observed = await page.evaluate(async () => {
          const state = window.__threadsRefresh;
          await state.drain();
          state.observe(200, location.href, '');
          return {envelopes: state.envelopes, request_count: state.request_count, failed: state.failed};
        });
        checkTime();
        Object.assign(result, observed);
        if (observed.envelopes.length) {result.failed = 'capture_blocked'; throw new Error('blocked');}
        if (observed.failed) throw new Error('capture_stopped');
      };
      await observePage();
      const clickRead = async action => {
        const until = Math.min(deadline, Date.now() + 4000);
        do {
          checkTime();
          if (await page.evaluate(value => window.__threadsRefresh.click(value), action)) return true;
          await sleep(250);
          await observePage();
        } while (Date.now() < until);
        return false;
      };
      for (const action of actions) {
        checkTime();
        if (action === 'scroll_following') {
          await page.evaluate(() => {
            const dialog = document.querySelector('[role="dialog"]');
            if (!dialog) return;
            for (const el of [dialog, ...dialog.querySelectorAll('div')]) {
              if (el.scrollHeight > el.clientHeight + 100 && el.clientHeight > 0) el.scrollTop += el.clientHeight;
            }
          });
        } else {
          await clickRead(action);
          if (action === 'search') {await sleep(500); await clickRead('search');}
        }
        checkTime();
        await sleep(Math.min(1000, Math.max(0, deadline - Date.now())));
        await observePage();
      }
      checkTime();
      const queries = await page.evaluate(() => window.__threadsRefresh.queries);
      checkTime();
      result.queries = queries.filter(q => ARGS.targets.includes(q.name));
      result.attempts = await page.evaluate(() => window.__threadsRefresh.attempts);
      result.observed_names = await page.evaluate(() => window.__threadsRefresh.observed_names);
      result.page_url = await page.evaluate(() => location.href);
    };
    await Promise.race([work(), sleep(Math.max(0, deadline - Date.now())).then(() => {
      expired = true;
      throw new Error('capture_timeout');
    })]);
  } catch (error) {
    result.failed = result.failed || (expired ? 'capture_timeout' : 'capture_failed');
  } finally {
    expired = true;
    if (page) {
      try {
        const snapshot = await Promise.race([page.evaluate(() => {
          const state = window.__threadsRefresh;
          if (!state) return null;
          state.stopped = true;
          return {request_count: state.request_count, envelopes: state.envelopes};
        }), sleep(250).then(() => null)]);
        if (snapshot) Object.assign(result, snapshot, {count_complete: true});
      } catch (_) { /* Python retains the reservation if no complete count is available. */ }
      try {
        await Promise.race([closeTab(page), sleep(750).then(() => {throw new Error('cleanup');})]);
      } catch (_) {result.failed = 'capture_cleanup_failed';}
    }
  }
  result.missing = ARGS.targets.filter(name => !result.queries.some(q => q.name === name));
}
const blocked = result.envelopes[0];
if (blocked) Object.assign(result, JSON.parse(blocked.body));
console.log(JSON.stringify({status: blocked ? blocked.status : 200, url: blocked ? blocked.url : result.page_url || ARGS.url || '', body: JSON.stringify(result)}));
