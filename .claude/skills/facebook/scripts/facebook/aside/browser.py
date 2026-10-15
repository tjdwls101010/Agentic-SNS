"""The Aside CLI: one bounded process per call, its output read back into one JSON value."""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from facebook.errors import FacebookError

PROGRAM = (Path(__file__).with_name('program.js')).read_text(encoding='utf-8')
REPL_SECONDS = 120          # aside repl's own limit
PROCESS_SECONDS = REPL_SECONDS + 5
OPEN_SECONDS = 90
_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_CHECK = 'Check that Aside is running, then run doctor.'


class Aside:
    """The Aside CLI for one Aside account: FACEBOOK_ASIDE_ACCOUNT, or Aside's default account when unset."""

    def __init__(self):
        self.binary = os.environ.get('FACEBOOK_ASIDE_BIN') or shutil.which('aside')
        self.account = os.environ.get('FACEBOOK_ASIDE_ACCOUNT') or None

    @property
    def account_key(self):
        """A file-name-safe name for the Aside account, for state that belongs to one browser profile."""
        return re.sub(r'[^A-Za-z0-9_-]', '_', self.account) if self.account else 'default'

    def _command(self, *args):
        if not self.binary:
            raise FacebookError(3, 'Aside is unavailable: its CLI is not on PATH.', 'Install or start Aside so the '
                                                                                   '`aside` command works, then run '
                                                                                   'doctor.')
        return [self.binary, *(['--account', self.account] if self.account else []), *args]

    def tabs(self):
        """Open browser tabs as [{target_id, url}]; listing touches no web page."""
        listed = self._repl({'op': 'tabs'}, None, {})
        if not isinstance(listed, list):
            raise FacebookError(3, 'Aside returned an invalid tab list.', _CHECK)
        return [{'target_id': t.get('targetId'), 'url': t.get('url') or ''} for t in listed
                if isinstance(t, dict) and isinstance(t.get('targetId'), str)]

    def open(self, url):
        """Open `url` in a new persistent browser tab (`aside <url>`) and wait for Aside to finish opening it."""
        try:
            result = subprocess.run(self._command(url), capture_output=True, text=True, timeout=OPEN_SECONDS)
        except subprocess.TimeoutExpired:
            raise FacebookError(3, 'Aside did not finish opening the Facebook tab in time.', _CHECK) from None
        except (OSError, UnicodeError):
            raise FacebookError(3, 'Aside could not run.', _CHECK) from None
        if result.returncode:
            raise FacebookError(3, 'Aside could not open the Facebook tab.', _CHECK)

    def evaluate(self, target_id, function, args):
        """Run a page function in the tab `target_id` with `args`; returns what the function returned.

        A tab that no longer exists raises FacebookError with reason 'tab_missing'.
        """
        return self._repl({'op': 'evaluate', 'tab': target_id}, function, args)

    def _repl(self, header, function, args):
        try:
            program = ('const ASIDE = ' + json.dumps(header, ensure_ascii=True) + ';\nconst ARGS = '
                       + json.dumps(args, ensure_ascii=True) + ';\n' + PROGRAM.replace('PAGE_FUNCTION', function or 'null'))
        except (TypeError, ValueError):
            raise FacebookError(3, 'A browser call had arguments that cannot be sent.', 'Report this as a skill bug.') from None
        started = time.monotonic()
        try:
            result = subprocess.run(self._command('repl', program), capture_output=True, text=True, timeout=PROCESS_SECONDS)
        except subprocess.TimeoutExpired:
            raise FacebookError(3, f'Aside did not answer within {REPL_SECONDS} seconds.', 'Check Aside, then run '
                                                                                          'doctor; the request may '
                                                                                          'have been made.') from None
        except (OSError, UnicodeError):
            raise FacebookError(3, 'Aside could not run.', _CHECK) from None
        if result.returncode:
            text = (result.stdout + result.stderr).lower()
            if 'other side closed' in text or 'daemon is not reachable' in text or time.monotonic() - started > REPL_SECONDS:
                raise FacebookError(3, 'Aside lost its connection or reached its time limit.', _CHECK)
            raise FacebookError(3, 'Aside failed to run the browser call.', _CHECK)
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
                raise FacebookError(3, 'The dedicated Facebook tab is gone.', 'Run the command again; it opens a new '
                                                                              'tab.', reason='tab_missing')
            raise FacebookError(3, 'The browser tab could not run the call.', _CHECK)
        chunks = lines[:-1]
        if last['kind'] != 'result' or type(last.get('chunks')) is not int or last['chunks'] != len(chunks):
            raise ValueError
        if any(c['kind'] != 'chunk' or c.get('index') != i or not isinstance(c.get('body'), str)
               for i, c in enumerate(chunks)):
            raise ValueError
        if not isinstance(last.get('body'), str):
            raise ValueError
        return json.loads(''.join(c['body'] for c in chunks) if chunks else last['body'])
    except FacebookError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise FacebookError(3, 'Aside returned output this skill cannot read.', _CHECK) from None
