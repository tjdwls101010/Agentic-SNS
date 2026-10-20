"""Small file primitives every store shares: an atomic JSON write, a fail-closed JSON read, a lock waited for only
until a deadline, and a best-effort line append."""
import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager

LOCK_POLL = 0.05


def write_json(path, value, fail):
    """Write `value` to `path` atomically (a temporary file, fsync, then replace), private (0600); `fail()` is raised
    when it cannot be written."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.' + path.name, delete=False,
                                         encoding='utf-8') as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        temporary = None
    except (OSError, TypeError, ValueError):
        raise fail() from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, fail):
    """The object stored at `path`, None when there is no file; `fail()` is raised for anything else (unreadable, not
    JSON, not an object, a link to nothing) — state that cannot be read is never taken for absent state."""
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if path.is_symlink():
            raise fail() from None
        return None
    except (OSError, ValueError, UnicodeError):
        raise fail() from None
    if not isinstance(value, dict):
        raise fail()
    return value


@contextmanager
def locked(path, deadline, fail, sleep=time.sleep, unavailable=None):
    """An exclusive lock on `path`, waited for until `deadline` runs out (`deadline` None: as long as it takes);
    `fail()` is raised when the lock does not come in time, `unavailable()` (default: `fail()`) when the file cannot
    be opened at all."""
    try:
        stream = open(path, 'a')
    except OSError:
        raise (unavailable or fail)() from None
    try:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (fcntl.LOCK_NB if deadline is not None else 0))
                break
            except BlockingIOError:
                if deadline.left() <= LOCK_POLL:
                    raise fail() from None
                sleep(LOCK_POLL)  # real time: another process holds the lock
        yield
    finally:
        try:
            fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            stream.close()


def append_line(path, value):
    """Append one JSON line; returns whether it was written. For observation records that must never stop work."""
    try:
        with open(path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
        return True
    except (OSError, TypeError, ValueError):
        return False
