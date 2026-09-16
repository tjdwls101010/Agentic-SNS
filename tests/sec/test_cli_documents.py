"""CLI integration at the HTTP boundary and immutable document reader seam."""
import re

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
    assert code == 0 and "42" in str(cells["rows"])
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


STRUCTURED = (
    b'<html><body><a href="#part1">Part I</a><h2 id="part1">Item 1. Business</h2><p>Narrative.</p>'
    b'<a name="pb1"></a><p>Net sales by category were:</p><table><caption>Sales table</caption>'
    b"<tr><th>Category</th><th>2025</th></tr><tr><td>iPhone</td><td></td><td>209,586</td></tr></table>"
    b"<h2>Item 1A. Risk Factors</h2></body></html>"
)


def test_outline_defaults_to_contents_and_tables_and_exposes_table_context(cli):
    cli.replies.append(("integration.htm", 200, STRUCTURED, {"content-type": "text/html"}))
    code, opened = cli("open", URL)
    assert code == 0 and "table_discovery" not in opened
    snapshot = opened["snapshot_id"]
    (table,) = opened["tables"]
    assert table["table_id"] == "table-0" and table["rows"] == 2
    assert table["context"] == "Sales table" and table["header"] == "Category | 2025"
    assert re.fullmatch(r"\d+:\d+", table["position"])
    cli.identity.write_text('EDGAR_IDENTITY=""')
    code, read = cli("read", snapshot, "--position", table["position"])
    assert code == 0 and read["text"].startswith("Sales table\nCategory\n2025")
    code, outline = cli("outline", snapshot)
    assert code == 0 and outline["scope_complete"] is True
    assert [item["kind"] for item in outline["items"]] == ["toc", "heading", "table", "heading"]
    toc, business, table_entry, risk = outline["items"]
    assert toc["text"] == "Part I" and toc["anchor"] == "part1" and toc["position"] == business["position"]
    assert set(business) == {"kind", "text", "position", "anchor"} and business["anchor"] == "part1"
    assert set(risk) == {"kind", "text", "position"} and risk["text"] == "Item 1A. Risk Factors"
    assert set(table_entry) == {"kind", "position", "table_id", "rows", "context", "header"}
    assert "context_position" not in toc
    assert table_entry["context"] == "Sales table" and table_entry["position"] == table["position"]
    code, anchors = cli("outline", snapshot, "--kind", "anchor")
    assert code == 0 and [item["text"] for item in anchors["items"]] == ["part1", "pb1"]
    code, mixed = cli("outline", snapshot, "--kind", "table,anchor")
    assert code == 0 and [item["kind"] for item in mixed["items"]] == ["anchor", "anchor", "table"]
    code, error = cli("outline", snapshot, "--kind", "chapter")
    assert code == 2 and error["error"]["code"] == "invalid_argument" and "anchor" in error["error"]["fix"]
    assert len(cli.calls) == 1


def test_reader_commands_have_no_item_limit_and_reject_it(cli):
    cli.replies.append(("integration.htm", 200, STRUCTURED, {"content-type": "text/html"}))
    code, opened = cli("open", URL)
    assert code == 0
    code, error = cli("outline", opened["snapshot_id"], "--limit", "5")
    assert code == 2 and error["error"]["code"] == "invalid_argument"
    code, result = cli("schema")
    reader_options = {name: [o["names"][0] for o in c["options"]] for name, c in result["commands"].items()}
    for name in ("outline", "find", "read", "table", "links"):
        assert "--limit" not in reader_options[name], name


SALES_TABLE = (
    b"<html><body><p>Products and Services Performance</p><p>Net sales by category (dollars in millions):</p>"
    b"<table><caption>Sales</caption><tr><td></td><td></td><td></td></tr>"
    b"<tr><th></th><th colspan=\"2\">2025</th><th>2024</th></tr>"
    b'<tr><td>iPhone <a href="#fn1">(1)</a></td><td>$</td><td>209,586</td><td>201,183</td></tr>'
    b'<tr><td>Mac <img src="mac.png" alt="Mac icon"></td><td></td><td>33,708</td><td>29,984</td></tr>'
    b"<tr><td>Total</td><td>$</td><td>243,294</td><td>231,167</td></tr></table>"
    b'<p id="fn1">(1) Includes accessories.</p></body></html>'
)


