"""--out through the real cli: a collection written a page at a time, resumed by rerunning the same command (a thread from
the generation its file committed, even after the snapshot is gone), refused when it belongs elsewhere, and a file that
answers a rerun as its first run did."""
import json
import random
import shutil

import pytest

from tests.sns.reddit.shapes import PERMALINK, about_user, epoch, listing, more, pair, post, t1, things


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_listing_collection_resumes_and_then_reads_nothing(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([post('a'), post('b')], after='t3_b'), query={'limit': 100})
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out), '--limit', '2')
    assert code == 0 and '2 saved to' in text and 'resume:' in text and 'stopped=limit_reached' in text
    reddit.me().json('/r/example/new.json', listing([post('c')]), query={'after': 't3_b'})
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 0 and '3 saved to' in text and 'stopped=exhausted' in text
    assert [r.get('id') for r in lines(out) if r.get('kind') == 'post'] == ['t3_a', 't3_b', 't3_c']
    before = len(reddit.fetches())
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 0 and 'already complete' in text and len(reddit.fetches()) == before


def test_a_file_for_another_query_or_account_is_refused(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([post('a')], after='t3_a'))
    reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out), '--limit', '1')
    content = out.read_bytes()
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'hot', '--out', str(out))
    assert code == 2 and out.read_bytes() == content
    reddit.me('someone_else')
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 4 and json.loads(text)['error'] == 'login' and out.read_bytes() == content


def test_out_and_after_do_not_mix(reddit, tmp_path):
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--out', str(tmp_path / 'x'), '--after', '3')
    assert code == 2


TREE = [t1('c1', 't3_aaa1', [t1('c2', 't1_c1')]), more('t3_aaa1', ['c3', 'c4'])]


def test_a_thread_collection_is_the_post_once_then_every_comment_flat(reddit, tmp_path):
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    reddit.json('/api/morechildren.json', things(t1('c3', 't3_aaa1'), t1('c4', 't3_aaa1')))
    code, text, _ = reddit.run('reddit', 'comments', PERMALINK, '--out', str(out))
    assert code == 0 and '5 saved to' in text and 'stopped=exhausted' in text
    saved = [r for r in lines(out) if r.get('kind') in ('post', 'comment')]
    assert [r['id'] for r in saved] == ['t3_aaa1', 't1_c1', 't1_c2', 't1_c3', 't1_c4']
    assert all('replies' not in r for r in saved) and saved[2]['depth'] == 1 and saved[2]['parent_id'] == 't1_c1'
    assert lines(out)[-1]['end'] == 'final', 'a complete tree is final: a rerun repeats it without a request'


def test_a_thread_collection_resumes_its_own_reading_after_the_snapshot_is_gone(reddit, tmp_path, data_dir):
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    code, text, _ = reddit.run('reddit', 'comments', PERMALINK, '--out', str(out), '--limit', '2')
    assert code == 0 and 'resume:' in text and '3 saved to' in text
    shutil.rmtree(data_dir / 'reddit/u0/snapshots')
    reddit.me().json('/comments/aaa1.json', pair([t1('n1', 't3_aaa1')]))
    reddit.run('reddit', 'post', PERMALINK)  # a newer reading of the same post
    reddit.me().json('/api/morechildren.json', things(t1('c3', 't3_aaa1'), t1('c4', 't3_aaa1')),
                     query={'children': 'c3,c4'})
    code, text, _ = reddit.run('reddit', 'comments', PERMALINK, '--out', str(out))
    assert code == 0 and 'stopped=exhausted' in text
    saved = [r['id'] for r in lines(out) if r.get('kind') in ('post', 'comment')]
    assert saved == ['t3_aaa1', 't1_c1', 't1_c2', 't1_c3', 't1_c4'] and 't1_n1' not in saved


def test_a_comment_link_after_a_resumed_collection_reads_the_comment_again(reddit, tmp_path, data_dir):
    # Codex P7: the resumed tree keeps no text, and a link answered from it crashed
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair(TREE))
    reddit.run('reddit', 'comments', PERMALINK, '--out', str(out), '--limit', '2')
    shutil.rmtree(data_dir / 'reddit/u0/snapshots')
    reddit.me().json('/api/morechildren.json', things(t1('c3', 't3_aaa1'), t1('c4', 't3_aaa1')))
    reddit.run('reddit', 'comments', PERMALINK, '--out', str(out))
    reddit.me().json('/comments/aaa1/_/c1.json', pair([t1('c1', 't3_aaa1', [t1('c2', 't1_c1')])]), query={'context': 0})
    code, text, _ = reddit.run('reddit', 'comments', PERMALINK + 'c1/')
    assert code == 0 and 'comment c1' in text and 'comment c2' in text


def test_a_new_thread_collection_holds_comments_already_shown_by_an_earlier_read(reddit, tmp_path):
    out = tmp_path / 'thread.ndjson'
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1'), t1('c2', 't3_aaa1')]))
    reddit.run('reddit', 'post', PERMALINK)  # shows c1 and c2
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1'), t1('c2', 't3_aaa1')]))
    code, text, _ = reddit.run('reddit', 'comments', PERMALINK, '--out', str(out))
    assert code == 0 and [r['id'] for r in lines(out) if r.get('kind') == 'comment'] == ['t1_c1', 't1_c2']


