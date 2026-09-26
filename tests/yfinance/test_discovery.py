"""Discovery: --help and schema are the only catalogue a reader has, so these check it against itself and the recorded shapes."""
import functools
import json
import os
import re
import subprocess
import sys
import tempfile

import pytest

from conftest import CLI, shape


STORE = tempfile.mkdtemp(prefix="yf-discovery-")


@functools.lru_cache(maxsize=None)
def schema(*scope):
    """schema is offline, so one call per scope serves every test that reads it."""
    env = dict(os.environ, YF_STORE=STORE)  # every command opens its store; keep that away from the user's cache
    proc = subprocess.run([sys.executable, str(CLI), "schema", *scope], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stdout[:400]
    return json.loads(proc.stdout)["results"][0]["data"]


def catalogue(cli=None):
    return schema()["commands"]


def leaf_keys(cli=None):
    return [(group, leaf) for group, leaves in catalogue().items() for leaf in leaves]


def describe(cli, group, leaf):
    return schema(group, *([leaf] if leaf else []))


EVERY_LEAF = leaf_keys()
IDS = [f"{g} {leaf}".strip() for g, leaf in EVERY_LEAF]


def test_every_schema_leaf_is_a_parser_command_and_every_parser_command_is_in_schema(cli):
    """A leaf without a declaration falls back to no default window and no recovery, which is how a leaf silently
    keeps the old behaviour after everything around it was rewritten."""
    for group, leaves in catalogue(cli).items():
        if list(leaves) == [""]:
            continue
        proc = cli(group, "--help", raw=True)
        offered = re.search(r"\{([^}]*)\}", proc.stdout)[1].split(",")
        assert set(offered) == set(leaves), group


def test_removed_leaves_are_absent_from_the_parser_and_from_schema(cli):
    commands = catalogue(cli)
    for group, gone in [("company", "sustainability"), ("market", "status"), ("fund", "bond"), ("fund", "rating")]:
        assert gone not in commands[group]
        proc, doc = cli(group, gone, "X")
        assert proc.returncode == 2
    assert "nav" not in describe(cli, "search", "")["arguments"]["--dataset"]["choices"]


@pytest.mark.parametrize("key", EVERY_LEAF, ids=IDS)
def test_each_leaf_declares_a_purpose_and_a_reachable_narrowing(cli, key):
    described = describe(cli, *key)
    purpose = described["description"]
    assert purpose[0].isupper() and purpose.endswith(".")
    for named in described.get("narrowing") or []:
        for flag in named.split("/"):
            flag = flag if flag.startswith("--") else "--" + flag
            assert flag in described["arguments"] or flag in schema()["common_arguments"], f"{described['command']} declares {named} but has no {flag}"


@pytest.mark.parametrize("key", EVERY_LEAF, ids=IDS)
def test_a_leaf_with_a_default_row_window_declares_which_end_a_limit_keeps(cli, key):
    """Which end a limit keeps cannot be re-derived from the data, and getting it backwards is silent: the call
    succeeds and returns the wrong end of the series."""
    window = describe(cli, *key)["default_window"]
    assert window["limit_keeps"] in ("the newest rows of a series the source publishes oldest first", "the first rows in source order")


@pytest.mark.parametrize("key", EVERY_LEAF, ids=IDS)
def test_no_unit_contract_is_stated_as_prose_instead(cli, key):
    """The scale of a field belongs in `units`, where a reader meets it beside the value, not in a warning list that
    only protects the fields someone happened to enumerate."""
    described = describe(cli, *key)
    for note in described.get("gotchas") or []:
        lowered = note.lower()
        if "percent" in lowered or "ratio" in lowered:
            assert described.get("units"), f"{described['command']} describes a scale in prose but declares no units"


def test_units_use_only_the_declared_vocabulary(cli):
    allowed_scale = {"ratio", "percent", "millions", "unverified"}
    allowed_kind = {"rate", "currency", "multiple", "weight", "count", "shares", "per_share"}
    for key in leaf_keys(cli):
        described = describe(cli, *key)
        for field, contract in (described.get("units") or {}).items():
            assert set(contract) <= {"scale", "kind", "inverted", "as_of"}, (key, field)
            assert contract.get("scale", "ratio") in allowed_scale, (key, field)
            assert contract.get("kind") in allowed_kind, (key, field)


def test_the_hundredfold_scale_collisions_are_declared_on_both_sides(cli):
    """The same measurement on two scales is the trap a value cannot reveal on its own: 0.0452 and 4.52 are both
    plausible surprises, so each side has to say which one it is."""
    assert describe(cli, "analysts", "history")["units"]["surprisePercent"]["scale"] == "ratio"
    assert describe(cli, "calendar", "earnings")["units"]["Surprise(%)"]["scale"] == "percent"
    quote = describe(cli, "prices", "quote")["units"]
    assert quote["dividendYield"]["scale"] == "percent"
    assert quote["trailingAnnualDividendYield"]["scale"] == "ratio"
    assert quote["fiftyTwoWeekChangePercent"]["scale"] == "percent"
    assert quote["52WeekChange"]["scale"] == "ratio"


def test_the_fund_multiples_are_declared_inverted(cli):
    equity = describe(cli, "fund", "equity")["units"]
    for field in ("Price/Earnings", "Price/Book", "Price/Sales", "Price/Cashflow"):
        assert equity[field]["inverted"] is True


def test_quote_and_profile_ask_different_questions_of_one_assembly(cli):
    quote = set(describe(cli, "prices", "quote")["default_window"]["fields"])
    profile = set(describe(cli, "company", "profile")["default_window"]["fields"])
    assert quote - profile and profile - quote
    known = set(shape("info_keys"))
    assert (quote | profile) <= known | {"symbol"}, "a default projection names a field the real payload does not have"


def test_the_news_default_projection_uses_the_recorded_nesting(cli):
    """A flat field name could not reach this payload at all, which is exactly what made the old recovery sentence
    impossible to follow."""
    recorded = shape("news_item")
    for path in describe(cli, "company", "news")["default_window"]["fields"]:
        node = recorded
        for part in path.split("."):
            assert isinstance(node, dict) and part in node, f"{path} is not in the recorded news shape"
            node = node[part]


def test_schema_reports_a_leaf_without_repeating_the_shared_envelope(cli):
    """The envelope, statuses and exit codes are the same for every leaf; carrying them per leaf is repetition that
    buries the leaf's own contract."""
    proc = cli("schema", "prices", "history", raw=True)
    assert proc.returncode == 0, proc.stderr
    assert '"envelope"' not in proc.stdout
    assert "schema (no scope)" in proc.stdout
    assert len(proc.stdout.strip()) <= 4000, "a leaf's schema has become prose rather than structure"
