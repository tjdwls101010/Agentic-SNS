"""Read SEC company, filing and search evidence through one identified transport."""

import argparse
import sqlite3
import sys

from output import SecError, emit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SecError('invalid_argument', message, 'Run the command with --help and correct its arguments.')


DESCRIPTIONS = {
    'company': 'Find exact ticker/CIK matches or company-name candidates; select a CIK explicitly for ambiguous names.',
    'filings': 'List company filings newest first, keeping submission dates, report dates and amendments distinct.',
    'search': 'Search filing and exhibit text since 2001 by default; each document remains a separate hit.',
    'open': 'Open a filing index to list exhibits, or save an original document as an immutable reading snapshot.',
    'outline': "List a saved snapshot's contents links, emphasis observations and tables; --kind selects anchors or link targets instead.",
    'find': 'Find a literal string in one saved snapshot; matching ignores case unless --case-sensitive is set.',
    'read': 'Read a saved snapshot range using opaque positions; tables arrive as grid rows, not one cell at a time.',
    'table': 'Read one table as a grid of original row and column numbers, with the prose and notes that frame it.',
    'links': 'List original links or images and their context in one saved snapshot; no external links are fetched.',
    'doctor': 'Check requester configuration without printing its value; optionally test the SEC connection.',
    'schema': 'Describe command inputs, output fields, defaults, exit codes and error recovery without an identity.',
}


def parser():
    p = Parser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument('--json', action='store_true', help='Return structured JSON (also accepted after the command).')
    p.add_argument('--cache-dir',
                   help='Override the user cache directory; processes sharing this directory share the limiter.')
    p.add_argument('--env-file', help='Identity dotenv file; default: Scripts/.env. Identity is never printed.')
    commands = p.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name, description in DESCRIPTIONS.items():
        sub = commands.add_parser(name, help=description, description=description,
                                  formatter_class=argparse.RawTextHelpFormatter)
        sub.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                         help='Return structured JSON instead of readable text.')
        if name in ('company', 'filings', 'search', 'open'):
            sub.add_argument('query', help='Company name/ticker/CIK, search text, or SEC filing URL/accession.')
            sub.add_argument('--limit', type=int, default=20,
                             help='Returned items, 1-100 (default 20). Applies to listings and to a filing '
                                  "index's attachment rows; a document's table list is bounded by --max-chars.")
            sub.add_argument('--cursor', help='Opaque saved continuation; repeat the original query and filters.')
        if name in ('filings', 'search'):
            sub.add_argument('--form', help='Exact form; amendments of this form are included unless excluded.')
            sub.add_argument('--amendments', choices=['include', 'exclude', 'only'], default='include',
                             help='Amendments: include originals and amendments (default), exclude amendments, '
                                  'or return amendments only.')
            sub.add_argument('--filed-from', help='Inclusive submission date YYYY-MM-DD.')
            sub.add_argument('--filed-to', help='Inclusive submission date YYYY-MM-DD.')
        if name == 'filings':
            sub.add_argument('--report-from', help='Inclusive report date YYYY-MM-DD; missing report dates do not match.')
            sub.add_argument('--report-to', help='Inclusive report date YYYY-MM-DD; distinct from dates of individual facts.')
        if name == 'search':
            sub.add_argument('--company', help='Exact ticker or CIK; resolve ambiguous names with company first.')
            sub.add_argument('--sort', choices=['date', 'relevance'], default='date',
                             help='Sort by newest filing date (default) or SEC relevance score.')
        if name == 'open':
            sub.add_argument('--company',
                             help='CIK/ticker required for a bare accession; never assumes the accession prefix is the issuer.')
        if name in ('outline', 'find', 'read', 'table', 'links'):
            sub.add_argument('snapshot', help='Immutable snapshot_id returned by open; use the same --cache-dir, no identity needed.')
            sub.add_argument('--cursor', help='Opaque continuation for this operation; repeat the same snapshot, options and output mode.')
        if name in ('open', 'outline', 'find', 'read', 'table', 'links'):
            sub.add_argument('--max-chars', dest='budget', type=int, default=12000,
                             help='Response budget measured on what is actually printed, 2000-24000 characters '
                                  "(default 12000); the only page boundary, kept below the host's ~30,000-character "
                                  'tool-output truncation.')
        if name == 'outline':
            sub.add_argument('--kind', default='toc,emphasis,table',
                             help='Comma-separated kinds from toc, emphasis, table, anchor, internal_link '
                                  '(default toc,emphasis,table); anchors are citation targets, not navigation.')
            sub.add_argument('--all', action='store_true',
                             help='Return every emphasis observation, not only the ones strong enough to read as '
                                  'section boundaries; use this when the navigation layer comes back empty.')
            sub.add_argument('--in-tables', choices=['only', 'exclude'],
                             help='Select emphasis inside or outside tables; default returns both. Only meaningful '
                                  'with --all, because the navigation layer is outside tables by definition.')
        if name == 'find':
            sub.add_argument('query', help='Nonempty literal text to find in snapshot text and table cells.')
            sub.add_argument('--case-sensitive', action='store_true', help='Match letter case exactly; default ignores case.')
        if name == 'read':
            sub.add_argument('--position', help='Inclusive opaque position from find, outline, links or read; default is document start.')
            sub.add_argument('--end', help='Exclusive opaque end position from this same snapshot; default is document end.')
        if name == 'table':
            sub.add_argument('table_id', help='Table identifier from open.tables or any outline entry whose kind is table.')
            sub.add_argument('--rows', help='Original row numbers, 0-based and inclusive at both ends, e.g. 2-5 or 7 (default all rows).')
        if name == 'links':
            sub.add_argument('--kind', choices=['image', 'internal', 'external'],
                             help='Filter image links, in-document anchors, or external links; default returns all kinds without fetching them.')
        if name == 'schema':
            sub.add_argument('command_name', nargs='?', choices=list(DESCRIPTIONS),
                             help='Describe one command instead of every command and output section.')
        if name == 'doctor':
            sub.add_argument('--live', action='store_true', help='Check the SEC ticker endpoint through the identified transport.')
    return p


