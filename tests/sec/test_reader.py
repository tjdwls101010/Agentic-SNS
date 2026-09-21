"""Budget paging, table context and position stability over one saved snapshot."""

import gzip
import json
from pathlib import Path

import pytest
import reader
from output import SecError, render
from snapshot import SourceDocument, parse_document
from store import Store

FIXTURES = Path(__file__).parent / 'fixtures' / 'documents'
NBIS = 'https://www.sec.gov/Archives/edgar/data/1513845/000110465926094844/nbis-20260812xex99d2.htm'
BUDGETS = (2000, 12000, 24000)


def build(tmp_path, body, url=NBIS, headers=None):
    store = Store(tmp_path / 'cache')
    source = {'url': url, 'fetched_at': '2026-09-21T15:32:05.719290+00:00'}
    snapshot = parse_document(SourceDocument(body, source, headers or {'content-type': 'text/html'}), store)
    return snapshot, store


@pytest.fixture(scope='module')
def nbis_bytes():
    metadata = json.loads((FIXTURES / 'provenance.json').read_text())['nbis.html']
    return gzip.decompress((FIXTURES / metadata['storage']).read_bytes())


@pytest.fixture
def nbis(tmp_path, nbis_bytes):
    return build(tmp_path, nbis_bytes)


def pages(call, **options):
    """Follow continuations to the end, refusing to loop."""
    collected, cursor = [], None
    for _ in range(600):
        page = call(cursor=cursor, **options)
        collected.append(page)
        cursor = page['next_cursor']
        if not cursor:
            return collected
    raise AssertionError('pagination did not finish')


# --- the table the grid model was designed against ---------------------------------------------


def test_the_whole_equity_table_arrives_in_one_call(nbis):
    snapshot, store = nbis
    result = reader.table(snapshot, store, table_id='table-7')
    assert result['scope_complete'] is True
    body = '\n'.join(row['text'] for row in result['table']['rows'])
    assert len(body) <= 3000, len(body)
    assert len(result['table']['rows']) == 32
    assert ('27|Issuance of pre-funded warrants (Note 14)|—|—|—|2,000.0|—|—|2,000.0|—|2,000.0'
            in body)


def test_the_reported_size_is_what_the_command_actually_prints(nbis):
    snapshot, store = nbis
    for as_json in (False, True):
        result = reader.table(snapshot, store, table_id='table-7', as_json=as_json)
        assert result['returned_chars'] == len(render(result, as_json)) + 1


def test_reading_from_a_match_returns_rows_rather_than_fragments(nbis):
    # In the old model 95% of the lines in this range were eight characters or fewer, because
    # each was one table cell.
    snapshot, store = nbis
    match = reader.find(snapshot, store, query='Issuance of pre-funded warrants')['items'][0]
    result = reader.read(snapshot, store, position=match['position'])
    lines = [line for segment in result['segments'] if segment['kind'] == 'grid'
             for line in (row['text'] for row in segment['rows'])]
    lines += [segment['text'] for segment in result['segments'] if segment['kind'] == 'text']
    body = [line for line in '\n'.join(lines).splitlines() if line.strip()]
    short = [line for line in body if len(line) <= 8]
    assert body
    assert len(short) / len(body) <= 0.20, f'{len(short)}/{len(body)}'


# --- the paging invariants ---------------------------------------------------------------------


@pytest.mark.parametrize('budget', BUDGETS)
@pytest.mark.parametrize('as_json', [False, True])
def test_reading_a_range_in_pages_covers_it_exactly_once(nbis, budget, as_json):
    # A range that spans prose, a whole table and the prose after it, so the sweep crosses every
    # kind of boundary the pager has to split on.
    snapshot, store = nbis
    table = next(t for t in snapshot.data['tables'] if t['table_id'] == 'table-7')
    start = reader.position(snapshot, reader._starts(snapshot)[table['block'] - 2])
    stop = reader.position(snapshot, reader._starts(snapshot)[table['block'] + 3])
    collected = pages(lambda cursor: reader.read(snapshot, store, position=start, end=stop,
                                                 cursor=cursor, budget=budget, as_json=as_json))
    boundaries = [start] + [page['next_position'] for page in collected if page['next_position']]
    assert len(collected) > 1 or budget > min(BUDGETS)
    offsets = [reader._offset(snapshot, value, 0) for value in boundaries]
    assert offsets == sorted(offsets)
    assert len(set(offsets)) == len(offsets)
    assert collected[-1]['scope_complete'] is True
    assert all(page['returned_chars'] <= budget for page in collected)


