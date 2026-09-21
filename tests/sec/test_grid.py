"""Span occupancy, table-wide column folding, canonical text and nested tables."""

import gzip
import json
import re
from pathlib import Path

import pytest
from grid import build_table, render_rows
from lxml import html
from output import SecError

FIXTURES = Path(__file__).parent / 'fixtures' / 'documents'


def table_of(markup, index=0):
    root = html.fromstring(markup)
    nodes = root.xpath('//table')
    ids = {node: f'table-{i}' for i, node in enumerate(nodes)}
    return build_table(nodes[index], ids[nodes[index]], table_ids=ids)


def nbis_table(index=7):
    metadata = json.loads((FIXTURES / 'provenance.json').read_text())['nbis.html']
    body = gzip.decompress((FIXTURES / metadata['storage']).read_bytes())
    root = html.document_fromstring(re.sub(r'^\s*<\?xml[^?]*\?>', '', body.decode('utf-8', 'replace')))
    nodes = root.xpath('//table')
    ids = {node: f'table-{i}' for i, node in enumerate(nodes)}
    return build_table(nodes[index], ids[nodes[index]], table_ids=ids)


def canonical_rows(table):
    return {row: table['text'][start:end] for row, start, end in table['row_ranges']}


# --- the document the grid model was designed against -------------------------------------


def test_nbis_equity_table_folds_nineteen_original_columns_to_ten():
    table = nbis_table()
    assert table['original_rows'] == 32
    assert table['original_columns'] == 19
    assert table['kept_columns'] == [0, 1, 3, 5, 7, 9, 11, 13, 15, 17]


def test_the_label_row_and_the_value_row_land_in_the_same_columns():
    # Row 5 names nine measures and row 6 reports nine numbers. If folding moved either one,
    # every number in this statement would be attributed to the wrong measure.
    table = nbis_table()
    cells = {(c['row'], c['column']): table['text'][c['text_start']:c['text_end']] for c in table['cells']}
    labels = [(c, t) for (r, c), t in sorted(cells.items()) if r == 5 and t]
    values = [(c, t) for (r, c), t in sorted(cells.items()) if r == 6 and t]
    assert [c for c, _ in labels] == [1, 3, 5, 7, 9, 11, 13, 15, 17]
    assert [t for _, t in labels] == [
        'Shares', 'Amount', 'cost', 'Capital', 'Loss', 'Earnings', 'Nebius Group N.V.', 'interests', 'Equity',
    ]
    assert [c for c, _ in values] == [0, 1, 3, 5, 7, 9, 11, 13, 15, 17]
    assert [t for _, t in values] == [
        'Balance as of December 31, 2024', '235,753,600', '9.2', '(1,968.1)', '2,016.7', '(22.1)', '3,218.0',
        '3,253.7', '—', '3,253.7',
    ]


def test_the_second_period_starts_again_inside_the_same_table():
    # The reason no column meaning is fixed for a whole table: rows 1-13 report the six months
    # to June 2025 and rows 15-31 start over for June 2026, under a second copy of the labels.
    rows = canonical_rows(nbis_table())
    assert 'Six months ended June 30, 2025' in rows[1]
    assert 'Six months ended June 30, 2026' in rows[15]
    assert rows[5].split('\t')[1:] == rows[19].split('\t')[1:]


def test_the_pre_funded_warrant_row_reads_as_one_row_of_values():
    table = nbis_table()
    rows = canonical_rows(table)
    assert rows[27].split('\t') == [
        'Issuance of pre-funded warrants (Note 14)', '—', '—', '—', '2,000.0', '—', '—', '2,000.0', '—', '2,000.0',
    ]


def test_a_span_records_the_original_width_and_the_folded_width_separately():
    # colspan is what the document said; w is how many kept columns it still covers. Reporting
    # one number for both would make a reader compute the other one wrongly.
    table = nbis_table()
    spans = {(s['row'], s['column']): s for s in table['spans']}
    assert spans[(1, 1)]['colspan'] == 17 and spans[(1, 1)]['w'] == 9
    assert spans[(2, 1)]['colspan'] == 3 and spans[(2, 1)]['w'] == 2
    assert all(s['rowspan'] == 1 for s in table['spans'])


