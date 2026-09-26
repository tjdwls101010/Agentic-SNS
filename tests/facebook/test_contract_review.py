"""Envelope and continuation contract cases found in review: every failure is finished like a reading, only saved
state makes a stop resumable, and a continuation line always means the same query."""
import json
import subprocess

import pytest

from tests.facebook.helpers import (LIMITED, POST_URL, Account, comment_node, comment_page, envelope, feed_page,
                                    feed_stories, login, more_args, post_response, story, story_id_page)
from tests.facebook.test_window import SINCE, ad, dated

FAILURE = envelope('{"errors":[{"message":"Synthetic failure"}]}')


def test_setup_budget_failure_carries_its_stop_reason_and_cost(tmp_path):
    result = Account(tmp_path).run('profile', 'synthetic.vanity', '--max-requests', '1', '--json', responses=[login()])
    assert result.code == 8
    assert (result.data['stop_reason'], result.data['request_count'], result.data['max_requests']) == ('budget', 1, 1)


def test_saved_block_during_a_collection_is_still_one_summary_line(tmp_path):
    account = Account(tmp_path)
    assert account.run('feed', responses=[login(), LIMITED]).code == 5
    path = tmp_path / 'blocked.ndjson'
    result = account.run('feed', '--out', str(path))
    assert result.code == 5 and len(result.stdout.splitlines()) == 1
    assert ' · stopped=blocked · requests=0/25' in result.stdout and 'error=blocked' in result.stdout


def test_failure_before_the_first_record_names_query_failure(tmp_path):
    result = Account(tmp_path).run('post', POST_URL, '--json', responses=[
        login(), envelope('<html>no id</html>', url=POST_URL)])
    assert result.code == 6 and result.data['stop_reason'] == 'query_failure'
    assert result.data['request_count'] == 2


def test_output_file_without_a_committed_page_must_restart_after_a_budget_stop(tmp_path):
    result = Account(tmp_path).run('feed', '--out', str(tmp_path / 'x.ndjson'), '--max-requests', '1', '--json',
                                   responses=[login()])
    assert result.code == 8 and result.data['stop_reason'] == 'budget'
    assert result.data['fix'] == 'Rerun with a larger --max-requests.'


def test_a_reply_failure_is_not_hidden_by_a_later_budget_stop(tmp_path):
    result = Account(tmp_path).run('comments', POST_URL, '--replies', '--max-requests', '5', '--json', responses=[
        login(), story_id_page(), post_response(), comment_page([comment_node('c1'), comment_node('c2')]), FAILURE])
    assert result.code == 8 and result.data['error'] == 'partial'
    assert result.data['stop_reason'] == 'query_failure' and result.data['next']
    assert result.data['fix'].startswith('Run more:')


def test_a_continuation_that_cannot_be_saved_keeps_the_records_and_says_why(tmp_path):
    account = Account(tmp_path)
    (account.home / 'cursors' / 'counter').mkdir(parents=True)
    result = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['p1', 'p2'])])
    assert result.code == 8 and result.ids == ['p1']
    assert result.data['message'] == 'Cannot save a continuation handle.'
    assert 'max-requests' not in result.data['fix']


def test_reaching_the_end_exactly_at_the_limit_is_exhaustion(tmp_path):
    result = Account(tmp_path).run('feed', '--sort', 'recent', '--since', SINCE, '--limit', '1', '--json',
                                   responses=[login(), feed_stories([dated('in1', '2026-09-15')])])
    assert result.data['stop_reason'] == 'exhausted' and 'next' not in result.data
    assert result.data['window']['coverage'] == 'closed (as served)'


def test_output_file_reruns_keep_the_window_line(tmp_path):
    account = Account(tmp_path)
    path = str(tmp_path / 'w.ndjson')
    args = ('feed', '--sort', 'recent', '--since', SINCE, '--limit', '1', '--out', path, '--json')
    assert account.run(*args, responses=[login(), feed_stories([dated('a', '2026-09-15'), dated('b', '2026-09-14')],
                                                               'next')]).code == 0
    satisfied = account.run(*args, responses=[login()])
    assert satisfied.data['stop_reason'] == 'limit_reached'
    assert satisfied.data['window']['coverage'] == 'open — more: continues'


def test_output_file_resume_does_not_count_a_skipped_ad_again(tmp_path):
    account = Account(tmp_path)
    path = str(tmp_path / 'ads.ndjson')
    first = account.run('feed', '--out', path, '--limit', '1', '--json', responses=[
        login(), feed_stories([ad('adA'), story('p1')], 'next')])
    assert first.data['sponsored_skipped'] == 1
    second = account.run('feed', '--out', path, '--limit', '2', '--json', responses=[
        login(), feed_stories([ad('adA'), story('p2')])])
    assert second.data['sponsored_skipped'] == 0 and second.ids == ['p2']


