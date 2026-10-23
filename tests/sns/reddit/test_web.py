"""reddit/web at its interface: classification, targets, the read allow-list and request shapes, the limit headers,
records and comment-tree reading (fixtures classify, targets, routes, records_*, tree, paging, limits). Expected values
name only the fields a case is about."""
import pytest

from sns.errors import SnsError
from sns.reddit import web
from tests.sns.reddit.scene import fixture
from tests.sns.support.policies import POLICIES

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
OUTCOMES = {'blocked': 'blocked', 'login': 'login', 'unavailable': 'unavailable', 'empty': 'empty', 'failed': 'failed'}


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_classify(case):
    want = case['outcome']
    try:
        web.classify(case['envelope'], case['expect'], personal=case.get('personal', False),
                     wiki=case['expect'].startswith('wiki'))
        got = {'outcome': 'ok'}
    except SnsError as error:
        got = {'outcome': OUTCOMES[error.kind], 'reason': error.reason, 'message': error.message, 'fix': error.fix,
               'seconds': error.details.get('seconds')}
    assert got['outcome'] == want['outcome']
    if want['outcome'] in ('blocked', 'unavailable') and 'reason' in want:
        assert got['reason'] == want['reason']
    if 'block_seconds' in want:  # a 429 holds for Reddit's reset when it gave a usable one, else for the policy's time
        assert (got['seconds'] if got['seconds'] is not None else POLICIES['reddit'].hold_seconds) == want['block_seconds']
    if 'message_contains' in want:
        assert want['message_contains'] in got['message']
    if 'message_excludes' in want:
        assert want['message_excludes'] not in got['message']


@pytest.mark.parametrize('case', fixture('targets.json')['cases'], ids=lambda c: c['input'] or '(empty)')
def test_targets(case):
    if case.get('refused'):
        with pytest.raises(SnsError) as caught:
            web.parse_target(case['input'])
        assert caught.value.kind == 'argument'
        return
    target = web.parse_target(case['input'])
    subset(case['target'], {'kind': target.kind, 'sub': target.sub, 'post_id': target.post_id,
                            'comment_id': target.comment_id, 'user': target.user, 'url': target.url, 'page': target.page})


def test_each_command_takes_the_target_kinds_the_fixture_lists():
    """targets.json commands.accepts is the table the commands check their target against (it once disagreed with the
    code for related and wiki)."""
    assert {name: list(kinds) for name, kinds in web.ACCEPTS.items()} == fixture('targets.json')['commands']['accepts']


@pytest.mark.parametrize('value, command', [
    ('https://www.reddit.com/r/example/comments/aaa1/t/', 'post'), ('https://redd.it/aaa1', 'post'),
    ('https://www.reddit.com/r/example/s/AbC123', 'post'), ('https://www.reddit.com/r/example/', 'sub'),
    ('https://www.reddit.com/user/example_user/', 'profile'), ('https://www.reddit.com/r/example/wiki/faq', 'wiki'),
    ('reddit.com/r/example/', 'sub')])
def test_a_reddit_link_names_the_command_that_opens_it(value, command):
    assert web.locate(value) == (command, value)


@pytest.mark.parametrize('value', ['r/example', 'aaa1', 'u/example_user', 'https://x.com/jack/status/20',
                                   'https://evil.example/r/example/', 'https://www.reddit.com/nonsense/', '', None])
def test_what_is_not_a_reddit_link_belongs_to_no_command(value):
    assert web.locate(value) is None


ROUTES = fixture('routes.json')


@pytest.mark.parametrize('case', [c for c in ROUTES['paths']['cases']] +
                         [c for c in ROUTES['after_recon']['cases'] if 'path' in c], ids=lambda c: c['path'])
def test_paths(case):
    if case['allowed']:
        assert web.routes.bucket_of(case['path']) == case.get('bucket', 'general')
    else:
        with pytest.raises(SnsError):
            web.routes.bucket_of(case['path'])


