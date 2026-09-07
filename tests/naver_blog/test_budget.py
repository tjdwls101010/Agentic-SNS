"""A slot is spent when it is reserved, not when the response comes back."""
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from naver_blog_skill import _budget
from naver_blog_skill._budget import Budget, cache_dir, check_blocked, clear_blocked, history, set_blocked
from naver_blog_skill._errors import NaverBlogError

SCRIPTS = Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts'


def test_a_reservation_survives_a_process_that_dies_before_the_response(monkeypatch, tmp_path):
    """Naver counts the request it received; a crash must not hand the slot back."""
    home = tmp_path / 'home'
    monkeypatch.setenv('NAVER_BLOG_HOME', str(home))
    monkeypatch.setenv('NAVER_BLOG_NO_PACING', '1')
    with pytest.raises(RuntimeError):
        with Budget(5).request():
            raise RuntimeError('the browser hung up mid-flight')
    assert len(history()) == 1


def test_two_processes_share_one_ten_minute_window(tmp_path):
    home = tmp_path / 'home'
    program = textwrap.dedent(f'''
        import sys; sys.path.insert(0, {str(SCRIPTS.parent)!r})
        from scripts._budget import Budget, history
        with Budget(5).request():
            pass
        print(len(history()))
    ''')
    environment = dict(os.environ, NAVER_BLOG_HOME=str(home), NAVER_BLOG_NO_PACING='1')
    counts = [subprocess.run([sys.executable, '-c', program], capture_output=True, text=True,
                             env=environment).stdout.strip() for _ in range(3)]
    assert counts == ['1', '2', '3']


def test_a_full_window_refuses_before_any_request_leaves(monkeypatch, tmp_path):
    monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NAVER_BLOG_NO_PACING', '1')
    now = time.time()
    (tmp_path / 'home').mkdir(parents=True)
    (tmp_path / 'home/budget.json').write_text(json.dumps({'requests': [now] * _budget.WINDOW_LIMIT}))
    budget = Budget(10)
    with pytest.raises(NaverBlogError) as caught:
        with budget.request():
            pytest.fail('the request body must not run')
    assert caught.value.code == 5 and budget.used == 0


def test_the_per_command_cap_is_partial_rather_than_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NAVER_BLOG_NO_PACING', '1')
    budget = Budget(40)
    for _ in range(40):
        with budget.request():
            pass
    with pytest.raises(NaverBlogError) as caught:
        with budget.request():
            pass
    assert caught.value.code == 8 and caught.value.error == 'budget'


def test_the_absolute_cap_holds_even_when_a_command_asks_for_more(monkeypatch, tmp_path):
    monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'home'))
    assert Budget(500).maximum == 60


def test_a_rate_limit_block_expires_on_its_own(monkeypatch, tmp_path):
    monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'home'))
    set_blocked()
    with pytest.raises(NaverBlogError) as caught:
        check_blocked()
    assert caught.value.error == 'rate_limit'
    record = json.loads((cache_dir() / 'blocked.json').read_text())
    record['expires_at'] = time.time() - 1
    (cache_dir() / 'blocked.json').write_text(json.dumps(record))
    assert check_blocked() is None


def test_clearing_a_block_leaves_the_local_window_intact(monkeypatch, tmp_path):
    monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NAVER_BLOG_NO_PACING', '1')
    with Budget(5).request():
        pass
    set_blocked()
    clear_blocked()
    # The block was about Naver; the window is our own promise and outlives it.
    assert check_blocked() is None and len(history()) == 1


def test_unreadable_history_stops_requests_rather_than_starting_over(monkeypatch, tmp_path):
    monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'home'))
    (tmp_path / 'home').mkdir(parents=True)
    (tmp_path / 'home/budget.json').write_text('{"requests": ["not a time"]}')
    with pytest.raises(NaverBlogError) as caught:
        history()
    assert caught.value.code == 5
