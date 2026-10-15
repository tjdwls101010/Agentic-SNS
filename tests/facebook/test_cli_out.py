"""--out collections through the real cli.py and a fake Aside: page commits, resume, complete, refusals."""
import json

from conftest import STATE_OK, graphql_body, known_tab, query_result, run_cli, story

FEED = ['viewer', 'news_feed']


def page(ids, has_next=True, cursor='C1'):
    return query_result(graphql_body(FEED, [story(i) for i in ids], has_next, cursor))


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_collect_resume_and_complete(browser, data_dir, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser, data_dir)
    browser.respond('query', page(['A', 'B'], cursor='C1'))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out), '--max-requests', '1')
    assert code == 0, text
    assert text.startswith('feed · 2 saved to "') and 'stopped=budget' in text and 'resume: ' in text
    assert [r.get('id') for r in lines(out)] == [None, 'A', 'B', None]
    assert text.strip().endswith(f'feed --sort top --out={out} --max-requests 1')

    browser.respond('state', STATE_OK)
    browser.respond('query', page(['B', 'C'], has_next=False))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out))
    assert code == 0 and '3 saved' in text and 'stopped=exhausted' in text
    assert [r['id'] for r in lines(out) if 'id' in r] == ['A', 'B', 'C']
    assert [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['variables']['cursor'] == 'C1'

    browser.respond('state', STATE_OK)
    queries = len([c for c in browser.calls() if c['op'] == 'query'])
    code, text, err = run_cli(browser, 'feed', '--out', str(out), '--json')
    assert code == 0, (text, err)
    summary = json.loads(text)
    assert code == 0 and summary['already_complete'] is True and summary['count'] == 3 and 'results' not in summary
    assert len([c for c in browser.calls() if c['op'] == 'query']) == queries


def test_a_file_of_another_query_is_refused_unchanged(browser, data_dir, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser, data_dir)
    browser.respond('query', page(['A'], has_next=False))
    run_cli(browser, 'feed', '--out', str(out))
    before = out.read_bytes()
    browser.respond('state', STATE_OK)
    code, text, _ = run_cli(browser, 'feed', '--sort', 'recent', '--out', str(out))
    assert code == 2 and json.loads(text)['error'] == 'argument'
    assert out.read_bytes() == before


def test_a_previous_versions_file_is_refused_unchanged(browser, data_dir, tmp_path):
    out = tmp_path / 'old.ndjson'
    out.write_text(json.dumps({'kind': 'header', 'format': 2, 'command': 'feed', 'target': None, 'sort': 'top',
                               'window': {'since': None, 'until': None}, 'include_sponsored': False,
                               'account_id': '1000123', 'started_at': 'x', 'limit_unit': 'page'}) + '\n'
                   + json.dumps({'id': 'A'}) + '\n')
    before = out.read_bytes()
    known_tab(browser, data_dir)
    code, text, _ = run_cli(browser, 'feed', '--out', str(out))
    assert code == 2 and 'earlier version' in json.loads(text)['message']
    assert out.read_bytes() == before


def test_limit_counts_what_is_saved(browser, data_dir, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser, data_dir)
    browser.respond('query', page(['A', 'B', 'C'], cursor='C1'))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and '3 saved' in text  # a page is committed whole
    browser.respond('state', STATE_OK)
    queries = len([c for c in browser.calls() if c['op'] == 'query'])
    code, text, _ = run_cli(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and 'stopped=limit_reached' in text
    assert len([c for c in browser.calls() if c['op'] == 'query']) == queries


def test_out_and_after_cannot_be_combined(browser, data_dir, tmp_path):
    code, text, _ = run_cli(browser, 'feed', '--out', str(tmp_path / 'x'), '--after', '3')
    assert code == 2 and browser.calls() == []


def test_comments_collect_parents_and_resume_without_finding_the_post_again(browser, data_dir, tmp_path):
    from test_cli_thread import URL, comment, comments_body, script_post
    out = tmp_path / 'comments.ndjson'
    script_post(browser, data_dir, [comment('C1', replies=0), comment('C2', replies=0)])
    code, text, _ = run_cli(browser, 'comments', URL, '--out', str(out), '--max-requests', '3')
    assert code == 0 and '2 saved' in text and 'stopped=budget' in text
    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(comments_body([comment('C3', replies=0)], has_next=False)),
                    name='CommentsListComponentsPaginationQuery')
    code, text, _ = run_cli(browser, 'comments', URL, '--out', str(out))
    assert code == 0 and '3 saved' in text, text
    assert not [c for c in browser.calls()[-3:] if c['op'] == 'page']
