"""replies through the real cli.py and a fake Aside: a comment's replies a batch at a time, deeper replies by handle."""
import json
import re

from conftest import STATE_OK, command_of, query_result, run_cli
from test_cli_thread import URL, comment, script_post


def replies_body(parent, nodes, has_next=True, cursor='R1'):
    return json.dumps({'data': {'node': {'__typename': 'Feedback', 'id': 'F' + parent, 'replies_connection': {
        'edges': [{'node': n} for n in nodes],
        'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}}}})


def handle_of(out, person):
    return re.search(rf'author: "https://www.facebook.com/person.{person}"   replies (\d+)', out).group(1)


def test_a_comments_replies_batch_by_batch_and_deeper(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=12)], has_next=False)
    code, out, _ = run_cli(browser, 'post', URL)
    first = handle_of(out, 'c1')

    batch = [comment(f'R{i}', replies=(1 if i == 1 else 0), depth=1, parent='C1') for i in range(1, 11)]
    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(replies_body('C1', batch, cursor='RC1')), name='Depth1CommentsListPaginationQuery')
    code, out, _ = run_cli(browser, 'replies', first)
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'replies · 10 shown · stopped=limit_reached · requests=1/25'
    assert lines[1] == f'thread: post "{URL}" · replies to comment C1'
    assert lines[2].startswith('  [c1] Person R1')
    deeper = handle_of(out, 'r1')
    assert not re.search(r'person.r2"   replies', out)
    sent = [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['variables']
    assert (sent['id'], sent['expansionToken'], sent['repliesAfterCursor']) == ('FC1', 'tok-C1', None)
    more = command_of(lines[-1])
    assert more[0] == 'replies' and more[1] != first

    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(replies_body('C1', [comment('R11', replies=0, depth=1, parent='C1')],
                                                       has_next=False)), name='Depth1CommentsListPaginationQuery')
    code, out, _ = run_cli(browser, *more)
    assert code == 0 and 'Person R11' in out and 'stopped=exhausted' in out and 'more:' not in out
    sent = [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['variables']
    assert sent['repliesAfterCursor'] == 'RC1'

    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(replies_body('R1', [comment('D1', replies=0, depth=2, parent='R1')],
                                                       has_next=False)), name='Depth2CommentsListPaginationQuery')
    code, out, _ = run_cli(browser, 'replies', deeper)
    assert code == 0 and 'Person D1' in out
    assert out.splitlines()[1] == f'thread: post "{URL}" · replies to comment R1'


def test_a_handle_is_reread_not_consumed(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=2)], has_next=False)
    code, out, _ = run_cli(browser, 'post', URL)
    first = handle_of(out, 'c1')
    for _ in range(2):
        browser.respond('state', STATE_OK)
        browser.respond('query', query_result(replies_body('C1', [comment('R1', replies=0, depth=1, parent='C1')],
                                                           has_next=False)), name='Depth1CommentsListPaginationQuery')
        code, out, _ = run_cli(browser, 'replies', first)
        assert code == 0 and 'Person R1' in out


def test_a_feed_handle_is_not_a_replies_handle(browser, data_dir):
    from conftest import graphql_body, known_tab, story
    known_tab(browser, data_dir)
    browser.respond('query', query_result(graphql_body(['viewer', 'news_feed'], [story('A'), story('B')])))
    code, out, _ = run_cli(browser, 'feed', '--limit', '1')
    number = re.search(r'--after (\d+)', out).group(1)
    browser.respond('state', STATE_OK)
    code, out, _ = run_cli(browser, 'replies', number)
    assert code == 2 and 'another command' in json.loads(out)['message']


def test_replies_handle_must_be_a_number(browser, data_dir):
    code, out, _ = run_cli(browser, 'replies', '../x')
    assert code == 2 and browser.calls() == []


def test_fewer_replies_than_facebook_reports_is_said(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=26)], has_next=False)
    code, out, _ = run_cli(browser, 'post', URL)
    first = handle_of(out, 'c1')
    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(replies_body('C1', [comment('R1', replies=0, depth=1, parent='C1')],
                                                       has_next=False)), name='Depth1CommentsListPaginationQuery')
    code, out, _ = run_cli(browser, 'replies', first)
    assert code == 0
    assert 'coverage: Facebook reports 26 replies under this comment (deeper ones included); 1 were sent' in out


def test_an_empty_batch_that_says_more_is_not_an_empty_result(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=3)], has_next=False)
    code, out, _ = run_cli(browser, 'post', URL)
    first = handle_of(out, 'c1')
    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(replies_body('C1', [], has_next=True, cursor='RC9')),
                    name='Depth1CommentsListPaginationQuery')
    code, out, _ = run_cli(browser, 'replies', first, '--json')
    result = json.loads(out)
    assert code == 0 and result['ok'] is True and 'error' not in result and result['next']
