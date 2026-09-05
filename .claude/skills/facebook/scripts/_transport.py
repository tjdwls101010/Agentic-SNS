"""Classify responses and guard every request with account protection."""
import json
import math
import random
import time
import re
from urllib.parse import urlsplit

from _aside import run_snippet
from _blocked import account_lock, cache_dir, check_blocked, set_blocked, write_state
from _registry import QuerySpec, build_variables, get_query
from _session import extract_tokens
from _errors import FacebookError, diagnostic


def iter_chunks(body):
    """Decode JSON or newline-separated Relay chunks, including the anti-JSON prefix."""
    text = body.decode('utf-8') if isinstance(body, bytes) else body
    decoder = json.JSONDecoder()
    text = text.strip()
    if text.startswith('for (;;);'):
        text = text[9:].lstrip()
    try:
        while text:
            chunk, end = decoder.raw_decode(text)
            if not isinstance(chunk, dict):
                raise ValueError
            yield chunk
            text = text[end:].lstrip()
    except (ValueError, TypeError, RecursionError):
        raise FacebookError(6, 'Facebook returned malformed query data.', 'Run refresh, then retry the read command.') from None


def _walk(value):
    stack = [value]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            yield value
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _failure():
    raise FacebookError(6, 'Facebook query failed or its expected structure changed.', 'Run refresh, then retry the read command.')


class _RetryRequest(FacebookError):
    def __init__(self):
        super().__init__(6, 'Facebook temporarily rejected the request.', 'The transport permits one paced retry.')


def classify(envelope, expected=None, *, home=False, html=False, retried=False, asset=False):
    """Return decoded chunks, or raise a safe public error; explicit empty connections are exit 7."""
    if (not isinstance(envelope, dict) or type(envelope.get('status')) is not int
            or not isinstance(envelope.get('body'), str) or not isinstance(envelope.get('url'), str)):
        _failure()
    body = envelope['body']
    if asset:
        # Static client code contains auth-error literals, not an account response.
        if envelope['status'] == 429:
            set_blocked('rate_limit')
            raise FacebookError(5, 'Facebook asset rate limit detected.', 'Stop requests for 30 minutes.')
        if envelope['status'] != 200 or not body.strip():
            _failure()
        return envelope
    try:
        path = urlsplit(envelope['url']).path.lower()
    except ValueError:
        _failure()
    chunks = []
    malformed = False
    if not (html or home) or body.lstrip().startswith(('{', 'for (;;);')):
        try:
            chunks = list(iter_chunks(body))
        except FacebookError:
            malformed = True
    objects = list(_walk(chunks))
    def has_key(key):
        return any(key in obj for obj in objects) or bool(re.search(r'"' + key + r'"\s*:', body))

    codes = {str(obj[key]) for obj in objects for key in ('code', 'error') if type(obj.get(key)) in (int, str)}
    codes.update(re.findall(r'"(?:error|code)"\s*:\s*"?(1357001|1357004|1357054)\b', body))
    if '/checkpoint' in path or has_key('checkpoint_url') or has_key('challenge_url'):
        set_blocked('checkpoint')
        raise FacebookError(5, 'Facebook checkpoint detected.', 'Stop requests. Check Facebook in Aside, then run doctor --unblock.')
    user = re.search(r'"USER_ID"\s*:\s*"(\d+)"', body)
    if ('1357001' in codes or has_key('caa_login_form_data') or path.startswith(('/login', '/recover'))
            or (user is not None and user[1] == '0') or (home and user is None and envelope['status'] == 200)):
        raise FacebookError(4, 'Facebook login is required.', 'Log in to Facebook in Aside, then run doctor.')
    if envelope['status'] == 429 or '1357004' in codes or ('1357054' in codes and retried):
        set_blocked('rate_limit')
        raise FacebookError(5, 'Facebook rate limit detected.', 'Stop requests for 30 minutes; check Facebook before unblocking.')
    if '1357054' in codes:
        raise _RetryRequest()
    if envelope['status'] != 200:
        _failure()
    for chunk in chunks:
        if chunk.get('errors') and not chunk.get('data'):
            _failure()
    if any(obj.get('severity') == 'CRITICAL' for obj in objects) or any(chunk.get('error') for chunk in chunks):
        _failure()
    if html or home:
        if not body.strip() or malformed:
            _failure()
        return envelope
    if malformed or not chunks:
        _failure()
    if expected is None:
        return chunks
    key = expected if isinstance(expected, str) else (expected.expected_key or expected.connection_key)
    kind = 'connection' if isinstance(expected, str) else expected.expected_kind
    matches = {}
    for chunk in chunks:
        path = chunk.get('path', [])
        if not isinstance(path, list) or any(type(part) not in (str, int) for part in path):
            _failure()
        pending = [(tuple(path), chunk.get('data'))]
        while pending:
            location, value = pending.pop()
            if location and location[-1] == key:
                if not isinstance(value, dict):
                    _failure()
                matches.setdefault(location, {}).update(value)
            if isinstance(value, dict):
                pending.extend((location + (field,), child) for field, child in value.items())
            elif isinstance(value, list):
                pending.extend((location + (index,), child) for index, child in enumerate(value))
    if kind == 'connection':
        # Count-only previews share the connection name but cannot paginate.
        matches = {path: value for path, value in matches.items()
                   if any(field in value for field in ('edges', 'nodes', 'page_info'))}
    if not matches:
        _failure()
    nonempty = False
    exhausted = True
    for value in matches.values():
        if not isinstance(value, dict):
            _failure()
        if kind == 'object':
            if not value or not any(k in value for k in ('id', '__typename', 'comet_sections', 'feedback', 'story')):
                _failure()
            nonempty = True
            continue
        fields = [field for field in ('edges', 'nodes') if field in value]
        if not fields:
            _failure()
        for field in fields:
            items = value[field]
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                _failure()
            if field == 'edges' and any(not isinstance(item.get('node'), dict) for item in items):
                _failure()
            nonempty |= bool(items)
        exhausted &= isinstance(value.get('page_info'), dict) and value['page_info'].get('has_next_page') is False
        if 'page_info' in value:
            info = value['page_info']
            if (not isinstance(info, dict)
                    or ('has_next_page' in info and type(info['has_next_page']) is not bool)
                    or ('end_cursor' in info and info['end_cursor'] is not None and not isinstance(info['end_cursor'], str))):
                _failure()
    if not nonempty and exhausted:
        raise FacebookError(7, 'Facebook returned an explicitly empty connection.', 'No results; pagination may treat this as exhausted.')
    return chunks


