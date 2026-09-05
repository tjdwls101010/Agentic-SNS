"""Reserve before requesting; authoritative headers replace the reservation."""
import random
import time
from ._blocked import read_state, write_state
from ._errors import TwitterError


class Budget:
    def __init__(self, maximum=10, clock=time.time, sleep=time.sleep, jitter=lambda: random.uniform(0, .5)):
        self.maximum, self.used = maximum, 0
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.operations = {}

    def reserve(self, query_id=None):
        now = self.clock()
        state = read_state('budget.json')
        if block := state.get('block'):
            raise TwitterError(5, 'X requests are blocked.', 'Check x.com in Aside, then run doctor --unblock.', block['reason'])
        if self.used >= self.maximum:
            raise TwitterError(8, 'This invocation reached its request budget.', 'Continue using the more: handle.', 'budget')
        requests = [t for t in state.get('requests', []) if t > now - 600]
        if len(requests) >= 200:
            raise TwitterError(5, 'Account request window is full.', f'Wait until {requests[0] + 600:.0f} (Unix time); do not retry now.', 'window')
        buckets = {k: v for k, v in state.get('buckets', {}).items() if v['reset_at'] > now}
        bucket = buckets.get(query_id)
        if bucket and bucket['remaining'] <= 0:
            raise TwitterError(5, 'Operation rate limit reached.', f'Wait until {bucket["reset_at"]:.0f} (Unix time); do not retry now.', 'rate_limit')
        # 성진: 1 second minimum and 20% slowdown are account-protection estimates; lower request frequency if locks occur.
        interval = 1 + self.jitter()
        if bucket and bucket['remaining'] < bucket['limit'] * .2:
            interval = max(interval, (bucket['reset_at'] - now) / bucket['remaining'])
        if requests:
            self.sleep(max(0, requests[-1] + interval - now))
        now = self.clock()
        requests = [t for t in requests if t > now - 600]
        if bucket:
            bucket['remaining'] -= 1
        state.update(requests=[*requests, now], buckets=buckets)
        write_state('budget.json', state)
        self.used += 1

    def observe(self, query_id, headers, status=200, operation=None):
        state = read_state('budget.json')
        buckets = state.setdefault('buckets', {})
        try:
            limit, remaining, reset = (int(headers[k]) for k in ('limit', 'remaining', 'reset'))
            buckets[query_id] = dict(limit=limit, remaining=remaining, reset_at=reset, observed_at=self.clock())
        except (KeyError, TypeError, ValueError):
            pass
        if status == 429:
            bucket = buckets.setdefault(query_id, dict(limit=0, remaining=0, reset_at=self.clock() + 900))
            bucket['remaining'] = 0
            if bucket['reset_at'] <= self.clock():
                bucket['reset_at'] = self.clock() + 900
        write_state('budget.json', state)
        if operation:
            self.operations[operation] = buckets.get(query_id, {})

    def summary(self):
        state = read_state('budget.json')
        return dict(operations=self.operations, window=sum(t > self.clock() - 600 for t in state.get('requests', [])), requests=self.used)
