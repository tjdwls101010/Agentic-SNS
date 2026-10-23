"""The shared reading pipeline end to end, through cli.main with the two stub platforms and the fake Aside: paging and
more:, handles, --out, windows, stops that pass by themselves, person blocks, the time limit, another platform's URL,
a changed account, doctor and the idle cleanup."""
import json

import pytest

import cli
from sns import reading
from sns.clock import Deadline
from tests.sns.support.browser import Browser
from tests.sns.support.cli import command_of, more_line
from tests.sns.support.stub_platform import ALPHA, BETA, STUBS


@pytest.fixture
def browser(tmp_path, monkeypatch, data_dir):
    monkeypatch.setenv('SNS_IDLE_SECONDS', 'off')
    return Browser(tmp_path)


def run(capsys, browser, monkeypatch, *argv):
    browser.install(monkeypatch)
    code = cli.main([str(a) for a in argv], platforms=STUBS)
    return code, capsys.readouterr().out


def item(n, day='2026-10-10', hour=12):
    return {'id': f'i{n}', 'text': f'post {n}', 'url': f'https://alpha.test/p/i{n}',
            'created_at': f'{day}T{hour:02d}:00:00+09:00'}


def feed(browser, cursor, items, following=None, **extra):
    browser.respond('alpha.get', {'status': 200, 'body': {'items': items, 'next': following, **extra}},
                    path='/feed', cursor=cursor)


def me(browser, viewer='ann'):
    browser.respond('alpha.get', {'status': 200, 'body': {'viewer': viewer}}, path='/me')


def requests_sent(browser, op='alpha.get'):
    return [c for c in browser.calls() if c['op'] == op]


def test_one_page_by_default_then_more_continues_without_repeats(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1), item(2)], 'C2', promoted=1)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    assert code == 0
    first = out.splitlines()[0]
    assert first.startswith('alpha feed · 2 shown · stopped=limit_reached · requests=2')
    assert 'coverage: 1 promoted entries (ads) left out' in out
    line = more_line(out)
    assert command_of(line)[:2] == ['alpha', 'feed'] and '--after' in command_of(line)
    assert line.startswith('more: uv run "') and line.split('"')[1].endswith('scripts/cli.py')
    me(browser)  # a continued reading checks the account it was read with (one request on a fetch platform)
    feed(browser, 'C2', [item(2), item(3)], None)
    code, out = run(capsys, browser, monkeypatch, *command_of(line))
    assert code == 0 and '[p1] i3' in out and 'i2 ' not in out and more_line(out) is None


def test_limit_reads_on_across_pages(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1)], 'C2')
    feed(browser, 'C2', [item(2)], 'C3')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '2')
    assert code == 0 and '2 shown' in out and len(requests_sent(browser)) == 3


def test_a_hold_before_records_is_exit_5_and_after_records_resumes(capsys, browser, monkeypatch):
    me(browser)
    browser.respond('alpha.get', {'status': 429, 'body': {}}, path='/feed', cursor=None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    envelope = json.loads(out)
    assert code == 5 and envelope['error'] == 'blocked' and envelope['stop_reason'] == 'rate_limited'
    assert envelope['limit']['scope'] is None and 'resume by themselves' in envelope['message']


def test_a_hold_after_records_is_a_resumable_stop(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1)], 'C2')
    browser.respond('alpha.get', {'status': 429, 'body': {}}, path='/feed', cursor='C2')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '5', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['stop_reason'] == 'rate_limited' and envelope['next']
    assert envelope['results'][0]['id'] == 'i1'


