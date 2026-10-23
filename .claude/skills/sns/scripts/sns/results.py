"""The result vocabulary, and the one place a reading becomes the public result.

A feature reports what happened (records, why it stopped, a failure, coverage notes); `finish` decides the result
kind, the public stop reason and the fix. Exit numbers belong to cli.py, which maps each kind to one.

Which stop wins when several apply: a person block, then a login, then an unavailable target, then the rest. A stop
that passes by itself (the time limit, a scope's limit, an account hold) after records whose resume state was saved is
a resumable stop (more: continues), not a failure; after records whose state could not be saved it is partial; before
any record it is the failure itself.
"""
from sns.clock import local
from sns.errors import SnsError

# stop_reason → (what it means, what to do next)
STOP_REASONS = {
    'limit_reached': ('The requested number of records was shown (or one page, the default).',
                      'Run more: if you need more.'),
    'exhausted': ('Nothing more to read in the requested range: the source ended, or the command reads one thing.',
                  'Nothing.'),
    'window_reached': ('A newest-first read passed --since; everything up to that boundary was delivered.', 'Nothing.'),
    'not_paginable': ('This surface is one batch.', 'Nothing.'),
    'server_capped': ('The platform serves no more than this (its own cap or sample), though it may report a larger '
                      'total; what lies beyond cannot be asked for.', 'Narrow the query to reach other records.'),
    'pagination_stalled': ('The platform kept serving the same records, so reading stopped there.',
                           'Retry later with more:.'),
    'time_limit': ('The command reached its time limit (it must end within about two minutes).',
                   'Run more: (or the same --out command) to continue.'),
    'rate_limited': ('A limit the platform announced ran out (an operation, a bucket, or this account for a while); '
                     'it passes by itself at the time shown.', 'Run more: after that time; other commands may work.'),
    'blocked': ('The platform showed a checkpoint, a challenge or a lock, or a saved block is still active.',
                'Stop. After a person checks the site in the browser, run <platform> doctor --unblock.'),
    'query_failure': ('A request failed; error, message and fix say why.', 'Follow fix.'),
    'query_restricted': ('The platform restricted the query (adult, forbidden or shielded words). What arrived is '
                         'kept; it is not an empty result.', 'Rephrase the query.'),
    'ready': ('doctor: Aside, the browser, login and account protection are usable.', 'Nothing.'),
    'complete': ('schema finished.', 'Nothing.'),
}

# Result kind → (situation, ok)
KINDS = {
    'records': ('At least one record and no failure.', True),
    'resumable': ('Reading stopped where it can continue (the time limit, or a limit that passes by itself); more: or '
                  'the same --out command resumes.', True),
    'complete': ('The --out file was already final; nothing was read and its result is repeated.', True),
    'maintenance': ('doctor or schema succeeded.', True),
    'argument': ('Arguments, a handle or an output file were rejected before any request.', False),
    'aside': ('Aside or the browser tab was unavailable, timed out or answered invalidly.', False),
    'login': ('Login is required in the Aside browser, or the platform account changed.', False),
    'blocked': ('A checkpoint, challenge, lock or network block a person must clear (now or saved earlier), an '
                'account hold before any record (it passes at the time given), or unreadable protection state.', False),
    'unavailable': ('The target cannot be read by this account: deleted, private, suspended or never existed. '
                    'Retrying does not change it.', False),
    'scope_limit': ('A named limit (an X operation, a Reddit bucket) ran out before any record: not an account problem; '
                    'other commands still work.', False),
    'failed': ('A request failed before any record was read (including a changed answer and the time limit).', False),
    'empty': ('The platform explicitly returned nothing, or nothing fell inside the window.', False),
    'partial': ('Records were read, then a request failed; or a stop could not save where to continue.', False),
}

RESUMABLE = ('time_limit', 'rate_limited')

# The window line of a dated read: the first row that matches wins.
COVERAGE = (
    ('any order', 'any stop', 'a failure', 'open — <failure>'),
    ('ranked (feeds, top search, other rankings)', 'any stop', 'no failure', 'sample (not in date order)'),
    ('any order', 'limit_reached, rate_limited or time_limit', 'no failure', 'open — more: continues'),
    ('newest first', 'window_reached', 'no failure', 'closed (as served)'),
    ('newest first, where the surface\'s end is the account\'s oldest record', 'exhausted', 'no failure',
     'closed (read to the end)'),
    ('a finite list in no date order', 'exhausted', 'no failure', 'closed (read to the end)'),
    ('filtered by the platform (search operators, sort new with dates)', 'exhausted', 'no failure',
     'closed (server-filtered)'),
)


def window_state(order, stop_reason, failure):
    """The coverage label of a date window (see COVERAGE)."""
    if failure is not None:
        return 'open — ' + failure.message.rstrip('.')
    if order == 'ranked':
        return 'sample (not in date order)'
    if stop_reason in ('limit_reached', 'rate_limited', 'time_limit'):
        return 'open — more: continues'
    if order == 'newest_first' and stop_reason == 'window_reached':
        return 'closed (as served)'
    if order in ('newest_first', 'finite') and stop_reason == 'exhausted':
        return 'closed (read to the end)'
    if order == 'server' and stop_reason == 'exhausted':
        return 'closed (server-filtered)'
    return 'open'


