"""post and comments through the real cli.py: the post in full and its first batch, batches from the snapshot with no
request, expansions when none is left, a linked comment always shown, read generations kept apart, share links."""
import json

from conftest import VIEWER, command_of, run_cli

PERMALINK = 'https://www.reddit.com/r/example/comments/aaa1/a_title/'


def t1(identity, parent, replies=(), body=None, **extra):
    data = {'id': identity, 'name': f't1_{identity}', 'parent_id': parent, 'link_id': 't3_aaa1', 'author': f'user_{identity}',
            'body': body or f'comment {identity}', 'permalink': f'/r/example/comments/aaa1/a_title/{identity}/',
            'created_utc': 1760000100, 'score': 3, 'replies': {'kind': 'Listing', 'data': {'children': list(replies)}}
            if replies else '', **extra}
    return {'kind': 't1', 'data': data}


def more(parent, ids, count=None):
    return {'kind': 'more', 'data': {'parent_id': parent, 'children': list(ids), 'count': count or len(ids),
                                     'id': ids[0] if ids else '_', 'name': f't1_{ids[0]}' if ids else 't1__'}}


def pair(comments, **post):
    head = {'id': 'aaa1', 'name': 't3_aaa1', 'title': 'A title', 'selftext': 'The whole body. ' * 30, 'is_self': True,
            'subreddit': 'example', 'author': 'poster', 'permalink': '/r/example/comments/aaa1/a_title/',
            'num_comments': 9, 'created_utc': 1760000000, **post}
    return [{'kind': 'Listing', 'data': {'children': [{'kind': 't3', 'data': head}]}},
            {'kind': 'Listing', 'data': {'children': list(comments)}}]


def things(*items):
    return {'json': {'errors': [], 'data': {'things': list(items)}}}


def more_line(out):
    found = [line for line in out.splitlines() if line.startswith('more: ')]
    return command_of(found[0]) if found else None


TREE = [t1('c1', 't3_aaa1', [t1('c2', 't1_c1', [t1('c3', 't1_c2', [t1('c4', 't1_c3')])])]), t1('c5', 't3_aaa1'),
        more('t3_aaa1', ['c6', 'c7'])]


def test_post_shows_the_post_in_full_and_the_first_batch(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE), query={'limit': '500', 'depth': '10', 'sort': 'confidence'})
    code, out, _ = run_cli(reddit, 'post', PERMALINK, '--limit', '3')
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith('post · sort=best · 3 shown · stopped=limit_reached · requests=2/25')
    assert lines[1].startswith('thread: 9 comments reported (deleted and removed included) · 5 received · 3 shown now')
    assert '2 not yet expanded (at least 1 requests)' in lines[1]
    assert f'text[{len("The whole body. " * 30) - 1} of' in out, 'the post body is shown in full'
    assert '[c1] u/user_c1' in out and '  [c2] u/user_c2' in out and '[c3]' not in out.split('[c2]')[0]
    assert more_line(out)[:2] == ['comments', 'https://www.reddit.com/comments/aaa1/']


