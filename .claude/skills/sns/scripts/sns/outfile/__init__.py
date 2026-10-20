"""--out files: NDJSON committed a whole page at a time, so an interrupted collection resumes where it stopped.

Line 1 is a header (kind header, format, platform, the query context, the platform account that read it, started_at).
Then records, each page closed by a marker (kind page, the state to resume from, ids and n of the records above it,
stop_reason, skipped, coverage). The last marker says how the file's last run ended:
- end "final": a judgment rereading would not change (the source ended, the window closed, the platform had nothing,
  the listing ended before the window); its verdict and window are kept and a rerun repeats them without a request;
- end "interrupted": a failure, a time limit or a stop; a rerun reads on from the saved state.
Only complete pages are trusted: the tail after the last marker is dropped and read again. A file for another query,
another account or an older format is refused before any byte changes. The file is the user's own: it must be a
regular file with one link, opened without following a final symbolic link, kept private (0600) and locked without
waiting; a path through a symbolic link on the way is followed and the result names the resolved path.
"""
import fcntl
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from sns.errors import SnsError
from sns.paths import outside_data

FORMAT = 1
COMPLETE = ('exhausted', 'window_reached', 'not_paginable', 'server_capped')
VERDICT_KINDS = ('empty', 'partial', 'unavailable')


def _line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def resolve(path):
    """The path with ~ and every symbolic link before its last part resolved (the last part is never followed)."""
    path = Path(path).expanduser()
    return Path(os.path.realpath(path.parent)) / path.name


def check_path(path):
    """Refuse, before any request, a path inside the skill's data/ or one that cannot be written."""
    outside_data(path)
    target = resolve(path)
    if not target.parent.is_dir():
        raise SnsError('argument', f'The --out directory {target.parent} does not exist.',
                       'Create it first, or pass a path in an existing directory; the skill does not create it.')
    if target.exists() and not os.access(target, os.W_OK):
        raise SnsError('argument', f'The --out file {target} is not writable.', 'Pass a path you can write.')
    if not target.exists() and not os.access(target.parent, os.W_OK | os.X_OK):
        raise SnsError('argument', f'The --out directory {target.parent} is not writable.', 'Pass a path you can '
                                                                                           'write.')


def describe():
    """The --out file schema."""
    return {
        'object': 'out',
        'description': 'The NDJSON file --out writes: one header, then records, each page closed by a page line.',
        'format': FORMAT,
        'lines': {
            'header': 'first line: kind "header", format, platform, context (platform, command, target, identity, the '
                      'Aside account), viewer (the platform account that read it), started_at',
            'record': 'one record of the command (see schema <object>); a thread file holds the post once, then its '
                      'replies or comments flat, each with parent_id and depth',
            'page': 'after each committed page: kind "page" with no id, state (where the next page starts), ids and n '
                    'of the records above it, stop_reason, skipped, coverage; the last one says how the file\'s last '
                    'run ended: end "final" with verdict {kind, message, fix, reason} (null for a plain success) and '
                    'window — a judgment a rerun repeats without a request — or end "interrupted" with the stop '
                    'reason, which a rerun continues from',
        },
        'resume': 'Rerun the same command with the same --out path: records after the last page line are dropped and '
                  'read again, saved ids are not written twice, and --limit counts what is saved. A final file reads '
                  'nothing and repeats its result. A file for another query, another account, an earlier format or '
                  'one whose pages do not match their records is refused before any byte changes; use a new path.',
        'privacy': 'The file holds other people\'s names, words and profile links. Keep it outside the repository.',
    }


def _verdict_ok(verdict):
    return verdict is None or (isinstance(verdict, dict) and verdict.get('kind') in VERDICT_KINDS
                               and all(isinstance(verdict.get(k), str) for k in ('message', 'fix'))
                               and isinstance(verdict.get('reason'), (str, type(None))))


