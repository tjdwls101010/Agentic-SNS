"""Public source/snapshot/reader contracts; synthetic cases are explicitly labeled."""
import gzip
import json
import socket
from pathlib import Path

import pytest

from document import SourceDocument, parse_document, load_snapshot
from output import SecError
from reader import read
from store import Store

URL = 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/report.htm'
FIXTURES = Path(__file__).parent / 'fixtures/documents'


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def unexpected_network(*args, **kwargs):
        raise AssertionError('Document parsing and reading must not make network requests')
    monkeypatch.setattr(socket.socket, 'connect', unexpected_network)


def snapshot(tmp_path, body, headers=None):
    store = Store(tmp_path / 'cache')
    return parse_document(SourceDocument(body, {'url': URL}, headers or {}), store), store


def table_pages(doc, store, table_id, **options):
    from reader import table
    pages = [table(doc, store, table_id=table_id, **options)]
    while pages[-1]['has_more']:
        pages.append(table(doc, store, table_id=table_id, cursor=pages[-1]['next_cursor'], **options))
    return pages


def cells(pages):
    return [dict(cell, row=row['row'], header=cell.get('header', row.get('header', False)), position=row['position'])
            for page in pages for row in page['rows'] for cell in row['cells']]


def test_synthetic_no_toc_preserves_direct_tail_inline_text_and_stable_snapshot(tmp_path):
    body = b'<html><body><div>Direct <span>inline</span> tail<div>nested</div> final</div></body></html>'
    doc, store = snapshot(tmp_path, body)
    assert doc.id == parse_document(SourceDocument(body, {'url': URL}), store).id
    assert read(load_snapshot(store, doc.id), store)['text'] == 'Direct inline tail\nnested\nfinal'
    assert doc.data['status'] == 'parsed'


def test_synthetic_long_read_budget_and_reusable_snapshot_bound_cursor(tmp_path):
    text = 'start ' + 'x' * 15000 + ' exact ending'
    doc, store = snapshot(tmp_path, ('<p>' + text + '</p>').encode())
    first = read(doc, store)
    assert len(json.dumps(first, ensure_ascii=False)) <= 12000
    assert first['has_more'] and first['next_cursor']
    second = read(doc, store, cursor=first['next_cursor'])
    pages = [first, second]
    while pages[-1]['has_more']:
        pages.append(read(doc, store, cursor=pages[-1]['next_cursor']))
    assert ''.join(page['text'] for page in pages) == text
    assert all(len(json.dumps(page, ensure_ascii=False)) <= 12000 for page in pages)
    assert second == read(doc, store, cursor=first['next_cursor'])
    other = parse_document(SourceDocument(b'<p>other</p>', {'url': URL}), store)
    with pytest.raises(SecError, match='different'):
        read(other, store, cursor=first['next_cursor'])
    with pytest.raises(SecError):
        read(doc, store, cursor=first['next_cursor'], budget=2000)


def test_synthetic_outline_links_and_find_share_real_anchor_and_position(tmp_path):
    from reader import outline, find, links
    doc, store = snapshot(tmp_path, b'<a href="#risk">Risk factors</a><h2 id="risk">Item 1A. Risk Factors</h2><p>Direct <b>MARKET</b> tail.</p><img src="chart.jpg" alt="Revenue chart"><h2>No anchor heading</h2>')
    entries = outline(doc, store)['items']
    assert any(x['kind'] == 'toc' and x['anchor'] == 'risk' and 'url' not in x for x in entries)
    assert any(x['kind'] == 'heading' and x['text'] == 'No anchor heading' and 'url' not in x for x in entries)
    matches = find(doc, store, query='market')['items']
    assert read(doc, store, position=matches[0]['position'])['text'].startswith('MARKET tail.')
    assert not find(doc, store, query='market', case_sensitive=True)['items']
    images = links(doc, store, kind='image')['items']
    assert images[0]['url'] == URL.rsplit('/', 1)[0] + '/chart.jpg'
    assert images[0]['text'] == 'Revenue chart'


