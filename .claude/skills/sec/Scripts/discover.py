"""Choose the company, the filing and the document, and open one as a reading snapshot."""

import re
from datetime import UTC, date, datetime

from output import SecError, measure
from store import Store
from transport import TICKERS, Transport

EFTS = 'https://efts.sec.gov/LATEST/search-index'
# The returned shape of every discovery command changed with this rewrite, so a cursor saved
# under the old shape would replay raw SEC hits into the new contract without any error.
QUERY_VERSION = 2
REQUESTS_PER_SECOND = 2


def cik(value):
    if not re.fullmatch(r'\d{1,10}', str(value)) or int(value) == 0:
        raise SecError('invalid_company', 'CIK must be a positive number of at most ten digits.',
                       'Use company to find an exact CIK.')
    return str(int(value)).zfill(10)


def accession(value):
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', value or ''):
        raise SecError('invalid_accession', 'Accession must have the form ##########-##-######.',
                       'Copy the exact accession from a SEC filing.')
    return value


def archive_url(identifier, number, filename):
    from transport import validate_url

    if (not filename or filename.startswith('/')
            or any(part in ('', '.', '..') for part in filename.split('/'))
            or any(character in filename for character in '\\%?#')):
        raise SecError('invalid_response', 'SEC returned an unsafe document filename.',
                       'Use the filing index to verify the source link.')
    return validate_url(f'https://www.sec.gov/Archives/edgar/data/{int(identifier)}/'
                        f"{accession(number).replace('-', '')}/{filename}")


def query_options(args):
    options = {key: value for key, value in vars(args).items()
               if key not in ('json', 'cursor', 'cache_dir', 'env_file')}
    return {'version': QUERY_VERSION, 'options': options}


def validate_options(args):
    if hasattr(args, 'budget') and not 2000 <= args.budget <= 24000:
        raise SecError('invalid_budget', 'max-chars must be 2000..24000.', 'Use a budget within this range.')
    if hasattr(args, 'limit') and not 1 <= args.limit <= 100:
        raise SecError('invalid_argument', 'limit must be between 1 and 100.', 'Choose a limit from 1 to 100.')
    if hasattr(args, 'query') and not args.query.strip():
        raise SecError('invalid_argument', 'The query cannot be empty.', 'Supply a company, search text or SEC URL.')
    for prefix in ('filed', 'report'):
        low, high = getattr(args, prefix + '_from', None), getattr(args, prefix + '_to', None)
        for value in (low, high):
            try:
                if value and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
                              or date.fromisoformat(value).isoformat() != value):
                    raise ValueError
            except ValueError:
                raise SecError('invalid_argument', 'Dates must use YYYY-MM-DD.',
                               'Supply an actual calendar date.') from None
        if low and high and low > high:
            raise SecError('invalid_argument', 'The start date is after the end date.',
                           'Use an ascending inclusive date range.')


def listing(args, store, state, operation, extra=None):
    items = state['pending'][:args.limit]
    state['pending'] = state['pending'][args.limit:]
    cursor = (store.save({'query': query_options(args), 'state': state})
              if state['pending'] or not state['exhausted'] else None)
    return {'operation': operation, 'items': items, 'returned': len(items),
            'remaining_saved': len(state['pending']), 'next_cursor': cursor,
            'remote_complete': state['exhausted'], 'sources': state['sources'], **(extra or {})}


# --- company ---------------------------------------------------------------------------------