def _scan(data):
    """What a file's bytes hold: its header, the committed pages, and where the trusted part ends."""
    lines = data.split(b'\n')
    try:
        header = json.loads(lines[0]) if len(lines) > 1 else None  # a header without its newline is incomplete
    except ValueError:
        header = None
    result = {'header': header, 'ids': set(), 'skipped': set(), 'count': 0, 'state': None, 'complete': False,
              'conclusion': None, 'last_stop': None, 'boundary': len(lines[0]) + 1}
    offset, page, broken = len(lines[0]) + 1, [], False
    for raw in lines[1:-1]:  # the last element follows the final newline: empty, or a partial line
        offset += len(raw) + 1
        try:
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError
        except ValueError:
            broken = True
            continue
        if record.get('kind') == 'page' and 'id' not in record:
            page_ids = [r.get('id') for r in page]
            named = [i for i in page_ids if i is not None]
            if broken or record.get('ids') != page_ids or record.get('n') != len(page) or \
                    len(set(named)) != len(named) or result['ids'] & set(named):
                raise SnsError('argument', 'The --out file failed its integrity check: a page line does not match the '
                                           'records above it.', 'Keep this file as it is and use a new path.')
            if record.get('end') not in (None, 'final', 'interrupted') or not _verdict_ok(record.get('verdict')) or \
                    not isinstance(record.get('window'), (dict, type(None))):
                raise SnsError('argument', 'The --out file failed its integrity check: a page line\'s ending is '
                                           'damaged.', 'Keep this file as it is and use a new path.')
            result['ids'].update(named)
            result['skipped'].update(record.get('skipped') or [])
            result['count'] += len(page)
            result['state'] = record.get('state')
            result['complete'] = record.get('end') == 'final'
            result['conclusion'] = {'stop_reason': record.get('stop_reason'), 'verdict': record.get('verdict'),
                                    'window': record.get('window')} if result['complete'] else None
            result['last_stop'] = record.get('stop_reason')
            result['boundary'], page = offset, []
        elif not broken:
            page.append(record)
    return result


def _check_header(header, context, viewer, strict):
    if not isinstance(header, dict) or header.get('kind') != 'header':
        raise SnsError('argument', 'The --out file is not a collection written by this skill.', 'Use a new --out path.')
    if header.get('format') != FORMAT or 'platform' not in header:
        raise SnsError('argument', 'The --out file was written by an earlier version of this skill.',
                       'Use a new --out path; the old file is left as it was.')
    if not isinstance(header.get('context'), dict):
        raise SnsError('argument', 'The --out file\'s header names no query.', 'Use a new --out path.')
    if context is None:
        return
    if header['context'] != context:
        raise SnsError('argument', 'The --out file belongs to another command, target, order, window or account.',
                       'Use a new --out path, or rerun the command that started this file.')
    if strict and header.get('viewer') != viewer:
        raise SnsError('login', f'The --out file was read as {header.get("viewer")}, but the browser is now logged in '
                                f'as {viewer}.', 'Use a new --out path to read as the current account.',
                       reason='account_changed')


def _open(path, flags):
    """A descriptor for the file itself: never through a final symbolic link, a regular file with one link, 0600."""
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except FileNotFoundError:
        raise
    except OSError:
        raise SnsError('argument', 'Cannot open the --out file (a symbolic link is refused).',
                       'Choose a regular file path.') from None
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise SnsError('argument', 'The --out path must be a regular file with no other links.',
                       'Choose a new file path.')
    if flags & (os.O_RDWR | os.O_WRONLY):
        os.fchmod(fd, 0o600)
    return fd


def peek(path):
    """What a file says without changing it — {context, viewer, platform, complete, count, conclusion, last_stop} —
    or None when there is no file or it is empty. A file that is not a current collection raises like opening it."""
    try:
        with os.fdopen(_open(resolve(path), os.O_RDONLY), 'rb') as stream:
            data = stream.read()
    except FileNotFoundError:
        return None
    if not data:
        return None
    scan = _scan(data)
    _check_header(scan['header'], None, None, False)
    header = scan['header']
    return {'context': header['context'], 'viewer': header.get('viewer'), 'platform': header.get('platform'),
            'complete': scan['complete'], 'count': scan['count'], 'conclusion': scan['conclusion'],
            'last_stop': scan['last_stop']}


