"""A read document turned into the text file and its map, through invest.filing's entry.

Contents expectations come from expected-map.json, read from the originals with lxml independently of the parser; synthetic documents pin each rule of choosing the contents and each invariant of the file.
"""
import gzip
import json
from pathlib import Path
import re

import pytest

from invest.filing import render
from invest.sec import Fetched, parse

DOCUMENTS = Path(__file__).parent / "fixtures" / "documents"
EXPECTED = json.loads((DOCUMENTS / "expected-map.json").read_text())
SOURCE = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/x.htm"
IDENTITY = {"source": SOURCE, "fetch": "https://cdn.yahoofinance.com/prod/sec-filings/0000000001/000000000000000001/x.htm", "sha256": "0" * 64}
MARK = re.compile(r"\[→L(\d+)\]")


def original(name):
    meta = json.loads((DOCUMENTS / "provenance.json").read_text())[name]
    raw = (DOCUMENTS / meta.get("storage", name)).read_bytes()
    return gzip.decompress(raw) if meta.get("compression") == "gzip" else raw


def rendered(markup):
    body = markup if isinstance(markup, bytes) else markup.encode()
    document = parse(Fetched(body, SOURCE, "text/html"))
    return document, render(document, IDENTITY)


@pytest.fixture(scope="module")
def files():
    return {name: rendered(original(name)) for name in EXPECTED["contents"]}


def lines_of(result):
    return result.text.split("\n")[:-1]


def line(result, number):
    return lines_of(result)[number - 1]


def reading(result, start, count=40):
    """The text from line `start` on as a reader meets it: markers, table frames, row numbers and every pipe (a field separator or the original's own) removed."""
    out = []
    for text in lines_of(result)[start - 1:start - 1 + count]:
        if re.match(r"\[t\d+ \|", text) or text.startswith(("spans:", "th:")):
            continue
        text = re.sub(r"^t\d+\.\d+(\||$)", "", MARK.sub("", text)).removeprefix("caption: ")
        out.append(text.replace("|", "").replace("**", ""))
    return re.sub(r"[\s​]+", "", "".join(out))


def range_start(entry):
    return int(entry["lines"].split("-")[0])


# ---- the file -------------------------------------------------------------------------------------------------------------

def test_the_first_line_names_the_original_and_the_copy_and_the_file_ends_with_a_newline():
    _, result = rendered("<p>Hello</p>")
    assert line(result, 1).startswith(f"SOURCE {SOURCE} | Yahoo copy {IDENTITY['fetch']} | sha256 {'0' * 16} | text v")
    assert result.text.endswith("Hello\n") and result.map["lines"] == 2 and result.map["chars"] == len(result.text)


def test_one_paragraph_is_one_line():
    _, result = rendered("<p>First paragraph\n spans lines.</p><div>Second</div>")
    assert lines_of(result)[1:] == ["First paragraph spans lines.", "Second"]


def test_an_anchor_at_the_end_of_a_paragraph_lands_on_the_text_that_follows_it():
    _, result = rendered('<p><a href="#s">Statements</a></p><p>Filler</p><p><b>NEBIUS GROUP N.V.</b><a name="s"></a></p><p>BALANCE SHEETS</p>')
    assert line(result, int(MARK.findall(line(result, 2))[0])) == "BALANCE SHEETS"


def test_a_link_marker_points_at_the_line_its_target_is_on_after_the_header_line():
    _, result = rendered('<p>See <a href="#n">the note</a>.</p><p>Filler</p><p id="n">Note text</p>')
    marks = [(i + 1, int(m)) for i, text in enumerate(lines_of(result)) for m in MARK.findall(text)]
    assert marks == [(2, 4)] and line(result, 4) == "Note text"


def test_an_anchor_inside_a_table_lands_on_its_row_not_the_table_frame():
    _, result = rendered('<p><a href="#r">to the row</a></p><table><tr><td>a</td></tr><tr><td>b</td></tr><tr><td id="r">target row</td></tr></table>')
    target = int(MARK.findall(line(result, 2))[0])
    assert line(result, target) == "t0.2|target row"


def test_an_anchor_on_a_table_row_or_the_table_itself_is_a_place_a_link_reaches():
    _, result = rendered('<p><a href="#t">table</a> <a href="#row">row</a></p><table id="t"><tr><td>a</td></tr><tr id="row"><td>b</td></tr></table>')
    table, row = map(int, MARK.findall(line(result, 2)))
    assert line(result, table).startswith("[t0 |") and line(result, row) == "t0.1|b"


def test_a_link_inside_a_table_cell_is_marked_on_that_rows_line():
    _, result = rendered('<table><tr><td>x</td></tr><tr><td>Revenue <a href="#n">(1)</a></td><td>9</td></tr></table><p id="n">(1) Note</p>')
    row = next(text for text in lines_of(result) if text.startswith("t0.1|"))
    assert MARK.findall(row) and line(result, int(MARK.findall(row)[0])) == "(1) Note"


def test_every_marker_in_a_real_document_points_inside_the_file(files):
    for name, (_, result) in files.items():
        total = len(lines_of(result))
        assert all(1 <= int(m) <= total for m in MARK.findall(result.text)), name


