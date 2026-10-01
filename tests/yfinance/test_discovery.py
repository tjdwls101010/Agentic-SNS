"""Discovery: --help is the only catalogue a reader has, so these check its documents against the parsers and the recorded shapes."""
import re

import pytest

from conftest import arguments, document, fact, groups, kind_block, section, shape, units

EVERY_KIND = [(group, kind) for group, kinds in groups().items() for kind in kinds]
IDS = [f"{g} {k}".strip() for g, k in EVERY_KIND]
TARGETS = {"search": ["apple"], ("market", "sector"): ["technology"], ("market", "industry"): ["semiconductors"],
           ("market", "summary"): [], "screen": [], "calendar": []}
SAMPLE = {"--from": "0123456789abcdef", "--start": "2024-01-02", "--end": "2024-01-09", "--period": "5d", "--frequency": None,
          "--periods": "1", "--date": "2024-01-19", "--field": "region", "--query": '{"operator":"EQ","operands":["region","us"]}',
          "--offset": "1", "--sort": "ticker", "--fields": "x", "--limit": "1", "--filter": "x"}
FLAGS_WITHOUT_VALUE = {"--repair", "--prepost", "--ascending", "--no-ascending", "--most-active"}


def targets(group, kind):
    return TARGETS.get((group, kind), TARGETS.get(group, ["AAPL"]))


def value(group, flag):
    """A value the parser accepts for this flag: the first choice the document lists, else a sample."""
    if flag in FLAGS_WITHOUT_VALUE:
        return []
    for _, typed, _ in arguments(group).get(flag, []):
        choices = re.search(r"\{([^}]*)\}", typed)
        if choices:
            return [choices[1].split(",")[0]]
    return [SAMPLE[flag]]


def parsed(cli, group, kind, flag):
    """Whether this kind's parser takes the flag: --max-chars 999 is refused only after every argument parsed, so no request is made either way."""
    base = [group, *([kind] if kind else []), *targets(group, kind)]
    if (group, kind) == ("screen", "run") and flag not in ("--query", "--preset"):
        base += ["--preset", "day_gainers"]
    proc, doc = cli(*base, flag, *value(group, flag), "--max-chars", "999", routes=[])
    message = doc["results"][0]["error"]["message"]
    assert proc.returncode == 2, proc.stdout[:300]
    if "--max-chars must be" in message:
        return True
    assert "unrecognized arguments" in message, message
    return False


def test_the_map_lists_every_kind_each_group_parser_accepts(cli):
    """A kind the map leaves out is one a reader never learns of, and one it lists that the parser refuses fails on first use."""
    for group, kinds in groups().items():
        if kinds == [""]:
            continue
        proc, doc = cli(group, "nope", routes=[])
        offered = re.search(r"choose from (.*)\)", doc["results"][0]["error"]["message"])[1]
        assert set(re.findall(r"[\w-]+", offered)) == set(kinds), group


def test_removed_commands_are_refused(cli):
    for argv in (["schema"], ["analysts", "summary", "AAPL"], ["market", "sectors"], ["company", "sustainability", "X"],
                 ["market", "status"], ["fund", "bond", "X"], ["fund", "rating", "X"], ["read", "0123456789abcdef", "--timeout", "5"]):
        proc, doc = cli(*argv, routes=[])
        assert proc.returncode == 2, argv
    assert "nav" not in arguments("search")["--dataset"][0][1]


@pytest.mark.parametrize("key", EVERY_KIND, ids=IDS)
def test_each_kind_states_its_purpose_and_what_its_values_mean(key):
    group, kind = key
    if kind:
        listed = {line.split()[0]: line.split(None, 1)[1] for line in section(document(group), "kinds")}
        purpose = listed[kind]
    else:
        purpose = document(group).splitlines()[1]
    assert purpose[0].isupper() and purpose.removesuffix(" (no --out)").endswith("."), purpose
    keeps = next(line for line in kind_block(group, kind) if line.startswith(("a limit keeps ", "--limit does not apply")))
    assert keeps.removeprefix("a limit keeps ") in ("the newest rows of a series the source publishes oldest first", "the first rows in source order",
                                                    "the first keys in sorted order", "--limit does not apply: the result is a single record")


@pytest.mark.parametrize("key", EVERY_KIND, ids=IDS)
def test_every_narrowing_a_kind_names_is_an_argument_it_takes(cli, key):
    """A recovery names these; one the parser refuses sends the reader into an invalid-argument error one step later."""
    group, kind = key
    named = fact(group, kind, "narrow with")
    for item in named.split(", ") if named else []:
        for flag in item.split("/"):
            assert parsed(cli, group, kind, flag if flag.startswith("--") else "--" + flag), (key, flag)


# Each kind's own options, written here rather than read from the document, so an option the document drops is noticed.
OWN = {("search", ""): {"--type", "--dataset"}, ("prices", "quote"): {"--from"}, ("company", "profile"): {"--from"},
       ("company", "shares"): {"--start", "--end"}, ("company", "news"): {"--tab"}, ("options", "chain"): {"--date", "--side"},
       ("screen", "presets"): {"--type"}, ("screen", "fields"): {"--type", "--field"}, ("screen", "values"): {"--type", "--field"},
       ("screen", "run"): {"--type", "--query", "--preset", "--offset", "--sort", "--ascending", "--no-ascending"},
       ("market", "summary"): {"--region"}, ("market", "sector"): {"--region", "--dataset"}, ("market", "industry"): {"--region", "--dataset"},
       ("calendar", "earnings"): {"--start", "--end", "--offset", "--most-active"}}
