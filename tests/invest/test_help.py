"""The two-level --help: a root map that fits a screen, and one document per command that a caller can act on alone.

Each command document names its kinds, every argument it takes (tagged with the kinds that take it), the input unit of every argument that has one, the receipt's keys, the failure codes and the exit codes. Units of output fields are not here: each result carries its own.
"""
import os
import re
import subprocess
import sys

import pytest

from conftest import CLI, document
from invest import load

COMMANDS = ["search", "quote", "history", "company", "financials", "analysts", "holders", "fund", "options", "screen", "market", "calendar"]
FAILURES = {"not_found", "no_data", "not_applicable", "source_constraint", "rate_limited", "upstream", "invalid", "local_io"}


def arguments(command):
    lines = document(command).splitlines()
    start = lines.index("arguments:") + 1
    return [line.strip() for line in lines[start:lines.index("", start)]]


def test_the_root_map_fits_a_screen_and_names_every_command():
    root = document()
    assert len(root) <= 2500, len(root)
    listed = [line.split()[0] for line in root.splitlines()[root.splitlines().index("commands:") + 1:] if line.startswith("  ")][:len(COMMANDS)]
    assert listed == COMMANDS
    assert "COMMAND --help" in root and "exit codes: 0 ok" in root


@pytest.mark.parametrize("command", COMMANDS)
def test_each_command_document_is_short_and_self_contained(command):
    text = document(command)
    assert len(text) <= 4000, (command, len(text))
    for key in ("status", "receipt_path", "file", "units", "warnings", "notes", "results", "observed_at", "as_of", "coverage", "conditions", "trimmed", "projected"):
        assert re.search(rf"\b{key}\b", text), (command, key)
    failures = re.search(r"failures \(error\.code\): ([a-z_, ]+);", text)[1].split(", ")
    assert set(failures) <= FAILURES and {"rate_limited", "invalid", "local_io"} <= set(failures)
    assert "exit codes: 0 ok · 2 invalid · 4 local_io · 5 rate_limited · 6 upstream · 7 empty · 8 partial" in text
    assert "ratio (0.25 = 25%)" in text, "the unit vocabulary a receipt uses is explained"
    assert "--ttl-days N deletes saved results older than N days" in text


@pytest.mark.parametrize("command", COMMANDS)
def test_every_kind_and_argument_appears_once_in_its_own_document(command):
    text = document(command)
    kinds = load.kinds()[command]
    for kind in kinds:
        assert len(re.findall(rf"^  {re.escape(kind)}\s", text, re.M)) == 1, (command, kind)
    flags = [re.match(r"(--[\w-]+|[A-Z]+(?:\.\.\.)?)", line)[1] for line in arguments(command)]
    assert len(flags) == len(set(flags)), flags
    for other in COMMANDS:
        if other != command:
            assert not any(re.search(rf"^  {re.escape(k)}\s", document(other), re.M) for k in kinds if k not in load.kinds()[other]), (command, other)


@pytest.mark.parametrize("command,code", [("history", "source_constraint"), ("fund", "not_applicable"), ("quote", "not_found")])
def test_a_command_lists_the_failure_codes_it_can_return(command, code):
    assert code in re.search(r"failures \(error\.code\): ([a-z_, ]+);", document(command))[1].split(", ")


def test_an_argument_some_kinds_take_names_them():
    lines = {line.split()[0]: line for line in arguments("financials")}
    assert "[valuation]" in lines["--periods"]
    lines = {line.split()[0]: line for line in arguments("options")}
    assert "[chain]" in lines["--date"] and "[chain]" in lines["--side"]


@pytest.mark.parametrize("command,flag,unit", [("history", "--start", "YYYY-MM-DD"), ("history", "--end", "exclusive"), ("calendar", "--end", "inclusive"),
                                                ("history", "--timeout", "Seconds"), ("history", "--max-chars", "characters"),
                                                ("screen", "--query", "ratio (0.2 = 20%)"), ("screen", "--limit", "at most 250"),
                                                ("calendar", "--limit", "at most 100")])
def test_an_argument_with_an_input_unit_states_it(command, flag, unit):
    line = next(line for line in arguments(command) if line.startswith(flag))
    assert unit in line, line


@pytest.mark.parametrize("command", COMMANDS)
def test_no_document_carries_a_table_of_output_field_units(command):
    text = document(command)
    for field in ("dividendYield", "marketCap", "surprisePercent", "Surprise(%)", "impliedVolatility", "pctHeld", "Holding Percent"):
        assert field not in text, (command, field)


def test_help_makes_no_request_and_creates_no_data_folder(tmp_path):
    for scope in [[]] + [[c] for c in COMMANDS] + [["holders", "institutional"]]:
        proc = subprocess.run([sys.executable, str(CLI), *scope, "--help"], capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, INVEST_DATA=str(tmp_path / "data"), PYTHONPATH="", YF_HTTP_FIXTURE=""))
        assert proc.returncode == 0, (scope, proc.stderr[-300:])
    assert not (tmp_path / "data").exists()


def test_a_kinds_document_is_the_commands_document():
    proc = subprocess.run([sys.executable, str(CLI), "holders", "institutional", "--help"], capture_output=True, text=True, timeout=60)
    assert proc.stdout == document("holders")
