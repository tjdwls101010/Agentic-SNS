"""--out collections through the real cli.py and a fake Aside: page commits, resume, complete, refusals. The file format
and its integrity rules are the core's (core/test_outfile.py); this is what Facebook's commands do with them."""
import json
import re

from sns.session import Session
from tests.sns.facebook.scenes import (ASIDE, graphql_body, known_tab, look, page_result, queries, query_result, rerun, run,
                                       state_of, story)
from tests.sns.facebook.test_cli_replies import replies_body
from tests.sns.facebook.test_cli_thread import URL, comment, comments_body, script_post

FEED = ['viewer', 'news_feed']


def page(ids, has_next=True, cursor='C1'):
    return query_result(graphql_body(FEED, [story(i) for i in ids], has_next, cursor))


def browser_calls(browser):
    """What was asked of the browser (resolving the Aside account is not that)."""
    return [c for c in browser.calls() if c['op'] != 'account_status']


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_collect_resume_and_complete(browser, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser)
    browser.respond('facebook.query', page(['A', 'B'], cursor='C1'))
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0, text
    assert text.startswith('facebook feed · 2 saved to "') and ' · sort=top · stopped=limit_reached' in text
    assert 'resume: ' in text
    assert [r['id'] for r in lines(out) if 'id' in r] == ['A', 'B'] and lines(out)[0]['kind'] == 'header'
    resume = text.strip().split('resume: ')[1]
    assert resume.endswith(f'facebook feed --sort top --limit 2 --out={out}')

    look(browser).respond('facebook.query', page(['B', 'C'], has_next=False))
    code, text, _ = rerun(browser, 'resume: ' + resume, '--limit', '3')
    assert code == 0 and '3 saved' in text and 'stopped=exhausted' in text
    assert [r['id'] for r in lines(out) if 'id' in r] == ['A', 'B', 'C']
    assert queries(browser)[-1]['args']['variables']['cursor'] == 'C1'


def test_a_complete_collection_touches_no_browser(browser, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser)
    browser.respond('facebook.query', page(['A'], has_next=False))
    code, text, _ = run(browser, 'feed', '--sort', 'recent', '--out', str(out))
    assert code == 0 and 'stopped=exhausted' in text
    Session('facebook', ASIDE).set_tab(None)  # the dedicated tab is no longer known
    calls = len(browser_calls(browser))
    code, text, _ = run(browser, 'feed', '--sort', 'recent', '--out', str(out), '--json')
    result = json.loads(text)
    assert code == 0 and result['already_complete'] is True and result['request_count'] == 0
    assert len(browser_calls(browser)) == calls


def test_a_resumed_profile_collection_does_not_look_its_id_up_again(browser, tmp_path):
    out = tmp_path / 'profile.ndjson'
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/some.person',
                                                 '<script>{"userID":"1000777"}</script>'))
    timeline = ['node', 'timeline_list_feed_units']
    browser.respond('facebook.query', query_result(graphql_body(timeline, [story('A'), story('B')], True, 'T1')))
    code, text, _ = run(browser, 'profile', 'some.person', '--out', str(out), '--limit', '2')
    assert code == 0 and '2 saved' in text
    look(browser).respond('facebook.query', query_result(graphql_body(timeline, [story('C')], False)))
    code, text, _ = run(browser, 'profile', 'some.person', '--out', str(out), '--limit', '3')
    assert code == 0 and '3 saved' in text
    assert len([c for c in browser.calls() if c['op'] == 'facebook.page']) == 1
    assert [q['args']['variables']['id'] for q in queries(browser)] == ['1000777', '1000777']


def lose_the_final_line(path):
    """A run that committed its last page and died before it wrote the final line: the file is cut after the marker."""
    kept = path.read_text().splitlines()
    assert json.loads(kept[-1]).get('end') == 'final'
    path.write_text('\n'.join(kept[:-1]) + '\n')


def test_a_comments_collection_missing_only_its_final_line_is_closed_without_a_request(browser, tmp_path):
    out = tmp_path / 'comments.ndjson'
    script_post(browser, [comment('C1', replies=0)], has_next=False)
    code, text, _ = run(browser, 'comments', URL, '--out', str(out), '--limit', '5')
    assert code == 0 and '1 saved' in text
    lose_the_final_line(out)
    look(browser)
    code, text, _ = run(browser, 'comments', URL, '--out', str(out), '--limit', '5', '--json')
    result = json.loads(text)
    assert code == 0 and result['request_count'] == 0 and result['count'] == 1 and result['stop_reason'] == 'exhausted'
    assert json.loads(out.read_text().splitlines()[-1]).get('end') == 'final'


