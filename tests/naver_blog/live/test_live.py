"""Reads against the real logged-in account: shapes and internal consistency, never counts.

An item count is a property of Naver on the day, so asserting one here would break for a
reason that is not a regression. What is asserted is that the answer is about the thing
that was asked for, and that the tool's own numbers agree with each other.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[3] / '.claude/skills/naver-blog/scripts/naver_blog.py'
pytestmark = pytest.mark.live


def cli(*arguments):
    result = subprocess.run([sys.executable, str(ENTRY), *arguments, '--json'],
                            capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout or '{}')


def test_doctor_reports_the_logged_in_naver_account(live_budget):
    live_budget(1, 'doctor')
    code, payload = cli('doctor')
    assert code == 0, payload
    assert payload['viewer'] == 'chunghun1'
    assert payload['budget']['kind'] == 'local'


def test_the_neighbour_feed_ignores_its_page_size_exactly_as_recorded(live_budget):
    """F14 regression watch: the same request at two sizes must answer identically."""
    from naver_blog_skill._transport import Transport
    live_budget(2, 'buddy feed at two sizes')
    transport = Transport(4)
    small = transport.get('buddy_feed', countPerPage=3)['result']['buddyPostList']
    large = transport.get('buddy_feed', countPerPage=30)['result']['buddyPostList']
    # The set, not the order: a neighbour posting between the two reads would reorder them.
    assert {item['logNo'] for item in small} == {item['logNo'] for item in large}


def test_the_feed_page_still_carries_the_viewer_link_login_detection_relies_on(live_budget):
    """A1: the logged-out shape is unverified, so only the positive shape is checked here."""
    from naver_blog_skill._session import read_viewer
    from naver_blog_skill._transport import Transport
    live_budget(1, 'feed html')
    html = Transport(2).get('feed_html')
    assert read_viewer(html, source='feed') == 'chunghun1'


def test_search_answers_in_all_three_kinds(live_budget):
    live_budget(3, 'three searches')
    code, payload = cli('search', '파이썬', '--limit', '3')
    assert code == 0, payload
    assert all(record['id'].startswith('post:') for record in payload['results'])
    assert all(record['url'].startswith('https://blog.naver.com/') for record in payload['results'])

    code, payload = cli('search', '파이썬', '--type', 'blogs', '--limit', '3')
    assert code == 0, payload
    assert all(record['id'].startswith('blog:') for record in payload['results'])

    code, payload = cli('search', '파이썬', '--type', 'tags', '--limit', '3')
    assert code in (0, 7), payload
    # Tag results carry no blog name at all; claiming one would be inventing it.
    assert all(record['blog_name'] is None for record in payload['results'])


def test_a_blog_card_answers_about_the_blog_that_was_asked_for(live_budget):
    live_budget(4, 'blog naverofficial')
    code, payload = cli('blog', 'naverofficial')
    assert code == 0, payload
    sections = {section['name']: section for section in payload['sections']}
    assert set(sections) == {'blog', 'categories', 'notices', 'popular'}
    assert all(section['ok'] for section in sections.values()), sections
    assert sections['blog']['data'][0]['blog_id'] == 'naverofficial'


def test_a_post_list_is_about_the_category_it_was_asked_for(live_budget):
    live_budget(1, 'posts naverofficial')
    code, payload = cli('posts', 'naverofficial', '--limit', '3')
    assert code in (0, 8), payload
    assert all(record['blog_id'] == 'naverofficial' for record in payload['results'])
    # A post list's own total is always 0, so it must never reach the reader as a total.
    assert payload.get('reported_total') != 0