def test_a_tree_whose_last_branch_reddit_will_not_expand_ends_partial_and_is_not_final(reddit, tmp_path):
    out = tmp_path / 'thread.ndjson'
    stalled = [t1('c1', 't3_aaa1', [more('t1_c1', [])])]  # 'continue this thread' that answers with nothing new
    reddit.me().json('/comments/aaa1.json', pair(stalled))
    reddit.json('/comments/aaa1/_/c1.json', pair([t1('c1', 't3_aaa1')]), query={'context': 0})
    code, text, _ = reddit.run('reddit', 'comments', PERMALINK, '--out', str(out))
    assert code == 8 and lines(out)[-1]['end'] == 'interrupted' and 'resume:' in text


def test_a_hidden_history_is_judged_for_a_collection_too_and_kept(reddit, tmp_path):
    # Codex P7: profile --out skipped the karma check and ended as an empty result (7)
    out = tmp_path / 'profile.ndjson'
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(28, 55636))
    code, text, _ = reddit.run('reddit', 'profile', 'u/example_user', '--out', str(out), '--json')
    envelope = json.loads(text)
    assert code == 9 and 'history is hidden' in envelope['message'] and 'next' not in envelope
    before = len(reddit.fetches())
    code, text, _ = reddit.run('reddit', 'profile', 'u/example_user', '--out', str(out), '--json')
    assert code == 9 and 'history is hidden' in json.loads(text)['message'] and len(reddit.fetches()) == before


def test_a_karma_check_the_time_limit_cut_off_is_made_when_the_command_is_rerun(reddit, tmp_path, monkeypatch):
    out = tmp_path / 'profile.ndjson'
    monkeypatch.setattr(random, 'uniform', lambda low, high: high)  # pacing 2 s: the third request cannot fit 6.5 s
    monkeypatch.setenv('SNS_DEADLINE_SECONDS', '6.5')
    reddit.me().json('/user/example_user/overview.json', listing([]))
    code, text, _ = reddit.run('reddit', 'profile', 'u/example_user', '--out', str(out), '--json')
    assert code == 6 and json.loads(text)['stop_reason'] == 'time_limit', 'cut off: no verdict was kept'
    monkeypatch.delenv('SNS_DEADLINE_SECONDS')
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(28, 55636))
    code, text, _ = reddit.run('reddit', 'profile', 'u/example_user', '--out', str(out), '--json')
    assert code == 9 and 'history is hidden' in json.loads(text)['message']


def window_file(reddit, tmp_path, *extra):
    out = tmp_path / 'sub.ndjson'
    old = {**post('a')['data'], 'created_utc': epoch('2025-10-09T00:00:00')}
    reddit.me().json('/r/example/new.json', listing([{'kind': 't3', 'data': old}]))
    args = ['reddit', 'sub', 'r/example', '--sort', 'new', '--since', '2025-01-01', '--out', str(out), '--json', *extra]
    return out, args


def test_a_window_the_listing_did_not_reach_stays_open_when_the_command_is_rerun(reddit, tmp_path):
    # Codex P7: the rerun said already complete (0) and dropped the window's warning; the first run offered a resume
    out, args = window_file(reddit, tmp_path)
    code, text, _ = reddit.run(*args)
    envelope = json.loads(text)
    assert code == 8 and envelope['window']['coverage'].startswith('open') and 'next' not in envelope
    before = len(reddit.fetches())
    code, text, _ = reddit.run(*args)
    envelope = json.loads(text)
    assert code == 8 and 'ended before' in envelope['message'] and envelope['window']['coverage'].startswith('open')
    assert len(reddit.fetches()) == before


@pytest.mark.xfail(strict=True, reason='core gap: reading.read_list returns limit_reached at once when the file already '
                                       'holds --limit records, before the source end the file reached is judged again '
                                       '(old reddit kept `ending` in the page line for this; Codex P7 round 3)')
def test_a_torn_completion_is_judged_again_even_when_the_limit_was_reached(reddit, tmp_path):
    out, args = window_file(reddit, tmp_path, '--limit', '1')
    code, _, _ = reddit.run(*args)
    assert code == 8
    out.write_bytes(out.read_bytes()[:-20])  # the completion line torn
    reddit.me().json('/r/example/new.json', listing([{'kind': 't3', 'data': {
        **post('a')['data'], 'created_utc': epoch('2025-10-09T00:00:00')}}]))
    code, text, _ = reddit.run(*args)
    assert code == 8 and json.loads(text)['window']['coverage'].startswith('open')
    assert [r['id'] for r in lines(out) if r.get('kind') == 'post'] == ['t3_a'], 'nothing saved twice'


def test_an_empty_collection_stays_empty_when_rerun(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([]))
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 7
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 7