def test_the_whole_equity_table_renders_under_the_grid_budget():
    table = nbis_table()
    body = render_rows(table, range(table['original_rows']))
    assert len(body) <= 2500, len(body)
    assert body.splitlines()[27] == (
        '27|Issuance of pre-funded warrants (Note 14)|—|—|—|2,000.0|—|—|2,000.0|—|2,000.0'
    )


# --- span occupancy -----------------------------------------------------------------------


def test_rowspan_zero_reaches_the_end_of_its_own_row_group():
    # HTML says rowspan=0 runs to the end of the row group. Running it to the end of the table
    # silently pulls a heading cell down over every later tbody.
    table = table_of("""
        <table>
          <tbody><tr><td rowspan="0">A</td><td>a1</td></tr><tr><td>a2</td></tr></tbody>
          <tbody><tr><td>B</td><td>b1</td></tr><tr><td>C</td><td>b2</td></tr></tbody>
        </table>
    """)
    cells = {(c['row'], c['column']): table['text'][c['text_start']:c['text_end']] for c in table['cells']}
    assert cells[(0, 0)] == 'A'
    assert cells[(2, 0)] == 'B'
    assert cells[(3, 0)] == 'C'
    span = next(s for s in table['spans'] if (s['row'], s['column']) == (0, 0))
    assert span['rowspan'] == 0 and span['effective_rows'] == 2


def test_rows_outside_any_group_form_one_implicit_group():
    table = table_of('<table><tr><td rowspan="0">A</td><td>a</td></tr><tr><td>b</td></tr></table>')
    cells = {(c['row'], c['column']): table['text'][c['text_start']:c['text_end']] for c in table['cells']}
    assert cells[(1, 1)] == 'b'
    assert (1, 0) not in cells
    assert next(s for s in table['spans'] if s['row'] == 0)['effective_rows'] == 2


def test_a_spanned_cell_keeps_its_text_only_where_it_starts():
    # Copying a rowspan's string into each covered row would multiply both the search hits and
    # the reported values for one phrase that the document states once.
    table = table_of('<table><tr><td rowspan="2">Once</td><td>x</td></tr><tr><td>y</td></tr></table>')
    assert table['text'].count('Once') == 1
    assert len([c for c in table['cells'] if c['row'] == 1]) == 1


def test_overlapping_span_rectangles_are_reported_as_a_structure_error():
    # The old placement checked only the starting column, so a wide cell could be written over
    # a rowspan already holding that ground and the loss was invisible.
    with pytest.raises(SecError) as error:
        table_of("""
            <table>
              <tr><td>a</td><td rowspan="2">held</td></tr>
              <tr><td colspan="3">wide</td></tr>
            </table>
        """)
    assert error.value.code == 'parse_failed'


@pytest.mark.parametrize('markup', [
    '<table><tr><td colspan="-1">x</td></tr></table>',
    '<table><tr><td rowspan="-3">x</td></tr></table>',
    '<table><tr><td colspan="nine">x</td></tr></table>',
    '<table><tr><td colspan="99999">x</td></tr></table>',
])
def test_a_span_outside_the_supported_range_fails_rather_than_being_repaired(markup):
    with pytest.raises(SecError) as error:
        table_of(markup)
    assert error.value.code == 'parse_failed'


# --- what counts as an empty column ---------------------------------------------------------


def test_a_column_is_folded_away_only_when_nothing_originates_in_it():
    table = table_of('<table><tr><td>a</td><td>\u200b</td><td>b</td></tr></table>')
    assert table['kept_columns'] == [0, 2]


def test_a_column_holding_only_an_image_survives_folding():
    # Text-only emptiness would delete a column of charts and leave no trace that it existed.
    root = html.fromstring('<table><tr><td>a</td><td><img src="c.jpg"/></td></tr></table>')
    node = root.xpath('//table')[0]
    image = root.xpath('//img')[0]
    table = build_table(node, 'table-0', table_ids={node: 'table-0'}, link_ids={image: 'link-4'})
    assert table['kept_columns'] == [0, 1]
    cell = next(c for c in table['cells'] if c['column'] == 1)
    assert cell['nonempty_reason'] == 'image'
    assert cell['links'] == ['link-4']


