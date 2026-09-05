"""Real read-only journeys assert invariants, not volatile Reddit counts."""
import pytest
from reddit_skill.reddit import parser, validate
from reddit_skill import _cmds_meta

pytestmark = pytest.mark.live


def execute(*words):
    args = parser().parse_args(list(words))
    validate(args)
    if args.command in ('doctor', 'about', 'schema'):
        return _cmds_meta.run(args)
    if args.command in ('post', 'comments'):
        from reddit_skill._cmds_thread import run
    else:
        from reddit_skill._cmds_browse import run
    return run(args)


def test_doctor():
    result = execute('doctor')
    assert result['doctor']['account'].startswith('u/')
    assert result['requests'] == 1
    assert result['budget']['expires_at'] > result['budget']['observed_at']


def test_browse_real_listings_and_server_continuation():
    import shlex
    home = execute('home', '--limit', '3')
    assert all(item['fullname'].startswith('t3_') for item in home['results'])
    first = execute('sub', 'r/python', '--sort', 'new', '--limit', '3')
    assert first['next']
    second = execute(*shlex.split(first['next'])[2:], '--limit', '101')
    assert second['requests'] >= 1
    identities = [item['fullname'] for item in first['results'] + second['results']]
    assert len(identities) == len(set(identities))
    for words in [('user', 'u/spez', '--type', 'overview'), ('me', 'subs'), ('sub', 'https://www.reddit.com/r/ClaudeAI/')]:
        result = execute(*words, '--limit', '3')
        assert result.get('code', 0) == 0, result.get('message')
        assert all(item['fullname'].startswith(('t1_', 't2_', 't3_', 't5_')) for item in result['results'])


def test_large_thread_cache_expansion_and_comment_anchor():
    import shlex
    from reddit_skill import _transport
    captured = []
    original = _transport.run_snippet
    def observe(name, args):
        envelope = original(name, args)
        if args.get('path') == '/api/morechildren.json':
            import json
            body = json.loads(envelope['body'])
            things = body['json']['data']['things']
            captured.append((set(args['query']['children'].split(',')), {t['data']['id'] for t in things if t['kind'] == 't1'}))
        return envelope
    _transport.run_snippet = observe
    try:
        discovery = execute('sub', 'r/AskReddit', '--sort', 'top', '--time', 'week', '--limit', '100')
        candidates = [p for p in discovery['results'] if (p['num_comments'] or 0) >= 2000]
        assert candidates, 'No large-thread sample in the current top-week listing.'
        target = candidates[0]['url']
        opened = execute('post', target, '--limit', '25')
        assert opened['requests'] == 1
        cached = execute(*shlex.split(opened['next'])[2:], '--limit', '5000', '--depth', '100')
        assert cached['requests'] == 0
        if cached.get('next') and cached['thread']['pending_ids']:
            expanded = execute(*shlex.split(cached['next'])[2:], '--limit', '100', '--depth', '100')
            assert expanded['requests'] == 1
            assert captured and captured[0][0] <= captured[0][1]
            from reddit_skill._thread import ThreadStateStore
            from reddit_skill._target import parse_target
            store = ThreadStateStore()
            state = store.load(store.key(parse_target(target), 'best'))
            assert all(n['parent'] in state['nodes'] or n['parent'] == state['post']['fullname'] for n in state['nodes'].values())
        comment = next(r for r in opened['results'] if r['kind'] == 'comment')
        branch = execute('comments', comment['url'], '--context', '2', '--depth', '0')
        assert any(r.get('anchor') and r['fullname'] == comment['fullname'] for r in branch['results'])
    finally:
        _transport.run_snippet = original


def test_search_about_and_file_window(tmp_path):
    from datetime import datetime, timedelta, timezone
    result = execute('search', 'type hints', '--in', 'r/python', '--limit', '3')
    assert all(r['kind'] == 'post' for r in result['results'])
    subs = execute('search', 'seoul', '--type', 'subs', '--limit', '3')
    assert all(r['kind'] == 'subreddit' for r in subs['results'])
    if subs['results']:
        sub = execute('sub', 'r/' + subs['results'][0]['name'], '--limit', '1')
        assert sub.get('code', 0) == 0
    about = execute('about', 'r/python')
    assert isinstance(about['results'][0]['rules'], list)
    user = execute('about', 'u/spez')
    assert user['results'][0]['kind'] == 'user'
    since = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    output = tmp_path / 'window.ndjson'
    first = execute('sub', 'r/python', '--sort', 'new', '--since', since, '--out', str(output))
    assert first['stop_reason'] in ('window_reached', 'exhausted')
    second = execute('sub', 'r/python', '--sort', 'new', '--since', since, '--out', str(output))
    assert second['already_complete'] and second['requests'] == 0


def test_morechildren_top_sort_keeps_the_flat_envelope():
    import json
    from reddit_skill._budget import Budget
    from reddit_skill._transport import Transport, build_request
    from reddit_skill._target import parse_target
    for path in (Budget().home / 'threads').glob('*.json'):
        state = json.loads(path.read_text())
        descriptor = next((pointer for pointer in state['pending_more'].values() if pointer['ids']), None)
        if descriptor:
            body = Transport().get(**build_request('morechildren', parse_target(state['post']['url']), sort='top', children=descriptor['ids'][:100]))
            assert isinstance(body['json']['data']['things'], list)
            assert all(item['kind'] in ('t1', 'more') and isinstance(item['data'].get('parent_id'), str) for item in body['json']['data']['things'])
            return
    pytest.skip('No cached pointer sample for the additional sort probe.')
