"""Every received response is saved, and read shows it again with the original command's selectors, its status and its gaps."""

import json
import shlex

from pages import stock_overview, stock_section


def test_search_candidates_are_saved_and_read_again_without_a_request(client):
    source = [{"ticker": "A", "company": "Agilent Technologies Inc", "exchange": "NYSE", "newField": 17}]
    client.add("https://finviz.com/api/suggestions?input=Agilent", source)
    result = client.one("search", "Agilent")
    assert result["status"] == "ok" and result["target"] == "Agilent"
    assert result["data"] == {"candidates": source}
    assert result["source"]["url"].endswith("input=Agilent") and result["source"]["http_status"] == 200
    assert "headers" not in result["source"]
    client.responses.clear()
    again = client.one("read", result["id"])
    assert again["data"] == {"candidates": source} and again["observed_at"] == result["observed_at"]
    assert json.loads(client.one("read", result["id"], "--raw")["data"]) == source


def test_an_http_failure_keeps_the_raw_response_and_a_recovery(client):
    client.add("https://finviz.com/api/suggestions?input=ZZZZ", "not found page", status=404)
    doc = client.run("search", "ZZZZ", code=6)
    result = doc["results"][0]
    assert doc["status"] == "error" and result["error"]["code"] == "http_error" and result["error"]["fix"]
    assert "data" not in result
    assert client.one("read", result["id"], "--raw")["data"] == "not found page"


def test_an_access_restriction_reports_retry_after_and_exits_5(client):
    client.add("https://finviz.com/api/suggestions?input=Agilent", "", status=429, headers={"Retry-After": "30"})
    result = client.one("search", "Agilent", code=5)
    assert result["error"]["code"] == "access_restricted" and "Retry-After=30" in result["error"]["message"]


def test_a_redirect_off_finviz_is_refused_and_every_hop_is_saved(client):
    client.add("https://finviz.com/api/suggestions?input=Out", "moved", status=302, headers={"Location": "https://evil.example/x"})
    refused = client.one("search", "Out", code=2)
    assert refused["error"]["code"] == "unsupported_url" and refused["id"]
    assert client.one("read", refused["id"], "--raw")["data"] == "moved"
    client.add("https://finviz.com/api/suggestions?input=In", "moved along", status=301, headers={"Location": "/api/suggestions?input=IN"})
    client.add("https://finviz.com/api/suggestions?input=IN", [{"ticker": "IN"}])
    result = client.one("search", "In")
    assert result["source"]["url"].endswith("input=IN") and result["source"]["requested_url"].endswith("input=In")
    hop = result["source"]["redirects"][0]
    assert hop["url"] == "https://finviz.com/api/suggestions?input=In" and hop["http_status"] == 301
    assert client.one("read", hop["id"], "--raw")["data"] == "moved along"


def test_a_verification_page_on_a_json_endpoint_is_access_restricted(client):
    client.add("https://finviz.com/api/suggestions?input=A", '<html><head><title>Just a moment...</title></head><body><form id="challenge-form"></form></body></html>')
    assert client.one("search", "A", code=5)["error"]["code"] == "access_restricted"


def test_selection_filters_projects_and_limits_and_refuses_unknown_fields(client):
    source = [{"ticker": "A", "company": "Agilent", "exchange": "NYSE"}, {"ticker": "AA", "company": "Alcoa", "exchange": "NYSE"}, {"ticker": "AAL", "company": "American Airlines", "exchange": "NASD"}]
    client.add("https://finviz.com/api/suggestions?input=A", source)
    result = client.one("search", "A", "--filter", "nyse", "--fields", "ticker", "--limit", "1")
    assert result["data"] == {"candidates": [{"ticker": "A"}]}
    assert result["coverage"] == {"received": 3, "matched": 2, "shown": 1, "start": 0, "cut": "limit"}
    assert result["next"] == "read " + result["id"] + " --filter nyse --fields ticker --start 1 --limit 1"
    refused = client.one("search", "A", "--fields", "symbol", code=2)
    assert refused["error"]["code"] == "invalid_fields" and "ticker" in refused["error"]["fix"]