# Each command's output fields live in one section; a scoped request carries only that command's
# own contract, its own recovery codes and the options every command shares.
SECTIONS = {'company': ('company', 'listing'), 'filings': ('listing',), 'search': ('search', 'listing'),
            'open': ('documents', 'listing'), 'outline': ('reading',), 'find': ('reading',),
            'read': ('reading',), 'table': ('reading',), 'links': ('reading',), 'doctor': ('doctor',),
            'schema': ()}

RECOVERY = {
    'identity_required': 'Set EDGAR_IDENTITY="you@example.org" in Scripts/.env, or pass --env-file with that file; run doctor to confirm. Cached readers, help and schema need no identity.',
    'cursor_mismatch': 'Repeat the original command, query, filters, budget and output mode, or start the query again without --cursor. A cursor is never reinterpreted under different options.',
    'cache_corrupt': 'Run again with a fresh --cache-dir and reopen the original sources; corrupted bytes are never trusted.',
    'missing_snapshot': 'Run open on the original URL again, or pass the --cache-dir the snapshot was saved in.',
    'unsupported_snapshot_version': 'Run open on the original URL again; a snapshot saved by an older reader is refused rather than reinterpreted.',
    'filing_mismatch': 'Verify the exact accession and a declared filer CIK with open on the filing index; no other filing is substituted.',
    'access_denied': 'Check the configured identity with doctor and pause before retrying; 403 is never retried automatically.',
    'connection_failed': 'Check that this machine can reach www.sec.gov, then run the command again; three attempts were already made. A reader command on a saved snapshot needs no network at all.',
    'not_found': 'Verify the exact accession and filename with open on the filing index; no other filing is substituted for one that is missing.',
    'rate_limited': 'Pause, then run the command again; 429 is never retried automatically. Run doctor if it keeps happening.',
    'parse_failed': 'Open the original source URL and read it directly; a parse failure is an error rather than an empty document.',
    'budget_too_small': 'Raise --max-chars up to 24000, or select less with --rows, --kind, --position/--end or a more specific query.',
    'invalid_table': 'Run outline --kind table, following its continuations, for every table_id in this snapshot.',
    'invalid_position': 'Use a position this same snapshot returned; run find or outline again to get one.',
    'invalid_argument': 'Run the command with --help and correct the named argument.',
    'company_required': 'Add --company with the filing company CIK or ticker; the accession prefix may identify a filing agent.',
    'ambiguous_company': 'Run company with the same name and pass one returned CIK.',
    'unsafe_url': 'Pass open a SEC filing index or document URL under /Archives/edgar/data/, with no credentials, traversal or another host; filings gives that URL for a company.',
}

