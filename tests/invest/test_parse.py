"""Reading a received SEC document through invest.sec's entry: blocks, tables as grids, links, anchors, emphasis, and the formats it refuses.

The expectations were established against the originals in fixtures/documents when the sec skill's reader was built (its tests carried them; this file keeps their meaning at the new entry), and expected-sections.json lists section titles read from the original DOM before the emphasis rule existed.
"""
import gzip
import json
from pathlib import Path
import re

from lxml import html
import pytest

from invest.receipts import Failure
from invest.sec import Fetched, parse

DOCUMENTS = Path(__file__).parent / "fixtures" / "documents"
URL = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/x.htm"


def original(name):
    meta = json.loads((DOCUMENTS / "provenance.json").read_text())[name]
    raw = (DOCUMENTS / meta.get("storage", name)).read_bytes()
    return gzip.decompress(raw) if meta.get("compression") == "gzip" else raw


def read(markup, url=URL, content_type="text/html"):
    body = markup if isinstance(markup, bytes) else markup.encode()
    return parse(Fetched(body, url, content_type))


def canonical(document):
    return "\n".join(block["text"] for block in document.blocks)


def emphasis(document, navigation=None):
    return [item for item in document.outline if item["kind"] == "emphasis" and (navigation is None or item["navigation"] is navigation)]


def table(markup, index=0):
    return read(markup).tables[index]


def cells(grid):
    return {(c["row"], c["column"]): grid["text"][c["text_start"]:c["text_end"]] for c in grid["cells"]}


def rows(grid):
    return {row: grid["text"][start:end] for row, start, end in grid["row_ranges"]}


@pytest.fixture(scope="module")
def nbis():
    return parse(Fetched(original("nbis.html"), "https://www.sec.gov/Archives/edgar/data/1513845/000110465926094844/nbis-20260812xex99d2.htm", "text/html"))


# ---- a table is one block, and nothing is lost or repeated ------------------------------------------------------------

def test_a_table_is_one_block_holding_its_grid():
    document = read("<p>Before</p><table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>")
    assert [b["kind"] for b in document.blocks] == ["text", "grid"]
    assert document.blocks[1]["text"] == "a\tb\nc\td" and document.blocks[1]["table_id"] == "table-0"
    assert document.blocks[document.tables[0]["block"]]["table_id"] == "table-0"


def test_an_empty_table_keeps_its_own_block():
    document = read("<p>Before</p><table><tr><td>​</td></tr></table><p>After</p>")
    assert [b["kind"] for b in document.blocks] == ["text", "grid", "text"] and document.blocks[1]["text"] == ""


def test_a_child_table_follows_its_parent_and_records_the_cell_it_sits_in():
    document = read("<table><tr><td>outer<table><tr><td>inner</td></tr></table></td></tr></table><p>After</p>")
    assert [b.get("table_id") for b in document.blocks] == ["table-0", "table-1", None]
    assert "inner" not in document.blocks[0]["text"]
    assert document.tables[1]["parent_table_id"] == "table-0" and document.tables[1]["parent_cell"] == {"row": 0, "column": 0}


def visible_characters(text):
    root = html.document_fromstring(re.sub(r"^\s*<\?xml[^?]*\?>", "", text))
    hidden = [n for n in root.iter() if isinstance(n.tag, str) and ":" in n.tag and n.tag.lower().split(":")[-1] in ("hidden", "header")]
    for node in [*root.xpath("//script | //style | //head"), *hidden]:
        if node.getparent() is not None:
            node.getparent().remove(node)
    return re.sub(r"[\s​]+", "", "".join(root.itertext()))


@pytest.mark.parametrize("name", ["nbis.html", "apple.html", "mrvl.html", "microsoft.html"])
def test_every_character_of_the_original_appears_exactly_once(name):
    body = original(name)
    document = read(body)
    assert re.sub(r"[\s​]+", "", canonical(document)) == visible_characters(body.decode("utf-8", "replace"))