def test_an_input_error_is_not_hidden_behind_the_size_of_the_payload_it_rejected(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A" * 40, "company": "x" * 900} for _ in range(30)])
    result = client.one("search", "A", "--fields", "bogus", code=2)
    assert result["error"]["code"] == "invalid_fields" and "company" in result["error"]["fix"] and "data" not in result


def test_read_applies_the_original_commands_selectors_and_refuses_the_request_arguments(client):
    source = [{"ticker": "T%d" % n, "note": "keep" if n < 3 else "drop"} for n in range(40)]
    client.add("https://finviz.com/api/suggestions?input=A", source)
    saved = client.one("search", "A")["id"]
    one = client.one("read", saved, "--limit", "1")
    assert one["data"]["candidates"] == [source[0]] and one["coverage"] == {"received": 40, "matched": 40, "shown": 1, "start": 0, "cut": "limit"}
    kept = client.one("read", saved, "--filter", "keep", "--fields", "ticker")
    assert kept["data"]["candidates"] == [{"ticker": "T0"}, {"ticker": "T1"}, {"ticker": "T2"}]
    none = client.one("read", saved, "--filter", "NEVER_MATCH_THIS")
    assert none["status"] == "ok" and none["coverage"]["matched"] == 0
    refused = client.one("read", saved, "--type", "put", code=2)
    assert refused["error"]["code"] == "invalid_argument" and "search" in refused["error"]["fix"] and "--filter" in refused["error"]["fix"]
    assert client.one("read", "nope", code=2)["error"]["code"] == "unknown_id"


def test_the_raw_response_reads_in_character_windows_and_the_budget_windows_it_too(client):
    body = json.dumps([{"ticker": "A", "company": "x" * 5000}])
    client.add("https://finviz.com/api/suggestions?input=A", body)
    saved = client.one("search", "A")["id"]
    head = client.one("read", saved, "--raw", "--chars", "0-1000")
    assert head["data"] == body[:1000] and head["chars"] == {"received": len(body), "start": 0, "shown": 1000}
    assert head["next"] == "read " + saved + " --raw --chars 1000-"
    tail = client.one("read", saved, "--raw", "--chars", str(len(body) - 10) + "-")
    assert tail["data"] == body[-10:] and "next" not in tail
    first = client.run("--max-chars", "1500", "read", saved, "--raw", code=8)
    text, doc = first["results"][0]["data"], first
    while doc.get("continuation"):
        doc = client.run(*shlex.split(doc["continuation"]), code=None)
        assert len(json.dumps(doc, ensure_ascii=False, separators=(",", ":"))) <= 1500
        text += doc["results"][0]["data"]
    assert text == body
    assert client.one("read", saved, "--chars", "0-10", code=2)["error"]["code"] == "invalid_argument"


def test_reading_an_empty_saved_response_is_empty_not_an_argument_error(client):
    client.add("https://finviz.com/api/suggestions?input=A", "", status=429, headers={"Retry-After": "5"})
    failed = client.one("search", "A", code=5)
    assert client.one("read", failed["id"], "--raw", code=7)["data"] == ""


def test_a_failed_observation_keeps_its_error_when_read_and_offers_its_raw_response(client):
    client.add("https://finviz.com/stock?t=A&ty=c", "<html><body>changed layout</body></html>")
    failed = client.one("stock", "overview", "A", code=6)
    assert failed["error"]["code"] == "structure_changed"
    again = client.one("read", failed["id"], code=6)
    assert again["status"] == "error" and again["error"]["code"] == "structure_changed" and "read " + failed["id"] + " --raw" in again["error"]["fix"]
    assert "changed layout" in client.one("read", failed["id"], "--raw")["data"]
    refused = client.one("read", failed["id"], "--fields", "label", code=2)
    assert "read " + failed["id"] + " --raw" in refused["error"]["fix"]


def test_a_partial_or_empty_observation_stays_so_when_read(client):
    client.add("https://finviz.com/stock?t=A&ty=c", stock_overview(metrics=[("M%d" % n, "1", "d" * 80) for n in range(30)]))
    partial = client.run("--max-chars", "2500", "stock", "overview", "A", code=8)
    assert client.run("--max-chars", "2500", "read", partial["results"][0]["id"], code=8)["status"] == "partial"
    client.add("https://finviz.com/stock?t=A&ty=si", stock_section([]))
    empty = client.one("stock", "short-interest", "A", code=7)
    assert client.one("read", empty["id"], code=7)["status"] == "empty"


def test_an_option_chain_is_read_again_with_its_own_collection_selectors(client):
    contracts = [{"strike": strike, "type": kind, "iv": 1.0, "delta": 0.5} for strike in (20, 60, 150, 155, 900) for kind in ("call", "put")]
    client.add("https://finviz.com/stock?t=A&ty=oc", stock_section({"expiries": ["2026-10-16"], "currentExpiry": "2026-10-16", "options": contracts, "lastClose": 152.0}))
    near = client.one("stock", "options", "A", "--strikes", "2")
    assert near["coverage"] == {"received": 10, "matched": 4, "shown": 4, "start": 0}
    client.responses.clear()
    puts = client.one("read", near["id"], "--type", "put", "--fields", "strike,iv", "--strikes", "0")
    assert puts["data"]["contracts"] == [{"strike": s, "iv": 1.0} for s in (20, 60, 150, 155, 900)]
    assert puts["data"]["current_expiry"] == "2026-10-16"  # the context travels with the records


def test_one_overview_observation_answers_every_section_without_another_request(client):
    client.add("https://finviz.com/stock?t=A&ty=c", stock_overview())
    first = client.one("stock", "overview", "A")
    assert first["data"]["other_sections"] == {"news": 1, "ratings": 1, "insiders": 1}
    client.responses.clear()
    news = client.one("read", first["id"], "--section", "news")
    assert news["data"]["news"][0]["title"] == "Keysight stock underperforms" and news["observed_at"] == first["observed_at"]
    assert "snapshot" not in news["data"] and news["data"]["ticker"] == "A"
    assert client.one("read", first["id"], "--section", "flows", code=7)["coverage"] == {"flows": {"absent": True}}
    assert client.one("read", first["id"], "--section", "nope", code=2)["error"]["code"] == "invalid_argument"


def test_several_ids_are_read_together_only_from_the_same_command(client):
    for ticker in ("A", "B"):
        client.add("https://finviz.com/stock?t=%s&ty=c" % ticker, stock_overview(ticker=ticker))
    doc = client.run("stock", "overview", "A", "B")
    ids = [r["id"] for r in doc["results"]]
    both = client.run("read", *ids, "--section", "news")
    assert [r["target"] for r in both["results"]] == ["A", "B"]
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}])
    other = client.one("search", "A")["id"]
    assert client.one("read", ids[0], other, code=2)["error"]["code"] == "invalid_argument"


def test_local_storage_failures_stay_inside_the_json_contract(client, tmp_path):
    (tmp_path / "adir").mkdir()
    doc = client.run("--store", str(tmp_path / "adir"), "doctor", code=6)
    assert doc["results"][0]["error"]["code"] == "local_io"
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", "<html></html>")
    blocked = tmp_path / "file.txt"
    blocked.write_text("x")
    assert client.one("screen", "run", "--out", str(blocked / "rows.jsonl"), code=6)["error"]["code"] == "local_io"


def test_doctor_runs_offline_and_reports_the_store(client):
    result = client.one("doctor")
    assert result["data"]["problems"] == [] and result["data"]["store"] == str(client.store)


def test_replaying_several_targets_keeps_a_failed_one_failed(client):
    client.add("https://finviz.com/stock?t=A&ty=c", stock_overview())
    client.add("https://finviz.com/stock?t=APPL&ty=c", "missing", status=404)
    doc = client.run("stock", "overview", "A", "APPL", code=8)
    again = client.run("read", *[r["id"] for r in doc["results"]], code=8)
    assert again["status"] == "partial" and [r["status"] for r in again["results"]] == ["ok", "error"]