def _validate_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not any(host == root or host.endswith('.' + root) for root in ('facebook.com', 'fbcdn.net'))):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise FacebookError(2, 'Expected an HTTPS Facebook URL.', 'Use a facebook.com URL.') from None


class Transport:
    def __init__(self, limit=25):
        if type(limit) is not int or limit < 1:
            raise FacebookError(2, 'Request budget must be a positive integer.')
        # 성진: 400회 상한은 실계정 보호용, 일회용 계정으로 바꾸면 올려도 됨
        self.limit = min(limit, 400)
        self.request_count = 0
        self.tokens = {}
        self.account_id = None

    def start(self):
        if not self.tokens:
            response = self._request('tokens', {}, home=True)
            self.tokens = extract_tokens(response['body'])
            self.account_id = self.tokens['user_id']
        else:
            check_blocked()
        return self

    def html(self, url):
        _validate_url(url)
        return self._request('page', {'url': url}, html=True, asset=(urlsplit(url).hostname or '').endswith('.fbcdn.net'))

    def mine(self, url, names):
        """One guarded route or static-bundle request, with parsed query metadata."""
        _validate_url(url)
        return self._request('mine', {'url': url, 'names': names}, html=True,
                             asset=(urlsplit(url).hostname or '').endswith('.fbcdn.net'))

    def query(self, key, overrides=None, referer=None):
        return self.query_spec(get_query(key), overrides, referer)

    def query_spec(self, spec, overrides=None, referer=None):
        if not isinstance(spec, QuerySpec) or not isinstance(spec.doc_id, str) or not spec.doc_id.isdigit():
            raise FacebookError(2, 'Expected a valid query specification.')
        referer = referer or spec.referer
        _validate_url(referer)
        variables = build_variables(spec, overrides)
        self.start()
        response = self._request('graphql', {'tokens': self.tokens, 'name': spec.name,
                                 'doc_id': spec.doc_id, 'variables': variables, 'referer': referer}, expected=spec)
        return response['body'].encode('utf-8')

    def capture(self, args):
        """Count bootstrap navigation plus intercepted GraphQL dispatches, not page assets.

        Reserve the remaining budget under the account lock. An incomplete browser
        count retains that reservation, so timeouts cannot free unknown requests.
        """
        if not isinstance(args, dict):
            raise FacebookError(2, 'Expected capture arguments.')
        _validate_url(args.get('url'))
        actions = args.get('actions', ['open_comments', 'more_comments', 'expand_replies'])
        targets = args.get('targets')
        allowed = {get_query(key).name for key in ('newsfeed', 'comments', 'comments_page', 'replies')}
        if (not isinstance(targets, list) or not targets or any(not isinstance(t, str) or t not in allowed for t in targets)
                or not isinstance(actions, list) or len(actions) > 4
                or any(a not in ('open_comments', 'sort_comments', 'more_comments', 'expand_replies', 'scroll_feed') for a in actions)):
            raise FacebookError(2, 'Expected supported comment capture targets and actions.')
        with account_lock():
            check_blocked()
            available = self.limit - self.request_count
            if available < 1:
                raise FacebookError(8, 'The shared request budget is exhausted.')
            self._pace()
            self.request_count += available
            try:
                response = run_snippet('capture', {**args, 'request_budget': available})
                try:
                    chunks = list(iter_chunks(response['body']))
                except FacebookError:
                    classify(response)
                    raise
                if len(chunks) != 1:
                    _failure()
                result = chunks[0]
                count = result.get('request_count')
                complete = result.get('count_complete') is True and type(count) is int and 1 <= count <= available
                if complete:
                    self.request_count -= available - count
                observations = result.get('envelopes', [])
                if not isinstance(observations, list):
                    _failure()
                # Persist observed protection signals before another CLI acquires the lock.
                for observed in observations:
                    classify(observed)
                classify(response)
                if not complete:
                    raise FacebookError(6, 'Browser capture request count is incomplete.', 'The remaining budget was retained.')
                if result.get('failed') == 'capture_budget':
                    raise FacebookError(8, 'The shared request budget is exhausted during capture.')
                if result.get('failed') or not isinstance(result.get('queries'), list):
                    raise FacebookError(6, 'Browser capture did not complete.', 'Check the post in Aside before capturing again.')
                return response
            finally:
                write_state('pace.json', {'next_allowed_at': time.time() + random.uniform(1.0, 2.0)})

    def _request(self, name, args, **classification):
        # Keep classification and a possible retry under the lock so waiters see a block before fetching.
        with account_lock():
            for attempt in range(2):
                check_blocked()
                if self.request_count >= self.limit:
                    raise FacebookError(8, 'The shared request budget is exhausted.', 'Continue from the saved cursor in a later invocation.')
                self._pace()
                self.request_count += 1
                if getattr(self, 'verbose', False):
                    diagnostic('request', count=self.request_count, snippet=name, query=args.get('name'))
                try:
                    response = run_snippet(name, args)
                finally:
                    write_state('pace.json', {'next_allowed_at': time.time() + random.uniform(1.0, 2.0)})
                try:
                    classify(response, retried=bool(attempt), **classification)
                    return response
                except _RetryRequest:
                    continue
        raise FacebookError(6, 'Facebook rejected the request.')

    def _pace(self):
        try:
            state = json.loads((cache_dir() / 'pace.json').read_text())
            deadline = state['next_allowed_at']
            if type(deadline) not in (int, float) or not math.isfinite(deadline):
                raise ValueError
        except FileNotFoundError:
            deadline = 0
        except (OSError, ValueError, TypeError, KeyError):
            raise FacebookError(5, 'Account pacing state is unreadable.', 'Restore the account protection cache before retrying.') from None
        gap = deadline - time.time()
        if gap > 0:
            time.sleep(gap)
        # Reserve a gap before starting as well, so a killed CLI cannot erase its request timestamp.
        write_state('pace.json', {'next_allowed_at': time.time() + random.uniform(1.0, 2.0)})
