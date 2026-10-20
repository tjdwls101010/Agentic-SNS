"""The dedicated tab classifies the app's own /i/api/ responses and keeps what it saw (fixtures/stores.json,
tab_protection): every command reads that record and the tab's location before it sends anything, turns a lock, a
challenge or a move to /account/access into a block and a 429 into that operation's window, and acknowledges the record
only once protection holds it. The kit's record itself (survives a reload, not a lost tab) is test_snippets.py."""
import json
import stat
import time

from sns.session import Session
from tests.sns.x.scenes import (ACCOUNT, ASIDE, guard, known_tab, limits, opening, query_result, queries, run,
                                state_of)
from tests.sns.x.test_cli_feed import RATE, entry, home, post

ACCESS = {'location': 'https://x.com/account/access', 'moved': '/account/access'}
LOGIN = {'location': 'https://x.com/i/flow/login', 'moved': '/i/flow/login'}


def signal(op, status=429, codes=(88,), at=101, remaining=0, reset=None):
    return {'path': f'/i/api/graphql/abc/{op}', 'status': status, 'codes': list(codes), 'html': False,
            'rate': {'limit': 50, 'remaining': remaining, 'reset': reset or int(time.time()) + 600}, 'at': at}


def lock(at=2):
    return signal('HomeTimeline', 200, (326,), at=at)


def search_page(ident):
    entries = [entry(post(ident)), {'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': 'C1'}}]
    return {'data': {'search_by_raw_query': {'search_timeline': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': entries}]}}}}}


def test_a_lock_the_app_met_between_commands_is_a_block_before_any_query_and_the_tab_closes(browser):
    """background-lock-then-reload (the record surviving the reload is test_snippets.py)."""
    known_tab(browser, signals=[lock(at=1792148826874)])
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and 'x.close' in browser.ops()
    assert state_of()['person']['reason'] == 'account_locked' and Session('x', ASIDE).ack == 1792148826874


def test_another_operations_429_is_recorded_and_acknowledged_and_the_search_runs(browser):
    other = signal('ViewerBadgeCounts', at=55)
    known_tab(browser, signals=[other]).respond('x.query', query_result(search_page('1850000000000000001'),
                                                                        headers=RATE))
    code, out, _ = run(browser, 'search', 'synthetic words')
    assert code == 0, out
    assert limits()['ViewerBadgeCounts']['blocked_until'] == other['rate']['reset']
    assert Session('x', ASIDE).ack == 55


def test_the_same_operations_429_stops_the_search_with_exit_10_naming_the_reset(browser):
    own = signal('SearchTimeline')
    known_tab(browser, signals=[own])
    code, out, _ = run(browser, 'search', 'synthetic words')
    envelope = json.loads(out)
    assert code == 10 and queries(browser) == [] and envelope['limit']['reset'] == own['rate']['reset']
    assert 'other commands' in envelope['fix'] and not state_of()['blocked']


def test_a_tab_on_the_access_page_is_a_block_and_no_query_is_sent(browser):
    known_tab(browser, **ACCESS)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and state_of()['block_reason'] == 'account_locked'


def test_a_signal_is_not_acknowledged_when_protection_cannot_record_it(browser):
    """record-cleared-only-after-transfer: fail closed, the tab keeps the record for the next command."""
    known_tab(browser, signals=[lock(at=77)])
    directory = guard().directory
    (directory / 'lock').touch()  # the lock file exists; without it an unwritable directory reads as the time limit
    directory.chmod(stat.S_IRUSR | stat.S_IXUSR)  # nothing can be written in it
    try:
        code, out, _ = run(browser, 'feed')
    finally:
        directory.chmod(0o700)
    assert code == 5 and queries(browser) == []
    assert Session('x', ASIDE).ack == 0 and not state_of()['blocked']


def test_a_new_tab_that_shows_the_access_page_is_a_block_and_the_opening_is_reported(browser):
    """lost-tab-new-tab-checked-first."""
    browser.tab('OLD', url='about:blank')
    Session('x', ASIDE).set_tab('GONE')
    opening(browser, **ACCESS, signals=[])
    code, out, _ = run(browser, 'feed')
    envelope = json.loads(out)
    assert code == 5 and queries(browser) == [] and state_of()['block_reason'] == 'account_locked'
    assert envelope['setup_requests'] >= 14, envelope  # what the opening cost is still told


def test_a_new_tab_that_lands_on_the_login_flow_needs_login_before_any_query(browser):
    """lost-tab-login."""
    Session('x', ASIDE).set_tab('GONE')
    opening(browser, **LOGIN, user_id=None)
    browser.respond('x.state', {})  # not reached: the first look decides
    code, out, _ = run(browser, 'feed')
    assert code == 4 and json.loads(out)['error'] == 'login' and queries(browser) == []
    assert not state_of()['blocked']


def test_a_lock_only_the_first_reply_of_a_clean_looking_new_tab_carries_is_recorded_then(browser):
    """lost-tab-residual-risk: the stated residual risk — one query is sent, its reply carries the lock."""
    Session('x', ASIDE).set_tab('GONE')
    opening(browser).respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE,
                                                      signals=[lock()]))
    code, out, _ = run(browser, 'feed')
    assert code == 5 and len(queries(browser)) == 1
    assert state_of()['person']['viewer'] == ACCOUNT
