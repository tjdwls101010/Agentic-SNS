"""fixtures/stores.json joined to the tests that run it. The file states 62 scenarios of the local state a Threads
command rests on: the --out file, handles, account protection, the dedicated tab's protection, the session. The first
three are the core's stores, run by tests/sns/core (any platform), so most scenarios name the test that holds them; the
ones that are Threads' own (the page's signals, the tab's life, the formats of the previous skill) or have no core test of
that shape are run here. A scenario with no test is a failure, so the file cannot go unread again (appendix C)."""
import ast
import json
import time
from pathlib import Path

import pytest

from sns.paths import scope
from tests.sns.threads.data import fixture
from tests.sns.threads.scenes import ASIDE, feed_body, known_tab, post, query_result, run

STORES = fixture('stores.json')
HERE = Path(__file__).parent
CORE = HERE.parent / 'core'
DROPPED = {'per-command-cap': 'there is no request budget (S2)', 'cap-ceiling': 'there is no request budget (S2)'}

OUTFILE, HANDLES, PROTECTION = 'core/test_outfile.py::', 'core/test_handles.py::', 'core/test_protection.py::'
COVERED = {
    # collection (--out)
    'new-file-gets-header': OUTFILE + 'test_pages_are_committed_with_a_marker_and_resume_drops_an_unfinished_tail',
    'page-commit': OUTFILE + 'test_pages_are_committed_with_a_marker_and_resume_drops_an_unfinished_tail',
    'interrupted-tail-replayed': OUTFILE + 'test_pages_are_committed_with_a_marker_and_resume_drops_an_unfinished_tail',
    'partial-line-replayed': OUTFILE + 'test_pages_are_committed_with_a_marker_and_resume_drops_an_unfinished_tail',
    'other-query-refused-byte-identical': 'test_cli_out.py::test_a_file_of_another_query_is_refused_unchanged',
    'older-format-refused-byte-identical': OUTFILE + 'test_a_file_of_another_query_or_version_is_refused_before_any_byte_changes',
    'previous-skill-file-refused': 'test_cli_out.py::test_a_file_from_the_previous_threads_skill_is_refused_unchanged',
    'integrity-failure': OUTFILE + 'test_a_damaged_committed_page_fails_the_integrity_check',
    'complete-file': 'test_cli_out.py::test_collect_resume_and_complete',
    'window-complete-file': OUTFILE + 'test_a_final_marker_is_repeated_by_peek_and_an_interrupted_one_resumes',
    'dedupe-across-pages': 'test_cli_out.py::test_collect_resume_and_complete',
    'concurrent-writer-refused': OUTFILE + 'test_links_are_refused_and_the_file_is_private_and_locked',
    'symlink-refused': OUTFILE + 'test_links_are_refused_and_the_file_is_private_and_locked',
    'out-with-after-refused': 'test_cli_out.py::test_out_and_after_cannot_be_combined',
    # handles
    'monotonic': HANDLES + 'test_the_first_handle_is_1000_and_numbers_only_grow',
    'counter-survives-cleanup': HANDLES + 'test_saving_prunes_handles_past_their_ttl_but_keeps_the_counter',
    'seeded-counter': HANDLES + 'test_the_first_handle_is_1000_and_numbers_only_grow',
    'context-mismatch': HANDLES + 'test_a_handle_of_another_platform_or_command_names_where_it_belongs',
    'account-mismatch': 'test_session.py::test_a_continuation_read_as_another_account_is_a_changed_login',
    'expired': HANDLES + 'test_an_expired_missing_or_older_handle_is_an_argument_error',
    'expired-files-cleaned': HANDLES + 'test_saving_prunes_handles_past_their_ttl_but_keeps_the_counter',
    'older-format': HANDLES + 'test_an_expired_missing_or_older_handle_is_an_argument_error',
    'previous-skill-handle': 'test_stores.py::test_a_handle_file_the_previous_skill_wrote_is_an_earlier_version',
    'missing': 'test_cli_thread.py::test_a_bad_or_foreign_handle_is_an_argument_error',
    'not-a-number': 'test_cli_thread.py::test_a_bad_or_foreign_handle_is_an_argument_error',
    'permissions': HANDLES + 'test_handle_files_are_private',
    # protection
    'no-state-is-open': PROTECTION + 'test_a_request_is_paced_counted_and_logged_before_it_is_sent',
    'checkpoint-blocks-indefinitely': PROTECTION + 'test_a_person_block_stops_every_later_invocation',
    'rate-limit-expires': PROTECTION + 'test_an_account_hold_passes_by_itself_at_its_time',
    'rate-limit-active': 'test_cli_doctor.py::test_a_hold_stops_the_next_command_before_the_browser_and_passes_by_itself',
    'rate-limit-never-downgrades-checkpoint': PROTECTION + 'test_person_and_hold_never_overwrite_each_other_and_times_never_shorten',
    'unreadable-block-fails-closed': 'test_stores.py::test_a_block_file_that_cannot_be_trusted_fails_closed',
    'unknown-reason-fails-closed': 'test_stores.py::test_a_block_file_that_cannot_be_trusted_fails_closed',
    'checkpoint-with-expiry-fails-closed': 'test_stores.py::test_a_block_file_that_cannot_be_trusted_fails_closed',
    'pace-waits': PROTECTION + 'test_the_next_request_waits_out_the_pacing_gap',
    'pace-recorded-before-request': PROTECTION + 'test_a_request_is_paced_counted_and_logged_before_it_is_sent',
    'block-recorded-inside-lock': PROTECTION + 'test_a_person_block_stops_every_later_invocation',
    'rate-limit-sets-30-minutes': 'test_cli_doctor.py::test_a_429_while_the_new_tab_loaded_is_an_account_hold_and_the_tab_is_emptied',
    'no-shared-window': 'test_stores.py::test_many_recent_requests_do_not_stop_a_read_and_the_log_gains_a_line',
    'observation-log-rolls': 'test_stores.py::test_log_lines_older_than_a_day_are_gone_after_the_next_request',
    'unblock-after-verification-only': 'test_cli_doctor.py::test_unblock_lifts_the_block_only_after_a_clean_check',
    'unblock-check-fails': 'test_cli_doctor.py::test_unblock_keeps_the_block_when_the_check_sees_a_checkpoint',
    'unblock-killed': PROTECTION + 'test_one_check_per_invocation_and_a_failed_check_keeps_the_block',
    'unblock-allows-one-request': 'test_cli_doctor.py::test_unblock_makes_one_request_even_when_threads_redirects_the_check',
    # the dedicated tab's protection
    'background-checkpoint-then-reload': 'test_tab_protection.py::test_a_checkpoint_the_app_met_between_commands_blocks_a_read_before_its_first_query',
    'background-rate-limit-body': 'test_tab_protection.py::test_a_rate_limit_body_the_app_met_between_commands_is_an_account_hold_before_any_query',
    'ledger-429': 'test_tab_protection.py::test_a_429_in_the_tabs_ledger_is_an_account_hold_before_any_query',
    'tab-moved-to-checkpoint': 'test_tab_protection.py::test_a_tab_moved_to_the_checkpoint_page_stops_a_read_before_any_query',
    'record-cleared-only-after-transfer': 'test_tab_protection.py::test_the_record_is_not_acknowledged_when_protection_could_not_hold_the_block',
    'lost-tab-new-tab-checked-first': 'test_tab_protection.py::test_a_lost_tab_gets_a_new_one_whose_checkpoint_is_found_before_any_query',
    'lost-tab-login': 'test_tab_protection.py::test_a_lost_tab_whose_replacement_lands_on_the_login_page_is_exit_4_before_any_query',
    'lost-tab-residual-risk': 'test_tab_protection.py::test_a_rate_limit_only_the_lost_tab_knew_is_recorded_when_the_one_query_meets_it_again',
    'block-blanks-tab': 'test_cli_doctor.py::test_a_checkpoint_body_the_tab_kept_blocks_and_empties_the_tab',
    'unwatched-background-counted': 'test_cli_doctor.py::test_reuses_the_known_tab_and_reports_what_it_did_between_commands',
    # the session
    'concurrent-start-one-tab': 'test_cli_doctor.py::test_two_commands_starting_together_open_one_tab',
    'recorded-tab-reused': 'test_cli_doctor.py::test_reuses_the_known_tab_and_reports_what_it_did_between_commands',
    'lost-tab-reopened': 'test_tab_protection.py::test_a_lost_recorded_tab_is_replaced_and_the_first_line_reports_the_opening',
    'user-tab-not-adopted': 'test_tab_protection.py::test_a_threads_tab_the_user_has_open_is_never_adopted_or_touched',
    'corrupt-session': 'test_cli_doctor.py::test_an_unreadable_session_opens_one_tab_and_says_so',
    'per-account': 'test_tab_protection.py::test_each_aside_account_has_its_own_session_and_tab',
}


