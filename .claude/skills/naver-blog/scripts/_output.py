"""Continuation handles and crash-resumable, page-committed NDJSON output.

Naver resumes by page number, not by a server cursor, so a handle here is a position in a
listing that may have shifted underneath it. That is why a handle also carries the records
already read but not yet displayed, and why the more: line says the boundary can move.
"""
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ._budget import cache_dir
from ._errors import NaverBlogError


def _line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


class OutFile:
    """Trust only complete page markers; an interrupted tail is replayed rather than trusted."""

    def __init__(self, path, context):
        self.path, self.context = Path(path).expanduser(), dict(context)
        self.ids, self.count, self.state, self.complete = set(), 0, None, False
        self.stream = None
        try:
            handle = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self.stream = os.fdopen(handle, 'r+b')
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._recover()
        except (OSError, ValueError, NaverBlogError) as error:
            self.close()
            if isinstance(error, NaverBlogError):
                raise
            raise NaverBlogError(2, 'Cannot open or lock the output file.',
                                 'Choose a writable file not already in use by another run.') from None

    def _recover(self):
        first = self.stream.readline()
        if not first:
            self.stream.write(_line(dict(self.context, kind='header',
                                         started_at=datetime.now(timezone.utc).isoformat(),
                                         limit_unit='records displayed; unshown page tails live in the handle')))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        try:
            header = json.loads(first)
        except ValueError:
            raise NaverBlogError(2, 'The output header is incomplete.', 'Use a new output file.') from None
        if (not isinstance(header, dict) or header.get('kind') != 'header'
                or {key: value for key, value in header.items()
                    if key not in ('kind', 'started_at', 'limit_unit')} != self.context):
            raise NaverBlogError(2, 'That output file belongs to a different query.',
                                 'Use a new file, or rerun the command it was started with.')
        boundary, page = self.stream.tell(), []
        while line := self.stream.readline():
            if not line.endswith(b'\n'):
                break
            try:
                record = json.loads(line)
            except ValueError:
                break
            if not isinstance(record, dict):
                break
            if record.get('kind') == 'page':
                identifiers = [item.get('id') for item in page]
                if record.get('ids') != identifiers or record.get('n') != len(page):
                    raise NaverBlogError(2, 'Output page integrity check failed.',
                                         'Keep this file and collect into a new path.')
                self.ids.update(value for value in identifiers if value is not None)
                self.count += len(page)
                self.state = record.get('state')
                self.complete = record.get('stop_reason') in (
                    'exhausted', 'window_reached', 'not_paginable', 'server_capped', 'pagination_stalled')
                boundary, page = self.stream.tell(), []
            else:
                page.append(record)
        self.stream.seek(boundary)
        self.stream.truncate()

    def commit(self, records, state, stop_reason):
        page, fresh = [], set()
        for record in records:
            identity = record.get('id')
            if identity is not None and (identity in self.ids or identity in fresh):
                continue
            page.append(record)
            if identity is not None:
                fresh.add(identity)
        try:
            for record in page:
                self.stream.write(_line(record))
            self.stream.write(_line(dict(kind='page', state=state, ids=[r.get('id') for r in page],
                                         n=len(page), stop_reason=stop_reason)))
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            raise NaverBlogError(8, 'Output page could not be committed.',
                                 'Free disk space and rerun the same command and file.') from None
        self.ids.update(fresh)
        self.count += len(page)
        self.state = state
        self.complete = stop_reason in ('exhausted', 'window_reached', 'not_paginable',
                                        'server_capped', 'pagination_stalled')

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class CursorStore:
    """Numbered handles bound to one query context; a handle from another query is refused."""

    def __init__(self):
        self.directory = cache_dir() / 'cursors'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def save(self, context, state):
        try:
            handle = os.open(self.directory / 'counter', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(handle, 'r+b') as counter:
                fcntl.flock(counter, fcntl.LOCK_EX)
                number = int(counter.read() or b'0') + 1
                # Persist the reservation first: an interruption leaves a gap, never a reused number.
                counter.seek(0)
                counter.write(str(number).encode())
                counter.truncate()
                counter.flush()
                os.fsync(counter.fileno())
                path = self.directory / f'{number}.json'
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                    stream.write(_line({'context': context, 'state': state,
                                        'created_at': datetime.now(timezone.utc).isoformat()}))
                    stream.flush()
                    os.fsync(stream.fileno())
                return number
        except (OSError, ValueError):
            raise NaverBlogError(8, 'Cannot save a continuation handle.',
                                 'Check the Naver Blog cache directory.') from None

    def load(self, number, context):
        try:
            data = json.loads((self.directory / f'{int(number)}.json').read_text())
        except (OSError, ValueError):
            raise NaverBlogError(2, 'That continuation handle is missing or incomplete.',
                                 'Run the original command again without --after.') from None
        if not isinstance(data, dict) or data.get('context') != context:
            # A handle is a page number into one account's view of one query; elsewhere it means nothing.
            raise NaverBlogError(2, 'That continuation handle belongs to a different query.',
                                 'Copy the whole more: line from the output you want to continue.')
        state = data.get('state')
        if (not isinstance(state, dict) or not isinstance(state.get('page'), int)
                or not isinstance(state.get('pending'), list) or not isinstance(state.get('seen'), list)):
            raise NaverBlogError(2, 'That continuation handle is malformed.',
                                 'Run the original command again without --after.')
        return state


def document(command, result, *, budget, fetched_bytes, next_command=None, sections=None):
    """One JSON document per run; namespaced ids are what --out deduplicates and resumes on."""
    payload = {'ok': result.get('ok', True), 'command': command,
               'stop_reason': result.get('stop_reason'), 'next': next_command,
               'budget': budget, 'fetched_bytes': fetched_bytes,
               'warnings': result.get('warnings') or []}
    if sections is not None:
        payload['sections'] = sections
    else:
        payload['results'] = result.get('results') or []
    for key in ('reported_total', 'reported_is_unreliable', 'context', 'shown_of',
                'out', 'saved', 'already_complete', 'error', 'message', 'fix'):
        if result.get(key) is not None:
            payload[key] = result[key]
    return payload
