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
    assert any(x['kind'] == 'toc' and x['url'] == URL + '#risk' for x in entries)
    assert any(x['kind'] == 'heading' and x['text'] == 'No anchor heading' and x['url'] == URL for x in entries)
    matches = find(doc, store, query='market')['items']
    assert read(doc, store, position=matches[0]['position'])['text'].startswith('MARKET tail.')
    assert not find(doc, store, query='market', case_sensitive=True)['items']
    images = links(doc, store, kind='image')['items']
    assert images[0]['url'] == URL.rsplit('/', 1)[0] + '/chart.jpg'
    assert images[0]['text'] == 'Revenue chart'


def test_synthetic_table_spans_nested_direct_tail_footnotes_and_long_cells(tmp_path):
    from reader import table, links, find
    long_cell = 'Direct ' + 'z' * 18000 + ' tail end'
    body = '<h2>Results</h2><p>USD in millions</p><table><tr><th rowspan="2">Metric</th><th colspan="2">2025 and 2024</th></tr><tr><th>2025</th><th>2024</th></tr><tr><td>' + long_cell + '<div>nested <b>bold</b> tail</div> after<a href="#fn">1</a><img src="cell.jpg"><table><tr><td>inner</td></tr></table>end</td><td>42</td><td>41</td></tr></table><p id="fn">1. Includes subsidiaries.</p>'
    doc, store = snapshot(tmp_path, body.encode())
    tables = doc.summary()['tables']
    assert len(tables) == 2
    result = table(doc, store, table_id=tables[0]['table_id'])
    pages = [result]
    while pages[-1]['has_more']:
        pages.append(table(doc, store, table_id=tables[0]['table_id'], cursor=pages[-1]['next_cursor']))
    items = [item for page in pages for item in page['items']]
    cells = [x for x in items if x['kind'] == 'cell']
    assert any(x['rowspan'] == 2 and x['header'] for x in cells)
    assert any(x['colspan'] == 2 and x['text'] == '2025 and 2024' for x in cells)
    fragments = [x['text'] for x in cells if x['row'] == 2 and x['column'] == 0]
    assert ''.join(fragments) == long_cell + ' nested bold tail after1innerend'
    assert any('USD in millions' in x['text'] for x in items if x['kind'] == 'context')
    assert any(x['kind'] == 'footnote' and 'Includes subsidiaries' in x['text'] for x in items)
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
    text = read(doc, store)['text']
    assert 'root:' not in text
    assert 'before' in text and 'bold' in text and 'after' in text
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
    from reader import table
    doc, store = real_snapshot(tmp_path, 'apple.html')
    page = table(doc, store, table_id='table-22')
    items = []
    while True:
        items.extend(page['items'])
        assert len(json.dumps(page, ensure_ascii=False)) <= 12000
        if not page['has_more']:
            break
        page = table(doc, store, table_id='table-22', cursor=page['next_cursor'])
    text = '\n'.join(x['text'] for x in items)
    for expected in ['September 28, 2024', 'September 30, 2023', 'September 24, 2022', '391,035', '383,285', '394,328', 'In millions, except number of shares']:
        assert expected in text
    assert any(x.get('colspan') == 15 and x['text'] == 'Years ended' for x in items)


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
    from reader import table
    doc, store = snapshot(tmp_path, ('<table><tr><td>short<div>' + 'B' * 6000 + '</div>tail</td></tr></table>').encode())
    page = table(doc, store, table_id='table-0', budget=2000)
    while True:
        for item in page['items']:
            read(doc, store, position=item['position'])
        if not page['has_more']:
            break
        page = table(doc, store, table_id='table-0', budget=2000, cursor=page['next_cursor'])


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
    records = table(doc, store, table_id='table-0')['items']
    assert any(x['kind'] == 'image' and x['url'].endswith('/assets.jpg') and x['row'] == 0 for x in records)
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
    result = find(doc, store, query='needle', limit=3)
    with pytest.raises(SecError):
        find(doc, store, query='other', limit=3, cursor=result['next_cursor'])
    with pytest.raises(SecError):
        read(doc, store, limit=3, cursor=result['next_cursor'])
    (store.root / result['next_cursor']).write_bytes(b'corrupt cursor')
    with pytest.raises(SecError) as error:
        find(doc, store, query='needle', limit=3, cursor=result['next_cursor'])
    assert error.value.code == 'cache_corrupt'


# Synthetic source cases supplied by the independent stage-3 review.
def test_review_nested_table_keeps_separate_numeric_cells(tmp_path):
    from reader import table
    doc, store = snapshot(tmp_path, b'<table><tr><td><table><tr><td>10</td><td>20</td></tr><tr><td>30</td><td>40</td></tr></table></td></tr></table>')
    outer = table(doc, store, table_id='table-0')['items'][0]
    assert outer['text'] == '10 20 30 40'
    assert read(doc, store)['text'] == '10\n20\n30\n40'


@pytest.mark.parametrize('markup', ['micro<span id="x">soft</span> tail', 'micro<a name="x"></a>soft tail', '  micro <span id="x">soft</span> tail'])
def test_review_inline_anchors_preserve_text_and_exact_offsets(tmp_path, markup):
    from reader import find, outline
    doc, store = snapshot(tmp_path, ('<html><p>' + markup + '</p><a href="#x">jump</a></html>').encode())
    expected = 'micro soft tail' if markup.startswith('  ') else 'microsoft tail'
    assert read(doc, store)['text'] == expected + '\njump'
    assert find(doc, store, query=expected)['items']
    anchor = next(x for x in outline(doc, store)['items'] if x['kind'] == 'anchor')
    assert anchor['url'] == URL + '#x'
    assert read(doc, store, position=anchor['position'])['text'].startswith('soft tail')
    target = next(x for x in outline(doc, store)['items'] if x['kind'] == 'internal_link')
    assert target['position'] == anchor['position']


def test_review_next_position_preserves_unreturned_block_separator(tmp_path):
    store = Store(tmp_path / 'cache')
    source = SourceDocument(('<p>' + 'A' * 101 + '</p><p>END</p>').encode(), {'url': 'https://www.sec.gov/Archives/edgar/data/1/report.htm'})
    doc = parse_document(source, store)
    first = read(doc, store, budget=1024)
    assert first['has_more']
    assert first['text'] + read(doc, store, position=first['next_position'])['text'] == 'A' * 101 + '\nEND'
    assert read(doc, store, position=f'{doc.id}:0:101', end=f'{doc.id}:1:0')['text'] == '\n'


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
    first = find(doc, store, query='\n', limit=1)
    assert first['has_more']
    second = find(doc, store, query='\n', limit=1, cursor=first['next_cursor'])
    for page in [first, second]:
        hit = page['items'][0]
        assert read(doc, store, position=hit['position'], end=hit['match_end'])['text'] == '\n'
    assert not second['has_more']


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
    cells = [item for item in table(doc, store, table_id='table-0')['items'] if item['kind'] == 'cell']
    assert cells[0]['text'] == '100 units'
