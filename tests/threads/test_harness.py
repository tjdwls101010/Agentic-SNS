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