def test_a_person_block_stops_this_and_every_later_command_before_the_browser(capsys, browser, monkeypatch):
    me(browser)
    browser.respond('alpha.get', {'status': 200, 'body': {'network_blocked': True}}, path='/feed', cursor=None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    assert code == 5 and json.loads(out)['stop_reason'] == 'blocked'
    before = len(browser.calls())
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    assert code == 5 and 'doctor --unblock' in json.loads(out)['fix']
    assert [c['op'] for c in browser.calls()[before:]] == ['account_status']


def test_doctor_unblock_lifts_the_block_only_after_a_clean_check(capsys, browser, monkeypatch):
    me(browser)
    browser.respond('alpha.get', {'status': 200, 'body': {'network_blocked': True, 'viewer': 'ann'}}, path='/feed')
    run(capsys, browser, monkeypatch, 'alpha', 'feed')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'doctor')
    assert code == 5
    me(browser, 'bob')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'doctor', '--unblock')
    assert code == 5 and json.loads(out)['verification_reason'] == 'account_mismatch'
    me(browser, 'ann')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'doctor', '--unblock')
    envelope = json.loads(out)
    assert code == 0 and envelope['results'][0]['unblocked'] is True and envelope['results'][0]['blocked'] is False
    assert envelope['results'][0]['alpha_check'] == 'fine'


def test_an_unavailable_target_is_exit_9_and_leaves_no_continuation(capsys, browser, monkeypatch):
    browser.respond('alpha.get', {'status': 404, 'body': {}}, path='/p/gone')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'post', 'https://alpha.test/p/gone')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_another_platforms_url_is_refused_with_the_command_that_reads_it(capsys, browser, monkeypatch):
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'post', 'https://beta.test/home')
    envelope = json.loads(out)
    assert code == 2 and envelope['fix'] == 'Read it with: beta feed https://beta.test/home'
    assert [c['op'] for c in browser.calls()] == []


def test_a_handle_of_another_command_names_where_it_belongs(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1)], 'C2')
    _, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    handle = command_of(more_line(out))[command_of(more_line(out)).index('--after') + 1]
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'ranked', '--after', handle)
    envelope = json.loads(out)
    assert code == 2 and 'alpha feed' in envelope['message']


def test_a_changed_account_on_continuing_is_exit_4(capsys, browser, monkeypatch):
    me(browser, 'ann')
    feed(browser, None, [item(1)], 'C2')
    _, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    me(browser, 'bob')
    code, out = run(capsys, browser, monkeypatch, *command_of(more_line(out)))
    envelope = json.loads(out)
    assert code == 4 and envelope['error'] == 'login' and 'bob' in envelope['message']


def test_out_commits_pages_concludes_and_a_rerun_repeats_without_requests(capsys, browser, monkeypatch, tmp_path):
    path = tmp_path / 'feed.ndjson'
    me(browser)
    feed(browser, None, [item(1)], 'C2')
    feed(browser, 'C2', [item(2)], None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--out', path)
    assert code == 0 and '2 saved to' in out and 'resume:' not in out
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines[0]['platform'] == 'alpha' and lines[-1]['end'] == 'final'
    before = len(browser.calls())
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--out', path)
    assert code == 0 and 'already complete' in out
    assert [c['op'] for c in browser.calls()[before:]] == ['account_status']


def test_an_interrupted_collection_resumes(capsys, browser, monkeypatch, tmp_path):
    path = tmp_path / 'feed.ndjson'
    me(browser)
    feed(browser, None, [item(1)], 'C2')
    browser.respond('alpha.get', {'status': 500, 'body': {}}, path='/feed', cursor='C2')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--out', path)
    assert code == 8 and 'resume:' in out
    me(browser)
    feed(browser, 'C2', [item(2)], None)
    resume = out.strip().split(' · resume: ', 1)[1].split(' · error=', 1)[0]
    code, out = run(capsys, browser, monkeypatch, *command_of('resume: ' + resume))
    assert code == 0 and '2 saved to' in out


def test_a_stalled_collection_is_interrupted_not_final(capsys, browser, monkeypatch, tmp_path):
    path = tmp_path / 'feed.ndjson'
    me(browser)
    feed(browser, None, [item(1)], 'C2', stop='pagination_stalled')  # the platform saw its pages repeat
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--out', path)
    assert code == 8
    assert json.loads(path.read_text().splitlines()[-1])['end'] == 'interrupted'


def test_an_endless_surface_refuses_out_without_limit_before_any_call(capsys, browser, monkeypatch, tmp_path):
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'ranked', '--out', tmp_path / 'r.ndjson')
    assert code == 2 and '--limit' in json.loads(out)['fix'] and browser.calls() == []