def test_inline_xbrl_hidden_metadata_is_not_reading_text():
    document = read('<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body><ix:hidden><p>0000320193FY</p></ix:hidden><p>Readable report.</p></body></html>')
    assert canonical(document) == "Readable report." and "inline_xbrl_metadata_excluded" in document.limits
    cell = read('<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body><table><tr><td><ix:hidden>hidden</ix:hidden>Revenue</td></tr></table></body></html>')
    assert canonical(cell) == "Revenue"


# ---- positions: anchors and links carry where they sit --------------------------------------------------------------

def test_an_anchor_inside_a_table_cell_points_at_that_cell():
    document = read('<table><tr><td>a</td><td id="here">the cell</td></tr></table>')
    anchor = next(item for item in document.outline if item["kind"] == "anchor")
    assert document.blocks[anchor["block"]]["text"][anchor["offset"]:].startswith("the cell")
    assert (anchor["table_id"], anchor["row"], anchor["column"]) == ("table-0", 0, 1)


def test_an_anchor_in_prose_points_at_the_text_it_marks():
    document = read('<p>Before</p><p>Lead in <span id="here">marked text</span> and after.</p>')
    anchor = next(item for item in document.outline if item["kind"] == "anchor")
    assert document.blocks[anchor["block"]]["text"][anchor["offset"]:].startswith("marked text")


def test_a_link_inside_a_table_carries_its_cell_and_an_image_its_column():
    document = read('<table><tr><td>Revenue <a href="https://example.com/n">note</a></td><td><img src="chart.jpg" alt="Q1"/></td></tr></table>')
    link = next(item for item in document.links if item["kind"] == "external")
    assert (link["table_id"], link["row"], link["column"], link["url"]) == ("table-0", 0, 0, "https://example.com/n")
    image = next(item for item in document.links if item["kind"] == "image")
    cell = next(c for c in document.tables[0]["cells"] if c["column"] == 1)
    assert cell["nonempty_reason"] == "image" and cell["links"] == [image["id"]] and image["url"].endswith("/chart.jpg")


def test_internal_links_keep_their_source_block_and_target_and_no_contents_verdict():
    """Choosing which links are the contents belongs to the filing feature; the reader only says where each link sits and lands."""
    document = read('<p><a href="#a">Item 1</a> <a href="#b">Item 2</a></p><p id="a">One</p><p id="b">Two</p>')
    internal = [item for item in document.links if item["kind"] == "internal"]
    assert [(item["block"], item["target_resolved"]) for item in internal] == [(0, True), (0, True)]
    assert not [item for item in document.outline if item["kind"] in ("toc", "internal_link")]


# ---- the grid: spans, folding, nested tables ------------------------------------------------------------------------

def test_nbis_equity_table_folds_nineteen_columns_to_ten(nbis):
    grid = nbis.tables[7]
    assert (grid["original_rows"], grid["original_columns"]) == (32, 19)
    assert grid["kept_columns"] == [0, 1, 3, 5, 7, 9, 11, 13, 15, 17]


def test_the_label_row_and_the_value_row_land_in_the_same_columns(nbis):
    found = cells(nbis.tables[7])
    labels = [(c, t) for (r, c), t in sorted(found.items()) if r == 5 and t]
    values = [(c, t) for (r, c), t in sorted(found.items()) if r == 6 and t]
    assert [t for _, t in labels] == ["Shares", "Amount", "cost", "Capital", "Loss", "Earnings", "Nebius Group N.V.", "interests", "Equity"]
    assert [c for c, _ in values] == [0, 1, 3, 5, 7, 9, 11, 13, 15, 17]
    assert [t for _, t in values] == ["Balance as of December 31, 2024", "235,753,600", "9.2", "(1,968.1)", "2,016.7", "(22.1)", "3,218.0", "3,253.7", "—", "3,253.7"]