def test_output_summary_reports_skipped_ads(tmp_path):
    result = Account(tmp_path).run('feed', '--out', str(tmp_path / 's.ndjson'), responses=[
        login(), feed_stories([ad('adA'), story('p1')])])
    assert ' · sponsored_skipped=1 · ' in result.stdout


def test_control_characters_in_arguments_are_rejected_before_any_request(tmp_path):
    for args in (['search', 'one\ntwo'], ['about', '42', '--section', 'a\rb'], ['feed', '--out', 'a\nb']):
        result = Account(tmp_path).run(*args)
        assert result.code == 2 and result.calls == [], args


def test_a_target_that_starts_with_a_dash_continues(tmp_path):
    account = Account(tmp_path)
    page = envelope({'data': {'serpResponse': {'results': {'edges': [
        {'node': {'__typename': 'Page', 'id': i, 'name': 'x', 'url': 'https://www.facebook.com/' + i}} for i in 'ab'],
        'page_info': {'has_next_page': False}}}}})
    first = account.run('search', '--type', 'pages', '--limit', '1', '--json', '--', '-spam', responses=[login(), page])
    assert first.code == 0 and more_args(first.data['next'])[-2:] == ['--', '-spam']
    second = account.run(*more_args(first.data['next']), responses=[login()])
    assert second.code == 0 and second.ids == ['b']


def test_a_pagination_failure_without_a_continuation_says_to_rerun(tmp_path):
    page = envelope({'data': {'viewer': {'news_feed': {'edges': [{'node': story('p1')}]}}}})
    result = Account(tmp_path).run('feed', '--json', responses=[login(), page])
    assert result.code == 8 and 'next' not in result.data
    assert result.data['fix'] == 'Rerun the same command later; refresh does not change pagination.'


def test_more_line_is_printed_exactly_as_it_runs(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', responses=[login(), feed_page(['p1', 'p2'])])
    line = result.stdout.splitlines()[-1].removeprefix('more: ')
    parsed = subprocess.run(['sh', '-c', 'uv() { printf "%s\\n" "$@"; }\n' + line], capture_output=True, text=True)
    assert parsed.stdout.splitlines()[2:] == ['feed', '--sort', 'top', '--limit', '1', '--after', '1']
    assert json.dumps(line)


def test_an_unusable_cursor_directory_keeps_the_records(tmp_path):
    account = Account(tmp_path)
    account.home.mkdir(parents=True)
    (account.home / 'cursors').write_text('not a directory')
    result = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['p1', 'p2'])])
    assert result.code == 8 and result.ids == ['p1']
    assert result.data['message'] == 'Cannot save a continuation handle.'
    assert (result.data['request_count'], result.data['max_requests']) == (2, 25)


def test_a_storage_failure_is_not_reported_as_a_budget_stop(tmp_path):
    account = Account(tmp_path)
    (account.home / 'cursors' / 'counter').mkdir(parents=True)
    result = account.run('feed', '--max-requests', '2', '--json', responses=[login(), feed_page(['p1'], 'next')])
    assert result.code == 8 and result.data['message'] == 'Cannot save a continuation handle.'
    assert 'max-requests' not in result.data['fix']


@pytest.mark.parametrize('last,shown', [(feed_page(['p2'], 'b'), ['p1', 'p2']), (feed_page([]), ['p1'])])
def test_a_failed_page_commit_keeps_what_was_read_and_what_was_saved(tmp_path, last, shown):
    path = tmp_path / 'disk.ndjson'
    # The header and the first page are synced, then the disk is full; the last page may be explicitly empty.
    result = Account(tmp_path).run('feed', '--out', str(path), '--json', env={'FAKE_FAIL_FSYNC': 'disk.ndjson:2'},
                                   responses=[login(), feed_page(['p1'], 'a'), last])
    assert result.code == 8 and result.data['error'] == 'partial'
    assert result.data['count'] == 1 and result.ids == shown
    assert result.data['message'] == 'Output page could not be committed.'


def test_an_output_path_that_starts_with_a_dash_resumes(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--out=-posts.ndjson', '--max-requests', '2', responses=[login(), feed_page(['p1'], 'a')],
                        cwd=tmp_path)
    resume = first.stdout.strip().split(' · resume: ')[1]
    assert '--out=-posts.ndjson' in more_args(resume)
    second = account.run(*more_args(resume), responses=[login(), feed_page(['p2'])], cwd=tmp_path)
    assert second.code == 0 and 'stopped=exhausted' in second.stdout
