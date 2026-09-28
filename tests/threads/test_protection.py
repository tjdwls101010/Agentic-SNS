"""Account protection through the CLI: every request is counted, blocks persist, and a block stops requests."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .fixtures.builders import ERRORS, envelope, listed_post, tab
from .helpers import CLI, PROCESS_DOUBLES, calls, data, run_cli, run_more

REPLIES = 'BarcelonaProfileRepliesTabDirectQuery'


def home_blocked(log):
    """The next read is refused before it makes any request."""
    before = len(calls(log))
    result = run_cli('user', '@fixture_user', '--tab', 'replies', '--json')
    return result.returncode == 5 and len(calls(log)) == before, data(result)


def test_separate_processes_share_one_request_window(fake_aside):
    environment = {**os.environ, 'PYTHONPATH': str(PROCESS_DOUBLES), 'FAKE_NO_SLEEP': '1'}
    workers = [subprocess.Popen([sys.executable, str(CLI), 'doctor'], stdout=subprocess.DEVNULL, env=environment)
               for _ in range(2)]
    assert [worker.wait(60) for worker in workers] == [0, 0]
    assert data(run_cli('doctor'))['budget']['window_used'] == 3


def test_a_full_window_refuses_before_any_request(fake_aside):
    home = Path(os.environ['THREADS_HOME'])
    home.mkdir(parents=True)
    (home / 'budget.json').write_text(json.dumps({'requests': [time.time()] * 120}))
    result = run_cli('home', '--json')
    assert result.returncode == 5
    assert calls(fake_aside) == []


def test_a_checkpoint_blocks_every_later_request_until_unblock_succeeds(routes):
    log = routes.path.parent / 'requests.ndjson'
    root = routes.body('/')
    ok = envelope(root, url='https://www.threads.com/')
    # doctor is the only command here that opens /: the first unblock probe is limited, the second succeeds.
    routes.set('/', envelope({}, status=429, url='https://www.threads.com/'), ok)
    routes.set(REPLIES, ERRORS['checkpoint'], envelope(tab([listed_post(1)])))
    routes.write()
    first = run_cli('user', '@fixture_user', '--tab', 'replies', '--json')
    assert (first.returncode, data(first)['error']) == (5, 'checkpoint')
    assert home_blocked(log)[0]
    assert run_cli('doctor').returncode == 5
    # An unblock probe that is itself limited keeps the checkpoint: a rate limit never replaces it.
    failed = run_cli('doctor', '--unblock')
    assert failed.returncode == 5
    blocked, body = home_blocked(log)
    assert blocked and body['error'] == 'checkpoint'
    assert run_cli('doctor', '--unblock').returncode == 0
    assert run_cli('user', '@fixture_user', '--tab', 'replies', '--json').returncode == 0


def test_a_rate_limit_expires_by_itself_after_thirty_minutes(routes):
    log = routes.path.parent / 'requests.ndjson'
    routes.set(REPLIES, ERRORS['rate_limit'], envelope(tab([listed_post(1)])))
    routes.write()
    assert data(run_cli('user', '@fixture_user', '--tab', 'replies', '--json'))['error'] == 'rate_limit'
    before = len(calls(log))
    assert run_cli('user', '@fixture_user', '--tab', 'replies', env={'FAKE_CLOCK_OFFSET': '1700'}).returncode == 5
    assert len(calls(log)) == before
    later = run_cli('user', '@fixture_user', '--tab', 'replies', '--json', env={'FAKE_CLOCK_OFFSET': '1801'})
    assert later.returncode == 0, later.stdout + later.stderr


def test_login_required_is_reported_without_blocking(routes):
    routes.set(REPLIES, ERRORS['login'], envelope(tab([listed_post(1)])))
    routes.write()
    assert run_cli('user', '@fixture_user', '--tab', 'replies', '--json').returncode == 4
    assert run_cli('user', '@fixture_user', '--tab', 'replies', '--json').returncode == 0


def test_a_request_the_bridge_lost_is_still_counted(routes):
    routes.set(REPLIES, {'mode': 'fail'})
    routes.write()
    assert run_cli('user', '@fixture_user', '--tab', 'replies', '--json').returncode == 3
    assert data(run_cli('doctor'))['budget']['window_used'] == 3


def test_the_command_request_cap_stops_with_a_continuation(routes):
    routes.set(REPLIES, envelope(tab([listed_post(1)], 'c1')))
    for n in range(1, 20):
        routes.set(f'{REPLIES}:after=c{n}', envelope(tab([listed_post(n + 1)], f'c{n + 1}')))
    routes.write()
    result = run_cli('user', '@fixture_user', '--tab', 'replies', '--json')
    assert result.returncode == 8, result.stdout + result.stderr
    body = data(result)
    # Ten requests: the route and nine pages of one post each.
    assert (body['stop_reason'], len(body['results']), body['budget']['used']) == ('budget', 9, 10)
    resumed = run_more(body['next'])
    assert [p['id'] for p in data(resumed)['results']][0] == '10'
