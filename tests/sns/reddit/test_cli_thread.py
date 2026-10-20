"""post and comments through the real cli: the post in full and its first batch, batches from the snapshot with no
listing request, expansions when none is left, a linked comment always shown, read generations kept apart, share
links, and a continuation that is offered only while it can still show or fetch something at the same --depth."""
import json

import pytest

from tests.sns.reddit.scene import VIEWER, fixture
from tests.sns.reddit.shapes import PERMALINK, more, pair, t1, things
from tests.sns.support.cli import command_of, more_line


def more_words(out):
    line = more_line(out)
    return command_of(line) if line else None


TREE = [t1('c1', 't3_aaa1', [t1('c2', 't1_c1', [t1('c3', 't1_c2', [t1('c4', 't1_c3')])])]), t1('c5', 't3_aaa1'),
        more('t3_aaa1', ['c6', 'c7'])]


def test_post_shows_the_post_in_full_and_the_first_batch(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE), query={'limit': 500, 'depth': 10, 'sort': 'confidence'})
    code, out, _ = reddit.run('reddit', 'post', PERMALINK, '--limit', '3')
    assert code == 0
    lines = out.splitlines()
    # the post record and the three comments are what the first line counts as shown
    assert lines[0].startswith('reddit post · sort=best · 4 shown · stopped=limit_reached · requests=2')
    assert lines[1].startswith('thread: 9 comments reported (deleted and removed included) · 5 received · 3 shown now')
    assert '2 not yet expanded (at least 1 requests)' in lines[1]
    assert f'text[{len("The whole body. " * 30) - 1} of' in out, 'the post body is shown in full'
    assert '[c1] u/user_c1' in out and '  [c2] u/user_c2' in out and '[c3]' not in out.split('[c2]')[0]
    assert more_words(out)[:3] == ['reddit', 'comments', 'https://www.reddit.com/comments/aaa1/']


