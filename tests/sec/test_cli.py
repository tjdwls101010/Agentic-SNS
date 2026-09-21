"""The public contract: argument handling, projections, error envelopes and the schema."""

import gzip
import json
from pathlib import Path

import pytest
from sec import DESCRIPTIONS, RECOVERY, schema

FIXTURES = Path(__file__).parent / 'fixtures'
APPLE = 'https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/'
INDEX = APPLE + '0000320193-24-000123-index.html'


def fixture(name):
    return (FIXTURES / name).read_bytes()


def document(name):
    metadata = json.loads((FIXTURES / 'documents' / 'provenance.json').read_text())[name]
    raw = (FIXTURES / 'documents' / metadata.get('storage', name)).read_bytes()
    return gzip.decompress(raw) if metadata.get('compression') == 'gzip' else raw


# --- what each discovery command returns ---------------------------------------------------


def test_a_ticker_match_names_the_company_and_says_no_choice_is_needed(cli):
    cli.replies.append(('company_tickers', 200, json.loads(fixture('tickers-live.json')), {}))
    code, result = cli('company', 'AAPL')
    assert code == 0
    assert result['items'] == [{'cik': '0000320193', 'name': 'Apple Inc.', 'tickers': ['AAPL'],
                                'match': 'exact_ticker'}]
    assert result['selection_required'] is False


def test_a_name_lookup_reports_filing_hits_rather_than_a_count_of_companies(cli):
    # The SEC total counts filings that mention the name. Calling it "total" beside a list of
    # candidates read as "there are this many companies".
    # A multi-word name cannot be a ticker, so only the name lookup is made.
    cli.replies.append(('entityName', 200, json.loads(fixture('company-name-live.json')), {}))
    code, result = cli('company', 'Apple Hospitality')
    assert code == 0
    assert 'total' not in result
    assert result['filing_hits']['value'] > len(result['items'])
    assert result['filing_hits']['relation'] in ('eq', 'gte')
    assert result['selection_required'] is True
    assert all(item['match'] == 'name_candidate' and item['tickers'] is None for item in result['items'])


def test_a_filing_row_is_the_fields_a_reader_chooses_a_document_with(cli):
    cli.replies.append(('CIK0000320193', 200, json.loads(fixture('apple-submissions.json')), {}))
    code, result = cli('filings', '320193', '--form', '10-K', '--limit', '1')
    assert code == 0
    row = result['items'][0]
    assert set(row) == {'accession', 'cik', 'form', 'filing_date', 'report_date',
                        'primary_document', 'index_url', 'document_url', 'items'}
    assert row['form'] == '10-K'
    assert row['filing_date'] != row['report_date']
    assert row['index_url'].endswith('-index.html')
    assert 'isXBRL' not in json.dumps(result)


def test_a_search_hit_groups_its_filers_with_each_filer_url(cli):
    # One filing can have several filers and each gets its own archive path, so a bare list of
    # URLs cannot say which CIK any of them belongs to.
    cli.replies.append(('search-index', 200, json.loads(fixture('efts-live.json')), {}))
    code, result = cli('search', 'competition', '--company', '320193')
    assert code == 0
    hit = result['items'][0]
    assert set(hit) == {'accession', 'document', 'form', 'file_type', 'file_date',
                        'period_ending', 'filers'}
    assert all(set(filer) == {'cik', 'name', 'document_url'} for filer in hit['filers'])
    assert all(filer['document_url'].endswith(hit['document']) for filer in hit['filers'])


def test_the_search_infrastructure_fields_are_not_returned(cli):
    cli.replies.append(('search-index', 200, json.loads(fixture('efts-live.json')), {}))
    _, result = cli('search', 'competition', '--company', '320193')
    body = json.dumps(result)
    for field in ('_index', '_score', '"sort"', 'xsl', 'film_num', 'sics', 'biz_states', 'inc_states'):
        assert field not in body, field
    assert result['total']['value'] >= result['returned']


