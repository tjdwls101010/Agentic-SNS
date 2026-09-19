import json
import re


def test_search_returns_candidates_and_saved_observation_can_be_reread(client):
    source = [{"ticker": "A", "company": "Agilent Technologies Inc", "exchange": "NYSE", "newField": 17}]
    client.add("https://finviz.com/api/suggestions?input=Agilent", source)
    result = client.one("search", "Agilent")
    assert result["status"] == "ok"
    assert result["target"] == "Agilent"
    assert result["data"] == source
    assert result["source"]["url"].endswith("input=Agilent")
    assert result["source"]["http_status"] == 200
    assert "headers" not in result["source"]
    saved = client.one("read", result["id"], "--pointer", "/data/0")
    assert saved["data"]["ticker"] == "A"
    assert saved["source"]["url"].endswith("input=Agilent")
    raw = client.one("read", result["id"], "--raw")
    assert json.loads(raw["data"]) == source


def test_http_failure_keeps_raw_response_and_reports_recovery(client):
    client.add("https://finviz.com/api/suggestions?input=ZZZZ", "not found page", status=404)
    doc = client.run("search", "ZZZZ", code=6)
    result = doc["results"][0]
    assert doc["status"] == "error" and result["status"] == "error"
    assert result["error"]["code"] == "http_error" and "fix" in result["error"]
    assert "data" not in result
    assert client.one("read", result["id"], "--raw")["data"] == "not found page"


def test_access_restriction_reports_retry_after_and_exit_5(client):
    client.add("https://finviz.com/api/suggestions?input=Agilent", "", status=429, headers={"Retry-After": "30"})
    result = client.one("search", "Agilent", code=5)
    assert result["error"]["code"] == "access_restricted"
    assert "Retry-After=30" in result["error"]["message"]


def test_redirect_to_external_host_is_refused_and_internal_redirect_keeps_requested_url(client):
    client.add("https://finviz.com/api/suggestions?input=Out", "", status=302, headers={"Location": "https://evil.example/x"})
    result = client.one("search", "Out", code=2)
    assert result["error"]["code"] == "unsupported_url"
    client.add("https://finviz.com/api/suggestions?input=In", "moved along", status=301, headers={"Location": "/api/suggestions?input=IN"})
    client.add("https://finviz.com/api/suggestions?input=IN", [{"ticker": "IN"}])
    result = client.one("search", "In")
    assert result["source"]["url"].endswith("input=IN")
    assert result["source"]["requested_url"].endswith("input=In")
    hop = result["source"]["redirects"][0]
    assert hop["url"] == "https://finviz.com/api/suggestions?input=In" and hop["http_status"] == 301
    assert client.one("read", hop["id"], "--raw")["data"] == "moved along"  # every received response is saved, the chain included


def test_selection_filters_fields_and_limits_records_and_rejects_unknown_fields(client):
    source = [{"ticker": "A", "company": "Agilent", "exchange": "NYSE"}, {"ticker": "AA", "company": "Alcoa", "exchange": "NYSE"}, {"ticker": "AAL", "company": "American Airlines", "exchange": "NASD"}]
    client.add("https://finviz.com/api/suggestions?input=A", source)
    result = client.one("--filter", "nyse", "--fields", "ticker", "--limit", "1", "search", "A")
    assert result["data"] == [{"ticker": "A"}]
    assert result["coverage"] == {"received": 3, "shown": 1, "exhaustive": False}
    result = client.one("search", "A", "--fields", "symbol", code=2)
    assert result["error"]["code"] == "invalid_fields" and "ticker" in result["error"]["fix"]


def test_oversized_output_becomes_too_large_error_with_saved_observation(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A", "company": "x" * 300}])
    doc = client.run("--max-chars", "700", "search", "A", code=9)
    error = doc["results"][0]["error"]
    assert error["code"] == "too_large"
    assert "--limit" in error["fix"] and "read " + doc["results"][0]["id"] in error["fix"]
    tiny = client.raw("--max-chars", "250", "search", "A", code=9)
    assert len(tiny.stdout.strip()) <= 250  # the replacement document obeys the budget it is reporting on
    smallest = json.loads(tiny.stdout)["results"][0]
    assert smallest["id"] and "--max-chars" in smallest["error"]["fix"]  # down to a saved id and the size that fits
    assert client.one("read", doc["results"][0]["id"], "--pointer", "/data/0/ticker")["data"] == "A"


def test_an_input_error_is_not_hidden_behind_the_size_of_the_payload_it_rejected(client):
    """finalize kept the unselected payload on an error result, so the real diagnosis lost to too_large at the default budget."""
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A" * 40, "company": "x" * 900} for _ in range(30)])
    result = client.one("search", "A", "--fields", "bogus", code=2)
    assert result["error"]["code"] == "invalid_fields"
    assert "ticker" in result["error"]["fix"] and "company" in result["error"]["fix"]
    assert "data" not in result


def test_a_too_large_fix_sizes_its_own_slice_from_the_document_it_could_not_send(client):
    """A constant --limit 20 is not a recovery when twenty records are what overflowed."""
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "T%d" % n, "company": "x" * 1500} for n in range(40)])
    error = client.run("search", "A", code=9)["results"][0]  # twenty of these records are themselves over the budget
    slice_command = re.search(r"read (\w+) --pointer (\S+) --start (\d+) --limit (\d+)", error["error"]["fix"])
    assert slice_command, error["error"]["fix"]
    recovered = client.one("read", slice_command[1], "--pointer", slice_command[2], "--start", slice_command[3], "--limit", slice_command[4])
    assert recovered["status"] == "ok" and recovered["data"]


