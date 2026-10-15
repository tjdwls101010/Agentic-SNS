"""The result vocabulary, and the one place a reading becomes the public result.

A feature reports what happened (records, why it stopped, a failure, coverage notes); `finish` decides the result
kind, the public stop reason and the fix. Exit numbers belong to cli.py, which maps each kind to one.
"""
from facebook.errors import FacebookError

# stop_reason → (what it means, what to do next)
STOP_REASONS = {
    'limit_reached': ('The requested number of records was shown.', 'Run more: if you need more.'),
    'exhausted': ('Nothing more to read in the requested range: the source ended, or the command reads one thing.',
                  'Nothing.'),
    'window_reached': ('A newest-first read passed --since; everything up to that boundary was delivered.', 'Nothing.'),
    'budget': ('--max-requests was spent.', 'Run more: (or rerun the same --out command); raise --max-requests if '
                                            'one invocation should read further.'),
    'blocked': ('Facebook showed a checkpoint or a rate limit, or a saved block is still active.',
                'Stop. After a person checks Facebook in the browser, run doctor --unblock.'),
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
    'login': ('Facebook login is required in the Aside browser.', False),
    'blocked': ('A checkpoint or rate limit, now or saved from an earlier invocation; or unreadable protection state.',
                False),
    'failed': ('A request failed before any record was read.', False),
    'empty': ('Facebook explicitly returned nothing, or nothing fell inside the window.', False),
    'partial': ('Records were read, then a request failed; or the budget ran out with nothing to continue from.',
                False),
}

FIXES = {
    'budget_resume': 'Run more: to continue; raise --max-requests if one invocation should read further.',
    'budget_restart': 'Rerun with a larger --max-requests.',
    'empty': 'Try another target, order or window; an explicitly empty result is not a failure to read.',
}

# Response-level issue → the coverage line it becomes.
ISSUES = {
    'unsupported_path_patch': 'part of a response could not be placed on any record; some records may lack fields',
    'graphql_errors': 'Facebook reported errors for part of a response; some records may lack fields',
    'cyclic_shared_story': 'a chain of shares looped back on itself and was cut there',
}

# The window line of a dated read: the first row that matches wins.
COVERAGE = (
    ('any order', 'any stop', 'a failure', 'open — <failure>'),
    ('ranked (feed top, group top or activity)', 'any stop', 'no failure', 'sample (ranked order)'),
    ('any order', 'limit_reached or budget', 'no failure', 'open — more: continues'),
    ('newest first (feed or group --sort recent)', 'window_reached or exhausted', 'no failure', 'closed (as served)'),
    ('filtered by Facebook (profile)', 'exhausted', 'no failure', 'closed (server-filtered)'),
)


def window_state(order, stop_reason, failure):
    """The coverage label of a date window (see COVERAGE)."""
    if failure is not None:
        return 'open — ' + failure.message.rstrip('.')
    if order == 'ranked':
        return 'sample (ranked order)'
    if stop_reason in ('limit_reached', 'budget'):
        return 'open — more: continues'
    if order == 'newest_first' and stop_reason in ('window_reached', 'exhausted'):
        return 'closed (as served)'
    if order == 'server' and stop_reason == 'exhausted':
        return 'closed (server-filtered)'
    return 'open'


def failure_envelope(error, command=None):
    """The envelope of an invocation that ended before any reading: always ok false, with error, message, fix."""
    kind = {2: 'argument', 3: 'aside', 4: 'login', 5: 'blocked', 7: 'empty', 8: 'partial'}.get(error.code, 'failed')
    envelope = {'ok': False}
    if command:
        envelope['command'] = command
    if kind != 'argument':
        envelope['stop_reason'] = {'blocked': 'blocked', 'partial': 'budget', 'empty': 'exhausted'}.get(kind, 'query_failure')
    envelope.update(error=kind, message=error.message, fix=error.fix, results=[])
    return kind, envelope