def test_table_returns_rows_once_without_spacer_cells_and_selects_row_ranges(cli):
    cli.replies.append(("integration.htm", 200, SALES_TABLE, {"content-type": "text/html"}))
    code, opened = cli("open", URL)
    assert code == 0
    cli.identity.write_text('EDGAR_IDENTITY=""')
    code, table = cli("table", opened["snapshot_id"], "table-0")
    assert code == 0 and table["scope_complete"] is True and table["next_cursor"] is None
    assert "items" not in table
    assert table["context"] == ["Products and Services Performance", "Net sales by category (dollars in millions):"]
    assert table["caption"] == "Sales"
    assert table["footnotes"] == [{"text": "(1) Includes accessories.", "anchor": "fn1"}]
    assert [row["row"] for row in table["rows"]] == [1, 2, 3, 4]
    header, iphone, mac, total = table["rows"]
    assert header["header"] is True and "header" not in iphone
    assert header["cells"] == [{"column": 1, "colspan": 2, "text": "2025"}, {"column": 3, "text": "2024"}]
    assert re.fullmatch(r"\d+:\d+", header["position"])
    assert [c["text"] for c in iphone["cells"]] == ["iPhone (1)", "$", "209,586", "201,183"]
    assert iphone["cells"][0]["links"] == [{"kind": "internal", "text": "(1)", "anchor": "fn1"}]
    assert mac["cells"][0]["links"] == [{"kind": "image", "text": "Mac icon", "url": URL.rsplit("/", 1)[0] + "/mac.png"}]
    assert [c["column"] for c in mac["cells"]] == [0, 2, 3]
    code, read = cli("read", opened["snapshot_id"], "--position", total["position"])
    assert code == 0 and read["text"].startswith("Total\n$\n243,294")
    code, part = cli("table", opened["snapshot_id"], "table-0", "--rows", "2-3")
    assert code == 0 and [row["row"] for row in part["rows"]] == [2, 3] and part["scope_complete"] is True
    assert part["context"] == table["context"] and "footnotes" in part
    code, error = cli("table", opened["snapshot_id"], "table-0", "--rows", "9")
    assert code == 2 and error["error"]["code"] == "invalid_argument" and "0-4" in error["error"]["fix"]
    assert len(cli.calls) == 1


def test_oversized_response_names_this_command_own_narrowing_options(cli):
    data_uri = "data:image/png;base64," + "A" * 2000
    body = (
        b"<html><body><p>" + b"z" * 4000 + b'</p><img src="' + data_uri.encode() + b'" alt="chart">'
        b"<table><tr><td>42</td></tr></table></body></html>"
    )
    cli.replies.append(("integration.htm", 200, body, {"content-type": "text/html"}))
    code, opened = cli("open", URL)
    assert code == 0
    cli.identity.write_text('EDGAR_IDENTITY=""')
    code, error = cli("links", opened["snapshot_id"], "--kind", "image", "--max-chars", "1024")
    assert code == 2 and error["error"]["code"] == "budget_too_small"
    assert "--kind" in error["error"]["fix"] and "--max-chars up to 24000" in error["error"]["fix"]
    code, table = cli("table", opened["snapshot_id"], "table-0", "--max-chars", "1024")
    assert code == 0 and table["returned_chars"] <= 1024
    code, whole = cli("table", opened["snapshot_id"], "table-0")
    assert code == 0 and whole["rows"][0]["cells"][0]["text"] == "42"
    code, long_read = cli("read", opened["snapshot_id"], "--max-chars", "1024")
    assert code == 0 and long_read["has_more"] is True and long_read["text"].startswith("zzz")


def test_read_returns_prose_once_as_plain_text_with_a_short_header(cli):
    prose = "Apple Inc. faces competition. " * 400 + "FINAL SENTENCE."
    cli.replies.append(("integration.htm", 200, ("<html><p>" + prose + "</p></html>").encode(), {"content-type": "text/html"}))
    code, opened = cli("open", URL)
    assert code == 0
    snapshot = opened["snapshot_id"]
    cli.identity.write_text('EDGAR_IDENTITY=""')
    code, output = cli.text("read", snapshot)
    assert code == 0
    header, _, body = output.partition("\n\n")
    assert header.splitlines()[0] == "source_url: " + URL
    keys = [line.split(":")[0] for line in header.splitlines()]
    assert {"source_url", "snapshot_id", "status", "extraction_complete", "has_more", "next_position"} <= set(keys)
    assert body.rstrip("\n") == prose[: len(body.rstrip("\n"))]
    assert "\\n" not in output and '"text"' not in output
    assert len(body) / len(output) > 0.9
    code, structured = cli("read", snapshot)
    assert code == 0 and structured["text"] == body.rstrip("\n")
    assert all(set(item) <= {"kind", "position", "anchor", "path", "parent", "attributes"} for item in structured["items"])
    code, rest = cli.text("read", snapshot, "--position", structured["next_position"])
    assert code == 0 and rest.rstrip("\n").endswith("FINAL SENTENCE.")


