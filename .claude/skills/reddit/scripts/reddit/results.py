"""The result vocabulary, and the one place a reading becomes the public result.

A feature reports what happened (records, why it stopped, a failure, coverage notes); `finish` decides the result
kind, the public stop reason and the fix. Exit numbers belong to cli.py, which maps each kind to one.
"""
from reddit.errors import RedditError

# stop_reason → (what it means, what to do next)
STOP_REASONS = {
    'limit_reached': ('The requested number of records was shown.', 'Run more: if you need more.'),
    'exhausted': ('Nothing more to read in the requested range: the listing or thread ended, or the command reads one '
                  'thing.', 'Nothing.'),
    'window_reached': ('A newest-first read passed --since; everything up to that boundary was delivered.', 'Nothing.'),
    'budget': ('--max-requests was spent.', 'Run more: (or rerun the same --out command); raise --max-requests if one '
                                           'invocation should read further.'),
    'window_spent': ('Reddit\'s request window for this account is used up (the bucket the next request needs has no '
                     'requests left until it resets); nothing more was sent.',
                     'Run more: (or rerun the same --out command) after the reset the result names.'),
    'probe_pending': ('Another invocation is making the first request of a new Reddit window; this one did not send to '
                      'the same bucket meanwhile.', 'Run more: (or rerun) a few seconds later.'),
    'stalled': ('A comment thread has gaps that could not be expanded (Reddit answered the same branch with nothing '
                'new); the rest was read.', 'Nothing more can be read there; the coverage line counts what is left.'),
    'blocked': ('Reddit answered with a rate limit or a browser challenge, or a saved block is still active.',
                'Stop. For a challenge, after a person checks Reddit in the Aside browser, run doctor --unblock; a rate '
                'limit expires by itself.'),
    'query_failure': ('A request failed; error, message and fix say why.', 'Follow fix.'),
    'ready': ('doctor: Aside, login and account protection are usable.', 'Nothing.'),
    'complete': ('schema finished.', 'Nothing.'),
}

# Result kind → (situation, ok)
KINDS = {
    'records': ('At least one record and no failure.', True),
    'resumable': ('--max-requests or Reddit\'s request window ran out where reading can continue; more: or the same '
                  '--out command resumes.', True),
    'complete': ('The --out file was already complete; nothing was read.', True),
    'maintenance': ('doctor or schema succeeded.', True),
    'argument': ('Arguments, a handle or an output file were rejected before any request.', False),
    'aside': ('Aside was unavailable, timed out, answered invalidly, or the Aside account could not be told.', False),
    'login': ('Reddit login is required in the Aside browser, or it is logged in to another Reddit account than the '
              'one a continuation was made with.', False),
    'blocked': ('A browser challenge or rate limit, now or saved from an earlier invocation; or unreadable protection '
                'state.', False),
    'unavailable': ('The target cannot be read by this account: missing, private, quarantined, banned, suspended, a '
                    'wiki that is off, or a profile whose history is not visible. Retrying does not change it.', False),
    'failed': ('A request failed before any record was read (including a response shape this skill does not know, or '
               'Reddit not reporting its request limit).', False),
    'empty': ('Reddit explicitly returned nothing, or nothing fell inside the window.', False),
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
    ('any', 'a failure', 'open — <failure>'),
    ('limit_reached, budget, window_spent or probe_pending', 'no failure', 'open — more: continues'),
    ('window_reached (sort new passed --since)', 'no failure', 'closed (as served)'),
    ('exhausted', 'no failure', 'closed (read to the end)'),
)
_RESUMABLE = ('budget', 'window_spent', 'probe_pending')


def window_state(stop_reason, failure):
    """The coverage label of a date window (see COVERAGE)."""
    if failure is not None:
        return 'open — ' + failure.message.rstrip('.')
    if stop_reason in ('limit_reached', *_RESUMABLE):
        return 'open — more: continues'
    if stop_reason == 'window_reached':
        return 'closed (as served)'
    if stop_reason == 'exhausted':
        return 'closed (read to the end)'
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