def test_a_table_opens_with_its_frame_and_writes_one_line_per_original_row(files):
    _, result = files["nbis.html"]
    rows = {}
    for text in lines_of(result):
        match = re.match(r"(t\d+)\.\d+\|", text) or re.match(r"(t\d+)\.\d+$", text)
        if match:
            rows[match[1]] = rows.get(match[1], 0) + 1
    tables = {t["id"]: t["rows"] for t in result.map["tables"]}
    assert len(tables) == EXPECTED["elements"]["nbis.html"]["tables"]
    assert {k: v for k, v in tables.items() if v} == rows


def test_the_nbis_warrant_row_reads_with_its_original_row_number(files):
    _, result = files["nbis.html"]
    assert "t7.27|Issuance of pre-funded warrants (Note 14)|—|—|—|2,000.0|—|—|2,000.0|—|2,000.0" in lines_of(result)
    frame = next(text for text in lines_of(result) if text.startswith("[t7 |"))
    assert frame == "[t7 | 32 rows x 10 columns]"


def test_spans_and_th_declarations_are_written_after_the_frame():
    _, result = rendered("<table><tr><th scope='col'>Year</th><th colspan='2'>Values</th></tr><tr><td>2025</td><td>1</td><td>2</td></tr></table>")
    assert lines_of(result)[1:5] == ["[t0 | 2 rows x 3 columns]", "spans: r0c1 c1-2", "th: r0c0=col r0c1", "t0.0|Year|Values"]


def test_a_pipe_and_a_backslash_in_a_cell_are_escaped():
    _, result = rendered("<table><tr><td>a|b</td><td>c\\d</td></tr></table>")
    assert "t0.0|a\\|b|c\\\\d" in lines_of(result)


def test_an_image_in_a_cell_is_written_in_its_field_and_one_outside_tables_on_its_own_line():
    _, result = rendered('<table><tr><td>Chart</td><td><img src="c.jpg" alt="Q1"/></td></tr></table><p>After</p><p><img src="d.jpg"/></p>')
    base = SOURCE.rsplit("/", 1)[0]
    assert f"t0.0|Chart|[image: Q1 \\| {base}/c.jpg]" in lines_of(result)  # a pipe inside a field is escaped like any other
    assert f"[image: no alt text | {base}/d.jpg]" in lines_of(result)


# ---- emphasis in the file ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("markup,bold", [
    ("<p><b>ABCD</b>E</p>", True),
    ("<p><b>ABC</b>DE</p>", False),
    ("<p><b>Risk Factors</b></p>", True),
    ("<table><tr><td><b>Bold cell</b></td></tr></table>", False),
], ids=["four-fifths", "three-fifths", "whole", "in-table"])
def test_a_paragraph_is_wrapped_in_stars_exactly_when_four_fifths_of_its_letters_are_bold(markup, bold):
    _, result = rendered(markup)
    assert any(text.startswith("**") and text.endswith("**") for text in lines_of(result)) is bold


def test_the_starred_lines_of_a_real_document_are_exactly_its_wholly_bold_paragraphs(files):
    document, result = files["apple.html"]
    expected = sorted(item["text"] for item in document.outline
                      if item["kind"] == "emphasis" and "table_id" not in item and item["bold_chars"] * 5 >= item["chars"] * 4)
    starred = sorted(text[2:-2] for text in lines_of(result) if text.startswith("**") and text.endswith("**"))
    assert starred == expected and len(starred) > 100


def test_a_heading_row_inside_a_one_row_table_is_a_set_apart_line():
    _, result = rendered('<p>Body text runs here.</p><table><tr><td><b>14. Equity</b></td></tr></table><p>The note.</p>')
    assert [h for h in result.map["headings"] if h["text"] == "14. Equity"] == [{"line": 4, "text": "14. Equity"}]
    assert line(result, 4) == "t0.0|14. Equity"


def test_every_place_a_repeated_heading_occurs_stays_in_the_map():
    _, result = rendered("".join(f"<p><b>PART II</b></p><p>Body {i}.</p>" for i in range(3)))
    assert [h["line"] for h in result.map["headings"] if h["text"] == "PART II"] == [2, 4, 6]


# ---- the contents --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", [n for n, v in EXPECTED["contents"].items() if v])
def test_the_contents_are_the_documents_own_linked_contents(files, name):
    _, result = files[name]
    expected = EXPECTED["contents"][name]
    entries = result.map["contents"]
    assert [e["title"] for e in entries] == [e["title"] for e in expected]
    for entry, wanted in zip(entries, expected):
        destination = re.sub(r"[\s​|]+", "", wanted["destination"])
        # One paragraph is one line, so a target placed mid-word (NBIS puts one inside "INCOM|E") lands on the line that holds the destination's first character.
        found = reading(result, range_start(entry)).find(destination)
        assert 0 <= found < len(reading(result, range_start(entry), 1)), (entry, wanted)


def test_a_document_without_linked_contents_has_none_and_lists_its_set_apart_lines(files):
    _, result = files["asml.html"]
    assert result.map["contents"] is None and result.map["candidates"] == []


