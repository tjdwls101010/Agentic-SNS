"""The live bridge's ledger, offline: concurrent CLI processes cannot overrun the cumulative cap."""
import json
import os
import subprocess
import sys
from pathlib import Path

from .helpers import CLI, PROCESS_DOUBLES, data

BRIDGE = Path(__file__).with_name('live_bridge') / 'aside'


def test_concurrent_processes_share_the_cap_and_refused_calls_never_reach_aside(fake_aside, tmp_path):
    ledger = tmp_path / 'ledger.json'
    environment = {**os.environ, 'PYTHONPATH': str(PROCESS_DOUBLES), 'FAKE_NO_SLEEP': '1',
                   'THREADS_ASIDE_BIN': str(BRIDGE), 'THREADS_LIVE_ASIDE': os.environ['THREADS_ASIDE_BIN'],
                   'THREADS_LIVE_LEDGER': str(ledger), 'THREADS_LIVE_CAP': '3'}
    workers = [subprocess.Popen([sys.executable, str(CLI), 'doctor'], stdout=subprocess.PIPE, text=True,
                                env=environment) for _ in range(5)]
    codes = sorted(worker.wait(60) for worker in workers)
    assert codes == [0, 0, 0, 3, 3]
    assert json.loads(ledger.read_text())['requests'] == 3
    assert len(fake_aside.read_text().splitlines()) == 3
    refused = subprocess.run([sys.executable, str(CLI), 'doctor'], capture_output=True, text=True, env=environment)
    assert refused.returncode == 3 and data(refused)['error'] == 'aside'