def test_recovery_codes_and_warnings_match_what_schema_lists(cli):
    body = (b'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
            b'<ix:header><ix:hidden>MACHINE_ONLY</ix:hidden></ix:header><p>Narrative.</p></body></html>')
    cli.replies.append(("integration.htm", 200, body, {"content-type": "text/html"}))
    code, opened = cli("open", URL)
    assert code == 0 and opened["warnings"] == ["inline_xbrl_metadata_excluded"]
    code, schema = cli("schema")
    assert "inline_xbrl_metadata_excluded" in schema["documents"]["warnings"]
    code, error = cli("read", "not-a-snapshot")
    assert code == 2 and error["error"]["code"] == "invalid_snapshot"
    assert "open" in error["error"]["fix"] and "cursor" not in error["error"]["fix"]
    code, error = cli("read", "f" * 64)
    assert code == 2 and error["error"]["code"] == "missing_snapshot"
    code, error = cli("filings", "320193", "--cursor", "not-a-cursor")
    assert code == 2 and error["error"]["code"] == "invalid_cursor"


def test_schema_scopes_to_one_command_and_responses_carry_no_prose_guidance(cli):
    code, whole = cli("schema")
    assert code == 0 and len(whole["commands"]) == 11
    code, scoped = cli("schema", "read")
    assert code == 0 and list(scoped["commands"]) == ["read"]
    assert scoped["reading"] and "documents" not in scoped and "search" not in scoped
    assert len(cli.last_output) < 5000  # one command's contract, well under a quarter of the full surface
    code, error = cli("schema", "nosuchcommand")
    assert code == 2 and "read" in error["error"]["message"] and error["error"]["fix"]


FORM4 = (
    b'<?xml version="1.0"?><ownershipDocument>'
    b"<nonDerivativeTransaction><shares>10</shares><footnoteId id=\"F1\"/></nonDerivativeTransaction>"
    b"<nonDerivativeTransaction><shares>20</shares><footnoteId id=\"F2\"/></nonDerivativeTransaction>"
    b'<footnotes><footnote id="F1">Gift.</footnote></footnotes></ownershipDocument>'
)


def test_structured_documents_keep_their_paths_in_the_default_rendering(cli):
    url = URL.replace(".htm", ".xml")
    cli.replies.append(("integration.xml", 200, FORM4, {"content-type": "application/xml"}))
    code, opened = cli("open", url)
    assert code == 0 and opened["format"] == "xml"
    cli.identity.write_text('EDGAR_IDENTITY=""')
    code, output = cli.text("read", opened["snapshot_id"])
    body = output.partition("\n\n")[2]
    assert "/ownershipDocument[1]/nonDerivativeTransaction[1]/shares[1]: 10" in body
    assert "/ownershipDocument[1]/nonDerivativeTransaction[2]/shares[1]: 20" in body
    assert 'footnoteId[1] {"id": "F1"}' in body
    code, structured = cli("read", opened["snapshot_id"])
    assert code == 0 and "text" not in structured
    assert structured["items"][0]["path"] == "/ownershipDocument[1]/nonDerivativeTransaction[1]/shares[1]"
    assert structured["items"][0]["text"] == "10"


def test_reader_responses_carry_the_snapshot_warnings(cli):
    body = (
        b'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
        b"<ix:header><ix:hidden>MACHINE</ix:hidden></ix:header><p>Narrative text.</p>"
        b'<img src="chart.png" alt="chart"><table><tr><td>42</td></tr></table></body></html>'
    )
    cli.replies.append(("integration.htm", 200, body, {"content-type": "text/html"}))
    code, opened = cli("open", URL)
    assert code == 0
    assert set(opened["warnings"]) == {"inline_xbrl_metadata_excluded", "image_content_not_extracted"}
    snapshot = opened["snapshot_id"]
    cli.identity.write_text('EDGAR_IDENTITY=""')
    for args in (
        ["read", snapshot],
        ["outline", snapshot],
        ["find", snapshot, "Narrative"],
        ["table", snapshot, "table-0"],
        ["links", snapshot],
    ):
        code, result = cli(*args)
        assert code == 0 and result["warnings"] == opened["warnings"], args
    code, output = cli.text("read", snapshot)
    assert "warnings: inline_xbrl_metadata_excluded, image_content_not_extracted" in output.partition("\n\n")[0]
    cli.replies.append(("clean.htm", 200, b"<html><p>Plain narrative.</p></html>", {"content-type": "text/html"}))
    cli.identity.write_text('EDGAR_IDENTITY="SEC fixture tests tests@example.org"')
    code, clean = cli("open", URL.replace("integration", "clean"))
    assert code == 0 and clean["warnings"] == []
    code, read = cli("read", clean["snapshot_id"])
    assert code == 0 and "warnings" not in read