@pytest.mark.parametrize('budget', BUDGETS)
def test_a_table_read_in_pages_returns_every_row_once(nbis, budget):
    snapshot, store = nbis
    collected = pages(lambda cursor: reader.table(snapshot, store, table_id='table-7',
                                                  cursor=cursor, budget=budget))
    rows = [row['row'] for page in collected for row in page['table']['rows']]
    assert rows == list(range(32))
    assert all(page['returned_chars'] <= budget for page in collected)


def test_a_budget_that_cannot_make_progress_fails_on_the_first_call(nbis):
    snapshot, store = nbis
    with pytest.raises(SecError) as error:
        reader.outline(snapshot, store, budget=reader.MIN_BUDGET - 1)
    assert error.value.code == 'invalid_budget'


def test_a_page_that_cannot_hold_one_row_splits_inside_the_row(tmp_path):
    body = ('<p>lead</p><table><tr><td>' + 'X' * 4000 + '</td><td>42</td></tr>'
            '<tr><td>Total</td><td>43</td></tr></table>').encode()
    snapshot, store = build(tmp_path, body)
    collected = pages(lambda cursor: reader.table(snapshot, store, table_id='table-0',
                                                  cursor=cursor, budget=reader.MIN_BUDGET))
    assert len(collected) > 1
    joined = ''.join(row['text'] for page in collected for row in page['table']['rows'])
    assert 'X' * 3000 in joined
    assert '43' in joined


def test_a_match_position_reads_back_the_match_it_named(nbis):
    snapshot, store = nbis
    for query in ('Issuance of pre-funded warrants', 'Balance as of December 31, 2024', 'Net income'):
        match = reader.find(snapshot, store, query=query)['items'][0]
        excerpt = reader.read(snapshot, store, position=match['position'], end=match['match_end'])
        text = render(excerpt, False)
        assert query.split()[0] in text, query


def test_find_reports_how_many_matches_there_are_not_only_this_page(nbis):
    snapshot, store = nbis
    result = reader.find(snapshot, store, query='Net income', budget=reader.MIN_BUDGET)
    assert result['total_matches'] > len(result['items'])
    assert result['has_more'] is True


# --- what a match in a table says ----------------------------------------------------------------


def test_a_match_inside_a_cell_names_the_table_row_and_column(nbis):
    snapshot, store = nbis
    match = reader.find(snapshot, store, query='Issuance of pre-funded warrants')['items'][0]
    assert match['table_id'] == 'table-7'
    assert match['row'] == 27
    assert match['column'] == 0


def test_a_match_spanning_two_rows_is_not_reported_as_one_place(tmp_path):
    body = b'<table><tr><td>alpha</td></tr><tr><td>beta</td></tr></table>'
    snapshot, store = build(tmp_path, body)
    match = reader.find(snapshot, store, query='alpha\nbeta')['items'][0]
    assert match['row'] == 0 and match['row_end'] == 1


# --- a table's opening rows ------------------------------------------------------------------------


def test_a_page_starting_mid_table_carries_the_rows_that_open_it(nbis):
    snapshot, store = nbis
    match = reader.find(snapshot, store, query='Issuance of pre-funded warrants')['items'][0]
    result = reader.read(snapshot, store, position=match['position'])
    segment = next(s for s in result['segments'] if s['kind'] == 'grid')
    assert segment['rows'][0]['row'] == 27
    assert [row['row'] for row in segment['context_rows']] == list(range(len(segment['context_rows'])))
    assert 'context_truncated' in segment


def test_opening_rows_are_never_the_reason_a_page_fails(nbis):
    # The body is the work; the opening rows are a convenience. A budget that fits one row of
    # body still succeeds, reporting that no opening row fitted.
    snapshot, store = nbis
    match = reader.find(snapshot, store, query='Issuance of pre-funded warrants')['items'][0]
    result = reader.read(snapshot, store, position=match['position'], budget=reader.MIN_BUDGET)
    segment = next(s for s in result['segments'] if s['kind'] == 'grid')
    assert segment['rows']
    assert segment['context_truncated'] is True
    assert result['returned_chars'] <= reader.MIN_BUDGET


