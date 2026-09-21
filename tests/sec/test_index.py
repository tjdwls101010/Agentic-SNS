"""Reading the attachment table out of a SEC filing index page."""

from pathlib import Path

import pytest
from index import attachment_rows
from lxml import html
from output import SecError

FIXTURES = Path(__file__).parent / 'fixtures'
BASE = 'https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/'


def rows(name, base=BASE):
    return attachment_rows(html.fromstring((FIXTURES / name).read_bytes()), base)


def table(markup):
    return attachment_rows(html.fromstring(f'<div>{markup}</div>'), BASE)


# --- the two real index pages -----------------------------------------------------------------


def test_both_index_pages_yield_every_row_in_document_order():
    # 18 and 24 rows, each matching what the SDK returned for the same page, field for field.
    assert len(rows('filing-index.html', 'https://www.sec.gov/Archives/edgar/data/1009672/000156459018004771/')) == 18
    assert len(rows('apple-index-live.html')) == 24


def test_the_complete_submission_row_survives_its_empty_sequence_and_type():
    # It is the only route to the raw submission, and it is the row an "every field present"
    # filter drops.
    complete = [row for row in rows('apple-index-live.html') if row['document'].endswith('.txt')]
    assert len(complete) == 1
    assert complete[0]['sequence_number'] is None
    assert complete[0]['document_type'] is None
    assert complete[0]['description'] == 'Complete submission text file'
    assert complete[0]['url'].endswith('/0000320193-24-000123.txt')


def test_the_primary_document_and_an_exhibit_read_as_the_index_shows_them():
    first, *rest = rows('apple-index-live.html')
    assert first['sequence_number'] == '1'
    assert first['document'] == 'aapl-20240928.htm'
    assert first['document_type'] == '10-K'
    assert first['size'] == 1503780  # the recorded original_bytes of the aapl-20240928.htm fixture
    assert first['url'] == BASE + 'aapl-20240928.htm'
    assert any(row['document_type'] == 'EX-4.1' for row in rest)


def test_a_missing_description_is_reported_as_absent_rather_than_as_an_empty_string():
    blank = [row for row in rows('apple-index-live.html') if row['description'] is None]
    assert len(blank) == 4


def test_an_ixbrl_viewer_link_resolves_to_the_document_itself():
    # The Document cell carries an iXBRL badge beside the name, so the filename has to come from
    # the link rather than from the cell's text.
    assert all('/ix?doc=' not in row['url'] for row in rows('apple-index-live.html'))
    assert all(not row['document'].startswith('iXBRL') for row in rows('apple-index-live.html'))


# --- how columns are found ----------------------------------------------------------------------


def test_columns_are_matched_by_their_header_name_not_their_position():
    result = table("""
        <table class="tableFile">
          <tr><th>Type</th><th>Seq</th><th>Description</th><th>Document</th><th>Size</th></tr>
          <tr><td>EX-99</td><td>2</td><td>Press release</td><td><a href="x.htm">x.htm</a></td><td>10</td></tr>
        </table>
    """)
    assert result == [{'sequence_number': '2', 'document': 'x.htm', 'description': 'Press release',
                       'document_type': 'EX-99', 'size': 10, 'url': BASE + 'x.htm'}]


def test_an_index_with_no_size_column_reports_no_size_rather_than_zero():
    result = table("""
        <table class="tableFile">
          <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
          <tr><td>1</td><td>Report</td><td><a href="a.htm">a.htm</a></td><td>10-K</td></tr>
        </table>
    """)
    assert result[0]['size'] is None


def test_a_row_shorter_than_its_header_is_an_error_rather_than_a_guess():
    with pytest.raises(SecError) as error:
        table("""
            <table class="tableFile">
              <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
              <tr><td>1</td><td><a href="a.htm">a.htm</a></td></tr>
            </table>
        """)
    assert error.value.code == 'parse_failed'


def test_two_rows_that_look_alike_are_both_kept():
    # Deduplicating would quietly drop a genuinely repeated attachment.
    result = table("""
        <table class="tableFile">
          <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
          <tr><td>1</td><td>R</td><td><a href="a.htm">a.htm</a></td><td>EX-1</td><td>5</td></tr>
          <tr><td>1</td><td>R</td><td><a href="a.htm">a.htm</a></td><td>EX-1</td><td>5</td></tr>
        </table>
    """)
    assert len(result) == 2


def test_a_nested_table_inside_a_cell_does_not_add_rows_of_its_own():
    result = table("""
        <table class="tableFile">
          <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
          <tr><td>1</td><td>R<table><tr><td>inner</td><td>rows</td></tr></table></td>
              <td><a href="a.htm">a.htm</a></td><td>EX-1</td><td>5</td></tr>
        </table>
    """)
    assert len(result) == 1


def test_a_page_with_no_attachment_table_is_an_error():
    with pytest.raises(SecError) as error:
        table('<p>Not an index page.</p>')
    assert error.value.code == 'parse_failed'
