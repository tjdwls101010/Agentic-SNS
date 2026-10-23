"""Live smoke against the real Facebook account in the Aside browser — runs only with SNS_LIVE=facebook (or all), through
the real cli.py and the skill's own data/, so its protection and pacing are the ones every invocation shares.

Targets come from the environment only (this repository is public): SNS_LIVE_FACEBOOK_POST (a public post URL, with
comments), SNS_LIVE_FACEBOOK_REPLIES_POST (a public post whose first page has a comment with replies),
SNS_LIVE_FACEBOOK_GROUP (a public group id) and SNS_LIVE_FACEBOOK_PAGE (a public page). Each step asserts what a working
read must show: records with their fields, a stop reason, a continuation that leads to the next read, no duplicates
across pages. There is no request budget; a page is a request or two."""
import json
import os
import sys

import pytest

from tests.sns.support.cli import command_of, run_cli

pytestmark = pytest.mark.live('facebook')


def target(name):
    value = os.environ.get(f'SNS_LIVE_FACEBOOK_{name}')
    if not value:
        pytest.skip(f'live: set SNS_LIVE_FACEBOOK_{name}')
    return value


def cli(*args):
    done = run_cli('facebook', *args, '--json', timeout=300)
    result = json.loads(done.stdout)
    print(json.dumps({'command': args[:2], 'exit': done.returncode, 'requests': result.get('request_count'),
                      'setup': result.get('setup_requests'), 'unwatched': result.get('unwatched_requests'),
                      'stopped': result.get('stop_reason'), 'error': result.get('error')}), file=sys.stderr)
    if result.get('error') in ('blocked', 'login'):
        pytest.exit(f'stopped: {result["error"]} — tell 성진 before anything else', returncode=3)
    return done.returncode, result


def required_post_fields(record):
    assert record['kind'] == 'post' and record['id'] and record['author_url'] and isinstance(record['text'], str)
    assert record['created_at'] or record['undated']


def test_doctor_feed_two_pages_post_and_comments():
    done = run_cli('facebook', 'doctor', timeout=300)
    check = json.loads(done.stdout)['results'][0]
    assert done.returncode == 0 and check['login'] == 'ready' and check['viewer'] and check['blocked'] is False

    code, first = cli('feed', '--sort', 'recent', '--limit', '3')
    assert code == 0 and first['results'] and first['stop_reason'] in ('limit_reached', 'exhausted')
    for record in first['results']:
        required_post_fields(record)
    assert first.get('next')
    code, second = cli(*command_of('more: ' + first['next'])[1:])
    assert code == 0 and second['results']
    assert not {r['id'] for r in first['results']} & {r['id'] for r in second['results']}

    url = os.environ.get('SNS_LIVE_FACEBOOK_POST') or next(r['url'] for r in first['results'] + second['results']
                                                           if r['url'] and '/posts/' in r['url'])
    code, post = cli('post', url, '--limit', '3')
    assert code == 0, post
    required_post_fields(post['results'][0])
    comments = [r for r in post['results'][1:] if r['kind'] == 'comment']
    assert all(c['post_id'] == post['results'][0]['id'] and c['depth'] == 0 for c in comments)


def test_replies_batches():
    code, post = cli('post', target('REPLIES_POST'))
    assert code == 0, post
    with_replies = [c for c in post['results'][1:] if c.get('replies_handle')]
    assert with_replies, 'no comment with replies on the first page'
    chosen = max(with_replies, key=lambda c: c['reply_count'] or 0)
    code, first = cli('replies', str(chosen['replies_handle']))
    assert code == 0 and first['results'] and first['thread']['parent_id'] == chosen['id']
    assert all(r['depth'] == 1 and r['parent_id'] == chosen['id'] for r in first['results'])


def test_search_filters_and_inside_a_group():
    group = target('GROUP')
    code, recent = cli('search', 'AI', '--type', 'posts', '--recent', '--limit', '3')
    assert code == 0 and recent['results'] and all(r['kind'] == 'post' for r in recent['results'])
    code, scoped = cli('search', 'pandas', '--type', 'posts', '--in-group', group, '--limit', '3')
    assert code == 0, scoped
    for record in scoped['results']:
        assert record['url'] is None or '/groups/' in record['url'], record['url']


def test_page_about_and_group_card():
    code, page = cli('about', target('PAGE'), '--section', 'directory_bio')
    assert code == 0 and page['results'] and all(f['section'] == 'directory_bio' for f in page['results'])
    code, card = cli('about', 'https://www.facebook.com/groups/' + target('GROUP') + '/')
    assert code == 0, card
    [group] = card['results']
    assert group['kind'] == 'group' and group['name'] and group['privacy'] and group['member_count_text']
    assert isinstance(group['rules'], list)
