"""One classification path for every answer, and its step order is the contract.

Naver answers a failure in whichever envelope the surface uses, so the same HTTP 404 means "no such blog" on one host
and nothing at all on another. The row declares its envelope; the order decides which reading wins when two apply:
a transport failure beats a block, a block a login wall, a login wall a missing target, a missing target a contract
error, and a policy restriction is read only from an otherwise valid answer — reporting the weaker hides the stronger.
A 429 is raised as a failure of reason rate_limit; the client turns it into the hold it records before leaving the
request's slot.
"""
import json
import re
from urllib.parse import urljoin, urlsplit

from sns.errors import SnsError

from sns.naver_blog.web.routes import operation

XSSI = ")]}',"
MISSING = {'not_exist_blog', 'not_exist_post', 'blog_id_invalidate', 'not_exist_category'}
BAD_ARGUMENT = {'param_is_invalidate', 'bad_request'}
NOT_LOGGED_IN = {'notlogined', 'not_logined', 'need_login', 'login_required'}
RESTRICTIONS = ('blockedByBifrostShield', 'isBlockedByBifrostShield', 'suicideWord')
_DRIFT = 'Run doctor; the response shape changed. Report it if it repeats.'
_RETRY = 'Wait a little and run the same command again; no automatic retry was made.'
_LOGIN = 'Log in to Naver in the Aside browser, then run doctor.'


def drift(message):
    return SnsError('failed', message, _DRIFT, reason='drift')