def test_synthetic_table_spans_nested_direct_tail_footnotes_and_long_cells(tmp_path):
    from reader import links, find
    long_cell = 'Direct ' + 'z' * 18000 + ' tail end'
    body = '<h2>Results</h2><p>USD in millions</p><table><tr><th rowspan="2">Metric</th><th colspan="2">2025 and 2024</th></tr><tr><th>2025</th><th>2024</th></tr><tr><td>' + long_cell + '<div>nested <b>bold</b> tail</div> after<a href="#fn">1</a><img src="cell.jpg"><table><tr><td>inner</td></tr></table>end</td><td>42</td><td>41</td></tr></table><p id="fn">1. Includes subsidiaries.</p>'
    doc, store = snapshot(tmp_path, body.encode())
    tables = doc.summary()['tables']
    assert len(tables) == 2
    pages = table_pages(doc, store, tables[0]['table_id'])
    assert len(pages) > 1
    found = cells(pages)
    assert any(x.get('rowspan') == 2 and x['header'] for x in found)
    assert any(x.get('colspan') == 2 and x['text'] == '2025 and 2024' for x in found)
    fragments = [x for x in found if x['row'] == 2 and x['column'] == 0 and 'text' in x]
    assert ''.join(x['text'] for x in fragments) == long_cell + ' nested bold tail after1innerend'
    assert fragments[0]['text_complete'] is False and 'text_complete' not in fragments[-1]
    assert 'USD in millions' in ' '.join(part['text'] for part in pages[0]['context'])
    assert any('Includes subsidiaries' in note['text'] for note in pages[0]['footnotes'])
    assert all('context' not in page for page in pages[1:])
    assert links(doc, store, kind='image')['items'][0]['url'].endswith('/cell.jpg')
    assert find(doc, store, query='tail end')['items']
    assert all(len(json.dumps(page, ensure_ascii=False)) <= 12000 for page in pages)


def test_synthetic_encoding_conflict_and_loss_are_reported(tmp_path):
    doc, store = snapshot(tmp_path, b'<meta charset="windows-1252"><p>Price \x80 42 \x97 caf\xe9</p>', {'Content-Type': 'text/html; charset=utf-8'})
    assert read(doc, store)['text'] == 'Price € 42 — café'
    assert doc.data['encoding']['selected'] == 'windows-1252'
    assert doc.data['encoding']['conflict'] is True
    assert doc.data['encoding']['loss'] is False
    lossy, _ = snapshot(tmp_path, '<p>bad � text</p>'.encode())
    assert lossy.data['encoding']['loss'] is True


def test_synthetic_xml_paths_repeated_records_tail_and_external_entity_disabled(tmp_path):
    from reader import find
    body = b'<?xml version="1.0"?><!DOCTYPE ownershipDocument [<!ENTITY leak SYSTEM "file:///etc/passwd">]><ownershipDocument><transaction><shares>10</shares><owner>A</owner></transaction><transaction><shares>20</shares><owner>B</owner></transaction><note>before<b>bold</b>after &leak;</note></ownershipDocument>'
    doc, store = snapshot(tmp_path, body, {'Content-Type': 'application/xml'})
    assert doc.data['format'] == 'xml'
    result = find(doc, store, query='20')['items'][0]
    block = read(doc, store, position=result['position'])['items'][0]
    assert block['path'] == '/ownershipDocument[1]/transaction[2]/shares[1]'
    assert block['parent'] == '/ownershipDocument[1]/transaction[2]'
    values = [item['text'] for item in read(doc, store)['items']]
    assert 'read' not in read(doc, store)
    assert not any('root:' in value for value in values)
    assert 'before' in values and 'bold' in values and 'after' in values
    assert not doc.data['extraction_complete']
    assert 'external_entities_not_expanded' in doc.data['warnings']


def test_real_old_sgml_preserves_document_boundaries_and_plain_text(tmp_path):
    doc, store = snapshot(tmp_path, (FIXTURES / 'old.txt').read_bytes(), {'Content-Type': 'text/plain'})
    assert doc.data['format'] == 'sgml'
    documents = [block for block in doc.data['blocks'] if block['kind'] == 'document']
    assert [block['document_type'] for block in documents] == ['24F-2NT', 'EX-99.11']
    assert 'COMMON SENSE TRUST' in read(doc, store)['text']
    all_text = []
    result = read(doc, store)
    while True:
        all_text.append(result['text'])
        if not result['has_more']:
            break
        result = read(doc, store, cursor=result['next_cursor'])
    assert '<TYPE>EX-99.11' in ''.join(all_text)
    assert '</DOCUMENT>' in ''.join(all_text)


def test_synthetic_plain_text_preserves_whitespace_and_has_no_toc(tmp_path):
    from reader import outline
    doc, store = snapshot(tmp_path, b'1995 report\n\nA     B\n10    20\n')
    assert read(doc, store)['text'] == '1995 report\n\nA     B\n10    20\n'
    assert outline(doc, store)['items'] == []


