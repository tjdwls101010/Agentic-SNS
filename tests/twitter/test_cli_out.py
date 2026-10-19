"""--out through the real CLI and a scripted Aside (fixtures/stores.json collection)."""
import json
import time

from conftest import command_of, known_tab, query_result, run_cli, state

RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}
A = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}


def page(ids, bottom):
    entries = [{'entryId': f'tweet-{i}', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
        'result': {'__typename': 'Tweet', 'rest_id': i, 'core': {'user_results': {'result': A}},
                   'legacy': {'full_text': f'post {i}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}}}}} for i in ids]
    if bottom:
        entries.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return query_result({'data': {'home': {'home_timeline_urt': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': entries}]}}}}, headers=RATE)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_out_commits_whole_pages_and_resumes_where_it_stopped(browser, data_dir, tmp_path):
    out = tmp_path / 'collect' / 'feed.ndjson'
    out.parent.mkdir()
    known_tab(browser, data_dir).respond('query', page(['1', '2'], 'C1')).respond('query', page(['3'], 'C2'))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out), '--max-requests', '2')
    assert code == 0, text
    assert text.startswith('feed · 3 saved to') and 'stopped=budget' in text and 'resume: ' in text
    kinds = [r.get('kind') for r in lines(out)]
    assert kinds == ['header', 'post', 'post', 'page', 'post', 'page']
    resume = command_of('resume: ' + text.split('resume: ')[1].split(' · ')[0])
    browser.respond('state', state()).respond('query', page(['3', '4'], None))
    code, text, _ = run_cli(browser, *resume)
    assert code == 0 and '4 saved to' in text and 'stopped=exhausted' in text
    assert [r['id'] for r in lines(out) if r.get('kind') == 'post'] == ['1', '2', '3', '4']
    assert [c['args']['variables'].get('cursor') for c in browser.calls() if c['op'] == 'query'][-1] == 'C2'


def test_a_complete_file_reads_nothing(browser, data_dir, tmp_path):
    out = tmp_path / 'done.ndjson'
    known_tab(browser, data_dir).respond('query', page(['1'], None))
    code, text, _ = run_cli(browser, 'feed', '--out', str(out))
    assert code == 0 and 'stopped=exhausted' in text
    calls = len(browser.calls())
    code, text, _ = run_cli(browser, 'feed', '--out', str(out))
    assert code == 0 and 'already complete' in text and len(browser.calls()) == calls


def test_a_file_of_another_query_is_refused_before_any_request(browser, data_dir, tmp_path):
    out = tmp_path / 'other.ndjson'
    known_tab(browser, data_dir).respond('query', page(['1'], None))
    run_cli(browser, 'feed', '--out', str(out))
    before = out.read_bytes()
    code, text, _ = run_cli(browser, 'feed', '--feed', 'following', '--out', str(out))
    assert code == 2 and out.read_bytes() == before


def test_a_file_inside_the_skills_data_is_refused(browser, data_dir):
    code, text, _ = run_cli(browser, 'feed', '--out', str(data_dir / 'collect.ndjson'))
    assert code == 2 and 'data' in json.loads(text)['message'] and browser.calls() == []


def test_out_and_after_together_are_refused(browser, data_dir, tmp_path):
    code, text, _ = run_cli(browser, 'feed', '--out', str(tmp_path / 'x.ndjson'), '--after', '3')
    assert code == 2 and browser.calls() == []


def test_a_previous_twitter_skill_file_is_refused_byte_identical(browser, data_dir, tmp_path):
    out = tmp_path / 'old.ndjson'
    old = json.dumps({'kind': 'header', 'format': 2, 'command': 'home', 'viewer_id': '1'}) + '\n'
    out.write_text(old)
    code, text, _ = run_cli(browser, 'feed', '--out', str(out))
    assert code == 2 and out.read_text() == old and browser.calls() == []


def test_records_without_an_id_are_not_saved_twice(browser, data_dir, tmp_path):
    out = tmp_path / 'f.ndjson'
    nameless = {'__typename': 'User', 'core': {'screen_name': 'no_id_one'}}

    def page(bottom):
        items = [{'entryId': 'user-x', 'content': {'itemContent': {'itemType': 'TimelineUser', 'user_results': {'result': nameless}}}}]
        if bottom:
            items.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
        return query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': [
            {'type': 'TimelineAddEntries', 'entries': items}]}}}}}}, headers=RATE)
    by_name = query_result({'data': {'user': {'result': {**A}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', by_name).respond('query', page('C1')).respond('query', page(None))
    code, text, _ = run_cli(browser, 'graph', 'author_a', 'followers', '--out', str(out))
    assert code == 0, text
    assert [r.get('username') for r in lines(out) if r.get('kind') == 'account'] == ['no_id_one']