def _failure_kind(error, has_records):
    if error.kind in ('blocked', 'login', 'unavailable', 'argument'):
        return error.kind
    if has_records:
        return 'partial'
    return error.kind


def _stop_of(error, kind):
    if error.reason in RESUMABLE:
        return error.reason
    if kind == 'blocked':
        return 'blocked'
    if kind == 'empty':
        return 'exhausted'
    if error.reason == 'restricted':
        return 'query_restricted'
    if error.reason == 'pagination_stalled':
        return 'pagination_stalled'
    return 'query_failure'


def _limit(error):
    """What a stop that passes by itself says about its time: {scope, reset, next_allowed_at, …}."""
    details = error.details if isinstance(error, SnsError) else {}
    reset = details.get('reset') or details.get('until')
    if not reset:
        return None
    following = details.get('next_allowed_at') or reset
    return {'scope': details.get('scope'), 'reset': reset, 'next_allowed_at': following,
            'reset_local': local(reset), 'next_allowed_local': local(following)}


def failure_envelope(error, platform=None, command=None):
    """The envelope of an invocation that ended before any reading: always ok false, with error, message, fix."""
    kind = _failure_kind(error, False)
    envelope = {'ok': False}
    if platform:
        envelope['platform'] = platform.replace('_', '-')
    if command:
        envelope['command'] = command
    if kind != 'argument':
        envelope['stop_reason'] = _stop_of(error, kind)
    envelope.update(error=kind, message=error.message, fix=error.fix)
    if _limit(error):
        envelope['limit'] = _limit(error)
    if error.details.get('verification_reason'):
        envelope['verification_reason'] = error.details['verification_reason']
    envelope['results'] = []
    return kind, envelope


def _sections_kind(sections):
    """A composite command whose sections all succeeded (the pipeline has already made a failed section the
    reading's failure): records when any section read something or the primary one succeeded, else empty."""
    return ('records' if any(s.get('data') for s in sections) or any(s.get('primary') for s in sections)
            else 'empty'), None


def finish(reading, *, platform, command, report=None, identity=None, out=None):
    """(kind, envelope) of one reading.

    reading: results (or sections), stop_reason (the natural stop when nothing failed), failure (SnsError or None),
    coverage notes, window (Window.describe()), details for JSON, next, continuable (a saved handle or committed --out
    pages let a later invocation continue), count/already_complete for --out. report: what the connection saw
    (requests, setup, unwatched, session_reset, limits).
    """
    report = report or {}
    records = reading.get('results') or []
    sections = reading.get('sections')
    failure = reading.get('failure')
    stop_reason = reading.get('stop_reason') or 'exhausted'
    continuable = bool(reading.get('continuable'))
    has_records = bool(records) or bool(reading.get('partial')) or (out is not None and bool(reading.get('count')))
    worst = None  # the failed section a composite command reports
    if isinstance(failure, SnsError):
        if failure.reason in RESUMABLE and has_records and failure.kind != 'argument':
            kind = 'resumable' if continuable else 'partial'
            stop_reason = failure.reason
        else:
            kind = _failure_kind(failure, has_records)
            stop_reason = _stop_of(failure, kind)
    elif sections is not None:
        kind, worst = _sections_kind(sections)
    elif reading.get('already_complete'):
        kind = 'complete'
    elif command in ('doctor', 'schema'):
        kind = 'maintenance'
    elif stop_reason == 'pagination_stalled':
        kind = 'partial'
    elif records or (out is not None and reading.get('count')) or continuable:
        kind = 'records'  # nothing shown yet is not an empty result while a continuation exists
    else:
        kind = 'empty'
    envelope = {'ok': KINDS[kind][1], 'platform': platform.replace('_', '-'), 'command': command}
    if identity:
        envelope['query'] = identity
    envelope['stop_reason'] = stop_reason
    window = reading.get('window')
    if window:
        judged = failure if kind not in ('resumable', 'empty', 'complete') else None
        envelope['window'] = {**{k: v for k, v in window.items() if k != 'order'},
                              'coverage': window_state(window.get('order'), stop_reason, judged)}
    envelope['request_count'] = report.get('requests', 0)
    if report.get('setup'):
        envelope['setup_requests'] = report['setup']
    if report.get('unwatched'):
        envelope['unwatched_requests'] = report['unwatched']
    if report.get('session_reset'):
        envelope['session_reset'] = True
    if report.get('limits'):
        envelope['limits'] = report['limits']
    if isinstance(failure, SnsError) and _limit(failure):
        envelope['limit'] = _limit(failure)
    if kind == 'empty':
        message = failure.message if isinstance(failure, SnsError) else 'This query returned no results.'
        fix = failure.fix if isinstance(failure, SnsError) else 'Try another target, order or window; an explicitly ' \
                                                                'empty result is not a failure to read.'
        envelope.update(error='empty', message=message, fix=fix)
    elif kind == 'partial' and failure is None:
        envelope.update(error='partial', message=STOP_REASONS[stop_reason][0], fix=STOP_REASONS[stop_reason][1])
    elif worst is not None:
        envelope.update(error=kind, message=worst['message'], fix=worst['fix'])
    elif failure is not None and kind != 'resumable':
        envelope.update(error=kind, message=failure.message, fix=failure.fix)
        if failure.details.get('verification_reason'):
            envelope['verification_reason'] = failure.details['verification_reason']
    elif kind == 'resumable':
        envelope['fix'] = {'rate_limited': 'Run more: after the time shown; other commands may work now.',
                           'time_limit': 'Run more: to continue.'}[stop_reason]
    coverage = list(dict.fromkeys(reading.get('coverage') or []))
    if coverage:
        envelope['coverage'] = coverage
    if reading.get('next'):
        envelope['next'] = reading['next']
    envelope.update(reading.get('details') or {})
    if out is not None:
        envelope.update(out=out, count=reading.get('count', 0))
        if reading.get('already_complete'):
            envelope['already_complete'] = True
    if sections is not None:
        envelope['sections'] = sections
    else:
        envelope['results'] = records
    return kind, envelope