class OutFile:
    """One --out file opened for one query context and platform account; the lock is held until close()."""

    def __init__(self, path, context, viewer=None):
        self.path, self.context, self.viewer = resolve(path), context, viewer
        self.ids, self.skipped = set(), set()
        self.count = 0
        self.state, self.complete, self.last_stop = None, False, None
        self.stream = None
        try:
            self.stream = os.fdopen(_open(self.path, os.O_RDWR | os.O_CREAT), 'r+b')
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except SnsError:
            self.close()
            raise
        except OSError:
            self.close()
            raise SnsError('argument', 'Cannot open or lock the --out file.',
                           'Choose a writable path that no other command is writing.') from None
        try:
            self._recover()
        except SnsError:
            self.close()
            raise
        except (OSError, ValueError):
            self.close()
            raise SnsError('argument', 'Cannot read the --out file.', 'Use a new --out path.') from None

    def _recover(self):
        data = self.stream.read()
        if not data:
            self._write([{'kind': 'header', 'format': FORMAT, 'platform': self.context.get('platform'),
                          'context': self.context, 'viewer': self.viewer,
                          'started_at': datetime.now(timezone.utc).isoformat()}])
            return
        scan = _scan(data)
        _check_header(scan['header'], self.context, self.viewer, True)
        self.ids, self.skipped, self.count = scan['ids'], scan['skipped'], scan['count']
        self.state, self.complete, self.last_stop = scan['state'], scan['complete'], scan['last_stop']
        self.stream.seek(scan['boundary'])
        self.stream.truncate()

    def _write(self, values):
        try:
            for value in values:
                self.stream.write(_line(value))
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            raise SnsError('failed', 'A page could not be written to the --out file.',
                           'Free disk space, then rerun the same command to resume.') from None

    def commit(self, records, state, stop_reason, skipped=(), notes=()):
        """Append one page and its marker, fsynced; records whose id is already saved are left out. Records are flat:
        a nested replies tree is refused (each reply is its own record with parent_id)."""
        page, new = [], set()
        for record in records:
            if 'replies' in record and isinstance(record['replies'], list):
                raise SnsError('failed', 'A nested record cannot be saved to an --out file.',
                               'Report this as a skill bug.')
            identity = record.get('id')
            if identity is not None and (identity in self.ids or identity in new):
                continue
            page.append(record)
            if identity is not None:
                new.add(identity)
        marker = {'kind': 'page', 'state': state, 'ids': [r.get('id') for r in page], 'n': len(page),
                  'stop_reason': stop_reason}
        if skipped:
            marker['skipped'] = list(skipped)
        if notes:
            marker['coverage'] = list(notes)
        self._write([*page, marker])
        self.ids |= new
        self.skipped |= set(skipped)
        self.count += len(page)
        self.state, self.last_stop = state, stop_reason

    def conclude(self, stop_reason, verdict, window):
        """Mark the file final with the result its reading ended in (verdict {kind, message, fix, reason} or None for
        a plain success, and the window), so rerunning the command repeats it without a request."""
        if not _verdict_ok(verdict):
            raise ValueError(verdict)
        self._write([{'kind': 'page', 'state': self.state, 'ids': [], 'n': 0, 'stop_reason': stop_reason,
                      'end': 'final', 'verdict': verdict, 'window': window}])
        self.complete = True

    def interrupt(self, stop_reason):
        """Say why the run stopped before the source's end (a failure, the time limit, a limit's stop); a rerun reads
        on from the last saved state."""
        self._write([{'kind': 'page', 'state': self.state, 'ids': [], 'n': 0, 'stop_reason': stop_reason,
                      'end': 'interrupted'}])

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
