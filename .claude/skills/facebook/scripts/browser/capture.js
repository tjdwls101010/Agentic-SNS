// Aside supports openTab/evaluate/closeTab; no request listeners or init scripts.
// Budget counts one bootstrap navigation and intercepted GraphQL dispatches, not assets.
// Instance variables live only in this result for immediate replay, never in cache.
const actions = ARGS.actions || ['open_comments', 'more_comments', 'expand_replies'];
const supported = ['open_comments', 'sort_comments', 'more_comments', 'expand_replies', 'scroll_feed'];
const result = {queries: [], missing: [], envelopes: [], request_count: 0, count_complete: false, failed: null};
if (!Number.isInteger(ARGS.request_budget) || ARGS.request_budget < 1 || ARGS.request_budget > 400 ||
    !/^https:\/\/(?:www\.)?facebook\.com\//.test(ARGS.url || '') ||
    !Array.isArray(ARGS.targets) || !Array.isArray(actions) ||
    actions.length > 4 || actions.some(action => !supported.includes(action))) {
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
            return /(?:^|\.)facebook\.com$/.test(url.hostname) && /^\/api\/graphql\/?$/.test(url.pathname);
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
          const checkpoint = /\/checkpoint(?:\/|\?|$)/.test(url || '') || /"(?:checkpoint_url|challenge_url)"\s*:/.test(body);
          const code = /"(?:error|code)"\s*:\s*"?(1357001|1357004|1357054)\b/.exec(body);
          if (!(checkpoint || status === 429 || code) || (state.envelopes.length && !checkpoint)) return;
          if (checkpoint) state.envelopes.length = 0;
          const safe = checkpoint ? {checkpoint_url: 'https://www.facebook.com/checkpoint/'} : code ? {error: Number(code[1])} : {};
          state.stopped = true;
          state.failed = 'capture_blocked';
          state.envelopes.push({status, url: checkpoint ? 'https://www.facebook.com/checkpoint/' : 'https://www.facebook.com/api/graphql/', body: JSON.stringify(safe)});
        };
        state.observe = observe;
        observe(200, location.href, document.documentElement ? document.documentElement.outerHTML : '');
        window.__facebookRefresh = state;
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
            if (!state.queries.some(q => q.name === name) && state.queries.length < 3)
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
          // 성진: Exact English/Korean labels miss other locales; add measured read labels when needed.
          const labels = {
            open_comments: /^(?:View comments|See all comments|\d[\d,.]* comments|댓글 보기|댓글 모두 보기|댓글 [\d,.]+개)$/i,
            sort_comments: /^(?:Most relevant|Most recent|Newest|All comments|가장 관련성 높은 댓글|관련성 높은 댓글|최신순|모든 댓글)$/i,
            sort_recent: /^(?:Newest|Most recent|New comments|최신순|최신 댓글)$/i,
            more_comments: /^(?:View (?:more|previous) comments|View \d[\d,.]* more comments|댓글 더 보기|이전 댓글 보기)$/i,
            expand_replies: /^(?:View (?:\d[\d,.]* |more )?replies|답글 [\d,.]+개(?: 보기)?|답글 더 보기)$/i,
          };
          for (const el of document.querySelectorAll('button, [role="button"], [role="menuitem"], [role="menuitemradio"], a[href]')) {
            const text = (el.getAttribute('aria-label') || el.innerText || '').trim().split('\n')[0].trim();
            if (!el.disabled && el.getAttribute('aria-disabled') !== 'true' && el.getClientRects().length &&
                labels[action].test(text)) {attempt.clicked = true; el.click(); return true;}
          }
          return false;
        };
      }, {request_budget: ARGS.request_budget, targets: ARGS.targets, remaining_ms: Math.max(0, deadline - Date.now())});
      const observePage = async () => {
        const observed = await page.evaluate(async () => {
          const state = window.__facebookRefresh;
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
          if (await page.evaluate(value => window.__facebookRefresh.click(value), action)) return true;
          await sleep(250);
          await observePage();
        } while (Date.now() < until);
        return false;
      };
      for (const action of actions) {
        checkTime();
        if (action === 'scroll_feed') await page.evaluate(() => window.scrollBy(0, 1800));
        if (action === 'sort_comments') {
          await clickRead('sort_comments');
          await sleep(300);
          await clickRead('sort_recent');
        }
        if (action === 'open_comments') await clickRead('open_comments');
        if (action === 'more_comments') await clickRead('more_comments');
        if (action === 'expand_replies') await clickRead('expand_replies');
        checkTime();
        await sleep(Math.min(1000, Math.max(0, deadline - Date.now())));
        await observePage();
      }
      checkTime();
      const queries = await page.evaluate(() => window.__facebookRefresh.queries);
      checkTime();
      result.queries = queries.filter(q => ARGS.targets.includes(q.name));
      result.attempts = await page.evaluate(() => window.__facebookRefresh.attempts);
      result.observed_names = await page.evaluate(() => window.__facebookRefresh.observed_names);
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
          const state = window.__facebookRefresh;
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