EXIT_CODES = {'0': 'the command produced a result', '2': 'a structured error was printed instead of a result'}

GLOBAL_OPTIONS = ('--json selects structured output and also changes where a page ends, so a cursor is bound to it; '
                  '--cache-dir selects the shared store of saved bytes, snapshots and cursors, and the request '
                  'limiter shared with other processes using it; --env-file selects the identity dotenv file. '
                  'All three come before the command name.')


def _describe(action):
    return {'names': action.option_strings or [action.dest], 'required': action.required,
            'default': action.default, 'choices': action.choices, 'help': action.help}


def schema(command=None):
    p = parser()
    subs = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    full = {
        'version': 2,
        'global_options': [_describe(action) for action in p._actions if action.option_strings],
        'global_options_note': GLOBAL_OPTIONS,
        'exit_codes': EXIT_CODES,
        'defaults': {'limit': 20, 'max_chars': 12000, 'max_chars_floor': 2000, 'max_chars_ceiling': 24000,
                     'max_chars_measure': 'the characters this command actually prints, in whichever output mode was chosen',
                     'requests_per_second': 2, 'search_from': '2001-01-01', 'sort': 'date'},
        'commands': {name: {'description': sub.description,
                            'options': [_describe(action) for action in sub._actions]}
                     for name, sub in subs.choices.items()},
        'error_envelope': {'error': {'code': 'stable machine code', 'message': 'reason',
                                     'fix': 'recovery instruction'},
                           'note': 'printed instead of a result, with exit code 2'},
        'recovery': RECOVERY,
        'listing': {
            'items': "one object per result; a field SEC did not supply is null rather than absent, so 'never stated' and 'not returned this time' stay distinct",
            'next_cursor': 'opaque immutable continuation, or null at the end',
            'returned': 'number returned by this call',
            'remaining_saved': 'already fetched items not yet returned',
            'remote_complete': 'all relevant remote pages visited with no reported timeout, failed shards or search-window limit',
            'sources': 'URL, sha256, fetched_at and content-type for each fetched page; the raw bytes are immutable',
        },
        'company': {
            'items': '{cik, name, tickers, match}; tickers is null for a name candidate, which SEC does not supply tickers for',
            'match': 'exact_ticker or exact_cik identifies an exact selection; name_candidate requires choosing a CIK',
            'selection_required': 'true for ambiguous, name-based or empty candidates; a name match is never selected silently',
            'filing_hits': 'for a name lookup, the SEC total of filings mentioning that name, with its relation (eq or gte). This is not a count of company candidates',
        },
        'filings': {
            'items': '{accession, cik, form, filing_date, report_date, primary_document, index_url, document_url, items}',
            'filing_date': 'when the filing arrived; report_date is the period it reports on, and dates neither of the individual facts inside it',
            'report_date': 'null when SEC states none; a row with no report date does not match --report-from or --report-to',
        },
        'search': {
            'items': '{accession, document, form, file_type, file_date, period_ending, filers}',
            'filers': 'one {cik, name, document_url} per filer on the hit; one filing can have several, and the accession prefix does not identify the issuer',
            'document': 'the exhibit filename within the accession; exhibits are searched directly and stay separate hits',
            'total': 'the SEC remote total and its relation (eq or gte), which is not the number returned after local filtering and deduplication',
            'excluded_fields': '_index, _score, sort, xsl, film_num, sics, biz_states and inc_states are SEC search infrastructure and are not returned',
            'shards_failed': 'sum of failed SEC search shards across fetched pages; any failure makes remote_complete false',
            'timed_out': 'SEC partial-search flag',
            'limit_reached': '10,000 remote-hit window reached with more possible hits',
            'unreturned_reason': 'remote_timeout, shard_failure, search_window_limit, incomplete_remote_page, more_results or null',
            'coverage': 'full-text search covers 2001 onward; a missing hit does not establish that an older filing does not exist',
        },
        'documents': {
            'status': 'parsed or unsupported; malformed supported content is a parse_failed error',
            'snapshot_id': 'immutable content-addressed reading snapshot; every reader command uses this id and the same --cache-dir',
            'source': 'original SEC URL, raw-byte sha256, fetched_at and response content-type; never a fabricated fragment',
            'format': 'html, xml, sgml, text, pdf or image; a PDF or image opens with unsupported status and its original access path',
            'encoding': 'selected encoding, original declarations, and inferred/conflict/loss flags',
            'blocks': 'number of saved reading blocks; one table is one block',
            'tables': 'every table as {table_id, rows, columns, position, context}. rows and columns are the original row count and the number of columns left after empty ones are folded away, so a 0 x 0 entry is a layout table with no values. The list is bounded by --max-chars and continues through next_cursor; outline --kind table gives the same list',
            'known_extraction_limits': 'named limits of this extraction: encoding_loss, inline_xbrl_metadata_excluded, external_entities_not_expanded, unsupported_format, image_content_not_extracted. An empty list means no known limit, which is not a guarantee of completeness',
            'index_result': 'opening a filing index returns attachment rows instead: {sequence_number, document, description, document_type, size, url}, with null where the index states nothing',
        },
        'reading': {
            'snapshot_id': 'the same immutable snapshot for outline/find/read/table/links; no identity, fetch or reparsing is required',
            'position': 'an opaque location in this snapshot. Repeat it unchanged; a position from another snapshot is refused, and it is not a SEC URL fragment',
            'grid': 'a table is read as a grid of its original row and column numbers. A text row is `row | cell | cell`, consecutive pipes are empty cells in the original, and a literal |, newline or backslash inside a cell is escaped as \\|, \\n or \\\\. Escapes and the row number are display only and are not part of any position',
            'kept_columns': 'the original column numbers still carrying values, for the whole table rather than per page, so the same column means the same thing on every page',
            'spans': "{row, column, colspan, rowspan, w}: colspan and rowspan are the original document's values and w is how many kept columns the merge still covers. rowspan 0 means to the end of its row group and carries effective_rows",
            'th': 'present on a cell only where the original declared <th>, with scope and headers alongside. No header row is inferred: the measured filings declare none, and one statement can restart its periods partway down',
            'emphasis': '{text, occurrences:[{position, signals, table_id, row}]}. The same phrase groups into one item and every place it occurs is kept, because one document prints the same words as a section heading and as a page mark. signals are per occurrence: bold_fraction, font_size_ratio against the document\'s own body size (null when it has no body prose to measure), alignment and all_caps',
            'emphasis_scope': 'HTML only, and inline styles only. A stylesheet with CSS classes is not supported and no measured filing used one. Emphasis is an observation, not a promised section boundary',
            'context_rows': "the rows that open a table, carried when a page starts partway into it. context_truncated says that prefix was cut by the budget, not that necessary context is missing, and context_next_position continues it",
            'row_complete': 'false where a row continues into the next page; a cell cut mid-way ends with an ellipsis',
            'next_position': 'where unread body continues, or null at the end of the selected range; --end stays exclusive. Repeating a table\'s opening rows never moves it back',
            'next_cursor': 'continuation bound to the operation, snapshot, every option, the budget and the output mode',
            'has_more': 'more content remains in the selected operation or range',
            'scope_complete': 'the selected range or output was returned completely; this says nothing about known_extraction_limits',
            'remaining_items': 'unreturned items, counting one whose text was only partly returned',
            'total_matches': 'find: how many matches exist in the whole snapshot, not only on this page',
            'returned_chars': 'the characters actually printed, including the envelope and the trailing newline; --max-chars 2000..24000 is the only page boundary',
            'xml': 'an XML snapshot is read as path, parent and attributes rather than prose, so repeated records with the same tag names stay distinct',
            'sgml': 'a submission text file keeps its document boundaries with sequence, type, filename and description; a historical filing may declare none of them but the boundary still holds',
        },
        'doctor': {
            'identity_configured': 'whether a usable requester identity was found; the value itself is never printed',
            'identity_source': 'the dotenv file that was read, or null when no file exists. A file that exists but holds no usable value reports the path with identity_configured false',
            'connection': 'ok, failed or not_checked; only --live contacts SEC',
            'cache_dir': 'the shared store this run would use',
            'snapshot_version': 'the snapshot format this reader writes and accepts',
            'exit': '2 with an identity_required error when no usable identity is configured, and 2 with the transport error code when --live cannot reach SEC',
        },
    }
    if command is None:
        return full
    scoped = {'version': full['version'], 'global_options': full['global_options'],
              'global_options_note': full['global_options_note'], 'exit_codes': full['exit_codes'],
              'defaults': full['defaults'], 'commands': {command: full['commands'][command]},
              'error_envelope': full['error_envelope']}
    scoped.update({section: full[section] for section in SECTIONS[command]})
    scoped['recovery'] = {code: fix for code, fix in RECOVERY.items() if code in _codes(command)}
    return scoped


