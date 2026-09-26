"""Preserve server order, explicit exhaustion and unshown page tails."""
from datetime import date, datetime
import json

from facebook.errors import FacebookError
from facebook.outcome import FIXES

# A JSON-safe local marker; never passed to Facebook as a cursor.
END = {'exhausted': True}


def in_window(record, since=None, until=None):
    if record.get('pinned') or record.get('is_pinned') or not record.get('created_at'):
        return True
    stamp = record['created_at']
    moment = datetime.fromisoformat(stamp.replace('Z', '+00:00')) if isinstance(stamp, str) else stamp
    day = moment.astimezone().date()
    start = date.fromisoformat(since) if isinstance(since, str) else since
    end = date.fromisoformat(until) if isinstance(until, str) else until
    return (start is None or day >= start) and (end is None or day <= end)


def page_options(args, state, commit):
    return dict(limit=args.limit, since=args.since, until=args.until,
                cursor=state.get('cursor'), pending=state.get('pending'),
                seen=state.get('seen'), commit=commit, page_limit=bool(args.out))


def paginate(fetch_page, *, limit=None, since=None, until=None, cursor=None,
             seen=None, commit=None, page_limit=False, pending=None):
    """fetch_page(cursor) -> (records, page_info); commit at complete page boundaries.

    ``pending`` holds an unshown tail; ``END`` after that tail means no more requests.
    Errors retain earlier results and the cursor of the uncommitted page.
    """
    results, waiting = [], list(pending or [])
    identities, visited = set(seen or []), set()

    def outcome(reason, *, error=None):
        return dict(results=results, stop_reason=reason, failure=error, cursor=cursor, pending=waiting)

    while True:
        malformed = False
        if waiting:
            records, waiting = waiting, []
        elif cursor == END:
            return outcome('exhausted')
        else:
            key = json.dumps(cursor, sort_keys=True)
            if key in visited:
                return outcome(None, error=FacebookError(6, 'Facebook repeated a page cursor.', FIXES['pagination']))
            visited.add(key)
            try:
                records, info = fetch_page(cursor)
            except FacebookError as error:
                if error.code == 7:
                    cursor = END
                    if commit:
                        commit([], cursor, 'exhausted')
                    return outcome('exhausted')
                return outcome(None, error=error)
            info = info or {}
            if info.get('has_next_page') is False:
                cursor = END
            elif info.get('has_next_page') is True and info.get('end_cursor'):
                cursor = info['end_cursor']
            else:
                malformed = True
        unique = []
        for record in records:
            identity = record.get('id')
            if identity is not None and identity in identities:
                continue
            if identity is not None:
                identities.add(identity)
            if in_window(record, since, until):
                unique.append(record)
        records = unique
        reached = limit is not None and len(results) + len(records) >= limit
        if reached and not page_limit:
            room = limit - len(results)
            waiting, records = records[room:], records[:room]
        results.extend(records)
        reason = None if malformed else 'limit_reached' if reached else 'exhausted' if cursor == END else None
        if commit and not malformed:
            commit(records, cursor, reason)
        if malformed:
            return outcome(None, error=FacebookError(6, 'Facebook sent a page without pagination metadata.',
                                                     FIXES['pagination']))
        if reason:
            return outcome(reason)
