"""Live smoke against the real X account in the Aside browser — opt in with TWITTER_LIVE=1.

Targets come from the environment only (this repository is public): TWITTER_LIVE_POST (a public post URL with replies
beyond the first batch). Each step asserts what a working read must show: records with their fields, a stop reason,
requests within the budget, a continuation that leads to the next read, no duplicates across pages. Never point it at
a screen that changes state when read (the notifications screen marks notifications as read).
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import CLI, command_of

pytestmark = pytest.mark.skipif(os.environ.get('TWITTER_LIVE') != '1', reason='live smoke: set TWITTER_LIVE=1')
SPENT = []


def cli(*args):
    env = {k: v for k, v in os.environ.items() if k not in ('TWITTER_ASIDE_BIN', 'TWITTER_DATA_DIR')}
    done = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=300)
    result = json.loads(done.stdout)
    SPENT.append((args[0], result.get('request_count', 0), result.get('setup_requests', 0),
                  result.get('unwatched_requests', 0)))
    print(json.dumps({'command': args[:2], 'exit': done.returncode, 'requests': result.get('request_count'),
                      'setup': result.get('setup_requests'), 'unwatched': result.get('unwatched_requests'),
                      'stopped': result.get('stop_reason'), 'error': result.get('error'),
                      'message': result.get('message')}), file=sys.stderr)
    if result.get('error') in ('blocked', 'login'):
        pytest.exit(f'stopped: {result["error"]} — tell 성진 before anything else', returncode=3)
    return done.returncode, result


def own(result):
    """Requests beyond opening or reloading the tab."""
    return result.get('request_count', 0) - result.get('setup_requests', 0)


def test_doctor_feed_two_pages_post_more_replies_and_a_branch():
    code, result = cli('doctor')
    assert code == 0, result
    assert result['results'][0]['login'] == 'ready' and result['results'][0]['account_id']

    code, first = cli('feed', '--json', '--max-requests', '3')
    assert code == 0, first
    assert first['results'] and all(r.get('id') and r.get('url') for r in first['results'] if not r.get('unavailable'))
    assert own(first) <= 3 and first.get('next')
    code, second = cli(*command_of('more: ' + first['next']))
    assert code == 0, second
    ids = [r['id'] for r in first['results']] + [r['id'] for r in second['results']]
    assert second['results'] and len(ids) == len(set(ids))

    url = os.environ['TWITTER_LIVE_POST']
    code, page = cli('post', url, '--json', '--max-requests', '3')
    assert code == 0, page
    roles = [r['role'] for r in page['results']]
    assert roles.count('post') == 1 and roles.count('reply') >= 1 and own(page) <= 3
    focal = next(r for r in page['results'] if r['role'] == 'post')
    assert focal['text'] and focal['author']['username'] and focal['url']
    assert page['replies']['direct_shown'] >= 1 and page.get('next')
    code, more = cli(*command_of('more: ' + page['next']))
    assert code == 0, more
    assert more['results'] and not {r['id'] for r in more['results']} & {r['id'] for r in page['results']}
    branch = next((r for r in page['results'] if r.get('replies_handle')), None)
    if branch:
        code, under = cli('replies', str(branch['replies_handle']), '--json')
        assert code == 0, under
        assert any(r['reply_to_id'] == branch['id'] for r in under['results'])
    print(json.dumps({'spent': SPENT}), file=sys.stderr)
