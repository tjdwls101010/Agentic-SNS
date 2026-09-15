"""The installed skill runs from its own locked environment at a path with Korean and spaces, silently."""

from pathlib import Path
import shutil
import subprocess


SKILL = Path(__file__).resolve().parents[2] / ".claude/skills/finviz"


def test_locked_skill_runs_outside_repository_with_korean_space_path(tmp_path):
    target = tmp_path / "설치 위치" / "finviz"
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    command = ["uv", "run", "-q", "--frozen", "--project", str(target), "python", str(target / "scripts/finviz.py"), "--store", str(tmp_path / "s.sqlite3"), "doctor"]
    proc = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    assert '"problems":[]' in proc.stdout
