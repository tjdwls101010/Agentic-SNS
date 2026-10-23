"""One answer from Reddit → its parsed body, or the failure it means.

Order matters: a rate limit (429) is decided before the body is looked at, then a browser challenge (an HTML 403
mentioning js_challenge), then server errors and non-JSON bodies, then 404 and 403 reasons, then the logged-out
answers, then whether the body has the shape the request expected. Only a listing or a comment expansion can be
explicitly empty. A 429 and a challenge are raised as the failure they mean (reason rate_limit / challenge); the client
turns them into the stop it records (a hold, a person block) before leaving the request's slot.
"""
import json
import math

from sns.errors import SnsError

from sns.reddit.web.headers import reset_seconds

CLOSED = ('private', 'gold_only', 'quarantined', 'banned', 'suspended', 'user_suspended')
_LOGIN = 'Log in to Reddit in the Aside browser, then run doctor.'
_RETRY = 'Check Reddit in the Aside browser; retry later if it is unavailable.'
_SHAPE = ('Reddit answered in a shape this skill does not know.', 'Retry once; if it persists, Reddit changed its '
                                                                 'response — report it so the skill can be updated.')


def outcome(error):
    """The request-log label of an answer that raised."""
    return {'rate_limit': 'rate_limited', 'challenge': 'challenge'}.get(error.reason) or \
        {'login': 'login_required', 'unavailable': 'unavailable', 'empty': 'empty'}.get(error.kind, 'failed')


def _listing(body, replies_only=False):
    pending = [(body, replies_only)]
    while pending:
        listing, only_comments = pending.pop()
        if (not isinstance(listing, dict) or listing.get('kind') != 'Listing' or not isinstance(listing.get('data'), dict)
                or not isinstance(listing['data'].get('children'), list)):
            return False
        kinds = ('t1', 'more') if only_comments else ('t1', 't2', 't3', 't5', 'more')
        for child in listing['data']['children']:
            if not isinstance(child, dict) or child.get('kind') not in kinds or not isinstance(child.get('data'), dict):
                return False
            if child['kind'] == 't1':
                replies = child['data'].get('replies')
                if replies not in (None, ''):
                    pending.append((replies, True))
    return True


def classify(envelope, expect, *, personal=False, wiki=False):
    """The parsed body of a 2xx answer of the expected shape; otherwise raise the failure it means (see the module)."""
    status, raw, url = envelope['status'], envelope['body'], envelope['url']
    if status == 429:
        seconds = reset_seconds(envelope.get('ratelimit'))
        raise SnsError('blocked', 'Reddit rate-limited this account.', 'Stop requests until the limit passes.',
                       reason='rate_limit', seconds=seconds if seconds is None else math.ceil(seconds))
    html = raw.lstrip().startswith('<')
    if status == 403 and html and 'js_challenge' in (raw + url).lower():
        raise SnsError('blocked', 'Reddit showed a browser challenge for this account.',
                       'Stop. After a person checks Reddit in the Aside browser (and solves the challenge there), '
                       'run doctor --unblock.', reason='challenge')
    if status >= 500 or not raw or html:
        raise SnsError('failed', f'Reddit returned an unavailable or non-JSON response (HTTP {status}).', _RETRY)
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise SnsError('failed', 'Reddit returned invalid JSON.', _RETRY) from None
    if status == 404:
        raise SnsError('unavailable', 'This Reddit target does not exist (or this account cannot see it).',
                       'Tell the user; check the name or link. Retrying does not change it.', reason='not_found')
    if status == 403 and isinstance(body, dict):
        reason = str(body.get('reason') or '')[:120]
        if reason in CLOSED or (wiki and reason):
            raise SnsError('unavailable', f'This Reddit target is closed to this account ({reason}).',
                           'Tell the user; retrying does not change it.', reason=reason)
        raise SnsError('failed', f'Reddit refused the request (reason={reason}).', _RETRY)
    if not 200 <= status < 300:
        raise SnsError('failed', f'Unexpected Reddit HTTP status {status}.', _RETRY)
    if expect == 'me':
        if body == {}:
            raise SnsError('login', 'Reddit login is required in the Aside browser.', _LOGIN, reason='logged_out')
        if isinstance(body, dict) and body.get('kind') == 't2' and isinstance(body.get('data'), dict):
            name = body['data'].get('name')
            if not name:
                raise SnsError('login', 'Reddit login is required in the Aside browser.', _LOGIN, reason='logged_out')
            if not isinstance(name, str):
                raise SnsError('failed', *_SHAPE)
            return body
        raise SnsError('failed', *_SHAPE)
    if personal and _listing(body) and body['data'].get('modhash') == '':
        raise SnsError('login', 'Reddit login is required in the Aside browser.', _LOGIN, reason='logged_out')
    empty = False
    if expect == 'listing':
        valid = _listing(body)
        empty = valid and not body['data']['children']
    elif expect in ('thing:t2', 'thing:t5'):
        valid = isinstance(body, dict) and body.get('kind') == expect.split(':')[1] and isinstance(body.get('data'), dict)
    elif expect in ('post_pair', 'duplicates'):
        valid = (isinstance(body, list) and len(body) == 2 and all(_listing(item) for item in body)
                 and len(body[0]['data']['children']) == 1 and body[0]['data']['children'][0]['kind'] == 't3')
        if valid:
            kinds = {'t3'} if expect == 'duplicates' else {'t1', 'more'}
            valid = all(child['kind'] in kinds for child in body[1]['data']['children'])
    elif expect == 'rules':
        valid = isinstance(body, dict) and isinstance(body.get('rules'), list) and \
            all(isinstance(rule, dict) for rule in body['rules'])
    elif expect == 'morechildren':
        data = body.get('json') if isinstance(body, dict) else None
        things = data['data'].get('things') if isinstance(data, dict) and data.get('errors') == [] and \
            isinstance(data.get('data'), dict) else None
        valid = isinstance(things, list) and _listing({'kind': 'Listing', 'data': {'children': things}}) and \
            all(thing['kind'] in ('t1', 'more') for thing in things)
        empty = valid and not things
    elif expect == 'wiki_page':
        valid = isinstance(body, dict) and body.get('kind') == 'wikipage' and isinstance(body.get('data'), dict) and \
            isinstance(body['data'].get('content_md'), str)
    elif expect == 'wiki_index':
        valid = isinstance(body, dict) and body.get('kind') == 'wikipagelisting' and isinstance(body.get('data'), list) \
            and all(isinstance(name, str) for name in body['data'])
    elif expect == 'moderators':
        valid = isinstance(body, dict) and body.get('kind') == 'UserList' and isinstance(body.get('data'), dict) and \
            isinstance(body['data'].get('children'), list) and all(isinstance(c, dict) for c in body['data']['children'])
    else:
        raise SnsError('argument', f'Unknown expected response: {expect}.', 'Report this as a skill bug.')
    if not valid:
        raise SnsError('failed', *_SHAPE, reason='shape_changed')
    if empty:
        raise SnsError('empty', 'Reddit returned an explicitly empty result.', 'Try another target, order or window.')
    return body
