"""What a Facebook response means for the account and for the read: the one place Facebook's codes are interpreted."""
import json
import re
from urllib.parse import urlsplit

from facebook.errors import FacebookError

BLOCK_FIX = 'Stop requests. After a person checks Facebook in the Aside browser, run doctor --unblock.'
LOGIN_FIX = 'Log in to Facebook in the Aside browser, then run doctor.'
STALE_FIX = 'Facebook changed this query; update the skill (its bundled query snapshot) or report it.'

_CODES = re.compile(r'"(?:error|code)"\s*:\s*"?(1357001|1357004|1357054)\b')


class Verdict:
    """ok (with chunks), empty, retry, or an error to raise; `block` names a block to record first."""

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


def _walk(value):
    stack = [value]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            yield value
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def location(url, user_id):
    """The verdict on a tab's location and logged-in user (from the state snippet)."""
    path = urlsplit(url or '').path.lower()
    if path.startswith('/checkpoint'):
        return Verdict('blocked', error=FacebookError(5, 'Facebook showed a checkpoint for this account.', BLOCK_FIX,
                                                      reason='checkpoint'), block='checkpoint')
    if path.startswith(('/login', '/recover')) or not user_id or user_id == '0':
        return Verdict('login', error=FacebookError(4, 'Facebook login is required in the Aside browser.', LOGIN_FIX,
                                                    reason='login'))
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

    codes = {str(obj[k]) for obj in objects for k in ('code', 'error') if type(obj.get(k)) in (int, str)}
    codes.update(_CODES.findall(body))
    if path.startswith('/checkpoint') or has_key('checkpoint_url') or has_key('challenge_url'):
        return Verdict('blocked', error=FacebookError(5, 'Facebook showed a checkpoint for this account.', BLOCK_FIX,
                                                      reason='checkpoint'), block='checkpoint')
    user = re.search(r'"USER_ID"\s*:\s*"(\d+)"', body)
    if ('1357001' in codes or has_key('caa_login_form_data') or path.startswith(('/login', '/recover'))
            or (user is not None and user[1] == '0')):
        return Verdict('login', error=FacebookError(4, 'Facebook login is required in the Aside browser.', LOGIN_FIX,
                                                    reason='login'))
    if status == 429 or '1357004' in codes or ('1357054' in codes and retried):
        return Verdict('blocked', error=FacebookError(5, 'Facebook rate-limited this account; requests are blocked '
                                                         'for 30 minutes.', 'Stop requests and retry after the block '
                                                                            'expires; check Facebook first.',
                                                      reason='rate_limit'), block='rate_limit')
    if '1357054' in codes:
        return Verdict('retry')
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
    return Verdict('failed', error=FacebookError(6, message, 'Retry later; run doctor if it keeps failing.', reason='failed'))


def _stale(message):
    return Verdict('stale', error=FacebookError(6, message, STALE_FIX, reason='stale'))


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
