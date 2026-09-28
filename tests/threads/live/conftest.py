"""Live runs go through the CLI and the live bridge, whose ledger caps the requests of the whole run."""
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[1] / 'live_bridge' / 'aside'


@pytest.fixture(autouse=True)
def live_bridge(monkeypatch):
    monkeypatch.setenv('THREADS_ASIDE_BIN', str(BRIDGE))
    for name in ('THREADS_HOME', 'FAKE_NO_SLEEP', 'FAKE_CLOCK_OFFSET', 'PYTHONPATH'):
        monkeypatch.delenv(name, raising=False)
