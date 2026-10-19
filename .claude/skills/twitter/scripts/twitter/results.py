"""The result vocabulary, and the one place a reading becomes the public result.

A feature reports what happened (records, why it stopped, a failure, coverage notes); `finish` decides the result
kind, the public stop reason and the fix. Exit numbers belong to cli.py, which maps each kind to one.

Which stop wins when several apply: a block a person must clear, then a login, then an unavailable target, then an
operation's limit, then the rest. An operation's limit or the command's deadline after records whose resume state was
saved is a resumable stop (more: continues), not a failure; before any record it is the failure itself.
"""
import time

from twitter.errors import TwitterError

# stop_reason → (what it means, what to do next)
STOP_REASONS = {
    'limit_reached': ('The requested number of records was shown.', 'Run more: if you need more.'),
    'exhausted': ('Nothing more to read in the requested range: the source ended, or the command reads one thing.',
                  'Nothing.'),
    'window_reached': ('A newest-first read passed --since; everything up to that boundary was delivered.', 'Nothing.'),
    'not_paginable': ('This surface is one batch.', 'Nothing.'),
    'budget': ('--max-requests was spent.', 'Run more: (or rerun the same --out command); raise --max-requests if '
                                            'one invocation should read further.'),
    'rate_limited': ('X\'s limit for the operation this read uses ran out; it is not an account block, and other '
                     'commands still work.', 'Run more: after the reset shown (limit.next_allowed_at).'),
    'time_limit': ('The command reached its time limit (it must end within about two minutes).',
                   'Run more: (or the same --out command) to continue.'),
    'blocked': ('X locked the account or showed a challenge, or a saved block is still active.',
                'Stop. After a person checks x.com in the browser, run doctor --unblock.'),
    'query_failure': ('A request failed; error, message and fix say why.', 'Follow fix.'),
    'ready': ('doctor: Aside, the browser tab, login and account protection are usable.', 'Nothing.'),
    'complete': ('schema finished.', 'Nothing.'),
}

# Result kind → (situation, ok)
KINDS = {
    'records': ('At least one record and no failure.', True),
    'resumable': ('Reading stopped where it can continue (budget, an operation\'s limit or the time limit); more: or '
                  'the same --out command resumes.', True),
    'complete': ('The --out file was already complete; nothing was read.', True),
    'maintenance': ('doctor or schema succeeded.', True),
    'argument': ('Arguments, a handle or an output file were rejected before any request.', False),
    'aside': ('Aside or the browser tab was unavailable, timed out or answered invalidly.', False),
    'login': ('X login is required in the Aside browser (or it changed accounts mid-command).', False),
    'blocked': ('A lock or challenge a person must clear, now or saved from an earlier invocation; or unreadable '
                'protection state.', False),
    'unavailable': ('The target cannot be read by this account: deleted, suspended, protected and not followed, or '
                    'never existed. Retrying does not change it.', False),
    'rate_limited': ('X\'s limit for this operation ran out before any record: not an account problem; other commands '
                     'still work.', False),
    'failed': ('A request failed before any record was read (including a read X no longer accepts, and the time limit).',
               False),
    'empty': ('X explicitly returned nothing, or nothing fell inside the window.', False),
    'partial': ('Records were read, then a request failed; or a stop could not save where to continue.', False),
}

FIXES = {
    'budget_resume': 'Run more: to continue; raise --max-requests if one invocation should read further.',
    'budget_restart': 'Rerun with a larger --max-requests.',
    'limit_resume': 'Run more: after the time shown; other commands work now.',
    'time_resume': 'Run more: to continue.',
    'empty': 'Try another target, order or window; an explicitly empty result is not a failure to read.',
}

