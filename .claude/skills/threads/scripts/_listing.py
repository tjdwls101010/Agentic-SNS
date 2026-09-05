"""Cursor progress and pending tails are independent from the request mechanism."""
import copy
from datetime import datetime, timezone

from ._errors import ThreadsError


def date_bound(value):
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, AttributeError):
        raise ThreadsError(2, 'Dates must be ISO dates or date-times; dates without offsets use UTC.') from None


def collect(fetch, *, limit, state=None, initial=None, since=None, until=None, monotonic=False, commit=None):
    state = copy.deepcopy(state or {})
    state.setdefault('after', None)
    state.setdefault('pending', [])
    state.setdefault('seen', [])
    state.setdefault('done', False)
    state.setdefault('terminal', 'exhausted')
    seen, cursors = set(state['seen']), set()
    results, error, stop = [], None, None
    lower, upper = date_bound(since), date_bound(until)
    if lower is not None and upper is not None and lower >= upper:
        raise ThreadsError(2, '--since must be earlier than --until.')
    while True:
        emitted = []
        while state['pending'] and len(results) < limit:
            record = state['pending'].pop(0)
            identity = record.get('id')
            if identity is not None and identity in seen:
                continue
            if identity is not None:
                seen.add(identity)
            results.append(record)
            emitted.append(record)
        state['seen'] = sorted(seen)
        if not state['pending'] and state['done']:
            stop = state['terminal']
        elif len(results) >= limit:
            stop = state['terminal'] if state['done'] and state['terminal'] in ('server_capped', 'not_paginable') else 'limit_reached'
        if commit and (emitted or stop):
            commit(emitted, copy.deepcopy(state), stop or 'page')
        if stop:
            break
        try:
            page = initial if initial is not None else fetch(state['after'])
            initial = None
            if page.has_next and (page.cursor == state['after'] or page.cursor in cursors):
                raise ThreadsError(6, 'The server repeated a continuation cursor.', 'Run refresh.', error='envelope_drift')
            if page.cursor:
                cursors.add(page.cursor)
            records = page.records
            window_reached = False
            if lower is not None or upper is not None:
                stamps = [date_bound(p.get('created_at')) for p in records]
                records = [p for p, stamp in zip(records, stamps) if stamp is not None
                           and (lower is None or stamp >= lower) and (upper is None or stamp < upper)]
                activity = []
                unknown = False
                for group in page.groups:
                    if any(p.get('is_pinned') for p in group):
                        continue
                    times = [date_bound(p.get('created_at')) for p in group]
                    if not times or any(t is None for t in times):
                        unknown = True
                    else:
                        activity.append(max(times))
                previous = state.get('last_activity')
                ordered = all(a >= b for a, b in zip(activity, activity[1:]))
                if previous is not None and activity and activity[0] > previous:
                    ordered = False
                state['unordered'] = state.get('unordered', False) or not ordered or unknown
                if activity:
                    state['last_activity'] = activity[-1]
                window_reached = bool(monotonic and lower is not None and activity and max(activity) < lower
                                      and not state['unordered'])
            state.update(after=page.cursor, pending=records, done=not page.has_next or window_reached,
                         terminal='window_reached' if window_reached else page.stop)
            if page.reported_total is not None:
                state['reported_total'] = page.reported_total
            if commit and not records:
                commit([], copy.deepcopy(state), state['terminal'] if state['done'] else 'page')
        except ThreadsError as exc:
            error = exc
            stop = 'blocked' if exc.code in (4, 5) else 'budget' if exc.error == 'budget' else 'query_failure'
            break
    code = 0
    if error:
        code = error.code if error.code in (4, 5) or not results else 8
    elif not results and stop in ('exhausted', 'window_reached', 'server_capped', 'not_paginable'):
        code = 7
    return {'ok': error is None, 'results': results, 'stop_reason': stop, 'state': state, 'code': code,
            **({'error': error.error, 'message': error.message, 'fix': error.fix} if error else {})}
