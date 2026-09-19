"""The declaration catalogue is the single source every other surface reads, so these check it against the parser and against itself."""
import subprocess
import sys

import pytest

from conftest import SCRIPTS, shape

sys.path.insert(0, str(SCRIPTS))

import leaves  # noqa: E402
import yfinance_cli as cli  # noqa: E402

PARSER, PARSERS = cli.build_parser()


def test_every_parser_leaf_has_a_declaration_and_every_declaration_has_a_parser():
    """A leaf without a declaration falls back to no default window and no recovery, which is how a leaf silently
    keeps the old behaviour after everything around it was rewritten."""
    assert set(PARSERS) == set(leaves.LEAVES)


def test_removed_leaves_are_absent_from_the_parser_and_from_schema():
    for gone in [("company", "sustainability"), ("market", "status"), ("fund", "bond"), ("fund", "rating")]:
        assert gone not in leaves.LEAVES
        assert gone not in PARSERS
    search = PARSERS["search", ""]
    dataset = next(a for a in search._actions if a.dest == "dataset")
    assert "nav" not in dataset.choices


@pytest.mark.parametrize("key", sorted(leaves.LEAVES), ids=lambda k: f"{k[0]} {k[1]}".strip())
def test_each_leaf_declares_a_purpose_and_a_reachable_narrowing(key):
    item = leaves.LEAVES[key]
    assert item.purpose and item.purpose[0].isupper() and item.purpose.endswith(".")
    options = {s for action in PARSERS[key]._actions for s in action.option_strings}
    for named in item.narrow:
        for flag in named.split("/"):
            flag = flag if flag.startswith("--") else "--" + flag
            assert flag in options, f"{item.path} declares {named} but its parser has no {flag}"


@pytest.mark.parametrize("key", sorted(leaves.LEAVES), ids=lambda k: f"{k[0]} {k[1]}".strip())
def test_a_leaf_with_a_default_row_window_declares_which_end_a_limit_keeps(key):
    """`recent` is the one declaration that cannot be re-derived from the data, and getting it backwards is silent:
    the call succeeds and returns the wrong end of the series."""
    item = leaves.LEAVES[key]
    if item.limit is not None or item.recent:
        assert item.limit_keeps()
        assert item.recent in (True, False)


@pytest.mark.parametrize("key", sorted(leaves.LEAVES), ids=lambda k: f"{k[0]} {k[1]}".strip())
def test_no_unit_contract_is_stated_as_prose_instead(key):
    """The scale of a field belongs in `units`, where a reader meets it beside the value, not in a warning list that
    only protects the fields someone happened to enumerate."""
    item = leaves.LEAVES[key]
    for note in item.gotchas:
        lowered = note.lower()
        if "percent" in lowered or "ratio" in lowered:
            assert item.units, f"{item.path} describes a scale in prose but declares no units"


def test_units_use_only_the_declared_vocabulary():
    allowed_scale = {"ratio", "percent", "millions", "unverified"}
    allowed_kind = {"rate", "currency", "multiple", "weight", "count", "shares", "per_share"}
    for item in leaves.LEAVES.values():
        for field, contract in item.units.items():
            assert set(contract) <= {"scale", "kind", "inverted", "as_of"}, (item.path, field)
            assert contract.get("scale", "ratio") in allowed_scale, (item.path, field)
            assert contract.get("kind") in allowed_kind, (item.path, field)


def test_the_two_hundred_fold_scale_collisions_are_declared_on_both_sides():
    """The same measurement on two scales is the trap a value cannot reveal on its own: 0.0452 and 4.52 are both
    plausible surprises, so each side has to say which one it is."""
    assert leaves.get("analysts", "history").units["surprisePercent"]["scale"] == "ratio"
    assert leaves.get("calendar", "earnings").units["Surprise(%)"]["scale"] == "percent"
    quote = leaves.get("prices", "quote").units
    assert quote["dividendYield"]["scale"] == "percent"
    assert quote["trailingAnnualDividendYield"]["scale"] == "ratio"
    assert quote["fiftyTwoWeekChangePercent"]["scale"] == "percent"
    assert quote["52WeekChange"]["scale"] == "ratio"


def test_the_fund_multiples_are_declared_inverted():
    """Measured across SPY, QQQ, VTI, IWM and VOO the reciprocal matched each index's known multiple; printed as-is the
    value reads as an impossible P/E and nothing in the payload says why."""
    equity = leaves.get("fund", "equity").units
    for field in ("Price/Earnings", "Price/Book", "Price/Sales", "Price/Cashflow"):
        assert equity[field]["inverted"] is True


def test_quote_and_profile_ask_different_questions_of_one_assembly():
    quote, profile = set(leaves.get("prices", "quote").fields), set(leaves.get("company", "profile").fields)
    assert quote != profile
    assert quote - profile and profile - quote
    known = set(shape("info_keys"))
    assert (quote | profile) <= known | {"symbol"}, "a default projection names a field the real payload does not have"


def test_the_news_default_projection_uses_the_recorded_nesting():
    """A flat field name could not reach this payload at all, which is exactly what made the old recovery sentence
    impossible to follow."""
    item = leaves.get("company", "news")
    recorded = shape("news_item")
    for path in item.fields:
        node = recorded
        for part in path.split("."):
            assert isinstance(node, dict) and part in node, f"{path} is not in the recorded news shape"
            node = node[part]


def test_declared_date_fields_exist_in_the_recorded_frames():
    """A context that named the source's internal field rather than the returned column sent --fields at a name the
    output does not contain."""
    frames = shape("frames")
    for key, name in [(("calendar", "earnings"), "calendar_earnings"), (("holders", "institutional"), "holders_institutional"),
                      (("holders", "insider-transactions"), "holders_insider_transactions")]:
        item = leaves.get(*key)
        assert item.date_field in frames[name]["columns"], (item.path, item.date_field)


def test_schema_reports_a_leaf_without_repeating_the_shared_envelope():
    """The envelope, statuses and exit codes are the same for every leaf; carrying them per leaf is repetition that
    buries the leaf's own contract."""
    proc = subprocess.run([sys.executable, str(SCRIPTS / "yfinance_cli.py"), "schema", "prices", "history"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert '"envelope"' not in proc.stdout
    assert "schema with no scope" in proc.stdout
    assert len(proc.stdout.strip()) <= 6320, "a leaf's schema has become prose rather than structure"
