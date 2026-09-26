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
    'empty': 'Try a different target or window; an explicitly empty result is not a stale query.',
    'budget_resume': 'Run more: to continue; raise --max-requests if one invocation should read further.',
    'budget_restart': 'Rerun with a larger --max-requests.',
}

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
    return {'ok': False, 'error': error_kind(error), 'message': error.message, 'fix': error.fix, 'results': []}


def finish(reading, *, command, requests, budget, identity=None, out=None, resumable=False):
    """(kind, envelope) for one reading.

    `reading` holds results, stop_reason (the natural stop when nothing failed), failure (FacebookError or None),
    coverage notes, window ({order, since, until}) and details for JSON; `resumable` says whether a saved cursor
    or the --out file lets a later invocation continue after a budget stop.
    """
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
    elif failure is not None and kind != 'resumable':
        envelope.update(error=kind, message=failure.message, fix=failure.fix)
    elif kind == 'resumable':
        envelope['fix'] = FIXES['budget_resume']
    coverage = list(reading.get('coverage') or [])
    if coverage:
        envelope['coverage'] = coverage
    envelope.update(reading.get('details') or {})
    if out is not None:
        envelope.update(out=out, count=reading.get('count', 0))
        if reading.get('already_complete'):
            envelope['already_complete'] = True
    envelope['results'] = records
    return kind, envelope
