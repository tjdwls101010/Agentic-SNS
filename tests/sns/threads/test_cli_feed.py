"""feed through the real CLI and a scripted Aside: pages, units, windows (fixtures/paging.json), handles, output."""
import json

import pytest

from tests.sns.threads.scenes import feed_body, known_tab, post, query_result, queries, rerun, run, state

def test_foryou_never_closes_a_window(browser):
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', '2026-09-01T00:00:00Z')]], False, None)))
    code, out, _ = run(browser, 'feed', '--since', '2026-10-01', '--json')
    assert json.loads(out)['window']['coverage'] == 'sample (not in date order)' and code == 7


def test_one_page_by_default_and_more_continues_from_the_kept_tail(browser):
    page1 = feed_body([[post('A', '2026-10-08T03:00:00Z')], [post('B', '2026-10-07T03:00:00Z')]], True, 'CUR1')
    page2 = feed_body([[post('B', '2026-10-07T03:00:00Z')], [post('C', '2026-10-06T03:00:00Z')]], False, None)
    known_tab(browser).respond('threads.query', query_result(page1))
    code, out, _ = run(browser, 'feed', '--limit', '1')
    assert code == 0 and '[p1]' in out and 'more: ' in out
    assert browser.ops().count('threads.query') == 1
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    browser.respond('threads.state', state()).respond('threads.query', query_result(page2))
    code, out, _ = rerun(browser, more)
    assert code == 0
    shown = [line for line in out.splitlines() if line.startswith('[p')]
    assert len(shown) == 1 and browser.ops().count('threads.query') == 1  # B came from the kept tail: no request
    assert queries(browser)[0]['args']['variables']['variant'] == 'for_you'


def test_a_unit_shows_a_reply_and_a_continuation_together(browser):
    other = {'pk': '1000000002', 'username': 'someone.else'}
    first, reply = post('Q', '2026-10-08T03:00:00Z'), post('R', '2026-10-08T04:00:00Z', author=other)
    reply['text_post_app_info'].update(is_reply=True, reply_to_id=first['pk'])
    cont = post('S', '2026-10-08T05:00:00Z')
    cont['text_post_app_info'].update(is_reply=True, reply_to_id=reply['pk'])
    known_tab(browser).respond('threads.query', query_result(feed_body([[first, reply, cont]], False, None)))
    code, out, _ = run(browser, 'feed')
    assert code == 0
    lines = [line for line in out.splitlines() if line.lstrip().startswith('[p')]
    assert 'reply-to=p1' in lines[1] and 'reply-to=p2' in lines[2]  # S answers R, a different author
    assert lines[1].startswith('  [p2]')


def test_the_header_names_feed_cost_and_the_text_preview(browser):
    text = 'x' * 300
    raw = post('A', '2026-10-08T03:00:00Z')
    raw['caption'] = {'text': text}
    known_tab(browser, resources=3).respond('threads.query', query_result(feed_body([[raw]], True, 'CUR1'), resources=2))
    code, out, _ = run(browser, 'feed', '--feed', 'following')
    header = out.splitlines()[0]
    assert header.startswith('threads feed · feed=following · 1 shown · stopped=limit_reached · requests=2')
    assert 'requests=2/' not in header  # there is no request budget
    assert 'unwatched=3' in header
    assert 'text[180 of 300 chars shown]' in out and 'url: "https://www.threads.com/@example.author/post/CA"' in out


def test_json_keeps_whole_texts_and_variables_follow_the_feed(browser):
    raw = post('A', '2026-10-08T03:00:00Z')
    raw['caption'] = {'text': 'y' * 500}
    known_tab(browser).respond('threads.query', query_result(feed_body([[raw]], False, None)))
    code, out, _ = run(browser, 'feed', '--feed', 'following', '--json')
    result = json.loads(out)
    assert code == 0 and result['results'][0]['text'] == 'y' * 500 and result['query']['feed'] == 'following'
    [call] = [c for c in browser.calls() if c['op'] == 'threads.query']
    assert call['args']['name'] == 'BarcelonaFeedDirectQuery'
    assert call['args']['variables']['variant'] == 'following'
    assert call['args']['variables']['data']['pagination_source'] == 'text_post_feed_following'


def test_records_read_before_a_failure_print_as_text_and_the_help_says_so(browser):
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')]], True, 'CUR1')))
    browser.respond('threads.query', query_result('oops', status=500))
    code, out, _ = run(browser, 'feed', '--limit', '10')
    assert code == 8
    assert out.startswith('threads feed · ') and '[p1]' in out and 'coverage: incomplete — ' in out
    _, help_text, _ = run(browser, 'feed', '--help')
    assert 'records read before a failure print as usual' in ' '.join(help_text.split())


@pytest.mark.parametrize('feed', ['foryou', 'following'])
def test_a_collection_of_an_endless_feed_needs_a_limit(browser, feed, tmp_path):
    """Neither feed ends by itself: --out without --limit would never finish (exit 2 before any request)."""
    code, out, _ = run(browser, 'feed', '--feed', feed, '--out', str(tmp_path / 'feed.ndjson'))
    envelope = json.loads(out)
    assert code == 2 and envelope['error'] == 'argument' and '--limit' in envelope['fix']
    assert browser.calls() == [] and not (tmp_path / 'feed.ndjson').exists()


def test_the_for_you_feed_with_a_window_reads_one_page_and_more_continues(browser):
    """A ranked feed cannot close a window: with no --limit it reads one page (it used to read until a budget ran out)."""
    today = '2026-10-08T03:00:00Z'
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', today)]], True, 'CUR1')))
    code, out, _ = run(browser, 'feed', '--since', '2026-10-01', '--json')
    result = json.loads(out)
    assert code == 0 and [r['unavailable'] for r in result['results']] == [False] and result['next']
    assert result['window']['coverage'] == 'sample (not in date order)' and len(queries(browser)) == 1
    assert '--since 2026-10-01' in result['next']


def test_the_following_feed_closes_a_window_at_the_first_page_older_than_it(browser):
    old = '2026-09-01T03:00:00Z'
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')]], True, 'CUR1')))
    browser.respond('threads.query', query_result(feed_body([[post('B', old)]], True, 'CUR2')))
    code, out, _ = run(browser, 'feed', '--feed', 'following', '--since', '2026-10-01', '--json')
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'window_reached' and len(result['results']) == 1
    assert result['window']['coverage'] == 'closed (as served)' and len(queries(browser)) == 2
