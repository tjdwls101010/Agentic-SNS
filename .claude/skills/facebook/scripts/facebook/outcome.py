"""The result vocabulary and the one place a reading becomes the public result.

A reading reports what happened (records, the reason it stopped, a failure, coverage notes); `finish` decides the
result kind, the public stop reason and the fix. Nothing else maps one reason onto another. Exit numbers belong to
cli.py, which maps each kind in KINDS to one.
"""
from facebook.errors import FacebookError

# stop_reason → (what it means, what to do next)
STOP_REASONS = {
    'limit_reached': ('The requested number of records was shown.', 'Run more: if you need more.'),
    'exhausted': ('Nothing more to read in the requested range: the source ended, the About selection finished, '
                  'or the command reads a single post.', 'Nothing.'),
    'window_reached': ('Newest-first results passed --since; everything up to that boundary was delivered.',
                       'Nothing.'),
    'budget': ('--max-requests was spent.', 'Run more: (or rerun the same --out command); raise --max-requests '
                                           'if one invocation should read further.'),
    'blocked': ('Facebook showed a checkpoint or a rate limit, or the saved block is still active.',
                'Stop. After a person checks Facebook in the browser, run doctor --unblock.'),
    'query_failure': ('A request failed; error, message and fix say why.', 'Follow fix.'),
    'ready': ('doctor: Aside, login and the account protection state are usable.', 'Nothing.'),
    'complete': ('schema or refresh finished; refresh lists what it updated, missed and failed.', 'Nothing.'),
}

# Cause → recovery instruction. A fix names the cause's remedy, never a generic one.
FIXES = {
    'argument': 'Run the command with --help.',
    'aside': 'Check that Aside is running, then run doctor.',
    'login': 'Log in to Facebook in Aside, then run doctor.',
    'blocked': 'Stop requests. After a person checks Facebook in Aside, run doctor --unblock.',
    'stale_query': 'Run refresh, then retry the read command.',
    'pagination': 'Retry later with the more: command; refresh does not change pagination.',
    'pagination_restart': 'Rerun the same command later; refresh does not change pagination.',
    'empty': 'Try a different target or window; an explicitly empty result is not a stale query.',
    'budget_resume': 'Run more: to continue; raise --max-requests if one invocation should read further.',
    'budget_restart': 'Rerun with a larger --max-requests.',
}

# Response-level issue (records.Page.issues) → the coverage line it becomes.
ISSUES = {
    'unsupported_path_patch': 'part of this response could not be placed on any record; some records may lack fields',
    'graphql_errors': 'Facebook reported errors for part of this response; some records may lack fields',
    'cyclic_shared_story': 'a chain of shares looped back on itself and was cut there',
    'invalid_utf8': 'some text was not valid UTF-8 and was replaced',
    'malformed_json': 'a line of the response could not be decoded; records in it are missing',
    'non_object_json': 'a line of the response was not an object; records in it are missing',
}

# The transport's own budget stop; finish words it by whether a later invocation can continue.
BUDGET_SPENT = 'The request budget (--max-requests) is spent.'
SETUP_BUDGET = 'The request budget ran out during setup, before any reading; setup needs 1–2 requests.'

# Result kind → (situation, ok, stop reasons it can carry). cli.py gives each kind its exit code.
KINDS = {
    'records': ('At least one record and no failure.', True, ('limit_reached', 'exhausted', 'window_reached')),
    'resumable': ('--max-requests ran out where reading can continue; more: or the same --out command resumes '
                  '(zero records included).', True, ('budget',)),
    'complete': ('The --out file was already complete; nothing was read.', True, ('exhausted',)),
    'maintenance': ('doctor, refresh or schema succeeded.', True, ('ready', 'complete')),
    'argument': ('Arguments were rejected before any request.', False, ()),
    'aside': ('Aside was unavailable or returned an invalid response.', False, ('query_failure',)),
    'login': ('Facebook login is required.', False, ('query_failure',)),
    'blocked': ('A checkpoint or rate limit, now or saved from an earlier invocation.', False, ('blocked',)),
    'failed': ('A request failed before any record was read.', False, ('query_failure',)),
    'empty': ('Facebook explicitly returned nothing, or nothing fell inside the window.', False,
              ('exhausted', 'window_reached')),
    'partial': ('Records were read, then a request failed; or the budget ran out where reading must restart.',
                False, ('query_failure', 'budget')),
}

