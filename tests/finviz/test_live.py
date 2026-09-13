"""Opt-in checks against anonymous Finviz; no account or SEC original requests."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/finviz/scripts/finviz.py"
CASES = [
    ["lookup", "Agilent"],
    ["catalog", "screen"],
    ["screen", "--filter", "sec_technology"],
    ["stock", "A"],
    *[
        ["stock", "A", "--section", s]
        for s in [
            "earnings",
            "dividends",
            "revenue",
            "forecast",
            "short-interest",
            "options",
            "filings",
            "income",
            "balance",
            "cashflow",
        ]
    ],
    ["stock", "SPY"],
    ["prices", "A"],
    ["groups"],
    ["groups", "--view", "110"],
    *[["market", k] for k in ["futures", "forex", "crypto"]],
    ["map", "--type", "geo"],
    ["map", "--bubbles"],
    ["calendar", "earnings"],
    ["calendar", "dividends"],
    ["calendar", "economic"],
    ["calendar", "season-preview"],
    ["news"],
    ["news", "--view", "6"],
    ["news", "--pulse", "284262"],
    ["insiders"],
    ["catalog", "map"],
]


@pytest.mark.live
@pytest.mark.parametrize("arguments", CASES, ids=lambda x: " ".join(x))
def test_anonymous_source_provides_usable_data(arguments, tmp_path):
    env = dict(os.environ, FINVIZ_STORE=str(tmp_path / "observations.sqlite3"))
    result = subprocess.run(
        [sys.executable, str(CLI), *arguments, "--json", "--full", "--timeout", "30"],
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout[:1500] + result.stderr
    observation = json.loads(result.stdout)
    assert observation["status"] == "ok", observation["errors"]
    assert observation["source"]["received_complete"] is True
    assert observation["data"] is not None
    if arguments == ["map", "--type", "geo"]:
        assert observation["data"]["classification"]["children"]
    if arguments == ["catalog", "screen"]:
        assert any(c["id"] == "fs_sec" for c in observation["data"]["controls"])
        assert observation["data"]["initial"]["route-init-data"]["tableSettings"]["columnsMap"]
    if arguments == ["stock", "A"]:
        eps = [m for m in observation["data"]["metrics"] if m["label"] == "EPS next Y"]
        assert len(eps) == 2
        assert len({m["definition"] for m in eps}) == 2
