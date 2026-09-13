"""Only HTTP transport is replaced; each subprocess runs real yfinance. Inline routes are synthetic examples, not recorded account traffic; their literal values establish the expected behavior independently of CLI output."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / ".claude/skills/yfinance/Scripts"


@pytest.fixture
def cli(tmp_path):
    def run(*args, routes=(), raw=False):
        run_dir = tmp_path / str(len(list(tmp_path.iterdir())))
        run_dir.mkdir()
        fixture = run_dir / "routes.json"
        fixture.write_text(json.dumps(routes))
        env = os.environ.copy()
        env.update(PYTHONPATH=str(Path(__file__).parent / "fixtures"), YF_HTTP_FIXTURE=str(fixture), YF_TEST_CACHE=str(run_dir / "cache"))
        proc = subprocess.run([sys.executable, str(SCRIPTS / "yfinance_cli.py"), *args], capture_output=True, text=True, env=env, timeout=30)
        assert "UNEXPECTED NETWORK" not in proc.stderr, proc.stderr
        if raw:
            return proc
        return proc, json.loads(proc.stdout)
    return run
