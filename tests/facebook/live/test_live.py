"""Explicitly selected live smoke reads: shapes and invariants only, never content, never large collections.

Run with FACEBOOK_ASIDE_BIN pointing at a request ledger in front of the real aside; this helper passes it through.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
CLI = Path(__file__).resolve().parents[3] / '.claude/skills/facebook/scripts/cli.py'


def read(*args, json_output=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith('FAKE_')}
    result = subprocess.run([sys.executable, str(CLI), *args, *(['--json'] if json_output else [])], env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data['ok'] is True and isinstance(data['results'], list)
    return data


def more_args(command):
    words = shlex.split(command)
    assert words[:3] == ['uv', 'run', str(CLI)]
    return words[3:]


def test_live_doctor():
    assert read('doctor', json_output=False)['results'][0]['account_id']


@pytest.mark.parametrize('args', [('feed',), ('profile', 'zuck'), ('search', 'seoul', '--type', 'groups')])
def test_live_small_read_shapes(args):
    result = read(*args, '--limit', '3', '--max-requests', '6')
    assert len(result['results']) <= 3
    assert all(isinstance(row.get('id'), str) for row in result['results'])


def test_live_continuation_does_not_repeat_records():
    first = read('feed', '--limit', '2', '--max-requests', '6')
    if 'next' not in first:
        pytest.skip('The first page ended the feed.')
    second = read(*more_args(first['next']), json_output=False)
    assert not {r['id'] for r in first['results']} & {r['id'] for r in second['results']}


def test_live_post_and_comments_shapes():
    url = os.environ.get('FACEBOOK_LIVE_POST')
    if not url:
        pytest.skip('Set FACEBOOK_LIVE_POST to a known visible post permalink.')
    post = read('post', url, '--limit', '3', '--max-requests', '6')
    assert any('text' in row and 'post_id' not in row for row in post['results'])
    comments = read('comments', url, '--limit', '3', '--max-requests', '6')
    assert all('post_id' in row and 'depth' in row for row in comments['results'])


def test_live_about_shape():
    result = read('about', 'zuck', '--max-requests', '12')
    assert all('section' in row and 'text' in row for row in result['results'])


def test_live_group_shape():
    group = os.environ.get('FACEBOOK_LIVE_GROUP')
    if not group:
        pytest.skip('Set FACEBOOK_LIVE_GROUP to a known readable group id.')
    result = read('group', group, '--limit', '3', '--max-requests', '6')
    assert all('id' in row and 'text' in row for row in result['results'])