def build(case):
    o, target = case['options'], case.get('target')
    surface = case['surface']
    routes = web.routes
    if surface == 'feed':
        return routes.feed(o['sort'], o.get('time'))
    if surface == 'sub':
        return routes.listing(web.parse_target(target).sub, o['sort'], after=o.get('after'))
    if surface == 'post':
        t = web.parse_target(target)
        return routes.post(t.post_id, o['sort'], t.comment_id, o.get('context'))
    if surface == 'morechildren':
        return routes.morechildren(target, o['children'], o['sort'])
    if surface == 'subtree':
        return routes.subtree(target, o['comment'], o['sort'])
    if surface == 'profile':
        return routes.profile(web.parse_target(target).user, o['type'], o['sort'], o.get('time'))
    if surface == 'search':
        sub = web.parse_target(target).sub if target else None
        return routes.search(o['text'], o['type'], o.get('sort', 'relevance'), sub=sub, nsfw=o.get('nsfw', False))
    if surface == 'related':
        return routes.related(web.parse_target(target).post_id)
    if surface == 'me':
        return routes.mine(o['collection'], 'example_viewer')
    if surface in ('about', 'rules'):
        t = web.parse_target(target)
        return routes.user(t.user) if t.kind == 'user' else (routes.community if surface == 'about' else routes.rules)(t.sub)
    if surface == 'me_check':
        return routes.me()
    raise AssertionError(surface)


@pytest.mark.parametrize('case', ROUTES['requests']['cases'], ids=lambda c: f"{c['surface']}-{c.get('target', '')}")
def test_requests(case):
    request = build(case)
    expected_path = case['path'].replace('/user/me/', '/user/example_viewer/')
    assert (request.path, request.query) == (expected_path, case['query'])
    web.routes.bucket_of(request.path)


@pytest.mark.parametrize('case', [c for c in ROUTES['after_recon']['cases'] if 'url' in c], ids=lambda c: c['url'])
def test_a_share_link_has_a_bucket_of_its_own_that_is_never_measured(case):
    request = web.routes.share(case['url'])
    assert request.bucket == case['bucket'] == 'share' and request.measured is False
    assert web.routes.feed('best').measured and web.routes.wiki_page('example', 'index').bucket == 'wiki'


def records(name):
    data = fixture(name)
    return data['cases'] + data.get('after_recon', {}).get('cases', [])


@pytest.mark.parametrize('case', records('records_posts.json'), ids=lambda c: c['name'])
def test_post_records(case):
    subset(case['record'], web.post(case['raw']))


@pytest.mark.parametrize('case', records('records_comments.json'), ids=lambda c: c['name'])
def test_comment_records(case):
    subset(case['record'], web.comment(case['raw']))


@pytest.mark.parametrize('case', records('records_entities.json'), ids=lambda c: c['name'])
def test_entity_records(case):
    raw = case['raw']
    built = {'t5': lambda: web.community(raw), 't2': lambda: web.user(raw), 'rule': lambda: web.rule(raw),
             't3': lambda: web.post(raw), 'moderator': lambda: web.moderator(raw),
             'wiki_page': lambda: web.wiki_page(raw['subreddit'], raw['page'], raw['data']),
             'wiki_index': lambda: web.wiki_index(raw['subreddit'], raw['data'])}[case['kind']]()
    subset(case['record'], built)


def test_every_record_carries_kind_id_url_and_created_at():
    """The head every record shares, whatever else it holds (plan: records)."""
    built = [web.post({'id': 'a'}), web.comment({'id': 'a', 'link_id': 't3_p'}), web.community({'display_name': 'x', 'id': 'a'}),
             web.user({'name': 'someone', 'id': 'a'}), web.moderator({'name': 'someone', 'id': 't2_a'}),
             web.wiki_page('example', 'index', {'content_md': 'x', 'revision_id': 'r'}),
             web.wiki_index('example', ['index'])]
    for record in built:
        assert {'kind', 'id', 'url', 'created_at'} <= set(record), record['kind']
        assert record['url'].startswith('https://www.reddit.com/')