def company(query, transport, offset=0, names_only=False):
    if query.isdecimal():
        value, source = transport.json(f'https://data.sec.gov/submissions/CIK{cik(query)}.json')
        if cik(value['cik']) != cik(query):
            raise SecError('invalid_response', 'SEC returned a different CIK.', 'Verify the company identifier.')
        return ([{'cik': cik(value['cik']), 'name': value['name'],
                  'tickers': value.get('tickers', []), 'match': 'exact_cik'}],
                [source], {'exhausted': True})
    # 성진: 짧은 단어는 티커와 이름이 겹칠 수 있어 티커 조회 실패 후 이름 후보를 반환한다, 별도 기업 검색 API가 제공되면 교체한다.
    sources = []
    if not names_only and re.fullmatch(r'[A-Za-z0-9.-]{1,10}', query):
        value, source = transport.json(TICKERS)
        sources.append(source)
        rows = [dict(zip(value['fields'], row, strict=True)) for row in value['data']]
        matches = [{'cik': cik(row['cik']), 'name': row['name'], 'tickers': [row['ticker']],
                    'match': 'exact_ticker'}
                   for row in rows if row['ticker'].casefold() == query.casefold()]
        if matches:
            return matches, sources, {'exhausted': True}
    value, source = transport.json(EFTS, {'entityName': query, 'from': offset, 'size': 100})
    sources.append(source)
    candidates = {}
    for hit in value['hits']['hits']:
        src = hit['_source']
        for identifier, name in zip(src.get('ciks', []), src.get('display_names', []), strict=True):
            if query.casefold() in name.casefold():
                candidates[cik(identifier)] = {'cik': cik(identifier), 'name': name,
                                               'tickers': None, 'match': 'name_candidate'}
    offset += len(value['hits']['hits'])
    total = value['hits']['total']
    return (list(candidates.values()), sources,
            {'offset': offset, 'total': total, 'timed_out': bool(value.get('timed_out')),
             'shards_failed': value.get('_shards', {}).get('failed', 0),
             'limit_reached': offset >= 10000 and (total['relation'] == 'gte' or total['value'] > 10000),
             'exhausted': len(value['hits']['hits']) < 100 or offset >= 10000
             or (total['relation'] == 'eq' and offset >= total['value'])})


def resolve(query, transport):
    # Turning a name into a CIK is how the request was read, not where the returned items came from.
    if query.isdecimal():
        return cik(query)
    items, _, _ = company(query, transport)
    exact = [item for item in items if item['match'] == 'exact_ticker']
    if len(exact) != 1:
        raise SecError('ambiguous_company' if items else 'company_not_found',
                       'An exact company selection is required.',
                       'Run company, then use a returned CIK or exact ticker.')
    return exact[0]['cik']


# --- filings ----------------------------------------------------------------------------------


def matches(form, filing_date, report_date, args):
    amendment = form.endswith('/A')
    if (args.amendments == 'exclude' and amendment) or (args.amendments == 'only' and not amendment):
        return False
    if args.form and form not in {args.form, args.form + '/A'}:
        return False
    for value, low, high in ((filing_date, getattr(args, 'filed_from', None), getattr(args, 'filed_to', None)),
                             (report_date, getattr(args, 'report_from', None), getattr(args, 'report_to', None))):
        # A row with no report date does not match a report-date filter: the filter asks about a
        # period the row does not state.
        if (low or high) and (not value or (low and value < low) or (high and value > high)):
            return False
    return True


def filing_rows(columns, identifier, args):
    if not isinstance(columns, dict) or 'accessionNumber' not in columns:
        raise SecError('invalid_response', 'SEC filing columns are missing.', 'Verify the submissions endpoint.')
    keys = list(columns)
    result = []
    for values in zip(*(columns[key] for key in keys), strict=True):
        row = dict(zip(keys, values, strict=True))
        number = accession(row['accessionNumber'])
        if not matches(row.get('form', ''), row.get('filingDate', ''), row.get('reportDate', ''), args):
            continue
        primary = row.get('primaryDocument') or None
        result.append({'accession': number, 'cik': identifier, 'form': row.get('form') or None,
                       'filing_date': row.get('filingDate') or None,
                       'report_date': row.get('reportDate') or None,
                       'primary_document': primary,
                       'index_url': archive_url(identifier, number, number + '-index.html'),
                       'document_url': archive_url(identifier, number, primary) if primary else None,
                       'items': row.get('items') or None})
    return sorted(result, key=lambda row: (row['filing_date'] or '', row['accession']), reverse=True)


