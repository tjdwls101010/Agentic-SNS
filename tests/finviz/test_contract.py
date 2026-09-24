"""The parser is derived from each leaf's declaration: a selector a leaf cannot apply is refused, never silently ignored."""

import json

import pytest

STATEMENT = {"currency": "USD", "data": {"Period": ["TTM", "2025FY"], "Period End Date": ["", "10/31/2025"], "Total Revenue": ["7,372.00", "6,948.00"], "EPS (Diluted)": ["4.91", "4.57"]}}


@pytest.mark.xfail(strict=True, reason="D1: shared selectors are attached to every leaf")
@pytest.mark.parametrize("arguments", [["stock", "statement", "A", "--keys", "x"], ["schema", "--filter", "x"], ["doctor", "--limit", "1"], ["search", "A", "--keys", "x"]])
def test_a_selector_the_leaf_cannot_apply_is_refused_with_that_leafs_help(client, arguments):
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", STATEMENT)
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}])
    result = client.one(*arguments, code=2)
    assert result["error"]["code"] == "invalid_argument"
    path = " ".join(w for w in arguments[:2] if w in ("stock", "statement", "schema", "doctor", "search"))
    assert path + " --help" in result["error"]["fix"]


@pytest.mark.xfail(strict=True, reason="D1: --limit is a no-op on mapping-shaped results")
def test_a_limit_on_a_statement_or_a_map_is_applied(client):
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", STATEMENT)
    assert len(client.one("stock", "statement", "A", "--limit", "1")["data"]["items"]) == 1
    client.add("https://finviz.com/api/map_perf?t=sec&st=d1", {"nodes": {"AAPL": 1.0, "MSFT": -0.5, "NVDA": 2.0}, "subtype": "d1", "version": 15})
    assert len(client.one("market", "map", "--limit", "1")["data"]["performance"]) == 1


@pytest.mark.xfail(strict=True, reason="D10: an option before GROUP breaks the leaf lookup of the argument error")
def test_an_argument_error_after_a_leading_option_points_at_the_leaf(client, tmp_path):
    result = client.one("--store", str(tmp_path / "s.sqlite3"), "screen", "run", "--bogus", code=2)
    assert "screen run --help" in result["error"]["fix"]
    assert result["target"] == "screen run"


@pytest.mark.xfail(strict=True, reason="D9: the transport fix names flags that moved to environment variables")
def test_a_transport_failure_names_the_environment_variable_that_limits_it(client):
    client.add("https://finviz.com/api/suggestions?input=A", "", exit=63)
    result = client.one("search", "A", code=6, extra_env={"FINVIZ_MAX_BYTES": "10"})
    assert result["error"]["code"] == "transport"
    assert "FINVIZ_MAX_BYTES=10" in result["error"]["fix"] and "--max-bytes" not in result["error"]["fix"]


# Sentences that justify a choice to its maintainer rather than tell the model what a value is and how to read it.
MAINTAINER_TELLS = ("could not hold", "so the choices are closed", "measured", "verified against", "on 2026-", "does not refuse an unknown")


@pytest.mark.xfail(strict=True, reason="D12: help and schema carry maintainer rationale")
def test_help_and_schema_describe_values_not_why_they_were_chosen(client):
    texts = [client.raw("--help", code=0).stdout, json.dumps(client.one("schema")["data"])]
    for group, leaves in client.one("schema")["data"]["groups"].items():
        for leaf in leaves:
            scope = [group] + ([leaf] if leaf else [])
            texts += [client.raw(*scope, "--help", code=0).stdout, json.dumps(client.one("schema", *scope)["data"])]
    found = [tell for tell in MAINTAINER_TELLS for text in texts if tell in text]
    assert not found, sorted(set(found))

