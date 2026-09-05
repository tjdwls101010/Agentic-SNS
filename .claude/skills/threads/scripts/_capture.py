"""A capture reserves all possible observed dispatches before opening its tab."""
import json
import time

from ._aside import run_snippet
from ._blocked import account_lock, cache_dir, check_blocked, set_blocked, write_state
from ._budget import WINDOW_LIMIT, history
from ._errors import ThreadsError


def capture(transport, post, targets):
    from ._refresh import CAPTURE
    from ._transport import classify
    if not post.username or not targets or any(name not in CAPTURE for name in targets):
        raise ThreadsError(2, 'Capture requires a canonical post URL and supported read-query targets.')
    with account_lock():
        check_blocked()
        times = history()
        available = min(20, transport.budget.maximum - transport.budget.used - len(targets), WINDOW_LIMIT - len(times))
        if available < 1:
            raise ThreadsError(8, 'Not enough local budget for capture plus replay.', 'Wait for the local window to clear.', error='budget')
        if times:
            time.sleep(max(0, max(times) + 1.0 - time.time()))
        write_state('capture-active.json', {'url': 'https://www.threads.com' + post.path,
                                          'started_at': time.time(), 'note': 'Cleanup not yet confirmed; inspect Aside if this marker survives.'})
        write_state('budget.json', {'requests': times + [time.time()] * available})
        transport.budget.used += available
        response = run_snippet('capture', {'url': 'https://www.threads.com' + post.path,
                                          'targets': targets, 'request_budget': available})
        transport.fetched_bytes += len(response['body'].encode())
        try:
            result = json.loads(response['body'])
            if not isinstance(result, dict):
                raise ValueError
        except (ValueError, TypeError):
            raise ThreadsError(6, 'Capture response is incomplete; its reservation and cleanup marker were retained.') from None
        count = result.get('request_count')
        complete = result.get('count_complete') is True and type(count) is int and 1 <= count <= available
        if complete:
            transport.budget.used -= available - count
            write_state('budget.json', {'requests': times + [time.time()] * count})
        if result.get('failed') != 'capture_cleanup_failed' and complete:
            (cache_dir() / 'capture-active.json').unlink(missing_ok=True)
        observations = result.get('envelopes', [])
        if not isinstance(observations, list):
            raise ThreadsError(6, 'Capture observations are malformed; no candidates were saved.')
        try:
            for envelope in observations:
                classify(envelope, 'graphql')
            classify(response, 'page')
        except ThreadsError as error:
            if error.code == 5:
                set_blocked(error.error)
            raise
        if not complete or not isinstance(result.get('queries'), list):
            raise ThreadsError(6, 'Capture count or candidates are incomplete; reservation retained.')
        return {'queries': result['queries'], 'missing': {name: result.get('failed') or 'Not observed after bounded SPA actions; Relay may already cache this surface.'
                for name in targets if not any(q.get('name') == name for q in result['queries'])},
                'observed_requests': count - 1, 'bootstrap_count_known': False, 'app_mutations_possible': True,
                'cleanup_confirmed': result.get('failed') != 'capture_cleanup_failed',
                'attempts': result.get('attempts', []), 'failed': result.get('failed')}