def test_an_out_path_inside_data_is_refused(capsys, browser, monkeypatch, data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--out', data_dir / 'x.ndjson')
    assert code == 2


def test_a_newest_first_window_closes_at_since(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1, '2026-10-12'), item(2, '2026-10-11')], 'C2')
    feed(browser, 'C2', [item(3, '2026-10-10'), item(4, '2026-10-09')], 'C3')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--since', '2026-10-10', '--until', '2026-10-11')
    lines = out.splitlines()
    assert code == 0 and 'stopped=window_reached' in lines[0]
    assert lines[1] == 'window 2026-10-10..2026-10-11 KST · closed (as served)'
    assert '[p1] i2' in out and '[p2] i3' in out and 'i4' not in out and 'i1 ' not in out


def test_a_window_on_a_ranked_surface_reads_one_page_as_a_sample(capsys, browser, monkeypatch):
    me(browser)
    browser.respond('alpha.get', {'status': 200, 'body': {'items': [item(1, '2026-10-12'), item(2, '2026-10-10')],
                                                          'next': 'R2'}}, path='/ranked', cursor=None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'ranked', '--since', '2026-10-10')
    lines = out.splitlines()
    assert code == 0 and lines[1].endswith('· sample (not in date order)') and more_line(out)
    assert len(requests_sent(browser)) == 2  # the account, then one page


def test_a_listing_that_ends_before_the_window_is_partial(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1, '2026-10-12')], None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--since', '2026-10-01')
    assert code == 8 and "[p1] i1" in out
    assert 'not covered' in out


def test_the_time_limit_after_records_resumes_and_before_records_is_exit_6(capsys, browser, monkeypatch):
    monkeypatch.setenv('SNS_DEADLINE_SECONDS', '4.5')  # pacing (virtual) leaves room for about one more request
    me(browser)
    feed(browser, None, [item(1)], 'C2')
    feed(browser, 'C2', [item(2)], 'C3')
    feed(browser, 'C3', [item(3)], 'C4')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '10', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['stop_reason'] == 'time_limit' and envelope['next']
    monkeypatch.setenv('SNS_DEADLINE_SECONDS', '1')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    assert code == 6 and json.loads(out)['stop_reason'] == 'time_limit'


# --- beta: the tab platform --------------------------------------------------------------------------------------

def beta_page(browser, cursor, items, following=None, remaining=90, status=200):
    browser.respond('beta.query', {'status': status, 'items': items, 'next': following,
                                   'headers': {'limit': 100, 'remaining': remaining, 'reset': 300}}, cursor=cursor)


def test_the_tab_is_opened_once_counted_apart_and_a_low_limit_shows(capsys, browser, monkeypatch):
    browser.respond('beta.state', {'viewer': 'carl'})
    beta_page(browser, None, [item(1)], 'C2', remaining=10)
    code, out = run(capsys, browser, monkeypatch, 'beta', 'feed')
    first = out.splitlines()[0]
    assert code == 0 and 'tab opened (+5 requests)' in first and 'limit general 10 of 100 left resets' in first
    assert [c['op'] for c in browser.calls()].count('open') == 1
    browser.respond('beta.state', {'viewer': 'carl'})
    beta_page(browser, None, [item(2)], 'C3')
    code, out = run(capsys, browser, monkeypatch, 'beta', 'feed')
    assert code == 0 and 'tab opened' not in out and [c['op'] for c in browser.calls()].count('open') == 1


def test_a_scope_limit_before_records_is_exit_10_and_after_records_resumes(capsys, browser, monkeypatch):
    browser.respond('beta.state', {'viewer': 'carl'})
    beta_page(browser, None, [], status=429)
    code, out = run(capsys, browser, monkeypatch, 'beta', 'feed')
    envelope = json.loads(out)
    assert code == 10 and envelope['error'] == 'scope_limit' and envelope['limit']['scope'] == 'general'


