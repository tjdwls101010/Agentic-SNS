"""Opt-in checks of the public CLI against SEC, using an isolated cache and the configured identity."""

import json
import os

import pytest

from sec import main

pytestmark = pytest.mark.skipif(
    os.environ.get("SEC_LIVE") != "1", reason="Set SEC_LIVE=1 to use the configured SEC identity."
)


def test_identified_live_company_filing_search_and_index(tmp_path, capsys):
    def run(*args):
        code = main(["--cache-dir", str(tmp_path / "cache"), *args, "--json"])
        result = json.loads(capsys.readouterr().out)
        assert code == 0, result
        return result

    assert run("doctor", "--live")["connection"] == "ok"
    company = run("company", "AAPL")
    assert company["items"][0]["cik"] == "0000320193"
    filings = run("filings", "320193", "--form", "10-K", "--filed-from", "2024-01-01", "--filed-to", "2024-12-31")
    assert filings["items"][0]["accessionNumber"] == "0000320193-24-000123"
    assert filings["items"][0]["reportDate"] == "2024-09-28"
    search = run(
        "search",
        "competition",
        "--company",
        "320193",
        "--filed-from",
        "2024-01-01",
        "--filed-to",
        "2024-12-31",
        "--sort",
        "relevance",
    )
    assert search["returned"] >= 1 and search["items"][0]["_score"] > 0
    index = run("open", filings["items"][0]["index_url"])
    assert index["items"][0]["document"] == "aapl-20240928.htm"
    assert any(item["document_type"] == "EX-4.1" for item in index["items"])

    document = run("open", index["items"][0]["url"])
    assert document["status"] == "parsed" and document["snapshot_id"]
    empty_identity = tmp_path / "empty.env"
    empty_identity.write_text('EDGAR_IDENTITY=""')
    code = main(
        [
            "--cache-dir",
            str(tmp_path / "cache"),
            "--env-file",
            str(empty_identity),
            "find",
            document["snapshot_id"],
            "competition",
            "--json",
        ]
    )
    found = json.loads(capsys.readouterr().out)
    assert code == 0 and found["items"]
    match = found["items"][0]
    code = main(
        [
            "--cache-dir",
            str(tmp_path / "cache"),
            "--env-file",
            str(empty_identity),
            "read",
            document["snapshot_id"],
            "--position",
            match["position"],
            "--end",
            match["match_end"],
            "--json",
        ]
    )
    excerpt = json.loads(capsys.readouterr().out)
    assert code == 0 and excerpt["text"].casefold() == "competition"
