"""The Aside CLI: which Aside account an invocation uses, and bounded `aside` processes whose output is read back into
one JSON value through one protocol (program.js).

Every call is clamped to the invocation's deadline. A call cut short by that clamp is the time limit (the command ends
and can resume), not an Aside failure; a call that times out with time to spare, or loses its connection, is.

An Aside failure names its cause, because each has a different remedy: the `aside` command is missing or does not run
(install it), the account or the agent cannot be used (sign in, pick an account), Aside cannot be reached (start it),
or Aside answered in a way this skill does not know (the skill may not match this Aside version, which the message
names). The `aside` command starts a closed Aside app by itself, which takes about half a minute (measured 2026-11-15).

A dedicated tab is opened with `open(url)` (`aside <url>`): Aside's browser agent opens the tab and it outlives the
call. That is the only way Aside 1.26 keeps a tab: a tab a REPL call opens is closed when that call ends, even while
another call has it attached, and piped REPL code runs only once stdin closes (measured 2026-11-15). A page that must
see its app from the first script (X) is opened on a placeholder and sent on with `load()`, which installs the
observer as the new document begins. Tab-less reads (Reddit, Naver) `run` a function in the REPL itself, which fetches
with the browser's cookies.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from sns.errors import SnsError

PROGRAM = (Path(__file__).with_name('program.js')).read_text(encoding='utf-8')
MEDIA = (Path(__file__).with_name('media.js')).read_text(encoding='utf-8')
REPL_SECONDS = 120          # aside repl's own limit
OPEN_SECONDS = 30           # opening a tab (`aside <url>`: about 4 s measured)
# `aside account status`: answers at once, or after about 35 s when it first starts a closed Aside (measured)
STATUS_SECONDS = 45
VERSION_SECONDS = 5         # `aside --version` (local, no app)
_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
_RUNS = 'Check that the `aside` command runs in a terminal (`aside --version`), then run doctor.'
_START = 'Start the Aside app (a closed one is started by the `aside` command, which takes about half a minute), then ' \
         'run doctor.'
_AGENT = 'Check that `aside https://example.com` opens a tab: Aside opens tabs through its browser agent, which needs ' \
         'Aside signed in with a model it can use. Then run doctor.'


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
            raise SnsError('aside', 'Aside is unavailable: its `aside` command is not on PATH.',
                           'Install Aside (it provides the `aside` command), then run doctor.', reason='missing')
        self._version = None
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
            raise SnsError('aside', 'Aside did not say which account is active in time: it is not running, or did not '
                                    'finish starting.', _START, reason='unreachable') from None
        except (OSError, UnicodeError):
            raise SnsError('aside', 'The `aside` command could not run.', _RUNS, reason='missing') from None
        account = active_account(done.stdout) if done.returncode == 0 else None
        if account is None:
            raise SnsError('aside', 'Could not tell which Aside account to use.',
                           'Set SNS_ASIDE_ACCOUNT to the Aside account id (such as u0), or check '
                           '`aside account status`.', reason='account')
        return account

    def version(self):
        """What `aside --version` prints (asked once, without the app), or None when it does not answer."""
        if self._version is None:
            try:
                done = subprocess.run([self.binary, '--version'], capture_output=True, text=True,
                                      timeout=VERSION_SECONDS)
                words = done.stdout.split() if done.returncode == 0 else []
                self._version = words[-1] if words else ''
            except (OSError, UnicodeError, subprocess.TimeoutExpired):
                self._version = ''
        return self._version or None

    def unexpected(self, message, reason='invalid'):
        """The failure of an Aside that answered, but not the way this skill knows: it names the Aside version."""
        version = self.version() or '(version unknown)'
        return SnsError('aside', f'{message} Aside {version} answered in a way this skill does not expect.',
                        f'Run doctor; if it fails the same way, tell the user this skill may not match Aside {version} '
                        'and needs an update.', reason=reason)

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
            raise self.unexpected('Aside returned an invalid tab list.')
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
            raise self.unexpected('Aside returned a picture answer this skill cannot read.')
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
            raise self.unexpected('Aside returned picture bytes this skill cannot read.') from None

    def open(self, url, seconds=None):
        """Open `url` in a new persistent tab (`aside <url>`) and wait for Aside to finish opening it."""
        limit, clamped = self._limit(seconds, OPEN_SECONDS)
        try:
            result = subprocess.run(self._command(url), capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            if clamped:
                raise time_limit() from None
            raise SnsError('aside', 'Aside\'s browser agent did not finish opening the tab in time.', _AGENT,
                           reason='timeout') from None
        except (OSError, UnicodeError):
            raise SnsError('aside', 'The `aside` command could not run.', _RUNS, reason='missing') from None
        if result.returncode:
            if _unreachable(result.stdout + result.stderr):
                raise SnsError('aside', 'Aside could not be reached to open the tab.', _START, reason='unreachable')
            raise SnsError('aside', 'Aside\'s browser agent could not open the tab.', _AGENT, reason='failed')

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
            version = self.version() or '(version unknown)'
            raise SnsError('aside', f'Aside did not answer within {int(limit)} seconds; the request may have been made.',
                           'Run doctor. If it passes, Aside is reachable and the page was slow: run the command again. '
                           f'If doctor fails the same way, this skill may not match Aside {version}.',
                           reason='timeout') from None
        except (OSError, UnicodeError):
            raise SnsError('aside', 'The `aside` command could not run.', _RUNS, reason='missing') from None
        if result.returncode:
            if _unreachable(result.stdout + result.stderr) or time.monotonic() - started > REPL_SECONDS:
                raise SnsError('aside', 'Aside lost its connection or reached its time limit.', _START, reason='lost')
            raise self.unexpected('Aside failed to run the browser call.', reason='failed')
        try:
            return parse(result.stdout)
        except SnsError as error:
            if error.reason == 'invalid':
                raise self.unexpected(error.message, reason=error.reason) from None
            raise


def _unreachable(output):
    """Whether the `aside` command said it could not reach the app."""
    text = output.lower()
    return 'other side closed' in text or 'daemon is not reachable' in text


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
                raise SnsError('aside', 'The tab did not load in time.', 'Run the command again; if the page keeps '
                                                                         'not loading, run doctor.', reason='load_timeout')
            raise SnsError('aside', 'The browser could not run the call.', 'Run doctor.', reason='failed')
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
        raise SnsError('aside', 'Aside returned output this skill cannot read.', 'Run doctor.', reason='invalid') from None
