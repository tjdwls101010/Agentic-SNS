"""The parser is derived from each leaf's declaration: a selector a leaf cannot apply is refused, never silently ignored."""

import json

import pytest

STATEMENT = {"currency": "USD", "data": {"Period": ["TTM", "2025FY"], "Period End Date": ["", "10/31/2025"], "Total Revenue": ["7,372.00", "6,948.00"], "EPS (Diluted)": ["4.91", "4.57"]}}


@pytest.mark.parametrize("arguments", [["stock", "statement", "A", "--keys", "x"], ["schema", "--filter", "x"], ["doctor", "--limit", "1"], ["search", "A", "--keys", "x"]])
def test_a_selector_the_leaf_cannot_apply_is_refused_with_that_leafs_help(client, arguments):
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", STATEMENT)
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}])
    result = client.one(*arguments, code=2)
    assert result["error"]["code"] == "invalid_argument"
    path = " ".join(w for w in arguments[:2] if w in ("stock", "statement", "schema", "doctor", "search"))
    assert path + " --help" in result["error"]["fix"]


def test_a_limit_on_a_statement_or_a_map_is_applied(client):
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", STATEMENT)
    assert len(client.one("stock", "statement", "A", "--limit", "1")["data"]["items"]) == 1
    client.add("https://finviz.com/api/map_perf?t=sec&st=d1", {"nodes": {"AAPL": 1.0, "MSFT": -0.5, "NVDA": 2.0}, "subtype": "d1", "version": 15})
    assert len(client.one("market", "map", "--limit", "1")["data"]["tickers"]) == 1


def test_an_argument_error_after_a_leading_option_points_at_the_leaf(client, tmp_path):
    result = client.one("--store", str(tmp_path / "s.sqlite3"), "screen", "run", "--bogus", code=2)
    assert "screen run --help" in result["error"]["fix"]
    assert result["target"] == "screen run"


def test_a_transport_failure_names_the_environment_variable_that_limits_it(client):
    client.add("https://finviz.com/api/suggestions?input=A", "", exit=63)
    result = client.one("search", "A", code=6, extra_env={"FINVIZ_MAX_BYTES": "10"})
    assert result["error"]["code"] == "transport"
    assert "FINVIZ_MAX_BYTES=10" in result["error"]["fix"] and "--max-bytes" not in result["error"]["fix"]


# Sentences that justify a choice to its maintainer rather than tell the model what a value is and how to read it.
MAINTAINER_TELLS = ("could not hold", "so the choices are closed", "measured", "verified against", "on 2026-", "does not refuse an unknown")


def test_help_and_schema_describe_values_not_why_they_were_chosen(client):
    texts = [client.raw("--help", code=0).stdout, json.dumps(client.one("schema")["data"])]
    for group, leaves in client.one("schema")["data"]["groups"].items():
        for leaf in leaves:
            scope = [group] + ([leaf] if leaf else [])
            texts += [client.raw(*scope, "--help", code=0).stdout, json.dumps(client.one("schema", *scope)["data"])]
    found = [tell for tell in MAINTAINER_TELLS for text in texts if tell in text]
    assert not found, sorted(set(found))



def leaves(client):
    for group, names in client.one("schema")["data"]["groups"].items():
        for name in names:
            yield [group] + ([name] if name else [])


def test_every_leaf_documents_its_arguments_and_offers_record_selectors_only_with_records(client):
    operational = set(client.one("schema")["data"]["operational_options"])
    assert operational == {"--max-chars", "--store"}
    for scope in leaves(client):
        data = client.one("schema", *scope)["data"]
        help_text = client.raw(*scope, "--help", code=0).stdout
        assert "schema " + " ".join(scope) in help_text, scope
        for name, spec in data["arguments"].items():
            assert spec["help"] and "default" in spec, (scope, name)
            if name.startswith("--") and name not in operational:
                assert name in help_text, (scope, name)
        selectors = {"--filter", "--fields", "--start", "--limit"} & set(data["arguments"])
        assert selectors == ({"--filter", "--fields", "--start", "--limit"} if data.get("collections") else set()), scope
        assert ("--sections" in data["arguments"]) == (len(data.get("collections") or {}) > 1), scope


