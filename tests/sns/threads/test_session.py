"""What Threads keeps in the session beyond the core's store (core/test_session.py): the Aside account that keys every
state, the ids a verified read taught, the account a continuation was read with."""
import json

from sns.session import Session
from tests.sns.threads.scenes import (ASIDE, feed_body, known_tab, post, query_result, queries, rerun, run,
                                      state)


def one_post(more=False):
    return query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')], [post('B', '2026-10-08T02:00:00Z')]], more, 'C1'))


def test_the_aside_account_is_the_resolved_id_so_a_named_default_shares_one_state(browser, data_dir):
    """Appendix C: the old reader keyed its state by the word 'default' when no account was named, so naming the same
    account split the state in two. Now the default is resolved to its id and both spellings are one."""
    known_tab(browser).respond('threads.query', one_post())
    assert run(browser, 'feed')[0] == 0                                     # `aside account status` says u0
    known_tab(browser, target='T2').respond('threads.query', one_post())
    assert run(browser, 'feed', env={'SNS_ASIDE_ACCOUNT': 'u0'})[0] == 0   # the same account, named
    sessions = sorted(str(p.relative_to(data_dir)) for p in data_dir.rglob('tab.json'))
    assert sessions == ['threads/u0/session/tab.json']
    assert not list(data_dir.rglob('default*'))


def test_an_id_a_verified_read_taught_is_the_fallback_of_the_next_command(browser):
    known_tab(browser).respond('threads.query', one_post())
    run(browser, 'feed')
    assert Session('threads', ASIDE).query('BarcelonaFeedDirectQuery')['doc_id'] == '111'  # the live id the tab gave
    known_tab(browser).respond('threads.query', one_post())
    run(browser, 'feed')
    assert queries(browser)[-1]['args']['fallback']['doc_id'] == '111'


def test_an_id_from_a_read_that_failed_is_not_learned(browser):
    known_tab(browser).respond('threads.query', query_result('oops', status=500))
    code, _, _ = run(browser, 'feed')
    assert code == 6 and Session('threads', ASIDE).query('BarcelonaFeedDirectQuery') is None


def test_a_continuation_read_as_another_account_is_a_changed_login(browser):
    """The Threads account sits beside a handle, not inside its context: a different one is exit 4, not a handle
    that 'belongs to another query' (appendix C)."""
    known_tab(browser).respond('threads.query', one_post(more=True))
    code, out, _ = run(browser, 'feed', '--limit', '1')
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    browser.respond('threads.state', state(user_id='1000000077'))
    code, out, _ = rerun(browser, more)
    assert code == 4 and json.loads(out)['error'] == 'login' and 'read as' in json.loads(out)['message'], out
    assert len(queries(browser)) == 1  # nothing was requested as the other account


def test_the_account_a_query_answer_shows_must_stay_the_commands_account(browser):
    known_tab(browser).respond('threads.query', one_post(more=True))
    browser.respond('threads.query', query_result(feed_body([[post('C', '2026-10-08T01:00:00Z')]], False, None),
                                                 user_id='1000000077'))
    code, out, _ = run(browser, 'feed', '--limit', '10')
    assert code == 4 and 'changed' in out and '[p1]' in out, out  # what was read before the change still prints
