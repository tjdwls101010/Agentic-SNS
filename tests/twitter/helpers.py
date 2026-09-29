"""Run the twitter CLI as a process against the fake Aside, as the model would.

The `fake_env` fixture (conftest) gives each test its own TWITTER_HOME seeded with a session and signature material, an empty fake script, request log and trace, and the process double that skips pacing sleeps.
"""
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / '.claude/skills/twitter/scripts/cli.py'
FAKE_ASIDE = Path(__file__).with_name('fake_aside') / 'aside'
PROCESS_DOUBLES = Path(__file__).with_name('process_doubles')
FIXTURES = Path(__file__).with_name('fixtures')


def run(args, env, *, json_mode=True, cli=CLI):
    return subprocess.run([sys.executable, str(cli), *args, *(['--json'] if json_mode else [])], capture_output=True,
                          text=True, env=env, timeout=120)


def invoke(args, env):
    """Exit code and the one JSON document of a --json run."""
    done = run(args, env)
    assert done.stdout, done.stderr
    return done.returncode, json.loads(done.stdout)


def text(args, env):
    done = run(args, env, json_mode=False)
    assert done.stdout, done.stderr
    return done.returncode, done.stdout


def script(env, *entries):
    """Queue scripted fake Aside answers; each is consumed by the first call it matches."""
    path = Path(env['TWITTER_FAKE_SCRIPT'])
    path.write_text(json.dumps(json.loads(path.read_text()) + list(entries)))


def records(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def calls(env):
    """One entry per request the CLI made: op, method and variables."""
    return records(env['TWITTER_FAKE_LOG'])


def trace(env):
    """One entry per request the CLI made: snippet, argv shape, ct0, txid and url."""
    return records(env['TWITTER_FAKE_TRACE'])


def home(env):
    return Path(env['TWITTER_HOME'])


def more_args(command):
    """A more: command is this CLI's allowed-tools invocation; return the arguments after it."""
    words = shlex.split(command)
    assert words[:3] == ['uv', 'run', str(CLI)], command
    return words[3:]