def test_a_verdict_cut_off_while_written_is_read_again(reddit, tmp_path):
    # Codex P7 round 2: a torn verdict line left the earlier complete marker, and the rerun reported success
    out, args = window_file(reddit, tmp_path)
    code, _, _ = reddit.run(*args)
    assert code == 8
    data = out.read_bytes()
    out.write_bytes(data[:-20])  # the last line, the verdict, torn
    reddit.me().json('/r/example/new.json', listing([{'kind': 't3', 'data': {
        **post('a')['data'], 'created_utc': epoch('2025-10-09T00:00:00')}}]))
    code, text, _ = reddit.run(*args)
    assert code == 8 and json.loads(text)['window']['coverage'].startswith('open')


def test_a_damaged_verdict_is_an_integrity_failure(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([]))
    reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    rows = out.read_text().splitlines()
    last = json.loads(rows[-1])
    assert last.get('verdict'), 'the empty result is kept as a verdict'
    rows[-1] = json.dumps({**last, 'verdict': {'code': 7}})
    out.write_text('\n'.join(rows) + '\n')
    code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    assert code == 2 and 'integrity' in text


def test_a_window_with_nothing_inside_stays_empty_when_rerun(reddit, tmp_path):
    # Codex P7 round 5: the empty verdict was made after the file was concluded, so the rerun said complete (0)
    out = tmp_path / 'sub.ndjson'
    old = {**post('a')['data'], 'created_utc': epoch('2025-10-09T00:00:00')}
    args = ['reddit', 'sub', 'r/example', '--sort', 'new', '--since', '2026-01-01', '--out', str(out), '--json']
    reddit.me().json('/r/example/new.json', listing([{'kind': 't3', 'data': old}], after='t3_a'))
    code, _, _ = reddit.run(*args)
    assert code == 7
    code, text, _ = reddit.run(*args)
    assert code == 7 and json.loads(text)['error'] == 'empty'


def test_a_damaged_ending_is_an_integrity_failure(reddit, tmp_path):
    out = tmp_path / 'sub.ndjson'
    reddit.me().json('/r/example/new.json', listing([post('a')]))
    reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
    rows = out.read_text().splitlines()
    assert json.loads(rows[-1]).get('end') == 'final'
    for bad in ('exhausted', 3, True, {}, []):
        out.write_text('\n'.join(rows[:-1] + [json.dumps({**json.loads(rows[-1]), 'end': bad})]) + '\n')
        code, text, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--out', str(out))
        assert code == 2 and 'integrity' in text, bad


def _dated(identity, when):
    return {'kind': 't3', 'data': {**post(identity)['data'], 'created_utc': epoch(when)}}


# Each scenario: the pages Reddit serves (in order) and the options; the property is the one the file exists for —
# rerunning the same command answers as the first run did, whatever is left of its last line.
RERUN = {
    'empty-listing': ([listing([])], []),
    'nothing-inside-listing-ended': ([listing([_dated('a', '2025-12-31T23:55:00')])], ['--since', '2026-01-01']),
    'nothing-inside-window-closed': ([listing([_dated('a', '2025-06-01T00:00:00')], after='t3_a')],
                                     ['--since', '2026-01-01']),
    'inside-listing-ended': ([listing([_dated('a', '2026-03-01T00:00:00')], after='t3_a'),
                              listing([_dated('b', '2026-02-01T00:00:00')])], ['--since', '2026-01-01']),
    'inside-window-closed': ([listing([_dated('a', '2026-03-01T00:00:00'), _dated('b', '2025-06-01T00:00:00')],
                                      after='t3_b')], ['--since', '2026-01-01']),
    'limit-with-more-left': ([listing([_dated('a', '2026-03-01T00:00:00')], after='t3_a')],
                             ['--since', '2026-01-01', '--limit', '1']),
}


def _answer(text):
    envelope = json.loads(text)
    return envelope.get('error'), envelope.get('stop_reason'), (envelope.get('window') or {}).get('coverage')


@pytest.mark.parametrize('cut', ['intact', 'completion-torn'])
@pytest.mark.parametrize('name', sorted(RERUN))
def test_a_rerun_answers_as_the_first_run_did(reddit, tmp_path, name, cut):
    pages, extra = RERUN[name]
    out = tmp_path / 'sub.ndjson'
    args = ['reddit', 'sub', 'r/example', '--sort', 'new', *extra, '--out', str(out), '--json']

    def serve():
        reddit.me().json('/r/example/new.json', pages[0], query={'limit': 100})
        for page, before in zip(pages[1:], pages):
            reddit.json('/r/example/new.json', page, query={'after': before['data']['after']})

    serve()
    code, text, _ = reddit.run(*args)
    first = (code, *_answer(text))
    if cut == 'completion-torn' and json.loads(out.read_text().splitlines()[-1]).get('end'):
        out.write_bytes(out.read_bytes()[:-10])
    for _ in range(2):  # the run that recovers, and the one after it
        serve()
        code, text, _ = reddit.run(*args)
        assert (code, *_answer(text)) == first
