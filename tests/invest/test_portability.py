"""The skill directory runs as installed: through a real `uv run`, from a path outside this repository, from any cwd, keeping its results in its own data folder.

The rest of the suite runs cli.py with an interpreter built from the script's declared dependencies, which proves the code but not the invocation. Here the invocation is the one SKILL.md gives, and the paths are the ones that break quoting: a space, Hangul, a dollar sign and a quote.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_prices import chart_routes

SKILL = Path(__file__).resolve().parents[2] / ".claude/skills/invest"
FIXTURES = Path(__file__).parent / "fixtures"


def install(base, name):
    copy = base / name / "invest"
    shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns("__pycache__", "data", ".ruff_cache"))
    return copy


def run(installed, cwd, *argv, routes=(), data=True):
    """`data=False` leaves $INVEST_DATA unset, so the skill keeps its results where it does by default."""
    fixture = cwd / "routes.json"
    fixture.write_text(json.dumps(list(routes)))
    env = dict(os.environ, PYTHONPATH=str(FIXTURES), YF_HTTP_FIXTURE=str(fixture), YF_TEST_CACHE=str(cwd / "cache"), INVEST_DATA=str(cwd / "data"))
    if not data:
        env.pop("INVEST_DATA")
    proc = subprocess.run(["uv", "run", "--quiet", str(installed / "scripts" / "cli.py"), *argv], capture_output=True, text=True, env=env, cwd=cwd, timeout=600)
    assert "UNEXPECTED NETWORK" not in proc.stderr, proc.stderr
    return proc


@pytest.mark.parametrize("name", ["with space", "한국어 경로", "dollar$sign", "quote'mark"])
def test_the_installed_copy_runs_from_an_unrelated_directory(tmp_path, name):
    installed = install(tmp_path, name)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    proc = run(installed, cwd, "--help")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert proc.stdout.startswith("usage: cli.py")
    proc = run(installed, cwd, "history", "AAPL", "--period", "5d", routes=chart_routes())
    assert proc.returncode == 0, proc.stdout[:400] + proc.stderr[-800:]
    receipt = json.loads(proc.stdout)
    assert Path(receipt["file"]["path"]).is_file() and Path(receipt["receipt_path"]).parent.parent == cwd / "data" / "results"
    left = {p.name for p in (installed / "scripts").iterdir()} - {"__pycache__"}
    assert left == {"cli.py", "invest"}, "running the skill must not write a lock file or environment beside it"


def test_results_are_kept_in_the_skills_own_data_folder(tmp_path):
    """With no $INVEST_DATA, results land in <skill>/data/results whatever the cwd."""
    installed = install(tmp_path, "installed copy")
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    assert not (installed / "data").exists()
    proc = run(installed, cwd, "history", "AAPL", "--period", "5d", routes=chart_routes(), data=False)
    assert proc.returncode == 0, proc.stdout[:400] + proc.stderr[-800:]
    receipt = json.loads(proc.stdout)
    assert Path(receipt["receipt_path"]).resolve().parent.parent == (installed / "data" / "results").resolve()
    assert not (cwd / "data").exists()


def test_filing_documents_are_kept_in_the_skills_own_data_folder(tmp_path):
    """With no $INVEST_DATA, a filing document lands in <skill>/data/filings whatever the cwd."""
    installed = install(tmp_path, "installed copy")
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    body = cwd / "body.htm"
    body.write_bytes(b"<p><b>Item 1. Business</b></p><p>We make things.</p>")
    url = "https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019324000123/x.htm"
    route = {"host": "cdn.yahoofinance.com", "path": url.split(".com", 1)[1], "file": str(body), "headers": {"Content-Type": "text/html"}}
    proc = run(installed, cwd, "filing", url, routes=[route], data=False)
    assert proc.returncode == 0, proc.stdout[:400] + proc.stderr[-800:]
    path = Path(json.loads(proc.stdout)["results"][0]["path"])
    assert path.resolve().parent.parent == (installed / "data" / "filings").resolve() and path.is_file()
    assert not (cwd / "data").exists()