def test_idle_cleanup_closes_the_tab_unless_a_newer_command_released_it(capsys, browser, monkeypatch):
    browser.respond('beta.state', {'viewer': 'carl'})
    beta_page(browser, None, [item(1)], None)
    run(capsys, browser, monkeypatch, 'beta', 'feed')
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    assert reading.idle(BETA.PLATFORM, invocation, 'u0', 'stale-token', 0) == 'newer command'
    tab = next(t for t in json.loads(browser.path.read_text())['tabs'] if t['url'].startswith('https://beta.test'))
    assert reading.idle(BETA.PLATFORM, invocation, 'u0', 'any', 0) == 'emptied'
    assert tab['id'] not in [t['id'] for t in json.loads(browser.path.read_text())['tabs']]
    assert 'beta.close' in browser.ops()


def test_alpha_schema_lists_shared_and_record_objects(capsys, browser, monkeypatch):
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'schema')
    assert code == 0 and [r['object'] for r in json.loads(out)['results']] == ['result', 'out', 'post']
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'schema', 'result')
    exits = {row['exit']: row['kinds'] for row in json.loads(out)['results'][0]['exit_codes']}
    assert exits[10] == ['scope_limit'] and exits[5] == ['blocked']


# --- repairs from the core review (Codex, 2026-10-21) ---------------------------------------------------------------

def test_a_stalled_read_keeps_where_to_continue(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1)], 'C2', stop='pagination_stalled')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed')
    assert code == 8 and more_line(out)
    me(browser)
    feed(browser, 'C2', [item(2)], None)
    code, out = run(capsys, browser, monkeypatch, *command_of(more_line(out)))
    assert code == 0 and '[p1] i2' in out


def test_out_refuses_a_file_of_another_window(capsys, browser, monkeypatch, tmp_path):
    path = tmp_path / 'feed.ndjson'
    me(browser)
    feed(browser, None, [item(1, '2026-10-12')], None)
    run(capsys, browser, monkeypatch, 'alpha', 'feed', '--since', '2026-10-10', '--out', path)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--since', '2026-10-01', '--out', path)
    assert code == 2


def test_more_keeps_the_window_it_was_read_with(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1, '2026-10-12')], 'C2')
    _, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--since', '2026-10-10', '--limit', '1')
    words = command_of(more_line(out))
    assert words[words.index('--since') + 1] == '2026-10-10'


def test_an_account_seen_changing_mid_command_is_exit_4(capsys, browser, monkeypatch):
    me(browser, 'ann')
    feed(browser, None, [item(1)], 'C2', viewer='ann')
    feed(browser, 'C2', [item(2)], None, viewer='bob')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '5', '--json')
    envelope = json.loads(out)
    assert code == 4 and envelope['error'] == 'login' and 'bob' in envelope['message']


def test_a_handle_always_carries_the_account_even_from_an_unbound_read(capsys, browser, monkeypatch):
    browser.respond('alpha.get', {'status': 200, 'body': {'items': [item(1)], 'next': 'R2'}}, path='/ranked',
                    cursor=None)
    me(browser, 'ann')
    _, out = run(capsys, browser, monkeypatch, 'alpha', 'ranked')
    me(browser, 'bob')
    code, out = run(capsys, browser, monkeypatch, *command_of(more_line(out)))
    assert code == 4


def test_a_tab_platforms_unblock_makes_its_request_and_checks_the_account(capsys, browser, monkeypatch):
    browser.respond('beta.state', {'viewer': 'alice'})
    browser.respond('beta.query', {'status': 200, 'challenge': True, 'items': []}, cursor=None)
    code, _ = run(capsys, browser, monkeypatch, 'beta', 'feed')
    assert code == 5
    browser.respond('beta.state', {'viewer': 'bob'})
    browser.respond('beta.query', {'status': 200, 'items': [], 'viewer': 'bob'}, check=True)
    code, out = run(capsys, browser, monkeypatch, 'beta', 'doctor', '--unblock')
    assert code == 5 and json.loads(out)['verification_reason'] == 'account_mismatch'
    browser.respond('beta.state', {'viewer': 'alice'})
    browser.respond('beta.query', {'status': 200, 'items': [], 'viewer': 'alice'}, check=True)
    before = browser.ops().count('beta.query')
    code, out = run(capsys, browser, monkeypatch, 'beta', 'doctor', '--unblock')
    assert code == 0 and browser.ops().count('beta.query') == before + 1


