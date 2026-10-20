"""--out files of X reads, through the real CLI and a scripted Aside (fixtures/stores.json, collection). The file
format, the integrity check, locking, links, 0600 and the final/interrupted endings are the core's (tests/sns/core/
test_outfile.py: test_pages_are_committed_with_a_marker_and_resume_drops_an_unfinished_tail, test_a_final_marker_is_
repeated_by_peek_and_an_interrupted_one_resumes, test_a_file_of_another_query_or_version_is_refused_before_any_byte_
changes, test_another_platform_account_is_a_changed_login, test_a_damaged_committed_page_fails_the_integrity_check,
test_links_are_refused_and_the_file_is_private_and_locked, test_a_nested_record_cannot_be_saved, test_a_path_inside_
data_or_in_a_missing_directory_is_refused_before_any_request); here is what X puts in them and how an X read ends one:
flat records with X's keys, the window and the tab in the file's context, the X account a file is bound to, the endings
of X's stops, and the refusals an X command makes before any request."""
import json
import os
import time


from sns import outfile
from tests.sns.x.scenes import ACCOUNT, known_tab, queries, query_result, rerun, run, state

RATE = {'x-rate-limit-limit': '150', 'x-rate-limit-remaining': '149', 'x-rate-limit-reset': str(int(time.time()) + 900)}
AUTHOR = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'Author A'},
          'privacy': {'protected': False}}


def tweet(ident, at='Thu Oct 15 10:00:00 +0000 2026', text=None, legacy=None, **extra):
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': AUTHOR}},
            'legacy': {'full_text': text or f'post {ident}', 'created_at': at, **(legacy or {})}, **extra}


def card():
    return query_result({'data': {'user': {'result': AUTHOR}}}, headers=RATE)


def timeline(*posts, bottom=None, pin=None):
    entries = [{'entryId': f'tweet-{t["rest_id"]}', 'content': {'itemContent': {
        'itemType': 'TimelineTweet', 'tweet_results': {'result': t}}}} for t in posts]
    if bottom:
        entries.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    instructions = [{'type': 'TimelineAddEntries', 'entries': entries}]
    if pin:
        instructions.insert(0, {'type': 'TimelinePinEntry', 'entry': {'entryId': f'tweet-{pin["rest_id"]}', 'content': {
            'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': pin}}}}})
    return query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': instructions}}}}}},
                        headers=RATE)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def records(path):
    return [r for r in lines(path) if r.get('kind') not in ('header', 'page')]


def saved(browser, path, *args, env=None):
    return run(browser, 'profile', '@author_a', '--out', str(path), *args, env=env)


def resume_line(out):
    return next(part for part in out.split(' · ') if part.startswith('resume: '))


def test_a_new_file_starts_with_the_header_of_the_query_and_holds_x_records_flat(browser, tmp_path):
    """new-file-gets-header, page-commit: header (platform x, the tab in the context), the records, then the page
    marker; the records keep X's keys (parent_id, pinned) and nest only the posts they quote or repost."""
    path = tmp_path / 'profile.ndjson'
    quoting = tweet('12', quoted_status_result={'result': tweet('99')}, legacy={'quoted_status_id_str': '99'})
    known_tab(browser).respond('x.query', card()).respond('x.query', timeline(
        tweet('11', legacy={'in_reply_to_status_id_str': '5'}), quoting, bottom='CUR1', pin=tweet('10')))
    code, out, _ = saved(browser, path, '--limit', '3')
    assert code == 0 and '3 saved to' in out, out
    header, *rest = lines(path)
    assert header['kind'] == 'header' and header['format'] == outfile.FORMAT and header['platform'] == 'x'
    assert header['context']['command'] == 'profile' and header['context']['identity'] == {'tab': 'posts'}
    assert header['context']['target'] == 'https://x.com/author_a' and header['viewer'] == ACCOUNT
    assert [r.get('kind') for r in rest] == ['post', 'post', 'post', 'page', 'page']  # the page, then why the run stopped
    assert rest[-1]['stop_reason'] == 'limit_reached' and rest[-1]['end'] == 'interrupted'
    pinned, reply, quote = rest[:3]
    assert pinned['pinned'] is True and reply['pinned'] is False and reply['parent_id'] == '5'
    assert 'is_pinned' not in pinned and 'reply_to_id' not in reply
    assert quote['quoted_post']['id'] == '99' and 'replies' not in quote  # nested by what it quotes, never by replies
    marker = rest[3]
    assert marker['ids'] == [pinned['id'], reply['id'], quote['id']] and marker['n'] == 3
    assert oct(os.stat(path).st_mode & 0o777) == '0o600'