def test_a_remote_total_is_not_the_number_returned(cli):
    cli.replies.append(('search-index', 200, json.loads(fixture('efts-live.json')), {}))
    _, result = cli('search', 'competition', '--company', '320193', '--limit', '1')
    assert result['returned'] == 1
    assert result['total']['value'] > 1


# --- open --------------------------------------------------------------------------------------


def test_opening_an_index_lists_its_attachments(cli):
    cli.replies.append(('-index.html', 200, fixture('apple-index-live.html'), {'Content-Type': 'text/html'}))
    code, result = cli('open', INDEX, '--limit', '100')
    assert code == 0
    assert result['returned'] == 24
    assert result['items'][0]['document'] == 'aapl-20240928.htm'
    assert any(item['sequence_number'] is None for item in result['items'])


def test_opening_a_document_lists_every_table_rather_than_a_hidden_twenty(cli):
    # summary() used to cut the list to twenty before --limit was read, so --limit 100 looked
    # as though the document had twenty tables.
    cli.replies.append(('aapl-20240928.htm', 200, document('apple.html'), {'Content-Type': 'text/html'}))
    code, result = cli('open', APPLE + 'aapl-20240928.htm', '--max-chars', '24000')
    assert code == 0
    assert result['table_count'] > 20
    assert len(result['tables']) == result['table_count']
    assert result['next_cursor'] is None
    assert 'tables_has_more' not in result


def test_a_table_list_too_long_for_the_budget_continues_rather_than_being_cut(cli):
    cli.replies.append(('aapl-20240928.htm', 200, document('apple.html'), {'Content-Type': 'text/html'}))
    code, first = cli('open', APPLE + 'aapl-20240928.htm', '--max-chars', '2000')
    assert code == 0 and first['next_cursor']
    assert first['returned_chars'] <= 2000
    code, second = cli('open', APPLE + 'aapl-20240928.htm', '--max-chars', '2000',
                       '--cursor', first['next_cursor'])
    assert code == 0
    assert second['tables'][0]['table_id'] != first['tables'][0]['table_id']


def test_a_layout_table_shows_itself_as_having_no_values(cli):
    cli.replies.append(('aapl-20240928.htm', 200, document('apple.html'), {'Content-Type': 'text/html'}))
    _, result = cli('open', APPLE + 'aapl-20240928.htm', '--max-chars', '24000')
    assert any(table['columns'] == 0 for table in result['tables'])


# --- reading through the CLI ---------------------------------------------------------------------


@pytest.fixture
def opened(cli):
    cli.replies.append(('nbis-', 200, document('nbis.html'), {'Content-Type': 'text/html'}))
    code, result = cli('open', APPLE + 'nbis-20260812xex99d2.htm', '--max-chars', '24000')
    assert code == 0
    return result['snapshot_id']


def test_a_reader_command_needs_no_identity(cli, opened):
    empty = cli.identity.parent / 'empty.env'
    empty.write_text('EDGAR_IDENTITY=""')
    from sec import main

    assert main(['--env-file', str(empty), '--cache-dir', str(cli.cache), 'table', opened, 'table-7']) == 0


def test_the_text_mode_of_every_reader_command_is_readable(cli, opened):
    code, text = cli.text('table', opened, 'table-7', '--rows', '26-27')
    assert code == 0
    assert 'Issuance of pre-funded warrants (Note 14)|—|—|—|2,000.0' in text
    assert not text.lstrip().startswith('{')
    for command, extra in (('outline', []), ('find', ['pre-funded']), ('links', []),
                           ('read', ['--max-chars', '2000'])):
        code, out = cli.text(command, opened, *extra)
        assert code == 0, out
        assert not out.lstrip().startswith('{'), command
        assert out.count('\n') > 2, command


def test_the_printed_size_matches_the_reported_size_in_both_modes(cli, opened):
    _, text = cli.text('table', opened, 'table-7')
    reported = int(next(line for line in text.splitlines() if line.startswith('returned_chars: ')).split()[-1])
    assert reported == len(text)
    _, result = cli('table', opened, 'table-7')
    assert result['returned_chars'] == len(cli.last_output)