def _stop_of(error):
    """The stop reason of a resumable stop (code 8): which limit ended it."""
    return error.reason if error.reason in _RESUMABLE else 'budget'


def failure_envelope(error, command=None):
    """The envelope of an invocation that ended before any reading: always ok false, with error, message, fix."""
    kind = _failure_kind(error, False)
    envelope = {'ok': False}
    if command:
        envelope['command'] = command
    if kind != 'argument':
        envelope['stop_reason'] = {'blocked': 'blocked', 'partial': _stop_of(error), 'empty': 'exhausted'}.get(
            kind, 'query_failure')
    envelope.update(error=kind, message=error.message, fix=error.fix)
    if error.reason:
        envelope['reason'] = error.reason
    envelope['results'] = []
    return kind, envelope


def finish(reading, *, command, requests, budget, identity=None, out=None, reddit=None, account=None):
    """(kind, envelope) of one reading.

    `reading` holds results, stop_reason (the natural stop when nothing failed), failure (RedditError or None),
    coverage notes, window (Window.describe()), thread coverage, details for JSON, and continuable: whether a saved
    handle or committed --out pages let a later invocation continue. reddit is the bucket state the last response
    reported; account says which Reddit account observed the records and whether it was checked now.
    """
    records = reading.get('results') or []
    failure = reading.get('failure')
    stop_reason = reading.get('stop_reason') or 'exhausted'
    continuable = bool(reading.get('continuable'))
    if isinstance(failure, RedditError):
        if failure.code == 8:
            kind, stop_reason = ('resumable' if continuable else 'partial'), _stop_of(failure)
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
        envelope['window'] = {**reading['window'],
                              'coverage': window_state(stop_reason, failure if kind not in ('resumable', 'empty')
                                                       else None)}
    envelope['request_count'] = requests
    envelope['max_requests'] = budget
    if reddit:
        envelope['reddit_window'] = reddit
    if account:
        envelope['account'] = account
    if kind == 'empty':
        message = failure.message if isinstance(failure, RedditError) else 'This query returned no results.'
        envelope.update(error='empty', message=message, fix=failure.fix if isinstance(failure, RedditError)
                        and failure.code == 7 else FIXES['empty'])
    elif kind == 'partial' and failure.code == 8:
        message = ('The request budget ran out before anything was saved to continue from.'
                   if failure.reason in (None, 'budget') else failure.message)
        envelope.update(error='partial', message=message, fix=FIXES['budget_restart'] if failure.reason in
                        (None, 'budget') else failure.fix)
    elif failure is not None and kind != 'resumable':
        envelope.update(error=kind, message=failure.message, fix=failure.fix)
    elif kind == 'resumable':
        envelope['message'] = failure.message
        envelope['fix'] = FIXES['budget_resume'] if stop_reason == 'budget' else failure.fix
    if isinstance(failure, RedditError) and failure.reason and kind != 'resumable':
        envelope['reason'] = failure.reason
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
        'description': 'The JSON envelope a command prints with --json (doctor and schema always print one), and the '
                       'text page built from it.',
        'fields': ENVELOPE,
        'stop_reasons': {reason: f'{meaning} Next: {action}' for reason, (meaning, action) in STOP_REASONS.items()},
        'kinds': {kind: situation for kind, (situation, _) in KINDS.items()},
        'exit_codes': [{'exit': code, 'meaning': meaning, 'kinds': list(kinds)} for code, meaning, kinds in exit_codes],
        'window_coverage': [{'stopped': stopped, 'failure': failure, 'window': label}
                            for stopped, failure, label in COVERAGE],
        'requests': REQUESTS,
        'text': TEXT,
        'detail': 'Every record carries the URL that names it alone: post <url> opens a post in full, comments '
                  '<comment url> opens one comment in full with what hangs under it, profile and about take u/ and r/ '
                  'names. These read live; they do not replay an earlier response.',
    }


