"""Cursor pagination in the server's order: dedupe, a boundary that closes the source, an unshown tail, cursor repeats.

It knows nothing of Facebook or of dates: what to keep, what to skip and what closes the source are callbacks.
"""
import json

from facebook.errors import FacebookError

END = {'end': True}  # a local marker meaning "nothing more to request"; never sent as a cursor
_RETRY = 'Retry later with the more: command; this is not fixed by changing options.'


def paginate(fetch, *, limit=None, state=None, keep=None, skip=None, closes=None, commit=None, whole_pages=False,
             max_pages=None):
    """Read pages until the limit, the end, a boundary or a failure.

    fetch(cursor) -> (records, page_info, has_items). state is where an earlier reading stopped ({cursor, pending,
    seen, closed}). keep(record) filters what is shown; skip(record) leaves a record out and counts it (its id is
    remembered so a continuation does not count it again); closes(records) ends the source after that page.
    commit(records, state, reason, skipped) is called once per complete page (for --out); with whole_pages a page is
    never split at the limit. max_pages counts pages served, an unshown tail from an earlier reading included. Returns {results, stop_reason, failure, state, skipped, pages}; state is None when
    nothing is left to continue.
    """
    state = dict(state or {})
    cursor, waiting = state.get('cursor'), list(state.get('pending') or [])
    seen, closed = set(state.get('seen') or []), bool(state.get('closed'))
    results, skipped, visited, pages, served = [], [], set(), 0, 0
    idle = 0  # consecutive fetched pages that brought no record not seen before

    def snapshot():
        if cursor == END and not waiting:
            return None
        return {'cursor': cursor, 'pending': waiting, 'seen': sorted(seen, key=str), 'closed': closed}

    def outcome(reason, failure=None):
        return {'results': results, 'stop_reason': reason, 'failure': failure, 'state': snapshot(),
                'skipped': skipped, 'pages': pages}

    while True:
        damaged = False
        if waiting:
            records, waiting, fetched = waiting, [], False
        elif cursor == END:
            return outcome('exhausted')
        elif max_pages is not None and served >= max_pages:
            return outcome('limit_reached')
        else:
            key = json.dumps(cursor, sort_keys=True)
            if key in visited:
                return outcome(None, FacebookError(6, 'Facebook served the same page cursor twice.', _RETRY,
                                                   reason='pagination'))
            visited.add(key)
            try:
                records, info, has_items = fetch(cursor)
            except FacebookError as error:
                return outcome(None, error)
            pages, fetched = pages + 1, True
            if not records and has_items:
                return outcome(None, FacebookError(6, 'A page had items this skill could not read; Facebook may have '
                                                      'changed the response.', 'Update the skill or report it.',
                                                   reason='stale_query'))
            info = info if isinstance(info, dict) else {}
            if info.get('has_next_page') is False:
                cursor = END
            elif info.get('has_next_page') is True and isinstance(info.get('end_cursor'), str) and info['end_cursor']:
                cursor = info['end_cursor']
            else:
                damaged = True
            if closes and closes(records):
                cursor, closed, damaged = END, True, False
        served += 1
        page, page_skipped = [], []
        for record in records:
            identity = record.get('id')
            if fetched and identity is not None:
                if identity in seen:
                    continue
                seen.add(identity)
            if skip and skip(record):
                page_skipped.append(identity)
                continue
            if keep is None or keep(record):
                page.append(record)
        skipped += page_skipped
        if fetched:
            fresh_ids = len(page) + len(page_skipped) + sum(1 for r in records if r.get('id') is None)
            idle = 0 if fresh_ids or cursor == END else idle + 1
            if idle >= 2:
                results.extend(page)
                return outcome(None, FacebookError(6, 'Facebook kept sending pages with nothing new, so reading '
                                                      'stopped there.', _RETRY, reason='pagination'))
        full = limit is not None and len(results) + len(page) >= limit
        if full and not whole_pages:
            room = limit - len(results)
            waiting, page = page[room:], page[:room]
        results.extend(page)
        if damaged:
            reason = None
        elif cursor == END and not waiting:
            reason = 'window_reached' if closed else 'exhausted'
        elif full or (max_pages is not None and served >= max_pages):
            reason = 'limit_reached'
        else:
            reason = None
        if commit and not damaged:
            try:
                commit(page, snapshot(), reason, page_skipped)
            except FacebookError as error:
                return outcome(None, error)
        if damaged:
            return outcome(None, FacebookError(6, 'Facebook sent a page without usable pagination data.', _RETRY,
                                               reason='pagination'))
        if reason:
            return outcome(reason)
