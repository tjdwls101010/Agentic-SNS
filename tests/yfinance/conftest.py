"""Only HTTP transport is replaced; each subprocess runs real yfinance. Inline routes are synthetic examples, not recorded account traffic; their literal values establish the expected behavior independently of CLI output.

`shape` and `inflate` exist because the two halves of a fixture fail differently. Recording a whole real payload keeps
passing after Yahoo changes its shape, and inventing a flat payload assumes a world where --fields reaches everything —
which is how a recovery sentence that could never work was tested green. So the structure is recorded from one real
item and the volume is synthetic on top of it.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/yfinance/scripts/cli.py"
SHAPES = Path(__file__).parent / "fixtures/shapes"


@pytest.fixture
def cli(tmp_path):
    def run(*args, routes=(), raw=False, store=None):
        run_dir = tmp_path / str(len(list(tmp_path.iterdir())))
        run_dir.mkdir()
        fixture = run_dir / "routes.json"
        fixture.write_text(json.dumps(routes))
        env = os.environ.copy()
        env.update(PYTHONPATH=str(Path(__file__).parent / "fixtures"), YF_HTTP_FIXTURE=str(fixture),
                   YF_TEST_CACHE=str(run_dir / "cache"), YF_STORE=str(store or (tmp_path / "store")))
        proc = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=60)
        assert "UNEXPECTED NETWORK" not in proc.stderr, proc.stderr
        if raw:
            return proc
        return proc, json.loads(proc.stdout)
    return run


def shape(name):
    return json.loads((SHAPES / f"{name}.json").read_text())


def inflate(template, index=0, text="x" * 40):
    """Build one synthetic record with the recorded nesting and key names, so a projection is tested against the real depth."""
    if isinstance(template, dict):
        return {k: inflate(v, index, text) for k, v in template.items()}
    if isinstance(template, list):
        return [inflate(template[0], index, text)] if template else []
    if template == "number":
        return 1000 + index
    if template == "bool":
        return False
    if template == "null":
        return None
    return f"{text}-{index}"
