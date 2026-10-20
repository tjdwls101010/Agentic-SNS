"""The dedicated tab classifies the app's own responses too (fixtures/stores.json tab_protection and session scenarios): a
hook installed once per page load keeps what it saw, and every command reads that record and the tab's location before it
sends anything — a checkpoint becomes a person block, a 429 or a rate-limit body an account hold — and acknowledges the
record only once protection holds it. The kit's record itself (it survives a reload, not a lost tab) is test_snippets.py;
doctor's view of the same scenes is test_cli_doctor.py."""
import json

import pytest

from sns.session import Session
from tests.sns.threads.scenes import (ASIDE, feed_body, known_tab, opening, post, query_result, queries, run,
                                      state, state_of)

CHECKPOINT = json.dumps({'message': 'checkpoint_required', 'checkpoint_url': 'https://www.threads.com/challenge/x/',
                         'status': 'fail'})
RATE_BODY = json.dumps({'error': {'code': 4, 'message': 'Please wait a few minutes before you try again later.'}})
GRAPHQL = 'https://www.threads.com/graphql/query'


def signal(summary, at=101, status=200):
    return {'url': GRAPHQL, 'status': status, 'summary': summary, 'at': at}


def one_post():
    return query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')]], False, None))


def test_a_checkpoint_the_app_met_between_commands_blocks_a_read_before_its_first_query(browser):
    """background-checkpoint-then-reload: the record held a checkpoint body; the command sends nothing, records the
    block, acknowledges the record after it and empties the tab."""
    known_tab(browser, signals=[signal(CHECKPOINT, at=1792148826874)])
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and 'threads.blank' in browser.ops()
    assert state_of()['person']['reason'] == 'checkpoint' and Session('threads', ASIDE).ack == 1792148826874


def test_a_rate_limit_body_the_app_met_between_commands_is_an_account_hold_before_any_query(browser):
    known_tab(browser, signals=[signal(RATE_BODY)])
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and 'threads.blank' in browser.ops()
    assert state_of()['hold'] is not None and state_of()['person'] is None


def test_a_429_in_the_tabs_ledger_is_an_account_hold_before_any_query(browser):
    known_tab(browser, statuses=[200, 429], resources=2)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and state_of()['hold'] is not None


def test_a_tab_moved_to_the_checkpoint_page_stops_a_read_before_any_query(browser):
    known_tab(browser, location='https://www.threads.com/challenge/?next=%2F', runtime=False, user_id=None)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and state_of()['person']['reason'] == 'checkpoint'


def test_the_record_is_not_acknowledged_when_protection_could_not_hold_the_block(browser, data_dir):
    """record-cleared-only-after-transfer: with blocks.json unwritable the block cannot be recorded, so the command
    fails closed (exit 5) and the tab keeps what it saw (nothing acknowledged), emptied anyway so it stops polling."""
    known_tab(browser, signals=[signal(CHECKPOINT, at=77)])
    protection = data_dir / 'threads' / ASIDE / 'protection'
    protection.mkdir(parents=True, exist_ok=True)
    (protection / 'lock').touch(mode=0o600)  # the lock opens; the replace of blocks.json inside the directory does not
    protection.chmod(0o500)
    try:
        code, out, _ = run(browser, 'feed')
    finally:
        protection.chmod(0o700)
    assert code == 5 and queries(browser) == []
    assert 'threads.state' in browser.ops(), 'the tab was never looked at: the scenario did not run'
    assert Session('threads', ASIDE).ack == 0 and 'threads.blank' in browser.ops()
    assert state_of()['person'] is None  # nothing was recorded either


def test_a_lost_tab_gets_a_new_one_whose_checkpoint_is_found_before_any_query(browser):
    """lost-tab-new-tab-checked-first: the new tab's document shows the checkpoint; the opening cost is still reported."""
    browser.tab('T1', url='about:blank')
    Session('threads', ASIDE).set_tab('T1')
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=20, document='<html><form action="/challenge/action/"></form></html>'))
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 5 and queries(browser) == [] and state_of()['person']['reason'] == 'checkpoint'
    assert result['setup_requests'] == 40


def test_a_lost_tab_whose_replacement_lands_on_the_login_page_is_exit_4_before_any_query(browser):
    browser.tab('T1', url='about:blank')
    Session('threads', ASIDE).set_tab('T1')
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=20, location='https://www.threads.com/accounts/login/?next=%2F',
                                           user_id=None, runtime=False))
    code, out, _ = run(browser, 'feed')
    assert code == 4 and queries(browser) == [] and state_of()['person'] is None


def test_a_rate_limit_only_the_lost_tab_knew_is_recorded_when_the_one_query_meets_it_again(browser):
    """lost-tab-residual-risk: the new tab looks clean, so one query is sent; its reply carries the limit again."""
    browser.tab('T1', url='about:blank')
    Session('threads', ASIDE).set_tab('T1')
    opening(browser)
    browser.respond('threads.query', query_result(RATE_BODY))
    code, out, _ = run(browser, 'feed')
    assert code == 5 and len(queries(browser)) == 1 and state_of()['hold'] is not None


