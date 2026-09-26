"""--max-requests: a stop that a later invocation can continue is a success; one that must restart says what it needs."""
import pytest

from tests.facebook.helpers import (Account, about_collection, about_overview, about_section, envelope, feed_page,
                                    login, more_args, timeline_page, story)


def test_budget_stop_with_a_saved_cursor_is_a_success_that_more_continues(tmp_path):
    account = Account(tmp_path)
    pages = [feed_page([f'p{i}', f'q{i}'], f'c{i}') for i in range(30)]
    first = account.run('feed', '--limit', '100', '--json', responses=[login(), *pages])
    assert first.code == 0 and first.data['ok'] is True
    assert first.data['stop_reason'] == 'budget'
    assert len(first.calls) == 25 and first.data['request_count'] == 25 and first.data['max_requests'] == 25
    assert len(first.ids) == 48 and first.data['next']
    assert first.data['fix'].startswith('Run more:')
    second = account.run(*more_args(first.data['next']), '--max-requests', '3', responses=[login(), *pages[24:26]])
    assert second.code == 0 and second.data['max_requests'] == 3
    assert second.ids == ['p24', 'q24', 'p25', 'q25']
    assert not set(first.ids) & set(second.ids)


def test_budget_stop_before_any_record_is_still_resumable_when_a_cursor_was_saved(tmp_path):
    pages = [feed_page([], f'c{i}') for i in range(5)]
    result = Account(tmp_path).run('feed', '--max-requests', '3', '--json', responses=[login(), *pages])
    assert result.code == 0 and result.data['ok'] is True
    assert result.data['stop_reason'] == 'budget' and result.ids == [] and result.data['next']


def test_budget_stop_in_an_output_file_resumes_with_the_same_command(tmp_path):
    path = tmp_path / 'feed.ndjson'
    result = Account(tmp_path).run('feed', '--out', str(path), '--max-requests', '3',
                                   responses=[login(), feed_page(['p1'], 'a'), feed_page(['p2'], 'b')])
    assert result.code == 0
    summary, resume = result.stdout.strip().split(' · resume: ')
    assert summary.endswith(' · stopped=budget · requests=3/3')
    assert more_args(resume) == ['feed', '--sort', 'top', '--max-requests', '3', f'--out={path}']


def test_budget_spent_during_setup_must_restart_and_says_what_setup_needs(tmp_path):
    result = Account(tmp_path).run('profile', 'synthetic.vanity', '--max-requests', '1', responses=[login()])
    assert result.code == 8 and result.data['error'] == 'partial'
    assert result.data['message'] == ('The request budget ran out during setup, before any reading; '
                                      'setup needs 1–2 requests.')
    assert result.data['fix'] == 'Rerun with a larger --max-requests.'
    assert result.snippets == ['tokens']


def test_budget_spent_on_a_retried_home_request_is_a_setup_stop(tmp_path):
    rejected = envelope('{"errors":[{"code":1357054}]}', status=500, url='https://www.facebook.com/')
    result = Account(tmp_path).run('feed', '--max-requests', '1', responses=[rejected, login()])
    assert result.code == 8 and 'setup' in result.data['message']


def test_budget_spent_before_the_first_page_must_restart(tmp_path):
    result = Account(tmp_path).run('profile', '42', '--max-requests', '1', '--json', responses=[login()])
    assert result.code == 8 and result.data['stop_reason'] == 'budget' and result.data['ok'] is False
    assert result.data['fix'] == 'Rerun with a larger --max-requests.'
    assert 'next' not in result.data


def test_budget_spent_between_about_collections_must_restart_and_says_the_total(tmp_path):
    collections = [('a', 'A'), ('b', 'B'), ('c', 'C')]
    result = Account(tmp_path).run('about', '42', '--max-requests', '4', '--json', responses=[
        login(), about_overview([about_section('directory_bio', 'Bio')], collections),
        about_collection(about_section('directory_work', 'Work')),
        about_collection(about_section('directory_college', 'College'))])
    assert result.code == 8 and result.data['stop_reason'] == 'budget'
    assert [r['section'] for r in result.data['results']] == ['directory_bio', 'directory_work', 'directory_college']
    assert result.data['message'] == ('The request budget ran out after 2 of 3 About collections; '
                                      'this profile needs 5 requests.')
    assert result.data['fix'] == 'Rerun with a larger --max-requests.'


@pytest.mark.parametrize('value', ['0', '401', 'many'])
def test_request_budget_is_bounded(tmp_path, value):
    result = Account(tmp_path).run('feed', '--max-requests', value)
    assert result.code == 2 and result.calls == []


def test_a_continuation_may_change_its_budget_but_not_its_query(tmp_path):
    account = Account(tmp_path)
    first = account.run('profile', '42', '--limit', '1', '--json', responses=[
        login(), timeline_page([story('p1'), story('p2')])])
    changed = account.run(*more_args(first.data['next']), '--max-requests', '7', responses=[login()])
    assert changed.code == 0
    assert account.run('profile', '43', '--after', more_args(first.data['next'])[-1], responses=[login()]).code == 2
