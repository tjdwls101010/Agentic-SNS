"""Running the real cli.py as a subprocess, as the model does, and reading its more: lines back."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / '.claude/skills/sns/scripts/cli.py'


def run_cli(*args, browser=None, env=None, timeout=120):
    """Run `cli.py *args` with the fake browser's environment; returns CompletedProcess (text)."""
    environment = {k: v for k, v in os.environ.items()}
    if browser is not None:
        browser.write()
        environment.update(browser.env())
    environment.update(env or {})
    return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True,
                          env=environment, timeout=timeout)


def envelope(done):
    """The one JSON envelope a --json (or failed) run printed."""
    return json.loads(done.stdout)


def more_line(text):
    return next((line for line in text.splitlines() if line.startswith('more: ')), None)


def command_of(line):
    """The cli.py arguments of a more: or resume: line (everything after the quoted cli.py path)."""
    words = shlex.split(line.split(': ', 1)[1])
    assert words[:2] == ['uv', 'run'] and words[2].endswith('cli.py'), words
    return words[3:]