def test_a_replies_collection_missing_only_its_final_line_is_closed_without_a_request(browser, tmp_path):
    out = tmp_path / 'replies.ndjson'
    script_post(browser, [comment('C1', replies=1)], has_next=False)
    code, text, _ = run(browser, 'post', URL)
    first = re.search(r'replies (\d+)', text).group(1)
    look(browser).respond('facebook.query', query_result(replies_body(
        'C1', [comment('R1', replies=0, depth=1, parent='C1')], has_next=False)), name='Depth1CommentsListPaginationQuery')
    run(browser, 'replies', first, '--out', str(out), '--limit', '5')
    lose_the_final_line(out)
    look(browser)
    code, text, _ = run(browser, 'replies', first, '--out', str(out), '--limit', '5', '--json')
    result = json.loads(text)
    assert code == 0 and result['request_count'] == 0 and result['count'] == 1


def test_a_profile_collection_missing_only_its_final_line_does_not_look_its_id_up_again(browser, tmp_path):
    out = tmp_path / 'profile.ndjson'
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/some.person',
                                                 '<script>{"userID":"1000777"}</script>'))
    browser.respond('facebook.query', query_result(graphql_body(['node', 'timeline_list_feed_units'], [story('A')], False)))
    run(browser, 'profile', 'some.person', '--out', str(out), '--limit', '5')
    lose_the_final_line(out)
    look(browser)
    code, text, _ = run(browser, 'profile', 'some.person', '--out', str(out), '--limit', '5', '--json')
    result = json.loads(text)
    assert code == 0 and result['request_count'] == 0 and len([c for c in browser.calls() if c['op'] == 'facebook.page']) == 1


def test_a_file_of_another_query_is_refused_unchanged(browser, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser)
    browser.respond('facebook.query', page(['A'], has_next=False))
    run(browser, 'feed', '--sort', 'recent', '--out', str(out))
    before = out.read_bytes()
    look(browser)
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '5')
    assert code == 2 and json.loads(text)['error'] == 'argument'
    assert out.read_bytes() == before


def test_a_previous_versions_file_is_refused_unchanged(browser, tmp_path):
    out = tmp_path / 'old.ndjson'
    out.write_text(json.dumps({'kind': 'header', 'format': 2, 'command': 'feed', 'target': None, 'sort': 'top',
                               'window': {'since': None, 'until': None}, 'include_sponsored': False,
                               'account_id': '1000123', 'started_at': 'x', 'limit_unit': 'page'}) + '\n'
                   + json.dumps({'id': 'A'}) + '\n')
    before = out.read_bytes()
    known_tab(browser)
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '5')
    assert code == 2 and 'earlier version' in json.loads(text)['message']
    assert out.read_bytes() == before


def test_limit_counts_what_is_saved(browser, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser)
    browser.respond('facebook.query', page(['A', 'B', 'C'], cursor='C1'))
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and '3 saved' in text  # a page is committed whole
    look(browser)
    queried = len(queries(browser))
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and 'stopped=limit_reached' in text and len(queries(browser)) == queried


def test_out_and_after_cannot_be_combined(browser, tmp_path):
    code, text, _ = run(browser, 'feed', '--out', str(tmp_path / 'x'), '--after', '3', '--limit', '2')
    assert code == 2 and browser.calls() == []


def test_comments_collect_parents_and_resume_without_finding_the_post_again(browser, tmp_path):
    out = tmp_path / 'comments.ndjson'
    script_post(browser, [comment('C1', replies=0), comment('C2', replies=0)])
    code, text, _ = run(browser, 'comments', URL, '--out', str(out), '--limit', '2')
    assert code == 0 and '2 saved' in text and 'stopped=limit_reached' in text
    look(browser)
    browser.respond('facebook.query', query_result(comments_body([comment('C3', replies=0)], has_next=False)),
                    name='CommentsListComponentsPaginationQuery')
    code, text, _ = run(browser, 'comments', URL, '--out', str(out))
    assert code == 0 and '3 saved' in text, text
    assert not [c for c in browser.calls()[-3:] if c['op'] == 'facebook.page']


def test_a_rate_limited_collection_resumes_after_the_hold_and_a_checkpointed_one_does_not(browser, tmp_path):
    known_tab(browser)
    browser.respond('facebook.query', page(['A'], cursor='C1'))
    browser.respond('facebook.query', query_result('', status=429))
    code, out, _ = run(browser, 'feed', '--sort', 'recent', '--out', str(tmp_path / 'f.ndjson'), '--json')
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'rate_limited' and result['count'] == 1 and result['next']
    assert state_of()['hold'] and not state_of()['person']


def test_a_checkpointed_collection_does_not_offer_to_resume(browser, tmp_path):
    known_tab(browser)
    browser.respond('facebook.query', page(['A'], cursor='C1'))
    browser.respond('facebook.query', query_result(json.dumps({'checkpoint_url': 'https://www.facebook.com/checkpoint/1/'})))
    code, out, _ = run(browser, 'feed', '--sort', 'recent', '--out', str(tmp_path / 'g.ndjson'), '--json')
    result = json.loads(out)
    assert code == 5 and 'next' not in result and result['count'] == 1
