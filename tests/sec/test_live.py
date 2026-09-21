"""Opt-in checks of the public CLI against SEC, using an isolated cache and the configured identity."""

import json
import os

import pytest
from sec import main

pytestmark = pytest.mark.skipif(
    os.environ.get('SEC_LIVE') != '1', reason='Set SEC_LIVE=1 to use the configured SEC identity.'
)


def test_identified_live_company_filing_search_and_index(tmp_path, capsys):
    def run(*args):
        code = main(['--cache-dir', str(tmp_path / 'cache'), *args, '--json'])
        result = json.loads(capsys.readouterr().out)
        assert code == 0, result
        return result

    assert run('doctor', '--live')['connection'] == 'ok'

    company = run('company', 'AAPL')
    assert company['items'][0]['cik'] == '0000320193'
    assert company['selection_required'] is False

    filings = run('filings', '320193', '--form', '10-K', '--filed-from', '2024-01-01', '--filed-to', '2024-12-31')
    filing = filings['items'][0]
    assert filing['accession'] == '0000320193-24-000123'
    assert filing['report_date'] == '2024-09-28'
    assert filing['filing_date'] != filing['report_date']

    search = run('search', 'competition', '--company', '320193', '--filed-from', '2024-01-01',
                 '--filed-to', '2024-12-31', '--sort', 'relevance')
    assert search['returned'] >= 1
    hit = search['items'][0]
    assert hit['filers'] and all(filer['document_url'].endswith(hit['document']) for filer in hit['filers'])
    assert '_score' not in json.dumps(hit)

    index = run('open', filing['index_url'], '--limit', '100')
    assert index['items'][0]['document'] == 'aapl-20240928.htm'
    assert any(item['document_type'] == 'EX-4.1' for item in index['items'])
    assert any(item['sequence_number'] is None for item in index['items'])

    document = run('open', index['items'][0]['url'], '--max-chars', '24000')
    assert document['status'] == 'parsed' and document['snapshot_id']
    assert document['source']['fetched_at'] and document['source']['content_type']
    assert len(document['tables']) == document['table_count']

    # Everything after this point reads the saved snapshot, so it needs no identity at all.
    empty = tmp_path / 'empty.env'
    empty.write_text('EDGAR_IDENTITY=""')

    def read(*args):
        code = main(['--cache-dir', str(tmp_path / 'cache'), '--env-file', str(empty), *args, '--json'])
        result = json.loads(capsys.readouterr().out)
        assert code == 0, result
        return result

    found = read('find', document['snapshot_id'], 'competition')
    assert found['items'] and found['total_matches'] >= len(found['items'])
    match = found['items'][0]

    excerpt = read('read', document['snapshot_id'], '--position', match['position'],
                   '--end', match['match_end'])
    assert 'competition' in json.dumps(excerpt).casefold()

    sections = read('outline', document['snapshot_id'], '--kind', 'emphasis')
    assert any('Item 1A' in item['text'] for item in sections['items'])

    statement = next(t for t in document['tables'] if t['rows'] > 10 and t['columns'] > 2)
    grid = read('table', document['snapshot_id'], statement['table_id'])
    rows = grid['table']['rows']
    # Rows keep their original numbers, an empty row included, and at least one carries values.
    assert [row['row'] for row in rows] == list(range(len(rows)))
    assert all(row['text'].split('|')[0] == str(row['row']) for row in rows)
    assert any(row['text'].count('|') > 2 for row in rows)
    assert grid['table']['kept_columns'] == sorted(grid['table']['kept_columns'])
