"""Numbered handles: a later command continues a reading by number.

A handle is bound to the query context it was made for (command, target, order, period, window days, filters, the Aside
account) and to the Reddit account that observed it; it carries a format version, expires after TTL_SECONDS, and is
never reused: the counter is reserved and fsynced before the handle file is written, and cleaning removes handle files
but never the counter.
"""
import fcntl
import json
import os
import time

from reddit.errors import RedditError
from reddit.paths import state_dir

FORMAT = 1
TTL_SECONDS = 24 * 3600

_RESTART = 'Rerun the original command without --after.'
_UNSAVED = ('Cannot save a handle to continue from.', 'Make the skill\'s data/ directory writable, then rerun the command.')


def _directory(account, create=True):
    try:
        return state_dir('handles', account, create)
    except OSError:
        raise RedditError(6, *_UNSAVED) from None


def save(account, context, state):
    """Store `state` for the query `context` (which names the observing Reddit account as reddit_account); returns the
    new handle number. Expired handles are removed."""
    directory = _directory(account)
    _prune(directory)
    try:
        fd = os.open(directory / 'counter', os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'r+b') as counter:
            fcntl.flock(counter, fcntl.LOCK_EX)
            number = int(counter.read().strip() or b'0') + 1
            counter.seek(0)
            counter.write(str(number).encode())
            counter.truncate()
            counter.flush()
            os.fsync(counter.fileno())
            record = {'format': FORMAT, 'context': context, 'state': state, 'created_at': time.time()}
            path = directory / f'{number}.json'
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
                json.dump(record, stream, ensure_ascii=False, separators=(',', ':'))
                stream.flush()
                os.fsync(stream.fileno())
            return number
    except (OSError, ValueError):
        raise RedditError(6, *_UNSAVED) from None


def load(account, number, context):
    """The state saved under `number` for this exact `context`. Another query, an expired or older handle is an
    argument error; the same query observed with another Reddit account than the one logged in now is a login error."""
    if type(number) is bool or not str(number).isascii() or not str(number).isdigit() or int(number) < 1:
        raise RedditError(2, 'A handle is a positive number printed by an earlier command.', 'Copy the whole more: line.')
    try:
        record = json.loads((_directory(account, create=False) / f'{int(number)}.json').read_text())
    except (OSError, ValueError):
        raise RedditError(2, f'Handle {int(number)} does not exist (or was cleaned up).', _RESTART) from None
    if not isinstance(record, dict) or record.get('format') != FORMAT:
        raise RedditError(2, f'Handle {int(number)} was made by an earlier version of this skill.', _RESTART)
    saved = record.get('context')
    if not isinstance(saved, dict) or {k: v for k, v in saved.items() if k != 'reddit_account'} != \
            {k: v for k, v in context.items() if k != 'reddit_account'}:
        raise RedditError(2, f'Handle {int(number)} belongs to another command, target, order, window or account.',
                          'Copy the whole more: line that printed it.')
    if saved.get('reddit_account') != context.get('reddit_account'):
        raise RedditError(4, f'Handle {int(number)} was read as u/{saved.get("reddit_account")}, but the Aside browser '
                             f'is now logged in to Reddit as u/{context.get("reddit_account")}.',
                          'Run the original command again (without --after) to read as the current account.',
                          reason='account_changed')
    created = record.get('created_at')
    if type(created) not in (int, float) or time.time() - created > TTL_SECONDS:
        raise RedditError(2, f'Handle {int(number)} has expired.', _RESTART)
    state = record.get('state')
    if not isinstance(state, dict):
        raise RedditError(2, f'Handle {int(number)} is incomplete.', _RESTART)
    return state


def _prune(directory):
    """Handles hold other people's ids; one past its TTL is useless, so it is deleted when a new one is saved."""
    cutoff = time.time() - TTL_SECONDS
    for path in directory.glob('*.json'):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass
