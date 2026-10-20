"""The shared wiring of every reading command: a guarded connection pinned to one Aside account, the platform account
check, handles, --out files, the finished result.

Flow of one command: settle an --out file from the file alone (a foreign or older file is refused, a final one is
repeated without a request); resolve the Aside account and open protection and the session; refuse a standing block;
start the platform's client; load the handle or open the --out file; run the platform's reader; save where to continue
and build more:; give the tab back (leaving the idle cleanup behind); finish the result. The lock order is session,
then protection.
"""
import os
import subprocess
import sys

from sns import handles, outfile, protection
from sns.aside import Aside
from sns.cmdline import command_line, words as command_words
from sns.errors import SnsError
from sns.paging import paginate
from sns.results import finish
from sns.session import Session
from sns.window import Window

# 성진: 마지막 명령 약 5분 뒤 전용 탭을 비우거나 닫는다(T14·C9) — 열린 탭의 앱이 스스로 폴링한다
IDLE_SECONDS = 300
VERDICTS = ('empty', 'partial', 'unavailable')                  # judgments a final --out file repeats


class Connection:
    """One invocation's connection for one platform: Aside (the account resolved first), protection, the session and
    the platform's client. Built first and started second, so the requests a failed start already made are reported."""

    def __init__(self, platform, invocation, account=None, deadline=None):
        self.platform, self.invocation = platform, invocation
        self.options = invocation.options
        self.deadline = deadline or invocation.deadline
        self.aside = Aside(platform.key, self.deadline, account=account)
        self.account = self.aside.account
        self.guard = protection.open(platform.key, self.account, platform.policy, self.deadline,
                                     title=platform.title, site=platform.site)
        self.session = Session(platform.key, self.account, self.deadline)
        self.client = platform.connect(self)
        self.started = False
        self._viewer = None
        self.observed = None   # the platform account a continued reading was read with

    @property
    def verbose(self):
        return self.invocation.verbose

    def start(self):
        """Refuse a standing block before the browser is touched, then start the client."""
        self.guard.check()
        self._viewer = self.client.start()
        self.started = True
        return self

    def viewer(self):
        """The platform account this invocation reads as: from the page (tab), or asked once (fetch, one request)."""
        if self._viewer is None:
            self._viewer = self.client.viewer()
        return self._viewer

    def seen(self, viewer):
        """A response showed the account the browser is logged in to: a different one than this invocation started
        with is a changed login (records of two accounts never mix in one result)."""
        if not viewer:
            return
        if self._viewer is None:
            self._viewer = viewer
        elif viewer != self._viewer:
            raise SnsError('login', f'The browser\'s {self.platform.title} account changed from {self._viewer} to '
                                    f'{viewer} during this command.', 'Run the command again to read as the current '
                                                                      'account.', reason='account_changed')

    def handle(self, command, state, target=None, identity=None):
        """Save a numbered handle another command continues from (a reply's branch, the next batch, hidden replies):
        bound to this platform, `command`, `target`, `identity` and the Aside account, and carrying the account it was
        read with. Returns the number to print (e.g. `replies <number>`)."""
        bound = context(self.platform, command, target, identity or {}, self.account)
        viewer = self.observed or self._viewer or self.viewer()
        return handles.save(bound, state, viewer=viewer, deadline=self.deadline)

    def resume(self, number, command, target=None, identity=None):
        """The state a handle saved for `command` (and target, identity); a handle of another command is an argument
        error naming where it belongs, one read as another account a changed login."""
        state, viewer = handles.load(number, context(self.platform, command, target, identity or {}, self.account))
        self.observed = viewer
        self.confirm(viewer)
        return state

    def confirm(self, saved):
        """A continued reading must be read as the account it was read with: a different one is a changed login."""
        if saved is None:
            return
        current = self.viewer()
        if current is not None and current != saved:
            raise SnsError('login', f'This reading was read as {saved}, but the browser is now logged in to '
                                    f'{self.platform.title} as {current}.',
                           'Run the original command again (without --after) to read as the current account.',
                           reason='account_changed')

    def empty_tab(self, tab):
        """Close or empty the dedicated tab so its app stops polling; makes no request. True once nothing polls."""
        return empty_tab(self.platform, self.aside, tab)

    @property
    def known_viewer(self):
        """The platform account if this invocation already knows it, without asking."""
        return self._viewer

    def report(self):
        client = self.client.report() or {}
        return {'requests': self.guard.count, 'setup': self.guard.setup + (client.get('setup') or 0),
                'unwatched': client.get('unwatched') or 0, 'session_reset': bool(client.get('session_reset')),
                'limits': self.guard.limits()}

    def release(self):
        """Give the tab back and leave the idle cleanup behind it."""
        token = self.client.release()
        if token:
            leave_idle(self.platform, self.invocation, self.account, token)


def stops_continuing(failure):
    """After a login wall, a person block (or unreadable protection state) or an unavailable target, a continuation
    would only invite another request; a stop that passes by itself (a hold, a scope limit, the time limit) does not."""
    return isinstance(failure, SnsError) and (failure.kind in ('login', 'unavailable') or (
        failure.kind == 'blocked' and failure.reason != 'rate_limited'))


def context(platform, command, target, identity, account):
    """What a handle or --out file is bound to (the platform account is kept beside it, not in it)."""
    return {'platform': platform.key, 'command': command, 'target': target, 'identity': identity,
            'aside_account': account}


def run(platform, invocation, *, command, target, identity, reader, window=None, bound=True, endless=False):
    """Run one reading command and finish it into (kind, envelope).

    reader(connection, state, out) returns a reading (see results.finish) and may set 'continuation' to
    {command, target, identity, words, state[, limit]}: what a later invocation needs to go on from here. bound: the
    reading can leave a handle or an --out file tied to the platform account (a fetch platform checks the account,
    one request). endless: the surface never ends by itself, so --out needs --limit.
    """
    options = invocation.options
    out_path = options.get('out')
    public = identity
    identity = with_window(identity, options)  # a different window is a different query for handles and files
    connection, reading = None, None
    try:
        if out_path:
            if endless and not options.get('limit'):
                raise SnsError('argument', 'This surface never ends by itself (a ranked or endless feed), so --out '
                                           'needs --limit to know when to stop.', 'Add --limit N.')
            outfile.check_path(out_path)
            reading = _settled(out_path, platform, command, target, identity)
        if reading is None:
            connection = Connection(platform, invocation)
            reading = _settled(out_path, platform, command, target, identity, connection.account) if out_path \
                else None
        if reading is None:
            connection.start()
            reading = _read(connection, command, target, identity, reader, out_path, bound)
    except SnsError as error:
        reading = {**(reading or {}), 'failure': error}
        reading.setdefault('results', [])
    finally:
        if connection is not None:
            try:
                connection.release()
            except SnsError:
                pass  # the tab stays until the next command or a person closes it
    if window is not None and 'window' not in reading:
        reading['window'] = window
    report = connection.report() if connection is not None else None
    return finish(reading, platform=platform.key, command=command, report=report, identity=_public(public),
                  out=str(outfile.resolve(out_path)) if out_path else None)


def with_window(identity, options):
    """The identity with the date window the options name."""
    window = {key: options[key] for key in ('since', 'until') if options.get(key)}
    return {**(identity or {}), **window} if window else identity


def window_words(words, options):
    """The words with --since/--until the options name and the words do not already carry."""
    words = list(words)
    for key in ('since', 'until'):
        if options.get(key) and f'--{key}' not in words:
            words += [f'--{key}', options[key]]
    return words


def _public(identity):
    return {key: value for key, value in (identity or {}).items() if value is not None}


def _settled(path, platform, command, target, identity, account=None):
    """A final --out file decided from the file alone: its result is repeated without a request. Before the Aside
    account is known only the query is compared; after, the account too."""
    peeked = outfile.peek(path)
    if peeked is None:
        return None
    saved = peeked['context']
    current = context(platform, command, target, identity, account)
    keys = [k for k in current if k != 'aside_account' or account is not None]
    if any(saved.get(k) != current[k] for k in keys):
        raise SnsError('argument', 'The --out file belongs to another command, target, order, window or account.',
                       'Use a new --out path, or rerun the command that started this file.')
    if not peeked['complete'] or account is None:
        return None
    conclusion = peeked['conclusion']
    reading = {'results': [], 'stop_reason': conclusion['stop_reason'], 'already_complete': True,
               'count': peeked['count']}
    verdict = conclusion['verdict']
    if verdict:
        reading['failure'] = SnsError(verdict['kind'], verdict['message'], verdict['fix'], reason=verdict.get('reason'))
    if conclusion['window']:
        reading['window'] = conclusion['window']
    return reading


def _read(connection, command, target, identity, reader, out_path, bound):
    options = connection.options
    platform = connection.platform
    bound_context = context(platform, command, target, identity, connection.account)
    state = None
    if options.get('after'):
        state, connection.observed = handles.load(options['after'], bound_context)
        connection.confirm(connection.observed)
    # A tab platform knows its account from the page; a fetch platform asks (one request) only for a reading that is
    # tied to the account: a collection, or one that can leave a handle (bound).
    viewer = connection.viewer() if (out_path or bound or platform.transport == 'tab') else None
    out = outfile.OutFile(out_path, bound_context, viewer=viewer) if out_path else None
    reading = None
    try:
        reading = reader(connection, state, out)
        _promote_sections(reading)
        if out is not None:
            _conclude(out, reading)
            reading['count'] = out.count
            reading['continuable'] = out.state is not None and not out.complete
            failure = reading.get('failure')
            stopped = out.complete or stops_continuing(failure)
            if not stopped:
                reading['next'] = command_line(connection.invocation.cli_path, command_words(
                    platform.key, command, target, window_words(reading.get('words', []), options), options,
                    out=out_path))
    finally:
        if out is not None:
            out.close()
    _continue(connection, reading)
    return reading


