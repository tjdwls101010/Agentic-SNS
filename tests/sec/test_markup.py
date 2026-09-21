"""Blocks, links, anchors and emphasis observations from one HTML document."""

import gzip
import json
import re
from pathlib import Path

import pytest
from lxml import html
from markup import parse_html

FIXTURES = Path(__file__).parent / 'fixtures' / 'documents'
URL = 'https://www.sec.gov/Archives/edgar/data/1/000000000000000001/x.htm'


def parse(markup, url=URL):
    blocks, outline, links, tables, excluded = parse_html(markup, url)
    return {'blocks': blocks, 'outline': outline, 'links': links, 'tables': tables, 'excluded': excluded}


def canonical(result):
    return '\n'.join(block['text'] for block in result['blocks'])


def fixture_text(name):
    metadata = json.loads((FIXTURES / 'provenance.json').read_text())[name]
    raw = (FIXTURES / metadata.get('storage', name)).read_bytes()
    body = gzip.decompress(raw) if metadata.get('compression') == 'gzip' else raw
    return body.decode('utf-8', 'replace')


def dom_characters(text):
    """Every character the original would show, with the layout characters normalization drops."""
    root = html.document_fromstring(re.sub(r'^\s*<\?xml[^?]*\?>', '', text))
    # Inline XBRL header and hidden sections are filing metadata, not the report: the reader
    # drops them, so the comparison has to as well or it would measure that decision instead.
    hidden = [n for n in root.iter()
              if isinstance(n.tag, str) and n.tag.lower().split(':')[-1] in ('hidden', 'header')
              and ':' in n.tag]
    for node in [*root.xpath('//script | //style | //head'), *hidden]:
        if node.getparent() is not None:
            node.getparent().remove(node)
    return re.sub(r'[\s\u200b]+', '', ''.join(root.itertext()))


# --- a table is one block ----------------------------------------------------------------


def test_a_table_becomes_one_block_instead_of_one_block_per_cell():
    # 92% of NBIS blocks were single table cells, so reading the document returned a fragment
    # per cell with no way to see which number belonged to which measure.
    result = parse('<p>Before</p><table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>')
    kinds = [block['kind'] for block in result['blocks']]
    assert kinds == ['text', 'grid']
    assert result['blocks'][1]['text'] == 'a\tb\nc\td'
    assert result['blocks'][1]['table_id'] == 'table-0'


def test_the_table_record_names_the_block_that_holds_its_grid():
    result = parse('<p>Before</p><table><tr><td>a</td></tr></table>')
    table = result['tables'][0]
    assert result['blocks'][table['block']]['table_id'] == table['table_id']


def test_an_empty_table_still_occupies_a_block_of_its_own():
    # Dropping it would slide every later position onto the following prose.
    result = parse('<p>Before</p><table><tr><td>\u200b</td></tr></table><p>After</p>')
    assert [block['kind'] for block in result['blocks']] == ['text', 'grid', 'text']
    assert result['blocks'][1]['text'] == ''
    assert result['tables'][0]['table_id'] == 'table-0'


def test_a_child_table_follows_its_parent_block_in_dom_order():
    # Flat order is not browser order, which is why the parent grid keeps a reference where the
    # child interrupted it rather than the child being emitted as if it were free-standing prose.
    result = parse(
        '<table><tr><td>outer<table><tr><td>inner</td></tr></table></td></tr></table><p>After</p>'
    )
    assert [block.get('table_id') for block in result['blocks']] == ['table-0', 'table-1', None]
    assert 'inner' not in result['blocks'][0]['text']
    assert result['tables'][1]['parent_table_id'] == 'table-0'
    assert result['tables'][1]['parent_cell'] == {'row': 0, 'column': 0}


# --- nothing lost, nothing duplicated ------------------------------------------------------


@pytest.mark.parametrize('name', ['nbis.html', 'apple.html', 'mrvl.html', 'microsoft.html'])
def test_every_character_of_the_original_appears_exactly_once(name):
    # The comparison ignores whitespace and layout characters on both sides, so it measures
    # loss and duplication rather than the spacing rules.
    text = fixture_text(name)
    result = parse(text)
    assert canonical(result).replace('\t', '').replace('\n', '') and dom_characters(text)
    assert re.sub(r'[\s\u200b]+', '', canonical(result)) == dom_characters(text)


@pytest.mark.parametrize(
    ('name', 'blocks'), [('nbis.html', 450), ('apple.html', 800), ('mrvl.html', 1000)]
)
def test_the_block_count_falls_to_roughly_one_per_passage(name, blocks):
    # Diagnostic, not a contract: NBIS 5,591, Apple 3,124 and MRVL 3,532 blocks were almost all
    # single cells. The bound here only catches a regression back to a cell-per-block model.
    assert len(parse(fixture_text(name))['blocks']) < blocks


# --- positions still point at the same text -------------------------------------------------