# The window line of a dated read: the first row that matches wins.
COVERAGE = (
    ('any order', 'any stop', 'a failure', 'open — <failure>'),
    ('ranked or unordered (for you and following feeds, top search, lists, bookmarks, likes)', 'any stop',
     'no failure', 'sample (not in date order)'),
    ('any order', 'limit_reached, budget, rate_limited or time_limit', 'no failure', 'open — more: continues'),
    ('newest first (profile posts and replies tabs, latest search)', 'window_reached or exhausted', 'no failure',
     'closed (as served)'),
    ('a finite list in no date order', 'exhausted', 'no failure', 'closed (read to the end)'),
    ('filtered by X (search since:/until:)', 'exhausted', 'no failure', 'closed (server-filtered)'),
)


def window_state(order, stop_reason, failure):
    """The coverage label of a date window (see COVERAGE)."""
    if failure is not None:
        return 'open — ' + failure.message.rstrip('.')
    if order == 'unordered':
        return 'sample (not in date order)'
    if stop_reason in ('limit_reached', 'budget', 'rate_limited', 'time_limit'):
        return 'open — more: continues'
    if order == 'newest_first' and stop_reason in ('window_reached', 'exhausted'):
        return 'closed (as served)'
    if order == 'finite' and stop_reason == 'exhausted':
        return 'closed (read to the end)'
    if order == 'server' and stop_reason == 'exhausted':
        return 'closed (server-filtered)'
    return 'open'


def _failure_kind(error, has_records):
    """A failure's kind: blocked (5) > login (4) > unavailable (9) > the operation's limit (10) > the rest."""
    if error.code == 5:
        return 'blocked'
    if error.code == 4:
        return 'login'
    if error.code == 9:
        return 'unavailable'
    if error.code == 2:
        return 'argument'
    if has_records:
        return 'partial'
    if error.code == 10:
        return 'rate_limited'
    return {3: 'aside', 7: 'empty', 8: 'partial'}.get(error.code, 'failed')


def _local(moment):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(moment)) if isinstance(moment, (int, float)) else None


def _limit(error):
    details = error.details if isinstance(error, TwitterError) else {}
    if not details.get('operation') and not details.get('reset'):
        return None
    return {'operation': details.get('operation'), 'reset': details.get('reset'),
            'next_allowed_at': details.get('next_allowed_at') or details.get('reset'),
            'reset_local': _local(details.get('reset')),
            'next_allowed_local': _local(details.get('next_allowed_at') or details.get('reset'))}


def failure_envelope(error, command=None):
    """The envelope of an invocation that ended before any reading: always ok false, with error, message, fix."""
    kind = _failure_kind(error, False)
    envelope = {'ok': False}
    if command:
        envelope['command'] = command
    if kind != 'argument':
        envelope['stop_reason'] = {'blocked': 'blocked', 'partial': 'budget', 'empty': 'exhausted',
                                   'rate_limited': 'rate_limited'}.get(kind, 'query_failure')
        if error.reason == 'time_limit':
            envelope['stop_reason'] = 'time_limit'
    envelope.update(error=kind, message=error.message, fix=error.fix)
    if kind == 'rate_limited' and _limit(error):
        envelope['limit'] = _limit(error)
    if isinstance(error, TwitterError) and error.details.get('verification_reason'):
        envelope['verification_reason'] = error.details['verification_reason']
    envelope['results'] = []
    return kind, envelope


