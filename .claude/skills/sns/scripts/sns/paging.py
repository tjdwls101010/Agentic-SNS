"""Pagination in the server's order — by cursor or by page number — with dedupe, a boundary that closes the source,
an unshown tail kept for the continuation, and the robustness stops that end a loop a server keeps feeding.

It knows nothing of a platform or of dates: fetch(cursor) returns a Page; what to keep, what to skip and what closes
the source are callbacks. The loop state a continuation carries (cursors already asked for, pages in a row with
nothing new) survives across invocations, so a server repeating itself is caught over `more:` too.
"""
import json

from sns.errors import SnsError

END = {'end': True}  # a local marker meaning "nothing more to request"; never sent as a cursor
_RETRY = 'Retry later with the more: command; this is not fixed by changing options.'


def record_key(record):
    """What a record is known by when telling repeats apart: its id, else its username, else its url."""
    if record.get('id') is not None:
        return record['id']
    if record.get('username'):
        return '@' + str(record['username']).lower()
    return record.get('url')


def _cursor_of(page):
    """The next cursor, END, or None when the page carries no usable pagination data."""
    if page.end:
        return END
    if (isinstance(page.next, str) and page.next) or (isinstance(page.next, dict) and page.next):
        return page.next
    return None


def paginate(fetch, *, limit=None, state=None, keep=None, skip=None, closes=None, commit=None, whole_pages=False,
             max_pages=None, idle_limit=2):
    """Read pages until the limit, the end, a boundary, a platform's stop or a failure.

    state: where an earlier reading stopped ({cursor, pending, seen, closed, visited, idle}). keep(record) filters what
    is shown; skip(record) leaves a record out and counts it; closes(records) ends the source after that page.
    commit(records, state, reason, skipped) is called once per complete page (--out); with whole_pages a page is never
    split at the limit. max_pages counts pages served, an unshown tail from an earlier reading included. idle_limit is
    how many fetched pages in a row may bring nothing new before reading stops.

    Returns {results, stop_reason, failure, state, skipped, pages, left_out, reported_total}; state is None when
    nothing is left to continue.
    """
    state = dict(state or {})
    cursor, waiting = state.get('cursor'), list(state.get('pending') or [])
    seen, closed = set(state.get('seen') or []), bool(state.get('closed'))
    visited, idle = set(state.get('visited') or []), int(state.get('idle') or 0)
    results, skipped, pages, served = [], [], 0, 0
    left_out, reported = {}, {'total': None}

    def snapshot():
        if cursor == END and not waiting:
            return None
        return {'cursor': cursor, 'pending': waiting, 'seen': sorted(seen, key=str), 'closed': closed,
                'visited': sorted(visited), 'idle': idle}

    def outcome(reason, failure=None):
        return {'results': results, 'stop_reason': reason, 'failure': failure, 'state': snapshot(),
                'skipped': skipped, 'pages': pages, 'left_out': left_out, 'reported_total': reported['total']}

    while True:
        damaged, stop = False, None
        if waiting:
            records, waiting, fetched = waiting, [], False
        elif cursor == END:
            return outcome('exhausted')
        elif max_pages is not None and served >= max_pages:
            return outcome('limit_reached')
        else:
            key = json.dumps(cursor, sort_keys=True)
            if key in visited:
                return outcome(None, SnsError('failed', 'The server served the same page twice.', _RETRY,
                                              reason='pagination'))
            try:
                page = fetch(cursor)
            except SnsError as error:
                return outcome(None, error)  # a page that never arrived may be asked for again
            visited.add(key)
            pages, fetched = pages + 1, True
            for label, count in (page.left_out or {}).items():
                left_out[label] = left_out.get(label, 0) + count
            if page.reported_total is not None:
                reported['total'] = page.reported_total
            records = list(page.records)
            if not records and page.unreadable:
                return outcome(None, SnsError('failed', 'A page had items this skill could not read; the platform may '
                                                        'have changed its answer.', 'Update the skill or report it.',
                                              reason='stale_query'))
            following = _cursor_of(page)
            if page.stop == 'pagination_stalled' and following not in (None, END):
                cursor, stop = following, page.stop  # a robustness stop: later reading may go on from here
            elif page.stop:
                cursor, stop = END, page.stop
            elif following is None:
                damaged = True
            else:
                cursor = following
            if closes and closes(records):
                cursor, closed, damaged = END, True, False
        served += 1
        page_records, page_skipped, fresh = [], [], 0
        for record in records:
            identity = record_key(record)
            if fetched and identity is not None:
                if identity in seen:
                    continue
                seen.add(identity)
            fresh += 1  # new to this reading, whether or not the window keeps it
            if skip and skip(record):
                page_skipped.append(identity)
                continue
            if keep is None or keep(record):
                page_records.append(record)
        skipped += page_skipped
        if fetched:
            idle = 0 if fresh or cursor == END else idle + 1
            if idle >= idle_limit:
                results.extend(page_records)
                return outcome(None, SnsError('failed', 'The server kept sending pages with nothing new, so reading '
                                                        'stopped there.', _RETRY, reason='pagination'))
        full = limit is not None and len(results) + len(page_records) >= limit
        if full and not whole_pages:
            room = limit - len(results)
            waiting, page_records = page_records[room:], page_records[:room]
        results.extend(page_records)
        if damaged:
            reason = None
        elif stop and cursor != END:
            reason = stop
        elif cursor == END and not waiting:
            reason = stop or ('window_reached' if closed else 'exhausted')
        elif full or (max_pages is not None and served >= max_pages):
            reason = 'limit_reached'
        else:
            reason = None
        if commit and not damaged:
            try:
                commit(page_records, snapshot(), reason, page_skipped)
            except SnsError as error:
                return outcome(None, error)
        if damaged:
            return outcome(None, SnsError('failed', 'The server sent a page without usable pagination data.', _RETRY,
                                          reason='pagination'))
        if reason:
            return outcome(reason)