def fixture_bytes(name):
    metadata = json.loads((FIXTURES / 'provenance.json').read_text())[name]
    body = (FIXTURES / metadata.get('storage', name)).read_bytes()
    return gzip.decompress(body) if metadata.get('compression') == 'gzip' else body


def real_snapshot(tmp_path, name):
    provenance = json.loads((FIXTURES / 'provenance.json').read_text())[name]
    store = Store(tmp_path / 'cache')
    return parse_document(SourceDocument(fixture_bytes(name), provenance), store), store


def test_real_asml_twelve_original_images_and_text_are_explicitly_incomplete(tmp_path):
    from reader import links, find
    doc, store = real_snapshot(tmp_path, 'asml.html')
    images = links(doc, store, kind='image')['items']
    assert len(images) == 12
    assert images[0]['url'].endswith('/financialstatementsusgaa001.jpg')
    assert images[-1]['url'].endswith('/financialstatementsusgaa012.jpg')
    assert find(doc, store, query='ASML Financial statements US GAAP Q2 2026')['items']
    assert not doc.summary()['extraction_complete']
    assert 'image_content_not_extracted' in doc.summary()['warnings']


@pytest.mark.parametrize('body,content_type', [(b'%PDF-1.7\nsource', 'application/pdf'), (b'\x89PNG\r\n\x1a\n', 'image/png')])
def test_synthetic_unsupported_media_exposes_original_source(tmp_path, body, content_type):
    doc, store = snapshot(tmp_path, body, {'Content-Type': content_type})
    assert doc.summary()['status'] == 'unsupported'
    result = read(doc, store)
    assert not result['extraction_complete']
    assert result['source_url'] == URL
    assert result['status'] == 'unsupported'


def test_real_microsoft_risk_tail_remains_findable_and_readable(tmp_path):
    from reader import find
    doc, store = real_snapshot(tmp_path, 'microsoft.html')
    expected = json.loads((FIXTURES / 'expected.json').read_text())['microsoft']['risk_tail']
    result = find(doc, store, query='The unionization of significant employee populations')
    assert result['items']
    excerpt = read(doc, store, position=result['items'][0]['position'])['text']
    assert expected in excerpt
    assert 'ITEM 1B' in excerpt.upper()


def test_real_apple_table_preserves_years_units_values_and_spans(tmp_path):
    doc, store = real_snapshot(tmp_path, 'apple.html')
    pages = table_pages(doc, store, 'table-22')
    assert all(len(json.dumps(page, ensure_ascii=False, indent=2)) <= 12000 for page in pages)
    found = cells(pages)
    text = '\n'.join(x['text'] for x in found if 'text' in x)
    for expected in ['September 28, 2024', 'September 30, 2023', 'September 24, 2022', '391,035', '383,285', '394,328']:
        assert expected in text
    assert any('In millions, except number of shares' in part['text'] for part in pages[0]['context'])
    assert any(x.get('colspan') == 15 and x['text'] == 'Years ended' for x in found)
    assert not any(x.get('text') == '' for x in found)


def test_real_form4_preserves_holding_path(tmp_path):
    from reader import find
    doc, store = real_snapshot(tmp_path, 'form4.xml')
    result = find(doc, store, query='9913.797')['items'][0]
    item = read(doc, store, position=result['position'])['items'][0]
    assert item['path'] == '/ownershipDocument[1]/nonDerivativeTable[1]/nonDerivativeHolding[1]/postTransactionAmounts[1]/sharesOwnedFollowingTransaction[1]/value[1]'
    assert find(doc, store, query='MICROSOFT CORP')['items']


def test_synthetic_modified_snapshot_data_and_corrupt_saved_sources_are_rejected(tmp_path):
    doc, store = snapshot(tmp_path, b'<p>Original content</p>')
    loaded = load_snapshot(store, doc.id)
    loaded.data['blocks'][0]['text'] = 'Tampered'
    with pytest.raises(SecError):
        read(loaded, store)
    (store.root / doc.data['source']['sha256']).write_bytes(b'corruption')
    with pytest.raises(SecError) as error:
        load_snapshot(store, doc.id)
    assert error.value.code == 'cache_corrupt'


def test_synthetic_non_document_record_and_malformed_xml_have_actionable_errors(tmp_path):
    store = Store(tmp_path / 'cache')
    with pytest.raises(SecError):
        load_snapshot(store, store.save({'arbitrary': 'record'}))
    with pytest.raises(SecError) as error:
        parse_document(SourceDocument(b'<?xml version="1.0"?><broken>', {'url': URL}), store)
    assert error.value.code == 'parse_failed'


