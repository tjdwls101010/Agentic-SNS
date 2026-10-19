"""Numbered handles: a later command continues a reading, or opens a comment's replies, by number.

A handle is bound to the query context it was made for (command, target, order, filters, X account), expires
after TTL_SECONDS, and is never reused: the counter is reserved and fsynced before the handle file is written, and
cleaning removes handle files but never the counter.
"""
import fcntl
import json
import os
import time

from twitter.errors import TwitterError
from twitter.paths import data_dir, state_dir

FORMAT = 3  # 3: the first format of this skill (the previous twitter skill's handles were six letters, never numbers)
TTL_SECONDS = 24 * 3600

_RESTART = 'Rerun the original command without --after (or the command that printed this handle).'


def _directory(create=True):
    try:
        return state_dir('handles') if create else data_dir() / 'handles'
    except OSError:
        raise TwitterError(6, 'Cannot save a handle to continue from.', 'Make the skill\'s data/ directory '
                                                                         'writable, then rerun the command.') from None


def save(context, state):
    """Store `state` for the query `context`; returns the new handle number. Expired handles are removed."""
    directory = _directory()
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
        raise TwitterError(6, 'Cannot save a handle to continue from.', 'Make the skill\'s data/ directory '
                                                                         'writable, then rerun the command.') from None


def load(number, context):
    """The state saved under `number` for this exact `context`; anything else is an argument error."""
    if type(number) is bool or not str(number).isascii() or not str(number).isdigit() or int(number) < 1:
        raise TwitterError(2, 'A handle is a positive number printed by an earlier command.',
                            'Copy the whole more: or replies line.')
    try:
        record = json.loads((_directory(create=False) / f'{int(number)}.json').read_text())
    except (OSError, ValueError):
        raise TwitterError(2, f'Handle {int(number)} does not exist (or was cleaned up).', _RESTART) from None
    if not isinstance(record, dict) or record.get('format') != FORMAT:
        raise TwitterError(2, f'Handle {int(number)} was made by an earlier version of this skill.', _RESTART)
    if record.get('context') != context:
        raise TwitterError(2, f'Handle {int(number)} belongs to another command, target, order or account.',
                            'Copy the whole more: or replies line that printed it.')
    created = record.get('created_at')
    if type(created) not in (int, float) or time.time() - created > TTL_SECONDS:
        raise TwitterError(2, f'Handle {int(number)} has expired; X cursors do not last.', _RESTART)
    state = record.get('state')
    if not isinstance(state, dict):
        raise TwitterError(2, f'Handle {int(number)} is incomplete.', _RESTART)
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


def clean():
    """Delete every handle file (they hold other people's ids); the counter stays so numbers are never reused."""
    directory = _directory(create=False)
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.glob('*.json'):
        path.unlink(missing_ok=True)
        removed += 1
    return removed