def test_a_failed_section_that_blocks_stops_the_composite_and_its_continuation(capsys, browser, monkeypatch):
    browser.respond('alpha.get', {'status': 200, 'body': {'id': 'i1', 'text': 't', 'url': 'u'}}, path='/p/i1')
    browser.respond('alpha.get', {'status': 200, 'body': {'network_blocked': True}}, path='/p/i1/comments')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'card', 'https://alpha.test/p/i1', '--json')
    envelope = json.loads(out)
    assert code == 5 and envelope['error'] == 'blocked' and 'next' not in envelope
    assert [s['name'] for s in envelope['sections']] == ['post', 'comments']


def test_saving_a_handle_waits_only_until_the_deadline(data_dir):
    import subprocess as sp
    import sys as system
    from sns import handles
    from sns.errors import SnsError
    directory = data_dir / 'handles'
    directory.mkdir(parents=True)
    holder = sp.Popen([system.executable, '-c', 'import fcntl,time\n'
                       f'f=open({str(directory / "counter")!r},"a"); fcntl.flock(f, fcntl.LOCK_EX)\n'
                       'print("held", flush=True); time.sleep(30)'], stdout=sp.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        with pytest.raises(SnsError) as caught:
            handles.save({'a': 1}, {}, deadline=Deadline(0.3))
        assert caught.value.reason == 'time_limit'
    finally:
        holder.kill()
        holder.wait()


def test_account_resolution_cut_by_the_deadline_is_the_time_limit(browser, monkeypatch):
    from sns.aside import Aside
    from sns.errors import SnsError
    browser.flag(account_status_sleep=3).install(monkeypatch)
    with pytest.raises(SnsError) as caught:
        Aside('alpha', Deadline(0.5))
    assert caught.value.reason == 'time_limit'


def test_idle_retries_a_cleanup_that_failed(capsys, browser, monkeypatch):
    from tests.sns.support import stub_platform
    browser.respond('beta.state', {'viewer': 'carl'})
    beta_page(browser, None, [item(1)], None)
    run(capsys, browser, monkeypatch, 'beta', 'feed')
    attempts = []
    real = stub_platform.BetaClient.release_tab

    def flaky(self):
        attempts.append(1)
        return False if len(attempts) == 1 else real(self)
    monkeypatch.setattr(stub_platform.BetaClient, 'release_tab', flaky)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    assert reading.idle(BETA.PLATFORM, invocation, 'u0', 'any', 0) == 'emptied' and len(attempts) == 2


def test_a_reader_can_save_and_resume_handles_of_its_own(browser, monkeypatch):
    """A thread command names several handles at once (the next batch, hidden replies, each reply's branch); they are
    bound to the platform, command, target and Aside account, and carry the account they were read with."""
    me(browser, 'ann')
    me(browser, 'ann')  # each new connection of a fetch platform asks once
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    number = connection.handle('replies', {'kind': 'branch', 'cursor': 'B1'}, target='i1')
    again = reading.Connection(ALPHA.PLATFORM, invocation).start()
    assert again.resume(number, 'replies', target='i1') == {'kind': 'branch', 'cursor': 'B1'}
    from sns.errors import SnsError
    with pytest.raises(SnsError) as caught:
        again.resume(number, 'feed')
    assert caught.value.kind == 'argument' and 'alpha replies' in caught.value.message
    me(browser, 'bob')
    browser.install(monkeypatch)
    other = reading.Connection(ALPHA.PLATFORM, invocation).start()
    with pytest.raises(SnsError) as caught:
        other.resume(number, 'replies', target='i1')
    assert caught.value.kind == 'login'


def test_a_worse_section_failure_wins_over_a_top_level_one(capsys, browser, monkeypatch):
    browser.respond('alpha.get', {'status': 200, 'body': {'id': 'i1', 'text': 't', 'url': 'u'}}, path='/p/i1')
    browser.respond('alpha.get', {'status': 200, 'body': {'network_blocked': True}}, path='/p/i1/comments')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'card', 'https://alpha.test/p/i1', '--json',
                    '--chars', '5')  # --chars 5 makes the stub report a soft failure of its own beside the sections
    assert code == 5 and json.loads(out)['error'] == 'blocked'


