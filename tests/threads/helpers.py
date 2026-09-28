"""Run the Threads CLI as a process against the fake Aside, as a caller would.

The `fake_aside` fixture (conftest) points THREADS_ASIDE_BIN, THREADS_FIXTURES and THREADS_FAKE_LOG at the fake and
gives each test its own THREADS_HOME; `run_cli` adds the process double that skips pacing sleeps.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / '.claude/skills/threads'
CLI = SKILL / 'scripts/cli.py'
PROCESS_DOUBLES = Path(__file__).with_name('process_doubles')
FAKE_ASIDE = Path(__file__).with_name('fake_aside') / 'aside'
POST = 'https://www.threads.com/@fixture_user/post/FIX_2'


def run_cli(*args, env=None, paced=False, cli=CLI, cwd=None):
    environment = {**os.environ, 'PYTHONPATH': str(PROCESS_DOUBLES)}
    if not paced:
        environment['FAKE_NO_SLEEP'] = '1'
    environment.update(env or {})
    return subprocess.run([sys.executable, str(cli), *args], capture_output=True, text=True, env=environment,
                          cwd=cwd, timeout=120)


def data(result):
    return json.loads(result.stdout)


def calls(log):
    """The fake Aside's call log: one entry per request the CLI made."""
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def more_args(command):
    """A more: command is this CLI's allowed-tools invocation; return the arguments after it."""
    words = shlex.split(command)
    assert words[:3] == ['uv', 'run', str(CLI)]
    return words[3:]


def run_more(command, **kwargs):
    return run_cli(*more_args(command), **kwargs)
