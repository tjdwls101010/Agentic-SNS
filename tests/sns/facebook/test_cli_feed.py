"""feed through the real cli.py and a fake Aside: output contract, continuation, one page by default, the window of
each order, advertisements, and the failures a read can meet."""
import json
import re

from tests.sns.facebook.scenes import graphql_body, known_tab, look, queries, query_result, rerun, run, story

FEED = ['viewer', 'news_feed']


def page(stories, has_next=True, cursor='CUR1', **kwargs):
    return query_result(graphql_body(FEED, stories, has_next, cursor), **kwargs)


def more_of(out):
    return next(line for line in out.splitlines() if line.startswith('more: '))


def test_text_page_contract_and_continuation(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([story('A'), story('B'), story('C')], cursor='CUR1'))
    code, out, _ = run(browser, 'feed', '--limit', '2')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'facebook feed · sort=top · 2 shown · stopped=limit_reached · requests=1'
    assert lines[1].startswith('[p1] Author A · 2026-09-12T03:00+00:00 · status · reactions=? comments=? shares=?')
    assert lines[2] == '     text[6 of 6 chars shown]: "post A"'
    assert lines[3] == '     url: "https://www.facebook.com/author.a/posts/A"   author: "https://www.facebook.com/author.a"'
    more = more_of(out)
    assert re.fullmatch(r'more: uv run ".*cli\.py" facebook feed --sort top --limit 2 --after \d+', more)
    first = queries(browser)[0]['args']
    assert first['name'] == 'CometNewsFeedPaginationQuery' and first['allowed'] == sorted(first['allowed'])
    assert first['variables']['orderby'] == ['TOP_STORIES'] and first['variables']['cursor'] is None

    # the continuation shows the unshown tail first, then requests the next page from the saved cursor
    look(browser).respond('facebook.query', page([story('D'), story('E')], has_next=False))
    code, out, _ = rerun(browser, more)
    assert code == 0, out
    assert out.splitlines()[0] == 'facebook feed · sort=top · 2 shown · stopped=limit_reached · requests=1'
    assert 'Author C' in out and 'Author D' in out and 'Author E' not in out
    assert queries(browser)[1]['args']['variables']['cursor'] == 'CUR1'


def test_without_a_limit_the_feed_reads_one_page_and_says_how_to_go_on(browser):
    """Intended change (S2): the old default read until the source ended or the budget was spent (104 s, 25 requests for
    one feed read); now one page, and more: continues."""
    known_tab(browser)
    browser.respond('facebook.query', page([story('A'), story('B'), story('C')], cursor='CUR1'))
    code, out, _ = run(browser, 'feed')
    assert code == 0 and len(queries(browser)) == 1
    assert out.splitlines()[0] == 'facebook feed · sort=top · 3 shown · stopped=limit_reached · requests=1'
    assert more_of(out).endswith(re.search(r'facebook feed .*', more_of(out)).group(0))
    assert re.search(r'--after \d+$', more_of(out))


def test_a_handle_of_another_query_is_refused(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([story('A'), story('B')]))
    code, out, _ = run(browser, 'feed', '--limit', '1')
    number = re.search(r'--after (\d+)', out).group(1)
    look(browser)
    code, out, _ = run(browser, 'feed', '--sort', 'recent', '--after', number)
    assert code == 2 and json.loads(out)['error'] == 'argument'


def test_the_window_is_part_of_the_continuation(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([story('A'), story('B'), story('C')]))
    code, out, _ = run(browser, 'feed', '--limit', '1', '--since', '2026-09-01')
    assert re.search(r'--since 2026-09-01', more_of(out))
    look(browser)
    code, out, _ = run(browser, 'feed', '--limit', '1', '--after', re.search(r'--after (\d+)', out).group(1))
    assert code == 2  # the same handle without the window it was read with is another query


def test_ranked_window_is_reported_as_a_sample(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([story('T1', '2026-09-12T00:00:00Z'), story('T2', '2026-09-01T00:00:00Z')]))
    code, out, _ = run(browser, 'feed', '--since', '2026-09-10', '--limit', '1')
    assert code == 0
    assert out.splitlines()[1] == 'window 2026-09-10.. UTC · sample (not in date order)'