def test_a_repost_row_is_saved_as_one_record_with_the_original_inside(browser, tmp_path):
    path = tmp_path / 'profile.ndjson'
    row = tweet('20', legacy={'retweeted_status_result': {'result': tweet('21', legacy={'retweet_count': 7})}})
    known_tab(browser).respond('x.query', card()).respond('x.query', timeline(row))
    code, out, _ = saved(browser, path)
    assert code == 0, out
    [record] = records(path)
    assert record['id'] == '20' and record['reposted_post']['id'] == '21' and record['text'] == ''


def test_a_tail_the_marker_does_not_cover_is_dropped_and_read_again_on_resume(browser, tmp_path):
    """interrupted-tail-replayed, partial-line-replayed: a run stopped by the time limit leaves a file whose tail past
    its last marker (a record, a half line) is not trusted; the resume reads that page from the saved cursor again."""
    path = tmp_path / 'profile.ndjson'
    known_tab(browser).respond('x.query', card()).respond('x.query', {'__sleep': 3, **timeline(
        tweet('11'), tweet('12'), bottom='CUR1')})
    code, out, _ = saved(browser, path, env={'SNS_DEADLINE_SECONDS': '6'})
    assert code == 0 and '2 saved to' in out and 'stopped=time_limit' in out, out
    with path.open('a') as stream:
        stream.write(json.dumps({'kind': 'post', 'id': 'ghost'}) + '\n{"kind": "post", "id": "half')
    browser.respond('x.state', state()).respond('x.query', timeline(tweet('12'), tweet('13')))
    code, out, _ = rerun(browser, resume_line(out))
    assert code == 0 and '3 saved to' in out and 'stopped=exhausted' in out, out
    assert [r['id'] for r in records(path)] == ['11', '12', '13']  # dedupe-across-pages: 12 once
    assert queries(browser)[-1]['args']['variables']['cursor'] == 'CUR1' and 'userId' in queries(browser)[-1]['args']['variables']
    assert len([q for q in queries(browser) if q['args']['name'] == 'UserByScreenName']) == 1  # the user id was saved


def test_a_file_of_another_tab_is_refused_before_any_request_and_stays_byte_identical(browser, tmp_path):
    """other-query-refused-byte-identical: the tab is part of the query."""
    path = tmp_path / 'profile.ndjson'
    known_tab(browser).respond('x.query', card()).respond('x.query', timeline(tweet('11')))
    saved(browser, path)
    before, sent = path.read_bytes(), len(queries(browser))
    code, out, _ = saved(browser, path, '--tab', 'replies')
    envelope = json.loads(out)
    assert code == 2 and envelope['error'] == 'argument' and path.read_bytes() == before
    assert len(queries(browser)) == sent


def test_a_file_read_as_another_x_account_is_a_changed_login(browser, tmp_path):
    """other-account: the file is bound to the X account it was read as; the browser now shows another (exit 4)."""
    path = tmp_path / 'profile.ndjson'
    known_tab(browser).respond('x.query', card()).respond('x.query', {'__sleep': 3, **timeline(tweet('11'), bottom='C')})
    code, out, _ = saved(browser, path, env={'SNS_DEADLINE_SECONDS': '6'})
    assert code == 0 and 'stopped=time_limit' in out, out
    before = path.read_bytes()
    browser.respond('x.state', state(user_id='1000000098'))
    code, out, _ = rerun(browser, resume_line(out))
    envelope = json.loads(out)
    assert code == 4 and envelope['error'] == 'login' and '1000000098' in envelope['message'], out
    assert path.read_bytes() == before


def test_a_file_the_previous_twitter_skill_wrote_is_refused_byte_identical(browser, tmp_path):
    """previous-skill-file-refused: its header was format 2 with a flat context and viewer_id."""
    path = tmp_path / 'old.ndjson'
    old = (json.dumps({'kind': 'header', 'format': 2, 'command': 'user', 'target': 'example_user', 'tab': 'posts',
                       'viewer_id': ACCOUNT}) + '\n' + json.dumps({'id': '1850000000000000001', 'kind': 'tweet'}) + '\n'
           + json.dumps({'kind': 'page', 'ids': ['1850000000000000001'], 'n': 1, 'state': {},
                         'stop_reason': 'exhausted'}) + '\n')
    path.write_text(old)
    known_tab(browser)
    code, out, _ = saved(browser, path)
    assert code == 2 and 'earlier version' in json.loads(out)['message'], out
    assert path.read_text() == old and queries(browser) == []