def test_synthetic_budget_covers_pretty_output_and_reports_remaining_scope(tmp_path):
    doc, store = snapshot(tmp_path, ('<p>' + 'A' * 19000 + '</p>').encode())
    result = read(doc, store, budget=2000)
    assert len(json.dumps(result, ensure_ascii=False, indent=2)) + 1 <= 2000
    assert result['scope_complete'] is False
    assert result['remaining_items'] == 1
    assert read(doc, store, position=result['next_position'])['text'].startswith('A')


def test_synthetic_long_nested_cell_fragments_keep_valid_document_positions(tmp_path):
    doc, store = snapshot(tmp_path, ('<table><tr><td>short<div>' + 'B' * 6000 + '</div>tail</td></tr></table>').encode())
    for cell in cells(table_pages(doc, store, 'table-0', budget=2000)):
        read(doc, store, position=cell['position'])


def test_synthetic_many_tables_are_discoverable_with_bounded_open_and_outline(tmp_path):
    from reader import outline
    doc, store = snapshot(tmp_path, ('<html>' + '<table><tr><td>value</td></tr></table>' * 25 + '</html>').encode())
    summary = doc.summary()
    assert len(summary['tables']) == 20
    assert summary['table_count'] == 25 and summary['tables_has_more']
    records = []
    page = outline(doc, store)
    while True:
        records.extend(page['items'])
        if not page['has_more']:
            break
        page = outline(doc, store, cursor=page['next_cursor'])
    assert len([x for x in records if x['kind'] == 'table']) == 25


def test_synthetic_empty_xml_reference_attributes_are_readable_without_declaration(tmp_path):
    store = Store(tmp_path / 'cache')
    source = SourceDocument(b'<ownershipDocument><footnoteId id="F1"/><footnotes><footnote id="F1">Stock award</footnote></footnotes></ownershipDocument>', {'url': URL.replace('.htm', '.xml')})
    doc = parse_document(source, store)
    assert doc.data['format'] == 'xml'
    result = read(doc, store)
    assert any(x.get('attributes') == {'id': 'F1'} and x['path'].endswith('/footnoteId[1]') for x in result['items'])


def test_synthetic_table_exposes_cell_image_links_and_context(tmp_path):
    from reader import table, links
    doc, store = snapshot(tmp_path, b'<p>Balance sheet</p><table><tr><td>Assets <img src="assets.jpg" alt="Asset breakdown"><a href="#f1">1</a></td></tr></table><p id="f1">Includes cash</p>')
    result = table(doc, store, table_id='table-0')
    assert result['context'] == [{'text': 'Balance sheet'}, {'text': 'Includes cash'}]
    (cell,) = result['rows'][0]['cells']
    assert cell['text'] == 'Assets 1'
    assert {'kind': 'image', 'text': 'Asset breakdown', 'url': URL.rsplit('/', 1)[0] + '/assets.jpg'} in cell['links']
    assert {'kind': 'internal', 'text': '1', 'anchor': 'f1'} in cell['links']
    assert result['footnotes'] == [{'text': 'Includes cash', 'anchor': 'f1'}]
    image = links(doc, store, kind='image')['items'][0]
    assert image['context_position']
    assert read(doc, store, position=image['context_position'])['text']


def test_synthetic_inline_image_and_unresolved_links_do_not_become_fake_toc(tmp_path):
    from reader import outline, links
    doc, store = snapshot(tmp_path, b'<img src="cover.jpg" alt="Cover"><a href="#missing">Missing</a>')
    assert links(doc, store, kind='image')['items'][0]['url'].endswith('/cover.jpg')
    unresolved = links(doc, store, kind='internal')['items'][0]
    assert unresolved['target_resolved'] is False
    assert not any(x['kind'] == 'toc' for x in outline(doc, store)['items'])


def test_synthetic_find_cursor_rejects_query_operation_changes_and_corruption(tmp_path):
    from reader import find
    doc, store = snapshot(tmp_path, ('<p>' + 'needle ' * 30 + '</p>').encode())
    result = find(doc, store, query='needle', budget=1100)
    assert result['has_more']
    with pytest.raises(SecError):
        find(doc, store, query='other', budget=1100, cursor=result['next_cursor'])
    with pytest.raises(SecError):
        read(doc, store, budget=1100, cursor=result['next_cursor'])
    (store.root / result['next_cursor']).write_bytes(b'corrupt cursor')
    with pytest.raises(SecError) as error:
        find(doc, store, query='needle', budget=1100, cursor=result['next_cursor'])
    assert error.value.code == 'cache_corrupt'