def test_the_next_position_never_goes_back_to_a_repeated_opening_row(nbis):
    snapshot, store = nbis
    match = reader.find(snapshot, store, query='Issuance of pre-funded warrants')['items'][0]
    result = reader.read(snapshot, store, position=match['position'], budget=2000)
    start = reader._offset(snapshot, match['position'], 0)
    assert reader._offset(snapshot, result['next_position'], 0) > start


# --- the outline's two emphasis layers ----------------------------------------------------------


def test_the_navigation_layer_groups_a_phrase_and_keeps_its_places(nbis):
    snapshot, store = nbis
    collected = pages(lambda cursor: reader.outline(snapshot, store, kinds=('emphasis',), cursor=cursor))
    items = [item for page in collected for item in page['items']]
    assert items
    assert all('occurrences' in item and item['occurrences'] for item in items)
    assert all('signals' in place for item in items for place in item['occurrences'])


def test_asking_for_emphasis_inside_tables_from_the_navigation_layer_says_why_it_cannot(nbis):
    snapshot, store = nbis
    with pytest.raises(SecError) as error:
        reader.outline(snapshot, store, kinds=('emphasis',), in_tables='only')
    assert error.value.code == 'invalid_argument'
    inside = reader.outline(snapshot, store, kinds=('emphasis',), observations=True, in_tables='only')
    assert inside['items']


# --- the snapshot a position belongs to ------------------------------------------------------------


def test_a_position_from_another_snapshot_is_refused(nbis, tmp_path):
    snapshot, store = nbis
    other, _ = build(tmp_path / 'second', b'<p>Another document entirely.</p>')
    with pytest.raises(SecError) as error:
        reader.read(snapshot, store, position=reader.position(other, 0))
    assert error.value.code == 'invalid_position'


def test_a_snapshot_saved_in_the_previous_format_is_refused_rather_than_reinterpreted(tmp_path):
    # A v1 block number still resolves under v2, to different text.
    from snapshot import load_snapshot

    store = Store(tmp_path / 'cache')
    old = store.save({'version': 1, 'blocks': [], 'tables': [], 'links': [], 'outline': [],
                      'source': {'url': NBIS, 'sha256': store.put(b'x')}, 'dom': store.put(b'y')})
    with pytest.raises(SecError) as error:
        load_snapshot(store, old)
    assert error.value.code == 'unsupported_snapshot_version'


def test_provenance_survives_being_reloaded_in_another_process(tmp_path, nbis_bytes):
    from snapshot import load_snapshot

    snapshot, _ = build(tmp_path, nbis_bytes)
    reloaded = load_snapshot(Store(tmp_path / 'cache'), snapshot.id)
    assert reloaded.data['source']['fetched_at'] == '2026-09-21T15:32:05.719290+00:00'
    assert reloaded.data['source']['content_type'] == 'text/html'


# --- what the independent review of the pager found -----------------------------------------


def test_a_position_inside_a_row_reads_from_there_not_from_the_row_start(nbis):
    # The unit's offset was relative to the selected range while the renderer read it as relative
    # to the row, so a match in a later column came back as the row's opening characters.
    snapshot, store = nbis
    match = next(item for item in reader.find(snapshot, store, query='2,000.0')['items']
                 if item.get('table_id') == 'table-7')
    excerpt = reader.read(snapshot, store, position=match['position'], end=match['match_end'])
    assert '2,000.0' in render(excerpt, False)


def test_every_cell_of_a_row_reads_back_the_text_its_position_named(tmp_path):
    snapshot, store = build(tmp_path, b'<table><tr><td>alpha</td><td>beta</td><td>gamma</td></tr></table>')
    for query in ('alpha', 'beta', 'gamma'):
        match = reader.find(snapshot, store, query=query)['items'][0]
        excerpt = reader.read(snapshot, store, position=match['position'], end=match['match_end'])
        assert query in render(excerpt, False), query