def at(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def parse_json(body):
    """Strip the section hosts' XSSI prefix, then parse; a truncated body raises ValueError (a transient failure)."""
    text = (body or '').lstrip()
    if text.startswith(XSSI):
        text = text[len(XSSI):].lstrip()
    return json.loads(text)


def _login_hop(row, response):
    """An exact nid.naver.com host, or a /nidlogin path on Naver's own hosts (or relative): never a lookalike."""
    for candidate in (response.get('location') or '', response.get('url') or ''):
        if not candidate:
            continue
        try:
            url = urlsplit(urljoin('https://' + row.host.lstrip('*'), candidate))
        except ValueError:
            continue
        host = (url.hostname or '').lower()
        naver = host == 'naver.com' or host.endswith('.naver.com')
        if host == 'nid.naver.com' or (naver and url.path.lower().startswith('/nidlogin')):
            return True
    return False


def _error_of(payload):
    if not isinstance(payload, dict):
        return '', ''
    error = payload.get('error')
    if isinstance(error, dict):
        return str(error.get('code') or ''), str(error.get('message') or '')
    if payload.get('success') is False or str(payload.get('code') or '') not in ('', '1000'):
        return str(payload.get('code') or ''), str(payload.get('message') or '')
    return '', ''


def _restricted(payload):
    """Policy flags ride anywhere in the envelope; only a true one restricts."""
    found, stack = [], [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key in RESTRICTIONS and child is True:
                    found.append(key)
                elif key == 'queryControlInfo' and isinstance(child, dict) and child.get('isForbidden') is True:
                    found.append('isForbidden')
                else:
                    stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
    return sorted(set(found))


def classify(name, response, ids=None):
    """The parsed answer (a dict for JSON, the body for HTML, the response itself for a hop or an image), or raise."""
    row = operation(name)
    ids = ids or {}
    status, body = response['status'], response.get('body') or ''
    # 1. Transport: nothing below can read a body that never arrived intact.
    if status >= 500:
        raise SnsError('failed', f'Naver answered HTTP {status}.', _RETRY, reason='transient')
    # 2. Rate limit: 429 is the only one Naver has been seen to send; it passes by itself.
    if status == 429:
        raise SnsError('blocked', 'Naver rate-limited this account.', 'Stop requests to Naver Blog; the limit passes '
                                                                       'by itself.', reason='rate_limit')
    # 3. Login wall.
    if _login_hop(row, response):
        raise SnsError('login', 'Naver login is required.', _LOGIN, reason='login')
    if row.envelope in ('hop', 'image'):
        return response
    payload, unparsed = None, False
    if row.accept == 'json':
        try:
            payload = parse_json(body)
        except ValueError:
            unparsed = True
    code, message = _error_of(payload)
    if row.login and code.lower() in NOT_LOGGED_IN:
        raise SnsError('login', 'Naver login is required for this surface.', _LOGIN, reason='login')
    # 4. The target is gone, closed or not ours.
    if row.envelope == 'html':
        page = re.search(r'MobileErrorView\.naver\?errorType=([A-Za-z0-9_]+)', body)
        if status == 404 and page:
            if page[1] == 'noPost':
                raise SnsError('unavailable', 'That post is deleted, private or for neighbors only (they answer alike).',
                               'Check the post number; this account cannot read it.', reason='noPost')
            raise SnsError('failed', f'Naver answered with an error page this reader does not know ({page[1]}).',
                           'Open the post once in Aside and report the errorType.', reason=page[1])
    if status == 403 and code == 'not_blog_owner':
        raise SnsError('unavailable', 'This surface belongs to its blog owner only.', 'Read what the blog shows '
                                                                                      'publicly instead.',
                       reason='owner_only')
    if code in MISSING:
        raise SnsError('unavailable', 'That blog, post or category does not exist, or this account cannot read it.',
                       'Check the id; a blog\'s own domain address resolves to a different id.', reason=code)
    # 5. Arguments the CLI should have refused before spending a request.
    if code in BAD_ARGUMENT:
        raise SnsError('argument', f'Naver rejected a request parameter ({code}).',
                       'This is a bug in the skill, not in your command; report the command you ran.',
                       reason='argument')
    # 6. Contract: an empty 403 is the referer contract; everything unexplained lands here.
    if status == 403:
        raise drift('Naver refused the request without a reason (the referer contract may have changed).')
    if status >= 400:
        raise SnsError('failed', f'Naver answered HTTP {status}.', _RETRY, reason='transient')
    if 300 <= status < 400:
        if row.accept == 'html' and not response.get('location'):
            raise drift('Naver redirected without saying where.')
        raise SnsError('failed', f'Naver redirected a request that does not redirect (HTTP {status}).', _RETRY,
                       reason='transient')
    if row.envelope == 'html':
        return body
    if unparsed or not isinstance(payload, dict):
        raise SnsError('failed', 'Naver returned incomplete or unrecognized data.', _RETRY, reason='transient')
    if code:
        raise drift(f'Naver reported {code}: {message[:120]}')
    if row.envelope == 'mblog' and payload.get('isSuccess') is not True:
        raise drift('The answer does not carry its success flag.')
    if row.envelope == 'cbox' and payload.get('success') is not True:
        raise drift('The comment box answer does not carry its success flag.')
    if row.leaf:
        leaf = at(payload, row.leaf)
        if leaf is None and row.empty_when_missing and isinstance(payload.get('result'), dict):
            leaf = []
        wanted = {'list': list, 'dict': dict, 'int': int}.get(row.leaf_type)
        if wanted and not isinstance(leaf, wanted):
            raise drift(f'Expected a {row.leaf_type} at {row.leaf}.')
    if row.identity == 'objectId':
        for item in at(payload, row.leaf) or []:
            object_id = str(item.get('objectId') or '') if isinstance(item, dict) else ''
            if object_id and object_id.split('_')[-1] != str(ids.get('logNo')):
                raise drift(f'Naver answered about {object_id}, not post {ids.get("logNo")}.')
    elif row.identity and not row.resolves_identity and ids.get('blogId'):
        got = at(payload, row.identity)
        if got is not None and str(got) != str(ids['blogId']):
            raise drift(f'Naver answered about {got}, not {ids["blogId"]}.')
    # 7. Policy restriction: what arrived is kept on the error; a restriction is not an empty shelf.
    flags = _restricted(payload)
    if flags:
        error = SnsError('partial', 'Naver restricted this query (' + ', '.join(flags) + ').',
                         'Rephrase the keyword; adult, forbidden and shielded queries answer this way.',
                         reason='restricted')
        error.payload = payload
        raise error
    return payload