# Synthetic source cases supplied by the independent stage-3 review.
def test_review_nested_table_keeps_separate_numeric_cells(tmp_path):
    from reader import table
    doc, store = snapshot(tmp_path, b'<table><tr><td><table><tr><td>10</td><td>20</td></tr><tr><td>30</td><td>40</td></tr></table></td></tr></table>')
    outer = table(doc, store, table_id='table-0')['rows'][0]['cells'][0]
    assert outer['text'] == '10 20 30 40'
    assert read(doc, store)['text'] == '10\n20\n30\n40'


@pytest.mark.parametrize('markup', ['micro<span id="x">soft</span> tail', 'micro<a name="x"></a>soft tail', '  micro <span id="x">soft</span> tail'])
def test_review_inline_anchors_preserve_text_and_exact_offsets(tmp_path, markup):
    from reader import find, outline
    doc, store = snapshot(tmp_path, ('<html><p>' + markup + '</p><a href="#x">jump</a></html>').encode())
    expected = 'micro soft tail' if markup.startswith('  ') else 'microsoft tail'
    assert read(doc, store)['text'] == expected + '\njump'
    assert find(doc, store, query=expected)['items']
    navigation = outline(doc, store, kinds=('anchor', 'internal_link'))['items']
    anchor = next(x for x in navigation if x['kind'] == 'anchor')
    assert set(anchor) == {'kind', 'text', 'position'} and anchor['text'] == 'x'
    assert read(doc, store, position=anchor['position'])['text'].startswith('soft tail')
    target = next(x for x in navigation if x['kind'] == 'internal_link')
    assert target['position'] == anchor['position']


def test_review_next_position_preserves_unreturned_block_separator(tmp_path):
    store = Store(tmp_path / 'cache')
    source = SourceDocument(('<p>' + 'A' * 1500 + '</p><p>END</p>').encode(), {'url': 'https://www.sec.gov/Archives/edgar/data/1/report.htm'})
    doc = parse_document(source, store)
    first = read(doc, store, budget=1024)
    assert first['has_more']
    assert first['text'] + read(doc, store, position=first['next_position'])['text'] == 'A' * 1500 + '\nEND'
    assert read(doc, store, position=f'{doc.id}:0:1500', end=f'{doc.id}:1:0')['text'] == '\n'
    assert first['next_position'].startswith(doc.id[:10] + ':')


@pytest.mark.parametrize('headers', [{'Content-Type': 'application/xml'}, {'Content-Type': 'text/xml'}, {}])
def test_review_explicit_xml_retains_record_context_despite_html_tag_names(tmp_path, headers):
    doc, store = snapshot(tmp_path, b'<?xml version="1.0"?><root><record><p>First</p></record><record><p>Second</p></record></root>', headers)
    assert doc.data['format'] == 'xml'
    items = read(doc, store)['items']
    assert [x['parent'] for x in items] == ['/root[1]/record[1]', '/root[1]/record[2]']
    assert [x['path'] for x in items] == ['/root[1]/record[1]/p[1]', '/root[1]/record[2]/p[1]']


@pytest.mark.parametrize('query,expected', [('alpha\nbeta', 'alpha\nbeta'), ('\nbeta\n', '\nbeta\n'), ('beta\ngamma', 'beta\ngamma'), ('ALPHA\nBETA\nGAMMA', 'alpha\nbeta\ngamma')])
def test_review_find_and_read_share_canonical_cross_block_ranges(tmp_path, query, expected):
    from reader import find
    doc, store = snapshot(tmp_path, b'<p>alpha</p><p>beta</p><p>gamma</p>')
    hits = find(doc, store, query=query)['items']
    assert len(hits) == 1
    assert read(doc, store, position=hits[0]['position'], end=hits[0]['match_end'])['text'] == expected
    if query.isupper():
        assert not find(doc, store, query=query, case_sensitive=True)['items']
    many, _ = snapshot(tmp_path, b'<p>x</p>' * 40)
    first = find(many, store, query='\n', budget=1024)
    assert first['has_more']
    second = find(many, store, query='\n', budget=1024, cursor=first['next_cursor'])
    for page in [first, second]:
        for hit in page['items']:
            assert read(many, store, position=hit['position'], end=hit['match_end'])['text'] == '\n'
    assert len(first['items']) + len(second['items']) < 39