def test_comments_continue_from_the_snapshot_then_expand(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    code, out, _ = reddit.run('reddit', 'post', PERMALINK, '--limit', '2')
    reddit.me()
    code, out, _ = reddit.run(*more_words(out), '--depth', '5', '--limit', '10')
    assert code == 0 and 'requests=1 ' in out.splitlines()[0], 'only the account check: the batch is in the snapshot'
    assert all(f'comment {c}' in out for c in ('c3', 'c4', 'c5')), 'received comments first, deeper ones included'
    assert reddit.paths() == ['/api/me.json', '/comments/aaa1.json', '/api/me.json']
    reddit.me().json('/api/morechildren.json', things(t1('c6', 't3_aaa1'), t1('c7', 't3_aaa1')),
                     query={'children': 'c6,c7', 'link_id': 't3_aaa1', 'sort': 'confidence'})
    code, out, _ = reddit.run(*more_words(out))
    assert code == 0 and 'comment c6' in out and 'comment c7' in out and 'stopped=exhausted' in out
    assert more_words(out) is None
    assert reddit.paths()[-2:] == ['/api/me.json', '/api/morechildren.json']


def test_a_linked_comment_is_shown_from_the_snapshot_with_its_context(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    reddit.run('reddit', 'post', PERMALINK, '--depth', '5')
    reddit.me()
    code, out, _ = reddit.run('reddit', 'comments', PERMALINK + 'c3/', '--chars', '0')
    assert code == 0 and 'requests=1 ' in out.splitlines()[0]
    assert '[c1] u/user_c1' in out and 'context' in out.split('[c3]')[0] and '· linked' in out
    assert reddit.paths() == ['/api/me.json', '/comments/aaa1.json', '/api/me.json']


def test_a_linked_comment_shows_what_hangs_under_it_even_after_the_post_showed_it(reddit):
    # measured 2026-10-20: after a whole thread was collected, a comment link showed the comment alone
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    reddit.run('reddit', 'post', PERMALINK, '--depth', '5')
    reddit.me()
    code, out, _ = reddit.run('reddit', 'comments', PERMALINK + 'c2/', '--limit', '1')
    assert code == 0 and '· linked' in out
    reddit.me()
    code, out, _ = reddit.run(*more_words(out), '--limit', '10')
    assert code == 0 and 'comment c3' in out and 'comment c4' in out and 'stopped=exhausted' in out
    assert 'comment c5' not in out, 'the link reads its own subtree, not the rest of the thread'
    assert reddit.paths().count('/comments/aaa1.json') == 1, 'no listing request, no gap outside the subtree'
    reddit.me()
    code, out, _ = reddit.run('reddit', 'comments', PERMALINK)
    assert 'comment c3' not in out, "the post's own reading is left as it was"


def test_a_linked_comment_with_ancestors_ends_when_its_subtree_is_read(reddit):
    # Codex P7: the ancestors sent as context stayed unshown, so more: never ended
    reddit.me().json('/comments/aaa1/_/c2.json', pair([t1('c1', 't3_aaa1', [t1('c2', 't1_c1', [t1('c3', 't1_c2')])])]),
                     query={'context': 1})
    code, out, _ = reddit.run('reddit', 'post', PERMALINK + 'c2/', '--context', '1')
    assert code == 0 and 'comment c3' in out and 'stopped=exhausted' in out and more_words(out) is None


def test_a_linked_comment_is_shown_in_full(reddit):
    # Codex P7: the help promises the comment in full; it was cut at the default 180 characters
    long = 'word ' * 80
    reddit.me().json('/comments/aaa1/_/c9.json', pair([t1('c9', 't1_c8', [t1('c10', 't1_c9', body=long)], body=long)]))
    code, out, _ = reddit.run('reddit', 'comments', PERMALINK + 'c9/')
    assert code == 0 and f'text[{len(long.strip())} of {len(long.strip())} chars shown]' in out.split('[c2]')[0]
    assert 'text[180 of' in out.split('[c2]')[1], 'the replies keep the default'


def test_a_linked_comment_not_yet_read_opens_its_subtree(reddit):
    reddit.me().json('/comments/aaa1/_/c9.json', pair([t1('c9', 't1_c8', [t1('c10', 't1_c9')])]), query={'context': 0})
    code, out, _ = reddit.run('reddit', 'comments', PERMALINK + 'c9/')
    assert code == 0 and '[c1] u/user_c9' in out and 'linked' in out and 'comment c10' in out


def test_a_linked_comment_reddit_does_not_return_is_unavailable(reddit):
    reddit.me().json('/comments/aaa1/_/zz9.json', pair([t1('c1', 't3_aaa1')]))
    code, out, _ = reddit.run('reddit', 'post', PERMALINK + 'zz9/')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_a_new_read_does_not_change_what_an_older_handle_continues(reddit):
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    code, first, _ = reddit.run('reddit', 'post', PERMALINK, '--limit', '1')
    reddit.me().json('/comments/aaa1.json', pair([t1('n1', 't3_aaa1'), t1('n2', 't3_aaa1')]))
    reddit.run('reddit', 'post', PERMALINK, '--limit', '1')
    reddit.me()
    code, out, _ = reddit.run(*more_words(first), '--depth', '5')
    assert code == 0 and 'comment c2' in out and 'comment n2' not in out


def test_a_share_link_resolves_hop_by_hop(reddit):
    share = 'https://www.reddit.com/r/example/s/AbC123'
    reddit.me().respond({'status': 301, 'location': PERMALINK + '?share_id=x&utm_source=share'}, url=share)
    reddit.json('/comments/aaa1.json', pair(TREE))
    code, out, _ = reddit.run('reddit', 'post', share)
    first = out.splitlines()[0]
    assert code == 0 and reddit.paths() == ['/api/me.json', share, '/comments/aaa1.json']
    assert 'requests=3 ' in first and 'share' not in first.split('requests=')[1], 'a share link is never measured'


def test_quotes_are_kept_apart_from_the_reply(reddit):
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1', body='> Cars are cheap to run.\n\nNot here.')]))
    code, out, _ = reddit.run('reddit', 'post', PERMALINK)
    assert '"❝Cars are cheap to run.❞ ⏎ Not here."' in out


def test_markers_of_who_wrote_it(reddit):
    reddit.me().json('/comments/aaa1.json', pair([
        t1('c1', 't3_aaa1', is_submitter=True, author_flair_text='Electrician'),
        t1('c2', 't3_aaa1', distinguished='moderator', stickied=True, author='AutoModerator'),
        t1('c3', 't3_aaa1', body='[removed]', author='[deleted]')], contest_mode=True))
    code, out, _ = reddit.run('reddit', 'post', PERMALINK)
    assert 'OP' in out and 'flair="Electrician"' in out and 'u/AutoModerator' in out and '· mod · pinned' in out
    assert '[deleted]' in out and 'removed' in out and 'contest mode' in out


# --- the continuation that repeated itself (plan, appendix C) -------------------------------------------------------

DEEP = [t1('c1', 't3_aaa1', [t1('c2', 't1_c1')]), t1('c5', 't3_aaa1')]


def test_comments_with_only_deeper_ones_left_end_instead_of_repeating_more(reddit):
    reddit.me().json('/comments/aaa1.json', pair(DEEP))
    code, out, _ = reddit.run('reddit', 'post', PERMALINK, '--depth', '0', '--limit', '1')
    assert code == 0 and 'stopped=limit_reached' in out.splitlines()[0] and more_words(out) is not None
    reddit.me()
    code, out, _ = reddit.run(*more_words(out), '--depth', '0', '--limit', '5')
    assert code == 0 and 'comment c5' in out and 'comment c2' not in out
    assert 'stopped=exhausted' in out.splitlines()[0], 'what is left is deeper than --depth: nothing a more: could show'
    assert more_words(out) is None and 'deeper than --depth 0; a larger --depth shows them' in out


def test_a_continuation_that_can_expand_gaps_is_still_offered(reddit):
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1', [t1('c2', 't1_c1')]),
                                                  more('t3_aaa1', ['c6'])]))
    code, out, _ = reddit.run('reddit', 'post', PERMALINK, '--depth', '0')
    assert code == 0 and 'stopped=limit_reached' in out.splitlines()[0] and more_words(out) is not None


