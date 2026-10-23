"""Comment-tree snapshots: one file per read generation of a thread, under data/reddit/<account>/snapshots/.

A generation starts with a first request for a (post, anchor comment, sort) key and is named by that key and a nonce,
so a later read of the same thread starts a new generation instead of changing what an older handle continues. A
snapshot is read, changed and saved under one lock; snapshots expire after TTL_SECONDS and the oldest are evicted when
the total passes MAX_BYTES. An unreadable snapshot asks for the post to be opened again.
"""
import hashlib
import json
import re
import secrets
import time
from contextlib import contextmanager

from sns.atomic import locked, write_json
from sns.errors import SnsError
from sns.paths import scope

TTL_SECONDS = 24 * 3600
MAX_BYTES = 200 * 1024 * 1024
_GENERATION = re.compile(r'[0-9a-f]{16}-[0-9]+-[0-9a-f]{8}')
_REOPEN = 'Open the post again (post <url>) to start a new reading.'


def _key(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def _cannot_keep():
    return SnsError('failed', 'Cannot keep the comment thread.', 'Make the skill\'s data/ directory writable and free '
                                                                'disk space, then retry.')


class Snapshots:
    """The snapshots of one Aside account; `deadline` bounds the wait for the lock."""

    def __init__(self, account, deadline=None):
        self.deadline = deadline
        try:
            self.directory = scope('reddit', account, 'snapshots')
        except SnsError:
            raise _cannot_keep() from None

    @contextmanager
    def locked(self):
        # 성진: 스냅숏 전체에 잠금 하나 — 대화는 명령을 하나씩 실행한다. 동시 실행의 경합이 측정되면 생성마다 나눈다
        def late():
            return SnsError('failed', 'The command reached its time limit while waiting for the comment thread.',
                            'Run the command again.', reason='time_limit')
        sleep = self.deadline.clock.sleep if self.deadline is not None else time.sleep
        with locked(self.directory / 'lock', self.deadline, late, sleep=sleep):
            yield self

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
            raise SnsError('argument', 'The thread reference is not one this skill made.', _REOPEN)
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
            raise SnsError('argument', 'The saved comment thread is unreadable.', _REOPEN) from None
        if not isinstance(state, dict):
            raise SnsError('argument', 'The saved comment thread is unreadable.', _REOPEN)
        return state

    def save(self, generation, state):
        """Write a generation, then evict expired and, above MAX_BYTES, the oldest other snapshots."""
        path = self._path(generation)
        try:
            size = len(json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode())
        except (TypeError, ValueError):
            raise _cannot_keep() from None
        if size > MAX_BYTES:
            raise SnsError('failed', 'This comment thread is larger than the space kept for threads.',
                           'Read it with --out instead, which writes as it goes.')
        write_json(path, state, _cannot_keep)
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

    def size(self):
        """The bytes the snapshots hold (doctor reports it); None when the directory cannot be read."""
        try:
            return sum(p.stat().st_size for p in self.directory.glob('*.json') if p.is_file())
        except OSError:
            return None