def filings(args, store, transport):
    if args.cursor:
        state = store.resume(args.cursor, query_options(args))
    else:
        identifier = resolve(args.query, transport)
        value, source = transport.json(f'https://data.sec.gov/submissions/CIK{identifier}.json')
        if cik(value['cik']) != identifier:
            raise SecError('invalid_response', 'SEC returned a different CIK.', 'Verify the company identifier.')
        files = [file for file in value['filings']['files']
                 if not ((args.filed_from and file.get('filingTo') and file['filingTo'] < args.filed_from)
                         or (args.filed_to and file.get('filingFrom') and file['filingFrom'] > args.filed_to))]
        files.sort(key=lambda file: file.get('filingTo', ''), reverse=True)
        state = {'cik': identifier, 'pending': filing_rows(value['filings']['recent'], identifier, args),
                 'files': files, 'sources': [source], 'exhausted': not files, 'seen': []}
    while len(state['pending']) < args.limit and state['files']:
        name = state['files'].pop(0)['name']
        if not re.fullmatch(r'CIK' + state['cik'] + r'-submissions-\d+\.json', name):
            raise SecError('unsafe_url', 'SEC supplied an invalid historical filename.',
                           'Verify the company submissions response.')
        value, source = transport.json('https://data.sec.gov/submissions/' + name)
        state['sources'].append(source)
        state['pending'].extend(filing_rows(value, state['cik'], args))
    state['exhausted'] = not state['files']
    seen = set(state['seen'])
    state['pending'] = [row for row in state['pending'] if row['accession'] not in seen]
    state['seen'].extend(row['accession'] for row in state['pending'][:args.limit])
    return listing(args, store, state, 'filings')


# --- search -----------------------------------------------------------------------------------


def search_status(state, has_more):
    incomplete = state['exhausted'] and (state['total']['relation'] == 'gte'
                                         or state['offset'] < state['total']['value'])
    partial = state['timed_out'] or state['shards_failed'] > 0 or state['limit_reached'] or incomplete
    result = {key: state[key] for key in ('total', 'timed_out', 'limit_reached', 'shards_failed')}
    result['remote_complete'] = state['exhausted'] and not partial
    result['unreturned_reason'] = ('remote_timeout' if state['timed_out']
                                   else 'shard_failure' if state['shards_failed']
                                   else 'search_window_limit' if state['limit_reached']
                                   else 'incomplete_remote_page' if incomplete
                                   else 'more_results' if has_more else None)
    return result


def _hit(hit):
    """One searched document: its identity, and one entry per filer with that filer's own URL."""
    source = hit['_source']
    number, separator, filename = hit['_id'].partition(':')
    if not separator or source.get('adsh') != number:
        raise SecError('invalid_response', 'SEC search document identity is inconsistent.',
                       'Open the filing index to verify this result.')
    identifiers, names = source.get('ciks', []), source.get('display_names', [])
    if len(identifiers) != len(names):
        raise SecError('invalid_response', 'SEC search returned filers without names.',
                       'Open the filing index to verify this result.')
    return {'accession': number, 'document': filename, 'form': source.get('form'),
            'file_type': source.get('file_type'), 'file_date': source.get('file_date'),
            'period_ending': source.get('period_ending'),
            'filers': [{'cik': cik(identifier), 'name': name,
                        'document_url': archive_url(cik(identifier), number, filename)}
                       for identifier, name in zip(identifiers, names, strict=True)]}


def search(args, store, transport):
    if args.cursor:
        state = store.resume(args.cursor, query_options(args))
    else:
        state = {'cik': resolve(args.company, transport) if args.company else None,
                 'pending': [], 'sources': [], 'exhausted': False, 'seen': [], 'offset': 0,
                 'total': None, 'timed_out': False, 'limit_reached': False, 'shards_failed': 0,
                 'startdt': args.filed_from or '2001-01-01',
                 'enddt': args.filed_to or datetime.now(UTC).date().isoformat()}
    while len(state['pending']) < args.limit and not state['exhausted']:
        params = {'q': args.query, 'from': state['offset'], 'size': 100, 'dateRange': 'custom',
                  'startdt': state['startdt'], 'enddt': state['enddt']}
        if args.sort == 'date':
            params['sort'] = 'desc'
        if state['cik']:
            params['ciks'] = state['cik']
        if args.form:
            params['forms'] = args.form
        value, source = transport.json(EFTS, params)
        state['sources'].append(source)
        total = value['hits']['total']
        if (not isinstance(total, dict) or total.get('relation') not in ('eq', 'gte')
                or not isinstance(total.get('value'), int)):
            raise SecError('invalid_response', 'SEC search totals have an unknown shape.',
                           'Retry later or narrow the query.')
        state['total'] = total
        state['timed_out'] |= bool(value.get('timed_out'))
        state['shards_failed'] += value.get('_shards', {}).get('failed', 0)
        hits = value['hits']['hits']
        seen = set(state['seen'])
        for hit in hits:
            if hit['_id'] in seen:
                continue
            seen.add(hit['_id'])
            state['seen'].append(hit['_id'])
            item = _hit(hit)
            if matches(item['form'] or '', item['file_date'] or '', item['period_ending'] or '', args):
                state['pending'].append(item)
        state['offset'] += len(hits)
        state['limit_reached'] = state['offset'] >= 10000 and (total['relation'] == 'gte'
                                                               or total['value'] > 10000)
        state['exhausted'] = (len(hits) < 100 or state['offset'] >= 10000
                              or (total['relation'] == 'eq' and state['offset'] >= total['value']))
    result = listing(args, store, state, 'search')
    result.update(search_status(state, bool(result['next_cursor'])))
    return result


