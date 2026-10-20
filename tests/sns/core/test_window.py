"""The date window of one read (window.Window): bounds fixed at creation, what it keeps, when a page closes it."""
from datetime import datetime, timedelta, timezone

from sns.clock import KST
from sns.window import Window, WindowPolicy

UTC = timezone.utc


def at(day, hour=12, tz=UTC):
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=tz).isoformat()


def test_bounds_are_fixed_at_creation_and_carried_by_the_state():
    first = Window('2026-10-10', '2026-10-11', order='newest_first', policy=WindowPolicy(tz=KST))
    start, end = first.bounds['start'], first.bounds['end']
    assert end - start == 2 * 86400
    assert start == datetime(2026, 10, 10, tzinfo=KST).timestamp()
    later = Window('2000-01-01', None, order='newest_first', policy=WindowPolicy(tz=KST), state=first.state())
    assert later.bounds['start'] == start and later.bounds['end'] == end  # the saved span wins over new options


def test_keep_takes_the_days_inclusively_and_counts_undated_records():
    window = Window('2026-10-10', '2026-10-10', order='newest_first', policy=WindowPolicy(tz=KST))
    assert window.keep({'id': '1', 'created_at': at('2026-10-10', 0, KST)})
    assert window.keep({'id': '2', 'created_at': at('2026-10-10', 23, KST)})
    assert not window.keep({'id': '3', 'created_at': at('2026-10-11', 0, KST)})
    assert not window.keep({'id': '4', 'created_at': None})
    assert not window.keep({'id': '4', 'created_at': None})
    assert window.report() == ['1 undated record left out: no date places it in the window']


def test_an_unavailable_record_is_never_kept_by_a_window():
    window = Window('2026-10-10', None, order='newest_first')
    assert not window.keep({'id': '1', 'unavailable': True, 'created_at': at('2026-10-11')})


def test_a_newest_first_page_closes_once_a_record_is_older_than_the_start():
    window = Window('2026-10-10', None, order='newest_first', policy=WindowPolicy(tz=UTC))
    assert not window.closes([{'id': 'a', 'created_at': at('2026-10-12')}, {'id': 'b', 'created_at': at('2026-10-10')}])
    assert window.closes([{'id': 'c', 'created_at': at('2026-10-10', 1)}, {'id': 'd', 'created_at': at('2026-10-09')}])


def test_pinned_records_neither_close_nor_break_the_order():
    window = Window('2026-10-10', None, order='newest_first', policy=WindowPolicy(tz=UTC))
    page = [{'id': 'p', 'pinned': True, 'created_at': at('2020-01-01')}, {'id': 'a', 'created_at': at('2026-10-12')}]
    assert not window.closes(page) and not window.unordered


def test_an_order_break_beyond_the_jitter_means_nothing_closes_it():
    strict = Window('2026-10-10', None, order='newest_first', policy=WindowPolicy(tz=UTC))
    assert not strict.closes([{'id': 'a', 'created_at': at('2026-10-11', 10)},
                              {'id': 'b', 'created_at': at('2026-10-11', 11)}])
    assert strict.unordered
    assert not strict.closes([{'id': 'c', 'created_at': at('2026-10-01')}])
    assert 'did not come newest first' in strict.report()[0]
    loose = Window('2026-10-10', None, order='newest_first', policy=WindowPolicy(tz=UTC, jitter=600))
    late = datetime.fromisoformat(at('2026-10-11', 10)) + timedelta(seconds=300)
    assert not loose.closes([{'id': 'a', 'created_at': at('2026-10-11', 10)}, {'id': 'b', 'created_at': late.isoformat()}])
    assert not loose.unordered


def test_a_unit_is_judged_by_its_newest_record():
    window = Window('2026-10-10', None, order='newest_first', policy=WindowPolicy(tz=UTC, unit_key='unit'))
    page = [{'id': 'a', 'unit': 'u1', 'created_at': at('2026-10-09')},
            {'id': 'b', 'unit': 'u1', 'created_at': at('2026-10-11')},
            {'id': 'c', 'unit': 'u2', 'created_at': at('2026-10-10', 5)}]
    assert not window.closes(page) and not window.unordered


def test_the_order_carries_over_a_continuation():
    first = Window('2026-10-01', None, order='newest_first', policy=WindowPolicy(tz=UTC))
    first.closes([{'id': 'a', 'created_at': at('2026-10-05')}])
    later = Window('2026-10-01', None, order='newest_first', policy=WindowPolicy(tz=UTC), state=first.state())
    later.closes([{'id': 'b', 'created_at': at('2026-10-07')}])
    assert later.unordered


def test_describe_names_days_zone_and_utc_bounds():
    window = Window('2026-10-10', '2026-10-10', order='server', policy=WindowPolicy(tz=KST))
    described = window.describe()
    assert described['since'] == described['until'] == '2026-10-10' and described['tz'] == 'KST'
    assert described['start_utc'] == '2026-10-09T15:00:00+00:00' and described['end_utc'] == '2026-10-10T15:00:00+00:00'
    assert described['order'] == 'server'


def test_an_inactive_window_keeps_everything():
    window = Window(None, None, order='ranked')
    assert not window.active and window.keep({'id': '1', 'created_at': None})