def finish(reading, *, command, requests, budget, identity=None, out=None, setup=0, unwatched=0, session_reset=False):
    """(kind, envelope) of one reading.

    `reading` holds results, stop_reason (the natural stop when nothing failed), failure (TwitterError or None),
    coverage notes, window ({order, since, until}), details for JSON, and continuable: whether a saved handle or
    committed --out pages let a later invocation continue.
    """
    records = reading.get('results') or []
    failure = reading.get('failure')
    stop_reason = reading.get('stop_reason') or 'exhausted'
    continuable = bool(reading.get('continuable'))
    has_records = bool(records) or bool(reading.get('partial')) or (out is not None and bool(reading.get('count')))
    if isinstance(failure, TwitterError):
        resumable = {8: 'budget', 10: 'rate_limited'}.get(failure.code) or \
            ('time_limit' if failure.reason == 'time_limit' else None)
        if resumable and (failure.code == 8 or has_records) and continuable:
            kind, stop_reason = 'resumable', resumable
        elif failure.code == 8:
            kind, stop_reason = 'partial', 'budget'
        else:
            kind = _failure_kind(failure, has_records)
            stop_reason = {'blocked': 'blocked', 'empty': 'exhausted', 'rate_limited': 'rate_limited'}.get(
                kind, 'time_limit' if failure.reason == 'time_limit' else 'query_failure')
    elif reading.get('already_complete'):
        kind = 'complete'
    elif command in ('doctor', 'schema'):
        kind = 'maintenance'
    elif records or (out is not None and reading.get('count')) or continuable:
        kind = 'records'  # nothing shown yet is not an empty result while a continuation exists
    else:
        kind = 'empty'
    envelope = {'ok': KINDS[kind][1], 'command': command, **(identity or {}), 'stop_reason': stop_reason}
    if reading.get('window'):
        window = reading['window']
        envelope['window'] = {'since': window.get('since'), 'until': window.get('until'),
                              'coverage': window_state(window['order'], stop_reason,
                                                       failure if kind not in ('resumable', 'empty') else None)}
    envelope['request_count'] = requests
    if setup:
        envelope['setup_requests'] = setup
    if unwatched:
        envelope['unwatched_requests'] = unwatched
    if session_reset:
        envelope['session_reset'] = True
    envelope['max_requests'] = budget
    if isinstance(failure, TwitterError) and failure.code == 10 and _limit(failure):
        envelope['limit'] = _limit(failure)
    if kind == 'empty':
        message = failure.message if isinstance(failure, TwitterError) else 'This query returned no results.'
        envelope.update(error='empty', message=message, fix=FIXES['empty'])
    elif kind == 'partial' and failure.code == 8:
        message = ('The request budget ran out before anything was saved to continue from.'
                   if failure.reason == 'budget' else failure.message)
        envelope.update(error='partial', message=message, fix=FIXES['budget_restart'])
    elif failure is not None and kind != 'resumable':
        envelope.update(error=kind, message=failure.message, fix=failure.fix)
        if failure.details.get('verification_reason'):
            envelope['verification_reason'] = failure.details['verification_reason']
    elif kind == 'resumable':
        envelope['fix'] = {'budget': FIXES['budget_resume'], 'rate_limited': FIXES['limit_resume'],
                           'time_limit': FIXES['time_resume']}[stop_reason]
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
    envelope['results'] = records
    return kind, envelope


REQUESTS = ('request_count counts what this invocation sent to X — each GraphQL read and retry, exactly — and every '
            'x.com or api.x.com request the dedicated tab finished while it ran; static files (abs.twimg.com, '
            'pbs.twimg.com, video.twimg.com) are not counted. The skill\'s own requests carry a nonce in their URL '
            'fragment (never sent to X) so the tab\'s timing list tells them apart and they are not counted twice; '
            'doctor says whether that matching works in this browser (if not, a request can be counted twice: an '
            'over-count, never an under-count). Opening the tab, or loading it again, is measured the same way when '
            'the skill\'s observer was installed before the app ran (about 14 requests) and charged 20 when it came '
            'later (setup_requests, not charged to max_requests); what the page requested before the observer existed '
            'is the one estimated part. Requests the open tab made between commands are reported as '
            'unwatched_requests and logged, not charged; a block seen there still stops the next command before it '
            'sends anything. All invocations share one lock and 1-2 s pacing for the account, slow down when X\'s '
            'per-operation limit is nearly used, and end within about two minutes.')