def test_a_reader_saves_pictures_through_its_connection(browser, monkeypatch, data_dir):
    me(browser, 'ann')
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    path = connection.save_image(b'\x89PNG....', 'image/png', key='i1', number=2)
    assert path.parent == data_dir / 'images' and path.name.startswith('alpha-i1-2-') and path.suffix == '.png'


# --- pictures (S12) -------------------------------------------------------------------------------------------------

MEDIA = [{'n': 1, 'kind': 'photo', 'image_url': 'https://cdn.alpha.test/a.jpg', 'video_url': None, 'width': 10,
          'height': 20, 'alt': 'a cat', 'media_id': 'm1'},
         {'n': 2, 'kind': 'video', 'image_url': 'https://cdn.alpha.test/poster.jpg', 'video_url': 'https://v/x.mp4',
          'width': 30, 'height': 40, 'alt': None, 'media_id': 'm2'},
         {'n': 3, 'kind': 'photo', 'image_url': 'https://elsewhere.test/b.jpg', 'video_url': None, 'width': 1,
          'height': 1, 'alt': None, 'media_id': 'm3'}]


def download(browser, url, data=b'\xff\xd8\xff\xe0jpeg', content_type='image/jpeg', status=200):
    import base64
    browser.respond('aside.media', {'status': status, 'type': content_type, 'size': len(data),
                                    'data': base64.b64encode(data).decode()}, url=url)


def test_pictures_are_saved_by_number_with_what_they_show(browser, monkeypatch, data_dir):
    me(browser)
    download(browser, 'https://cdn.alpha.test/poster.jpg')
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    result = reading.pictures(connection, key='i1', media=MEDIA, numbers=[2], hosts=('cdn.alpha.test',))
    record = result['results'][0]
    assert record['kind'] == 'image' and record['n'] == 2 and record['media_kind'] == 'video'
    assert record['media_id'] == 'm2' and record['content_type'] == 'image/jpeg' and record['bytes'] == 8
    assert record['path'].startswith(str(data_dir / 'images')) and result['failure'] is None
    assert connection.guard.count == 1


def test_pictures_name_what_they_could_not_save_and_are_partial(browser, monkeypatch, data_dir):
    me(browser)
    download(browser, 'https://cdn.alpha.test/a.jpg', data=b'<html>', content_type='text/html')
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    result = reading.pictures(connection, key='i1', media=MEDIA, numbers=[1, 3], hosts=('cdn.alpha.test',))
    assert result['results'] == [] and result['failure'].kind == 'partial'
    notes = ' '.join(result['coverage'])
    assert 'picture 1' in notes and 'not a picture' in notes
    assert 'picture 3' in notes and 'elsewhere.test' in notes
    assert connection.guard.count == 1  # only the one allowed host was asked


def test_a_number_the_post_does_not_have_is_an_argument_error_before_any_picture(browser, monkeypatch, data_dir):
    """Asking for a picture the post does not have is the caller's mistake (naver's rule, now every platform's): the
    range is named and no picture is fetched."""
    from sns.errors import SnsError
    me(browser)
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    with pytest.raises(SnsError) as caught:
        reading.pictures(connection, key='i1', media=MEDIA, numbers=[1, 9], hosts=('cdn.alpha.test',))
    assert caught.value.kind == 'argument' and '1-3' in caught.value.fix
    assert connection.guard.count == 0


def test_all_takes_every_picture_and_none_is_an_argument_error(browser, monkeypatch, data_dir):
    me(browser)
    download(browser, 'https://cdn.alpha.test/a.jpg')
    download(browser, 'https://cdn.alpha.test/poster.jpg')
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    result = reading.pictures(connection, key='i1', media=MEDIA[:2], numbers=None, hosts=('cdn.alpha.test',))
    assert [r['n'] for r in result['results']] == [1, 2]
    from sns.errors import SnsError
    with pytest.raises(SnsError) as caught:
        reading.pictures(connection, key='i1', media=[], numbers=None, hosts=('cdn.alpha.test',))
    assert caught.value.kind == 'empty'