def test_an_anchor_inside_a_table_cell_points_at_that_cell_text():
    result = parse('<table><tr><td>a</td><td id="here">the cell</td></tr></table>')
    anchor = next(item for item in result['outline'] if item['kind'] == 'anchor')
    block = result['blocks'][anchor['block']]
    assert block['text'][anchor['offset']:].startswith('the cell')
    assert anchor['table_id'] == 'table-0' and anchor['row'] == 0 and anchor['column'] == 1


def test_an_anchor_in_prose_points_at_the_text_it_marks():
    result = parse('<p>Before</p><p>Lead in <span id="here">marked text</span> and after.</p>')
    anchor = next(item for item in result['outline'] if item['kind'] == 'anchor')
    block = result['blocks'][anchor['block']]
    assert block['text'][anchor['offset']:].startswith('marked text')


def test_a_link_inside_a_table_carries_the_cell_it_sits_in():
    result = parse('<table><tr><td>Revenue <a href="https://example.com/n">note</a></td></tr></table>')
    link = result['links'][0]
    assert link['table_id'] == 'table-0' and link['row'] == 0 and link['column'] == 0
    assert link['url'] == 'https://example.com/n'


def test_an_image_link_is_the_same_item_the_cell_points_to():
    # A column kept alive only by an image is useless unless the image itself is reachable.
    result = parse('<table><tr><td>a</td><td><img src="chart.jpg" alt="Q1"/></td></tr></table>')
    image = next(link for link in result['links'] if link['kind'] == 'image')
    cell = next(c for c in result['tables'][0]['cells'] if c['column'] == 1)
    assert cell['nonempty_reason'] == 'image'
    assert cell['links'] == [image['id']]
    assert image['url'].endswith('/chart.jpg')


# --- what the original declares, and what it does not ----------------------------------------


def test_inline_xbrl_hidden_metadata_is_not_reading_text():
    markup = ('<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
              '<ix:hidden><p>0000320193FY</p></ix:hidden><p>Readable report.</p></body></html>')
    result = parse(markup)
    assert canonical(result) == 'Readable report.'
    assert result['excluded'] is True


def test_metadata_is_excluded_from_a_table_cell_as_well():
    markup = ('<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body><table><tr>'
              '<td><ix:hidden>hidden</ix:hidden>Revenue</td></tr></table></body></html>')
    assert canonical(parse(markup)) == 'Revenue'


# --- emphasis observations -------------------------------------------------------------------


def emphasis(result, navigation=None):
    return [item for item in result['outline']
            if item['kind'] == 'emphasis' and (navigation is None or item['navigation'] is navigation)]


def expected_sections(name):
    return json.loads((FIXTURES / 'expected-sections.json').read_text())['documents'][name]


def test_an_inline_bold_run_is_an_observation_with_its_evidence():
    # The SDK reported a heading with no way to check it. An observation carries what it saw.
    result = parse('<p>Plain body text that runs on.</p>'
                   '<p style="font-weight:700;text-align:center">Risk Factors</p>')
    item = emphasis(result)[0]
    assert item['text'] == 'Risk Factors'
    assert item['signals']['bold_fraction'] == 1.0
    assert item['signals']['alignment'] == 'center'
    assert item['signals']['all_caps'] is False


def test_bold_is_recognised_by_keyword_and_by_number():
    # Two of the four measured filings write font-weight:bold and two write 700.
    for declaration in ('font-weight:bold', 'font-weight:700', 'font-weight:bolder'):
        assert emphasis(parse(f'<p style="{declaration}">Heading</p>'))
    assert not emphasis(parse('<p style="font-weight:400">Heading</p>'))


def test_a_b_tag_is_a_signal_even_with_no_inline_style():
    assert emphasis(parse('<p><b>Bold heading</b></p>'))
    assert emphasis(parse('<p><i>Italic aside</i></p>'))


def test_a_heading_tag_is_an_observation_without_any_inline_style():
    # No measured filing has one, but where a document declares a heading that is the declaration.
    item = emphasis(parse('<h2>Business</h2>'))[0]
    assert item['navigation'] is True


def test_the_same_content_is_not_counted_twice_through_its_parent():
    # Microsoft splits a line into many spans; counting a parent and its child both would make
    # bold_fraction exceed one and blow up the observation count.
    item = emphasis(parse('<p style="font-weight:bold"><span><span>Risk Factors</span></span></p>'))[0]
    assert item['signals']['bold_fraction'] == 1.0


def test_a_partly_bold_paragraph_reports_the_fraction_it_measured():
    result = parse('<p><b>Item 1A.</b> The rest of this paragraph is ordinary body text here.</p>')
    item = emphasis(result)[0]
    assert 0.0 < item['signals']['bold_fraction'] < 0.3
    assert item['text'].startswith('Item 1A. The rest')


