"""The Aside CLI: bounded processes whose output is read back into one JSON value, and the opener that leaves a tab
open with no process holding it.

A tab opened by a one-shot `aside repl` closes when that run ends, and so does a popup it opened; but a tab another
session has attached stays open when its opener ends. So a tab is opened by a held session (`aside repl` reading
stdin), recorded and attached by a second one, and only then is the opener ended. Nothing here uses `aside exec`
(the browser agent), so no agent session or credit is spent.
"""
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from twitter.errors import TwitterError

PROGRAM = (Path(__file__).with_name('program.js')).read_text(encoding='utf-8')
REPL_SECONDS = 120          # aside repl's own limit
OPEN_SECONDS = 30           # the opener's first answer
_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_CHECK = 'Check that Aside is running, then run doctor.'
# One line: the interactive REPL runs each line on its own. The leading string names it for the test fake.
_OPENER = ("'twitter-opener'; const xsBefore = await listBrowserTabs(); await openTab('about:blank'); "
           "const xsAfter = await listBrowserTabs(); console.log(JSON.stringify({kind: 'opened', tabs: "
           "xsAfter.filter(t => !xsBefore.some(b => b.targetId === t.targetId)).map(t => t.targetId)}));\n")


class Aside:
    """The Aside CLI for one Aside account: TWITTER_ASIDE_ACCOUNT, or Aside's default account when unset."""

    def __init__(self):
        self.binary = os.environ.get('TWITTER_ASIDE_BIN') or shutil.which('aside')
        self.account = os.environ.get('TWITTER_ASIDE_ACCOUNT') or None

    @property
    def account_key(self):
        """A file-name-safe name for the Aside account, for state that belongs to one browser profile."""
        return re.sub(r'[^A-Za-z0-9_-]', '_', self.account) if self.account else 'default'

    def _command(self, *args):
        if not self.binary:
            raise TwitterError(3, 'Aside is unavailable: its CLI is not on PATH.', 'Install or start Aside so the '
                                                                                  '`aside` command works, then run '
                                                                                  'doctor.')
        return [self.binary, *(['--account', self.account] if self.account else []), *args]

    def tabs(self, seconds=None):
        """Open browser tabs as [{target_id, url}]; listing touches no web page."""
        listed = self._repl({'op': 'tabs'}, None, {}, seconds)
        if not isinstance(listed, list):
            raise TwitterError(3, 'Aside returned an invalid tab list.', _CHECK)
        return [{'target_id': t.get('targetId'), 'url': t.get('url') or ''} for t in listed
                if isinstance(t, dict) and isinstance(t.get('targetId'), str)]

    @contextmanager
    def opener(self, seconds=None):
        """Open a new about:blank tab in a held session and yield its target id; the session ends when the block does.
        The caller records the tab and attaches it from another call before leaving the block (see the module
        docstring). Raises 3 when the tab cannot be told apart from the others."""
        limit = min(OPEN_SECONDS, seconds) if seconds is not None else OPEN_SECONDS
        try:
            process = subprocess.Popen(self._command('repl'), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1)  # stdout is read raw
        except (OSError, UnicodeError):
            raise TwitterError(3, 'Aside could not run.', _CHECK) from None
        try:
            try:
                process.stdin.write(_OPENER)
                process.stdin.flush()
            except OSError:
                raise TwitterError(3, 'Aside did not accept the tab opener.', _CHECK) from None
            found = self._opened(process, time.monotonic() + limit)
            if not isinstance(found, list) or len(found) != 1 or not isinstance(found[0], str):
                raise TwitterError(3, 'Aside opened no tab this skill can tell apart from the others.', _CHECK)
            yield found[0]
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    @staticmethod
    def _opened(process, deadline):
        """The new tab ids the opener printed, read from its raw output until its answer or the deadline (a buffered
        reader would hold lines back from select)."""
        descriptor = process.stdout.fileno()
        selector = selectors.DefaultSelector()
        selector.register(descriptor, selectors.EVENT_READ)
        pending = b''
        try:
            while time.monotonic() < deadline:
                if not selector.select(timeout=max(0.0, deadline - time.monotonic())):
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
        raise TwitterError(3, 'Aside did not open a tab in time.', _CHECK)

    def evaluate(self, target_id, function, args, seconds=None):
        """Run a page function in the tab `target_id` with `args`; returns what the function returned.

        A tab that no longer exists raises TwitterError with reason 'tab_missing'.
        """
        return self._repl({'op': 'evaluate', 'tab': target_id}, function, args, seconds)

    def load(self, target_id, url, function, args, seconds=None):
        """Send the tab to `url` without a history entry, then run `function` until it answers (not null); returns
        that answer. Used to act on a new page before its own scripts run."""
        wait = max(1, int(min(20, (seconds or 25) - 3)))
        return self._repl({'op': 'load', 'tab': target_id, 'url': url, 'seconds': wait}, function, args, seconds)

    def _repl(self, header, function, args, seconds=None):
        try:
            program = ('const ASIDE = ' + json.dumps(header, ensure_ascii=True) + ';\nconst ARGS = '
                       + json.dumps(args, ensure_ascii=True) + ';\n' + PROGRAM.replace('PAGE_FUNCTION', function or 'null'))
        except (TypeError, ValueError):
            raise TwitterError(3, 'A browser call had arguments that cannot be sent.', 'Report this as a skill bug.') from None
        limit = REPL_SECONDS + 5 if seconds is None else max(1.0, min(REPL_SECONDS + 5, seconds))
        started = time.monotonic()
        try:
            result = subprocess.run(self._command('repl', program), capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            raise TwitterError(3, f'Aside did not answer within {int(limit)} seconds.', 'Check Aside, then run doctor; '
                                                                                       'the request may have been '
                                                                                       'made.', reason='timeout') from None
        except (OSError, UnicodeError):
            raise TwitterError(3, 'Aside could not run.', _CHECK) from None
        if result.returncode:
            text = (result.stdout + result.stderr).lower()
            if 'other side closed' in text or 'daemon is not reachable' in text or time.monotonic() - started > REPL_SECONDS:
                raise TwitterError(3, 'Aside lost its connection or reached its time limit.', _CHECK, reason='lost')
            raise TwitterError(3, 'Aside failed to run the browser call.', _CHECK, reason='failed')
        return parse(result.stdout)


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
                raise TwitterError(3, 'The dedicated X tab is gone.', 'Run the command again; it opens a new tab.',
                                   reason='tab_missing')
            if last['error'] == 'load_timeout':
                raise TwitterError(3, 'The X tab did not load in time.', _CHECK, reason='load_timeout')
            raise TwitterError(3, 'The browser tab could not run the call.', _CHECK, reason='failed')
        chunks = lines[:-1]
        if last['kind'] != 'result' or type(last.get('chunks')) is not int or last['chunks'] != len(chunks):
            raise ValueError
        if any(c['kind'] != 'chunk' or c.get('index') != i or not isinstance(c.get('body'), str)
               for i, c in enumerate(chunks)):
            raise ValueError
        if not isinstance(last.get('body'), str):
            raise ValueError
        return json.loads(''.join(c['body'] for c in chunks) if chunks else last['body'])
    except TwitterError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise TwitterError(3, 'Aside returned output this skill cannot read.', _CHECK, reason='invalid') from None
