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
