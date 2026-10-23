"""Reddit's answers in miniature (synthetic names and ids only): the things a listing, a post read, a comment expansion,
a community or a user answer holds."""
from datetime import datetime, timezone


def epoch(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def listing(children, after=None, modhash='m0d'):
    return {'kind': 'Listing', 'data': {'after': after, 'modhash': modhash, 'children': children}}


def post(identity, created=None, **extra):
    return {'kind': 't3', 'data': {'id': identity, 'name': f't3_{identity}', 'title': f'title {identity}', 'is_self': True,
                                   'subreddit': extra.pop('subreddit', 'example'), 'author': 'someone',
                                   'permalink': f'/r/example/comments/{identity}/t/',
                                   'created_utc': created if created is not None else 1760000000, **extra}}


def t1(identity, parent, replies=(), body=None, **extra):
    data = {'id': identity, 'name': f't1_{identity}', 'parent_id': parent, 'link_id': 't3_aaa1',
            'author': f'user_{identity}', 'body': body or f'comment {identity}',
            'permalink': f'/r/example/comments/aaa1/a_title/{identity}/', 'created_utc': 1760000100, 'score': 3,
            'replies': {'kind': 'Listing', 'data': {'children': list(replies)}} if replies else '', **extra}
    return {'kind': 't1', 'data': data}


def more(parent, ids, count=None):
    return {'kind': 'more', 'data': {'parent_id': parent, 'children': list(ids), 'count': count or len(ids),
                                     'id': ids[0] if ids else '_', 'name': f't1_{ids[0]}' if ids else 't1__'}}


def pair(comments, **post_fields):
    head = {'id': 'aaa1', 'name': 't3_aaa1', 'title': 'A title', 'selftext': 'The whole body. ' * 30, 'is_self': True,
            'subreddit': 'example', 'author': 'poster', 'permalink': '/r/example/comments/aaa1/a_title/',
            'num_comments': 9, 'created_utc': 1760000000, **post_fields}
    return [{'kind': 'Listing', 'data': {'children': [{'kind': 't3', 'data': head}]}},
            {'kind': 'Listing', 'data': {'children': list(comments)}}]


def things(*items):
    return {'json': {'errors': [], 'data': {'things': list(items)}}}


def profile_comment(identity):
    return {'kind': 't1', 'data': {'id': identity, 'name': f't1_{identity}', 'parent_id': 't3_p', 'link_id': 't3_p',
                                   'body': f'said {identity}', 'author': 'example_user', 'subreddit': 'example',
                                   'permalink': f'/r/example/comments/p/t/{identity}/', 'created_utc': 1760000000}}


def about_user(link_karma, comment_karma):
    return {'kind': 't2', 'data': {'id': 'u1', 'name': 'example_user', 'link_karma': link_karma,
                                   'comment_karma': comment_karma, 'created_utc': 1500000000}}


PERMALINK = 'https://www.reddit.com/r/example/comments/aaa1/a_title/'
CHALLENGE = {'status': 403, 'body': '<html><script src="/js_challenge.js"></script></html>'}
