"""The CLI seam: each test runs cli.py in a subprocess with real yfinance and only the HTTP transport replaced.

Recorded routes (fixtures/yahoo/, written by scenarios/invest/record_yahoo.py) are Yahoo's own answers, so a test's expected values are read from those responses, never from the CLI's output. Inline routes are synthetic and their literals are the expectation. A test reads what a caller reads: the printed receipt, the receipt.json it names and the result file it names.
"""
import csv
import functools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/invest/scripts/cli.py"
FIXTURES = Path(__file__).parent / "fixtures"
SHAPES = FIXTURES / "shapes"


def recorded(*names):
    """The routes of one or more recorded fixtures, in order."""
    found = []
    for name in names:
        found += json.loads((FIXTURES / "yahoo" / f"{name}.json").read_text(encoding="utf-8"))["routes"]
    return found


def source(name, path_part, index=0):
    """The JSON body of the index-th recorded response whose path contains path_part: what Yahoo sent, for reading expected values."""
    bodies = [r.get("json") for r in recorded(name) if path_part in r["path"]]
    return bodies[index]


class Run:
    """One CLI run: exit code, printed receipt, the receipt.json and result file it names, and the requests it made."""

    def __init__(self, proc, log):
        self.proc, self.code = proc, proc.returncode
        self.doc = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
        self.requests = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    @functools.cached_property
    def receipt(self):
        return json.loads(Path(self.doc["receipt_path"]).read_text(encoding="utf-8"))

    @functools.cached_property
    def rows(self):
        """result.csv as dicts of strings, the way a caller's csv reader sees it."""
        with open(self.doc["file"]["path"], newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    @functools.cached_property
    def records(self):
        return json.loads(Path(self.doc["file"]["path"]).read_text(encoding="utf-8"))

    def result(self, i=0):
        return self.doc["results"][i]

    def __repr__(self):
        return f"exit {self.code}: {self.proc.stdout[:600]} {self.proc.stderr[-600:]}"


@pytest.fixture
def cli(tmp_path):
    def run(*args, routes=(), now=None, data=None, env=None, timeout=120):
        run_dir = Path(tempfile.mkdtemp(dir=tmp_path))
        fixture, log = run_dir / "routes.json", run_dir / "requests.jsonl"
        fixture.write_text(json.dumps(list(routes)))
        environment = dict(os.environ, PYTHONPATH=str(FIXTURES), YF_HTTP_FIXTURE=str(fixture), YF_HTTP_LOG=str(log),
                           YF_TEST_CACHE=str(run_dir / "cache"), INVEST_DATA=str(data or (tmp_path / "data")))
        environment.pop("YF_FIXTURE_NOW", None)
        if now:
            environment["YF_FIXTURE_NOW"] = now
        environment.update(env or {})
        proc = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=environment, timeout=timeout)
        assert "UNEXPECTED NETWORK" not in proc.stderr, proc.stderr[-1500:]
        return Run(proc, log)
    return run


def shape(name):
    return json.loads((SHAPES / f"{name}.json").read_text())


def inflate(template, index=0, text="x" * 40):
    """One synthetic record with the recorded nesting and key names."""
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


HELP_DATA = tempfile.mkdtemp(prefix="invest-help-")


@functools.lru_cache(maxsize=None)
def document(*scope):
    """What `[scope...] --help` prints; offline, and it opens no data folder."""
    proc = subprocess.run([sys.executable, str(CLI), *scope, "--help"], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, INVEST_DATA=str(Path(HELP_DATA) / "data")))
    assert proc.returncode == 0, proc.stdout[:400] + proc.stderr[-400:]
    return proc.stdout
