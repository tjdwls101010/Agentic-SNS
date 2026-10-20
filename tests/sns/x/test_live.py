"""Live smoke against the real X account in the Aside browser — runs only with SNS_LIVE=x (or all), through the real
cli.py and the skill's own data/, so its protection and pacing are the ones every invocation shares.

Targets come from the environment only (this repository is public): SNS_LIVE_X_POST (a public post URL with replies
beyond the first batch and reposts), SNS_LIVE_X_ACCOUNT (a public @handle with lists), SNS_LIVE_X_LIST and
SNS_LIVE_X_COMMUNITY (ids), SNS_LIVE_X_SPACE (a space link; ended or gone is fine). Each step asserts what a working read
must show: records with their fields, a stop reason, a continuation that leads to the next read, no duplicates across
pages. There is no request budget; a page is a request or two. Never point it at a screen that changes state when read
(the notifications screen marks notifications as read)."""
import json
import os
import sys

import pytest

from tests.sns.support.cli import command_of, run_cli

pytestmark = pytest.mark.live('x')
SPENT = []


def target(name):
    value = os.environ.get(f'SNS_LIVE_X_{name}')
    if not value:
        pytest.skip(f'live: set SNS_LIVE_X_{name}')
    return value


def cli(*args):
    done = run_cli('x', *args, timeout=300)
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
    post = target('POST')
    code, result = cli('doctor')
    assert code == 0, result
    assert result['results'][0]['login'] == 'ready' and result['results'][0]['viewer']

    code, first = cli('feed', '--json')
    assert code == 0, first
    assert first['results'] and all(r.get('id') and r.get('url') for r in first['results'] if not r.get('unavailable'))
    assert own(first) <= 3 and first.get('next')
    code, second = cli(*command_of('more: ' + first['next'])[1:])
    assert code == 0, second
    ids = [r['id'] for r in first['results']] + [r['id'] for r in second['results']]
    assert second['results'] and len(ids) == len(set(ids))

    code, page = cli('post', post, '--json')
    assert code == 0, page
    roles = [r['role'] for r in page['results']]
    assert roles.count('post') == 1 and roles.count('reply') >= 1 and own(page) <= 3
    focal = next(r for r in page['results'] if r['role'] == 'post')
    assert focal['text'] and focal['author']['username'] and focal['url']
    assert page['replies']['direct_shown'] >= 1 and page.get('next')
    code, more = cli(*command_of('more: ' + page['next'])[1:])
    assert code == 0, more
    assert more['results'] and not {r['id'] for r in more['results']} & {r['id'] for r in page['results']}
    branch = next((r for r in page['results'] if r.get('replies_handle')), None)
    if branch:
        code, under = cli('replies', str(branch['replies_handle']), '--json')
        assert code == 0, under
        assert any(r['parent_id'] == branch['id'] for r in under['results'])
    print(json.dumps({'spent': SPENT}), file=sys.stderr)


def test_a_time_limit_stop_resumes_with_more(monkeypatch):
    """The 100-second deadline is the brake that replaced the budget: a short one stops a long read after records with
    exit 0 and a more: line that continues it."""
    monkeypatch.setenv('SNS_DEADLINE_SECONDS', '12')
    code, result = cli('feed', '--json', '--limit', '200')
    assert code == 0, result
    assert result['results'] and result['stop_reason'] in ('time_limit', 'limit_reached') and result.get('next')


def test_the_surfaces_added_after_the_core():
    """Each read makes 1-2 requests of its own (the rest is the page's own background, 2-4 a command), with the records
    its kind promises."""
    def read(*args, kinds, allow=(0,)):
        code, result = cli(*args, '--json')
        assert code in allow, result
        if code == 0:
            assert result['results'] and {r['kind'] for r in result['results']} <= set(kinds), result.get('message')
            missing = [{k: (r[k] if k in ('kind', 'unavailable', 'role', 'unit') else type(r[k]).__name__) for k in sorted(r)}
                       for r in result['results'] if not r.get('id') and not r.get('unavailable')]
            assert not missing, (args[:2], missing[:2])
        assert own(result) <= 8
        return result

    account = target('ACCOUNT')
    read('reposts', target('POST'), kinds=('account',))
    read('graph', account, 'similar', kinds=('account',), allow=(0, 7))  # X's suggestions vary, sometimes none
    read('profile', account, '--tab', 'lists', kinds=('list',))
    read('profile', account, '--tab', 'memberships', kinds=('list',), allow=(0, 7))
    for tab, kinds in (('posts', ('post',)), ('members', ('account',)), ('about', ('list',))):
        read('list', target('LIST'), '--tab', tab, kinds=kinds)
    for tab, kinds in (('posts', ('post',)), ('media', ('post',)), ('about', ('community',))):
        read('community', target('COMMUNITY'), '--tab', tab, kinds=kinds)
    read('community', kinds=('community',))
    read('search', 'the', '--in', 'communities', kinds=('post',))
    trending = read('trends', kinds=('trend', 'event'))
    assert all(r.get('query') for r in trending['results'] if r['kind'] == 'trend')
    read('trends', '--tab', 'foryou', kinds=('trend', 'event'))
    read('about', target('SPACE'), kinds=('space',), allow=(0, 9))
    read('me', 'notifications', kinds=('notification', 'post'), allow=(0, 7))
    read('me', 'mentions', kinds=('post',), allow=(0, 7))
    print(json.dumps({'spent': SPENT}), file=sys.stderr)