# The window line of a dated read: the first row that matches, top to bottom.
COVERAGE = (
    ('any order', 'any stop', 'a failure', 'open — <failure>'),
    ('ranked (top, activity)', 'any stop', 'no failure', 'sample (ranked order)'),
    ('any order', 'limit_reached or budget', 'no failure', 'open — more: continues'),
    ('newest first (feed, group --sort recent)', 'window_reached or exhausted', 'no failure', 'closed (as served)'),
    ('filtered by Facebook (profile)', 'exhausted', 'no failure', 'closed (server-filtered)'),
)

ENVELOPE = {
    'ok': 'boolean — false only for the kinds in exit_codes whose ok is false',
    'command': 'string — the command that ran',
    'sort, type, section': 'string — the query options that make this query what it is, when the command has them',
    'stop_reason': 'string — why reading stopped; see stop_reasons (absent only for argument errors)',
    'window': 'object — dated reads only: {since, until, coverage}; coverage follows window_coverage',
    'sponsored_skipped': 'integer — feed only: advertisements left out of results and --limit, first seen here',
    'request_count': 'integer — Facebook requests this invocation made, setup included',
    'max_requests': 'integer — the budget it had',
    'error': 'string — the kind of failure (see exit_codes); absent on success',
    'message': 'string — what failed',
    'fix': 'string — what to do next; a resumable budget stop carries one too',
    'coverage': 'array<string> — what this result does not cover: unread replies or collections, response issues',
    'next': 'string — the continuation command; run it as it is (text output prints it as more:)',
    'out': 'string — the --out file',
    'count': 'integer — records saved in the --out file so far',
    'already_complete': 'boolean — the --out file was complete before this run; nothing was read',
    'replies_incomplete': 'array<object> — replies that were not read, per parent comment, and whether more: retries them',
    'failed_sections': 'array<object> — About collections that failed',
    'updated, missing, failed': 'refresh only — query ids verified and saved, not found, and rejected with a reason',
    'results': 'array<object> — the records: post, comment, entity or about (see schema <object>)',
}
TEXT_HEADER = ('<command>[ · sort=…][ · type=…][ · section=…] · <n> shown[ · sponsored_skipped=<n>] · stopped=<stop_reason> '
               '· requests=<used>/<budget>; dated reads add "window <since>..<until> · <coverage>"; each coverage note '
               'is a "coverage:" line; the last line is "more: <command>" when reading can continue. With --out the '
               'whole result is one line: <command> · <n> saved to "<path>" · … [· already complete] '
               '[· resume: <command>] [· error=<kind> fix=<fix>].')
TEXT_MARKERS = {
    '?': 'a count Facebook did not send',
    'unavailable': 'no author name or URL was sent; there is no handle to follow',
    'text[shown/received chars, complete|truncated]': 'how much of the received text is shown here; truncated means '
                                                       'Facebook marked the received body as cut, so the rest is unknown',
    'pinned': 'pinned to the top of its timeline or group, so it can be old',
    'undated': 'no creation time was sent',
    'incomplete': 'a piece of this record could not be merged; fields may be missing',
    'sponsored': 'an advertisement (shown only with --include-sponsored, or when opened directly)',
    'attachment=': 'what a comment carries besides text, e.g. attachment=photo on a comment with empty text',
    'reply-to=cN': 'a reply to the comment labelled cN above it',
    'shared-from': 'the post this one shares, nested once per level',
}


def describe_result(exit_codes):
    """The result schema. `exit_codes` is cli.py's declaration: [(code, meaning, kinds)]."""
    return {
        'object': 'result',
        'description': 'The JSON envelope every command prints with --json, and the text output built from it.',
        'fields': ENVELOPE,
        'stop_reasons': {reason: f'{meaning} Next: {action}' for reason, (meaning, action) in STOP_REASONS.items()},
        'exit_codes': [{'exit': code, 'meaning': meaning, 'kinds': list(kinds),
                        'ok': all(KINDS[kind][1] for kind in kinds)} for code, meaning, kinds in exit_codes],
        'window_coverage': [{'order': order, 'stopped': stopped, 'failure': failure, 'window': label}
                            for order, stopped, failure, label in COVERAGE],
        'text_header': TEXT_HEADER,
        'text_markers': TEXT_MARKERS,
    }


