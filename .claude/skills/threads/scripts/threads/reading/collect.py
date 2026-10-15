"""Cursor progress and pending tails are independent from the request mechanism."""
import copy

from ..errors import ThreadsError, changed


def collect(fetch, *, limit, window, state=None, initial=None, commit=None):
    state = copy.deepcopy(state or {})
    state.setdefault('after', None)
    state.setdefault('pending', [])
    state.setdefault('seen', [])
    state.setdefault('done', False)
    state.setdefault('terminal', 'exhausted')
    seen, cursors = set(state['seen']), set()
    results, error, stop = [], None, None
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
            if page.has_next and not page.restarted and (page.cursor == state['after'] or page.cursor in cursors):
                raise changed('The server repeated a continuation cursor.')
            if page.cursor:
                cursors.add(page.cursor)
            records, window_reached = window.keep(page, state)
            state.update(after=page.cursor, pending=records, done=not page.has_next or window_reached,
                         terminal='window_reached' if window_reached else page.stop)
            state.update(page.state_updates)
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