def scenario_names():
    return [s['name'] for section in ('collection', 'handles', 'protection', 'tab_protection', 'session')
            for s in STORES[section]['scenarios']]


def test_every_scenario_of_the_file_is_run_by_a_named_test_or_dropped_for_a_reason():
    names = scenario_names()
    assert len(names) == 62 and len(set(names)) == 62
    assert set(names) == set(COVERED) | set(DROPPED)
    assert not set(COVERED) & set(DROPPED)


def test_each_named_test_exists():
    def defined(path):
        tree = ast.parse((HERE.parent / path if path.startswith('core/') else HERE / path).read_text())
        return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    missing = []
    for scenario, where in COVERED.items():
        path, name = where.split('::')
        if name not in defined(path):
            missing.append((scenario, where))
    assert not missing, missing


# --- the scenarios nobody else holds ---------------------------------------------------------------------------------

def blocks_path():
    return scope('threads', ASIDE, 'protection') / 'blocks.json'


def test_there_is_no_request_budget_option(browser):
    """per-command-cap and cap-ceiling are gone with the budget (S2): the option does not exist."""
    known_tab(browser)
    code, out, _ = run(browser, 'feed', '--max-requests', '5')
    assert code == 2 and 'unrecognized' in json.loads(out)['message']
    assert browser.calls() == []


