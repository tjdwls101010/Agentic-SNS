"""Date windows: newest-first reads close at --since, ranked reads are samples, profile windows are Facebook's own.
Sponsored feed posts are skipped and counted unless asked for."""
import json
from datetime import datetime

import pytest

from tests.facebook.helpers import (Account, envelope, feed_stories, group_page, login, more_args, story,
                                    timeline_page)

SINCE, UNTIL = '2026-09-10', '2026-09-20'
FAILURE = envelope('{"errors":[{"message":"Synthetic failure"}]}')


def dated(ident, day, **fields):
    return story(ident, ident, creation_time=int(datetime.fromisoformat(day + 'T12:00:00').timestamp()), **fields)


def ad(ident, day=None):
    fields = {'is_sponsored': True}
    return dated(ident, day, **fields) if day else story(ident, ident, **fields)


def recent_feed(account, *pages, args=(), json_output=True):
    return account.run('feed', '--sort', 'recent', '--since', SINCE, '--until', UNTIL, *args,
                       *(['--json'] if json_output else []), responses=[login(), *pages])


# --- the newest-first boundary -------------------------------------------------------------------------------------

def test_an_older_ordinary_post_closes_the_window_without_another_request(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([dated('in1', '2026-09-15'), dated('in2', '2026-09-12'),
                                                          dated('old', '2026-09-01')], 'next'),
                         feed_stories([dated('never', '2026-08-01')]))
    assert result.code == 0 and result.ids == ['in1', 'in2']
    assert result.data['stop_reason'] == 'window_reached' and 'next' not in result.data
    assert result.data['window'] == {'since': SINCE, 'until': UNTIL, 'coverage': 'closed (as served)'}
    assert result.left == 1


def test_an_old_pinned_post_does_not_close_the_window(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([dated('pin', '2020-01-01', is_pinned_story=True),
                                                          dated('in1', '2026-09-15')], 'next'),
                         feed_stories([dated('in2', '2026-09-11'), dated('old', '2026-09-02')]))
    assert result.ids == ['pin', 'in1', 'in2'] and result.data['stop_reason'] == 'window_reached'
    assert result.left == 0


def test_undated_posts_pass_through_and_never_close_the_window(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([story('undated'), dated('in1', '2026-09-15')], 'next'),
                         feed_stories([dated('old', '2026-09-01')]))
    assert result.ids == ['undated', 'in1'] and result.data['stop_reason'] == 'window_reached'
    assert result.data['results'][0]['undated'] is True


def test_an_old_sponsored_post_does_not_close_the_window(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([ad('ad1', '2020-01-01'), dated('in1', '2026-09-15')], 'next'),
                         feed_stories([dated('in2', '2026-09-12'), dated('old', '2026-09-01')]))
    assert result.ids == ['in1', 'in2'] and result.data['stop_reason'] == 'window_reached'


def test_posts_newer_than_until_are_skipped_and_reading_continues(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([dated('new1', '2026-09-25'), dated('new2', '2026-09-24')], 'n'),
                         feed_stories([dated('in1', '2026-09-15'), dated('old', '2026-09-01')]))
    assert result.ids == ['in1'] and result.data['stop_reason'] == 'window_reached'


def test_group_recent_closes_at_the_boundary_too(tmp_path):
    result = Account(tmp_path).run('group', '123', '--sort', 'recent', '--since', SINCE, '--json', responses=[
        login(), group_page([dated('in1', '2026-09-15'), dated('old', '2026-09-01')], 'next')])
    assert result.ids == ['in1'] and result.data['stop_reason'] == 'window_reached'
    assert result.data['window']['coverage'] == 'closed (as served)'


def test_boundary_with_a_limit_keeps_the_rest_of_the_window_pending(tmp_path):
    account = Account(tmp_path)
    first = recent_feed(account, feed_stories([dated('in1', '2026-09-15'), dated('in2', '2026-09-12'),
                                               dated('in3', '2026-09-11'), dated('old', '2026-09-01')], 'next'),
                        args=('--limit', '1'))
    assert first.ids == ['in1'] and first.data['stop_reason'] == 'limit_reached'
    assert first.data['window']['coverage'] == 'open — more: continues'
    second = account.run(*more_args(first.data['next']), responses=[login()])
    assert second.ids == ['in2'] and second.snippets == ['tokens']
    third = account.run(*more_args(second.data['next'])[:-2], '--limit', '5', '--after',
                        more_args(second.data['next'])[-1], responses=[login()])
    assert third.ids == ['in3'] and third.data['stop_reason'] == 'window_reached' and 'next' not in third.data
    assert third.data['window']['coverage'] == 'closed (as served)'


def test_boundary_page_is_committed_whole_and_the_file_is_complete(tmp_path):
    account = Account(tmp_path)
    path = tmp_path / 'window.ndjson'
    first = recent_feed(account, feed_stories([dated('in1', '2026-09-15'), dated('in2', '2026-09-12'),
                                               dated('old', '2026-09-01')], 'next'), args=('--limit', '1', '--out', str(path)))
    assert first.code == 0 and first.data['count'] == 2 and first.data['stop_reason'] == 'window_reached'
    again = recent_feed(account, args=('--limit', '1', '--out', str(path)))
    assert again.data['already_complete'] is True and again.snippets == ['tokens']


# --- every row of the window truth table ---------------------------------------------------------------------------

def test_newest_first_read_that_reaches_the_end_is_closed(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([dated('in1', '2026-09-15')]))
    assert result.data['stop_reason'] == 'exhausted'
    assert result.data['window']['coverage'] == 'closed (as served)'


