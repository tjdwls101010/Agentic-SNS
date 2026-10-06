"""`filing URL...` through the CLI: Yahoo's copy received from recorded bytes, saved as a text file and its map under data/filings, and one receipt for every document.

The originals are the SEC bytes in fixtures/documents; the transport answers Yahoo's CDN path with them, so what is checked is what a caller reads: the printed receipt, the files it names, and the requests made.
"""
import gzip
import json
import os
from pathlib import Path
import time

import pytest

DOCUMENTS = Path(__file__).parent / "fixtures" / "documents"
CDN = "cdn.yahoofinance.com"
NBIS = "https://cdn.yahoofinance.com/prod/sec-filings/0001513845/000110465926094844/nbis-20260812xex99d2.htm"
NBIS_SEC = "https://www.sec.gov/Archives/edgar/data/1513845/000110465926094844/nbis-20260812xex99d2.htm"
APPLE = "https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019324000123/aapl-20240928.htm"
OTHER = "https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019324000123/other.htm"
TARGET_KEYS = ["target", "status", "source", "path", "map_path", "lines", "chars"]


def original(name):
    meta = json.loads((DOCUMENTS / "provenance.json").read_text())[name]
    raw = (DOCUMENTS / meta.get("storage", name)).read_bytes()
    return gzip.decompress(raw) if meta.get("compression") == "gzip" else raw


@pytest.fixture
def copy(tmp_path):
    """A route serving `body` (bytes, or the name of an original) at a CDN URL."""
    def route(url, body=b"", status=200, headers=None, **extra):
        path = tmp_path / f"body-{abs(hash((url, status)))}"
        path.write_bytes(original(body) if isinstance(body, str) else body)
        return {"host": CDN, "path": url.split(CDN, 1)[1], "file": str(path), "status": status,
                "headers": headers or {"Content-Type": "text/html"}, **extra}
    return route


def test_a_document_is_saved_as_its_text_file_map_source_and_original(cli, copy):
    run = cli("filing", NBIS, routes=[copy(NBIS, "nbis.html")])
    assert run.code == 0, run
    assert list(run.doc) == ["status", "command", "receipt_path", "warnings", "results", "trimmed"]
    result = run.result()
    assert list(result)[:7] == TARGET_KEYS and result["status"] == "ok" and result["source"] == NBIS_SEC
    folder = Path(result["path"]).parent
    assert sorted(p.name for p in folder.iterdir()) == ["document.txt", "map.json", "original.htm", "source.json"]
    assert (folder / "original.htm").read_bytes() == original("nbis.html")
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert text.startswith(f"SOURCE {NBIS_SEC} | Yahoo copy {NBIS} | sha256 ") and result["lines"] == text.count("\n") and result["chars"] == len(text)
    source = json.loads((folder / "source.json").read_text())
    assert (source["source"], source["fetch"], source["bytes"]) == (NBIS_SEC, NBIS, len(original("nbis.html")))
    assert [e["title"] for e in result["contents"]] == [e["title"] for e in json.loads(Path(result["map_path"]).read_text())["contents"]]
    assert (result["tables"], result["images"]) == (79, 0) and result["reused"] is False


def test_the_archive_url_is_fetched_from_yahoos_copy(cli, copy):
    run = cli("filing", NBIS_SEC, routes=[copy(NBIS, "nbis.html")])
    assert run.code == 0, run
    assert [(r["host"], r["path"]) for r in run.requests] == [(CDN, NBIS.split(CDN, 1)[1])]


def test_opening_the_same_document_again_reuses_its_folder(cli, copy):
    first = cli("filing", NBIS, routes=[copy(NBIS, "nbis.html")])
    second = cli("filing", NBIS_SEC, routes=[copy(NBIS, "nbis.html")])
    assert first.code == second.code == 0
    assert second.result()["path"] == first.result()["path"] and second.result()["reused"] is True