@pytest.mark.parametrize('prefix', ['ix', 'inline'])
def test_nonbody_inline_xbrl_metadata_is_distinct_from_readable_report(tmp_path, prefix):
    from reader import find
    body = (f'<html xmlns:{prefix}="http://www.xbrl.org/2013/inlineXBRL"><body>'
            f'<div style="display:none"><{prefix}:header><{prefix}:hidden>MACHINE_ONLY_FACT'
            f'</{prefix}:hidden></{prefix}:header></div><h1>Annual report</h1>'
            '<p>Visible narrative.</p></body></html>').encode()
    doc, store = snapshot(tmp_path, body)
    assert read(doc, store)['text'] == 'Annual report\nVisible narrative.'
    assert find(doc, store, query='MACHINE_ONLY_FACT')['items'] == []
    assert store.get(doc.data['source']['sha256']) == body
    assert doc.data['warnings']


def test_nonbody_metadata_is_excluded_from_table_cell_text_too(tmp_path):
    from reader import table
    body = (b'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body><table><tr><td>'
            b'100<ix:header><ix:hidden>MACHINE_ONLY_FACT</ix:hidden></ix:header> units'
            b'</td></tr></table></body></html>')
    doc, store = snapshot(tmp_path, body)
    assert 'MACHINE_ONLY_FACT' not in read(doc, store)['text']
    assert table(doc, store, table_id='table-0')['rows'][0]['cells'][0]['text'] == '100 units'


# Output density: the snapshot argument already names the copy, so positions carry only block:offset.
def test_positions_name_their_snapshot_by_fingerprint(tmp_path):
    from reader import find, outline
    doc, store = snapshot(tmp_path, b'<h2 id="a">Alpha</h2><p>beta gamma</p>')
    short = doc.id[:10]
    hit = find(doc, store, query='gamma')['items'][0]
    assert hit['position'] == f'{short}:1:5' and hit['match_end'] == f'{short}:2:0'
    assert read(doc, store, position=f'{short}:1:5')['text'] == 'gamma'
    assert read(doc, store, position=f'{doc.id}:1:5', end=f'{short}:1:10')['text'] == 'gamma'
    assert outline(doc, store)['items'][0]['position'] == f'{short}:0:0'
    with pytest.raises(SecError) as bare:
        read(doc, store, position='1:5')
    assert bare.value.code == 'invalid_position'
    other = parse_document(SourceDocument(b'<p>other</p>', {'url': URL}), store)
    with pytest.raises(SecError) as error:
        read(doc, store, position=f'{other.id}:0:0')
    assert error.value.code == 'invalid_position'


def test_contents_links_to_one_target_merge_into_one_entry_and_table_header_skips_empty_rows(tmp_path):
    from reader import outline
    body = (b'<table><tr><td><a href="#i1">Item 1.</a></td><td><a href="#i1">Business</a></td><td><a href="#i1">1</a></td></tr>'
            b'<tr><td><a href="#i2">Item 2.</a></td><td><a href="#i2">Properties</a></td></tr></table>'
            b'<h2 id="i1">Item 1. Business</h2><p>Sales:</p><table><tr><td></td><td></td></tr><tr><td>Region</td><td></td><td>2025</td></tr></table><h2 id="i2">Item 2. Properties</h2>')
    doc, store = snapshot(tmp_path, body)
    items = outline(doc, store)['items']
    toc = [x for x in items if x['kind'] == 'toc']
    assert [x['text'] for x in toc] == ['Item 1. Business 1', 'Item 2. Properties']
    assert toc[0]['anchor'] == 'i1'
    table_entry = next(x for x in items if x['kind'] == 'table' and x['table_id'] == 'table-1')
    assert table_entry['header'] == 'Region | 2025' and table_entry['context'] == 'Sales:'


def test_reader_pages_are_bounded_by_budget_alone(tmp_path):
    from reader import outline
    body = ''.join(f'<h2>Heading {i}</h2>' for i in range(60)).encode()
    doc, store = snapshot(tmp_path, body)
    page = outline(doc, store)
    assert len(page['items']) == 60 and page['scope_complete']
    small = outline(doc, store, budget=1024)
    assert 0 < len(small['items']) < 60 and small['has_more'] and small['next_cursor']


