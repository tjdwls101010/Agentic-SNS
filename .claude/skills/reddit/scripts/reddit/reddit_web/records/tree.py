"""Reddit's comment-tree shapes → comments and gaps in the skill's terms.

A post read answers [post Listing, comments Listing] with replies nested inside each t1; a comment expansion
(morechildren) answers {json: {errors: [], data: {things: [...]}}} with things flat, each naming its parent. A gap is a
`more` item: ids of comments not sent (count is how many hide behind them, descendants included), or 'continue this
thread' — a more with id '_', no ids and count 0, which only a read of the parent comment's subtree opens. Items come
out depth-first in the order Reddit sent them, a comment before what hangs under it. Anything malformed is a failed
read (6): a tree this skill cannot place must not be guessed at.
"""
import re

from reddit.errors import RedditError
from reddit.reddit_web.records.comments import comment
from reddit.reddit_web.records.posts import post

_ID = re.compile(r'(?:t1_)?([A-Za-z0-9]+)')


def _malformed():
    return RedditError(6, 'Reddit sent a comment tree this skill cannot read.', 'Retry once; if it persists, report it '
                                                                               '(Reddit may have changed its format).',
                       reason='shape_changed')


def _require(condition):
    if not condition:
        raise _malformed()


def _items(children, depth, out):
    """Walk one Listing's children (nested replies included) into out, depth-first."""
    _require(isinstance(children, list))
    for child in children:
        _require(isinstance(child, dict) and isinstance(child.get('data'), dict))
        kind, data = child.get('kind'), child['data']
        _require(isinstance(data.get('parent_id', ''), str))
        if kind == 'more':
            ids = data.get('children')
            _require(isinstance(ids, list) and all(isinstance(i, str) and _ID.fullmatch(i) for i in ids))
            count = data.get('count', 0)
            _require(type(count) is int and count >= 0)
            out.append({'type': 'gap', 'parent': data.get('parent_id'), 'ids': [_ID.fullmatch(i)[1] for i in ids],
                        'count': count})
            continue
        _require(kind == 't1')
        identity, name = data.get('id'), data.get('name')
        _require(isinstance(identity, str) and re.fullmatch(r'[A-Za-z0-9]+', identity))
        _require(name in (None, 't1_' + identity))
        _require(isinstance(data.get('parent_id'), str) and data['parent_id'])
        sent = data.get('depth', depth)
        _require(type(sent) is int and sent >= 0)
        out.append({'type': 'comment', 'record': comment(data)})
        replies = data.get('replies', '')
        _require(replies in ('', None) or (isinstance(replies, dict) and replies.get('kind') == 'Listing'
                                          and isinstance(replies.get('data'), dict)))
        if replies:
            _items(replies['data'].get('children'), depth + 1, out)


def thread(body):
    """(post record, items) of a post read; items are {type: comment, record} and {type: gap, parent, ids, count}."""
    _require(isinstance(body, list) and len(body) == 2)
    head = body[0]['data']['children'][0]['data']
    _require(isinstance(head.get('id'), str) and head.get('name') in (None, 't3_' + head.get('id', '')))
    out = []
    _items(body[1]['data']['children'], 0, out)
    return post(head), out


def expansion(body):
    """Items of a morechildren answer, flat as Reddit sent them (each names its parent)."""
    envelope = body.get('json') if isinstance(body, dict) else None
    _require(isinstance(envelope, dict) and envelope.get('errors') == [] and isinstance(envelope.get('data'), dict))
    data = envelope['data']
    out = []
    _items(data.get('things'), 0, out)
    return out