def test_media_is_numbered_in_the_order_reddit_shows_it_and_a_video_keeps_its_poster():
    gallery = web.post({'id': 'g', 'is_gallery': True,
                        'gallery_data': {'items': [{'media_id': 'b'}, {'media_id': 'gone', 'is_deleted': True},
                                                   {'media_id': 'a', 'caption': 'second'}]},
                        'media_metadata': {'a': {'e': 'Image', 's': {'u': 'https://i.redd.it/a.jpg', 'x': 10, 'y': 20}},
                                           'b': {'e': 'Image', 's': {'u': 'https://i.redd.it/b.jpg', 'x': 30, 'y': 40}}}})
    assert [(m['n'], m['media_id'], m['alt'], m['width']) for m in gallery['media']] == [(1, 'b', '', 30), (2, 'a', 'second', 10)]
    clip = web.post({'id': 'v', 'is_video': True, 'secure_media': {'reddit_video': {'fallback_url': 'https://v.redd.it/c.mp4'}},
                     'preview': {'images': [{'source': {'url': 'https://preview.redd.it/c.jpg', 'width': 640, 'height': 360}}]}})
    assert clip['media'][0]['image_url'] == 'https://preview.redd.it/c.jpg' and clip['media'][0]['video_url'] == 'https://v.redd.it/c.mp4'
    assert web.media_items({'k': {'s': {'u': 'https://i.redd.it/k.png'}}})[0]['n'] == 1
    assert web.media_items({'k': {'e': 'Image'}}) == [], 'an entry with no source takes no number'


@pytest.mark.parametrize('case', fixture('tree.json')['walk']['cases'], ids=lambda c: c['name'])
def test_tree_walk(case):
    raw = case['raw']
    try:
        if isinstance(raw, dict) and 'json' in raw:
            items = web.expansion(raw)
        elif isinstance(raw, list):
            items = web.thread(raw)[1]
        else:
            items = web.expansion({'json': {'errors': [], 'data': {'things': [raw]}}})
        ok = True
    except SnsError as error:
        assert error.kind == 'failed' and error.reason == 'shape_changed'
        ok = False
    assert ok == case['ok']
    if ok and 'things' in case:
        names = [i['record']['id'] if i['type'] == 'comment' else 'more' for i in items]
        assert names == [t for t in case['things'] if not t.startswith('t3_')]


def test_continue_this_thread_is_a_gap_without_ids():
    items = web.expansion({'json': {'errors': [], 'data': {'things': [
        {'kind': 'more', 'data': {'count': 0, 'name': 't1__', 'id': '_', 'parent_id': 't1_abc', 'depth': 2,
                                  'children': []}}]}}})
    assert items == [{'type': 'gap', 'parent': 't1_abc', 'ids': [], 'count': 0}]


@pytest.mark.parametrize('case', fixture('paging.json')['listing']['cases'], ids=lambda c: c['name'])
def test_listing_pages(case):
    listing = {'kind': 'Listing', 'data': {'after': case.get('after'), 'children': [case['child']] if 'child' in case
                                           else []}}
    try:
        found, after = web.page(listing)
        ok = True
    except SnsError:
        ok = False
    assert ok == case['ok']
    if ok and 'id' in case:
        assert found[0]['id'] == case['id']


# --- Reddit's rate-limit headers → a limits.Fact (fixture limits.json) -------------------------------------------

def headers(used, remaining, reset):
    return {'used': used, 'remaining': remaining, 'reset': reset}


def test_valid_headers_state_a_window_the_reset_becomes_an_epoch():
    """valid-headers-update-the-bucket: limit = used + remaining, reset_at = now + seconds-to-reset."""
    fact = web.limit_fact(headers('4', '96.0', '300'), 1000.0)
    assert (fact.limit, fact.remaining, fact.reset_at) == (100.0, 96.0, 1300.0)


@pytest.mark.parametrize('given', [headers('51', None, '299'), headers('51', '-1', '299'), headers('x', '48', 'nan'),
                                   headers('51', 'inf', '299'), headers(True, '48', '299'), headers(None, None, None),
                                   None, {}, 'not a dict'])
def test_unusable_headers_state_no_window(given):
    """invalid-header-values: only a set of three finite non-negative numbers is a statement."""
    assert web.limit_fact(given, 1000.0) is None


def test_a_reset_is_usable_alone_for_a_429():
    assert web.reset_seconds(headers(None, None, '212')) == 212 and web.reset_seconds(headers('1', '1', '-3')) is None
    assert web.reset_seconds(headers('1', '1', 'x')) is None and web.reset_seconds(None) is None


def test_the_policy_is_the_plans_reddit_row():
    from sns.reddit import PLATFORM
    assert PLATFORM.policy == POLICIES['reddit']
    assert (PLATFORM.key, PLATFORM.title, PLATFORM.site, PLATFORM.transport) == ('reddit', 'Reddit', 'reddit.com', 'fetch')
    assert PLATFORM.window.jitter == 600 and PLATFORM.unblock_scope == 'general' and PLATFORM.idle_action is None