def test_changed_bytes_are_saved_as_a_new_document(cli, copy):
    first = cli("filing", OTHER, routes=[copy(OTHER, b"<p>First version.</p>")])
    second = cli("filing", OTHER, routes=[copy(OTHER, b"<p>Second version.</p>")])
    assert first.result()["path"] != second.result()["path"]
    assert Path(first.result()["path"]).read_text().endswith("First version.\n")


def test_the_full_receipt_is_saved_and_names_its_id(cli, copy):
    run = cli("filing", NBIS, routes=[copy(NBIS, "nbis.html")])
    assert run.receipt["id"] == Path(run.doc["receipt_path"]).parent.name
    assert run.receipt["results"][0]["contents"] == run.result()["contents"]


@pytest.mark.parametrize("url", ["https://example.com/a.htm", "https://www.sec.gov/cgi-bin/browse-edgar?CIK=320193", NBIS + "#part"])
def test_a_url_this_skill_does_not_read_is_refused_before_any_request_and_nothing_is_saved(cli, tmp_path, url):
    run = cli("filing", url)
    assert run.code == 2 and run.result()["error"]["code"] == "invalid" and run.requests == []
    assert not (tmp_path / "data").exists()


def test_filing_needs_a_url(cli):
    run = cli("filing")
    assert run.code == 2 and "URL" in run.result()["error"]["message"]


def test_yahoos_spreadsheet_is_unsupported_without_a_request(cli):
    run = cli("filing", "https://s3.amazonaws.com/finance-pri-uw2/sec-filings/0000320193/000032019324000123/Financial_Report.xlsx")
    assert run.code == 7 and run.result()["error"]["code"] == "unsupported" and run.requests == []


@pytest.mark.parametrize("body,content_type", [(b"%PDF-1.7 rest", "application/pdf"), (b"PK\x03\x04 zip", "application/octet-stream")], ids=["pdf", "zip"])
def test_a_binary_copy_is_unsupported_and_nothing_is_saved_for_it(cli, copy, tmp_path, body, content_type):
    run = cli("filing", OTHER, routes=[copy(OTHER, body, headers={"Content-Type": content_type})])
    assert run.code == 7 and run.result()["error"]["code"] == "unsupported"
    assert not (tmp_path / "data" / "filings").exists()


def test_a_copy_with_no_text_is_an_empty_document(cli, copy):
    run = cli("filing", OTHER, routes=[copy(OTHER, b"")])
    assert run.code == 7 and run.result()["error"]["code"] == "empty_document"


@pytest.mark.parametrize("status,code,exit,requests", [(404, "not_found", 6, 1), (403, "upstream", 6, 1), (429, "upstream", 6, 1), (302, "upstream", 6, 1),
                                                       (503, "upstream", 6, 2)])
def test_a_refusal_maps_to_its_code_and_only_a_server_fault_is_retried(cli, copy, status, code, exit, requests):
    run = cli("filing", OTHER, routes=[copy(OTHER, b"", status=status, headers={"Location": "https://elsewhere.test/"})])
    assert (run.code, run.result()["error"]["code"], len(run.requests)) == (exit, code, requests)
    assert run.result()["error"]["fix"]


def test_one_document_saved_and_one_missing_is_partial(cli, copy):
    run = cli("filing", NBIS, OTHER, routes=[copy(NBIS, "nbis.html"), copy(OTHER, b"", status=404)])
    assert run.code == 8 and [r["status"] for r in run.doc["results"]] == ["ok", "error"]


def test_an_unsupported_document_beside_an_empty_one_still_exits_seven(cli, copy):
    pdf = OTHER.replace("other.htm", "deck.pdf")
    run = cli("filing", OTHER, pdf, routes=[copy(OTHER, b""), copy(pdf, b"%PDF-1.7", headers={"Content-Type": "application/pdf"})])
    assert run.code == 7 and [r["error"]["code"] for r in run.doc["results"]] == ["empty_document", "unsupported"]


