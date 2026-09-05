"""Preserve server order, explicit exhaustion and unshown page tails."""
from datetime import date, datetime
import json

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


def find_page_info(raw, connection_key):
    """Read only this connection's inline or path-addressed deferred metadata."""
    def walk(obj):
        if isinstance(obj, dict):
            connection = obj.get(connection_key)
            if isinstance(connection, dict) and isinstance(connection.get('page_info'), dict):
                return connection['page_info']
            for value in obj.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = walk(value)
                if found is not None:
                    return found
        return None
    from _transport import iter_chunks
    found = None
    for chunk in iter_chunks(raw):
        path, data = chunk.get('path'), chunk.get('data')
        if isinstance(path, list) and path and path[-1] == connection_key and isinstance(data, dict):
            if isinstance(data.get('page_info'), dict):
                found = data['page_info']
        found = walk(data) or found
    return found


def connection_has_items(raw, key):
    """Distinguish an empty continuation page from nonempty data a model could not parse."""
    from _transport import iter_chunks
    for chunk in iter_chunks(raw):
        path = chunk.get('path') or []
        data = chunk.get('data')
        if path and path[-1] == key and isinstance(data, dict) and (data.get('edges') or data.get('nodes')):
            return True
        if key in path and any(part in ('edges', 'nodes') for part in path) and chunk.get('data'):
            return True
        stack = [chunk.get('data')]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                connection = item.get(key)
                if isinstance(connection, dict) and (connection.get('edges') or connection.get('nodes')):
                    return True
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return False


def paginate(fetch_page, *, limit=None, since=None, until=None, cursor=None,
             seen=None, commit=None, page_limit=False, pending=None):
    """fetch_page(cursor) -> (records, page_info); commit at complete page boundaries.

    ``pending`` holds an unshown tail; ``END`` after that tail means no more requests.
    Errors retain earlier results and the cursor of the uncommitted page.
    """
    from _errors import FacebookError
    results, waiting = [], list(pending or [])
    identities, visited = set(seen or []), set()

    def outcome(reason, *, error=None):
        result = dict(ok=error is None, results=results, stop_reason=reason,
                      cursor=cursor, pending=waiting)
        if error is not None:
            result.update(error='partial' if results else 'query_failure',
                          message=error.message, fix=error.fix, code=error.code)
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
                return outcome('query_failure', error=FacebookError(6, 'The server repeated a cursor.'))
            visited.add(key)
            try:
                records, info = fetch_page(cursor)
            except FacebookError as error:
                if error.code == 7:
                    cursor = END
                    if commit:
                        commit([], cursor, 'exhausted')
                    return outcome('exhausted')
                reason = 'blocked' if error.code == 5 else 'budget' if error.code == 8 else 'query_failure'
                return outcome(reason, error=error)
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
        reason = 'query_failure' if malformed else 'limit_reached' if reached else 'exhausted' if cursor == END else None
        if commit and not malformed:
            commit(records, cursor, reason)
        if malformed:
            return outcome('query_failure', error=FacebookError(6, 'Missing explicit pagination metadata.'))
        if reason:
            return outcome(reason)
