"""reddit_web at its interface: classification, targets, the read allow-list and request shapes, records and comment-tree
reading (fixtures classify, targets, routes, records_*, tree). Expected values name only the fields a case is about."""
import json

import pytest

from conftest import fixture
from reddit import reddit_web
from reddit.errors import RedditError
from reddit.reddit_web import routes

P3_EXPECTS = ('listing', 'thing:t2', 'thing:t5', 'me', 'post_pair', 'duplicates', 'rules', 'morechildren', 'wiki_page',
              'wiki_index', 'moderators')


def subset(expected, actual, path='$'):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f'{path}: {actual!r}'
        for key, value in expected.items():
            assert key in actual, f'{path}.{key} missing'
            subset(value, actual[key], f'{path}.{key}')
    elif isinstance(expected, list) and expected and isinstance(expected[0], dict):
        assert isinstance(actual, list) and len(actual) == len(expected), f'{path}: {actual!r}'
        for index, (e, a) in enumerate(zip(expected, actual)):
            subset(e, a, f'{path}[{index}]')
    else:
        assert expected == actual, f'{path}: expected {expected!r}, got {actual!r}'


CLASSIFY = fixture('classify.json')
CASES = [c for c in CLASSIFY['cases'] + CLASSIFY['after_recon']['cases'] if c['expect'] in P3_EXPECTS]
OUTCOMES = {5: 'blocked', 4: 'login', 9: 'unavailable', 7: 'empty', 6: 'failed'}


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_classify(case):
    want = case['outcome']
    try:
        reddit_web.classify(case['envelope'], case['expect'], personal=case.get('personal', False),
                            wiki=case['expect'].startswith('wiki'))
        got = {'outcome': 'ok'}
    except RedditError as error:
        got = {'outcome': OUTCOMES[error.code], 'reason': error.reason, 'message': error.message, 'fix': error.fix}
    assert got['outcome'] == want['outcome']
    if want['outcome'] in ('blocked', 'unavailable') and 'reason' in want:
        assert got['reason'] == want['reason']
    if 'block_seconds' in want:
        assert f'after {want["block_seconds"]} seconds' in got['fix']
    if 'message_contains' in want:
        assert want['message_contains'] in got['message']
    if 'message_excludes' in want:
        assert want['message_excludes'] not in got['message']


@pytest.mark.parametrize('case', fixture('targets.json')['cases'], ids=lambda c: c['input'] or '(empty)')
def test_targets(case):
    if case.get('refused'):
        with pytest.raises(RedditError) as caught:
            reddit_web.parse_target(case['input'])
        assert caught.value.code == 2
        return
    target = reddit_web.parse_target(case['input'])
    subset(case['target'], {'kind': target.kind, 'sub': target.sub, 'post_id': target.post_id,
                            'comment_id': target.comment_id, 'user': target.user, 'url': target.url, 'page': target.page})


ROUTES = fixture('routes.json')


@pytest.mark.parametrize('case', [c for c in ROUTES['paths']['cases']] +
                         [c for c in ROUTES['after_recon']['cases'] if 'path' in c], ids=lambda c: c['path'])
def test_paths(case):
    if case['allowed']:
        assert routes.bucket_of(case['path']) == case.get('bucket', 'general')
    else:
        with pytest.raises(RedditError):
            routes.bucket_of(case['path'])


def build(case):
    o, target = case['options'], case.get('target')
    surface = case['surface']
    if surface == 'feed':
        return routes.feed(o['sort'], o.get('time'))
    if surface == 'sub':
        return routes.listing(reddit_web.parse_target(target).sub, o['sort'], after=o.get('after'))
    if surface == 'post':
        t = reddit_web.parse_target(target)
        return routes.post(t.post_id, o['sort'], t.comment_id, o.get('context'))
    if surface == 'morechildren':
        return routes.morechildren(target, o['children'], o['sort'])
    if surface == 'subtree':
        return routes.subtree(target, o['comment'], o['sort'])
    if surface == 'profile':
        return routes.profile(reddit_web.parse_target(target).user, o['type'], o['sort'], o.get('time'))
    if surface == 'search':
        sub = reddit_web.parse_target(target).sub if target else None
        return routes.search(o['text'], o['type'], o.get('sort', 'relevance'), sub=sub, nsfw=o.get('nsfw', False))
    if surface == 'related':
        return routes.related(reddit_web.parse_target(target).post_id)
    if surface == 'me':
        return routes.mine(o['collection'], 'example_viewer')
    if surface in ('about', 'rules'):
        t = reddit_web.parse_target(target)
        return routes.user(t.user) if t.kind == 'user' else (routes.community if surface == 'about' else routes.rules)(t.sub)
    if surface == 'me_check':
        return routes.me()
    raise AssertionError(surface)


