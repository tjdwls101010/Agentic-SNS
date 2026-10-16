"""The result vocabulary, and the one place a reading becomes the public result.

A feature reports what happened (records, why it stopped, a failure, coverage notes); `finish` decides the result
kind, the public stop reason and the fix. Exit numbers belong to cli.py, which maps each kind to one.
"""
from threads.errors import ThreadsError

# stop_reason → (what it means, what to do next)
STOP_REASONS = {
    'limit_reached': ('The requested number of records was shown.', 'Run more: if you need more.'),
    'exhausted': ('Nothing more to read in the requested range: the source ended, or the command reads one thing.',
                  'Nothing.'),
    'window_reached': ('A newest-first read passed --since; everything up to that boundary was delivered.', 'Nothing.'),
    'not_paginable': ('This surface is one batch (account search, liked, saved).', 'Nothing.'),
    'server_capped': ('Threads returned its own sample (followers), not the whole list; reported_total is larger.',
                      'Nothing more can be read here.'),
    'budget': ('--max-requests was spent.', 'Run more: (or rerun the same --out command); raise --max-requests if '
                                            'one invocation should read further.'),
    'blocked': ('Threads showed a checkpoint or a rate limit, or a saved block is still active.',
                'Stop. After a person checks Threads in the browser, run doctor --unblock.'),
    'query_failure': ('A request failed; error, message and fix say why.', 'Follow fix.'),
    'ready': ('doctor: Aside, the browser tab, login and account protection are usable.', 'Nothing.'),
    'complete': ('schema finished.', 'Nothing.'),
}

# Result kind → (situation, ok)
KINDS = {
    'records': ('At least one record and no failure.', True),
    'resumable': ('--max-requests ran out where reading can continue; more: or the same --out command resumes.', True),
    'complete': ('The --out file was already complete; nothing was read.', True),
    'maintenance': ('doctor or schema succeeded.', True),
    'argument': ('Arguments, a handle or an output file were rejected before any request.', False),
    'aside': ('Aside or the browser tab was unavailable, timed out or answered invalidly.', False),
    'login': ('Threads login is required in the Aside browser.', False),
    'blocked': ('A checkpoint or rate limit, now or saved from an earlier invocation; or unreadable protection state.',
                False),
    'unavailable': ('The target cannot be read by this account: deleted, private and not followed, or a post that '
                    'redirected away. Retrying does not change it.', False),
    'failed': ('A request failed before any record was read (including a query Threads no longer accepts).', False),
    'empty': ('Threads explicitly returned nothing, or nothing fell inside the window.', False),
    'partial': ('Records were read, then a request failed; or the budget ran out with nothing to continue from.',
                False),
}

FIXES = {
    'budget_resume': 'Run more: to continue; raise --max-requests if one invocation should read further.',
    'budget_restart': 'Rerun with a larger --max-requests.',
    'empty': 'Try another target, order or window; an explicitly empty result is not a failure to read.',
}

# The window line of a dated read: the first row that matches wins.
COVERAGE = (
    ('any order', 'any stop', 'a failure', 'open — <failure>'),
    ('not by writing time (for you feed, search, reposts and media tabs)', 'any stop', 'no failure',
     'sample (not in date order)'),
    ('any order', 'limit_reached or budget', 'no failure', 'open — more: continues'),
    ('newest first (following feed, threads and replies tabs)', 'window_reached or exhausted', 'no failure',
     'closed (as served)'),
    ('filtered by Threads (search dates)', 'exhausted', 'no failure', 'closed (server-filtered)'),
)


def window_state(order, stop_reason, failure):
    """The coverage label of a date window (see COVERAGE)."""
    if failure is not None:
        return 'open — ' + failure.message.rstrip('.')
    if order == 'unordered':
        return 'sample (not in date order)'
    if stop_reason in ('limit_reached', 'budget'):
        return 'open — more: continues'
    if order == 'newest_first' and stop_reason in ('window_reached', 'exhausted'):
        return 'closed (as served)'
    if order == 'server' and stop_reason == 'exhausted':
        return 'closed (server-filtered)'
    return 'open'


def _failure_kind(error, has_records):
    """A failure's kind: blocked (5) > login (4) > unavailable (9) > the rest."""
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
    return {3: 'aside', 7: 'empty', 8: 'partial'}.get(error.code, 'failed')


def failure_envelope(error, command=None):
    """The envelope of an invocation that ended before any reading: always ok false, with error, message, fix."""
    kind = _failure_kind(error, False)
    envelope = {'ok': False}
    if command:
        envelope['command'] = command
    if kind != 'argument':
        envelope['stop_reason'] = {'blocked': 'blocked', 'partial': 'budget', 'empty': 'exhausted'}.get(kind, 'query_failure')
    envelope.update(error=kind, message=error.message, fix=error.fix, results=[])
    return kind, envelope