def test_recent_window_closes_at_the_first_old_post(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([story('N1', '2026-09-12T00:00:00Z'), story('N2', '2026-09-08T00:00:00Z'),
                                            story('N3', '2026-09-07T00:00:00Z')]))
    code, out, _ = run(browser, 'feed', '--sort', 'recent', '--since', '2026-09-10', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['N1']
    assert result['stop_reason'] == 'window_reached' and result['window']['coverage'] == 'closed (as served)'
    assert 'next' not in result and len(queries(browser)) == 1


def test_a_recent_feed_that_ends_before_the_window_starts_is_partial(browser):
    """Facebook shows no older posts here: the listing ended before --since, so the window is not covered."""
    known_tab(browser)
    browser.respond('facebook.query', page([story('N1', '2026-09-12T00:00:00Z')], has_next=False))
    code, out, _ = run(browser, 'feed', '--sort', 'recent', '--since', '2026-09-10', '--json')
    result = json.loads(out)
    assert code == 8 and result['error'] == 'partial' and result['stop_reason'] == 'query_failure'
    assert [r['id'] for r in result['results']] == ['N1']


def test_sponsored_posts_are_left_out_and_counted_or_kept(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([story('AD', sponsored=True), story('A')], has_next=False))
    code, out, _ = run(browser, 'feed')
    lines = out.splitlines()
    assert code == 0 and lines[0] == 'facebook feed · sort=top · 1 shown · stopped=exhausted · requests=1'
    assert 'coverage: 1 sponsored posts (ads) left out' in lines
    look(browser).respond('facebook.query', page([story('AD', sponsored=True), story('A')], has_next=False))
    code, out, _ = run(browser, 'feed', '--include-sponsored')
    assert out.splitlines()[0] == ('facebook feed · sort=top · include_sponsored=True · 2 shown · stopped=exhausted · '
                                   'requests=1')
    assert 'sponsored · ' in out and 'left out' not in out


def test_explicit_empty_feed_is_exit_7(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([], has_next=False))
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 7 and result['error'] == 'empty' and result['stop_reason'] == 'exhausted'


def test_the_ranked_feed_never_ends_so_out_needs_a_limit(browser, tmp_path):
    code, out, _ = run(browser, 'feed', '--out', str(tmp_path / 'f.ndjson'))
    result = json.loads(out)
    assert code == 2 and '--limit' in result['fix'] and browser.calls() == []
    known_tab(browser)
    browser.respond('facebook.query', page([story('A')], has_next=False))
    code, out, _ = run(browser, 'feed', '--sort', 'recent', '--out', str(tmp_path / 'g.ndjson'))
    assert code == 0  # the newest-first feed is read to its end


def test_a_page_of_unreadable_items_is_a_changed_answer_not_an_empty_feed(browser):
    known_tab(browser)
    body = json.dumps({'data': {'viewer': {'news_feed': {'edges': [{'node': {'something': 'else'}}],
                                                         'page_info': {'has_next_page': True, 'end_cursor': 'C'}}}}})
    browser.respond('facebook.query', query_result(body))
    code, out, _ = run(browser, 'feed')
    assert code == 6 and json.loads(out)['error'] == 'failed'


def test_the_time_limit_after_records_is_a_stop_that_more_resumes(browser):
    """No request budget stops a long read any more: the time limit does, and the saved cursor carries on (S2)."""
    known_tab(browser)
    for number in range(12):
        browser.respond('facebook.query', page([story(f'P{number}')], cursor=f'C{number}'))
    code, out, _ = run(browser, 'feed', '--limit', '100', '--json', env={'SNS_DEADLINE_SECONDS': '7'})
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'time_limit' and 2 <= len(result['results']) < 12
    assert result['next'] and len(queries(browser)) == len(result['results'])
    look(browser)
    code, out, _ = rerun(browser, 'more: ' + result['next'], env={'SNS_DEADLINE_SECONDS': '8'})
    assert code == 0 and json.loads(out)['results'][0]['id'] == f'P{len(result["results"])}'
