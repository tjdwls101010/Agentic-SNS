"""The skill directory runs as installed: through a real `uv run`, from a path outside this repository, from any cwd.

The rest of the suite runs cli.py with an interpreter built from the script's declared dependencies, which proves the
code but not the invocation. Here the invocation is the one SKILL.md gives, and the paths are the ones that break
quoting — a space, Hangul, a dollar sign and a quote — so a copy that works only from this checkout fails here.
"""
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_budget import chart_routes

SKILL = Path(__file__).resolve().parents[2] / ".claude/skills/yfinance"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(params=["with space", "한국어 경로", "dollar$sign", "quote'mark"])
def installed(request, tmp_path):
    copy = tmp_path / request.param / "yfinance"
    shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def run(installed, cwd, *argv, routes=()):
    fixture = cwd / "routes.json"
    fixture.write_text(json.dumps(list(routes)))
    env = dict(os.environ, PYTHONPATH=str(FIXTURES), YF_HTTP_FIXTURE=str(fixture), YF_TEST_CACHE=str(cwd / "cache"),
               YF_STORE=str(cwd / "store"))
    proc = subprocess.run(["uv", "run", "--quiet", str(installed / "scripts" / "cli.py"), *argv],
                          capture_output=True, text=True, env=env, cwd=cwd, timeout=300)
    assert "UNEXPECTED NETWORK" not in proc.stderr, proc.stderr
    return proc


def test_the_installed_copy_runs_from_an_unrelated_directory(installed, tmp_path):
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    proc = run(installed, cwd, "--help")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert proc.stdout.startswith("usage: cli.py")

    proc = run(installed, cwd, "schema", "prices", "history")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert json.loads(proc.stdout)["results"][0]["data"]["command"] == "prices history"

    out = cwd / "five years.csv"
    proc = run(installed, cwd, "prices", "history", "AAPL", "--period", "5y", "--out", str(out), routes=chart_routes())
    assert proc.returncode == 0, proc.stdout[:400] + proc.stderr[-800:]
    assert json.loads(proc.stdout)["results"][0]["data"]["rows"] == 300
    with open(out, newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 300

    left = {p.name for p in (installed / "scripts").iterdir()} - {"__pycache__"}
    assert left == {"cli.py", "yfinance_skill"}, "running the skill must not write a lock file or environment beside it"