def test_invalid_pointer_and_unknown_id_are_input_errors(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}])
    saved = client.one("search", "A")["id"]
    assert client.one("read", saved, "--pointer", "/data/9", code=2)["error"]["code"] == "invalid_pointer"
    assert client.one("read", "nope", code=2)["error"]["code"] == "unknown_id"
    sliced = client.one("read", saved, "--pointer", "/data", "--start", "0", "--limit", "1")
    assert sliced["selection"] == {"pointer": "/data", "start": 0, "received": 1, "shown": 1} and sliced["data"] == [{"ticker": "A"}]
    assert client.one("read", saved, "--pointer", "/data", "--limit", "0", code=7)["selection"]["shown"] == 0
    pointers = {e["pointer"]: e["type"] for e in client.one("inspect", saved)["data"]}
    assert pointers["/data"] == "list" and pointers["/data/0/ticker"] == "str"


def test_raw_reading_is_sliceable_by_character_range_and_names_the_next_window(client):
    """A raw response larger than the budget is one string: --start/--limit cut containers, so only a character range reaches it."""
    body = json.dumps([{"ticker": "A", "company": "x" * 5000}])
    client.add("https://finviz.com/api/suggestions?input=A", body)
    saved = client.one("search", "A")["id"]
    head = client.one("read", saved, "--raw", "--chars", "0-1000")
    assert head["data"] == body[:1000]
    assert head["selection"] == {"pointer": "/raw", "start": 0, "received": len(body), "shown": 1000}
    assert head["continuation"] == {"chars": "1000-2000"}
    tail = client.one("read", saved, "--raw", "--chars", str(len(body) - 10) + "-")
    assert tail["data"] == body[-10:] and "continuation" not in tail
    windows, start = [], 0
    while start is not None:
        window = client.one("--max-chars", "2000", "read", saved, "--raw", "--chars", str(start) + "-" + str(start + 1000))
        windows.append(window["data"])
        start = int(window["continuation"]["chars"].split("-")[0]) if "continuation" in window else None
    assert "".join(windows) == body
    oversized = client.run("--max-chars", "800", "read", saved, "--raw", code=9)["results"][0]
    assert "--chars" in oversized["error"]["fix"]


def test_doctor_runs_offline(client):
    result = client.one("doctor")
    assert result["data"]["problems"] == []
    assert result["data"]["store"] == str(client.store)


def test_verification_page_on_a_json_endpoint_is_access_restricted(client):
    client.add("https://finviz.com/api/suggestions?input=A", '<html><head><title>Just a moment...</title></head><body><form id="challenge-form"></form></body></html>')
    result = client.one("search", "A", code=5)
    assert result["error"]["code"] == "access_restricted"


def test_rejected_redirect_still_saves_the_received_response(client):
    client.add("https://finviz.com/api/suggestions?input=Out", "moved", status=302, headers={"Location": "https://evil.example/x"})
    result = client.one("search", "Out", code=2)
    assert result["error"]["code"] == "unsupported_url" and result["id"]
    assert client.one("read", result["id"], "--raw")["data"] == "moved"


def test_read_hides_headers_unless_pointed_at_and_accepts_the_root_pointer(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}], headers={"Set-Cookie": "secret=1", "Retry-After": "5"})
    saved = client.one("search", "A")["id"]
    whole = client.one("read", saved)
    assert "headers" not in whole["data"]["source"] and whole["data"]["data"] == [{"ticker": "A"}]
    root = client.one("read", saved, "--pointer", "/")
    assert root["data"]["data"] == [{"ticker": "A"}]
    headers = client.one("read", saved, "--pointer", "/source/headers")["data"]
    assert headers["retry-after"] == "5"
    pointers = [e["pointer"] for e in client.one("inspect", saved)["data"]]
    assert pointers[0] == "/data" and "/source/headers" in pointers


def test_local_storage_failures_stay_inside_the_json_contract(client, tmp_path):
    (tmp_path / "adir").mkdir()
    doc = client.run("--store", str(tmp_path / "adir"), "doctor", code=6)
    assert doc["results"][0]["error"]["code"] == "local_io"
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", "<html></html>")
    blocked = tmp_path / "file.txt"
    blocked.write_text("x")
    result = client.one("screen", "run", "--out", str(blocked / "rows.jsonl"), code=6)
    assert result["error"]["code"] == "local_io"


def test_reading_an_empty_saved_response_is_empty_not_an_argument_error(client):
    client.add("https://finviz.com/api/suggestions?input=A", "", status=429, headers={"Retry-After": "5"})
    failed = client.one("search", "A", code=5)
    assert client.one("read", failed["id"], "--raw", code=7)["data"] == ""