# Which failed section a composite command reports first: what says something about the account or the target, then
# what passes by itself, then the rest.
_SECTION_ORDER = ('person', 'login', 'unavailable', 'hold', 'scope_limit', 'aside', 'failed', 'partial', 'empty',
                  'argument')


def _section_rank(error):
    kind = error['kind']
    if kind == 'blocked':
        kind = 'hold' if error.get('reason') == 'rate_limited' else 'person'
    return _SECTION_ORDER.index(kind) if kind in _SECTION_ORDER else len(_SECTION_ORDER)


def _promote_sections(reading):
    """A composite command's failed sections become its failure (the worst one), so continuations, --out endings
    and the result kind treat them like any other; what the other sections read stays beside it."""
    sections = reading.get('sections')
    if not sections:
        return
    failed = [s['error'] for s in sections if not s.get('ok')]
    if not failed:
        return
    worst = min(failed, key=_section_rank)
    current = reading.get('failure')
    if isinstance(current, SnsError) and _section_rank({'kind': current.kind, 'reason': current.reason}) <= \
            _section_rank(worst):
        return  # the reading's own failure is at least as grave
    reading['failure'] = SnsError(worst['kind'], worst['message'], worst['fix'], reason=worst.get('reason'),
                                  **(worst.get('details') or {}))
    reading['partial'] = any(s.get('ok') and s.get('data') for s in sections)


def _conclude(out, reading):
    """At the end of a collection's run: a judgment rereading would not change makes the file final; anything else
    marks where it was interrupted."""
    failure = reading.get('failure')
    ending = reading.pop('ending', None)
    if out.complete:
        return
    if ending is None and out.state is None and out.count and failure is None:
        ending = reading.get('stop_reason') if reading.get('stop_reason') in outfile.COMPLETE else None
    if ending and failure is None and not out.count:
        failure = reading['failure'] = SnsError('empty', 'Nothing fell inside the requested range.',
                                                'Try another target, order or window.')
    if ending and failure is None:
        out.conclude(ending, None, reading.get('window'))
    elif ending and isinstance(failure, SnsError) and failure.kind in VERDICTS and failure.reason != 'time_limit':
        out.conclude(ending, {'kind': failure.kind, 'message': failure.message, 'fix': failure.fix,
                              'reason': failure.reason}, reading.get('window'))
    elif failure is not None or reading.get('stop_reason') not in outfile.COMPLETE:
        out.interrupt(failure.reason or failure.kind if isinstance(failure, SnsError) else reading.get('stop_reason'))


def _continue(connection, reading):
    continuation = reading.pop('continuation', None)
    failure = reading.get('failure')
    options = connection.options
    if not continuation or options.get('out') or stops_continuing(failure):
        return
    platform = connection.platform
    bound = context(platform, continuation['command'], continuation['target'],
                    with_window(continuation['identity'], options), connection.account)
    try:
        # a handle always carries the account it was read with (a fetch platform asks now if it has not yet)
        viewer = connection.observed or connection.known_viewer or connection.viewer()
        number = handles.save(bound, continuation['state'], viewer=viewer, deadline=connection.deadline)
    except SnsError as error:
        current = reading.get('failure')
        reading['failure'] = error if current is None else current
        return
    reading['continuable'] = True
    reading['next'] = command_line(connection.invocation.cli_path, command_words(
        platform.key, continuation['command'], continuation['target'], window_words(continuation['words'], options),
        options, after=number, limit=continuation.get('limit', ...)))