def test_operational_options_work_before_the_group_and_after_the_command(client, tmp_path):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}])
    store = str(tmp_path / "other.sqlite3")
    before = client.one("--store", store, "search", "A")
    after = client.one("search", "A", "--store", store)
    assert client.one("read", before["id"], "--store", store)["data"] == client.one("--store", store, "read", after["id"])["data"]
    assert client.one("doctor", "--store", store)["data"]["store"] == store
    assert client.one("schema", "--max-chars", "50000")["status"] == "ok"
    assert client.one("--limit", "1", "search", "A", code=2)["error"]["code"] == "invalid_argument"  # a record selector belongs to the leaf


def test_unscoped_schema_lists_commands_envelope_statuses_and_exit_codes(client):
    data = client.one("schema")["data"]
    assert {"search", "read", "doctor", "schema"} <= set(data["groups"])
    assert not {"open", "inspect"} & set(data["groups"])
    assert "views" not in data["groups"]["screen"] and "options" not in data["groups"]["groups"]
    assert data["exit_codes"]["too_large"] == 9 and data["exit_codes"]["partial"] == 8
    assert all(data["group_purposes"].values())
    assert client.one("schema", "nothing", code=2)["error"]["code"] == "invalid_scope"


def test_a_leaf_schema_names_its_collections_order_window_and_selectors(client):
    data = client.one("schema", "stock", "options")["data"]
    assert data["collections"]["contracts"]["selectors"] == ["--type", "--strikes"]
    assert data["context"]["current_expiry"]
    earnings = client.one("schema", "stock", "earnings")["data"]
    assert earnings["default_sections"] == ["quarterly"] and "reverse" in earnings["collections"]["revisions"]["order"]
    assert client.one("schema", "screen", "run")["data"]["source_paging"].startswith("--row")


def test_help_keeps_operational_text_at_the_root_and_parser_errors_stay_json(client):
    root_help = client.raw("--help", code=0).stdout
    assert "--max-chars" in root_help and "--max-bytes" not in root_help
    leaf_help = client.raw("stock", "earnings", "--help", code=0).stdout
    assert "finviz.py --help" in leaf_help and "Output budget in characters" not in leaf_help
    limits = client.one("doctor")["data"]["transport"]
    assert limits["timeout"] == 60 and limits["connect_timeout"] == 10 and limits["max_bytes"] == 16777216 and limits["set_by"] == "defaults"
    invalid = client.one("stock", "earnings", "A", "--sections", "bogus", code=2)
    assert invalid["error"]["code"] == "invalid_argument" and "quarterly" in invalid["error"]["fix"]
    assert client.raw("stock", "options", "A", "--type", "bogus", code=2).stderr == ""
    unknown = client.one("stock", "nosuchleaf", code=2)
    assert unknown["error"]["code"] == "invalid_argument" and "nosuchleaf" in unknown["error"]["message"]
    assert client.one("nosuchgroup", code=2)["error"]["code"] == "invalid_argument"


def test_a_collection_selector_for_a_section_not_shown_is_refused(client):
    refused = client.one("stock", "earnings", "A", "--fiscal-period", "2026Q4", code=2)
    assert "--sections revisions" in refused["error"]["fix"]
    several = client.one("stock", "overview", "A", "--sections", "snapshot,news", "--fields", "label", code=2)
    assert "--sections snapshot" in several["error"]["fix"]


def test_a_value_starting_with_a_dash_gets_a_fix_that_keeps_that_value(client):
    refused = client.one("screen", "run", "--sort", "-marketcap", code=2)
    assert "--sort=-marketcap" in refused["error"]["fix"]
    assert "--sort=-filingDate" in client.one("stock", "filings", "A", "--sort", "-filingDate", code=2)["error"]["fix"]
    assert "--sort=-" in " ".join(client.raw("screen", "run", "--help", code=0).stdout.split())