def test_the_second_period_starts_again_inside_the_same_table_and_the_warrant_row_reads_whole(nbis):
    found = rows(nbis.tables[7])
    assert "Six months ended June 30, 2025" in found[1] and "Six months ended June 30, 2026" in found[15]
    assert found[5].split("\t")[1:] == found[19].split("\t")[1:]
    assert found[27].split("\t") == ["Issuance of pre-funded warrants (Note 14)", "—", "—", "—", "2,000.0", "—", "—", "2,000.0", "—", "2,000.0"]


def test_a_span_records_its_original_and_folded_widths(nbis):
    spans = {(s["row"], s["column"]): s for s in nbis.tables[7]["spans"]}
    assert (spans[(1, 1)]["colspan"], spans[(1, 1)]["w"]) == (17, 9)
    assert (spans[(2, 1)]["colspan"], spans[(2, 1)]["w"]) == (3, 2)


def test_rowspan_zero_and_a_positive_rowspan_stop_at_their_row_group():
    zero = table("<table><tbody><tr><td rowspan='0'>A</td><td>a1</td></tr><tr><td>a2</td></tr></tbody><tbody><tr><td>B</td><td>b1</td></tr><tr><td>C</td><td>b2</td></tr></tbody></table>")
    assert (cells(zero)[(0, 0)], cells(zero)[(2, 0)], cells(zero)[(3, 0)]) == ("A", "B", "C")
    assert next(s for s in zero["spans"] if (s["row"], s["column"]) == (0, 0))["effective_rows"] == 2
    positive = table("<table><tbody><tr><td rowspan='2'>A</td><td>a</td></tr></tbody><tbody><tr><td>B</td></tr></tbody></table>")
    assert positive["text"] == "A\ta\nB"


def test_a_footer_group_declared_early_is_read_last():
    assert table("<table><tfoot><tr><td>F</td></tr></tfoot><tbody><tr><td>B</td></tr></tbody></table>")["text"] == "B\nF"


def test_a_spanned_cell_keeps_its_text_only_where_it_starts():
    grid = table("<table><tr><td rowspan='2'>Once</td><td>x</td></tr><tr><td>y</td></tr></table>")
    assert grid["text"].count("Once") == 1


@pytest.mark.parametrize("markup", [
    "<table><tr><td>a</td><td rowspan='2'>held</td></tr><tr><td colspan='3'>wide</td></tr></table>",
    "<table><tr><td colspan='-1'>x</td></tr></table>",
    "<table><tr><td colspan='nine'>x</td></tr></table>",
    "<table><tr><td colspan='99999'>x</td></tr></table>",
    "<table>" + "<tr>" + "".join(f"<td>{i}</td>" for i in range(600)) + "</tr>" + "<tr><td>x</td></tr>" * 600 + "</table>",
], ids=["overlap", "negative", "not-a-number", "too-wide", "too-large"])
def test_a_table_that_cannot_be_laid_out_faithfully_fails_rather_than_being_repaired(markup):
    with pytest.raises(Failure) as error:
        read(markup)
    assert error.value.code == "unsupported"


def test_a_column_survives_folding_only_when_something_starts_in_it():
    assert table("<table><tr><td>a</td><td>​</td><td>b</td></tr></table>")["kept_columns"] == [0, 2]
    grid = table("<table><tr><td>a</td><td><table><tr><td>inner</td></tr></table></td></tr></table>")
    assert grid["kept_columns"] == [0, 1] and next(c for c in grid["cells"] if c["column"] == 1)["nonempty_reason"] == "child_table"


def test_the_parent_cell_records_where_a_child_table_interrupted_it():
    grid = table("<table><tr><td>before<table><tr><td>inner</td></tr></table>after</td></tr></table>")
    cell = grid["cells"][0]
    assert [p["kind"] for p in cell["parts"]] == ["text", "child_table", "text"] and cell["parts"][1]["child_table_id"] == "table-1"
    assert "beforeafter" not in grid["text"] and "\n" in grid["text"]


