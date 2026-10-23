"""The Aside CLI: which Aside account an invocation uses, and bounded `aside` processes whose output is read back into
one JSON value through one protocol (program.js).

Every call is clamped to the invocation's deadline. A call cut short by that clamp is the time limit (the command ends
and can resume), not an Aside failure; a call that times out with time to spare, or loses its connection, is.

Two ways to open a dedicated tab are kept because each was verified for its platform: `open(url)` (`aside <url>`,
Threads and Facebook) and `opener()` + `load()` (X: a held session opens about:blank, the tab is recorded and attached
by a second call before the opener ends, so Aside does not close it, and the page is loaded with the observer already
installed). Tab-less reads (Reddit, Naver) `run` a function in the REPL itself, which fetches with the browser's
cookies. Nothing here uses `aside exec` (the browser agent).
"""
import base64
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from sns.errors import SnsError

PROGRAM = (Path(__file__).with_name('program.js')).read_text(encoding='utf-8')
MEDIA = (Path(__file__).with_name('media.js')).read_text(encoding='utf-8')
REPL_SECONDS = 120          # aside repl's own limit
OPEN_SECONDS = 30           # opening a tab, and the opener's first answer
STATUS_SECONDS = 15         # `aside account status`
_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
_CHECK = 'Check that Aside is running, then run doctor.'
# One line: the interactive REPL runs each line on its own. The leading string names it for the test stand-in.
# openTab answers with the page it opened, target id included (measured 2026-10-21): a before/after diff of the tab
# list would also catch a tab another command opened meanwhile.
_OPENER = ("'sns-opener'; const opened = await openTab('about:blank'); "
           "console.log(JSON.stringify({kind: 'opened', tabs: [opened && opened.targetId]}));\n")


def active_account(stdout):
    """The id on the one line `aside account status` marks with *, else None."""
    marked = []
    for raw in stdout.splitlines():
        line = _ANSI.sub('', raw).strip()
        if line.startswith('*'):
            words = line[1:].split()
            if words and _ID.fullmatch(words[0]):
                marked.append(words[0])
    return marked[0] if len(marked) == 1 else None


def time_limit():
    return SnsError('failed', 'The command reached its time limit during a browser call; its request may have been '
                              'made.', 'Run the command again (or its more: line); nothing is wrong with the account.',
                    reason='time_limit')