ENVELOPE = {
    'ok': 'boolean — false only for the kinds whose ok is false (see kinds)',
    'command': 'string — the command that ran',
    'sort, feed, tab, type, relation, collection': 'string — the order or surface that makes this query what it is',
    'stop_reason': 'string — why reading stopped; see stop_reasons (absent for argument errors)',
    'window': 'object — dated reads only: {since, until, coverage}; coverage follows window_coverage',
    'request_count': 'integer — requests this invocation made (see requests)',
    'setup_requests': 'integer — of request_count, opening or reloading the dedicated tab (not charged to '
                      'max_requests); absent when the tab was already open',
    'unwatched_requests': 'integer — requests the open tab made between commands (not in request_count)',
    'session_reset': 'boolean — the saved session was unreadable and was started over (a new tab was opened)',
    'max_requests': 'integer — the budget it had',
    'limit': 'object — an operation\'s limit stopped it: {operation, reset, next_allowed_at, reset_local, '
             'next_allowed_local}; reset is when X refills the limit, next_allowed_at when the next request of '
             'that operation may go (Unix seconds and local time)',
    'verification_reason': 'string — doctor --unblock only: why the check that could lift a block was not made or not '
                           'clean (rate_limited, logged_out, account_mismatch, moved, time_limit, aside); the block '
                           'stays',
    'error': 'string — the kind of failure (see kinds); absent on success',
    'message': 'string — what failed',
    'fix': 'string — what to do next; a resumable stop carries one too',
    'coverage': 'array<string> — what this result does not cover: unread parts, response issues',
    'next': 'string — the command that continues this reading; run it as it is (text prints it as more:)',
    'replies': 'object — post and replies: the reply coverage (reported, direct_shown, nested_shown, branches, hidden, '
               'unavailable)',
    'out': 'string — the --out file',
    'count': 'integer — records saved in the --out file so far',
    'already_complete': 'boolean — the --out file was complete before this run; nothing was read',
    'results': 'array<object> — post or account records (see schema post, account); doctor returns its checks, '
               'schema its documents',
}

TEXT = {
    'header': '<command>[ · feed=…][ · sort=…][ · tab=…] · <n> shown · stopped=<stop_reason> · '
              'requests=<charged>/<budget>[ · tab opened (+<n> requests)][ · unwatched=<n>][ · x-limit <operation> '
              'resets <local time> · next <local time>]',
    'window': 'dated reads add a second line: window <since>..<until> · <coverage>',
    'records': '[p<n>] posts, [r<n>] replies, [a<n>] accounts, [t<n>] trends; each record ends with the arguments of '
               'the next command: url (post <url> opens that one post), author (profile, about), replies <handle> '
               '(more replies under it)',
    'text': 'text[N of M chars shown]: N characters of the M received are shown (--chars); --chars 0 shows everything',
    'tail': 'coverage: <note> lines, then more: <command> when reading can continue. With --out the whole result '
            'is one line: <command> · <n> saved to "<path>" · stopped=… · requests=… [· resume: <command>] '
            '[· error=<kind> fix=<fix>]',
}


def describe(exit_codes):
    """The result schema; `exit_codes` is cli.py's declaration [(code, meaning, kinds)]."""
    return {
        'object': 'result',
        'description': 'The JSON envelope a command prints with --json (doctor and schema always print one), and '
                       'the text page built from it.',
        'fields': ENVELOPE,
        'stop_reasons': {reason: f'{meaning} Next: {action}' for reason, (meaning, action) in STOP_REASONS.items()},
        'kinds': {kind: situation for kind, (situation, _) in KINDS.items()},
        'exit_codes': [{'exit': code, 'meaning': meaning, 'kinds': list(kinds)} for code, meaning, kinds in exit_codes],
        'window_coverage': [{'order': order, 'stopped': stopped, 'failure': failure, 'window': label}
                            for order, stopped, failure, label in COVERAGE],
        'requests': REQUESTS,
        'text': TEXT,
        'detail': 'Every record carries the command that opens it alone (post <url>, about <@handle>, …); it reads '
                  'live, so what it shows can differ from what was shown before.',
    }