OWN.update({("prices", k): {"--start", "--end", "--period", "--interval", "--adjust", "--repair", "--prepost"} for k in ("history", "actions")})
OWN.update({("financials", k): {"--frequency", "--periods"} for k in ("income", "balance", "cashflow", "valuation")})
OWN.update({("calendar", k): {"--start", "--end", "--offset"} for k in ("economic", "ipo", "splits")})


@pytest.mark.parametrize("key", EVERY_KIND, ids=IDS)
def test_each_kind_documents_exactly_its_own_options(cli, key):
    group, kind = key
    documented = {flag for flag, entries in arguments(group).items() if flag.startswith("--")
                  and any(tags is None or kind in tags for tags, _, _ in entries)}
    assert documented == OWN.get(key, set()), key
    for flag in OWN.get(key, set()):
        assert parsed(cli, group, kind, flag), (key, flag)


@pytest.mark.parametrize("group", sorted(groups()))
def test_every_argument_is_taken_by_exactly_the_kinds_its_document_tags(cli, group):
    kinds = groups()[group]
    for flag, entries in arguments(group).items():
        if not flag.startswith("--"):
            continue
        taking = set(kinds) if any(tags is None for tags, _, _ in entries) else {k for tags, _, _ in entries for k in tags}
        for kind in kinds:
            assert parsed(cli, group, kind, flag) is (kind in taking), (group, kind, flag)


@pytest.mark.parametrize("key", EVERY_KIND, ids=IDS)
def test_no_unit_contract_is_stated_as_prose_instead(key):
    """The scale of a field belongs in `units`, where a reader meets it beside the value, not in a warning list that
    only protects the fields someone happened to enumerate."""
    group, kind = key
    for note in (line for line in kind_block(group, kind) if line.startswith("gotcha: ")):
        if "percent" in note.lower() or "ratio" in note.lower():
            assert units(group, kind), f"{group} {kind} describes a scale in prose but declares no units"


def test_units_use_only_the_declared_vocabulary():
    allowed_scale = {"ratio", "percent", "millions", "unverified"}
    allowed_kind = {"rate", "currency", "multiple", "weight", "count", "shares", "per_share"}
    for group, kind in EVERY_KIND:
        for field, contract in units(group, kind).items():
            assert set(contract) <= {"scale", "kind", "inverted", "as_of", "scale_by_quote_type"}, (group, kind, field)
            assert contract.get("scale", "ratio") in allowed_scale, (group, kind, field)
            assert set((contract.get("scale_by_quote_type") or {}).values()) <= allowed_scale, (group, kind, field)
            assert contract.get("kind") in allowed_kind, (group, kind, field)


def test_the_hundredfold_scale_collisions_are_declared_on_both_sides():
    """The same measurement on two scales is the trap a value cannot reveal on its own: 0.0452 and 4.52 are both
    plausible surprises, so each side has to say which one it is."""
    assert units("analysts", "history")["surprisePercent"]["scale"] == "ratio"
    assert units("calendar", "earnings")["Surprise(%)"]["scale"] == "percent"
    quote = units("prices", "quote")
    assert quote["dividendYield"]["scale"] == "percent"
    assert quote["trailingAnnualDividendYield"]["scale"] == "ratio"
    assert quote["fiftyTwoWeekChangePercent"]["scale"] == "percent"
    assert quote["52WeekChange"]["scale"] == "ratio" and quote["52WeekChange"]["scale_by_quote_type"] == {"INDEX": "percent"}


def test_the_fund_multiples_are_declared_inverted():
    equity = units("fund", "equity")
    for field in ("Price/Earnings", "Price/Book", "Price/Sales", "Price/Cashflow"):
        assert equity[field]["inverted"] is True


def test_quote_and_profile_ask_different_questions_of_one_assembly():
    quote = set(fact("prices", "quote", "default fields").split(", "))
    profile = set(fact("company", "profile", "default fields").split(", "))
    assert quote - profile and profile - quote
    known = set(shape("info_keys"))
    assert (quote | profile) <= known | {"symbol"}, "a default projection names a field the real payload does not have"


def test_the_news_default_projection_uses_the_recorded_nesting():
    """A flat field name could not reach this payload at all, which is exactly what made the old recovery sentence
    impossible to follow."""
    recorded = shape("news_item")
    for path in fact("company", "news", "default fields").split(", "):
        node = recorded
        for part in path.split("."):
            assert isinstance(node, dict) and part in node, f"{path} is not in the recorded news shape"
            node = node[part]


@pytest.mark.parametrize("group", sorted(groups()))
def test_a_group_and_each_of_its_kinds_print_the_same_document(cli, group):
    """Two levels of reading: the map, then one document that holds everything the group's kinds take and return."""
    for kind in groups()[group]:
        if kind:
            assert document(group, kind) == document(group), (group, kind)


ENVELOPE_KEYS = ["target", "id", "observed_at", "source_time", "stored_age_seconds", "status", "context", "conditions", "coverage", "continuation", "warnings", "data", "error"]
STATUS_NAMES = ["ok", "empty", "partial", "error", "not_attempted"]


def test_every_document_carries_the_output_contract_and_the_exit_codes():
    for text in [document(group) for group in groups()] + [document("read")]:
        output = section(text, "output")
        for key in ENVELOPE_KEYS:
            assert any(line.strip().startswith(key + ":") for line in output), key
        for status in STATUS_NAMES:
            assert any(line.strip().startswith(status + ":") for line in output), status
        listed = {name: int(code) for code, name in re.findall(r"(?m)^\s+(\d)\s+(\w+): \S", text)}
        assert listed == {"ok": 0, "invalid": 2, "local_io": 4, "rate_limited": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}
