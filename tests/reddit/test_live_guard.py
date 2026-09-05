"""The live cap must stop a subprocess before it can invoke Aside."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_live_guard_refuses_request_31_without_invoking_aside(tmp_path):
    ledger = tmp_path / 'ledger.json'
    ledger.write_text(json.dumps({'requests': 30, 'calls': []}))
    fake = tmp_path / 'aside'
    marker = tmp_path / 'called'
    fake.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
    fake.chmod(0o755)
    env = {**os.environ, 'PATH': str(tmp_path), 'REDDIT_LIVE_LEDGER': str(ledger)}
    result = subprocess.run([sys.executable, str(Path(__file__).parent / 'live/guard_aside.py')], env=env, capture_output=True)
    assert result.returncode == 77 and not marker.exists()
    assert json.loads(ledger.read_text())['requests'] == 30
