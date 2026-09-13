"""The installed skill is the public boundary, independent of the repository."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required for installation verification")
def test_locked_skill_runs_outside_repository_with_korean_space_path(tmp_path):
    source = Path(__file__).resolve().parents[2] / ".claude/skills/finviz"
    target = tmp_path / "설치 위치" / "finviz"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    env = dict(os.environ, FINVIZ_STORE=str(tmp_path / "saved.sqlite3"))
    command = [
        "uv",
        "run",
        "--isolated",
        "--frozen",
        "--project",
        str(target),
        "python",
        str(target / "scripts/finviz.py"),
    ]
    result = subprocess.run([*command, "doctor", "--json"], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "ok"
    help_result = subprocess.run([*command, "screen", "--help"], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert help_result.returncode == 0, help_result.stderr
    assert (
        "Comma-separated native filters, e.g. sec_technology,cap_largeover; discover with catalog."
        in help_result.stdout
    )
    assert not (target / "references").exists()
