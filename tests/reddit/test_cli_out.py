"""--out through the real cli.py: a collection written a page at a time, resumed by rerunning the same command (a
thread from the generation its file committed, even after the snapshot is gone), refused when it belongs elsewhere."""
import json
import shutil

from conftest import VIEWER, run_cli
from test_cli_thread import PERMALINK, more, pair, t1, things


def listing(children, after=None):
    return {'kind': 'Listing', 'data': {'after': after, 'modhash': 'm', 'children': children}}


def post(identity):
    return {'kind': 't3', 'data': {'id': identity, 'name': f't3_{identity}', 'title': identity, 'is_self': True,
                                   'subreddit': 'example', 'author': 'a', 'permalink': f'/r/example/comments/{identity}/',
                                   'created_utc': 1760000000}}


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_listing_collection_resumes_and_then_reads_nothing(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([post('a'), post('b')], after='t3_b'), query={'limit': '100'})
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out), '--max-requests', '2')
    assert code == 0 and '2 saved to' in text and 'resume:' in text and 'stopped=budget' in text
    reddit.me().json('/r/example/new.json', listing([post('c')]), query={'after': 't3_b'})
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 0 and '3 saved to' in text and 'stopped=exhausted' in text
    assert [r.get('id') for r in lines(out) if r.get('kind') == 'post'] == ['t3_a', 't3_b', 't3_c']
    before = len(reddit.fetches())
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 0 and 'already complete' in text and len(reddit.fetches()) == before


def test_a_file_for_another_query_or_account_is_refused(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([post('a')], after='t3_a'))
    run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out), '--limit', '1')
    content = out.read_bytes()
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'hot', '--out', str(out))
    assert code == 2 and out.read_bytes() == content
    reddit.me('someone_else')
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 4 and json.loads(text)['reason'] == 'account_changed' and out.read_bytes() == content


def test_out_and_after_do_not_mix(reddit, tmp_path):
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--out', str(tmp_path / 'x'), '--after', '3')
    assert code == 2


TREE = [t1('c1', 't3_aaa1', [t1('c2', 't1_c1')]), more('t3_aaa1', ['c3', 'c4'])]


def test_a_thread_collection_is_the_post_once_then_every_comment_flat(reddit, tmp_path):
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    reddit.json('/api/morechildren.json', things(t1('c3', 't3_aaa1'), t1('c4', 't3_aaa1')))
    code, text, _ = run_cli(reddit, 'comments', PERMALINK, '--out', str(out))
    assert code == 0 and '5 saved to' in text and 'stopped=exhausted' in text
    saved = [r for r in lines(out) if r.get('kind') in ('post', 'comment')]
    assert [r['id'] for r in saved] == ['t3_aaa1', 't1_c1', 't1_c2', 't1_c3', 't1_c4']
    assert all('replies' not in r for r in saved) and saved[2]['depth'] == 1 and saved[2]['parent_id'] == 't1_c1'


def test_a_thread_collection_resumes_its_own_reading_after_the_snapshot_is_gone(reddit, tmp_path, data_dir):
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    code, text, _ = run_cli(reddit, 'comments', PERMALINK, '--out', str(out), '--max-requests', '2')
    assert code == 0 and 'resume:' in text and '3 saved to' in text
    shutil.rmtree(data_dir / 'snapshots')
    reddit.me().json('/comments/aaa1.json', pair([t1('n1', 't3_aaa1')]))
    run_cli(reddit, 'post', PERMALINK)  # a newer reading of the same post
    reddit.me().json('/api/morechildren.json', things(t1('c3', 't3_aaa1'), t1('c4', 't3_aaa1')),
                     query={'children': 'c3,c4'})
    code, text, _ = run_cli(reddit, 'comments', PERMALINK, '--out', str(out))
    assert code == 0 and 'stopped=exhausted' in text
    saved = [r['id'] for r in lines(out) if r.get('kind') in ('post', 'comment')]
    assert saved == ['t3_aaa1', 't1_c1', 't1_c2', 't1_c3', 't1_c4'] and 't1_n1' not in saved


def test_a_comment_link_after_a_resumed_collection_reads_the_comment_again(reddit, tmp_path, data_dir):
    # Codex P7: the resumed tree keeps no text, and a link answered from it crashed
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    run_cli(reddit, 'comments', PERMALINK, '--out', str(out), '--max-requests', '2')
    shutil.rmtree(data_dir / 'snapshots')
    reddit.me().json('/api/morechildren.json', things(t1('c3', 't3_aaa1'), t1('c4', 't3_aaa1')))
    run_cli(reddit, 'comments', PERMALINK, '--out', str(out))
    reddit.me().json('/comments/aaa1/_/c1.json', pair([t1('c1', 't3_aaa1', [t1('c2', 't1_c1')])]), query={'context': '0'})
    code, text, _ = run_cli(reddit, 'comments', PERMALINK + 'c1/')
    assert code == 0 and 'comment c1' in text and 'comment c2' in text