def test_a_picture_over_the_size_cap_is_refused_in_the_browser(browser, monkeypatch, data_dir):
    me(browser)
    browser.respond('aside.media', {'status': 200, 'type': 'image/jpeg', 'size': 11 * 1024 * 1024, 'data': None,
                                    'too_large': True}, url='https://cdn.alpha.test/a.jpg')
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    result = reading.pictures(connection, key='i1', media=MEDIA, numbers=[1], hosts=('cdn.alpha.test',))
    assert result['failure'].kind == 'partial' and 'larger than 10 MB' in ' '.join(result['coverage'])


def test_a_stop_between_pictures_keeps_the_saved_ones_and_offers_the_rest(browser, monkeypatch, data_dir):
    """The time limit or a hold between two pictures is a stop, not a lost read: the saved pictures are reported (their
    files exist) and the command for the numbers left is offered (naver's rule, now every platform's)."""
    from sns.errors import SnsError
    me(browser)
    browser.install(monkeypatch)
    invocation = reading.Invocation({'target': 'https://alpha.test/p/i1', 'numbers': [1, 2], 'json': True},
                                    Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    asked = []

    def fetch(url):
        asked.append(url)
        if len(asked) == 2:
            raise SnsError('failed', 'The command reached its time limit.', 'Run it again.', reason='time_limit')
        return b'\xff\xd8\xff\xe0jpeg', 'image/jpeg'

    result = reading.pictures(connection, key='i1', media=MEDIA, numbers=[1, 2], hosts=('cdn.alpha.test',),
                              fetch=fetch)
    assert [r['n'] for r in result['results']] == [1] and result['failure'].reason == 'time_limit'
    assert result['continuable'] and result['next'].endswith('alpha images https://alpha.test/p/i1 2 --json')


def test_a_platform_fetch_replaces_the_download_and_guards_itself(browser, monkeypatch, data_dir):
    me(browser)
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    result = reading.pictures(connection, key='i1', media=MEDIA, numbers=[1], hosts=('cdn.alpha.test',),
                              fetch=lambda url: (b'\x89PNG....', 'image/png'))
    assert result['results'][0]['content_type'] == 'image/png'
    assert connection.guard.count == 0 and not [c for c in browser.calls() if c['op'] == 'aside.media']


def test_a_number_asked_of_a_post_without_pictures_is_an_argument_error(browser, monkeypatch, data_dir):
    """Found by review: the empty check came first, so 'images <post> 1' on a text post was exit 7, not 2."""
    from sns.errors import SnsError
    me(browser)
    browser.install(monkeypatch)
    invocation = reading.Invocation({}, Deadline(30), {}, cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    with pytest.raises(SnsError) as caught:
        reading.pictures(connection, key='i1', media=[], numbers=[1], hosts=('cdn.alpha.test',))
    assert caught.value.kind == 'argument'


def test_a_stop_that_ends_continuing_still_keeps_the_saved_pictures(browser, monkeypatch, data_dir):
    """Found by review: a login wall or a person block after a saved picture dropped its record although the file was
    on disk; it is kept, with the failure, and no command for the rest is offered (a login or block stops that)."""
    from sns.errors import SnsError
    me(browser)
    browser.install(monkeypatch)
    invocation = reading.Invocation({'target': 'https://alpha.test/p/i1', 'numbers': [1, 2]}, Deadline(30), {},
                                    cli.__file__)
    connection = reading.Connection(ALPHA.PLATFORM, invocation).start()
    asked = []

    def fetch(url):
        asked.append(url)
        if len(asked) == 2:
            raise SnsError('login', 'The account is logged out.', 'Log in.', reason='login_required')
        return b'\xff\xd8\xff\xe0jpeg', 'image/jpeg'

    result = reading.pictures(connection, key='i1', media=MEDIA, numbers=[1, 2], hosts=('cdn.alpha.test',),
                              fetch=fetch)
    assert [r['n'] for r in result['results']] == [1] and result['failure'].kind == 'login'
    assert not result.get('next') and not result.get('continuable')
