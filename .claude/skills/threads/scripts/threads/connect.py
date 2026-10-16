"""Shared wiring of the reading commands: a guarded connection, handles, --out files, the finished result, and the
idle blanker that empties the dedicated tab once nobody uses it."""
import os
import subprocess
import sys
import time
from pathlib import Path

from threads import guard as protection
from threads import handles
from threads.aside import Aside
from threads.collection import OutFile, peek
from threads.errors import ThreadsError
from threads.results import finish
from threads.session import Session
from threads.threads_web import Client

# 성진: 마지막 명령 뒤 약 5분 동안 쓰지 않으면 전용 탭을 비운다(T14) — 열린 탭은 31초마다 알림 배지, 5분마다 앱의 사용
# 시간 기록을 보낸다. 대화형 사용의 명령 간격이 실측으로 더 길거나 짧으면 조정한다
IDLE_SECONDS = 300
CLI = Path(__file__).resolve().parents[1] / 'cli.py'


class Connection:
    """One invocation's guarded connection: the client, its guard, and the Threads account in use.

    Built first and started second, so the requests a failed start already made are still reported.
    """

    def __init__(self, budget, verbose=False):
        self.guard = protection.Guard(budget)
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

    def release(self):
        """Give the tab back, and leave the idle blanker behind: it empties the tab after IDLE_SECONDS unless another
        command is still using it or was released after this one."""
        if not self.client.token or not self.client.tab:
            return
        self.memory.release(self.client.token)
        seconds = os.environ.get('THREADS_IDLE_SECONDS')
        if seconds == 'off':
            return  # a person who wants the tab left open
        delay = int(seconds) if seconds and seconds.isdigit() else IDLE_SECONDS
        try:
            subprocess.Popen([sys.executable, str(CLI), 'idle', '--token', self.client.token, '--after', str(delay)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=os.environ.copy())
        except OSError:
            pass  # without it the tab stays open until the next command or a person closes it


def idle(token, after):
    """Empty the dedicated tab after `after` seconds when the latest command is still the one that left `token`."""
    time.sleep(after)
    browser = Aside()
    memory = Session(browser.account_key)
    client = Client(browser, protection.Guard(1), memory)
    with memory.opening():
        memory.reload()
        if memory.active:
            return 'busy'  # a command still running uses the tab; its own release starts another blanker
        if memory.released != token or not memory.tab:
            return 'newer command'
        client.tab = memory.tab
        try:
            client.blank()
        except ThreadsError as error:
            return error.reason or 'failed'
    return 'blanked'


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
    except ThreadsError as error:
        reading = {**(reading or {}), 'failure': error}
        reading.setdefault('results', [])
    finally:
        if connection is not None:
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
        raise ThreadsError(2, 'The --out file belongs to another command, target, order or account.',
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
            stopped = isinstance(failure, ThreadsError) and failure.code in (4, 5, 9)
            if not stopped and (reading.get('stop_reason') == 'budget' or isinstance(failure, ThreadsError)):
                reading['next'] = words(command, target, reading.get('words', []), options, out=out_path)
    finally:
        if out is not None:
            out.close()
    _continue(reading, options, connection.account_id)
    return reading


def _continue(reading, options, account_id):
    continuation = reading.pop('continuation', None)
    failure = reading.get('failure')
    if not continuation or options.get('out') or (isinstance(failure, ThreadsError) and failure.code in (4, 5, 9)):
        return  # after a block, a logout or an unreadable target, a continuation would only invite another request
    context = _context(continuation['command'], continuation['target'], continuation['identity'], account_id)
    try:
        number = handles.save(context, continuation['state'])
    except ThreadsError as error:
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