REQUESTS = ('request_count counts what this invocation sent to Reddit: each page, post, expansion, redirect and '
            'share-link hop, and the account check (/api/me.json) a command makes before it starts or continues a '
            'reading bound to the account. Reddit counts .json requests in its own buckets per ten minutes (wiki pages '
            'in one, everything else in another) and reports what is left in each answer: reddit_window repeats the '
            'last answer\'s numbers, and a bucket with nothing left stops the command (stopped=window_spent) instead of '
            'sending. Requests are paced 1-2 s apart across every invocation of the account, slower when Reddit\'s '
            'bucket runs low (seconds to the reset divided by what is left), so a large read takes minutes.')

ENVELOPE = {
    'ok': 'boolean — false only for the kinds whose ok is false (see kinds)',
    'command': 'string — the command that ran',
    'sort, time, type, collection': 'string — the order, period or surface that makes this query what it is',
    'stop_reason': 'string — why reading stopped; see stop_reasons (absent for argument errors)',
    'window': 'object — dated reads only: {since, until, tz, start_utc, end_utc, coverage}; the local days, the time '
              'zone they were judged in when the reading started, the exact UTC bounds, and coverage per '
              'window_coverage',
    'request_count': 'integer — requests this invocation made (see requests)',
    'max_requests': 'integer — the budget it had',
    'reddit_window': 'object — {bucket: {remaining, limit, resets_in}} as Reddit\'s last answer reported each bucket '
                     'this invocation used',
    'account': 'object — {observed: the Reddit account the records were read with, checked: whether this invocation '
               'confirmed the browser is logged in to it now}',
    'error': 'string — the kind of failure (see kinds); absent on success',
    'reason': 'string — a finer cause when there is one (e.g. rate_limit, challenge, history_not_visible, private)',
    'message': 'string — what failed or why reading stopped',
    'fix': 'string — what to do next; a resumable stop carries one too',
    'coverage': 'array<string> — what this result does not cover: unread parts, unexpanded comments, undated records',
    'thread': 'object — post and comments: the comment tree coverage (see the text page\'s coverage line)',
    'next': 'string — the command that continues this reading; run it as it is (text prints it as more:)',
    'out': 'string — the --out file (the resolved path when the given path went through a symbolic link)',
    'count': 'integer — records saved in the --out file so far',
    'already_complete': 'boolean — the --out file was complete before this run; nothing was read',
    'results': 'array<object> — post, comment, subreddit, user or wiki records (see schema <object>); doctor returns '
               'its checks, schema its documents',
}

TEXT = {
    'header': '<command>[ · sort=…][ · time=…][ · type=…] · <n> shown · stopped=<stop_reason> · '
              'requests=<used>/<budget> · reddit window <remaining>/<limit>, resets in <s>s',
    'window': 'dated reads add a line: window <since>..<until> <tz> · <coverage>',
    'records': '[p<n>] posts, [c<n>] comments, [s<n>] communities, [u<n>] users, [w<n>] wiki pages; each record ends '
               'with the URL that names it alone',
    'text': 'text[N of M chars shown]: N characters of the M received are shown (--chars); --chars 0 shows everything',
    'markers': {'OP': 'written by the post\'s author', 'mod': 'written as a moderator', 'admin': 'written as a Reddit '
                'admin', 'pinned': 'pinned by moderators (or by the author on a profile); can be old',
                'collapsed': 'Reddit folds it by default', 'low score': 'below the community\'s score threshold',
                'controversial': 'many votes both ways', 'edited': 'changed after posting', 'removed': 'removed by '
                'moderators or Reddit (the text is gone)', 'deleted': 'deleted by its author', 'score hidden': 'the '
                'community hides new comments\' scores for a while', 'flair="…"': 'what the author or post says about '
                'itself in that community', '❝…❞': 'words quoted from someone else (a > quote), not the author\'s own',
                'nsfw': 'marked over 18 (shown, never filtered)', 'archived': 'too old for new comments or votes',
                'locked': 'no new comments'},
    'tail': 'coverage: <note> lines, then more: <command> when reading can continue. With --out the whole result is '
            'one line: <command> · <n> saved to "<path>" · stopped=… · requests=… [· resume: <command>] '
            '[· error=<kind> fix=<fix>]',
}