def test_an_original_th_declaration_is_kept_and_an_absent_one_invents_nothing():
    header, value = table("<table><tr><th scope='col'>Year</th><td>2025</td></tr></table>")["cells"]
    assert header["th"] is True and header["scope"] == "col" and "th" not in value


def test_row_numbers_are_not_renumbered_around_an_empty_row():
    grid = table("<table><tr><td>a</td></tr><tr><td>​</td></tr><tr><td>c</td></tr></table>")
    assert [r for r, _, _ in grid["row_ranges"]] == [0, 1, 2] and rows(grid)[1] == "" and rows(grid)[2] == "c"


# ---- text normalisation ------------------------------------------------------------------------------------------------

def test_a_layout_cell_is_empty_and_a_mixed_value_keeps_its_character():
    assert table("<table><tr><td>​​</td><td>x</td></tr></table>")["kept_columns"] == [1]
    assert "Share​holders" in table("<table><tr><td> Share​holders </td></tr></table>")["text"]


@pytest.mark.parametrize("value", ["(1,968.1)", "—", "–", "−", "Share‑based", "$9.2", "€8.8", "51%", "235,753,600", "(6.59)"])
def test_evidence_characters_survive_exactly(value):
    assert table(f"<table><tr><td>{value}</td></tr></table>")["text"] == value


# ---- emphasis ------------------------------------------------------------------------------------------------------------

def test_an_emphasized_block_carries_the_signals_it_was_judged_on():
    item = emphasis(read('<p>Plain body text that runs on.</p><p style="font-weight:700;text-align:center">Risk Factors</p>'))[0]
    assert item["text"] == "Risk Factors" and item["signals"] == {"bold_fraction": 1.0, "font_size_ratio": None, "alignment": "center", "all_caps": False}


def test_bold_italic_and_heading_declarations_are_signals_and_normal_weight_is_not():
    for markup in ('<p style="font-weight:bold">H</p>', '<p style="font-weight:700">H</p>', "<p><b>H</b></p>", "<p><i>H</i></p>"):
        assert emphasis(read(markup)), markup
    assert not emphasis(read('<p style="font-weight:400">H</p>'))
    assert emphasis(read("<h2>Business</h2>"))[0]["navigation"] is True


def test_the_space_between_runs_counts_and_a_partly_bold_block_reports_its_fraction():
    assert emphasis(read("<p><b>ABCD</b> <span>E</span></p>"))[0]["signals"]["bold_fraction"] == pytest.approx(4 / 6, rel=0.01)
    item = emphasis(read("<p><b>Item 1A.</b> The rest of this paragraph is ordinary body text here.</p>"))[0]
    assert 0 < item["signals"]["bold_fraction"] < 0.3


def test_the_body_size_is_measured_from_the_document():
    body = '<p style="font-size:9pt">' + "Ordinary sentence. " * 20 + "</p>"
    item = next(x for x in emphasis(read(body * 5 + '<p style="font-size:14pt">Larger Line</p>')) if x["text"] == "Larger Line")
    assert item["signals"]["font_size_ratio"] == pytest.approx(14 / 9, rel=0.01) and item["navigation"] is True
    assert emphasis(read('<p style="font-size:14pt">Larger Line</p>')) == []


def test_emphasis_inside_a_table_belongs_to_its_row_and_a_layout_cell_adds_none():
    item = emphasis(read('<table><tr><td style="font-weight:bold">ITEM 4 INFORMATION ON THE COMPANY</td></tr></table>'))[0]
    assert item["navigation"] is False and (item["table_id"], item["row"]) == ("table-0", 0)
    assert [x for x in emphasis(read('<table><tr><td style="font-weight:bold">​</td><td>Translation adjustment</td></tr></table>')) if x["signals"]["bold_fraction"]] == []


def test_a_contents_row_of_links_is_not_navigation():
    document = read('<p style="font-weight:bold"><a href="#a">Item 1. Business</a></p><h2 id="a">Item 1</h2>')
    assert [x["text"] for x in emphasis(document, navigation=True)] == ["Item 1"]