def test_a_larger_depth_shows_what_the_first_reading_left_deeper(reddit):
    reddit.me().json('/comments/aaa1.json', pair(DEEP))
    code, out, _ = reddit.run('reddit', 'post', PERMALINK, '--depth', '0')
    assert more_words(out) is None and 'comment c2' not in out
    reddit.me()
    code, out, _ = reddit.run('reddit', 'comments', PERMALINK, '--depth', '1')
    assert code == 0 and 'comment c2' in out


def compact(comments):
    """tree.json's compact notation → Reddit's t1 things."""
    return [t1(c['id'], c['parent'], compact(c.get('replies') or [])) for c in comments]


@pytest.mark.parametrize('case', fixture('tree.json')['first_read']['cases'], ids=lambda c: c['name'])
def test_the_first_read_must_answer_with_the_post_asked_for_and_hold_the_linked_comment(reddit, case):
    target = case['target']
    suffix = f'/_/{target["comment_id"]}' if target.get('comment_id') else ''
    link = f'https://www.reddit.com/comments/{target["post_id"]}/{"_/" + target["comment_id"] + "/" if suffix else ""}'
    answer = case['answer_post']
    reddit.me().json(f'/comments/{target["post_id"]}{suffix}.json',
                     pair(compact(case.get('answer_comments', [])), id=answer, name=f't3_{answer}'))
    code, out, _ = reddit.run('reddit', 'post', link)
    assert code == (9 if 'error' in case['expected'] else 0), out


def test_the_comments_help_says_when_more_is_offered():
    from tests.sns.support.cli import run_cli
    done = run_cli('reddit', 'comments', '--help')
    assert done.returncode == 0 and '--depth' in done.stdout and 'more: is offered only while' in done.stdout
    assert VIEWER not in done.stdout
