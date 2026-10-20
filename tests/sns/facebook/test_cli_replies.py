"""replies through the real cli.py and a fake Aside: a comment's replies a batch at a time, deeper replies by handle. The
handles are saved while the comments are read and belong to the command replies and to the account that read them."""
import json
import re

from tests.sns.facebook.scenes import graphql_body, known_tab, look, queries, query_result, rerun, run, story
from tests.sns.facebook.test_cli_thread import URL, comment, script_post


def replies_body(parent, nodes, has_next=True, cursor='R1'):
    return json.dumps({'data': {'node': {'__typename': 'Feedback', 'id': 'F' + parent, 'replies_connection': {
        'edges': [{'node': n} for n in nodes],
        'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}}}})


def handle_of(out, person):
    return re.search(rf'author: "https://www.facebook.com/person.{person}"   replies (\d+)', out).group(1)


def serve(browser, parent, nodes, name='Depth1CommentsListPaginationQuery', **kwargs):
    look(browser)
    browser.respond('facebook.query', query_result(replies_body(parent, nodes, **kwargs)), name=name)


def test_a_comments_replies_batch_by_batch_and_deeper(browser):
    script_post(browser, [comment('C1', replies=12)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    first = handle_of(out, 'c1')

    batch = [comment(f'R{i}', replies=(1 if i == 1 else 0), depth=1, parent='C1') for i in range(1, 11)]
    serve(browser, 'C1', batch, cursor='RC1')
    code, out, _ = run(browser, 'replies', first)
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'facebook replies · 10 shown · stopped=limit_reached · requests=1'
    assert lines[1] == f'thread: post "{URL}" · replies to comment C1'
    assert lines[2].startswith('  [c1] Person R1')
    deeper = handle_of(out, 'r1')
    assert not re.search(r'person.r2"   replies', out)
    variables = queries(browser)[-1]['args']['variables']
    assert (variables['id'], variables['expansionToken'], variables['repliesAfterCursor']) == ('FC1', 'tok-C1', None)
    more = lines[-1]
    assert re.search(r'facebook replies (\d+)$', more) and re.search(r'replies (\d+)$', more).group(1) != first

    serve(browser, 'C1', [comment('R11', replies=0, depth=1, parent='C1')], has_next=False)
    code, out, _ = rerun(browser, more)
    assert code == 0 and 'Person R11' in out and 'stopped=exhausted' in out and 'more:' not in out
    assert queries(browser)[-1]['args']['variables']['repliesAfterCursor'] == 'RC1'

    serve(browser, 'R1', [comment('D1', replies=0, depth=2, parent='R1')], name='Depth2CommentsListPaginationQuery',
          has_next=False)
    code, out, _ = run(browser, 'replies', deeper)
    assert code == 0 and 'Person D1' in out
    assert out.splitlines()[1] == f'thread: post "{URL}" · replies to comment R1'


def test_a_handle_is_reread_not_consumed(browser):
    script_post(browser, [comment('C1', replies=2)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    first = handle_of(out, 'c1')
    for _ in range(2):
        serve(browser, 'C1', [comment('R1', replies=0, depth=1, parent='C1')], has_next=False)
        code, out, _ = run(browser, 'replies', first)
        assert code == 0 and 'Person R1' in out


def test_a_feed_handle_is_not_a_replies_handle(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(graphql_body(['viewer', 'news_feed'], [story('A'), story('B')])))
    code, out, _ = run(browser, 'feed', '--limit', '1')
    number = re.search(r'--after (\d+)', out).group(1)
    look(browser)
    code, out, _ = run(browser, 'replies', number)
    assert code == 2 and 'belongs to facebook feed' in json.loads(out)['message']


def test_replies_handle_must_be_a_number(browser):
    code, out, _ = run(browser, 'replies', '../x')
    assert code == 2 and browser.calls() == []


def test_a_replies_handle_read_as_another_account_is_a_changed_login(browser):
    script_post(browser, [comment('C1', replies=2)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    first = handle_of(out, 'c1')
    look(browser, user_id='222')
    code, out, _ = run(browser, 'replies', first)
    assert code == 4 and json.loads(out)['error'] == 'login' and len(queries(browser)) == 2


def test_fewer_replies_than_facebook_reports_is_said(browser):
    script_post(browser, [comment('C1', replies=26)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    first = handle_of(out, 'c1')
    serve(browser, 'C1', [comment('R1', replies=0, depth=1, parent='C1')], has_next=False)
    code, out, _ = run(browser, 'replies', first)
    assert code == 0
    assert 'coverage: Facebook reports 26 replies under this comment (deeper ones included); 1 were sent' in out


def test_an_empty_batch_that_says_more_is_not_an_empty_result(browser):
    script_post(browser, [comment('C1', replies=3)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    first = handle_of(out, 'c1')
    serve(browser, 'C1', [], has_next=True, cursor='RC9')
    code, out, _ = run(browser, 'replies', first, '--json')
    result = json.loads(out)
    assert code == 0 and result['ok'] is True and 'error' not in result and result['next']


def test_reply_coverage_counts_what_an_earlier_out_run_saved(browser, tmp_path):
    """A resumed --out reading counts the replies already in the file."""
    script_post(browser, [comment('C1', replies=4)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    first = handle_of(out, 'c1')
    target = str(tmp_path / 'replies.ndjson')
    serve(browser, 'C1', [comment(f'R{i}', replies=0, depth=1, parent='C1') for i in (1, 2)], cursor='RC1')
    code, out, _ = run(browser, 'replies', first, '--out', target, '--limit', '2', '--json')
    assert code == 0, out
    serve(browser, 'C1', [comment(f'R{i}', replies=0, depth=1, parent='C1') for i in (3, 4)], has_next=False)
    code, out, _ = run(browser, 'replies', first, '--out', target, '--json')
    result = json.loads(out)
    assert code == 0 and result['count'] == 4
    assert not any('were sent' in line for line in result.get('coverage', []))


def test_the_replies_under_a_reply_are_its_whole_sub_thread_whoever_each_one_answers(browser):
    """Observed 2026-10-21: the second-level list of a reply holds its sub-thread, every node at depth 2, and each node
    names as its direct parent the comment it answers: the top comment or another reply in the sub-thread, seldom the
    expanded reply itself. All of them are the replies under it."""
    script_post(browser, [comment('C1', replies=12)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    serve(browser, 'C1', [comment('R1', replies=3, depth=1, parent='C1')], has_next=False)
    code, out, _ = run(browser, 'replies', handle_of(out, 'c1'))
    deeper = handle_of(out, 'r1')
    serve(browser, 'R1', [comment('D1', replies=0, depth=2, parent='C1'), comment('D2', replies=0, depth=2, parent='D1'),
                          comment('D3', replies=0, depth=2, parent='R1')],
          name='Depth2CommentsListPaginationQuery', has_next=False)
    code, out, _ = run(browser, 'replies', deeper, '--json')
    result = json.loads(out)
    assert code == 0, result
    assert [(r['id'], r['parent_id']) for r in result['results']] == [('D1', 'C1'), ('D2', 'D1'), ('D3', 'R1')]


def test_the_replies_under_a_reply_are_one_batch_because_facebook_repeats_it_when_asked_for_more(browser):
    """Observed 2026-10-21 (D6): asked for the next batch of a reply's replies (after or before cursor, with or without
    a count), Facebook sends the first batch again. The first batch is all a reply's replies can give, said so; no
    more: that would return the same replies."""
    script_post(browser, [comment('C1', replies=50)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    serve(browser, 'C1', [comment('R1', replies=30, depth=1, parent='C1')], has_next=False)
    code, out, _ = run(browser, 'replies', handle_of(out, 'c1'))
    serve(browser, 'R1', [comment(f'D{i}', replies=0, depth=2, parent='C1') for i in range(1, 11)],
          name='Depth2CommentsListPaginationQuery', has_next=True, cursor='DC1')
    code, out, _ = run(browser, 'replies', handle_of(out, 'r1'))
    assert code == 0, out
    assert out.splitlines()[0] == 'facebook replies · 10 shown · stopped=server_capped · requests=1'
    assert 'coverage: Facebook reports 30 replies under this comment (deeper ones included); 10 were sent' in out
    assert 'more:' not in out


def test_a_deeper_branch_read_in_parts_still_ends_server_capped(browser):
    """Found by review: --limit split the capped batch, and the continuation served the rest and called it exhausted."""
    script_post(browser, [comment('C1', replies=50)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    serve(browser, 'C1', [comment('R1', replies=30, depth=1, parent='C1')], has_next=False)
    code, out, _ = run(browser, 'replies', handle_of(out, 'c1'))
    serve(browser, 'R1', [comment(f'D{i}', replies=0, depth=2, parent='C1') for i in range(1, 3)],
          name='Depth2CommentsListPaginationQuery', has_next=True, cursor='DC1')
    code, out, _ = run(browser, 'replies', handle_of(out, 'r1'), '--limit', '1', '--json')
    first = json.loads(out)
    assert code == 0 and first.get('next'), out
    look(browser)
    code, out, _ = rerun(browser, 'more: ' + first['next'])
    last = json.loads(out)
    assert code == 0 and [r['id'] for r in last['results']] == ['D2'] and last['stop_reason'] == 'server_capped'
    assert not last.get('next') and len(queries(browser)) == 4  # the rest came from the handle: no request