def test_a_column_holding_only_a_child_table_survives_folding():
    table = table_of('<table><tr><td>a</td><td><table><tr><td>inner</td></tr></table></td></tr></table>')
    assert table['kept_columns'] == [0, 1]
    assert next(c for c in table['cells'] if c['column'] == 1)['nonempty_reason'] == 'child_table'


def test_an_entirely_empty_table_keeps_its_identity():
    # Dropping it would move every later anchor onto the following prose.
    table = table_of('<table><tr><td>\u200b</td><td> </td></tr></table>')
    assert table['table_id'] == 'table-0'
    assert table['kept_columns'] == []
    assert table['original_rows'] == 1 and table['original_columns'] == 2
    assert table['text'] == ''


# --- nested tables ---------------------------------------------------------------------------


def test_a_child_table_is_its_own_table_and_its_text_is_not_copied_into_the_parent():
    root = html.fromstring(
        '<div><table><tr><td>before<table><tr><td>inner value</td></tr></table>after</td>'
        '<td>sibling</td></tr></table></div>'
    )
    nodes = root.xpath('//table')
    ids = {node: f'table-{i}' for i, node in enumerate(nodes)}
    parent = build_table(nodes[0], 'table-0', table_ids=ids)
    child = build_table(nodes[1], 'table-1', table_ids=ids, parent=(parent['table_id'], 0, 0))
    assert 'inner value' not in parent['text']
    assert 'inner value' in child['text']
    assert child['parent_table_id'] == 'table-0'
    assert child['parent_cell'] == {'row': 0, 'column': 0}


def test_the_parent_cell_records_where_the_child_table_interrupted_it():
    root = html.fromstring(
        '<table><tr><td>before<table><tr><td>inner</td></tr></table>after</td></tr></table>'
    )
    nodes = root.xpath('//table')
    parent = build_table(nodes[0], 'table-0', table_ids={nodes[0]: 'table-0', nodes[1]: 'table-1'})
    cell = parent['cells'][0]
    kinds = [part['kind'] for part in cell['parts']]
    assert kinds == ['text', 'child_table', 'text']
    assert cell['parts'][1]['child_table_id'] == 'table-1'
    assert parent['text'][cell['parts'][0]['text_start']:cell['parts'][0]['text_end']] == 'before'
    assert parent['text'][cell['parts'][2]['text_start']:cell['parts'][2]['text_end']] == 'after'


def test_a_search_boundary_stands_where_the_child_table_was():
    # Without it "before" and "after" join into a sentence the original never contained.
    root = html.fromstring(
        '<table><tr><td>before<table><tr><td>inner</td></tr></table>after</td></tr></table>'
    )
    nodes = root.xpath('//table')
    parent = build_table(nodes[0], 'table-0', table_ids={nodes[0]: 'table-0', nodes[1]: 'table-1'})
    assert 'beforeafter' not in parent['text']
    assert 'before after' not in parent['text']
    assert '\n' in parent['text']


# --- the original's own declarations ---------------------------------------------------------


def test_an_original_th_declaration_is_kept_and_an_absent_one_invents_nothing():
    table = table_of('<table><tr><th scope="col">Year</th><td>2025</td></tr></table>')
    header, value = table['cells']
    assert header['th'] is True and header['scope'] == 'col'
    assert 'th' not in value and 'scope' not in value
    assert 'header' not in table and 'header' not in value


def test_row_numbers_are_not_renumbered_around_an_empty_row():
    table = table_of('<table><tr><td>a</td></tr><tr><td>\u200b</td></tr><tr><td>c</td></tr></table>')
    assert [row for row, _, _ in table['row_ranges']] == [0, 1, 2]
    assert canonical_rows(table)[1] == ''
    assert canonical_rows(table)[2] == 'c'


def test_a_pipe_or_newline_inside_a_cell_is_escaped_only_in_the_text_rendering():
    table = table_of('<table><tr><td>a|b</td><td>c\\d</td></tr></table>')
    assert 'a|b' in table['text'] and 'c\\d' in table['text']
    assert render_rows(table, [0]) == '0|a\\|b|c\\\\d'