class Aside:
    """The Aside CLI for one platform's invocation, pinned to one Aside account.

    The account is SNS_ASIDE_ACCOUNT_<PLATFORM>, else SNS_ASIDE_ACCOUNT, else the one `aside account status` marks
    active — resolved once per invocation, before any request, so that a person switching Aside accounts is seen by
    the next command and the default account and the same id named explicitly share one state.
    """

    def __init__(self, platform, deadline, account=None):
        self.platform, self.deadline = platform, deadline
        self.binary = os.environ.get('SNS_ASIDE_BIN') or shutil.which('aside')
        if not self.binary:
            raise SnsError('aside', 'Aside is unavailable: its CLI is not on PATH.',
                           'Install or start Aside so the `aside` command works, then run doctor.')
        self.account = account if account and _ID.fullmatch(account) else self._account()

    def _account(self):
        for name in (f'SNS_ASIDE_ACCOUNT_{self.platform.upper()}', 'SNS_ASIDE_ACCOUNT'):
            named = os.environ.get(name)
            if named:
                if not _ID.fullmatch(named):
                    raise SnsError('argument', f'{name} is not an Aside account id (such as u0).',
                                   'Set it to an id `aside account list` shows, or unset it.')
                return named
        limit, clamped = self._limit(None, STATUS_SECONDS)
        try:
            done = subprocess.run([self.binary, 'account', 'status'], capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            if clamped:
                raise time_limit() from None
            raise SnsError('aside', 'Aside did not say which account is active in time.', _CHECK) from None
        except (OSError, UnicodeError):
            raise SnsError('aside', 'Aside could not run.', _CHECK) from None
        account = active_account(done.stdout) if done.returncode == 0 else None
        if account is None:
            raise SnsError('aside', 'Could not tell which Aside account to use.',
                           'Set SNS_ASIDE_ACCOUNT to the Aside account id (such as u0), or check '
                           '`aside account status`.')
        return account

    def _command(self, *args):
        return [self.binary, '--account', self.account, *args]

    def _limit(self, seconds, natural):
        """The seconds a call may take: its own cap, the caller's, and the deadline; and whether the deadline set it."""
        wanted = natural if seconds is None else min(natural, seconds)
        left = self.deadline.left()
        if left <= 0:
            raise time_limit()
        return max(0.05, min(wanted, left)), left < wanted

    # --- calls ---------------------------------------------------------------------------------------------------

    def tabs(self, seconds=None):
        """Open browser tabs as [{target_id, url}]; listing touches no web page."""
        listed = self._repl({'op': 'tabs'}, None, {}, seconds)
        if not isinstance(listed, list):
            raise SnsError('aside', 'Aside returned an invalid tab list.', _CHECK)
        return [{'target_id': t.get('targetId'), 'url': t.get('url') or ''} for t in listed
                if isinstance(t, dict) and isinstance(t.get('targetId'), str)]

    def evaluate(self, target_id, function, args, seconds=None):
        """Run a page function in the tab `target_id` with `args`; returns what it returned. A tab that no longer
        exists raises with reason 'tab_missing'."""
        return self._repl({'op': 'evaluate', 'tab': target_id}, function, args, seconds)

    def load(self, target_id, url, function, args, seconds=None):
        """Send the tab to `url` without a history entry, then run `function` until it answers (not null)."""
        wait = max(1, int(min(20, (seconds or 25) - 3, self.deadline.left() - 3)))
        return self._repl({'op': 'load', 'tab': target_id, 'url': url, 'seconds': wait}, function, args, seconds)

    def run(self, function, args, seconds=None):
        """Call `function` (an async function expression) with `args` in the REPL itself, without a tab; returns what
        it returned. For fetches that need only the browser's cookies."""
        return self._repl({'op': 'run'}, function, args, seconds)

    def download(self, url, max_bytes, seconds=60):
        """(bytes, content type) of one picture the browser fetches without cookies; a picture over max_bytes, an
        answer that is not 200 or one that is not a picture is a partial failure naming why (reason too_large,
        status_<n>, not_image, redirect, network)."""
        answer = self.run(MEDIA, {'url': url, 'max': max_bytes}, seconds)
        if not isinstance(answer, dict) or type(answer.get('status')) is not int:
            raise SnsError('aside', 'Aside returned a picture answer this skill cannot read.', _CHECK, reason='invalid')
        if answer.get('redirect'):
            raise SnsError('partial', 'the image host redirected it elsewhere, so it was not fetched',
                           'Read the post again; a signed link may have expired.', reason='redirect')
        if answer.get('network'):
            raise SnsError('partial', f'the image host could not be reached ({answer["network"]})',
                           'Run the command again later.', reason='network')
        if answer.get('too_large'):
            raise SnsError('partial', f'it is larger than {max_bytes // (1024 * 1024)} MB', 'Open it in the browser.',
                           reason='too_large')
        if answer['status'] != 200:
            raise SnsError('partial', f'the image host answered {answer["status"]}', 'Read the post again; a signed '
                                                                                      'link may have expired.',
                           reason=f'status_{answer["status"]}')
        if not str(answer.get('type') or '').startswith('image/') or not isinstance(answer.get('data'), str):
            raise SnsError('partial', 'the answer was not a picture', 'Open it in the browser.', reason='not_image')
        try:
            return base64.b64decode(answer['data'], validate=True), answer['type']
        except ValueError:
            raise SnsError('aside', 'Aside returned picture bytes this skill cannot read.', _CHECK,
                           reason='invalid') from None

    def open(self, url, seconds=None):
        """Open `url` in a new persistent tab (`aside <url>`) and wait for Aside to finish opening it."""
        limit, clamped = self._limit(seconds, OPEN_SECONDS)
        try:
            result = subprocess.run(self._command(url), capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            if clamped:
                raise time_limit() from None
            raise SnsError('aside', 'Aside did not finish opening the tab in time.', _CHECK, reason='timeout') from None
        except (OSError, UnicodeError):
            raise SnsError('aside', 'Aside could not run.', _CHECK) from None
        if result.returncode:
            raise SnsError('aside', 'Aside could not open the tab.', _CHECK, reason='failed')

    @contextmanager
    def opener(self, seconds=None):
        """Open a new about:blank tab in a held session and yield its target id; the session ends when the block does.
        The caller records the tab and attaches it from another call before leaving the block."""
        limit, clamped = self._limit(seconds, OPEN_SECONDS)
        try:
            process = subprocess.Popen(self._command('repl'), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1)
        except (OSError, UnicodeError):
            raise SnsError('aside', 'Aside could not run.', _CHECK) from None
        try:
            try:
                process.stdin.write(_OPENER)
                process.stdin.flush()
            except OSError:
                raise SnsError('aside', 'Aside did not accept the tab opener.', _CHECK) from None
            found = self._opened(process, time.monotonic() + limit, clamped)
            if not isinstance(found, list) or len(found) != 1 or not isinstance(found[0], str):
                raise SnsError('aside', 'Aside opened no tab this skill can tell apart from the others.', _CHECK)
            yield found[0]
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=max(0.5, min(10, self.deadline.left())))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)  # killed: it ends at once

    @staticmethod
    def _opened(process, until, clamped):
        """The new tab ids the opener printed, read from its raw output until its answer or `until`."""
        descriptor = process.stdout.fileno()
        selector = selectors.DefaultSelector()
        selector.register(descriptor, selectors.EVENT_READ)
        pending = b''
        try:
            while time.monotonic() < until:
                if not selector.select(timeout=max(0.0, until - time.monotonic())):
                    break
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                pending += chunk
                *lines, pending = pending.split(b'\n')
                for raw in lines:
                    line = _ANSI.sub('', raw.decode('utf-8', 'replace')).strip()
                    start = line.find('{"kind"')
                    if start < 0:
                        continue
                    try:
                        value = json.loads(line[start:])
                    except ValueError:
                        continue
                    if isinstance(value, dict) and value.get('kind') == 'opened':
                        return value.get('tabs')
        finally:
            selector.close()
        if clamped:
            raise time_limit()
        raise SnsError('aside', 'Aside did not open a tab in time.', _CHECK, reason='timeout')

    def _repl(self, header, function, args, seconds=None):
        try:
            text = program(header, function, args)
        except (TypeError, ValueError):
            raise SnsError('aside', 'A browser call had arguments that cannot be sent.',
                           'Report this as a skill bug.') from None
        limit, clamped = self._limit(seconds, REPL_SECONDS + 5)
        started = time.monotonic()
        try:
            result = subprocess.run(self._command('repl', text), capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            if clamped:
                raise time_limit() from None
            raise SnsError('aside', f'Aside did not answer within {int(limit)} seconds.',
                           'Check Aside, then run doctor; the request may have been made.', reason='timeout') from None
        except (OSError, UnicodeError):
            raise SnsError('aside', 'Aside could not run.', _CHECK) from None
        if result.returncode:
            text = (result.stdout + result.stderr).lower()
            if 'other side closed' in text or 'daemon is not reachable' in text or \
                    time.monotonic() - started > REPL_SECONDS:
                raise SnsError('aside', 'Aside lost its connection or reached its time limit.', _CHECK, reason='lost')
            raise SnsError('aside', 'Aside failed to run the browser call.', _CHECK, reason='failed')
        return parse(result.stdout)


def program(header, function, args):
    """The REPL program of one call: the header and arguments, then program.js with the page function in place."""
    return ('const ASIDE = ' + json.dumps(header, ensure_ascii=True) + ';\nconst ARGS = '
            + json.dumps(args, ensure_ascii=True) + ';\n' + PROGRAM.replace('PAGE_FUNCTION', function or 'null'))


def parse(stdout):
    """The value of one program run: chunk lines in index order, then one result line (or one error line)."""
    try:
        # JSON.stringify leaves U+2028, U+2029 and U+0085 literal inside strings; only a newline ends a line.
        lines = [json.loads(line) for line in (_ANSI.sub('', raw).strip(' \t\r') for raw in stdout.split('\n'))
                 if line.startswith('{')]
        lines = [line for line in lines if isinstance(line, dict) and line.get('kind') in ('chunk', 'result', 'error')]
        if not lines:
            raise ValueError
        last = lines[-1]
        if last['kind'] == 'error':
            if len(lines) != 1 or not isinstance(last.get('error'), str):
                raise ValueError
            if last['error'] == 'tab_missing':
                raise SnsError('aside', 'The dedicated browser tab is gone.', 'Run the command again; it opens a new '
                                                                             'tab.', reason='tab_missing')
            if last['error'] == 'load_timeout':
                raise SnsError('aside', 'The tab did not load in time.', _CHECK, reason='load_timeout')
            raise SnsError('aside', 'The browser could not run the call.', _CHECK, reason='failed')
        chunks = lines[:-1]
        if last['kind'] != 'result' or type(last.get('chunks')) is not int or last['chunks'] != len(chunks):
            raise ValueError
        if any(c['kind'] != 'chunk' or c.get('index') != i or not isinstance(c.get('body'), str)
               for i, c in enumerate(chunks)):
            raise ValueError
        if not isinstance(last.get('body'), str):
            raise ValueError
        return json.loads(''.join(c['body'] for c in chunks) if chunks else last['body'])
    except SnsError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise SnsError('aside', 'Aside returned output this skill cannot read.', _CHECK, reason='invalid') from None
