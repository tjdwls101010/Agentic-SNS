"""Comment-tree snapshots: one file per read generation of a thread.

A generation starts with a first request for a (post, anchor comment, sort) key and is named by that key and a nonce,
so a later read of the same thread starts a new generation instead of changing what an older handle continues. A
snapshot is read, changed and saved under one lock; snapshots expire after TTL_SECONDS and the oldest are evicted when
the total passes MAX_BYTES. An unreadable snapshot asks for the post to be opened again.
"""
import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager

from reddit.errors import RedditError
from reddit.paths import state_dir

TTL_SECONDS = 24 * 3600
MAX_BYTES = 200 * 1024 * 1024
_GENERATION = re.compile(r'[0-9a-f]{16}-[0-9]+-[0-9a-f]{8}')
_REOPEN = 'Open the post again (post <url>) to start a new reading.'


def _key(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


class Snapshots:
    """The snapshots of one Aside account."""

    def __init__(self, account):
        try:
            self.directory = state_dir('snapshots', account)
        except OSError:
            raise RedditError(6, 'Cannot keep the comment thread.', 'Make the skill\'s data/ directory writable.') \
                from None

    @contextmanager
    def locked(self):
        # 성진: 스냅숏 전체에 잠금 하나 — 대화는 명령을 하나씩 실행한다. 동시 실행의 경합이 측정되면 생성마다 나눈다
        with open(self.directory / 'lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield self
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def new(self, parts):
        """A new generation id for the key `parts` (post, anchor, sort)."""
        return f'{_key(parts)}-{int(time.time() * 1000)}-{secrets.token_hex(4)}'

    def latest(self, parts):
        """The newest live generation of a key, or None."""
        prefix, cutoff = _key(parts) + '-', time.time() - TTL_SECONDS
        found = []
        for path in self.directory.glob(prefix + '*.json'):
            try:
                if path.stat().st_mtime >= cutoff:
                    found.append((int(path.stem.split('-')[1]), path.stem))
            except (OSError, ValueError, IndexError):
                continue
        return max(found)[1] if found else None

    def _path(self, generation):
        if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
            raise RedditError(2, 'The thread reference is not one this skill made.', _REOPEN)
        return self.directory / f'{generation}.json'

    def load(self, generation):
        """The snapshot of a generation; None when it expired or was evicted; unreadable raises (argument error)."""
        path = self._path(generation)
        try:
            if time.time() - path.stat().st_mtime > TTL_SECONDS:
                return None
            state = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise RedditError(2, 'The saved comment thread is unreadable.', _REOPEN) from None
        if not isinstance(state, dict):
            raise RedditError(2, 'The saved comment thread is unreadable.', _REOPEN)
        return state

    def save(self, generation, state):
        """Write a generation, then evict expired and, above MAX_BYTES, the oldest other snapshots."""
        path = self._path(generation)
        encoded = json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode()
        if len(encoded) > MAX_BYTES:
            raise RedditError(6, 'This comment thread is larger than the space kept for threads.',
                              'Read it with --out instead, which writes as it goes.')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('wb', dir=self.directory, suffix='.tmp', delete=False) as stream:
                temporary = stream.name
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError:
            raise RedditError(6, 'Cannot keep the comment thread.', 'Free disk space, then retry.') from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        self._evict(path)

    def _evict(self, keep):
        cutoff, files = time.time() - TTL_SECONDS, []
        for path in self.directory.glob('*.json'):
            try:
                info = path.stat()
            except OSError:
                continue
            if path != keep and info.st_mtime < cutoff:
                path.unlink(missing_ok=True)
            else:
                files.append((info.st_mtime, info.st_size, path))
        total = sum(size for _, size, _ in files)
        for _, size, path in sorted(files):
            if total <= MAX_BYTES:
                break
            if path != keep:
                path.unlink(missing_ok=True)
                total -= size
