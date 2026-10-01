"""Only HTTP transport is replaced; each subprocess runs real yfinance. Inline routes are synthetic examples, not recorded account traffic; their literal values establish the expected behavior independently of CLI output.

`shape` and `inflate` exist because the two halves of a fixture fail differently. Recording a whole real payload keeps
passing after Yahoo changes its shape, and inventing a flat payload assumes a world where --fields reaches everything —
which is how a recovery sentence that could never work was tested green. So the structure is recorded from one real
item and the volume is synthetic on top of it.
"""
import functools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

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


# ---- the documents --help prints -----------------------------------------------------------------------------------

HELP_STORE = tempfile.mkdtemp(prefix="yf-help-")  # --help opens no store; a separate one shows any that it did


@functools.lru_cache(maxsize=None)
def document(*scope):
    """What `[scope...] --help` prints. It is offline and creates nothing, so one call per scope serves every test."""
    proc = subprocess.run([sys.executable, str(CLI), *scope, "--help"], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, YF_STORE=str(Path(HELP_STORE) / "store")))
    assert proc.returncode == 0, proc.stdout[:400] + proc.stderr[-400:]
    return proc.stdout


def section(text, title):
    """The lines of one titled section (`title:` on its own line), up to the next blank line."""
    lines = text.splitlines()
    start = lines.index(title + ":") + 1
    end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
    return lines[start:end]


def groups():
    """{group: [kinds]} from the root map; a group whose only command is itself has the kind ''."""
    found = {}
    for line in section(document(), "commands"):
        typed = line.strip().split("  ")[0]
        group = typed.split()[0]
        if group == "read":
            continue
        listed = re.match(r"\S+ \{([^}]*)\}", typed)
        found[group] = [k.split()[0] for k in re.split(r"[,|]", listed[1]) if k.strip()] if listed else [""]
    return found


def kind_block(group, kind):
    """The lines under a kind's `[kind]` header in its group's document, up to the next header."""
    lines = document(group).splitlines()
    start = lines.index(f"[{kind or group}]") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    return [line.strip() for line in lines[start:end]]


def fact(group, kind, label):
    """The text after `label: ` in a kind's block, or None; a fact the block names as `same as [earlier]: …` is read from that kind."""
    block = kind_block(group, kind)
    found = next((line[len(label) + 2:] for line in block if line.startswith(label + ": ")), None)
    for line in block if found is None else []:
        same = re.match(r"same as \[([^\]]+)\]: (.*)", line)
        if same and label in same[2].split(", "):
            return fact(group, "" if same[1] == group else same[1], label)
    return found


def units(group, kind):
    found = fact(group, kind, "units")
    return json.loads(found) if found else {}


def arguments(group):
    """{flag or positional: (kinds it is tagged with, or None for every kind, the rest of the line)} from a group's arguments section."""
    found = {}
    for line in section(document(group), "arguments"):
        if line.strip().startswith("exactly one of"):
            continue
        typed, rest = line.strip().split("  ", 1)
        tagged = re.match(r"\[([^\]]*)\] (.*)", rest)
        kinds = tagged[1].split(", ") if tagged else None
        for name in re.findall(r"(?:^|, )(--[\w-]+)", typed) or [typed.split()[0]]:  # every spelling, --no-ascending included
            found.setdefault(name, []).append((kinds, typed, tagged[2] if tagged else rest))
    return found