# --- open -------------------------------------------------------------------------------------


def open_filing(args, store, transport):
    from urllib.parse import parse_qs, urlsplit

    from transport import filing_location, validate_url

    if args.cursor:
        state = store.resume(args.cursor, query_options(args))
        return (_document_page(args, store, state) if state.get('kind') == 'document'
                else listing(args, store, state, 'index'))
    if '://' in args.query:
        url = validate_url(args.query)
    else:
        number = accession(args.query)
        if not args.company:
            raise SecError('company_required', 'A bare accession requires its filing company.',
                           'Supply --company with the CIK or ticker; the accession prefix may '
                           'identify a filing agent.')
        url = archive_url(resolve(args.company, transport), number, number + '-index.html')
    if filing_location(url) is None:
        raise SecError('unsafe_url', 'Open requires a SEC filing document or index URL.',
                       'Use a document URL under /Archives/edgar/data/.')
    body, source = transport.get(url)
    if not urlsplit(url).path.endswith(('-index.html', '-index.htm')):
        return _document(args, store, body, source)

    from bs4 import UnicodeDammit
    from index import attachment_rows
    from lxml import html

    text = UnicodeDammit(body).unicode_markup
    if text is None:
        raise SecError('parse_failed', 'The filing index encoding could not be decoded.',
                       'Read the original SEC filing index.')
    root = html.fromstring(text)
    expected_cik, expected_accession = filing_location(url)
    actual = re.findall(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', root.xpath('string(//*[@id="secNum"])'))
    filers = {cik(value) for href in root.xpath('//div[contains(@class,"companyInfo")]//a/@href')
              for value in parse_qs(urlsplit(href).query).get('CIK', [])}
    expected = (expected_accession[:10] + '-' + expected_accession[10:12] + '-' + expected_accession[12:])
    if actual != [expected] or expected_cik not in filers:
        raise SecError('filing_mismatch', 'The index does not confirm the requested accession and filer CIK.',
                       'Verify the exact SEC filing URL and company CIK.')
    items = []
    for row in attachment_rows(root, url):
        location = filing_location(row['url'])
        if location is None or location[1] != expected_accession or location[0] not in filers:
            raise SecError('filing_mismatch', 'An attachment belongs to a different filing or undeclared filer.',
                           'Verify the source filing index and attachment link.')
        items.append(row)
    return listing(args, store, {'pending': items, 'sources': [source], 'exhausted': True}, 'index')


def _document(args, store, body, source):
    from snapshot import SourceDocument, parse_document

    snapshot = parse_document(SourceDocument(body, source, source['headers']), store)
    summary = snapshot.summary()
    state = {'kind': 'document', 'summary': {k: v for k, v in summary.items() if k != 'tables'},
             'pending': summary['tables'], 'sources': [source], 'exhausted': True}
    return _document_page(args, store, state)


def _document_page(args, store, state):
    """List every table, bounded by the budget rather than by a hidden count.

    --limit applies to an index's attachment rows, not here: a document's table list is bounded
    by what fits and continues through next_cursor, and a hidden cap of twenty made --limit 100
    look as though the document had twenty tables.
    """
    # Every field the finished page carries, at its widest: returned and remaining_saved are
    # written after the list is filled, and a page measured without them overflows when printed.
    result = dict(state['summary'], operation='document', tables=[], sources=state['sources'],
                  returned=len(state['pending']), remaining_saved=len(state['pending']),
                  returned_chars=args.budget, next_cursor='0' * 64)
    pending = list(state['pending'])
    taken = []
    while pending:
        taken.append(pending[0])
        result['tables'] = taken
        if measure(result, args.json) > args.budget:
            taken.pop()
            result['tables'] = taken
            break
        pending.pop(0)
    if not taken and state['pending']:
        raise SecError('budget_too_small', 'The snapshot summary metadata exceeds this budget.',
                       'Increase --max-chars, or read the table list with outline --kind table.')
    remaining = dict(state, pending=pending)
    result['next_cursor'] = store.save({'query': query_options(args), 'state': remaining}) if pending else None
    result['returned'] = len(taken)
    result['remaining_saved'] = len(pending)
    result['returned_chars'] = measure(result, args.json)
    return result


# --- doctor -----------------------------------------------------------------------------------


def doctor(args, store):
    from snapshot import SNAPSHOT_VERSION
    from transport import identity_state

    state = identity_state(args.env_file)
    result = {'operation': 'doctor',
              'identity_configured': state['configured'], 'identity_source': state['source'],
              'connection': 'not_checked', 'requests_per_second': REQUESTS_PER_SECOND,
              'cache_dir': str(store.root), 'snapshot_version': SNAPSHOT_VERSION}
    if not state['configured']:
        result['error'] = {'code': 'identity_required',
                           'message': 'A valid requester email is not configured.',
                           'fix': 'Set EDGAR_IDENTITY="your-email@your-domain" in Scripts/.env or --env-file.'}
        return result
    if args.live:
        try:
            Transport(store, args.env_file).json(TICKERS)
            result['connection'] = 'ok'
        except SecError as error:
            result['connection'] = 'failed'
            result['error'] = {'code': error.code, 'message': error.message, 'fix': error.fix}
    return result


# --- dispatch ---------------------------------------------------------------------------------


def dispatch(args):
    validate_options(args)
    store = Store(args.cache_dir)
    cursor = getattr(args, 'cursor', None) if args.command in ('company', 'filings', 'search', 'open') else None
    if cursor:
        replay = store.replay(cursor, query_options(args))
        if replay is not None:
            return replay
    result = execute(args, store)
    return store.complete_cursor(cursor, query_options(args), result) if cursor else result


def execute(args, store):
    if args.command in ('outline', 'find', 'read', 'table', 'links'):
        import reader
        from snapshot import load_snapshot

        snapshot = load_snapshot(store, args.snapshot)
        options = {'cursor': args.cursor, 'budget': args.budget, 'as_json': args.json}
        if args.command == 'outline':
            options.update(kinds=[kind.strip() for kind in args.kind.split(',')],
                           observations=args.all, in_tables=args.in_tables)
        elif args.command == 'find':
            options.update(query=args.query, case_sensitive=args.case_sensitive)
        elif args.command == 'read':
            options.update(position=args.position, end=args.end)
        elif args.command == 'table':
            options.update(table_id=args.table_id, rows=args.rows)
        elif args.command == 'links':
            options['kind'] = args.kind
        return getattr(reader, args.command)(snapshot, store, **options)
    if args.command == 'doctor':
        return doctor(args, store)
    transport = Transport(store, args.env_file)
    if args.command == 'open':
        return open_filing(args, store, transport)
    if args.command == 'search':
        return search(args, store, transport)
    if args.command == 'filings':
        return filings(args, store, transport)
    return _company_listing(args, store, transport)


def _company_listing(args, store, transport):
    if args.cursor:
        state = store.resume(args.cursor, query_options(args))
        if not state['pending'] and not state['exhausted']:
            items, sources, metadata = company(args.query, transport, state['offset'], names_only=True)
            metadata['timed_out'] |= state['timed_out']
            metadata['shards_failed'] += state['shards_failed']
            state.update(metadata)
            state['sources'].extend(sources)
            state['pending'] = [item for item in items if item['cik'] not in state['seen']]
            state['seen'].extend(item['cik'] for item in state['pending'])
    else:
        items, sources, metadata = company(args.query, transport)
        state = {'pending': items, 'sources': sources,
                 'selection_required': len(items) != 1 or any(i['match'] == 'name_candidate' for i in items),
                 'seen': [item['cik'] for item in items], **metadata}
    result = listing(args, store, state, 'company', {'selection_required': state['selection_required']})
    if 'total' in state:
        status = search_status(state, bool(result['next_cursor']))
        # A name lookup's total counts filings that mention the name, not company candidates.
        result['filing_hits'] = status.pop('total')
        result.update(status)
    return result
