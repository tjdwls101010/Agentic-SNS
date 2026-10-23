"""--out collections through the real cli.py and a fake Aside: page commits, resume, complete, refusals."""
import json

from tests.sns.threads.scenes import feed_body, known_tab, pk, post, query_result, run, state


def page(ids, has_next=True, cursor='C1'):
    return query_result(feed_body([[post(i, '2026-10-08T03:00:00Z')] for i in ids], has_next, cursor))


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_collect_resume_and_complete(browser, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser).respond('threads.query', page(['A', 'B'], cursor='C1'))
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0, text
    assert text.startswith('threads feed · 2 saved to "') and 'stopped=limit_reached' in text and 'resume: ' in text
    assert [r.get('kind') for r in lines(out)] == ['header', 'post', 'post', 'page', 'page']  # the last: interrupted
    assert [r['id'] for r in lines(out) if r.get('kind') == 'post'] == [pk('A'), pk('B')]
    assert text.strip().endswith(f'threads feed --feed foryou --limit 2 --out={out}'), text

    browser.respond('threads.state', state()).respond('threads.query', page(['B', 'C'], has_next=False))
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '10')
    assert code == 0 and '3 saved' in text and 'stopped=exhausted' in text
    assert [r['id'] for r in lines(out) if r.get('kind') == 'post'] == [pk('A'), pk('B'), pk('C')]
    assert [c for c in browser.calls() if c['op'] == 'threads.query'][-1]['args']['variables']['after'] == 'C1'

    queries = browser.ops().count('threads.query')
    code, text, err = run(browser, 'feed', '--out', str(out), '--limit', '10', '--json')
    summary = json.loads(text)
    assert code == 0 and summary['already_complete'] is True and summary['count'] == 3 and 'results' not in summary
    assert browser.ops().count('threads.query') == queries and 'state' not in browser.ops()[-1:]  # decided from the file


def test_a_file_of_another_query_is_refused_unchanged(browser, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser).respond('threads.query', page(['A'], has_next=False))
    run(browser, 'feed', '--out', str(out), '--limit', '10')
    before = out.read_bytes()
    code, text, _ = run(browser, 'feed', '--feed', 'following', '--out', str(out), '--limit', '10')
    assert code == 2 and json.loads(text)['error'] == 'argument'
    assert out.read_bytes() == before


def test_a_file_from_the_previous_threads_skill_is_refused_unchanged(browser, tmp_path):
    out = tmp_path / 'old.ndjson'
    out.write_text(json.dumps({'command': 'home', 'account': 'u0', 'feed': 'foryou', 'kind': 'header',
                               'started_at': 'x', 'limit_unit': 'records'}) + '\n' + json.dumps({'id': '1'}) + '\n')
    before = out.read_bytes()
    known_tab(browser)
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '10')
    assert code == 2 and out.read_bytes() == before


def test_limit_counts_what_is_saved(browser, tmp_path):
    out = tmp_path / 'feed.ndjson'
    known_tab(browser).respond('threads.query', page(['A', 'B', 'C'], cursor='C1'))
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and '3 saved' in text  # a page is committed whole
    browser.respond('threads.state', state())
    queries = browser.ops().count('threads.query')
    code, text, _ = run(browser, 'feed', '--out', str(out), '--limit', '2')
    assert code == 0 and 'stopped=limit_reached' in text and browser.ops().count('threads.query') == queries


def test_out_and_after_cannot_be_combined(browser, tmp_path):
    code, text, _ = run(browser, 'feed', '--out', str(tmp_path / 'x'), '--after', '3')
    assert code == 2 and browser.calls() == []


def test_a_profile_collection_resumes_without_finding_the_profile_again(browser, tmp_path):
    out = tmp_path / 'profile.ndjson'
    user = {'pk': '1000000001', 'username': 'example.author'}
    known_tab(browser).respond('threads.query', query_result({'data': {'xdt_text_app_user_by_username': user}}))
    item = {'pk': '3000000000000000701', 'code': 'Cp701', 'user': user, 'taken_at': 1791428400}
    body = {'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': item}]}}],
                                   'page_info': {'has_next_page': True, 'end_cursor': 'P2'}}}}
    browser.respond('threads.query', query_result(body))
    code, text, _ = run(browser, 'profile', '@example.author', '--out', str(out), '--limit', '1')
    assert code == 0 and '1 saved' in text, text
    item2 = {**item, 'pk': '3000000000000000702', 'code': 'Cp702'}
    body2 = {'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': item2}]}}],
                                    'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    browser.respond('threads.state', state()).respond('threads.query', query_result(body2))
    code, text, _ = run(browser, 'profile', '@example.author', '--out', str(out))
    assert code == 0 and '2 saved' in text, text
    names = [c['args']['name'] for c in browser.calls() if c['op'] == 'threads.query']
    assert names.count('BarcelonaProfilePageFallbackQuery') == 1  # the id came from the file