def _codes(command):
    """The error codes this command can actually return."""
    shared = {'invalid_argument', 'cache_corrupt'}
    if command in ('outline', 'find', 'read', 'table', 'links'):
        return shared | {'missing_snapshot', 'unsupported_snapshot_version', 'invalid_position',
                         'invalid_table', 'budget_too_small', 'cursor_mismatch'}
    if command == 'schema':
        return shared
    if command == 'doctor':
        return shared | {'identity_required', 'access_denied', 'rate_limited', 'connection_failed'}
    codes = shared | {'identity_required', 'cursor_mismatch', 'access_denied', 'rate_limited',
                      'unsafe_url', 'connection_failed', 'not_found'}
    if command == 'open':
        return codes | {'filing_mismatch', 'parse_failed', 'budget_too_small', 'company_required'}
    return codes | {'ambiguous_company'}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in argv
    try:
        args = parser().parse_args(argv)
        if args.command == 'schema':
            result = schema(args.command_name)
        else:
            from discover import dispatch

            result = dispatch(args)
        emit(result, args.json)
        return 2 if isinstance(result, dict) and 'error' in result else 0
    except SystemExit as exc:
        return int(exc.code)
    except SecError as exc:
        emit({'error': {'code': exc.code, 'message': exc.message, 'fix': exc.fix}}, as_json)
        return 2
    except sqlite3.Error:
        emit({'error': {'code': 'cache_corrupt',
                        'message': 'The shared cache database could not be read or updated.',
                        'fix': 'Use a fresh --cache-dir; if the database is busy, wait for other SEC commands to finish.'}},
             as_json)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        emit({'error': {'code': 'invalid_data',
                        'message': f'Unable to process local or SEC data ({type(exc).__name__}).',
                        'fix': 'Check inputs; use a fresh cache directory if saved data is damaged.'}},
             as_json)
        return 2
    except Exception:  # noqa: BLE001 -- The CLI must return a structured error without exposing exception data or identity.
        emit({'error': {'code': 'processing_failed',
                        'message': 'The response could not be processed safely.',
                        'fix': 'Verify the input and original SEC URL, or retry with a fresh cache directory.'}},
             as_json)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
