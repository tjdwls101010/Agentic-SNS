"""Shared wiring of the reading commands: a guarded connection, handles, --out files, the finished result, and the
idle cleanup that closes (or empties) the dedicated tab once nobody uses it."""
import os
import subprocess
import sys
import time
from pathlib import Path

from twitter import guard as protection
from twitter import handles
from twitter.aside import Aside
from twitter.collection import OutFile, peek
from twitter.errors import TwitterError
from twitter.paging import paginate
from twitter.results import finish
from twitter.session import Session
from twitter.window import Window
from twitter.x_web import Client

# 성진: 마지막 명령 뒤 약 5분 동안 쓰지 않으면 전용 탭을 닫는다(T14) — 열린 탭은 앱 안 없는 화면에서도 분당 약 1번 배경
# 요청을 보낸다(정찰). 대화형 사용의 명령 간격이 실측으로 더 길거나 짧으면 조정한다
IDLE_SECONDS = 300
CLI = Path(__file__).resolve().parents[1] / 'cli.py'


class Connection:
    """One invocation's guarded connection: the client, its guard, and the X account in use.

    Built first and started second, so the requests a failed start already made are still reported.
    """

    def __init__(self, budget, verbose=False):
        seconds = os.environ.get('TWITTER_DEADLINE_SECONDS')  # tests shorten the command's deadline
        self.guard = protection.Guard(budget, deadline_seconds=float(seconds) if seconds else None)
        browser = Aside()
        self.memory = Session(browser.account_key)
        self.client = Client(browser, self.guard, self.memory, verbose)
        self.account_id = None

    def start(self):
        self.guard.check()  # a saved block stops the invocation before the browser is touched
        self.account_id = self.client.start()
        return self

    def report(self):
        """What finish() needs to know about the requests and the session."""
        return {'requests': self.guard.count, 'setup': self.guard.setup, 'unwatched': self.client.unwatched,
                'session_reset': self.client.session_reset}

    def note_nonce(self):
        """Keep, per Aside account, whether the skill's own requests were told apart by their nonce (doctor)."""
        self.memory.note_nonce(self.client.nonce['sent'], self.client.nonce['matched'])

    def release(self):
        """Give the tab back, and leave the idle cleanup behind: it closes the tab after IDLE_SECONDS unless another
        command is still using it or was released after this one."""
        if not self.client.tab:
            return
        if self.client.token:
            self.memory.release(self.client.token)
        elif not self.memory.reload().dirty:
            return  # the command never used the tab, and nothing is left to empty
        seconds = os.environ.get('TWITTER_IDLE_SECONDS')
        if seconds == 'off':
            return  # a person who wants the tab left open
        delay = int(seconds) if seconds and seconds.isdigit() else IDLE_SECONDS
        try:
            subprocess.Popen([sys.executable, str(CLI), 'idle', '--token', self.client.token or '-', '--after', str(delay)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=os.environ.copy())
        except OSError:
            pass  # without it the tab stays open until the next command or a person closes it


# 성진: 바쁜 탭은 IDLE_SECONDS 간격으로 12번까지 다시 본다 — 그보다 오래 도는 명령은 끝날 때 자기 정리를 남긴다
BUSY_CHECKS = 12


def idle(token, after):
    """Close the dedicated tab after `after` seconds when no command is using it and the last one released was the
    one that left `token` (`any`: whichever did, for a job that stopped a command), or when an earlier attempt to empty
    it failed. While a command still runs, it waits and looks again, so a command that dies without releasing does not
    leave the tab polling."""
    browser = Aside()
    memory = Session(browser.account_key)
    client = Client(browser, protection.Guard(1), memory)
    for _ in range(BUSY_CHECKS):
        time.sleep(max(after, 1) if _ else after)
        with memory.opening():
            memory.reload()
            if memory.active:
                continue  # a command still running uses the tab
            if not memory.tab or (token not in ('any', memory.released) and not memory.dirty):
                return 'newer command'
            client.tab = memory.tab
            try:
                return 'closed' if client.release_tab() else 'not closed'
            except TwitterError as error:
                return error.reason or 'failed'
    return 'busy'


def run(options, *, command, target, identity, reader, window=None):
    """Run one reading command and finish it into (kind, envelope).

    reader(connection, state, out) returns a reading (see results.finish) and may set 'continuation' to
    {command, target, identity, words, state}: what a later invocation needs to go on from here.
    """
    connection, reading = None, None
    out_path = options.get('out')
    try:
        if out_path:
            reading = _settled_file(out_path, _context(command, target, identity, None))
        if reading is None:
            connection = Connection(options['max_requests'], options.get('verbose'))
            connection.start()
            reading = _read(connection, options, command, target, identity, reader, out_path)
    except TwitterError as error:
        reading = {**(reading or {}), 'failure': error}
        reading.setdefault('results', [])
    finally:
        if connection is not None:
            connection.note_nonce()
            connection.release()
    if window:
        reading['window'] = window
    report = connection.report() if connection else {'requests': 0, 'setup': 0, 'unwatched': 0, 'session_reset': False}
    return finish(reading, command=command, budget=options['max_requests'], identity=_public(identity), out=out_path,
                  **report)


def _settled_file(path, context):
    """Decide a --out file from the file alone, before the browser: a foreign or older file is refused, a complete one
    reads nothing. Returns the reading of a complete file, else None (read on)."""
    saved, complete, count = peek(path)
    if saved is None:
        return None
    if {k: v for k, v in saved.items() if k != 'account_id'} != {k: v for k, v in context.items() if k != 'account_id'}:
        raise TwitterError(2, 'The --out file belongs to another command, target, order or account.',
                           'Use a new --out path, or rerun the command that started this file.')
    if complete:
        return {'results': [], 'stop_reason': 'exhausted', 'already_complete': True, 'count': count}
    return None


def _read(connection, options, command, target, identity, reader, out_path):
    context = _context(command, target, identity, connection.account_id)
    state = handles.load(options['after'], context) if options.get('after') else None
    out = OutFile(out_path, context) if out_path else None
    reading = None
    try:
        if out is not None and out.complete:
            reading = {'results': [], 'stop_reason': 'exhausted', 'already_complete': True}
        else:
            reading = reader(connection, state, out)
        if out is not None:
            reading['count'] = out.count
            reading['continuable'] = out.state is not None and not out.complete
            failure = reading.get('failure')
            stopped = isinstance(failure, TwitterError) and failure.code in (4, 5, 9)
            if not stopped and (reading.get('stop_reason') == 'budget' or isinstance(failure, TwitterError)):
                reading['next'] = words(command, target, reading.get('words', []), options, out=out_path)
    finally:
        if out is not None:
            out.close()
    _continue(reading, options, connection.account_id)
    return reading


def _continue(reading, options, account_id):
    continuation = reading.pop('continuation', None)
    failure = reading.get('failure')
    if not continuation or options.get('out') or (isinstance(failure, TwitterError) and failure.code in (4, 5, 9)):
        return  # after a block, a logout or an unreadable target, a continuation would only invite another request
    context = _context(continuation['command'], continuation['target'], continuation['identity'], account_id)
    try:
        number = handles.save(context, continuation['state'])
    except TwitterError as error:
        current = reading.get('failure')
        reading['failure'] = error if current is None or current.code == 8 else current
        return
    reading['continuable'] = True
    reading['next'] = words(continuation['command'], continuation['target'], continuation['words'], options,
                            after=number, limit=continuation.get('limit', ...))


def words(command, target, identity_words, options, *, after=None, out=None, limit=..., chars=None):
    """The argument words that rerun or continue a command: target last after `--` when it looks like an option."""
    result = [command]
    tail = []
    if target is not None:
        if str(target).startswith('-'):
            tail = ['--', str(target)]
        else:
            result.append(str(target))
    result += identity_words
    limit = options.get('limit') if limit is ... else limit  # an explicit None drops --limit
    if limit is not None:
        result += ['--limit', str(limit)]
    chars = options.get('chars') if chars is None else chars
    if chars is not None:
        result += ['--chars', str(chars)]
    if after is not None:
        result += ['--after', str(after)]
    if out is not None:
        result.append('--out=' + out)
    if options.get('json'):
        result.append('--json')
    if options.get('max_requests') not in (None, 25):
        result += ['--max-requests', str(options['max_requests'])]
    return result + tail


def _context(command, target, identity, account_id):
    return {'command': command, 'target': target, **identity, 'account_id': account_id}


def _public(identity):
    """The identity options a result names in its header."""
    return {key: value for key, value in identity.items()
            if key in ('sort', 'feed', 'tab', 'type', 'relation', 'collection') and value is not None}


def read_list(options, identity, state, out, *, order, fetch, command, target, extra=None, words=None, stops=False,
              idle_limit=2):
    """Read a list surface by cursor in the server's order with its date-window policy: one page by default (a
    glance costs one request), --limit or a window reads on, --out commits whole pages; the reading carries a
    continuation for the next handle. fetch(cursor) returns a page with records, cursor, has_next, promoted, other."""
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(options.get('since'), options.get('until'), order, start.pop('window', None))
    for key in (extra or {}):
        start.pop(key, None)
    natural = start.pop('natural', None) or {}
    skipped = {'promoted': 0, 'other': 0}

    def fetch_page(cursor):
        page = fetch(cursor)
        skipped['promoted'] += page.promoted
        skipped['other'] += page.other
        if getattr(page, 'stop', None):
            natural['stop'] = page.stop
        return page.records, {'has_next_page': page.has_next, 'end_cursor': page.cursor}, bool(page.records)

    def commit(records, page_state, reason, page_skipped):
        out.commit(records, {**page_state, 'window': window.state(), 'natural': dict(natural), **(extra or {})}
                   if page_state else None, reason, page_skipped, window.report())

    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
    limit = options.get('limit')
    if out is not None and limit is not None:
        if out.count >= limit:
            return {'results': [], 'stop_reason': 'limit_reached', 'words': list_words(identity)}
        limit -= out.count
    closes = window.closes if order == 'newest_first' and window.since else None
    # Without --limit, a window or --out, one page is read: a glance at a list costs one request, not the budget.
    one_page = limit is None and out is None and not window.active
    result = paginate(fetch_page, limit=limit, state=start, keep=window.keep, closes=closes,
                      commit=commit if out is not None else None, whole_pages=out is not None,
                      max_pages=1 if one_page else None, idle_limit=idle_limit)
    stop = result['stop_reason']
    if stops and stop == 'exhausted' and natural.get('stop') == 'not_paginable':
        stop = 'not_paginable'
    coverage = window.report()
    if skipped['promoted']:
        coverage.append(f'{skipped["promoted"]} promoted posts (ads) left out')
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop,
               'failure': result['failure'], 'coverage': coverage, 'words': list_words(identity, words),
               'partial': bool(result['results'])}
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity,
                                   'words': list_words(identity, words),
                                   'state': {**result['state'], 'window': window.state(), 'natural': dict(natural),
                                             **(extra or {})}}
    return reading


def list_words(identity, positional=None):
    words = list(positional or [])
    for key in ('feed', 'tab', 'sort'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    for key in ('since', 'until'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    return words


def window_of(options, order):
    if not (options.get('since') or options.get('until')):
        return None
    return {'order': order, 'since': options.get('since'), 'until': options.get('until')}
