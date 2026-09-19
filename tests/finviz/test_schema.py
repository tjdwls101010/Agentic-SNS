"""The interface describes itself: schema, --help and the parser agree, and every argument is explained."""

import itertools


def test_unscoped_schema_lists_every_group_and_command_with_shared_options(client):
    data = client.one("schema")["data"]
    assert {"search", "read", "inspect", "doctor", "schema"} <= set(data["groups"])
    assert data["shared_options"]["--max-chars"]["default"] == 20000
    assert data["exit_codes"]["too_large"] == 9
    for group, purpose in data["group_purposes"].items():
        assert purpose


def test_every_command_documents_arguments_with_help_and_default_and_matches_its_help_text(client):
    unscoped = client.one("schema")["data"]
    groups, shared = unscoped["groups"], set(unscoped["shared_options"])
    for group, leaves in groups.items():
        for leaf in leaves:
            scope = [group] + ([leaf] if leaf else [])
            data = client.one("schema", *scope)["data"]
            assert data["output"], scope
            help_text = client.raw(*scope, "--help", code=0).stdout
            for name, spec in data["arguments"].items():
                assert spec["help"], (scope, name)
                assert "default" in spec, (scope, name)
                if name.startswith("--") and name not in shared:  # shared options are explained by finviz.py --help, not repeated per leaf
                    assert name in help_text, (scope, name)
            assert "schema " + " ".join(scope) in help_text, scope


def test_scoped_schema_rejects_unknown_command(client):
    assert client.one("schema", "nothing", code=2)["error"]["code"] == "invalid_scope"


def test_shared_options_work_before_the_group_and_after_the_command(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}, {"ticker": "AA"}])
    before = client.one("--limit", "1", "search", "A")["data"]
    after = client.one("search", "A", "--limit", "1")["data"]
    assert before == after == [{"ticker": "A"}]
    assert list(itertools.chain(before)) == before


def test_help_and_schema_disclose_shared_defaults_and_parser_errors_stay_in_the_json_contract(client):
    root_help = client.raw("--help", code=0).stdout
    assert "--max-chars" in root_help and "--max-bytes" not in root_help  # transport limits are the operator's, not a choice in the model's list
    leaf_help = client.raw("stock", "earnings", "--help", code=0).stdout
    assert "finviz.py --help" in leaf_help and "Maximum output characters" not in leaf_help  # named in the epilog, explained once at the root
    schema = client.one("schema", "stock", "earnings")["data"]
    assert schema["arguments"]["--max-chars"]["default"] == 20000
    limits = client.one("doctor")["data"]["transport"]
    assert limits["timeout"] == 60 and limits["connect_timeout"] == 10 and limits["max_bytes"] == 16777216
    assert limits["set_by"] == "defaults"
    invalid = client.one("stock", "earnings", "A", "--dataset", "bogus", code=2)
    assert invalid["error"]["code"] == "invalid_argument" and "invalid choice" in invalid["error"]["message"]
    assert client.raw("stock", "earnings", "A", "--dataset", "bogus", code=2).stderr == ""
    unknown = client.one("stock", "nosuchleaf", code=2)
    assert unknown["error"]["code"] == "invalid_argument" and "nosuchleaf" in unknown["error"]["message"]
    assert client.one("nosuchgroup", code=2)["error"]["code"] == "invalid_argument"
