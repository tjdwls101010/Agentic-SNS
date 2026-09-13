import json

from sec import main


def test_help_schema_and_invalid_arguments_need_no_identity(capsys):
    assert main(["--help"]) == 0
    assert "company" in capsys.readouterr().out
    assert main(["schema", "--json"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["defaults"]["limit"] == 20
    assert schema["defaults"]["max_chars"] == 12000
    assert main(["filings", "--json"]) == 2
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "invalid_argument"
    assert error["fix"]


def test_doctor_identity_redaction_and_live_boundary(cli):
    assert cli("doctor") == (0, {"identity_configured": True, "connection": "not_checked", "requests_per_second": 2})
    cli.replies.append(("company_tickers_exchange.json", 200, {"fields": [], "data": []}, {}))
    code, result = cli("doctor", "--live")
    assert code == 0 and result["connection"] == "ok"
    assert len(cli.calls) == 1
    cli.identity.write_text('EDGAR_IDENTITY=""')
    code, result = cli("doctor")
    assert code == 2 and result["error"]["code"] == "identity_required"


def test_email_only_identity_is_valid(cli):
    cli.identity.write_text('EDGAR_IDENTITY="tests@example.org"')
    code, result = cli("doctor")
    assert code == 0
    assert result["identity_configured"] is True


def test_exact_ticker_and_ambiguous_name_candidates(cli):
    tickers = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"], [1, "Apple Other", "OTHER", "NYSE"]],
    }
    cli.replies.append(("company_tickers_exchange.json", 200, tickers, {}))
    code, result = cli("company", "aapl")
    assert code == 0
    assert result["items"][0]["cik"] == "0000320193"
    assert result["items"][0]["match"] == "exact_ticker"
    cli.replies.append(("company_tickers_exchange.json", 200, tickers, {}))
    cli.replies.append(
        (
            "search-index",
            200,
            {
                "hits": {
                    "total": {"value": 2, "relation": "eq"},
                    "hits": [
                        {
                            "_source": {
                                "ciks": ["0000320193", "0000000001"],
                                "display_names": ["Apple Inc.", "Apple Other"],
                            }
                        }
                    ],
                }
            },
            {},
        )
    )
    code, result = cli("company", "Apple")
    assert code == 0 and len(result["items"]) == 2
    assert result["selection_required"] is True
    assert cli.calls[-1].url.params["entityName"] == "Apple"


def test_filings_preserve_periods_amendments_and_historical_cursor(cli):
    recent = {
        "accessionNumber": ["0000320193-24-000123", "0000320193-24-000124"],
        "filingDate": ["2024-11-01", "2024-11-02"],
        "reportDate": ["2024-09-28", "2024-09-28"],
        "form": ["10-K", "10-K/A"],
        "primaryDocument": ["aapl.htm", "amend.htm"],
    }
    old = {
        "accessionNumber": ["0000320193-00-000001"],
        "filingDate": ["2000-02-01"],
        "reportDate": ["1999-12-31"],
        "form": ["10-K"],
        "primaryDocument": ["old.txt"],
    }
    cli.replies.append(
        (
            "CIK0000320193.json",
            200,
            {"cik": "320193", "filings": {"recent": recent, "files": [{"name": "CIK0000320193-submissions-001.json"}]}},
            {},
        )
    )
    code, first = cli("filings", "320193", "--form", "10-K", "--limit", "1")
    assert code == 0 and first["items"][0]["form"] == "10-K/A"
    assert first["items"][0]["reportDate"] == "2024-09-28"
    assert first["items"][0]["filingDate"] == "2024-11-02"
    code, second = cli("filings", "320193", "--form", "10-K", "--limit", "1", "--cursor", first["next_cursor"])
    assert code == 0 and second["items"][0]["form"] == "10-K"
    assert len(cli.calls) == 1
    cli.replies.append(("CIK0000320193-submissions-001.json", 200, old, {}))
    code, third = cli("filings", "320193", "--form", "10-K", "--limit", "1", "--cursor", second["next_cursor"])
    assert code == 0 and third["items"][0]["filingDate"] == "2000-02-01"
    assert third["remote_complete"] is True and third["next_cursor"] is None
    code, bad = cli("filings", "320193", "--form", "10-Q", "--limit", "1", "--cursor", first["next_cursor"])
    assert code == 2 and bad["error"]["code"] == "cursor_mismatch"


def test_search_original_response_preserves_document_ids_and_fixed_page(cli):
    from pathlib import Path

    body = (Path(__file__).parent / "fixtures/efts-live.json").read_bytes()
    cli.replies.append(("search-index", 200, body, {}))
    code, result = cli(
        "search",
        "competition",
        "--company",
        "320193",
        "--filed-from",
        "2024-01-01",
        "--filed-to",
        "2024-12-31",
        "--limit",
        "1",
    )
    assert code == 0
    assert result["total"] == {"value": 4, "relation": "eq"}
    assert result["items"][0]["_id"] == "0000320193-24-000123:aapl-20240928.htm"
    assert result["items"][0]["_source"]["period_ending"] == "2024-09-28"
    assert cli.calls[0].url.params["size"] == "100"
    assert cli.calls[0].url.params["sort"] == "desc"
    code, next_page = cli(
        "search",
        "competition",
        "--company",
        "320193",
        "--filed-from",
        "2024-01-01",
        "--filed-to",
        "2024-12-31",
        "--limit",
        "1",
        "--cursor",
        result["next_cursor"],
    )
    assert code == 0 and len(cli.calls) == 1
    assert next_page["items"][0]["_id"] == "0000320193-24-000081:aapl-20240629.htm"


def test_open_original_filing_index_preserves_exhibits_and_continuation(cli):
    from pathlib import Path

    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.html"
    cli.replies.append(
        ("-index.html", 200, (Path(__file__).parent / "fixtures/apple-index-live.html").read_bytes(), {})
    )
    code, result = cli("open", url, "--limit", "2")
    assert code == 0
    assert result["items"][0]["document"] == "aapl-20240928.htm"
    assert result["items"][1]["document_type"] == "EX-4.1"
    assert result["items"][1]["url"].endswith("/a10-kexhibit4109282024.htm")
    code, page = cli("open", url, "--limit", "2", "--cursor", result["next_cursor"])
    assert code == 0 and page["items"][0]["document_type"] == "EX-10.19"
    assert len(cli.calls) == 1
    code, failure = cli("open", "0000320193-24-000123")
    assert code == 2 and failure["error"]["code"] == "company_required"


def test_transport_rejects_nested_traversal_but_accepts_sec_xml_stylesheet_path(cli):
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/xslF345X05/ownership.xml"
    cli.replies.append(
        ("ownership.xml", 200, b"<ownership><value>1</value></ownership>", {"content-type": "application/xml"})
    )
    code, result = cli("open", url)
    assert code == 0 and result["format"] == "xml"
    for bad in [
        "https://evil.example/a",
        "http://www.sec.gov/Archives/edgar/data/1/000000000000000001/a.htm",
        "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/%252e%252e/a",
        "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/../a",
        "https://user@www.sec.gov/Archives/edgar/data/1/000000000000000001/a",
    ]:
        code, result = cli("open", bad)
        assert code == 2 and result["error"]["code"] == "unsafe_url"
    assert len(cli.calls) == 1


def test_remote_errors_retries_redirects_and_corrupt_cursors(cli):
    for status, payload, expected in [
        (403, b"denied", "access_denied"),
        (429, b"slow down", "rate_limited"),
        (200, {"error": {"reason": "window too large"}}, "remote_error"),
        (200, b"<html>Request Rate Threshold Exceeded</html>", "access_denied"),
        (200, {"error": None}, "remote_error"),
    ]:
        before = len(cli.calls)
        cli.replies.append(("company_tickers_exchange.json", status, payload, {}))
        code, result = cli("doctor", "--live")
        assert code == 2 and result["error"]["code"] == expected
        assert len(cli.calls) == before + 1
    cli.replies.extend(
        [
            ("company_tickers_exchange.json", 503, b"busy", {}),
            ("company_tickers_exchange.json", 200, {"fields": [], "data": []}, {}),
        ]
    )
    assert cli("doctor", "--live")[0] == 0
    cli.replies.append(("company_tickers_exchange.json", 302, b"", {"location": "https://evil.example/steal"}))
    code, result = cli("doctor", "--live")
    assert code == 2 and result["error"]["code"] == "unsafe_url"


def test_saved_search_integrity_and_partial_result_contract(cli):
    hit = {
        "_id": "0000320193-24-000123:exhibit.htm",
        "_source": {
            "adsh": "0000320193-24-000123",
            "form": "10-K",
            "file_date": "2024-11-01",
            "ciks": ["0000320193", "0000000001"],
            "display_names": ["Apple", "Co-filer"],
        },
    }
    other = {"_id": "0000320193-24-000123:main.htm", "_source": hit["_source"]}
    cli.replies.append(
        (
            "search-index",
            200,
            {"timed_out": True, "hits": {"total": {"value": 10000, "relation": "gte"}, "hits": [hit, other]}},
            {},
        )
    )
    code, result = cli("search", "risk", "--limit", "1")
    assert code == 0 and result["remote_complete"] is False
    assert result["total"]["relation"] == "gte" and result["timed_out"] is True
    assert len(result["items"][0]["document_urls"]) == 2
    assert result["unreturned_reason"] == "remote_timeout"
    cursor = result["next_cursor"]
    code, page = cli("search", "risk", "--limit", "1", "--cursor", cursor)
    assert code == 0 and page["items"][0]["_id"].endswith("main.htm")
    (cli.cache / result["sources"][0]["sha256"]).write_bytes(b"corrupted original")
    code, error = cli("search", "risk", "--limit", "1", "--cursor", cursor)
    assert code == 2 and error["error"]["code"] == "cache_corrupt"
    code, error = cli("search", "risk", "--limit", "1", "--cursor", "../escape")
    assert code == 2 and error["error"]["code"] == "invalid_cursor"


def test_company_name_results_exclude_unrelated_cofilers_and_expose_remote_pages(cli):
    from pathlib import Path

    cli.replies.append(
        ("company_tickers_exchange.json", 200, {"fields": ["cik", "name", "ticker", "exchange"], "data": []}, {})
    )
    cli.replies.append(
        ("search-index", 200, (Path(__file__).parent / "fixtures/company-name-live.json").read_bytes(), {})
    )
    code, result = cli("company", "Apple", "--limit", "1")
    assert code == 0 and result["items"][0]["cik"] == "0000320193"
    assert all("apple" in item["name"].lower() for item in result["items"])
    assert result["remote_complete"] is False
    assert result["next_cursor"] is not None


def test_help_schema_describe_every_public_option_without_internal_stage_prose(capsys):
    assert main(["schema", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    for name, command in result["commands"].items():
        assert command["description"]
        for option in command["options"]:
            assert option["help"], (name, option["names"])
        assert main([name, "--help"]) == 0
        help_text = capsys.readouterr().out
        assert "stage 3" not in help_text.lower()
        assert "Return structured JSON" in help_text
    assert main(["doctor", "--env-file"]) == 2
    text = capsys.readouterr().out
    assert "Fix:" in text


def test_invalid_dates_and_exact_accession_never_select_latest(cli):
    for option, value in [("--filed-from", "2024-02-30"), ("--report-to", "2024/09/28")]:
        code, result = cli("filings", "320193", option, value)
        assert code == 2 and result["error"]["code"] == "invalid_argument"
    assert not cli.calls
    code, result = cli("open", "not-an-accession", "--company", "320193")
    assert code == 2 and result["error"]["code"] == "invalid_accession"
    cli.replies.append(("0000320193-24-999999-index.html", 404, b"Not found", {}))
    code, result = cli("open", "0000320193-24-999999", "--company", "320193")
    assert code == 2 and result["error"]["code"] == "not_found"
    assert len(cli.calls) == 1


def test_filings_report_range_amendment_exclusion_and_original_source(cli):
    from pathlib import Path

    cli.replies.append(
        ("CIK0000320193.json", 200, (Path(__file__).parent / "fixtures/apple-live.json").read_bytes(), {})
    )
    code, result = cli(
        "filings",
        "320193",
        "--form",
        "10-K",
        "--filed-from",
        "2024-01-01",
        "--filed-to",
        "2024-12-31",
        "--report-from",
        "2024-09-28",
        "--report-to",
        "2024-09-28",
        "--amendments",
        "exclude",
    )
    assert code == 0
    assert [row["accessionNumber"] for row in result["items"]] == ["0000320193-24-000123"]
    assert result["remote_complete"] is True
    assert len(cli.calls) == 1


def test_search_remote_pages_deduplicate_documents_and_retain_new_page_time(cli):
    hits = [
        {
            "_id": f"0000320193-24-000123:exhibit-{i}.htm",
            "_source": {
                "adsh": "0000320193-24-000123",
                "form": "10-K",
                "file_date": "2024-11-01",
                "ciks": ["0000320193"],
            },
        }
        for i in range(100)
    ]
    cli.replies.append(("search-index", 200, {"hits": {"total": {"value": 102, "relation": "eq"}, "hits": hits}}, {}))
    code, result = cli("search", "risk", "--limit", "100")
    assert code == 0 and result["returned"] == 100
    new = {"_id": "0000320193-24-000123:new.htm", "_source": hits[0]["_source"]}
    cli.replies.append(
        ("search-index", 200, {"hits": {"total": {"value": 102, "relation": "eq"}, "hits": [hits[0], new]}}, {})
    )
    code, page = cli("search", "risk", "--limit", "100", "--cursor", result["next_cursor"])
    assert code == 0 and [h["_id"] for h in page["items"]] == ["0000320193-24-000123:new.htm"]
    assert cli.calls[-1].url.params["from"] == "100"
    assert cli.calls[-1].url.params["startdt"] == "2001-01-01"
    assert page["sources"][0] == result["sources"][0]
    assert page["sources"][1]["fetched_at"] > page["sources"][0]["fetched_at"]
    assert page["next_cursor"] is None


def test_processes_share_request_pacing_at_public_cli(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / ".claude/skills/sec/Scripts"
    identity = tmp_path / "test.env"
    identity.write_text('EDGAR_IDENTITY="tests@example.org"')
    program = """
import sys, time, httpx
sys.path.insert(0, sys.argv[1])
from sec import main
def handle(self, request):
    print('REQUEST_TIME', time.time())
    return httpx.Response(200, json={'fields': [], 'data': []})
httpx.HTTPTransport.handle_request = handle
raise SystemExit(main(['--env-file', sys.argv[2], '--cache-dir', sys.argv[3], 'doctor', '--live', '--json']))
"""
    jobs = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(script), str(identity), str(tmp_path / "cache")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    times = []
    for job in jobs:
        out, err = job.communicate(timeout=20)
        assert job.returncode == 0, err
        times.append(float(out.split("REQUEST_TIME ")[1].splitlines()[0]))
        assert "tests@example.org" not in out + err
    times.sort()
    assert all(b - a >= 0.45 for a, b in zip(times, times[1:]))


def test_empty_search_is_distinct_from_partial_and_cache_cursor_tampering(cli):
    cli.replies.append(
        ("search-index", 200, {"timed_out": False, "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}}, {})
    )
    code, result = cli("search", "no such evidence", "--sort", "relevance")
    assert code == 0 and result["items"] == [] and result["remote_complete"] is True
    assert result["timed_out"] is False and result["next_cursor"] is None
    assert "sort" not in cli.calls[0].url.params
    code, error = cli("search", "no such evidence", "--cursor", "f" * 64)
    assert code == 2 and error["error"]["code"] == "missing_snapshot"


def test_damaged_limiter_database_returns_recoverable_error(cli):
    cli.cache.mkdir()
    (cli.cache / "requests.sqlite3").write_bytes(b"not sqlite")
    code, result = cli("doctor")
    assert code == 2
    assert result["error"]["code"] == "cache_corrupt"
    assert result["error"]["fix"]


def test_short_remote_page_cannot_claim_exhaustive_when_total_is_a_lower_bound(cli):
    cli.replies.append(
        (
            "search-index",
            200,
            {"timed_out": False, "hits": {"total": {"value": 10000, "relation": "gte"}, "hits": []}},
            {},
        )
    )
    code, result = cli("search", "risk")
    assert code == 0
    assert result["remote_complete"] is False
    assert result["unreturned_reason"] == "incomplete_remote_page"


def test_search_window_stops_at_ten_thousand_remote_hits(cli):
    cursor = None
    result = None
    for page in range(100):
        hits = [
            {
                "_id": f"0000320193-24-000123:ex-{page * 100 + i}.htm",
                "_source": {
                    "adsh": "0000320193-24-000123",
                    "form": "10-K",
                    "file_date": "2024-11-01",
                    "ciks": ["0000320193"],
                },
            }
            for i in range(100)
        ]
        cli.replies.append(
            (
                "search-index",
                200,
                {"timed_out": False, "hits": {"total": {"value": 10000, "relation": "gte"}, "hits": hits}},
                {},
            )
        )
        args = ["search", "risk", "--limit", "100"] + (["--cursor", cursor] if cursor else [])
        code, result = cli(*args)
        assert code == 0 and result["returned"] == 100
        assert cli.calls[-1].url.params["from"] == str(page * 100)
        cursor = result["next_cursor"]
        if page < 99:
            assert cursor is not None
    assert len(cli.calls) == 100
    assert result["limit_reached"] is True and result["remote_complete"] is False
    assert result["unreturned_reason"] == "search_window_limit" and cursor is None


def test_legacy_sec_index_response_preserves_original_attachment_rows(cli):
    from pathlib import Path

    url = "https://www.sec.gov/Archives/edgar/data/1009672/0001564590-18-004771-index.html"
    cli.replies.append(("-index.html", 200, (Path(__file__).parent / "fixtures/filing-index.html").read_bytes(), {}))
    code, result = cli("open", url, "--limit", "2")
    assert code == 0
    assert result["items"][0]["document"] == "crr-10k_20171231.htm"
    assert result["items"][1]["document_type"] == "EX-10.16"
    assert result["items"][1]["size"] == 33917


def test_company_continuation_keeps_prior_timeout_and_lower_bound(cli):
    hit = {"_source": {"ciks": ["0000320193"], "display_names": ["Apple Inc."]}}
    cli.replies.append(("company_tickers_exchange.json", 200, {"fields": [], "data": []}, {}))
    cli.replies.append(
        (
            "search-index",
            200,
            {"timed_out": True, "hits": {"total": {"value": 10000, "relation": "gte"}, "hits": [hit] * 100}},
            {},
        )
    )
    code, first = cli("company", "Apple", "--limit", "1")
    assert code == 0 and first["timed_out"] is True
    cli.replies.append(
        (
            "search-index",
            200,
            {"timed_out": False, "hits": {"total": {"value": 10000, "relation": "gte"}, "hits": []}},
            {},
        )
    )
    code, second = cli("company", "Apple", "--limit", "1", "--cursor", first["next_cursor"])
    assert code == 0 and second["timed_out"] is True
    assert second["remote_complete"] is False
    assert second["unreturned_reason"] == "remote_timeout"


def test_default_filings_accept_original_xsl_primary_document_paths(cli):
    from pathlib import Path

    cli.replies.append(
        ("CIK0000320193.json", 200, (Path(__file__).parent / "fixtures/apple-live.json").read_bytes(), {})
    )
    code, result = cli("filings", "320193")
    assert code == 0 and result["returned"] == 20
    assert any("/xslF345X" in row.get("document_url", "") for row in result["items"])


def test_open_rejects_wrong_filing_body_and_same_host_redirect(cli):
    from pathlib import Path

    cli.replies.append(("-index.html", 200, (Path(__file__).parent / "fixtures/filing-index.html").read_bytes(), {}))
    code, result = cli("open", "0000320193-24-000123", "--company", "320193")
    assert code == 2 and result["error"]["code"] == "filing_mismatch"
    cli.replies.append(
        (
            "-index.html",
            302,
            b"",
            {"location": "https://www.sec.gov/Archives/edgar/data/1009672/0001564590-18-004771-index.html"},
        )
    )
    code, result = cli("open", "0000320193-24-000123", "--company", "320193")
    assert code == 2 and result["error"]["code"] == "filing_mismatch"
    assert len(cli.calls) == 2


def test_normal_json_access_denied_phrase_is_not_a_block_page(cli):
    hit = {
        "_id": "0000320193-24-000123:a.htm",
        "_source": {
            "adsh": "0000320193-24-000123",
            "form": "10-K",
            "file_date": "2024-11-01",
            "ciks": ["0000320193"],
            "file_description": "Access denied controls",
        },
    }
    cli.replies.append(("search-index", 200, {"hits": {"total": {"value": 1, "relation": "eq"}, "hits": [hit]}}, {}))
    code, result = cli("search", "access denied")
    assert code == 0
    assert result["items"][0]["_source"]["file_description"] == "Access denied controls"


def test_index_normalizes_legacy_txt_and_official_viewer_wrappers(cli):
    from pathlib import Path
    from lxml import html

    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.html"
    root = html.fromstring((Path(__file__).parent / "fixtures/apple-index-live.html").read_bytes())
    anchors = root.xpath('//table[contains(@class,"tableFile")]//a')
    anchors[0].set("href", "/Archives/edgar/data/320193/0000320193-24-000123.txt")
    anchors[1].set("href", "/ixviewer/doc/action?doc=/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm")
    cli.replies.append(("-index.html", 200, html.tostring(root), {}))
    code, result = cli("open", url)
    assert code == 0
    assert result["items"][0]["url"].endswith("/320193/0000320193-24-000123.txt")
    assert (
        result["items"][1]["url"]
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )


def test_same_remote_cursor_replays_first_received_page_without_refetch(cli):
    hits = [
        {
            "_id": f"0000320193-24-000123:d1-{i}.htm",
            "_source": {
                "adsh": "0000320193-24-000123",
                "form": "10-K",
                "file_date": "2024-11-01",
                "ciks": ["0000320193"],
            },
        }
        for i in range(100)
    ]
    cli.replies.append(("search-index", 200, {"hits": {"total": {"value": 101, "relation": "eq"}, "hits": hits}}, {}))
    code, first = cli("search", "risk", "--limit", "100")
    assert code == 0
    hit = {"_id": "0000320193-24-000123:d2.htm", "_source": hits[0]["_source"]}
    cli.replies.append(("search-index", 200, {"hits": {"total": {"value": 101, "relation": "eq"}, "hits": [hit]}}, {}))
    args = ["search", "risk", "--limit", "100", "--cursor", first["next_cursor"]]
    code, second = cli(*args)
    assert code == 0
    code, replay = cli(*args)
    assert code == 0 and replay == second
    assert len(cli.calls) == 2


def test_company_shard_failure_is_explicitly_partial(cli):
    cli.replies.append(
        (
            "search-index",
            200,
            {
                "timed_out": False,
                "_shards": {"failed": 1},
                "hits": {
                    "total": {"value": 1, "relation": "eq"},
                    "hits": [{"_source": {"ciks": ["0000320193"], "display_names": ["Apple Inc."]}}],
                },
            },
            {},
        )
    )
    code, result = cli("company", "Apple Inc.")
    assert code == 0
    assert result["remote_complete"] is False
    assert result["shards_failed"] == 1 and result["unreturned_reason"] == "shard_failure"


def test_schema_default_text_works_without_identity(capsys, tmp_path):
    assert main(['--env-file', str(tmp_path / 'missing.env'), 'schema']) == 0
    output = capsys.readouterr().out
    assert 'commands:' in output
    assert 'Error [' not in output
