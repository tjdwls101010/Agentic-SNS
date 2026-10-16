"""--out collections through the real cli.py and a fake Aside: page commits, resume, complete, refusals."""
import json

from conftest import known_tab, query_result, run_cli, state
from test_cli_feed import feed_body, pk, post


def page(ids, has_next=True, cursor='C1'):
    return query_result(feed_body([[post(i, '2026-10-08T03:00:00Z')] for i in ids], has_next, cursor))


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_collect_resume_and_complete(browser, data_dir, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser, data_dir).respond('query', page(['A', 'B'], cursor='C1'))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out), '--max-requests', '1')
    assert code == 0, text
    assert text.startswith('feed · 2 saved to "') and 'stopped=budget' in text and 'resume: ' in text
    assert [r.get('id') for r in lines(out)] == [None, pk('A'), pk('B'), None]
    assert text.strip().endswith(f'feed --feed foryou --out={out} --max-requests 1')

    browser.respond('state', state()).respond('query', page(['B', 'C'], has_next=False))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out))
    assert code == 0 and '3 saved' in text and 'stopped=exhausted' in text
    assert [r['id'] for r in lines(out) if 'id' in r] == [pk('A'), pk('B'), pk('C')]
    assert [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['variables']['after'] == 'C1'

    queries = browser.ops().count('query')
    code, text, err = run_cli(browser, 'feed', '--out', str(out), '--json')
    summary = json.loads(text)
    assert code == 0 and summary['already_complete'] is True and summary['count'] == 3 and 'results' not in summary
    assert browser.ops().count('query') == queries and 'state' not in browser.ops()[-1:]  # decided from the file


def test_a_file_of_another_query_is_refused_unchanged(browser, data_dir, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser, data_dir).respond('query', page(['A'], has_next=False))
    run_cli(browser, 'feed', '--out', str(out))
    before = out.read_bytes()
    code, text, _ = run_cli(browser, 'feed', '--feed', 'following', '--out', str(out))
    assert code == 2 and json.loads(text)['error'] == 'argument'
    assert out.read_bytes() == before


def test_a_file_from_the_previous_threads_skill_is_refused_unchanged(browser, data_dir, tmp_path):
    out = tmp_path / 'old.ndjson'
    out.write_text(json.dumps({'command': 'home', 'account': 'u0', 'feed': 'foryou', 'kind': 'header',
                               'started_at': 'x', 'limit_unit': 'records'}) + '\n' + json.dumps({'id': '1'}) + '\n')
    before = out.read_bytes()
    known_tab(browser, data_dir)
    code, text, _ = run_cli(browser, 'feed', '--out', str(out))
    assert code == 2 and out.read_bytes() == before


def test_limit_counts_what_is_saved(browser, data_dir, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser, data_dir).respond('query', page(['A', 'B', 'C'], cursor='C1'))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and '3 saved' in text  # a page is committed whole
    browser.respond('state', state())
    queries = browser.ops().count('query')
    code, text, _ = run_cli(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and 'stopped=limit_reached' in text and browser.ops().count('query') == queries


def test_out_and_after_cannot_be_combined(browser, data_dir, tmp_path):
    code, text, _ = run_cli(browser, 'feed', '--out', str(tmp_path / 'x'), '--after', '3')
    assert code == 2 and browser.calls() == []


def test_a_profile_collection_resumes_without_finding_the_profile_again(browser, data_dir, tmp_path):
    out = tmp_path / 'profile.ndjson'
    user = {'pk': '1000000001', 'username': 'example.author'}
    known_tab(browser, data_dir).respond('query', query_result({'data': {'xdt_text_app_user_by_username': user}}))
    item = {'pk': '3000000000000000701', 'code': 'Cp701', 'user': user, 'taken_at': 1791428400}
    body = {'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': item}]}}],
                                   'page_info': {'has_next_page': True, 'end_cursor': 'P2'}}}}
    browser.respond('query', query_result(body))
    code, text, _ = run_cli(browser, 'profile', '@example.author', '--out', str(out), '--max-requests', '2')
    assert code == 0 and '1 saved' in text, text
    item2 = {**item, 'pk': '3000000000000000702', 'code': 'Cp702'}
    body2 = {'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': item2}]}}],
                                    'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    browser.respond('state', state()).respond('query', query_result(body2))
    code, text, _ = run_cli(browser, 'profile', '@example.author', '--out', str(out))
    assert code == 0 and '2 saved' in text, text
    names = [c['args']['name'] for c in browser.calls() if c['op'] == 'query']
    assert names.count('BarcelonaProfilePageFallbackQuery') == 1  # the id came from the file
