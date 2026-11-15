"""Whole results kept as files under <state>/results/<n>.json for about a day, so a result a reader cut short (a long
text, a tool's output limit) can be read again from disk without asking the platform again.

A file is the --json envelope of one read, its own path included as `saved`. Numbers are reserved under a lock and
never reused, like handles. A file more than a day old is removed by the next read command, whatever it finds (and by the
idle cleanup) — not at the hour: if the skill is not used again, it stays until it is. A file holds other people's posts.
"""
import fcntl
import json
import os
import time

from sns.errors import SnsError
from sns.paths import shared

TTL_SECONDS = 24 * 3600
_FAILED = 'the whole result could not be saved to a file; it is only in this output'


def _directory():
    return shared('results')


def prune():
    """Remove result files more than a day old (never the counter)."""
    try:
        directory = _directory()
        cutoff = time.time() - TTL_SECONDS
        for path in directory.glob('*.json'):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
    except (OSError, SnsError):
        pass


def keep(envelope):
    """Write `envelope` to a new result file after putting its path in envelope['saved'] (day-old files are pruned when
    the read starts, see reading.pipeline.run); when it cannot be written,
    envelope['saved'] is 'unavailable' and a coverage line says so (the read itself stands). Returns the envelope."""
    path, created = None, False
    try:
        directory = _directory()
        with open(directory / 'counter', 'a+b') as counter:
            fcntl.flock(counter, fcntl.LOCK_EX)
            counter.seek(0)
            # above the counter and above every file there, so a lost or emptied counter never reuses a number
            highest = max((int(p.stem) for p in directory.glob('*.json') if p.stem.isdigit()), default=0)
            number = max(int(counter.read().strip() or b'0'), highest) + 1
            counter.seek(0)
            counter.truncate()
            counter.write(str(number).encode())
            counter.flush()
            os.fsync(counter.fileno())
        path = directory / f'{number}.json'
        envelope['saved'] = str(path)
        text = json.dumps(envelope, ensure_ascii=False, indent=1)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True  # from here a failure leaves a file of this call's own, which goes
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError, TypeError, SnsError):
        if created:
            try:
                path.unlink()  # a file written in part is not the result it would name
            except OSError:
                pass
        envelope['saved'] = 'unavailable'
        envelope['coverage'] = [*(envelope.get('coverage') or []), _FAILED]
    return envelope
