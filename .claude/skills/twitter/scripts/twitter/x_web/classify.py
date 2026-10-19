"""What an X response means for account protection and for the read: one place, for the skill's own queries and for
what the tab's hook saw the app receive.

Order when several apply: a challenge, then a lock (a person must clear both), then the operation's limit, then a
login, then the faults of the request itself. An operation's limit is that operation's alone, never an account block.
"""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from twitter.errors import TwitterError

LOCK_CODES = {64, 326}         # suspended, locked
LOGIN_CODES = {32}
CSRF_CODES = {353}
_CHALLENGE = re.compile(r'<!doctype|<html|cf-', re.I)
_CONTRACT = re.compile(r'must be defined|coerced Null value|GRAPHQL_VALIDATION_FAILED')
UNBLOCK_FIX = 'Stop requests. After a person checks x.com in the Aside browser, run doctor --unblock.'
LOGIN_FIX = 'Log in to x.com in the Aside browser, then run doctor.'
UPDATE_FIX = 'X changed this read; the skill needs an update. Tell the user which read failed; other commands may work.'
RETRY_FIX = 'Retry later; run doctor if it keeps failing.'
LOCKED_PATHS = ('/account/access',)
LOGIN_PATHS = ('/i/flow/login', '/login')


@dataclass
class Verdict:
    kind: str                       # ok | blocked | rate_limited | login | csrf | signature_rejected |
    #                                 contract_changed | features_missing | rotated | transient | unavailable |
    #                                 shape_changed
    error: TwitterError | None = None
    block: str | None = None        # challenge | account_locked
    root: object = None             # an ok response: the data at the operation's root
    warnings: list = field(default_factory=list)   # errors that came with data (scrubbed by the caller)
    names: list = field(default_factory=list)      # features_missing: the feature names X asked for
    bucket: str | None = None       # rate_limited: the operation (or REST path) whose limit ran out
    reset: int | None = None        # rate_limited: X's reset (Unix seconds), None when not sent


def _blocked(reason):
    message = ('X presented a browser challenge for this account.' if reason == 'challenge'
               else 'X locked or suspended this account.')
    return Verdict('blocked', TwitterError(5, message + ' Requests stay blocked until a person clears it.', UNBLOCK_FIX,
                                           reason=reason), block=reason)


def _rate_limited(bucket, reset):
    error = TwitterError(10, f'X\'s limit for {bucket} is used up for now.', 'This is not an account problem and other '
                         'commands still work; retry this one after its reset.', reason='rate_limited',
                         operation=bucket, reset=reset)
    return Verdict('rate_limited', error, bucket=bucket, reset=reset)


def _login():
    return Verdict('login', TwitterError(4, 'X requires a logged-in session in the Aside browser.', LOGIN_FIX,
                                         reason='login'))


def _failed(kind, message, fix=RETRY_FIX, code=6):
    return Verdict(kind, TwitterError(code, message, fix, reason=kind))


def _errors(body):
    errors = body.get('errors') if isinstance(body, dict) else None
    return [e for e in errors if isinstance(e, dict)] if isinstance(errors, list) else []


def _codes(errors):
    found = set()
    for error in errors:
        for value in (error.get('code'), (error.get('extensions') or {}).get('code')):
            if type(value) is int:
                found.add(value)
            elif isinstance(value, str) and value.isdigit():
                found.add(int(value))
    return found


def at_root(data, path):
    """The value at a dotted path (a segment ending in [] maps over a list), or None."""
    current = data
    parts = path.split('.')
    for index, piece in enumerate(parts):
        if piece.endswith('[]'):
            sequence = current.get(piece[:-2]) if isinstance(current, dict) else None
            if not isinstance(sequence, list):
                return None
            rest = '.'.join(parts[index + 1:])
            return [at_root(item, rest) if rest else item for item in sequence]
        if not isinstance(current, dict) or piece not in current:
            return None
        current = current[piece]
    return current


def _reset(headers):
    try:
        return int(str((headers or {})['x-rate-limit-reset']))
    except (KeyError, TypeError, ValueError):
        return None