_ERROR_KINDS = {2: 'argument', 3: 'aside', 4: 'login', 5: 'blocked', 6: 'failed', 7: 'empty', 8: 'partial'}


def error_kind(error):
    """The kind of a failure that ended an invocation before any reading result existed."""
    return _ERROR_KINDS.get(error.code, 'failed')


def window_state(order, stop_reason, failure):
    if failure is not None:
        return 'open — ' + failure.message.rstrip('.')
    if order == 'ranked':
        return 'sample (ranked order)'
    if stop_reason in ('limit_reached', 'budget'):
        return 'open — more: continues'
    if order == 'chronological' and stop_reason in ('window_reached', 'exhausted'):
        return 'closed (as served)'
    if order == 'server' and stop_reason == 'exhausted':
        return 'closed (server-filtered)'
    return 'open'


def failure_envelope(error):
    """An argument error, or a local failure outside any reading."""
    kind = error_kind(error)
    envelope = {'ok': False, 'error': kind, 'message': error.message, 'fix': error.fix, 'results': []}
    if kind != 'argument':
        envelope['stop_reason'] = {'blocked': 'blocked', 'partial': 'budget'}.get(kind, 'query_failure')
    return envelope


def finish(reading, *, command, requests, budget, identity=None, out=None, continuable=False):
    """(kind, envelope) for one reading.

    `reading` holds results, stop_reason (the natural stop when nothing failed), failure (FacebookError or None),
    coverage notes, window ({order, since, until}) and details for JSON; `continuable` says whether a saved cursor
    or committed --out pages let a later invocation continue.
    """
    resumable = continuable
    records = reading.get('results') or []
    failure = reading.get('failure')
    stop_reason = reading.get('stop_reason') or 'exhausted'
    if isinstance(failure, FacebookError):
        if failure.code == 5:
            kind, stop_reason = 'blocked', 'blocked'
        elif failure.code == 8:
            stop_reason = 'budget'
            kind = 'resumable' if resumable else 'partial'
        elif failure.code == 4:
            kind, stop_reason = 'login', 'query_failure'
        else:
            partial = records or reading.get('partial')
            kind, stop_reason = ('partial' if partial else 'aside' if failure.code == 3 else 'failed'), 'query_failure'
    elif reading.get('already_complete'):
        kind = 'complete'
    elif command in ('doctor', 'refresh', 'schema'):
        kind = 'maintenance'
    elif records or (out and reading.get('count')):
        kind = 'records'
    else:
        kind = 'empty'
    envelope = {'ok': KINDS[kind][1], 'command': command, **(identity or {}), 'stop_reason': stop_reason}
    if reading.get('window'):
        window = reading['window']
        envelope['window'] = {'since': window.get('since'), 'until': window.get('until'),
                              'coverage': window_state(window['order'], stop_reason, failure if kind != 'resumable'
                                                       else None)}
    if 'sponsored_skipped' in reading:
        envelope['sponsored_skipped'] = reading['sponsored_skipped']
    envelope['request_count'] = requests
    envelope['max_requests'] = budget
    if kind == 'empty':
        envelope.update(error='empty', message='This query explicitly returned no results.', fix=FIXES['empty'])
    elif failure is not None and failure.code == 8 and kind == 'partial' and command not in ('doctor', 'refresh'):
        message = failure.message
        if message == BUDGET_SPENT:
            message = 'The request budget ran out before anything was saved to continue from.'
        envelope.update(error=kind, message=message, fix=FIXES['budget_restart'])
    elif failure is not None and kind != 'resumable':
        fix = failure.fix
        if fix == FIXES['pagination'] and not continuable:
            fix = FIXES['pagination_restart']
        envelope.update(error=kind, message=failure.message, fix=fix)
    elif kind == 'resumable':
        envelope['fix'] = FIXES['budget_resume']
    coverage = list(reading.get('coverage') or []) + [ISSUES.get(issue, issue) for issue in
                                                      dict.fromkeys(reading.get('issues') or [])]
    if coverage:
        envelope['coverage'] = coverage
    envelope.update(reading.get('details') or {})
    if out is not None:
        envelope.update(out=out, count=reading.get('count', 0))
        if reading.get('already_complete'):
            envelope['already_complete'] = True
    envelope['results'] = records
    return kind, envelope
