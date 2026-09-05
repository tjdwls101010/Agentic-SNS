"""Explicitly selected live smoke reads; no content snapshots or large collections."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.live
CLI = Path(__file__).resolve().parents[3] / '.claude/skills/facebook/scripts/facebook.py'


def read(*args):
    env = dict(os.environ)
    for name in ('FACEBOOK_ASIDE_BIN', 'FAKE_ASIDE_RESPONSES', 'FAKE_ASIDE_MODE'):
        env.pop(name, None)
    result = subprocess.run([sys.executable, str(CLI), *args, '--json'], env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data['ok'] is True
    assert isinstance(data['results'], list)
    return data


def test_live_doctor():
    result = read('doctor')
    assert result['results'][0]['account_id']


@pytest.mark.parametrize('args', [('feed',), ('profile', 'zuck'), ('search', 'seoul', '--type', 'groups')])
def test_live_small_read_shapes(args):
    result = read(*args, '--limit', '3')
    assert len(result['results']) <= 3
    assert all(isinstance(row.get('id'), str) for row in result['results'])


def test_live_post_and_comments_shapes():
    url = os.environ.get('FACEBOOK_LIVE_POST')
    if not url:
        pytest.skip('Set FACEBOOK_LIVE_POST to a known visible post permalink.')
    post = read('post', url, '--limit', '3')
    assert any('text' in row and 'post_id' not in row for row in post['results'])
    comments = read('comments', url, '--limit', '3')
    assert all('post_id' in row and 'depth' in row for row in comments['results'])


def test_live_about_shape():
    result = read('about', 'zuck', '--limit', '3')
    assert all('section' in row and 'text' in row for row in result['results'])


def test_live_group_shape():
    group = os.environ.get('FACEBOOK_LIVE_GROUP')
    if not group:
        pytest.skip('Set FACEBOOK_LIVE_GROUP to a known readable group id.')
    result = read('group', group, '--limit', '3')
    assert all('id' in row and 'text' in row for row in result['results'])