def test_a_position_survives_a_round_trip_through_the_command_line(cli, opened):
    code, found = cli('find', opened, 'Issuance of pre-funded warrants')
    assert code == 0
    match = found['items'][0]
    assert match['table_id'] == 'table-7' and match['row'] == 27
    code, excerpt = cli('read', opened, '--position', match['position'], '--end', match['match_end'])
    assert code == 0
    assert 'Issuance of pre-funded warrants' in json.dumps(excerpt)


def test_asking_the_navigation_layer_for_table_emphasis_explains_itself(cli, opened):
    code, result = cli('outline', opened, '--kind', 'emphasis', '--in-tables', 'only')
    assert code == 2
    assert result['error']['code'] == 'invalid_argument'
    assert 'observation' in result['error']['fix'] or '--all' in result['error']['fix']


# --- cursors and errors ---------------------------------------------------------------------------


def test_a_cursor_from_the_previous_contract_is_refused(cli):
    from store import Store

    store = Store(cli.cache)
    stale = store.save({'query': {'command': 'filings', 'query': '320193'},
                        'state': {'pending': [], 'sources': [], 'exhausted': True}})
    code, result = cli('filings', '320193', '--cursor', stale)
    assert code == 2
    assert result['error']['code'] == 'cursor_mismatch'


def test_a_bare_accession_will_not_guess_the_filing_company(cli):
    code, result = cli('open', '0000320193-24-000123')
    assert code == 2
    assert result['error']['code'] == 'company_required'


def test_a_configuration_problem_is_reported_with_its_source_and_exit_code(cli):
    broken = cli.identity.parent / 'broken.env'
    broken.write_text('EDGAR_IDENTITY="not-an-email"\n')
    from sec import main

    code = main(['--env-file', str(broken), '--cache-dir', str(cli.cache), 'doctor', '--json'])
    assert code == 2


# --- the schema owns the contract -------------------------------------------------------------------


def test_every_command_describes_its_own_recovery_options_and_exit_codes():
    for name in DESCRIPTIONS:
        scoped = schema(name)
        assert scoped['commands'] == {name: scoped['commands'][name]}
        assert scoped['global_options'] and scoped['global_options_note']
        assert scoped['exit_codes'] == {'0': scoped['exit_codes']['0'], '2': scoped['exit_codes']['2']}
        assert scoped['recovery'], name
        assert all(code in RECOVERY for code in scoped['recovery']), name


def test_every_recovery_instruction_names_something_that_can_be_run():
    # A recovery line whose key merely exists is not recovery: it has to name a command, a flag
    # or a setting the reader can actually act on.
    runnable = set(DESCRIPTIONS) | {'--max-chars', '--rows', '--kind', '--position/--end', '--cursor',
                                    '--cache-dir', '--env-file', '--company', '--help', 'EDGAR_IDENTITY'}
    for code, fix in RECOVERY.items():
        assert any(word in fix for word in runnable), f'{code}: {fix}'


def test_the_reading_section_says_what_is_not_supported():
    reading = schema('table')['reading']
    assert 'CSS classes is not supported' in reading['emphasis_scope']
    assert 'No header row is inferred' in reading['th']
    assert 'not that necessary context is missing' in reading['context_rows']


def test_the_documents_section_does_not_promise_completeness():
    documents = schema('open')['documents']
    assert 'not a guarantee of completeness' in documents['known_extraction_limits']
    assert 'extraction_complete' not in json.dumps(documents)


def test_schema_needs_neither_identity_nor_network(capsys):
    from sec import main

    assert main(['schema', 'read', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['commands']['read']


def test_an_outage_is_reported_as_a_connection_failure_with_a_recovery_line(cli):
    import httpx
    from sec import RECOVERY

    cli.replies.append(('CIK0000320193', 200, httpx.ConnectError('no route'), {}))
    cli.replies.append(('CIK0000320193', 200, httpx.ConnectError('no route'), {}))
    cli.replies.append(('CIK0000320193', 200, httpx.ConnectError('no route'), {}))
    code, result = cli('filings', '320193')
    assert code == 2
    assert result['error']['code'] == 'connection_failed'
    assert 'connection_failed' in RECOVERY
