"""What a Facebook response means for the account and for the read: the one place Facebook's codes are interpreted.

Order when several apply: a checkpoint (a person must clear it), a login, a rate limit, a temporary rejection (one
retry), then the faults of the request itself. A rate limit is the account's for a while, never a person block.
"""
import json
import re
from urllib.parse import urlsplit

from sns.errors import SnsError

BLOCK_FIX = 'Stop requests. After a person checks facebook.com in the Aside browser, run facebook doctor --unblock.'
LOGIN_FIX = 'Log in to Facebook in the Aside browser, then run facebook doctor.'
STALE_FIX = 'Facebook changed this query; the skill needs an update (its bundled query snapshot). Tell the user which read failed.'
RETRY_FIX = 'Retry later; run facebook doctor if it keeps failing.'
GONE_FIX = 'Tell the user; check the address in the Aside browser (the page may be private, removed or misspelled).'

_CODES = re.compile(r'"(?:error|code)"\s*:\s*"?(1357001|1357004|1357054)\b')
# A key that is present with nothing in it (null, false, an empty string, list or object) names no checkpoint
# A key's value that names something: a string with a character in it, or an object or list that is not empty
_VALUE = r'(?:"(?=[^"\s])|[\[{](?!\s*[\]}]))'


class Verdict:
    """What one answer was. kind: ok (with chunks), empty (an explicitly empty connection), retry (a temporary
    rejection: one paced retry), stale (the query is no longer accepted), failed, unavailable, login, blocked (a
    checkpoint: `block` names it, `error` is the stop) or rate_limited (the account's stop is made by the guard)."""

    def __init__(self, kind, chunks=None, error=None, block=None):
        self.kind, self.chunks, self.error, self.block = kind, chunks or [], error, block


def decode(body):
    """The JSON objects of a GraphQL body (Relay incremental delivery, optional anti-JSON prefix)."""
    text = body.strip()
    if text.startswith('for (;;);'):
        text = text[9:].lstrip()
    decoder, chunks = json.JSONDecoder(), []
    while text:
        chunk, end = decoder.raw_decode(text)
        if not isinstance(chunk, dict):
            raise ValueError('not an object')
        chunks.append(chunk)
        text = text[end:].lstrip()
    return chunks


def _at(path, *names):
    """Whether a URL path is one of these screens (or under it): /checkpoint and /checkpoint/1/, not /checkpointsoftware."""
    return any(path == f'/{name}' or path.startswith(f'/{name}/') or path == f'/{name}.php' for name in names)


def _named(value):
    return (isinstance(value, str) and bool(value.strip())) or (isinstance(value, (dict, list)) and bool(value))


def _walk(value):
    stack = [value]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            yield value
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _checkpoint():
    return Verdict('blocked', error=SnsError('blocked', 'Facebook showed a checkpoint for this account; requests stay '
                                                        'blocked until a person clears it.', BLOCK_FIX,
                                             reason='checkpoint', person=True), block='checkpoint')


def _login():
    return Verdict('login', error=SnsError('login', 'Facebook login is required in the Aside browser.', LOGIN_FIX,
                                           reason='login'))


def location(url, user_id):
    """The verdict on a tab's location and logged-in user (from the state snippet)."""
    path = urlsplit(url or '').path.lower()
    if _at(path, 'checkpoint'):
        return _checkpoint()
    if _at(path, 'login', 'recover') or not user_id or user_id == '0':
        return _login()
    return Verdict('ok')