def test_a_committed_page_that_disagrees_with_its_marker_is_an_integrity_failure(browser, tmp_path):
    path = tmp_path / 'profile.ndjson'
    known_tab(browser).respond('x.query', card()).respond('x.query', {'__sleep': 3, **timeline(
        tweet('11'), tweet('12'), bottom='C')})
    code, out, _ = saved(browser, path, env={'SNS_DEADLINE_SECONDS': '6'})
    assert code == 0, out
    path.write_text(path.read_text().replace('"n":2', '"n":1'))
    before = path.read_bytes()
    browser.respond('x.state', state())
    code, out, _ = rerun(browser, resume_line(out))
    assert code == 2 and 'integrity' in json.loads(out)['message'] and path.read_bytes() == before


def test_a_file_that_reached_the_end_is_complete_and_repeats_without_a_request(browser, tmp_path):
    """complete-file: exhausted ends the file 'final'; the rerun is the core's repeat of its judgment."""
    path = tmp_path / 'profile.ndjson'
    known_tab(browser).respond('x.query', card()).respond('x.query', timeline(tweet('11')))
    code, out, _ = saved(browser, path)
    assert code == 0 and 'stopped=exhausted' in out, out
    sent = len(queries(browser))
    code, out, _ = saved(browser, path)
    assert code == 0 and 'already complete' in out and len(queries(browser)) == sent
    assert lines(path)[-1]['end'] == 'final'


def test_a_window_is_part_of_the_files_query_and_a_window_that_closed_ends_it(browser, tmp_path):
    """window-complete-file: a newest-first window closes at the first page older than --since (window_reached ends the
    file final, and the repeat names the window); another window is another query."""
    path = tmp_path / 'window.ndjson'
    known_tab(browser).respond('x.query', card())
    browser.respond('x.query', timeline(tweet('11', 'Thu Oct 15 10:00:00 +0000 2026'), tweet('10', 'Wed Oct 14 10:00:00 +0000 2026'),
                                        bottom='CUR1'))
    browser.respond('x.query', timeline(tweet('9', 'Mon Oct 05 10:00:00 +0000 2026'), bottom='CUR2'))
    code, out, _ = saved(browser, path, '--since', '2026-10-14')
    assert code == 0 and 'stopped=window_reached' in out and '2 saved to' in out, out
    assert lines(path)[0]['context']['identity'] == {'tab': 'posts', 'since': '2026-10-14'}
    assert lines(path)[-1]['end'] == 'final'
    code, out, _ = saved(browser, path, '--since', '2026-10-14')
    assert code == 0 and 'already complete' in out and 'window 2026-10-14..' in out and 'closed (as served)' in out, out
    before = path.read_bytes()
    code, out, _ = saved(browser, path, '--since', '2026-10-13')
    assert code == 2 and path.read_bytes() == before


def test_a_stop_that_passes_by_itself_leaves_the_file_to_resume(browser, tmp_path):
    """rate-limited-file-resumes: the operation's window ran out after a page; the file is not complete and the resume
    line is printed, but protection refuses the operation until X's reset (no request is made inside the window)."""
    path = tmp_path / 'profile.ndjson'
    reset = int(time.time()) + 600
    known_tab(browser).respond('x.query', card()).respond('x.query', timeline(tweet('11'), bottom='CUR1'))
    browser.respond('x.query', query_result('{"errors":[{"code":88}]}', status=429, headers={
        'x-rate-limit-limit': '50', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(reset)}))
    code, out, _ = saved(browser, path, '--limit', '5')
    assert code == 0 and 'stopped=rate_limited' in out and 'resume: ' in out and '1 saved to' in out, out
    assert lines(path)[-1]['end'] == 'interrupted'
    sent = len(queries(browser))
    browser.respond('x.state', state())
    code, out, _ = rerun(browser, resume_line(out))
    assert code == 0 and 'stopped=rate_limited' in out and len(queries(browser)) == sent, out


