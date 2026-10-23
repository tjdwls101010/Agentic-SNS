"""Live smoke against the real Threads account in the Aside browser — runs only with SNS_LIVE=threads (or all), through the
real cli.py and the skill's own data/, so its protection and pacing are the ones every invocation shares.

Targets come from the environment only (this repository is public): SNS_LIVE_THREADS_POST (a public post URL with replies
beyond the first batch). Each step asserts what a working read must show: records with their fields, a stop reason, a
continuation that leads to the next read, no duplicates across pages. There is no request budget; a page is a request."""
import json
import os
import sys

import pytest

from tests.sns.support.cli import command_of, run_cli

pytestmark = pytest.mark.live('threads')
SPENT = []


def target(name):
    value = os.environ.get(f'SNS_LIVE_THREADS_{name}')
    if not value:
        pytest.skip(f'live: set SNS_LIVE_THREADS_{name}')
    return value


def cli(*args):
    done = run_cli('threads', *args, timeout=300)
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


def test_doctor_feed_two_pages_post_and_more_replies():
    code, result = cli('doctor')
    assert code == 0, result
    assert result['results'][0]['login'] == 'ready' and result['results'][0]['viewer']

    code, first = cli('feed', '--json')
    assert code == 0, first
    assert first['results'] and all(r.get('id') and r.get('url') for r in first['results'] if not r.get('unavailable'))
    assert first.get('next')
    code, second = cli(*command_of('more: ' + first['next'])[1:], '--json')
    assert code == 0, second
    ids = [r['id'] for r in first['results']] + [r['id'] for r in second['results']]
    assert len(ids) == len(set(ids)) and second['results']

    url = target('POST')
    code, page = cli('post', url, '--json')
    assert code == 0, page
    roles = [r['role'] for r in page['results']]
    assert 'post' in roles and roles.count('reply') >= 1
    assert page['replies']['received_direct'] >= 1 and page.get('next')
    code, more = cli(*command_of('more: ' + page['next'])[1:], '--json')
    assert code == 0, more
    assert more['results'] and not set(r['id'] for r in more['results']) & set(r['id'] for r in page['results'])
    branch = next((r for r in page['results'] if r.get('replies_handle')), None)
    if branch:
        code, under = cli('replies', str(branch['replies_handle']), '--json')
        assert code == 0, under
        first_level = [r for r in under['results'] if r['depth'] == 1]
        assert first_level and all(r['relation']['to'] == branch['id'] for r in first_level)
    nested = [r for r in page['results'] if (r.get('reply_level') or 0) >= 2]
    assert all(r['relation'] for r in nested), 'a nested reply was not placed'
    print(json.dumps({'spent': SPENT}), file=sys.stderr)


def test_quotes_and_reposts_of_the_live_post():
    url = target('POST')
    for command, kind in (('quotes', 'quote'), ('reposts', None)):
        code, result = cli(command, url, '--json')
        assert code in (0, 7), result
        if code == 7:
            continue
        assert result['stop_reason'] in ('exhausted', 'server_capped')
        for record in result['results']:
            assert record['id'] and (record.get('role') == kind if kind else record.get('reposted_at'))
            assert record['url'] and (record['author']['username'] if kind else record['username'])
    print(json.dumps({'spent': SPENT}), file=sys.stderr)