@pytest.mark.parametrize("name", ["apple.html", "microsoft.html", "mrvl.html"])
def test_every_section_boundary_of_the_original_is_reachable(name):
    expected = json.loads((DOCUMENTS / "expected-sections.json").read_text())["documents"][name]
    reached = {x["text"] for x in emphasis(read(original(name)), navigation=True)}
    assert [text for text in expected if text not in reached] == []


def test_a_repeated_page_header_keeps_every_place_it_occurs():
    places = [x for x in emphasis(read(original("microsoft.html"))) if x["text"] == "PART II"]
    assert len(places) > 10 and len({x["block"] for x in places}) == len(places)
    assert len({x["signals"]["bold_fraction"] for x in places}) > 1 and [x for x in places if x["navigation"]]


# ---- formats it reads and formats it refuses -----------------------------------------------------------------------------

@pytest.mark.parametrize("body,content_type,url", [
    (b"%PDF-1.7 ...", "application/pdf", URL.replace(".htm", ".pdf")),
    (b"PK\x03\x04\x14\x00 rest of a zip", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", URL.replace(".htm", ".xlsx")),
    (b"\x89PNG\r\n\x1a\n...", "image/png", URL.replace(".htm", ".png")),
], ids=["pdf", "xlsx", "png"])
def test_a_binary_document_is_unsupported(body, content_type, url):
    with pytest.raises(Failure) as error:
        read(body, url, content_type)
    assert error.value.code == "unsupported"


@pytest.mark.parametrize("name", ["form4.xml", "old.txt"])
def test_an_xml_record_and_a_multi_document_submission_are_unsupported(name):
    with pytest.raises(Failure) as error:
        read(original(name), URL.replace("x.htm", name), "text/xml" if name.endswith(".xml") else "text/plain")
    assert error.value.code == "unsupported" and ("XML" in str(error.value) or "SGML" in str(error.value))


def test_a_single_document_wrapper_around_html_is_read_as_html():
    expected = json.loads((DOCUMENTS / "expected.json").read_text())["asml"]
    document = read(original("asml.html"))
    images = [x["url"].rsplit("/", 1)[-1] for x in document.links if x["kind"] == "image"]
    assert document.format == "html" and expected["text"] in canonical(document)
    assert (len(images), images[0], images[-1]) == (expected["image_count"], expected["first_image"], expected["last_image"])


@pytest.mark.parametrize("body", [b"", b"   \n\t ", b"<html><body><p>\xe2\x80\x8b</p></body></html>"], ids=["empty", "whitespace", "layout-only"])
def test_a_document_with_no_readable_text_is_an_empty_document(body):
    with pytest.raises(Failure) as error:
        read(body)
    assert error.value.code == "empty_document"


def test_plain_text_is_read_line_by_line():
    document = read(b"FORM 8-K\n\nItem 2.02 Results of Operations\n  Revenue rose.\n", URL.replace(".htm", ".txt"), "text/plain")
    assert document.format == "text" and [b["text"] for b in document.blocks] == ["FORM 8-K", "Item 2.02 Results of Operations", "Revenue rose."]


def test_bytes_that_do_not_fit_the_declared_encoding_are_marked_lost_rather_than_reread_in_a_guessed_one():
    document = read(b"<html><head><meta charset='utf-8'></head><body><p>caf\xe9 cr\xc3\xa8me</p></body></html>")
    assert canonical(document) == "caf\ufffd cr\u00e8me"
    assert "encoding_loss" in document.limits and document.encoding["loss"] is True and document.encoding["selected"] == "utf-8"


def test_undeclared_bytes_are_read_as_utf8_when_they_are_utf8():
    assert canonical(read("<p>Share\u200bholders \u2014 caf\u00e9</p>".encode())) == "Share\u200bholders \u2014 caf\u00e9"