def test_comments_continue_from_the_snapshot_then_expand(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    code, out, _ = run_cli(reddit, 'post', PERMALINK, '--limit', '2')
    code, out, _ = run_cli(reddit, *more_line(out), '--depth', '5', '--limit', '10')
    assert code == 0 and 'requests=0/25' in out.splitlines()[0]
    assert all(f'comment {c}' in out for c in ('c3', 'c4', 'c5')), 'received comments first, deeper ones included'
    assert reddit.paths() == ['/api/me.json', '/comments/aaa1.json']
    reddit.me().json('/api/morechildren.json', things(t1('c6', 't3_aaa1'), t1('c7', 't3_aaa1')),
                     query={'children': 'c6,c7', 'link_id': 't3_aaa1', 'sort': 'confidence'})
    code, out, _ = run_cli(reddit, *more_line(out))
    assert code == 0 and 'comment c6' in out and 'comment c7' in out and 'stopped=exhausted' in out
    assert more_line(out) is None
    assert reddit.paths()[-2:] == ['/api/me.json', '/api/morechildren.json']


def test_a_linked_comment_is_shown_from_the_snapshot_with_its_context(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    run_cli(reddit, 'post', PERMALINK, '--depth', '5')
    code, out, _ = run_cli(reddit, 'comments', PERMALINK + 'c3/', '--chars', '0')
    assert code == 0 and 'requests=0/25' in out.splitlines()[0]
    assert '[c1] u/user_c1' in out and 'context' in out.split('[c3]')[0] and '· linked' in out
    assert reddit.paths() == ['/api/me.json', '/comments/aaa1.json']


def test_a_linked_comment_not_yet_read_opens_its_subtree(reddit):
    reddit.me().json('/comments/aaa1/_/c9.json', pair([t1('c9', 't1_c8', [t1('c10', 't1_c9')])]),
                     query={'context': '0'})
    code, out, _ = run_cli(reddit, 'comments', PERMALINK + 'c9/')
    assert code == 0 and '[c1] u/user_c9' in out and 'linked' in out and 'comment c10' in out


def test_a_linked_comment_reddit_does_not_return_is_unavailable(reddit):
    reddit.me().json('/comments/aaa1/_/zz9.json', pair([t1('c1', 't3_aaa1')]))
    code, out, _ = run_cli(reddit, 'post', PERMALINK + 'zz9/')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_a_new_read_does_not_change_what_an_older_handle_continues(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    code, first, _ = run_cli(reddit, 'post', PERMALINK, '--limit', '1')
    reddit.me().json('/comments/aaa1.json', pair([t1('n1', 't3_aaa1'), t1('n2', 't3_aaa1')]))
    run_cli(reddit, 'post', PERMALINK, '--limit', '1')
    code, out, _ = run_cli(reddit, *more_line(first), '--depth', '5')
    assert code == 0 and 'comment c2' in out and 'comment n2' not in out


def test_a_share_link_resolves_hop_by_hop(reddit):
    share = 'https://www.reddit.com/r/example/s/AbC123'
    reddit.me().respond({'status': 301, 'location': PERMALINK + '?share_id=x&utm_source=share', 'ratelimit': {
        'used': None, 'remaining': None, 'reset': None}}, url=share)
    reddit.json('/comments/aaa1.json', pair(TREE))
    code, out, _ = run_cli(reddit, 'post', share)
    assert code == 0 and reddit.paths() == ['/api/me.json', share, '/comments/aaa1.json']
    assert 'requests=3/25' in out.splitlines()[0]


def test_quotes_are_kept_apart_from_the_reply(reddit):
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1', body='> Cars are cheap to run.\n\nNot here.')]))
    code, out, _ = run_cli(reddit, 'post', PERMALINK)
    assert '"❝Cars are cheap to run.❞ ⏎ Not here."' in out


def test_markers_of_who_wrote_it(reddit):
    reddit.me().json('/comments/aaa1.json', pair([
        t1('c1', 't3_aaa1', is_submitter=True, author_flair_text='Electrician'),
        t1('c2', 't3_aaa1', distinguished='moderator', stickied=True, author='AutoModerator'),
        t1('c3', 't3_aaa1', body='[removed]', author='[deleted]')], contest_mode=True))
    code, out, _ = run_cli(reddit, 'post', PERMALINK)
    assert 'OP' in out and 'flair="Electrician"' in out and 'u/AutoModerator' in out and '· mod · pinned' in out
    assert '[deleted]' in out and 'removed' in out and 'contest mode' in out


def test_thread_help_says_what_reading_costs(reddit):
    for command in ('post', 'comments'):
        code, out, _ = run_cli(reddit, command, '--help')
        assert code == 0 and 'requests:' in out and 'exit codes' in out and '--depth' in out