def test_a_document_whose_bytes_lost_characters_says_so_in_its_warnings(cli, copy):
    run = cli("filing", OTHER, routes=[copy(OTHER, b"<html><head><meta charset='utf-8'></head><body><p>caf\xe9</p></body></html>")])
    assert run.code == 0 and [w["code"] for w in run.result()["warnings"]] == ["encoding_loss"] and "encoding_loss" in run.result()["limits"]


# ---- the receipt within --max-chars ----------------------------------------------------------------------------------------

def test_a_small_budget_cuts_the_inside_lists_first_then_the_contents(cli, copy):
    whole = cli("filing", APPLE, "--max-chars", "200000", routes=[copy(APPLE, "apple.html")])
    assert whole.code == 0 and any("inside" in e for e in whole.result()["contents"]) and not whole.doc["trimmed"]
    size = len(json.dumps(whole.doc, ensure_ascii=False, separators=(",", ":")))
    # A margin beyond the one character a reused document saves ("reused":true is shorter than false).
    cut = cli("filing", APPLE, "--max-chars", str(size - 20), routes=[copy(APPLE, "apple.html")])
    assert cut.doc["trimmed"] is True and cut.result()["contents"] and not any("inside" in e for e in cut.result()["contents"])
    smaller = cli("filing", APPLE, "--max-chars", str(len(json.dumps(cut.doc, ensure_ascii=False, separators=(",", ":"))) - 20), routes=[copy(APPLE, "apple.html")])
    assert "contents" not in smaller.result() and list(smaller.result())[:7] == TARGET_KEYS
    assert Path(smaller.result()["map_path"]).is_file() and smaller.receipt["results"][0]["contents"]


def test_headings_are_cut_when_there_are_no_contents(cli, copy):
    body = "".join(f"<p><b>Heading number {i}</b></p><p>Body paragraph {i}.</p>" for i in range(40)).encode()
    whole = cli("filing", OTHER, "--max-chars", "200000", routes=[copy(OTHER, body)])
    assert whole.code == 0 and "contents" not in whole.result() and len(whole.result()["headings"]) == 40
    assert whole.result()["headings"][:2] == ["L2 Heading number 0", "L4 Heading number 1"]
    size = len(json.dumps(whole.doc, ensure_ascii=False, separators=(",", ":")))
    cut = cli("filing", OTHER, "--max-chars", str(size - 20), routes=[copy(OTHER, body)])
    assert cut.doc["trimmed"] is True and "headings" not in cut.result() and cut.result()["lines"] == 81


def test_the_smallest_receipt_keeps_every_target_status_and_error_code(cli, copy):
    run = cli("filing", NBIS, OTHER, "--max-chars", "700", routes=[copy(NBIS, "nbis.html"), copy(OTHER, b"", status=404)])
    assert run.code == 8 and run.doc["trimmed"] is True
    assert [(r["target"], r["status"], r.get("error", {}).get("code")) for r in run.doc["results"]] == [(NBIS, "ok", None), (OTHER, "error", "not_found")]


def test_a_budget_below_the_smallest_receipt_is_refused_before_any_request(cli, copy):
    run = cli("filing", NBIS, "--max-chars", "50", routes=[copy(NBIS, "nbis.html")])
    assert run.code == 2 and run.requests == [] and "--max-chars" in run.result()["error"]["message"]


def test_old_documents_are_deleted_by_age_when_filing_runs_and_zero_keeps_them(cli, copy, tmp_path):
    old = tmp_path / "data" / "filings" / "0123456789abcdef"
    old.mkdir(parents=True)
    (old / "document.txt").write_text("old\n")
    month = time.time() - 30 * 86400
    os.utime(old, (month, month))
    kept = cli("--ttl-days", "0", "filing", OTHER, routes=[copy(OTHER, b"<p>New.</p>")])
    assert kept.code == 0 and old.exists()
    pruned = cli("filing", OTHER, routes=[copy(OTHER, b"<p>New.</p>")])
    assert pruned.code == 0 and not old.exists()