@pytest.mark.parametrize('content', ['not json', json.dumps({'person': {'reason': 'other', 'at': 1, 'viewer': None},
                                                           'hold': None}),
                                     json.dumps({'person': {'reason': 'checkpoint', 'at': time.time(), 'viewer': None,
                                                            'expires_at': time.time() + 10}, 'hold': None})],
                         ids=['not-json', 'unknown-reason', 'checkpoint-with-expiry'])
def test_a_block_file_that_cannot_be_trusted_fails_closed(browser, content):
    path = blocks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    known_tab(browser)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and json.loads(out)['error'] == 'blocked'
    assert set(browser.ops()) <= {'account_status'}  # nothing was sent, the browser untouched


def test_many_recent_requests_do_not_stop_a_read_and_the_log_gains_a_line(browser):
    log = scope('threads', ASIDE, 'protection') / 'requests.jsonl'
    log.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    log.write_text(''.join(json.dumps({'at': now - 600 + i, 'id': f'r{i}', 'kind': 'query', 'n': 1, 'outcome': 'sent'}) + '\n'
                           for i in range(500)))
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')]], False, None)))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out  # the log is an observation, never a window that stops a command
    assert len(log.read_text().splitlines()) > 500


def test_log_lines_older_than_a_day_are_gone_after_the_next_request(browser):
    log = scope('threads', ASIDE, 'protection') / 'requests.jsonl'
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({'at': time.time() - 2 * 86400, 'id': 'old', 'kind': 'query', 'n': 1, 'outcome': 'sent'}) + '\n')
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')]], False, None)))
    assert run(browser, 'feed')[0] == 0
    assert 'old' not in log.read_text()


def test_a_handle_file_the_previous_skill_wrote_is_an_earlier_version(browser, data_dir):
    handles = data_dir / 'handles'
    handles.mkdir(parents=True, exist_ok=True)
    (handles / '1500.json').write_text(json.dumps({'context': {'command': 'post', 'target': None}, 'cursor': 'C',
                                                   'pending': [], 'created_at': time.time()}))
    known_tab(browser)
    code, out, _ = run(browser, 'feed', '--after', '1500')
    assert code == 2 and 'earlier version' in json.loads(out)['message']
    assert 'threads.query' not in browser.ops()
