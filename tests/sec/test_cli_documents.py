"""CLI integration at the HTTP boundary and immutable document reader seam."""

URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/integration.htm"
HTML = b"""<html><body><h1 id="risk">Risk factors</h1><p>Access denied controls cost \x80 20.</p><p>Competition evidence.</p><table><tr><th>Year</th><th>Revenue</th></tr><tr><td>2024</td><td>42</td></tr></table><a href="#risk">Return to risks</a><img src="chart.png" alt="Sales chart"></body></html>"""


def test_open_decodes_http_charset_and_readers_use_same_cached_snapshot_without_identity(cli):
    cli.replies.append(("integration.htm", 200, HTML, {"content-type": "text/html; charset=windows-1252"}))
    code, opened = cli("open", URL)
    assert code == 0 and opened["status"] == "parsed"
    assert opened["encoding"]["inferred"] is False
    assert "windows-1252" in opened["encoding"]["declared"]
    snapshot = opened["snapshot_id"]
    cli.identity.write_text('EDGAR_IDENTITY=""')
    code, found = cli("find", snapshot, "competition")
    assert code == 0 and found["items"] and found["snapshot_id"] == snapshot
    position = found["items"][0]["position"]
    end = found["items"][0]["match_end"]
    code, read = cli("read", snapshot, "--position", position, "--end", end)
    assert code == 0 and read["text"] == "Competition"
    code, cells = cli("table", snapshot, opened["tables"][0]["table_id"])
    assert code == 0 and "42" in str(cells["items"])
    code, links = cli("links", snapshot, "--kind", "image")
    assert code == 0 and "chart.png" in str(links["items"])
    code, outline = cli("outline", snapshot)
    assert code == 0 and any(item.get("kind") == "table" for item in outline["items"])
    assert len(cli.calls) == 1


def test_open_summary_is_bounded_and_outline_discovers_all_table_ids(cli):
    body = "<html><body>" + "".join(f"<table><tr><td>{i}</td></tr></table>" for i in range(30)) + "</body></html>"
    cli.replies.append(("integration.htm", 200, body.encode(), {"content-type": "text/html"}))
    code, opened = cli("open", URL, "--max-chars", "1024")
    assert code == 0 and opened["table_count"] == 30
    assert opened["returned_chars"] == len(cli.last_output) <= 1024
    assert opened["tables_has_more"] is True
    assert "outline" in opened["table_discovery"]
    cli.identity.write_text('EDGAR_IDENTITY=""')
    cursor, table_ids = None, []
    while True:
        args = ["outline", opened["snapshot_id"]] + (["--cursor", cursor] if cursor else [])
        code, result = cli(*args)
        assert code == 0
        table_ids.extend(item["table_id"] for item in result["items"] if item["kind"] == "table")
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert len(set(table_ids)) == 30 and len(cli.calls) == 1


def test_unsupported_source_is_saved_but_malformed_xml_is_parse_failure(cli):
    pdf_url = URL.replace(".htm", ".pdf")
    cli.replies.append(("integration.pdf", 200, b"%PDF-1.4\nfixture", {"content-type": "application/pdf"}))
    code, opened = cli("open", pdf_url)
    assert code == 0 and opened["status"] == "unsupported" and opened["snapshot_id"]
    assert opened["source"]["url"] == pdf_url and opened["extraction_complete"] is False
    cli.replies.append(("integration.xml", 200, b"<ownership><unclosed>", {"content-type": "application/xml"}))
    code, error = cli("open", URL.replace(".htm", ".xml"))
    assert code == 2 and error["error"]["code"] == "parse_failed"


def test_document_schema_explains_positions_budgets_selection_and_partial_results(cli):
    code, result = cli("schema")
    assert code == 0
    assert result["documents"]["status"] == "parsed or unsupported; malformed supported content is a parse_failed error"
    assert result["reading"]["position"]
    assert result["reading"]["returned_chars"]
    assert result["company"]["selection_required"]
    assert result["company"]["match"]
    assert result["search"]["document_urls"]
    assert result["search"]["shards_failed"]
    assert result["recovery"]["cursor_mismatch"]


def test_long_read_cursor_is_exact_bounded_and_reusable_without_network(cli):
    text = "Evidence beyond the first page. " * 150 + "FINAL_SENTENCE"
    cli.replies.append(
        ("integration.htm", 200, ("<html><p>" + text + "</p></html>").encode(), {"content-type": "text/html"})
    )
    code, opened = cli("open", URL)
    assert code == 0
    cli.identity.write_text('EDGAR_IDENTITY=""')
    args = ["read", opened["snapshot_id"], "--max-chars", "2048"]
    chunks, cursor, first_cursor = [], None, None
    while True:
        code, result = cli(*(args + (["--cursor", cursor] if cursor else [])))
        assert code == 0
        assert result["returned_chars"] == len(cli.last_output) <= 2048
        chunks.append(result["text"])
        if cursor == first_cursor and cursor:
            code, replay = cli(*args, "--cursor", cursor)
            assert code == 0 and replay == result
        cursor = result["next_cursor"]
        if not cursor:
            assert result["scope_complete"] is True
            break
        first_cursor = first_cursor or cursor
    assert "".join(chunks) == text
    assert len(cli.calls) == 1
    code, error = cli("read", opened["snapshot_id"], "--max-chars", "4096", "--cursor", first_cursor)
    assert code == 2 and error["error"]["code"] == "cursor_mismatch"