def finish(reading, *, command, requests, budget, identity=None, out=None, setup=0, unwatched=0, session_reset=False):
    """(kind, envelope) of one reading.

    `reading` holds results, stop_reason (the natural stop when nothing failed), failure (ThreadsError or None),
    coverage notes, window ({order, since, until}), details for JSON, and continuable: whether a saved handle or
    committed --out pages let a later invocation continue.
    """
    records = reading.get('results') or []
    failure = reading.get('failure')
    stop_reason = reading.get('stop_reason') or 'exhausted'
    continuable = bool(reading.get('continuable'))
    if isinstance(failure, ThreadsError):
        if failure.code == 8:
            kind, stop_reason = ('resumable' if continuable else 'partial'), 'budget'
        else:
            kind = _failure_kind(failure, bool(records) or bool(reading.get('partial')))
            stop_reason = {'blocked': 'blocked', 'empty': 'exhausted'}.get(kind, 'query_failure')
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
        envelope['tab_opened_requests'] = setup
    if unwatched:
        envelope['unwatched_requests'] = unwatched
    if session_reset:
        envelope['session_reset'] = True
    envelope['max_requests'] = budget
    if kind == 'empty':
        message = failure.message if isinstance(failure, ThreadsError) else 'This query returned no results.'
        envelope.update(error='empty', message=message, fix=FIXES['empty'])
    elif kind == 'partial' and failure.code == 8:
        message = ('The request budget ran out before anything was saved to continue from.'
                   if failure.reason == 'budget' else failure.message)
        envelope.update(error='partial', message=message, fix=FIXES['budget_restart'])
    elif failure is not None and kind != 'resumable':
        envelope.update(error=kind, message=failure.message, fix=failure.fix)
    elif kind == 'resumable':
        envelope['fix'] = FIXES['budget_resume']
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
        'detail': 'Every record carries post <url>, which opens that one post live; it does not replay an earlier '
                  'response, so what it shows can differ from what was shown before.',
    }


REQUESTS = ('request_count counts what this invocation sent to Threads (each GraphQL query, document read, retry) '
            'and every Threads request (threads.com, threads.net, instagram.com, facebook.com) the dedicated tab '
            'finished while it ran; static CDN files (cdninstagram.com, fbcdn.net) are not counted. What the page '
            'itself loads is prepaid: opening the tab, or loading it again after it was emptied or its app was '
            'refused, is reserved at 40 (tab_opened_requests, not charged to max_requests), and requests the page '
            'finishes later in the same command use up that reservation first. Learning a refused query reads one '
            'document per try, also outside max_requests; one command learns at most 3 times and reloads at most '
            'once. Requests the open tab made between commands (its notification and screen-time polling, impression '
            'logs) are reported as unwatched_requests and logged, not charged; their statuses and suspect bodies are '
            'still checked, so a block seen there stops the next command before it sends anything. The tab is '
            'emptied about 5 minutes after the last command, which ends that polling; a block empties it at once. '
            'All invocations share one cross-process lock and 1-2 s pacing for the account.')

ENVELOPE = {
    'ok': 'boolean — false only for the kinds whose ok is false (see kinds)',
    'command': 'string — the command that ran',
    'sort, feed, tab, type, relation': 'string — the order or surface that makes this query what it is, when the '
                                       'command has one',
    'stop_reason': 'string — why reading stopped; see stop_reasons (absent for argument errors)',
    'window': 'object — dated reads only: {since, until, coverage}; coverage follows window_coverage',
    'request_count': 'integer — requests this invocation made (see requests)',
    'tab_opened_requests': 'integer — of request_count, the requests of opening or reloading the dedicated tab (not '
                           'charged to max_requests); absent when the tab was already open',
    'unwatched_requests': 'integer — requests the open tab made between commands (not in request_count)',
    'session_reset': 'boolean — the saved session was unreadable and was started over (a new tab was opened)',
    'max_requests': 'integer — the budget it had',
    'error': 'string — the kind of failure (see kinds); absent on success',
    'message': 'string — what failed',
    'fix': 'string — what to do next; a resumable budget stop carries one too',
    'coverage': 'array<string> — what this result does not cover: unread parts, response issues',
    'next': 'string — the command that continues this reading; run it as it is (text prints it as more:)',
    'replies': 'object — post and replies: the reply coverage (reported_direct, received_direct, shown_direct, '
               'shown_descendants, unshown_received, unavailable, unfetched, unfetched_is_estimate)',
    'reported_total': 'integer — graph followers: the total Threads reports; the sample holds fewer',
    'out': 'string — the --out file',
    'count': 'integer — records saved in the --out file so far',
    'already_complete': 'boolean — the --out file was complete before this run; nothing was read',
    'results': 'array<object> — post or account records (see schema post, account); doctor returns its checks, '
               'schema its documents',
}

TEXT = {
    'header': '<command>[ · feed=…][ · sort=…][ · tab=…] · <n> shown · stopped=<stop_reason> · '
              'requests=<charged>/<budget>[ · tab opened (+<n> requests)][ · unwatched=<n>]',
    'window': 'dated reads add a second line: window <since>..<until> · <coverage>',
    'records': '[p<n>] posts, [r<n>] replies, [a<n>] accounts; each record ends with the arguments of the next '
               'command: url (post <url> opens that one post), author (profile, about), replies <handle> (more '
               'replies under it)',
    'text': 'text[N of M chars shown]: N characters of the M received are shown (--chars); Threads sends whole '
            'texts, so --chars 0 shows everything received',
    'markers': {'?': 'a count Threads did not send (or the author hid)', 'unavailable': 'a post that was deleted or '
                'is not visible to this account', 'pinned': 'pinned to the top of a profile, so it can be old',
                'undated': 'no writing time was sent', 'reply-to=<label>': 'answers that record',
                'continuation': 'the author continuing their own post', 'quoting': 'the post this one quotes: '
                'its words are its own author\'s', 'repost of': 'the post this one shares: it adds no words, and '
                'the date is the original\'s', 'alt=': 'Threads\' description of a photo; often generated '
                'automatically and can be wrong'},
    'tail': 'coverage: <note> lines, then more: <command> when reading can continue. With --out the whole result '
            'is one line: <command> · <n> saved to "<path>" · stopped=… · requests=… [· resume: <command>] '
            '[· error=<kind> fix=<fix>]',
}
