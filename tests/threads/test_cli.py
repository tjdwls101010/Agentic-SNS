import json
import os
from pathlib import Path
import subprocess
import sys

CLI = Path(__file__).resolve().parents[2] / '.claude/skills/threads/scripts/threads.py'


def run_cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)


def test_doctor_through_aside_process_boundary(tmp_path, monkeypatch):
    from .test_session import route
    binary = tmp_path / 'aside'
    binary.write_text('#!' + sys.executable + '\nimport json\nprint(' + repr(json.dumps({
        'status': 200, 'url': 'https://www.threads.com/', 'body': route()})) + ')\n')
    binary.chmod(0o700)
    monkeypatch.setenv('THREADS_ASIDE_BIN', str(binary))
    result = run_cli('doctor', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert body['viewer'] == 'fixture_viewer'
    assert body['budget']['used'] == 1
    assert 'synthetic-csrf' not in result.stdout
    assert os.stat(Path(os.environ['THREADS_HOME']) / 'budget.json').st_mode & 0o777 == 0o600


def test_invalid_arguments_are_one_json_document_without_browser():
    result = run_cli('user', '/activity', '--json')
    assert result.returncode == 2
    assert json.loads(result.stdout)['error'] == 'arguments'
    assert result.stderr == ''


def test_help_describes_every_argument():
    result = run_cli('--help')
    assert result.returncode == 0
    for command in ('home', 'user', 'about', 'post', 'graph', 'search', 'me', 'doctor', 'refresh', 'schema'):
        assert command in result.stdout
    assert '--unblock' in run_cli('doctor', '--help').stdout