def finish(reading, *, command, requests, budget, identity=None, out=None):
    """(kind, envelope) of one reading.

    `reading` holds results, stop_reason (the natural stop when nothing failed), failure (FacebookError or None),
    coverage notes, issues, window ({order, since, until}), details for JSON, and continuable: whether a saved
    handle or committed --out pages let a later invocation continue.
    """
    records = reading.get('results') or []
    failure = reading.get('failure')
    stop_reason = reading.get('stop_reason') or 'exhausted'
    continuable = bool(reading.get('continuable'))
    if isinstance(failure, FacebookError):
        if failure.code == 5:
            kind, stop_reason = 'blocked', 'blocked'
        elif failure.code == 8:
            kind, stop_reason = ('resumable' if continuable else 'partial'), 'budget'
        elif failure.code == 4:
            kind, stop_reason = 'login', 'query_failure'
        elif failure.code == 2:
            kind, stop_reason = 'argument', 'query_failure'
        else:
            partial = bool(records) or bool(reading.get('partial'))
            kind = 'partial' if partial else ('aside' if failure.code == 3 else 'empty' if failure.code == 7 else 'failed')
            stop_reason = 'exhausted' if kind == 'empty' else 'query_failure'
    elif reading.get('already_complete'):
        kind = 'complete'
    elif command in ('doctor', 'schema'):
        kind = 'maintenance'
    elif records or (out is not None and reading.get('count')):
        kind = 'records'
    else:
        kind = 'empty'
    envelope = {'ok': KINDS[kind][1], 'command': command, **(identity or {}), 'stop_reason': stop_reason}
    if reading.get('window'):
        window = reading['window']
        envelope['window'] = {'since': window.get('since'), 'until': window.get('until'),
                              'coverage': window_state(window['order'], stop_reason,
                                                       failure if kind not in ('resumable', 'empty') else None)}
    if 'sponsored_skipped' in reading:
        envelope['sponsored_skipped'] = reading['sponsored_skipped']
    envelope['request_count'] = requests
    envelope['max_requests'] = budget
    if kind == 'empty':
        message = failure.message if isinstance(failure, FacebookError) else 'This query returned no results.'
        envelope.update(error='empty', message=message, fix=FIXES['empty'])
    elif kind == 'partial' and failure.code == 8:
        envelope.update(error='partial', message='The request budget ran out before anything was saved to continue '
                                                 'from.', fix=FIXES['budget_restart'])
    elif failure is not None and kind != 'resumable':
        envelope.update(error=kind, message=failure.message, fix=failure.fix)
    elif kind == 'resumable':
        envelope['fix'] = FIXES['budget_resume']
    coverage = list(dict.fromkeys(list(reading.get('coverage') or [])
                                  + [ISSUES.get(issue, issue) for issue in reading.get('issues') or []]))
    if coverage:
        envelope['coverage'] = coverage
    for key in ('next', 'detail'):
        if reading.get(key):
            envelope[key] = reading[key]
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
        'detail': 'Every detail path (post <url>, a detail: line, a replies handle) is a new live request; it does not '
                  'replay an earlier response, so what it shows can differ from what was shown before.',
    }


REQUESTS = ('request_count counts every network action this invocation started toward facebook.com: each GraphQL '
            'query, each page fetch, a retry, and every facebook.com request the browser tab made while the command '
            'ran (opening the dedicated tab, or moving it to another Facebook screen to load that screen\'s queries). '
            'Static files from fbcdn.net are not counted. An action that timed out is still counted. All invocations '
            'share one cross-process lock and pacing (1-2 s between requests) for the account.')

ENVELOPE = {
    'ok': 'boolean — false only for the kinds whose ok is false (see kinds)',
    'command': 'string — the command that ran',
    'sort, type': 'string — the order or vertical that makes this query what it is, when the command has one',
    'stop_reason': 'string — why reading stopped; see stop_reasons (absent for argument errors)',
    'window': 'object — dated reads only: {since, until, coverage}; coverage follows window_coverage',
    'sponsored_skipped': 'integer — feed only: advertisements left out of results and --limit',
    'request_count': 'integer — requests this invocation made (see requests)',
    'max_requests': 'integer — the budget it had',
    'error': 'string — the kind of failure (see kinds); absent on success',
    'message': 'string — what failed',
    'fix': 'string — what to do next; a resumable budget stop carries one too',
    'coverage': 'array<string> — what this result does not cover: unread parts, response issues',
    'next': 'string — the command that continues this reading; run it as it is (text prints it as more:)',
    'detail': 'string — the same page again with full text, when text was cut by --chars (text prints detail:)',
    'out': 'string — the --out file',
    'count': 'integer — records saved in the --out file so far',
    'already_complete': 'boolean — the --out file was complete before this run; nothing was read',
    'failed_sections': 'array<object> — about: collections that failed to load',
    'results': 'array<object> — post, comment, entity, about or group records (see schema <object>); doctor returns '
               'its checks, schema its documents',
}

TEXT = {
    'header': '<command>[ · sort=…][ · type=…] · <n> shown[ · sponsored_skipped=<n>] · stopped=<stop_reason> · '
              'requests=<used>/<budget>',
    'window': 'dated reads add a second line: window <since>..<until> · <coverage>',
    'records': '[p<n>] posts, [c<n>] comments and replies, [e<n>] people, pages and groups, then about fields; each '
               'record ends with the arguments of the next command: url (post), author (profile, about), '
               'replies <handle> (a comment\'s replies)',
    'text': 'text[N of M chars shown, complete|truncated]: N characters of the M received are shown (--chars); '
            'truncated means Facebook marked the received body itself as cut, so the rest is unknown even with '
            '--chars 0',
    'markers': {'?': 'a count Facebook did not send', 'unavailable': 'a name or URL that was not sent (no handle to '
                'follow there)', 'pinned': 'pinned to the top, so it can be old', 'undated': 'no creation time was '
                'sent', 'incomplete': 'a piece of this record could not be merged; fields may be missing',
                'sponsored': 'an advertisement', 'attachment=': 'what a comment carries besides text',
                'reply-to=cN': 'a reply to the comment labelled cN on this page', 'shared-from': 'the post this one '
                'shares, nested once per level', 'alt=': 'Facebook\'s automatic description of a photo; generated by '
                'Facebook and can be wrong'},
    'tail': 'coverage: <note> lines, then detail: <command> when --chars cut a comment, then more: <command> when '
            'reading can continue. With --out the whole result is one line: <command> · <n> saved to "<path>" · '
            'stopped=… · requests=… [· resume: <command>] [· error=<kind> fix=<fix>]',
}
