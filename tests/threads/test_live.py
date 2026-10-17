"""Live smoke against the real Threads account in the Aside browser — opt in with THREADS_LIVE=1.

Targets come from the environment only (this repository is public): THREADS_LIVE_POST (a public post URL with replies
beyond the first batch). Each step asserts what a working read must show: records with their fields, a stop reason,
requests within the budget, a continuation that leads to the next read, no duplicates across pages.
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import CLI, command_of

pytestmark = pytest.mark.skipif(os.environ.get('THREADS_LIVE') != '1', reason='live smoke: set THREADS_LIVE=1')
SPENT = []


def cli(*args):
    env = {k: v for k, v in os.environ.items() if k not in ('THREADS_ASIDE_BIN', 'THREADS_DATA_DIR')}
    done = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=300)
    result = json.loads(done.stdout)
    SPENT.append((args[0], result.get('request_count', 0), result.get('unwatched_requests', 0)))
    print(json.dumps({'command': args[:2], 'exit': done.returncode, 'requests': result.get('request_count'),
                      'tab': result.get('tab_opened_requests'), 'unwatched': result.get('unwatched_requests'),
                      'stopped': result.get('stop_reason'), 'error': result.get('error'),
                      'message': result.get('message')}), file=sys.stderr)
    return done.returncode, result


def test_doctor_feed_two_pages_post_and_more_replies():
    code, result = cli('doctor')
    assert code == 0, result
    assert result['results'][0]['login'] == 'ready' and result['results'][0]['account_id']

    code, first = cli('feed', '--json', '--max-requests', '5')
    assert code == 0, first
    assert first['results'] and all(r.get('id') and r.get('url') for r in first['results'] if not r.get('unavailable'))
    assert first['request_count'] - first.get('tab_opened_requests', 0) <= 5 and first.get('next')
    code, second = cli(*command_of('more: ' + first['next']))
    assert code == 0, second
    ids = [r['id'] for r in first['results']] + [r['id'] for r in second['results']]
    assert len(ids) == len(set(ids)) and second['results']

    url = os.environ['THREADS_LIVE_POST']
    code, page = cli('post', url, '--json', '--max-requests', '6')
    assert code == 0, page
    roles = [r['role'] for r in page['results']]
    assert 'post' in roles and roles.count('reply') >= 1
    assert page['replies']['received_direct'] >= 1 and page.get('next')
    code, more = cli(*command_of('more: ' + page['next']))
    assert code == 0, more
    assert more['results'] and not set(r['id'] for r in more['results']) & set(r['id'] for r in page['results'])
    branch = next((r for r in page['results'] if r.get('replies_handle')), None)
    if branch:
        code, under = cli('replies', str(branch['replies_handle']), '--json')
        assert code == 0, under
        first = [r for r in under['results'] if r['depth'] == 1]
        assert first and all(r['relation']['to'] == branch['id'] for r in first)
        assert under.get('next') or len(under['results']) >= min(branch['reply_count'] or 0, 5)
    nested = [r for r in page['results'] if (r.get('reply_level') or 0) >= 2]
    assert all(r['relation'] for r in nested), 'a nested reply was not placed'
    print(json.dumps({'spent': SPENT}), file=sys.stderr)


def test_quotes_and_reposts_of_the_live_post():
    url = os.environ['THREADS_LIVE_POST']
    for command, kind in (('quotes', 'quote'), ('reposts', None)):
        code, result = cli(command, url, '--json', '--max-requests', '3')
        assert code == 0, result
        assert result['results'] and result['request_count'] - result.get('tab_opened_requests', 0) <= 5
        assert result['stop_reason'] in ('exhausted', 'server_capped') and result.get('reported_total')
        for record in result['results']:
            assert record['id'] and (record.get('role') == kind if kind else record.get('reposted_at'))
            assert record['url'] and (record['author']['username'] if kind else record['username'])
    print(json.dumps({'spent': SPENT}), file=sys.stderr)