def test_the_separator_between_two_blocks_is_part_of_the_document(tmp_path):
    # The canonical text joins blocks with a newline. A range covering only that newline used to
    # return nothing at all while reporting the range complete.
    snapshot, store = build(tmp_path, b'<p>first</p><p>second</p>')
    match = reader.find(snapshot, store, query='\n')['items'][0]
    excerpt = reader.read(snapshot, store, position=match['position'], end=match['match_end'])
    assert excerpt['scope_complete'] is True
    assert sum(len(s.get('text', '')) for s in excerpt['segments'] if s['kind'] == 'text') == 1


@pytest.mark.parametrize('as_json', [False, True])
def test_a_page_that_reports_more_to_come_returns_something(nbis, as_json):
    # A zero-length unit could fill the page on its own, so the body was empty while has_more
    # said to keep going.
    snapshot, store = nbis
    total = reader._starts(snapshot)[-1]
    for offset in range(0, total, max(1, total // 120)):
        page = reader.read(snapshot, store, position=reader.position(snapshot, offset),
                           budget=reader.MIN_BUDGET, as_json=as_json)
        if not page['has_more']:
            continue
        body = sum(len(s.get('text', '')) for s in page['segments'] if s['kind'] == 'text')
        body += sum(len(row['text']) for s in page['segments'] if s['kind'] == 'grid' for row in s['rows'])
        assert body > 0, f'empty page at {offset}'


@pytest.mark.parametrize('name', ['nbis.html', 'apple.html', 'mrvl.html'])
@pytest.mark.parametrize('as_json', [False, True])
def test_a_whole_document_pages_to_the_end_without_failing_part_way(tmp_path, name, as_json):
    # Failing on a continuation is the one thing the budget contract forbids: a selection that
    # cannot make progress has to say so on the first call.
    metadata = json.loads((FIXTURES / 'provenance.json').read_text())[name]
    body = gzip.decompress((FIXTURES / metadata['storage']).read_bytes())
    snapshot, store = build(tmp_path, body, url=metadata['url'])
    cursor, seen = None, 0
    while True:
        page = reader.read(snapshot, store, cursor=cursor, budget=reader.MIN_BUDGET, as_json=as_json)
        seen += 1
        cursor = page['next_cursor']
        if not cursor:
            break
        assert seen < 4000, 'pagination did not finish'
    assert page['scope_complete'] is True


def test_an_outline_pages_to_the_end_at_the_smallest_budget(tmp_path):
    metadata = json.loads((FIXTURES / 'provenance.json').read_text())['mrvl.html']
    body = gzip.decompress((FIXTURES / metadata['storage']).read_bytes())
    snapshot, store = build(tmp_path, body, url=metadata['url'])
    cursor = None
    for _ in range(4000):
        page = reader.outline(snapshot, store, kinds=('emphasis',), cursor=cursor,
                              budget=reader.MIN_BUDGET)
        cursor = page['next_cursor']
        if not cursor:
            return
    raise AssertionError('pagination did not finish')


def test_the_text_output_says_where_the_rest_of_the_opening_rows_are(nbis):
    # Reporting that the opening rows were cut, without the address to continue from, leaves the
    # reader knowing something is missing and unable to fetch it.
    snapshot, store = nbis
    match = reader.find(snapshot, store, query='Issuance of pre-funded warrants')['items'][0]
    result = reader.read(snapshot, store, position=match['position'], budget=reader.MIN_BUDGET)
    segment = next(s for s in result['segments'] if s['kind'] == 'grid')
    assert segment['context_truncated'] is True
    assert segment['context_next_position'] in render(result, False)


def test_an_opening_row_too_long_to_fit_whole_contributes_what_it_can(tmp_path):
    body = ('<table><tr><td>' + 'H' * 2000 + '</td></tr><tr><td>body</td></tr></table>').encode()
    snapshot, store = build(tmp_path, body)
    table = snapshot.data['tables'][0]
    start = reader.position(snapshot, reader._starts(snapshot)[table['block']] + table['row_ranges'][1][1])
    result = reader.read(snapshot, store, position=start, budget=2400)
    segment = next(s for s in result['segments'] if s['kind'] == 'grid')
    assert segment['context_rows'], 'no part of the opening row was carried'
    assert segment['context_truncated'] is True
    assert result['returned_chars'] <= 2400