def test_table_anchor_to_a_container_of_the_table_is_not_a_footnote(tmp_path):
    from reader import table
    body = (b'<html><body><div id="top"><p>Annual report</p>'
            b'<table><tr><td>Revenue <a href="#top">top</a> <a href="#note">2</a></td></tr></table>'
            b'</div><p><a name="note"></a></p><p>2. Revenue excludes returns.</p></body></html>')
    doc, store = snapshot(tmp_path, body)
    result = table(doc, store, table_id='table-0')
    assert result.get('footnotes') == [{'text': '2. Revenue excludes returns.', 'anchor': 'note'}]
    links = result['rows'][0]['cells'][0]['links']
    assert {'kind': 'internal', 'text': 'top', 'anchor': 'top'} in links


def test_contents_link_inside_a_table_is_navigation_not_a_footnote(tmp_path):
    from reader import table, outline
    body = (b'<html><body><table><tr><td><a href="#item1">Item 1. Business</a></td>'
            b'<td>Revenue <a href="#fn1">(1)</a></td></tr></table>'
            b'<h2 id="item1">Item 1. Business</h2><p>Narrative.</p>'
            b'<p id="fn1">(1) Excludes returns.</p></body></html>')
    doc, store = snapshot(tmp_path, body)
    result = table(doc, store, table_id='table-0')
    assert result['footnotes'] == [{'text': '(1) Excludes returns.', 'anchor': 'fn1'}]
    anchors = [link['anchor'] for cell in result['rows'][0]['cells'] for link in cell.get('links', [])]
    assert anchors == ['item1', 'fn1']
    assert any(x['kind'] == 'toc' and x['anchor'] == 'item1' for x in outline(doc, store)['items'])


def test_mixed_header_row_keeps_which_cell_is_a_header_and_keeps_open_rowspans(tmp_path):
    from reader import table
    body = (b'<table><tr><th>Revenue</th><td>42</td></tr>'
            b'<tr><th rowspan="0">Segment</th><td>Americas</td></tr>'
            b'<tr><th>2025</th><th>2024</th></tr></table>')
    doc, store = snapshot(tmp_path, body)
    mixed, spanning, headers = table(doc, store, table_id='table-0')['rows']
    assert all('header' not in row for row in (mixed, spanning, headers))
    assert mixed['cells'][0]['header'] is True and 'header' not in mixed['cells'][1]
    assert spanning['cells'][0]['rowspan'] == 0
    assert all(cell['header'] is True for cell in headers['cells'])


def test_selecting_no_records_still_obeys_the_budget_and_every_row_keeps_a_position(tmp_path):
    from reader import table
    body = ('<p>' + 'C' * 1500 + '</p><table><tr><td></td><td></td></tr>'
            '<tr><td>' + 'X' * 1300 + '<a href="https://example.com/note">note</a></td><td>42</td></tr>'
            '<tr><td>Total</td><td>43</td></tr></table>').encode()
    doc, store = snapshot(tmp_path, body)
    empty = table(doc, store, table_id='table-0', rows='0', budget=1024)
    assert empty['rows'] == [] and empty['returned_chars'] <= 1024
    assert empty['has_more'] and 'C' * 100 in empty['context'][0]['text']
    # Framing pages with the rows, so even the smallest allowed budget makes progress instead of refusing the table.
    smallest = table(doc, store, table_id='table-0', budget=1024)
    assert smallest['returned_chars'] <= 1024 and smallest['has_more']
    for budget in (1024, 3000, 12000):
        pages = table_pages(doc, store, 'table-0', budget=budget)
        assert all(len(json.dumps(page, ensure_ascii=False, indent=2)) + 1 <= budget for page in pages)
        assert all('position' in row for page in pages for row in page['rows'])
        assert [cell for cell in cells(pages) if cell.get('text') == '42']
        fragments = [cell for cell in cells(pages) if cell['column'] == 0 and cell['row'] == 1]
        assert ''.join(cell.get('text', '') for cell in fragments) == 'X' * 1300 + 'note'
        assert any(cell.get('links') for cell in fragments)


def test_footnote_is_the_note_beside_the_anchor_and_never_a_navigation_section(tmp_path):
    from reader import table
    adjacent = (b'<html><body><div><table><tr><td>Revenue <a href="#n">(1)</a></td></tr></table>'
                b'<a id="n"></a><p>(1) Excludes returns.</p></div></body></html>')
    doc, store = snapshot(tmp_path, adjacent)
    assert table(doc, store, table_id='table-0')['footnotes'] == [{'text': '(1) Excludes returns.', 'anchor': 'n'}]
    navigation = (b'<html><body><table><tr><td>Revenue <a href="#n">see</a></td></tr></table>'
                  b'<div><p>Overview.</p><h2 id="n">Business</h2><p>Unrelated narrative.</p></div></body></html>')
    doc, store = snapshot(tmp_path, navigation)
    result = table(doc, store, table_id='table-0')
    assert 'footnotes' not in result
    assert result['rows'][0]['cells'][0]['links'] == [{'kind': 'internal', 'text': 'see', 'anchor': 'n'}]