def test_an_emphasized_item_number_is_navigation_even_when_the_paragraph_runs_on():
    # In one holdout 10-K the emphasized run is a truncated prefix inside a paragraph that
    # continues into the section's prose, so requiring emphasis to cover the block loses it.
    result = parse('<p><b>Item 1A. R</b>isk Factors In addition to the other information in this report, '
                   'the risks described below should be considered carefully.</p>')
    assert emphasis(result, navigation=True)


def test_a_body_paragraph_in_the_same_size_is_not_navigation():
    result = parse('<p style="font-size:10pt">' + 'Ordinary sentence. ' * 20 + '</p>'
                   '<p style="font-size:10pt">Another ordinary sentence with nothing emphasized.</p>')
    assert emphasis(result, navigation=True) == []


def test_the_body_size_is_measured_from_the_document_rather_than_assumed():
    # Apple's body runs at 9pt and Microsoft's at 10pt, so a fixed "12pt or larger" threshold
    # calls every line in one document a heading and none in the other.
    body = '<p style="font-size:9pt">' + 'Ordinary sentence. ' * 20 + '</p>'
    result = parse(body * 5 + '<p style="font-size:14pt">Larger Line</p>')
    item = next(x for x in emphasis(result) if x['text'] == 'Larger Line')
    assert item['signals']['font_size_ratio'] == pytest.approx(14 / 9, rel=0.01)
    assert item['navigation'] is True


def test_with_no_body_paragraph_to_measure_the_size_signal_is_not_used_at_all():
    # Size means larger than this document's running text. With no running text to measure, a
    # 14pt line is not evidence of anything, and the ratio is absent rather than invented.
    assert emphasis(parse('<p style="font-size:14pt">Larger Line</p>')) == []
    item = emphasis(parse('<p style="font-size:14pt;font-weight:bold">Larger Line</p>'))[0]
    assert item['signals']['font_size_ratio'] is None


def test_a_long_emphasized_passage_is_not_discarded_for_its_length():
    # A 180-character limit dropped 15 emphasized blocks from Apple, including real risk wording.
    long_line = 'Item 1A. Risk Factors ' + 'and a very long emphasized sentence that keeps going ' * 6
    result = parse(f'<p style="font-weight:bold">{long_line}</p>')
    assert len(emphasis(result, navigation=True)) == 1
    assert emphasis(result)[0]['text'] == long_line.strip()


def test_a_contents_row_of_links_is_not_navigation():
    result = parse('<p style="font-weight:bold"><a href="#a">Item 1. Business</a></p><h2 id="a">Item 1</h2>')
    assert [item['text'] for item in emphasis(result, navigation=True)] == ['Item 1']


def test_emphasis_inside_a_table_belongs_to_the_table_and_is_not_navigation():
    # Every ITEM heading in one holdout 20-F sits in a table cell, so an empty navigation layer
    # there is the true observation and the rows still have to be reachable.
    result = parse('<table><tr><td style="font-weight:bold">ITEM 4 INFORMATION ON THE COMPANY</td></tr></table>')
    item = emphasis(result)[0]
    assert item['navigation'] is False
    assert item['table_id'] == 'table-0' and item['row'] == 0
    assert item['text'] == 'ITEM 4 INFORMATION ON THE COMPANY'


def test_every_observation_carries_the_signals_it_was_judged_on():
    result = parse(fixture_text('apple.html'))
    items = emphasis(result)
    assert items
    assert all(set(item['signals']) == {'bold_fraction', 'font_size_ratio', 'alignment', 'all_caps'}
               for item in items)


@pytest.mark.parametrize('name', ['apple.html', 'microsoft.html', 'mrvl.html'])
def test_every_section_boundary_of_the_original_is_reachable(name):
    # The expected list was read from the original DOM before this rule existed.
    result = parse(fixture_text(name))
    reached = {item['text'] for item in emphasis(result, navigation=True)}
    missing = [text for text in expected_sections(name) if text not in reached]
    assert missing == []


def test_a_repeated_page_header_keeps_every_place_it_occurs():
    # Microsoft prints PART II 61 times: one section boundary, one contents link, and 59 small
    # centred page marks. Collapsing the phrase to one position would make the two audit reports
    # and the several Competition sections unreachable, so every occurrence keeps its own place.
    # Their signals differ, which is why one set of signals cannot be attached to the group: 59
    # of these are not bold and would be reported as bold section headings if it were.
    result = parse(fixture_text('microsoft.html'))
    places = [item for item in emphasis(result) if item['text'] == 'PART II']
    assert len(places) > 10
    assert len({item['block'] for item in places}) == len(places)
    assert len({item['signals']['bold_fraction'] for item in places}) > 1
    assert [item for item in places if item['navigation']]


def test_a_financial_statement_exhibit_honestly_has_no_section_layer():
    # NBIS is an exhibit with no Item structure at all; an empty navigation layer is the fact.
    assert expected_sections('nbis.html') == {}
