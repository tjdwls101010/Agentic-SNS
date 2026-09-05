import json

import pytest

from threads_skill._capture import capture
from threads_skill._transport import Transport
from threads_skill._target import parse_target
from threads_skill._blocked import cache_dir, check_blocked
from threads_skill._errors import ThreadsError


def test_capture_preserves_unknown_reservation_and_marker_on_bridge_loss(monkeypatch):
    from threads_skill import _capture
    def lost(*args):
        raise ThreadsError(3, 'Browser bridge lost')
    monkeypatch.setattr(_capture, 'run_snippet', lost)
    transport = Transport(10)
    with pytest.raises(ThreadsError):
        capture(transport, parse_target('/@fixture/post/FIX', 'post'), ['BarcelonaFriendshipsFollowersTabQuery'])
    assert transport.budget.snapshot()['used'] > 0
    assert (cache_dir() / 'capture-active.json').exists()


def test_capture_block_is_persisted_before_returning_any_candidates(monkeypatch):
    from threads_skill import _capture
    result = {'queries': [], 'missing': [], 'request_count': 2, 'count_complete': True,
              'failed': 'capture_blocked', 'envelopes': [{'status': 429, 'url': 'https://www.threads.com/checkpoint/',
                                                       'body': '{"error_code":"368"}'}]}
    monkeypatch.setattr(_capture, 'run_snippet', lambda *args: {'status': 429,
        'url': 'https://www.threads.com/checkpoint/', 'body': json.dumps(result)})
    with pytest.raises(ThreadsError):
        capture(Transport(10), parse_target('/@fixture/post/FIX', 'post'), ['BarcelonaFriendshipsFollowersTabQuery'])
    with pytest.raises(ThreadsError) as error:
        check_blocked()
    assert error.value.error == 'checkpoint'
