"""The scenario harness's replay: a recorded response is served byte for byte, and an unrecorded one is a miss."""
import json

from .fixtures.builders import Routes
from .helpers import FAKE_ASIDE, data, run_cli


def test_recording_then_replaying_serves_the_same_responses_and_flags_a_miss(fake_aside, tmp_path):
    snapshot = tmp_path / 'snapshot'
    record = {'THREADS_RECORD': str(snapshot), 'THREADS_REAL_ASIDE': str(FAKE_ASIDE)}
    first = run_cli('home', '--limit', '3', '--json', env=record)
    assert first.returncode == 0, first.stdout + first.stderr
    keys = [json.loads(line)['key'] for line in (snapshot / 'responses.ndjson').read_text().splitlines()]
    assert keys == ['page|/']
    replayed = run_cli('home', '--limit', '3', '--json', env={'THREADS_REPLAY': str(snapshot)})
    assert data(replayed)['results'] == data(first)['results']
    log = tmp_path / 'misses.ndjson'
    missed = run_cli('user', '@fixture_user', '--json',
                     env={'THREADS_REPLAY': str(snapshot), 'THREADS_HARNESS_LOG': str(log)})
    assert missed.returncode == 3
    assert json.loads(log.read_text().splitlines()[0])['harness_miss'] == 'page|/@fixture_user'


def test_offline_scenario_fixtures_are_synthetic(tmp_path):
    from .tools.ablation import fixtures
    import subprocess
    import sys
    for task in ('F1', 'F2', 'F3'):
        (tmp_path / task).mkdir()
        path = fixtures(task, tmp_path / task)
        gate = subprocess.run([sys.executable, 'tests/threads/tools/check_fixtures_pii.py', str(path)],
                              capture_output=True, text=True)
        assert gate.returncode == 0, gate.stdout
    assert Routes  # the builders are the only source of these fixtures


def test_a_recorded_text_with_a_line_separator_character_replays(fake_aside, tmp_path, routes):
    """JSON keeps U+2028 inside strings; the snapshot is split on newlines only."""
    body = routes.body('/').replace('Synthetic post 1', 'Synthetic post' + chr(0x2028) + 'one')
    page = {'status': 200, 'url': 'https://www.threads.com/', 'body': body}
    routes.set('/', {'raw_stdout': json.dumps(page, ensure_ascii=False) + '\n'}).write()  # Aside prints raw characters
    snapshot = tmp_path / 'snapshot'
    first = run_cli('home', '--json', env={'THREADS_RECORD': str(snapshot), 'THREADS_REAL_ASIDE': str(FAKE_ASIDE)})
    replayed = run_cli('home', '--json', env={'THREADS_REPLAY': str(snapshot)})
    assert replayed.returncode == 0, replayed.stdout + replayed.stderr
    assert data(replayed)['results'] == data(first)['results']


def test_a_harness_failure_invalidates_the_run_instead_of_looking_like_aside(fake_aside, tmp_path):
    snapshot = tmp_path / 'snapshot'
    snapshot.mkdir()
    (snapshot / 'responses.ndjson').write_text('{broken\n')
    log = tmp_path / 'misses.ndjson'
    run_cli('home', '--json', env={'THREADS_REPLAY': str(snapshot), 'THREADS_HARNESS_LOG': str(log)})
    assert 'harness_error' in log.read_text()
