"""X's use of the session store (fixtures/stores.json, session): the one dedicated tab per Aside account, the tab
record's life through opening, loss and the idle cleanup, the operation ids a verified read teaches and the nonce
statistics. The store itself (leases, the lock, a reset, the viewer hint, ack and dirty) is core/test_session.py."""
import json
import time

from sns.session import Session
from tests.sns.x.scenes import ASIDE, MODULES, known_tab, opening, query_result, queries, run, state_of
from tests.sns.x.test_cli_feed import RATE, entry, home, post


def one_post():
    return query_result(home([entry(post('1850000000000000001'))]), headers=RATE)


def test_a_recorded_tab_that_is_still_open_is_reused(browser):
    known_tab(browser).respond('x.query', one_post())
    code, out, _ = run(browser, 'feed')
    assert code == 0 and 'opener' not in browser.ops() and 'tab opened' not in out.splitlines()[0]
    assert Session('x', ASIDE).tab == 'T1'


def test_a_lost_tab_is_replaced_and_the_first_line_reports_what_opening_cost(browser):
    browser.tab('OTHER', url='https://example.org/')  # T1 is recorded but gone
    Session('x', ASIDE).set_tab('T1')
    opening(browser, target='NEW1', resources=13).respond('x.query', one_post())
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert 'tab opened (+14 requests)' in out.splitlines()[0] and Session('x', ASIDE).tab == 'NEW1'


def test_a_tab_of_the_users_is_never_adopted(browser):
    browser.tab('MINE', url='https://x.com/home')  # open at x.com, but the skill never recorded it
    opening(browser, target='NEW1').respond('x.query', one_post())
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert Session('x', ASIDE).tab == 'NEW1'
    assert all(c.get('tab') != 'MINE' for c in browser.calls())  # the user's tab was not even looked at


def test_a_corrupt_session_opens_one_tab_rewrites_the_record_and_says_so(browser):
    directory = Session('x', ASIDE).directory
    (directory / 'tab.json').write_text('not json')
    opening(browser, target='NEW1').respond('x.query', one_post())
    code, out, _ = run(browser, 'feed', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['session_reset'] is True and envelope['setup_requests'] == 14
    assert Session('x', ASIDE).reset is False and Session('x', ASIDE).tab == 'NEW1'


def test_each_aside_account_has_its_own_tab(browser, data_dir):
    known_tab(browser)  # recorded for u0
    opening(browser, target='NEW1').respond('x.query', one_post())
    code, out, _ = run(browser, 'feed', env={'SNS_ASIDE_ACCOUNT': 'u1'})
    assert code == 0 and 'tab opened' in out.splitlines()[0], out
    assert Session('x', 'u1').tab == 'NEW1' and Session('x', ASIDE).tab == 'T1'
    assert (data_dir / 'x' / 'u1' / 'session').is_dir()


def test_the_idle_cleanup_empties_the_tab_and_the_next_command_opens_a_new_one(browser):
    known_tab(browser).respond('x.query', one_post())
    code, out, _ = run(browser, 'feed', env={'SNS_IDLE_SECONDS': '1'})
    assert code == 0, out
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and 'x.close' not in browser.ops():
        time.sleep(0.2)
    assert 'x.close' in browser.ops(), browser.ops()  # X's tab is closed first (Aside closes an emptied one anyway)
    opening(browser, target='NEW2').respond('x.query', one_post())
    code, out, _ = run(browser, 'feed')
    assert code == 0 and 'tab opened' in out.splitlines()[0] and Session('x', ASIDE).tab == 'NEW2'


def test_the_idle_cleanup_takes_in_what_the_tab_saw_before_it_empties_it(browser):
    """X's part of the cleanup: a lock the app met on its own is recorded (the tab is about to go) and the requests it
    made since the last command are logged as seen, never charged."""
    lock = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None,
            'at': 1792148826874}
    known_tab(browser, resources=3, signals=[lock])
    code, out, _ = run(browser, 'idle', '--account', ASIDE, '--token', 'any', '--after', '0')
    assert code == 0 and json.loads(out)['outcome'] == 'emptied', out
    assert state_of()['block_reason'] == 'account_locked' and 'x.close' in browser.ops()
    assert Session('x', ASIDE).ack == 1792148826874 and not Session('x', ASIDE).dirty


def test_an_id_a_verified_read_taught_is_the_fallback_of_the_next_command(browser):
    known_tab(browser).respond('x.query', one_post())
    run(browser, 'feed')
    assert Session('x', ASIDE).query('HomeTimeline')['doc_id'] == 'SYNTHq'  # the live id the tab gave
    known_tab(browser).respond('x.query', one_post())
    run(browser, 'feed')
    assert queries(browser)[-1]['args']['fallback']['query_id'] == 'SYNTHq'


def test_an_id_from_a_read_that_failed_is_not_learned(browser):
    known_tab(browser).respond('x.query', query_result('{"errors":[{"message":"x must be defined"}]}', status=422))
    code, _, _ = run(browser, 'feed')
    assert code == 6 and Session('x', ASIDE).query('HomeTimeline') is None


def test_the_nonce_statistics_count_own_requests_and_what_the_tab_matched(browser):
    known_tab(browser).respond('x.query', one_post())
    run(browser, 'feed')
    assert Session('x', ASIDE).nonce == {'sent': 1, 'matched': 1}
    known_tab(browser).respond('x.modules', MODULES)
    code, out, _ = run(browser, 'doctor')
    assert json.loads(out)['results'][0]['own_request_matching'] == 'confirmed'