def response(envelope, *, mode, expected=None, retried=False):
    """The verdict on one HTTP response {status, url, body}.

    mode: graphql (expected = (key, kind) where kind is connection or object), html (a facebook.com page).
    """
    if (not isinstance(envelope, dict) or type(envelope.get('status')) is not int
            or not isinstance(envelope.get('body'), str) or not isinstance(envelope.get('url'), str)):
        return _failed('Facebook returned an invalid response.')
    status, body = envelope['status'], envelope['body']
    path = urlsplit(envelope['url']).path.lower()
    chunks, malformed = [], False
    if mode == 'graphql' or body.lstrip().startswith(('{', 'for (;;);')):
        try:
            chunks = decode(body)
        except (ValueError, RecursionError):
            malformed = True
    objects = list(_walk(chunks))

    def has_key(key):
        return any(key in obj for obj in objects) or bool(re.search(r'"' + key + r'"\s*:', body))

    def carries(key):
        """Whether the key is there with something in it."""
        return any(_named(obj.get(key)) for obj in objects if key in obj) or bool(
            re.search(r'"' + key + r'"\s*:\s*' + _VALUE, body))

    codes = {str(obj[k]) for obj in objects for k in ('code', 'error') if type(obj.get(k)) in (int, str)}
    codes.update(_CODES.findall(body))
    if _at(path, 'checkpoint') or carries('checkpoint_url') or carries('challenge_url'):
        return _checkpoint()
    user = re.search(r'"USER_ID"\s*:\s*"(\d+)"', body)
    if ('1357001' in codes or has_key('caa_login_form_data') or _at(path, 'login', 'recover')
            or (user is not None and user[1] == '0')):
        return _login()
    if status == 429 or '1357004' in codes or ('1357054' in codes and retried):
        return Verdict('rate_limited')
    if '1357054' in codes:
        return Verdict('retry')
    if status == 404 and mode == 'html':
        return Verdict('unavailable', error=SnsError('unavailable', 'Facebook has no such page for this account: '
                                                                   'deleted, private or never existed.', GONE_FIX,
                                                     reason='unavailable'))
    if status != 200:
        return _failed(f'Facebook answered with HTTP {status}.')
    if mode == 'html':
        if not body.strip():
            return _failed('Facebook returned an empty page.')
        return Verdict('ok')
    if malformed or not chunks:
        return _failed('Facebook returned query data this skill cannot decode.')
    for chunk in chunks:
        if chunk.get('errors') and not chunk.get('data'):
            return _stale('Facebook rejected the query: ' + _first_message(chunk['errors']))
    if any(obj.get('severity') == 'CRITICAL' for obj in objects) or any(chunk.get('error') for chunk in chunks):
        return _failed('Facebook reported a failure for the query.')
    return _expected(chunks, *(expected or (None, None)))


def _first_message(errors):
    for error in errors if isinstance(errors, list) else []:
        if isinstance(error, dict) and isinstance(error.get('message'), str):
            return error['message'][:120]
    return 'no reason given'


def _failed(message):
    return Verdict('failed', error=SnsError('failed', message, RETRY_FIX, reason='failed'))


def _stale(message):
    return Verdict('stale', error=SnsError('failed', message, STALE_FIX, reason='stale'))


def _expected(chunks, key, kind):
    if key is None:
        return Verdict('ok', chunks)
    matches = {}
    for chunk in chunks:
        path = chunk.get('path', [])
        if not isinstance(path, list) or any(type(part) not in (str, int) for part in path):
            return _failed('Facebook returned a malformed response path.')
        pending = [(tuple(path), chunk.get('data'))]
        while pending:
            where, value = pending.pop()
            if where and where[-1] == key:
                if not isinstance(value, dict):
                    if value is None:
                        continue
                    return _stale(f'The {key} part of the response has an unexpected shape.')
                matches.setdefault(where, {}).update(value)
            if isinstance(value, dict):
                pending.extend((where + (name,), child) for name, child in value.items())
            elif isinstance(value, list):
                pending.extend((where + (index,), child) for index, child in enumerate(value))
    if kind == 'connection':
        # Count-only previews share the connection's name but cannot paginate.
        matches = {where: value for where, value in matches.items()
                   if any(field in value for field in ('edges', 'nodes', 'page_info'))}
    if not matches:
        return _stale(f'The response has no {key}; Facebook may have changed the query.')
    nonempty, exhausted = False, True
    for value in matches.values():
        if kind == 'object':
            if not any(k in value for k in ('id', '__typename', 'comet_sections', 'feedback', 'story')):
                return _stale(f'The {key} in the response is not a readable object.')
            nonempty = True
            continue
        fields = [field for field in ('edges', 'nodes') if field in value]
        for field in fields:
            items = value[field]
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                return _stale(f'The {key} items have an unexpected shape.')
            if field == 'edges' and any(not isinstance(item.get('node'), dict) for item in items):
                return _stale(f'The {key} edges have no nodes.')
            nonempty |= bool(items)
        info = value.get('page_info')
        if info is not None and (not isinstance(info, dict)
                                 or ('has_next_page' in info and type(info['has_next_page']) is not bool)
                                 or (info.get('end_cursor') is not None and not isinstance(info.get('end_cursor'), str))):
            return _failed('Facebook sent pagination data of the wrong type.')
        exhausted &= isinstance(info, dict) and info.get('has_next_page') is False
    if not nonempty and exhausted:
        return Verdict('empty', chunks)
    return Verdict('ok', chunks)