def test_newest_first_read_stopped_by_the_budget_is_open(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([dated('in1', '2026-09-15')], 'a'),
                         feed_stories([dated('in2', '2026-09-14')], 'b'), args=('--max-requests', '3'))
    assert result.code == 0 and result.data['stop_reason'] == 'budget'
    assert result.data['window']['coverage'] == 'open — more: continues'


def test_newest_first_read_that_fails_is_open_and_says_why(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([dated('in1', '2026-09-15')], 'a'), FAILURE)
    assert result.code == 8
    assert result.data['window']['coverage'] == 'open — Facebook query failed or its expected structure changed'


def test_ranked_window_is_a_sample_whatever_stopped_it(tmp_path):
    result = Account(tmp_path).run('feed', '--since', SINCE, '--json', responses=[
        login(), feed_stories([dated('in1', '2026-09-15'), dated('old', '2026-09-01')])])
    assert result.data['stop_reason'] == 'exhausted'
    assert result.data['window']['coverage'] == 'sample (ranked order)'


def test_profile_window_is_closed_by_facebook_when_exhausted_and_open_on_budget(tmp_path):
    done = Account(tmp_path).run('profile', '42', '--since', SINCE, '--json', responses=[
        login(), timeline_page([dated('in1', '2026-09-15')])])
    assert done.data['window']['coverage'] == 'closed (server-filtered)'
    spent = Account(tmp_path / 'b').run('profile', '42', '--since', SINCE, '--max-requests', '2', '--json', responses=[
        login(), timeline_page([dated('in1', '2026-09-15')], 'next')])
    assert spent.data['stop_reason'] == 'budget'
    assert spent.data['window']['coverage'] == 'open — more: continues'


def test_window_line_in_text_output(tmp_path):
    result = recent_feed(Account(tmp_path), feed_stories([dated('in1', '2026-09-15'), dated('old', '2026-09-01')]),
                         json_output=False)
    lines = result.stdout.splitlines()
    assert lines[0] == 'feed · sort=recent · 1 shown · sponsored_skipped=0 · stopped=window_reached · requests=2/25'
    assert lines[1] == f'window {SINCE}..{UNTIL} · closed (as served)'


# --- sponsored posts -----------------------------------------------------------------------------------------------

def test_sponsored_posts_are_skipped_counted_once_and_not_counted_against_the_limit(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--limit', '2', '--json', responses=[
        login(), feed_stories([ad('ad1'), story('p1'), ad('ad2')], 'a'), feed_stories([ad('ad1'), story('p2'), story('p3')])])
    assert first.ids == ['p1', 'p2'] and first.data['sponsored_skipped'] == 2
    second = account.run(*more_args(first.data['next']), responses=[login()])
    assert second.ids == ['p3'] and second.data['sponsored_skipped'] == 0


def test_a_page_of_only_sponsored_posts_moves_on_to_the_next_page(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', '--json', responses=[
        login(), feed_stories([ad('ad1'), ad('ad2')], 'a'), feed_stories([story('p1')])])
    assert result.code == 0 and result.ids == ['p1'] and result.data['sponsored_skipped'] == 2


def test_a_budget_spent_on_sponsored_posts_is_still_resumable(tmp_path):
    result = Account(tmp_path).run('feed', '--max-requests', '2', '--json', responses=[
        login(), feed_stories([ad('ad1')], 'a')])
    assert result.code == 0 and result.ids == [] and result.data['stop_reason'] == 'budget'
    assert result.data['sponsored_skipped'] == 1 and result.data['next']


def test_include_sponsored_keeps_them_and_is_part_of_the_query(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--include-sponsored', '--limit', '1', '--json', responses=[
        login(), feed_stories([ad('ad1'), story('p1')])])
    assert first.ids == ['ad1'] and first.data['results'][0]['sponsored'] is True
    assert 'sponsored_skipped' not in first.data
    assert '--include-sponsored' in more_args(first.data['next'])
    handle = more_args(first.data['next'])[-1]
    mismatch = account.run('feed', '--limit', '1', '--after', handle, responses=[login()])
    assert mismatch.code == 2 and mismatch.data['message'] == 'Continuation context does not match this query.'


def test_a_sponsored_post_opened_by_url_is_shown(tmp_path):
    result = Account(tmp_path).run('post', 'https://www.facebook.com/zuck/posts/123', '--json', responses=[
        login(), envelope('"storyID":"s"'), envelope({'data': {'node': ad('ad-post')}}),
        envelope({'data': {'node': {'comments': {'edges': [], 'page_info': {'has_next_page': False}}}}})])
    assert result.code == 0 and result.ids == ['ad-post'] and result.data['results'][0]['sponsored'] is True


@pytest.mark.parametrize('command,page', [('group', group_page), ('search', None)])
def test_sponsored_posts_outside_the_feed_are_not_filtered(tmp_path, command, page):
    if command == 'group':
        result = Account(tmp_path).run('group', '123', '--json', responses=[login(), group_page([ad('ad1')])])
    else:
        body = envelope(json.dumps({'data': {'serpResponse': {'results': {'edges': [{'node': ad('ad1')}],
                                                                          'page_info': {'has_next_page': False}}}}}))
        result = Account(tmp_path).run('search', 'x', '--type', 'posts', '--json', responses=[login(), body])
    assert result.ids == ['ad1'] and 'sponsored_skipped' not in result.data