def test_a_new_thread_collection_holds_comments_already_shown_by_an_earlier_read(reddit, tmp_path):
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1'), t1('c2', 't3_aaa1')]))
    run_cli(reddit, 'post', PERMALINK)  # shows c1 and c2
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1'), t1('c2', 't3_aaa1')]))
    code, text, _ = run_cli(reddit, 'comments', PERMALINK, '--out', str(out))
    assert code == 0 and [r['id'] for r in lines(out) if r.get('kind') == 'comment'] == ['t1_c1', 't1_c2']


def test_a_hidden_history_is_judged_for_a_collection_too_and_kept(reddit, tmp_path):
    # Codex P7: profile --out skipped the karma check and ended as an empty result (7)
    from test_cli_people import about_user
    out = tmp_path / 'profile.ndjson'
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(28, 55636))
    code, text, _ = run_cli(reddit, 'profile', 'u/example_user', '--out', str(out), '--json')
    envelope = json.loads(text)
    assert code == 9 and envelope['reason'] == 'history_not_visible' and 'next' not in envelope
    before = len(reddit.fetches())
    code, text, _ = run_cli(reddit, 'profile', 'u/example_user', '--out', str(out), '--json')
    assert code == 9 and json.loads(text)['reason'] == 'history_not_visible' and len(reddit.fetches()) == before


def test_a_window_the_listing_did_not_reach_stays_open_when_the_command_is_rerun(reddit, tmp_path):
    # Codex P7: the rerun said already complete (0) and dropped the window's warning; the first run offered a resume
    from test_cli_lists import epoch
    out = tmp_path / 'sub.ndjson'
    old = {**post('a')['data'], 'created_utc': epoch('2025-10-09T00:00:00')}
    reddit.me().json('/r/example/new.json', listing([{'kind': 't3', 'data': old}]))
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--since', '2025-01-01', '--out', str(out),
                            '--json')
    envelope = json.loads(text)
    assert code == 8 and envelope['window']['coverage'].startswith('open') and 'next' not in envelope
    before = len(reddit.fetches())
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--since', '2025-01-01', '--out', str(out),
                            '--json')
    envelope = json.loads(text)
    assert code == 8 and 'ended before' in envelope['message'] and envelope['window']['coverage'].startswith('open')
    assert len(reddit.fetches()) == before


def test_an_empty_collection_stays_empty_when_rerun(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([]))
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 7
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 7


def test_a_karma_check_the_budget_cut_off_is_made_when_the_command_is_rerun(reddit, tmp_path):
    # Codex P7 round 2: the file was already complete, so the rerun never checked the karma
    from test_cli_people import about_user
    out = tmp_path / 'profile.ndjson'
    reddit.me().json('/user/example_user/overview.json', listing([]))
    code, text, _ = run_cli(reddit, 'profile', 'u/example_user', '--out', str(out), '--max-requests', '2', '--json')
    assert code == 8 and json.loads(text)['reason'] == 'karma_unchecked'
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(28, 55636))
    code, text, _ = run_cli(reddit, 'profile', 'u/example_user', '--out', str(out), '--json')
    assert code == 9 and json.loads(text)['reason'] == 'history_not_visible'


def test_a_verdict_cut_off_while_written_is_read_again(reddit, tmp_path):
    # Codex P7 round 2: a torn verdict line left the earlier complete marker, and the rerun reported success
    from test_cli_lists import epoch
    out = tmp_path / 'sub.ndjson'
    old = {**post('a')['data'], 'created_utc': epoch('2025-10-09T00:00:00')}
    args = ['sub', 'r/example', '--sort', 'new', '--since', '2025-01-01', '--out', str(out), '--json']
    reddit.me().json('/r/example/new.json', listing([{'kind': 't3', 'data': old}]))
    code, _, _ = run_cli(reddit, *args)
    assert code == 8
    data = out.read_bytes()
    out.write_bytes(data[:-20])  # the last line, the verdict, torn
    reddit.me().json('/r/example/new.json', listing([{'kind': 't3', 'data': old}]))
    code, text, _ = run_cli(reddit, *args)
    assert code == 8 and json.loads(text)['window']['coverage'].startswith('open')


def test_a_damaged_verdict_is_an_integrity_failure(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([]))
    run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    rows = out.read_text().splitlines()
    last = json.loads(rows[-1])
    assert last.get('verdict'), 'the empty result is kept as a verdict'
    rows[-1] = json.dumps({**last, 'verdict': {'code': 7}})
    out.write_text('\n'.join(rows) + '\n')
    code, text, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 2 and 'integrity' in text
