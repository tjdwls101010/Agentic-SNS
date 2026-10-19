"""The Aside CLI: which Aside account to use, and one bounded `aside repl` process per Reddit request."""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from reddit.errors import RedditError

SNIPPET = (Path(__file__).with_name('fetch.js')).read_text(encoding='utf-8')
REPL_SECONDS = 120          # aside repl's own limit
PROCESS_SECONDS = REPL_SECONDS + 5
STATUS_SECONDS = 30
_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
_CHECK = 'Check that Aside is running, then run doctor.'


class Aside:
    """The Aside CLI pinned to one Aside account for the whole invocation."""

    def __init__(self):
        self.binary = os.environ.get('REDDIT_ASIDE_BIN') or shutil.which('aside')
        if not self.binary:
            raise RedditError(3, 'Aside is unavailable: its CLI is not on PATH.', 'Install or start Aside so the '
                                                                                  '`aside` command works, then run '
                                                                                  'doctor.')
        self.account = self._account()

    def _account(self):
        """REDDIT_ASIDE_ACCOUNT, else the account `aside account status` marks active — resolved before any request,
        so the default account and the same id named explicitly share one protection state."""
        named = os.environ.get('REDDIT_ASIDE_ACCOUNT')
        if named:
            if not _ID.fullmatch(named):
                raise RedditError(2, 'REDDIT_ASIDE_ACCOUNT is not an Aside account id (such as u0).',
                                  'Set it to an id `aside account list` shows, or unset it.')
            return named
        try:
            done = subprocess.run([self.binary, 'account', 'status'], capture_output=True, text=True,
                                  timeout=STATUS_SECONDS)
        except subprocess.TimeoutExpired:
            raise RedditError(3, 'Aside did not say which account is active in time.', _CHECK) from None
        except (OSError, UnicodeError):
            raise RedditError(3, 'Aside could not run.', _CHECK) from None
        account = active_account(done.stdout) if done.returncode == 0 else None
        if account is None:
            raise RedditError(3, 'Could not tell which Aside account to use.', 'Set REDDIT_ASIDE_ACCOUNT to the Aside '
                                                                               'account id (such as u0), or check '
                                                                               '`aside account status`.')
        return account

    def fetch(self, args):
        """One GET through the browser: args {path, query} or {url}. Returns the envelope {status, url, body,
        location, ratelimit}."""
        try:
            program = 'const ARGS = ' + json.dumps(args, ensure_ascii=True) + ';\n' + SNIPPET
        except (TypeError, ValueError):
            raise RedditError(3, 'A browser call had arguments that cannot be sent.', 'Report this as a skill bug.') \
                from None
        started = time.monotonic()
        try:
            result = subprocess.run([self.binary, '--account', self.account, 'repl', program], capture_output=True,
                                    text=True, timeout=PROCESS_SECONDS)
        except subprocess.TimeoutExpired:
            raise RedditError(3, f'Aside did not answer within {REPL_SECONDS} seconds.',
                              'Check Aside, then run doctor; the request may have been made.', reason='timeout') \
                from None
        except (OSError, UnicodeError):
            raise RedditError(3, 'Aside could not run.', _CHECK) from None
        if result.returncode:
            text = (result.stdout + result.stderr).lower()
            if 'other side closed' in text or 'daemon is not reachable' in text or \
                    time.monotonic() - started > REPL_SECONDS:
                raise RedditError(3, 'Aside lost its connection or reached its time limit.', _CHECK, reason='lost')
            raise RedditError(3, 'Aside failed to run the browser request.', _CHECK, reason='failed')
        return parse(result.stdout)


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


def parse(stdout):
    """The envelope of one fetch: body_chunk lines in index order, then one envelope line."""
    try:
        lines = [json.loads(line) for line in (_ANSI.sub('', raw).strip() for raw in stdout.split('\n'))
                 if line.startswith('{')]
        if not lines:
            raise ValueError
        envelope = lines[-1]
        if not isinstance(envelope, dict) or 'body_file' in envelope:
            raise ValueError
        chunks = lines[:-1]
        if 'body_chunks' in envelope:
            count = envelope.pop('body_chunks')
            if type(count) is not int or count != len(chunks):
                raise ValueError
            if any(not isinstance(c, dict) or c.get('kind') != 'body_chunk' or c.get('index') != i
                   or not isinstance(c.get('body'), str) for i, c in enumerate(chunks)):
                raise ValueError
            envelope['body'] = ''.join(c['body'] for c in chunks)
        elif chunks:
            raise ValueError
        if (type(envelope.get('status')) is not int or not 100 <= envelope['status'] <= 599
                or not isinstance(envelope.get('url'), str) or not isinstance(envelope.get('body'), str)
                or not isinstance(envelope.get('ratelimit'), dict)
                or not isinstance(envelope.get('location'), (str, type(None)))):
            raise ValueError
        return envelope
    except (ValueError, TypeError, KeyError, RecursionError):
        raise RedditError(3, 'Aside returned output this skill cannot read.', _CHECK, reason='invalid') from None
