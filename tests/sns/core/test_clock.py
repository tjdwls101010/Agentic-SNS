"""The invocation clock in the suite's virtual mode (a stand-in Aside and SNS_TEST_NO_WAIT): sleeping moves time forward
without waiting, and a later command in the same data directory starts where the earlier ones left time, as real time
would (a resume right after a run cut short by its deadline must not find its own requests in the future)."""
from sns.clock import Clock


def virtual(monkeypatch, data_dir):
    monkeypatch.setenv('SNS_TEST_NO_WAIT', '1')
    monkeypatch.setenv('SNS_ASIDE_BIN', '/bin/false')
    return Clock()


def test_sleeping_moves_virtual_time_without_waiting(monkeypatch, data_dir):
    clock = virtual(monkeypatch, data_dir)
    start = clock.time()
    clock.sleep(30)
    assert clock.time() - start >= 30 and clock.slept == 30


def test_a_later_command_starts_where_earlier_ones_left_virtual_time(monkeypatch, data_dir):
    first = virtual(monkeypatch, data_dir)
    first.sleep(7)
    reached = first.time()
    assert virtual(monkeypatch, data_dir).time() >= reached - 0.05  # the mark is written at the sleep, a moment earlier


def test_against_the_real_browser_nothing_is_kept(monkeypatch, data_dir):
    monkeypatch.delenv('SNS_TEST_NO_WAIT', raising=False)
    Clock().time()
    assert not any(data_dir.glob('*clock*')) if data_dir.exists() else True