def response(envelope, operation, root):
    """The verdict on one GraphQL response {status, body, headers} to `operation`, whose data sits at `root`."""
    status, raw = envelope.get('status'), envelope.get('body') or ''
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        body = None
    errors = _errors(body)
    codes = _codes(errors)
    messages = ' '.join(str(e.get('message', '')) for e in errors)
    if status == 403 and _CHALLENGE.search(raw):
        return _blocked('challenge')
    if codes & LOCK_CODES:
        return _blocked('account_locked')
    if status == 429:
        return _rate_limited(operation, _reset(envelope.get('headers')))
    if status == 401 or codes & LOGIN_CODES:
        return _login()
    if codes & CSRF_CODES:
        return _failed('csrf', 'X refused the session\'s CSRF token.', LOGIN_FIX, code=4)
    if status == 404 and not raw.strip():
        return _failed('signature_rejected', 'X refused the request signature.')
    if status == 422 or _CONTRACT.search(messages):
        return _failed('contract_changed', f'X no longer accepts the variables this skill sends for {operation}.',
                       UPDATE_FIX)
    if status == 400 and 'features cannot be null:' in messages:
        names = re.findall(r'[A-Za-z_][A-Za-z_0-9]*', messages.split('features cannot be null:', 1)[1])
        verdict = _failed('features_missing', f'X asked for feature switches {operation} was sent without.')
        verdict.names = names
        return verdict
    if status in (200, 404) and errors and isinstance(body, dict) and 'data' not in body:
        return _failed('rotated', f'X did not run {operation} as sent; its query id may have changed.')
    if not isinstance(status, int) or status >= 400 or not body:
        return _failed('transient', f'X answered {operation} with HTTP {status} and no usable data.')
    value = at_root(body, root)
    if value is None and root.endswith('.timeline.instructions') and \
            at_root(body, root[:-len('.timeline.instructions')]) == {}:
        value = []  # an empty timeline object: nothing in it (measured: ListMemberships for an account in no lists)
    data = body.get('data') if isinstance(body, dict) else None
    if (operation == 'UserByScreenName' and data == {}) or (isinstance(value, dict) and value.get('__typename') in
                                                            ('UserUnavailable', 'TweetTombstone')):
        return Verdict('unavailable', TwitterError(9, 'The target is unavailable: deleted, suspended, protected or '
                                                      'never existed.', 'Tell the user; retrying will not change it.',
                                                   reason='unavailable'))
    malformed = root.endswith('instructions') and (not isinstance(value, list) or
                                                   any(not isinstance(item, dict) for item in value))
    if operation in ('UserByScreenName', 'UsersByScreenNames', 'Viewer') and value is not None:
        nodes = value if isinstance(value, list) else [value]
        malformed = malformed or any(node is not None and (not isinstance(node, dict) or (
            node.get('__typename') != 'UserUnavailable' and not str(node.get('rest_id', '')).isdigit())) for node in nodes)
    if value is None or malformed:
        return _failed('shape_changed', f'X\'s answer to {operation} is not where or what this skill expects.',
                       UPDATE_FIX)
    return Verdict('ok', root=value, warnings=errors)


def bucket_of(url):
    """The limit a request belongs to: a GraphQL operation's name, or a REST path without its query."""
    try:
        path = urlsplit(url or '').path
    except ValueError:
        return None
    match = re.match(r'^/i/api/graphql/[^/]+/([A-Za-z0-9_]+)$', path)
    return match[1] if match else (path or None)


def signal(kept):
    """The verdict on one response the tab's hook kept {path, status, codes, rate, html?} or a move {moved: path}."""
    moved = kept.get('moved')
    if isinstance(moved, str):
        if moved.startswith(LOCKED_PATHS):
            return _blocked('account_locked')
        if moved.startswith(LOGIN_PATHS):
            return _login()
        return Verdict('ok')
    status = kept.get('status')
    codes = {c for c in kept.get('codes') or [] if type(c) is int}
    if status == 403 and kept.get('html'):
        return _blocked('challenge')
    if codes & LOCK_CODES:
        return _blocked('account_locked')
    rate = kept.get('rate') if isinstance(kept.get('rate'), dict) else None
    if status == 429 or (rate and rate.get('remaining') == 0):
        return _rate_limited(bucket_of(kept.get('path')), rate.get('reset') if rate else None)
    if status == 401 or codes & LOGIN_CODES:
        return _login()
    return Verdict('ok')


def strongest(verdicts):
    """The verdict that weighs most for protection: a challenge, a lock, then a login; None when none is any.
    Operation limits are not compared here: each is recorded for its own bucket."""
    rank = {'challenge': 3, 'account_locked': 2}
    found = [v for v in verdicts if v.block or v.kind == 'login']
    return max(found, key=lambda v: rank.get(v.block, 1)) if found else None