def read_list(connection, state, out, *, order, fetch, command, target, identity, words=(), extra=None, show=None,
              idle_limit=2, end_covers_window=False, notes=None):
    """Read a list surface page by page in the platform's order, as a reading for run().

    One page by default (a glance costs one request); `show` caps what that page shows when it is larger than a
    screen (the rest waits in the handle and more: shows it without a request). --limit reads on to N; --out commits
    whole pages to the end (or N). A window reads on only where it can close: a newest-first surface closes at --since,
    a server-filtered one ends by itself; a finite list or a ranked surface reads one page (or --limit) and its
    coverage says so. fetch(cursor) returns a page.Page. end_covers_window: the end of this newest-first surface is
    the account's oldest record, so reaching it covers the window; otherwise a listing that ends before --since did
    not cover it (partial). notes: labels for what pages left out ({'promoted': 'promoted entries (ads)'}).
    """
    options = connection.options
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(options.get('since'), options.get('until'), order=order, policy=connection.platform.window,
                    state=start.pop('window', None))
    for key in (extra or {}):
        start.pop(key, None)
    received = []

    def counted(cursor):
        page = fetch(cursor)
        received.append(len(page.records))
        return page

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**page_state, 'window': window.state(), **(extra or {})} if page_state else None, reason,
                   skipped, window.report())

    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
    limit = options.get('limit')
    if out is not None and limit is not None:
        if out.count >= limit:
            return {'results': [], 'stop_reason': 'limit_reached', 'words': list(words),
                    'window': window.describe() if window.active else None}
        limit -= out.count
    closes = window.closes if order == 'newest_first' and window.bounds['start'] is not None else None
    reads_on = out is not None or limit is not None or (window.active and order in ('newest_first', 'server'))
    if not reads_on and show is not None:
        limit = show
    result = paginate(counted, limit=limit, state=start, keep=window.keep, closes=closes,
                      commit=commit if out is not None else None, whole_pages=out is not None,
                      max_pages=None if reads_on else 1, idle_limit=idle_limit)
    stop, failure = result['stop_reason'], result['failure']
    if stop == 'exhausted' and order == 'newest_first' and window.bounds['start'] is not None \
            and not end_covers_window and failure is None:
        failure = SnsError('partial', f'The listing ended before the window\'s start: {connection.platform.title} had '
                                      'no older records to show here, so the window is not covered.',
                           'Use a later --since, or search with dates instead of reading the listing.',
                           reason='listing_ended')
    coverage = window.report()
    for label, count in sorted(result['left_out'].items()):
        coverage.append(f'{count} {(notes or {}).get(label, label)} left out')
    if result['reported_total'] is not None:
        coverage.append(f'{connection.platform.title} reports {result["reported_total"]} in total')
    if order in ('finite', 'ranked') and window.active and stop == 'limit_reached':
        coverage.append('this surface is not in date order: a window covers it only when read to the end')
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop, 'failure': failure,
               'coverage': coverage, 'words': list(words), 'partial': bool(result['results']),
               'reported_total': result['reported_total']}
    if window.active:
        reading['window'] = window.describe()
    if out is not None and stop in outfile.COMPLETE and (
            (result['state'] is None and failure is None) or (failure is not None and failure.reason == 'listing_ended')):
        reading['ending'] = stop  # only an end rereading would not change makes the file final
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity, 'words': list(words),
                                   'state': {**result['state'], 'window': window.state(), **(extra or {})}}
    return reading


def section(sections, name, produce, *, primary=False):
    """Run one section of a composite command; a failure in a secondary one is kept beside the others."""
    try:
        data = produce()
    except SnsError as error:
        if primary:
            raise
        sections.append({'name': name, 'ok': False, 'error': {'kind': error.kind, 'message': error.message,
                                                              'fix': error.fix, 'reason': error.reason,
                                                              'details': error.details}})
        return None
    sections.append({'name': name, 'ok': True, 'primary': primary, 'data': data})
    return data


def idle_seconds():
    value = os.environ.get('SNS_IDLE_SECONDS')
    if value == 'off':
        return None
    return int(value) if value and value.isdigit() else IDLE_SECONDS


def leave_idle(platform, invocation, account, token):
    """Start the idle cleanup in the background: it empties the tab after the idle delay unless another command is
    using it or was released after this one."""
    delay = idle_seconds()
    if delay is None:
        return  # a person who wants the tab left open
    try:
        subprocess.Popen([sys.executable, str(invocation.cli_path), platform.word, 'idle', '--account', account,
                          '--token', token, '--after', str(delay)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env=os.environ.copy())
    except OSError:
        pass  # without it the tab stays open until the next command or a person closes it


_EMPTY = {'close': '() => { window.close(); return true; } // sns-snippet: {platform}.close',
          'blank': '() => { location.replace("about:blank"); return true; } // sns-snippet: {platform}.blank'}


def empty_tab(platform, aside, tab):
    """Close the tab (or empty it to about:blank) the way the platform declares first, the other way when that does
    not take; True once the tab is gone or blank. Makes no request to the platform."""
    first = platform.idle_action or 'blank'
    for action in (first, 'blank' if first == 'close' else 'close', 'blank'):
        snippet = _EMPTY[action].replace('{platform}', platform.key)
        try:
            aside.evaluate(tab, snippet, {}, seconds=10)
        except SnsError as error:
            if error.reason == 'tab_missing':
                return True
        for _ in range(6):
            try:
                found = next((t for t in aside.tabs(seconds=10) if t['target_id'] == tab), None)
            except SnsError:
                break
            if found is None or found['url'] in ('about:blank', ''):
                return True
            aside.deadline.clock.sleep(0.3)
    return False
