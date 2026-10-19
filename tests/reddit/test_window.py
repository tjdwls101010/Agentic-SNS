"""Date windows (fixture paging.json): local-day bounds fixed when the window is made, kept across a time-zone change,
daylight-saving days, and the newest-first close."""
import os
import time

import pytest

from conftest import fixture
from reddit.window import Window

SCENARIOS = {s['name']: s for s in fixture('paging.json')['scenarios']}


@pytest.fixture
def zone(monkeypatch):
    def set_zone(name):
        monkeypatch.setenv('TZ', name)
        time.tzset()
    yield set_zone
    monkeypatch.undo()
    time.tzset()


def utc(window):
    described = window.describe()
    return [described['start_utc'], described['end_utc']]


def test_bounds_are_kept_after_the_time_zone_changes(zone):
    scenario = SCENARIOS['window-resumes-with-saved-bounds']
    zone(scenario['options']['tz'])
    made = Window('2026-10-05', '2026-10-05')
    assert utc(made) == scenario['expected']['bounds_utc'] and made.describe()['tz'] == 'KST'
    zone(scenario['options']['then_tz'])
    resumed = Window('2026-10-05', '2026-10-05', made.state())
    assert utc(resumed) == scenario['expected']['bounds_utc']
    assert utc(Window('2026-10-05', '2026-10-05')) != scenario['expected']['bounds_utc'], 'a new window would differ'


def test_a_daylight_saving_day(zone):
    scenario = SCENARIOS['window-dst-edge']
    zone(scenario['options']['tz'])
    assert utc(Window('2026-11-01', '2026-11-01')) == scenario['expected']['bounds_utc']


def test_keep_includes_the_last_day_and_excludes_the_next(zone):
    zone('Asia/Seoul')
    window = Window('2026-10-05', '2026-10-07')
    assert window.keep({'id': 'a', 'created_at': '2026-10-07T14:59:59+00:00'})       # 23:59:59 on the 7th
    assert not window.keep({'id': 'b', 'created_at': '2026-10-07T15:00:00+00:00'})   # 00:00 on the 8th
    assert window.keep({'id': 'c', 'created_at': '2026-10-04T15:00:00+00:00'})       # 00:00 on the 5th
    assert not window.keep({'id': 'd', 'created_at': None}) and window.undated == ['d']


def test_the_first_older_record_closes_unless_the_order_broke(zone):
    zone('UTC')
    window = Window('2026-10-05', None)
    page = [{'created_at': '2025-01-01T00:00:00+00:00', 'pinned': True}, {'created_at': '2026-10-06T00:00:00+00:00'},
            {'created_at': '2026-10-04T23:00:00+00:00'}]
    assert window.closes(page)
    broken = Window('2026-10-05', None)
    assert not broken.closes([{'created_at': '2026-10-04T00:00:00+00:00'}, {'created_at': '2026-10-06T00:00:00+00:00'}])
    assert broken.unordered and 'did not come newest first' in ' '.join(broken.report())