def test_contents_ranges_run_from_each_target_to_the_line_before_the_next(files):
    _, result = files["apple.html"]
    entries = result.map["contents"]
    starts = [range_start(e) for e in entries]
    assert starts == sorted(starts)
    for entry, following in zip(entries, entries[1:] + [None]):
        start, end = map(int, entry["lines"].split("-"))
        assert end == (range_start(following) - 1 if following else result.map["lines"])
        assert entry["chars"] == sum(len(text) + 1 for text in lines_of(result)[start - 1:end])


def test_a_large_range_lists_the_set_apart_lines_inside_it(files):
    _, result = files["apple.html"]
    large = [e for e in result.map["contents"] if e["chars"] > 20000]
    assert large and all(e.get("inside") for e in large)
    risk = next(e for e in large if e["title"].startswith("Item 1A"))
    start, end = map(int, risk["lines"].split("-"))
    assert all(start < h["line"] <= end for h in risk["inside"])


def toc(order, targets=None, place="before", table=True):
    targets = targets or len(order)
    links = [f'<a href="#s{i}">Section {i}</a>' for i in order]
    group = ("<table>" + "".join(f"<tr><td>{a}</td></tr>" for a in links) + "</table>") if table else "<p>" + " ".join(links) + "</p>"
    body = "".join(f'<p id="s{i}">Section {i} body.</p>' for i in range(targets))
    return group + body if place == "before" else body + group


def test_a_group_of_three_ordered_targets_before_them_is_the_contents():
    _, result = rendered(toc([0, 1, 2]))
    assert [e["title"] for e in result.map["contents"]] == ["Section 0", "Section 1", "Section 2"]


def test_two_targets_are_not_a_contents():
    _, result = rendered(toc([0, 1]))
    assert result.map["contents"] is None and result.map["candidates"][0]["targets"] == 2


def test_a_reference_table_out_of_document_order_is_not_the_contents():
    _, result = rendered(toc([3, 0, 4, 1, 5, 2]))
    assert result.map["contents"] is None and result.map["candidates"][0]["ordered"] < 0.9


def test_links_after_their_targets_are_not_the_contents():
    _, result = rendered(toc([0, 1, 2], place="after"))
    assert result.map["contents"] is None and result.map["candidates"][0]["before"] is False


def test_two_equally_large_groups_tie_and_neither_is_chosen():
    first, second = toc([0, 1, 2], targets=0), toc([3, 4, 5], targets=0)
    body = "".join(f'<p id="s{i}">Section {i} body.</p>' for i in range(6))
    _, result = rendered(first + second + body)
    assert result.map["contents"] is None and [c["targets"] for c in result.map["candidates"]] == [3, 3]


def test_contents_split_over_two_tables_choose_the_larger_and_keep_the_other_as_a_candidate():
    first, second = toc([0, 1, 2, 3], targets=0), toc([4, 5, 6], targets=0)
    body = "".join(f'<p id="s{i}">Section {i} body.</p>' for i in range(7))
    _, result = rendered(first + second + body)
    assert [e["title"] for e in result.map["contents"]] == [f"Section {i}" for i in range(4)]
    assert sorted((c["targets"], c["chosen"]) for c in result.map["candidates"]) == [(3, False), (4, True)]


def test_several_links_to_one_target_make_one_entry_with_their_texts_joined():
    group = '<table><tr><td><a href="#s0">Item 1.</a></td><td><a href="#s0">Business</a></td><td><a href="#s0">3</a></td></tr>' \
            '<tr><td><a href="#s1">Item 2.</a></td></tr><tr><td><a href="#s2">Item 3.</a></td></tr></table>'
    body = "".join(f'<p id="s{i}">Section {i} body.</p>' for i in range(3))
    _, result = rendered(group + body)
    assert [e["title"] for e in result.map["contents"]] == ["Item 1. Business 3", "Item 2.", "Item 3."]


def test_the_contents_links_carry_no_markers_but_other_internal_links_do():
    _, result = rendered(toc([0, 1, 2]) + '<p>See <a href="#s1">section one</a>.</p>')
    assert not any(MARK.search(text) for text in lines_of(result) if text.startswith("t0."))
    assert MARK.search(lines_of(result)[-1])


# ---- elements against the independent count ------------------------------------------------------------------------------

@pytest.mark.parametrize("name", list(EXPECTED["elements"]))
def test_images_and_links_match_the_originals_count(files, name):
    expected = EXPECTED["elements"][name]
    _, result = files[name]
    images = [i["url"].rsplit("/", 1)[-1] for i in result.map["images"]]
    internal = [x for x in result.map["links"] if x["kind"] == "internal"]
    external = [x for x in result.map["links"] if x["kind"] == "external"]
    assert (len(images), len(internal), len(external)) == (expected["images"], expected["internal_links"], expected["external_links"])
    assert images[:len(expected["image_sample"])] == expected["image_sample"]
    assert [x["url"] for x in external[:3]] == [s if s.startswith("http") else f"{SOURCE.rsplit('/', 1)[0]}/{s}" for s in expected["external_sample"]]
    assert all(line(result, i["line"]).count("[image:") for i in result.map["images"])
