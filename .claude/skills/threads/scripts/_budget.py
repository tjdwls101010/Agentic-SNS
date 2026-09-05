"""Every HTTP hop reserves a shared slot before it can leave the process."""
import json
import math
import random
import time
from contextlib import contextmanager

from ._blocked import account_lock, cache_dir, check_blocked, write_state
from ._errors import ThreadsError

# 성진: 120 requests/10 minutes and a 1-second floor are estimates protecting a real account without rate headers; lower them if checkpoints appear.
WINDOW, WINDOW_LIMIT, MIN_GAP = 600, 120, 1.0


def history():
    try:
        values = json.loads((cache_dir() / 'budget.json').read_text())['requests']
        if not isinstance(values, list) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError
        return [v for v in values if v > time.time() - WINDOW]
    except FileNotFoundError:
        return []
    except (ValueError, KeyError, TypeError, OSError):
        raise ThreadsError(5, 'Local request history is unreadable.', 'Restore THREADS_HOME before making requests.') from None


class Budget:
    def __init__(self, max_requests=10):
        self.maximum = min(60, max_requests)
        self.used = 0

    @contextmanager
    def request(self, *, unblock=False):
        with account_lock():
            if not unblock:
                check_blocked()
            if self.used >= self.maximum:
                raise ThreadsError(8, 'This command reached its local request cap.',
                                   'Use the continuation handle later; --limit controls results, not unlimited requests.', error='budget')
            times = history()
            if len(times) >= WINDOW_LIMIT:
                raise ThreadsError(5, 'The local 10-minute request window is full.',
                                   f'No retry before {min(times) + WINDOW:.0f} (Unix time).', error='rate_limit')
            if times:
                time.sleep(max(0, max(times) + MIN_GAP + random.uniform(0, 0.5) - time.time()))
            times = history()
            times.append(time.time())
            write_state('budget.json', {'requests': times})
            self.used += 1
            yield

    def snapshot(self):
        with account_lock():
            return {'kind': 'local', 'used': self.used, 'limit': self.maximum,
                    'remaining': max(0, self.maximum - self.used), 'window_used': len(history()),
                    'window_limit': WINDOW_LIMIT, 'window_seconds': WINDOW}