ENVELOPE = {
    'ok': 'boolean — false only for the kinds whose ok is false (see kinds)',
    'platform': 'string — x, threads, reddit, facebook or naver-blog',
    'command': 'string — the command that ran',
    'query': 'object — the options that make this query what it is (sort, tab, type, feed, …)',
    'stop_reason': 'string — why reading stopped; see stop_reasons (absent for argument errors)',
    'window': 'object — dated reads only: {since, until, tz, start_utc, end_utc, coverage}; coverage follows '
              'window_coverage',
    'request_count': 'integer — requests this invocation made, opening or reloading a tab included',
    'setup_requests': 'integer — of request_count, what opening or reloading the dedicated tab cost (the page\'s own '
                      'requests while it loads); absent when the tab was already open',
    'unwatched_requests': 'integer — requests the open tab made between commands (not in request_count)',
    'session_reset': 'boolean — the saved session was unreadable and was started over',
    'limits': 'object — the platform\'s announced limits this command used: {scope: {status, limit, remaining, '
              'reset_at, slow_until, blocked_until}}; status unknown means the platform did not report it',
    'limit': 'object — a stop that passes by itself stopped it: {scope (null: the whole account), reset, '
             'next_allowed_at, reset_local, next_allowed_local}',
    'verification_reason': 'string — doctor --unblock only: why the check that could lift a block was not made or '
                           'not clean; the block stays',
    'error': 'string — the kind of failure (see kinds); absent on success',
    'message': 'string — what failed',
    'fix': 'string — what to do next; a resumable stop carries one too',
    'coverage': 'array<string> — what this result does not cover: unread parts, left-out entries, response issues',
    'next': 'string — the command that continues this reading; run it as it is (text prints it as more:)',
    'out': 'string — the --out file',
    'count': 'integer — records saved in the --out file so far',
    'already_complete': 'boolean — the --out file was final before this run; nothing was read',
    'results': 'array<object> — the records (see schema <object>); doctor returns its checks, schema its documents',
    'sections': 'array<object> — a composite command instead of results: {name, ok, primary, data | error}; a failed '
                'section stays beside the others',
}

TEXT = {
    'header': '<platform> <command>[ · key=value …] · <n> shown · stopped=<stop_reason> · requests=<n>[ · tab opened '
              '(+<n> requests)][ · unwatched=<n>][ · limit <scope> <remaining> of <limit> left resets <local time>]',
    'window': 'dated reads add a second line: window <since>..<until> <tz> · <coverage>',
    'records': 'one record per label ([p1] post, [r1] reply, [c1] comment, [a1] account, …); each record ends with the '
               'arguments of the next command (url: <command> <url> opens it alone; replies <handle> reads more under '
               'it)',
    'text': 'text[N of M chars shown]: N characters of the M received are shown (--chars); --chars 0 shows everything',
    'tail': 'coverage: <note> lines, then more: <command> when reading can continue. With --out the whole result is '
            'one line: <platform> <command> · <n> saved to "<path>" · stopped=… · requests=… [· resume: <command>] '
            '[· error=<kind> fix=<fix>]',
}


def describe(exit_codes):
    """The result schema; `exit_codes` is cli.py's declaration [(code, meaning, kinds)]."""
    return {
        'object': 'result',
        'description': 'The JSON envelope a command prints with --json (doctor and schema always print one), and the '
                       'text page built from it.',
        'fields': ENVELOPE,
        'stop_reasons': {reason: f'{meaning} Next: {action}' for reason, (meaning, action) in STOP_REASONS.items()},
        'kinds': {kind: situation for kind, (situation, _) in KINDS.items()},
        'exit_codes': [{'exit': code, 'meaning': meaning, 'kinds': list(kinds)} for code, meaning, kinds in exit_codes],
        'window_coverage': [{'order': order, 'stopped': stopped, 'failure': failure, 'window': label}
                            for order, stopped, failure, label in COVERAGE],
        'text': TEXT,
        'detail': 'Every record carries the command that opens it alone; it reads live, so what it shows can differ '
                  'from what was shown before.',
    }
