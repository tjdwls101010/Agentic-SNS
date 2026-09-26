"""Preserve server order, explicit exhaustion and unshown page tails."""
from datetime import date, datetime
import json

from facebook.errors import FacebookError
from facebook.outcome import FIXES

# A JSON-safe local marker; never passed to Facebook as a cursor.
END = {'exhausted': True}


def in_window(record, since=None, until=None):
    if record.get('pinned') or not record.get('created_at'):
        return True
    stamp = record['created_at']
    moment = datetime.fromisoformat(stamp.replace('Z', '+00:00')) if isinstance(stamp, str) else stamp
    day = moment.astimezone().date()
    start = date.fromisoformat(since) if isinstance(since, str) else since
    end = date.fromisoformat(until) if isinstance(until, str) else until
    return (start is None or day >= start) and (end is None or day <= end)


def local_day(record):
    stamp = record['created_at']
    moment = datetime.fromisoformat(stamp.replace('Z', '+00:00')) if isinstance(stamp, str) else stamp
    return moment.astimezone().date()


def passes_boundary(records, since):
    """Whether a newest-first page reached --since: one dated, unpinned, unsponsored post older than it."""
    # 성진: 최신순=시간순 실측(피드 9/9, 그룹 15/15) 위의 정지. 순서가 어긋난 응답이 관측되면 경계 이후 한 페이지 더 확인하도록 바꾼다
    start = date.fromisoformat(since)
    return any(r.get('created_at') and not r.get('pinned') and not r.get('sponsored') and local_day(r) < start
               for r in records)


def page_options(args, state, commit):
    return dict(limit=args.limit, since=args.since, until=args.until,
                cursor=state.get('cursor'), pending=state.get('pending'),
                seen=state.get('seen'), commit=commit, page_limit=bool(args.out),
                window_closed=bool(state.get('window_closed')))


def paginate(fetch_page, *, limit=None, since=None, until=None, cursor=None, seen=None, commit=None,
             page_limit=False, pending=None, newest_first=False, window_closed=False, skip_sponsored=False,
             max_pages=None):
    """fetch_page(cursor) -> (records, page_info); commit at complete page boundaries.

    ``pending`` holds an unshown tail; ``END`` after that tail means no more requests. A newest-first read with
    --since ends its source at the first page that passes the boundary (``window_closed``). Sponsored posts are
    left out and counted once when ``skip_sponsored``. Errors keep earlier results and the cursor of the
    uncommitted page.
    """
    results, waiting = [], list(pending or [])
    identities, visited = set(seen or []), set()
    skipped = []
    pages = 0

    def committed(records, reason, page_skipped=()):
        """Commit one page; a store that cannot write ends the reading with what it has."""
        try:
            commit(records, cursor, reason, page_skipped)
        except FacebookError as error:
            return error
        return None

    def outcome(reason, *, error=None):
        result = dict(results=results, stop_reason=reason, failure=error, cursor=cursor, pending=waiting,
                      window_closed=window_closed, skipped_ids=skipped)
        if skip_sponsored:
            result['sponsored_skipped'] = len(skipped)
        return result

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
                pages += 1
            except FacebookError as error:
                if error.code == 7:
                    cursor = END
                    failed = committed([], 'exhausted') if commit else None
                    return outcome(None, error=failed) if failed else outcome('exhausted')
                return outcome(None, error=error)
            info = info or {}
            if info.get('has_next_page') is False:
                cursor = END
            elif info.get('has_next_page') is True and info.get('end_cursor'):
                cursor = info['end_cursor']
            else:
                malformed = True
            if newest_first and since and passes_boundary(records, since):
                cursor, window_closed, malformed = END, True, False
        unique, page_skipped = [], []
        for record in records:
            identity = record.get('id')
            if identity is not None and identity in identities:
                continue
            if identity is not None:
                identities.add(identity)
            if skip_sponsored and record.get('sponsored'):
                skipped.append(identity)
                page_skipped.append(identity)
                continue
            if in_window(record, since, until):
                unique.append(record)
        records = unique
        full = limit is not None and len(results) + len(records) >= limit
        reached = full or max_pages is not None and pages >= max_pages and cursor != END
        if full and not page_limit:
            room = limit - len(results)
            waiting, records = records[room:], records[:room]
        results.extend(records)
        if malformed:
            reason = None
        elif cursor == END and not waiting:
            reason = 'window_reached' if window_closed else 'exhausted'
        else:
            reason = 'limit_reached' if reached else None
        if commit and not malformed:
            failed = committed(records, reason, page_skipped)
            if failed:
                return outcome(None, error=failed)
        if malformed:
            return outcome(None, error=FacebookError(6, 'Facebook sent a page without pagination metadata.',
                                                     FIXES['pagination']))
        if reason:
            return outcome(reason)