@pytest.mark.parametrize('case', ROUTES['requests']['cases'], ids=lambda c: f"{c['surface']}-{c.get('target', '')}")
def test_requests(case):
    request = build(case)
    expected_path = case['path'].replace('/user/me/', '/user/example_viewer/')
    assert (request.path, request.query) == (expected_path, case['query'])
    routes.bucket_of(request.path)


def test_a_share_link_is_unmetered():
    request = routes.share('https://www.reddit.com/r/example/s/AbC123')
    assert request.bucket == 'share' and request.metered is False


def records(name):
    data = fixture(name)
    return data['cases'] + data.get('after_recon', {}).get('cases', [])


@pytest.mark.parametrize('case', records('records_posts.json'), ids=lambda c: c['name'])
def test_post_records(case):
    subset(case['record'], reddit_web.post(case['raw']))


@pytest.mark.parametrize('case', records('records_comments.json'), ids=lambda c: c['name'])
def test_comment_records(case):
    subset(case['record'], reddit_web.comment(case['raw']))


@pytest.mark.parametrize('case', records('records_entities.json'), ids=lambda c: c['name'])
def test_entity_records(case):
    raw = case['raw']
    built = {'t5': lambda: reddit_web.community(raw), 't2': lambda: reddit_web.user(raw), 'rule': lambda: reddit_web.rule(raw),
             't3': lambda: reddit_web.post(raw), 'moderator': lambda: reddit_web.moderator(raw),
             'wiki_page': lambda: reddit_web.wiki_page(raw['subreddit'], raw['page'], raw['data']),
             'wiki_index': lambda: reddit_web.wiki_index(raw['subreddit'], raw['data'])}[case['kind']]()
    subset(case['record'], built)


@pytest.mark.parametrize('case', fixture('tree.json')['walk']['cases'], ids=lambda c: c['name'])
def test_tree_walk(case):
    raw = case['raw']
    body = raw if isinstance(raw, dict) and 'json' in raw else None
    try:
        if body is not None:
            items = reddit_web.expansion(body)
        elif isinstance(raw, list):
            items = reddit_web.thread(raw)[1]
        else:
            items = reddit_web.expansion({'json': {'errors': [], 'data': {'things': [raw]}}})
        ok = True
    except RedditError as error:
        assert error.code == 6
        ok = False
    assert ok == case['ok']
    if ok and 'things' in case:
        names = [i['record']['id'] if i['type'] == 'comment' else 'more' for i in items]
        assert names == [t for t in case['things'] if not t.startswith('t3_')]


def test_continue_this_thread_is_a_gap_without_ids():
    items = reddit_web.expansion({'json': {'errors': [], 'data': {'things': [
        {'kind': 'more', 'data': {'count': 0, 'name': 't1__', 'id': '_', 'parent_id': 't1_abc', 'depth': 2,
                                  'children': []}}]}}})
    assert items == [{'type': 'gap', 'parent': 't1_abc', 'ids': [], 'count': 0}]


@pytest.mark.parametrize('case', fixture('paging.json')['listing']['cases'], ids=lambda c: c['name'])
def test_listing_pages(case):
    listing = {'kind': 'Listing', 'data': {'after': case.get('after'), 'children': [case['child']] if 'child' in case
                                           else []}}
    try:
        found, after = reddit_web.page(listing)
        ok = True
    except RedditError:
        ok = False
    assert ok == case['ok']
    if ok and 'id' in case:
        assert found[0]['id'] == case['id']