def test_inline_anchor_keeps_its_whole_note_and_a_standalone_anchor_uses_the_next_block(tmp_path):
    from reader import table
    inline = (b'<html><body><table><tr><td>Revenue <a href="#n">(1)</a></td></tr></table>'
              b'<p><a id="n"></a>Excludes <b>returns</b>.</p></body></html>')
    doc, store = snapshot(tmp_path, inline)
    assert table(doc, store, table_id='table-0')['footnotes'] == [{'text': 'Excludes returns.', 'anchor': 'n'}]
    standalone = (b'<html><body><div><table><tr><td>Revenue <a href="#n">(1)</a></td></tr></table>'
                  b'<a id="n"></a><p>Excludes returns.</p></div></body></html>')
    doc, store = snapshot(tmp_path, standalone)
    assert table(doc, store, table_id='table-0')['footnotes'] == [{'text': 'Excludes returns.', 'anchor': 'n'}]


def test_xml_range_read_keeps_a_newline_the_original_contains(tmp_path):
    from reader import find
    doc, store = snapshot(tmp_path, b'<root><n>A\nB</n><m>C</m></root>', {'Content-Type': 'application/xml'})
    hit = find(doc, store, query='B')['items'][0]
    assert read(doc, store, end=hit['position'])['items'][0]['text'] == 'A\n'
    assert read(doc, store)['items'][0]['text'] == 'A\nB'


def test_a_header_cell_split_across_pages_does_not_make_its_row_a_header_row(tmp_path):
    body = ('<table><tr><th>' + 'Revenue ' * 250 + '</th><td>42</td></tr></table>').encode()
    doc, store = snapshot(tmp_path, body)
    pages = table_pages(doc, store, 'table-0', budget=1024)
    assert len(pages) > 1
    assert all('header' not in row for page in pages for row in page['rows'])
    found = cells(pages)
    assert all(cell.get('header') for cell in found if cell['column'] == 0)
    assert not any(cell.get('header') for cell in found if cell['column'] == 1)


def test_a_split_context_and_caption_say_they_are_partial(tmp_path):
    from reader import table
    body = ('<p>' + 'C' * 1500 + '</p><table><caption>' + 'K' * 1500 + '</caption>'
            '<tr><td>42</td></tr></table>').encode()
    doc, store = snapshot(tmp_path, body)
    first = table(doc, store, table_id='table-0', budget=1024)
    assert first['context'][0]['text_complete'] is False
    assert 0 < len(first['context'][0]['text']) < 1500
    pages = table_pages(doc, store, 'table-0', budget=1024)
    assert ''.join(part['text'] for page in pages for part in page.get('context', [])) == 'C' * 1500
    assert ''.join(page['caption']['text'] for page in pages if 'caption' in page) == 'K' * 1500
    whole = table(doc, store, table_id='table-0', budget=24000)
    assert whole['context'] == [{'text': 'C' * 1500}] and whole['caption'] == {'text': 'K' * 1500}


def test_a_marker_anchor_yields_the_note_it_marks_not_the_marker(tmp_path):
    from reader import table
    body = (b'<html><body><table><tr><td>Revenue <a href="#n">(1)</a></td></tr></table>'
            b'<p><a id="n">(1)</a> Excludes <b>returns</b>.</p></body></html>')
    doc, store = snapshot(tmp_path, body)
    assert table(doc, store, table_id='table-0')['footnotes'] == [
        {'text': '(1) Excludes returns.', 'anchor': 'n'}
    ]


def test_table_context_includes_the_prose_that_follows_it(tmp_path):
    from reader import table
    body = (b'<html><body><p>Cash and equivalents (in millions):</p>'
            b'<table><tr><th>Type</th><th>2025</th></tr><tr><td>Cash</td><td>29,943</td></tr></table>'
            b'<p>(1) Includes $2.6 billion of restricted cash.</p>'
            b'<p>Unrelated later section.</p></body></html>')
    doc, store = snapshot(tmp_path, body)
    context = [part['text'] for part in table(doc, store, table_id='table-0')['context']]
    assert 'Cash and equivalents (in millions):' in context
    assert '(1) Includes $2.6 billion of restricted cash.' in context
