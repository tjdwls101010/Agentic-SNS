"""Numbered handles: a later command continues a reading, or opens a reply's branch, by number.

One counter serves the whole skill, so a number names one handle across all platforms (a handle given to another
platform's command is refused with where it belongs). A handle is bound to the query context it was made for
(platform, command, target, identity, Aside account) and keeps, beside it, the platform account it was read with, which
the caller compares itself (a different one is a changed login, not a wrong argument). It expires after TTL_SECONDS and
is never reused: the counter is reserved and fsynced before the handle file is written, and cleaning removes handle
files, never the counter. Numbers start at FIRST.
"""
import fcntl
import json
import os
import time
from contextlib import contextmanager

from sns.errors import SnsError
from sns.paths import data_dir, shared

FORMAT = 1
TTL_SECONDS = 24 * 3600
KEEP_SECONDS = 7 * 24 * 3600   # how long an expired handle keeps the command that remakes it (no cursor, no ids)
FIRST = 1000
_RESTART = 'Rerun the original command without --after (or the command that printed this handle).'


def _directory():
    try:
        return shared('handles')
    except SnsError:
        raise SnsError('failed', 'Cannot save a handle to continue from.',
                       'Make the skill\'s state directory writable, then rerun the command.') from None


@contextmanager
def _counter(directory, deadline):
    """The counter file, locked; waited for only until `deadline` (None: as long as it takes)."""
    fd = os.open(directory / 'counter', os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'r+b') as counter:
        while True:
            try:
                fcntl.flock(counter, fcntl.LOCK_EX | (fcntl.LOCK_NB if deadline is not None else 0))
                break
            except BlockingIOError:
                if deadline.left() <= 0.05:
                    raise SnsError('failed', 'The command reached its time limit while saving where to continue.',
                                   'Run the command again.', reason='time_limit') from None
                deadline.clock.sleep(0.05)
        yield counter


def save(context, state, viewer=None, deadline=None, remake=None):
    """Store `state` for the query `context` (and the platform account it was read with); returns the new number.
    `remake` is the command line that makes such a handle again (the reading restarted), given back once it expires."""
    directory = _directory()
    _prune(directory)
    try:
        with _counter(directory, deadline) as counter:
            text = counter.read().strip()
            number = max(int(text or b'0') + 1, FIRST)
            counter.seek(0)
            counter.write(str(number).encode())
            counter.truncate()
            counter.flush()
            os.fsync(counter.fileno())
            record = {'format': FORMAT, 'context': context, 'viewer': viewer, 'state': state,
                      'created_at': time.time(), 'remake': remake}
            path = directory / f'{number}.json'
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
                json.dump(record, stream, ensure_ascii=False, separators=(',', ':'))
                stream.flush()
                os.fsync(stream.fileno())
            return number
    except (OSError, ValueError, TypeError):
        raise SnsError('failed', 'Cannot save a handle to continue from.',
                       'Make the skill\'s state directory writable, then rerun the command.') from None


def adopt_counter(legacy):
    """Go on numbering from an install from before the state moved (`legacy`: its old data/handles/), so a number it
    gave is never given again here (handles themselves stay where they were: they last a day)."""
    try:
        text = (legacy / 'counter').read_text(encoding='utf-8').strip()
        old = int(text or '0')
    except (OSError, ValueError, UnicodeError):
        return
    directory = _directory()
    try:
        with _counter(directory, None) as counter:
            current = int(counter.read().strip() or b'0')
            if old > current:
                counter.seek(0)
                counter.write(str(old).encode())
                counter.truncate()
                counter.flush()
                os.fsync(counter.fileno())
    except (OSError, ValueError):
        raise SnsError('failed', 'Cannot carry the handle numbering over from the old data/.',
                       'Make the skill\'s state directory writable, then rerun the command.') from None


def _where(context):
    if not isinstance(context, dict):
        return 'another query'
    return f'{str(context.get("platform", "?")).replace("_", "-")} {context.get("command", "?")}'


def load(number, context):
    """(state, viewer) saved under `number` for this exact `context`; anything else is an argument error."""
    if type(number) is bool or not str(number).isascii() or not str(number).isdigit() or int(number) < 1:
        raise SnsError('argument', 'A handle is a positive number printed by an earlier command.',
                       'Copy the whole more: or replies line.')
    number = int(number)
    try:
        record = json.loads((data_dir() / 'handles' / f'{number}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise SnsError('argument', f'Handle {number} does not exist (or was cleaned up).', _RESTART) from None
    if not isinstance(record, dict) or record.get('format') != FORMAT:
        raise SnsError('argument', f'Handle {number} was made by an earlier version of this skill.', _RESTART)
    saved = record.get('context')
    if saved != context:
        same_command = isinstance(saved, dict) and _where(saved) == _where(context)
        raise SnsError('argument', f'Handle {number} belongs to {_where(saved)}'
                       + (' with another target, order or account.' if same_command else ', not this command.'),
                       f'Run it as {_where(saved)}: copy the whole more: or replies line that printed it.')
    created = record.get('created_at')
    if type(created) not in (int, float) or time.time() - created > TTL_SECONDS or 'state' not in record:
        remake = record.get('remake')
        raise SnsError('argument', f'Handle {number} has expired: handles last 24 hours (a post\'s URL does not).',
                       f'Start the reading again: {remake}' if isinstance(remake, str) and remake
                       else _RESTART)
    state = record.get('state')
    if not isinstance(state, dict):
        raise SnsError('argument', f'Handle {number} is incomplete.', _RESTART)
    viewer = record.get('viewer')
    return state, viewer if isinstance(viewer, str) else None


def remake_of(number):
    """The command a saved handle names for starting its reading again, or None (no such handle, or none saved)."""
    try:
        record = json.loads((data_dir() / 'handles' / f'{int(number)}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    remake = record.get('remake') if isinstance(record, dict) else None
    return remake if isinstance(remake, str) and remake else None


def _prune(directory):
    """Handles hold other people's ids, so one past its day loses its cursor when a new one is saved; it keeps the
    command that remakes it for KEEP_SECONDS more, so its more: line still says what to run, and then goes."""
    now = time.time()
    for path in directory.glob('*.json'):
        try:
            if path.stat().st_mtime >= now - TTL_SECONDS:
                continue
            record = json.loads(path.read_text(encoding='utf-8'))
            created = record.get('created_at') if isinstance(record, dict) else None
            if type(created) not in (int, float) or now - created > TTL_SECONDS + KEEP_SECONDS or not record.get('remake'):
                path.unlink()
            elif 'state' in record:
                kept = {key: record[key] for key in ('format', 'context', 'created_at', 'remake') if key in record}
                temporary = path.with_name('.' + path.name + '.tmp')
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
                    json.dump(kept, stream, ensure_ascii=False, separators=(',', ':'))
                os.utime(temporary, (created, created))
                os.replace(temporary, path)
        except (OSError, ValueError):
            pass
