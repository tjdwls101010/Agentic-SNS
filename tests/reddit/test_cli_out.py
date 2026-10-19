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


def test_a_new_thread_collection_holds_comments_already_shown_by_an_earlier_read(reddit, tmp_path):
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1'), t1('c2', 't3_aaa1')]))
    run_cli(reddit, 'post', PERMALINK)  # shows c1 and c2
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1'), t1('c2', 't3_aaa1')]))
    code, text, _ = run_cli(reddit, 'comments', PERMALINK, '--out', str(out))
    assert code == 0 and [r['id'] for r in lines(out) if r.get('kind') == 'comment'] == ['t1_c1', 't1_c2']