# --- the session (stores.json session scenarios) ----------------------------------------------------------------------

def test_a_lost_recorded_tab_is_replaced_and_the_first_line_reports_the_opening(browser):
    browser.tab('T1', url='about:blank')
    Session('threads', ASIDE).set_tab('T1')
    opening(browser).respond('threads.query', one_post())
    code, out, _ = run(browser, 'feed')
    assert code == 0 and 'tab opened (+40 requests)' in out.splitlines()[0], out
    assert Session('threads', ASIDE).tab == 'NEW1'


def test_a_threads_tab_the_user_has_open_is_never_adopted_or_touched(browser):
    browser.tab('USER', url='https://www.threads.com/@someone')
    opening(browser).respond('threads.query', one_post())
    code, out, _ = run(browser, 'feed')
    assert code == 0 and Session('threads', ASIDE).tab == 'NEW1'
    assert all(call.get('tab') != 'USER' for call in browser.calls())


def test_each_aside_account_has_its_own_session_and_tab(browser):
    known_tab(browser).respond('threads.query', one_post())
    assert run(browser, 'feed')[0] == 0
    opening(browser, target='NEW9').respond('threads.query', one_post())
    code, out, _ = run(browser, 'feed', env={'SNS_ASIDE_ACCOUNT': 'u1'})
    assert code == 0 and Session('threads', 'u1').tab == 'NEW9' and Session('threads', ASIDE).tab == 'T1'



@pytest.mark.parametrize('signal', ['checkpoint', '429'])
def test_a_block_in_an_answer_shown_to_another_account_is_still_recorded(browser, signal):
    """Found by review: the account check ran before the answer was judged, so a checkpoint or a 429 in an answer that
    came back under another account was never recorded (exit 4 with nothing in protection)."""
    known_tab(browser)
    response = (query_result(CHECKPOINT, user_id='1000000077') if signal == 'checkpoint'
                else query_result('', status=429, statuses=[429], user_id='1000000077'))
    browser.respond('threads.query', response)
    code, out, _ = run(browser, 'feed', '--json')
    recorded = state_of()
    assert recorded['person' if signal == 'checkpoint' else 'hold'] is not None, (code, out, recorded)


def test_a_checkpoint_in_the_answer_is_recorded_even_with_a_rate_limit_seen_beside_it(browser):
    """Found by review: the tab's own 429 was recorded and raised first, and the answer's checkpoint never was."""
    known_tab(browser)
    browser.respond('threads.query', query_result(CHECKPOINT, resources=2, statuses=[200, 429]))
    code, out, _ = run(browser, 'feed', '--json')
    recorded = state_of()
    assert recorded['person'] is not None and recorded['hold'] is not None
    assert code == 5 and json.loads(out)['error'] == 'blocked', out


@pytest.mark.parametrize('with_signal', [False, True])
def test_a_block_in_an_answer_is_recorded_for_the_account_that_answered(browser, with_signal):
    """Found by the second review: the answer's checkpoint was recorded for the command's starting account, not the
    one the answer came back under, so a later unblock checked the wrong account."""
    known_tab(browser)
    signals = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': CHECKPOINT, 'at': 101}] \
        if with_signal else []
    browser.respond('threads.query', query_result(CHECKPOINT, user_id='1000000077', signals=signals))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 5 and state_of()['person']['viewer'] == '1000000077', out


def test_a_checkpoint_and_a_rate_limit_among_the_tabs_signals_are_both_recorded(browser):
    """Found by the second review: only the strongest of the tab's signals was recorded; the hold beside the
    checkpoint was lost, and an unblock would not have waited for it."""
    known_tab(browser)
    signals = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': CHECKPOINT, 'at': 101}]
    browser.respond('threads.query', query_result(feed_body([], False, None), resources=2, statuses=[200, 429],
                                                  signals=signals))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 5 and state_of()['person'] is not None and state_of()['hold'] is not None, out


@pytest.mark.parametrize('failed_write', [1, 2])
def test_the_tabs_signals_are_acknowledged_only_once_every_stop_they_name_is_saved(browser, monkeypatch, failed_write):
    """Found by the third review: with a hold and a checkpoint among the signals, the hold's save acknowledged them, so
    a failed save of the checkpoint left it acknowledged (the tab drops it) and recorded nowhere."""
    import errno
    import os
    from pathlib import Path
    known_tab(browser)
    signals = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': CHECKPOINT, 'at': 101}]
    browser.respond('threads.query', query_result(feed_body([], False, None), resources=2, statuses=[200, 429],
                                                  signals=signals))
    original, writes = os.replace, []

    def replace(source, destination):
        if Path(destination).name == 'blocks.json':
            writes.append(1)
            if len(writes) == failed_write:
                raise OSError(errno.ENOSPC, 'simulated full disk')
        return original(source, destination)

    browser.install(monkeypatch)
    monkeypatch.setattr('os.replace', replace)
    import cli
    code = cli.main(['threads', 'feed', '--json'])
    assert code == 5 and Session('threads', ASIDE).ack == 0