def test_a_lock_in_the_middle_keeps_the_pages_read_and_offers_no_resume(browser, tmp_path):
    path = tmp_path / 'profile.ndjson'
    known_tab(browser).respond('x.query', card()).respond('x.query', timeline(tweet('11'), bottom='CUR1'))
    browser.respond('x.query', query_result('{"errors":[{"code":326,"message":"locked"}]}', status=403))
    code, out, _ = saved(browser, path, '--limit', '5')
    assert code == 5 and '1 saved to' in out and 'resume:' not in out, out
    assert [r['id'] for r in records(path)] == ['11'] and lines(path)[-1]['end'] == 'interrupted'


def test_two_writers_of_one_file_do_not_wait_for_each_other(browser, tmp_path):
    import fcntl
    path = tmp_path / 'profile.ndjson'
    path.write_text('')
    known_tab(browser)
    with open(path, 'r+b') as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, out, _ = saved(browser, path)
    assert code == 2 and json.loads(out)['error'] == 'argument' and queries(browser) == []


def test_a_symbolic_link_is_refused_and_its_target_untouched(browser, tmp_path):
    target = tmp_path / 'elsewhere.txt'
    target.write_text('')
    link = tmp_path / 'profile.ndjson'
    link.symlink_to(target)
    known_tab(browser)
    code, out, _ = saved(browser, link)
    assert code == 2 and target.read_text() == '' and queries(browser) == []


def test_a_file_inside_the_skills_data_and_out_with_after_are_refused_before_any_request(browser, data_dir, tmp_path):
    """inside-skill-data-refused, out-with-after-refused."""
    known_tab(browser)
    code, out, _ = saved(browser, data_dir / 'x.ndjson')
    assert code == 2 and 'data/' in json.loads(out)['message']
    code, out, _ = run(browser, 'profile', '@author_a', '--out', str(tmp_path / 'a.ndjson'), '--after', '1000')
    assert code == 2 and '--after and --out' in json.loads(out)['message']
    assert queries(browser) == [] and not (tmp_path / 'a.ndjson').exists()


def test_a_page_that_cannot_be_written_stops_the_read_as_partial_and_keeps_the_last_complete_page(
        browser, tmp_path, monkeypatch, capsys):
    """commit-failure-is-8: the write of the second page fails once (the disk was full for a moment); the exit is 8
    with the cause and the command that resumes, and the file keeps its first page and says it was interrupted. (A disk that stays
    full fails the closing marker too and the exit is then 6 with count 0 — the core's pipeline, see the map.)"""
    import cli
    path = tmp_path / 'profile.ndjson'
    known_tab(browser).respond('x.query', card()).respond('x.query', timeline(tweet('11'), bottom='CUR1'))
    browser.respond('x.query', timeline(tweet('12'), bottom='CUR2'))
    browser.install(monkeypatch)
    monkeypatch.setenv('TZ', 'UTC')
    monkeypatch.setenv('SNS_IDLE_SECONDS', 'off')
    real, failed = os.fsync, []

    def full_disk(descriptor):
        if not failed and path.exists() and os.fstat(descriptor).st_ino == path.stat().st_ino \
                and path.read_text().count('"kind":"page"') > 1:
            failed.append(descriptor)
            raise OSError(28, 'No space left on device')  # the second page is written and cannot be made durable
        return real(descriptor)
    monkeypatch.setattr(os, 'fsync', full_disk)
    code = cli.main(['x', 'profile', '@author_a', '--out', str(path), '--limit', '5', '--json'])
    envelope = json.loads(capsys.readouterr().out)
    assert code == 8 and envelope['error'] == 'partial' and 'could not be written' in envelope['message'], envelope
    assert envelope['count'] == 1 and lines(path)[-1]['end'] == 'interrupted'
    assert [r['id'] for r in records(path)] == ['11', '12']  # 12 is past the last durable marker: replayed on resume
    monkeypatch.setattr(os, 'fsync', real)
    browser.respond('x.state', state()).respond('x.query', timeline(tweet('12')))
    code, out, _ = rerun(browser, 'resume: ' + envelope['next'])
    resumed = json.loads(out)  # the resume command keeps --json
    assert code == 0 and resumed['count'] == 2 and resumed['stop_reason'] == 'exhausted', out
    assert [r['id'] for r in records(path)] == ['11', '12']
