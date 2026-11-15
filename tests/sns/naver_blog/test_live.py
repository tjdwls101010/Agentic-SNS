"""Live smoke against the real Naver account in the Aside browser — runs only with SNS_LIVE=naver-blog (or all), through the
real cli.py and the skill's own state, so its protection and pacing are the ones every invocation shares.

Targets come from the environment only (this repository is public): SNS_LIVE_NAVER_BLOG_QUERY (a search with many recent
posts; the post and blog under test are taken from its results) and, optionally, SNS_LIVE_NAVER_BLOG_POST (a public post
with comments). A block or a login wall ends the session: tell the person instead of retrying."""
import json
import os
import sys

import pytest

from tests.sns.support.cli import command_of, run_cli

pytestmark = pytest.mark.live('naver-blog')


def target(name):
    value = os.environ.get(f'SNS_LIVE_NAVER_BLOG_{name}')
    if not value:
        pytest.skip(f'live: set SNS_LIVE_NAVER_BLOG_{name}')
    return value


def cli(*args):
    done = run_cli('naver-blog', *args, timeout=300)
    result = json.loads(done.stdout)
    print(json.dumps({'command': args[:2], 'exit': done.returncode, 'requests': result.get('request_count'),
                      'stopped': result.get('stop_reason'), 'error': result.get('error'),
                      'message': result.get('message')}), file=sys.stderr)
    if result.get('error') in ('blocked', 'login'):
        pytest.exit(f'stopped: {result["error"]} — tell 성진 before anything else', returncode=3)
    return done.returncode, result


def records(result):
    """The records of a result, from results or, for a composite command (post, blog), from its sections."""
    return result.get('results') or [r for section in result.get('sections', []) for r in section.get('data') or []]


def follow(next_command):
    """Run the command a result's next field names, as JSON."""
    return cli(*command_of('more: ' + next_command)[1:], '--json')


def test_doctor_and_feed_two_pages():
    code, result = cli('doctor')
    assert code == 0, result
    assert result['results'][0]['login'] == 'ready'

    code, first = cli('feed', '--json')
    assert code == 0, first
    assert first['results'] and all(r.get('url') for r in first['results'])
    if first.get('next'):
        code, second = follow(first['next'])
        assert code == 0, second
        urls = [r['url'] for r in first['results']] + [r['url'] for r in second['results']]
        assert second['results'] and len(urls) == len(set(urls))


def test_search_then_the_post_and_its_blog():
    code, found = cli('search', target('QUERY'), '--limit', '5', '--json')
    assert code == 0, found
    assert len(found['results']) == 5 and found.get('next')
    code, more = follow(found['next'])
    assert code == 0 and more['results'], more
    assert not {r['url'] for r in found['results']} & {r['url'] for r in more['results']}

    hit = found['results'][0]
    code, page = cli('post', hit['url'], '--json')
    assert code == 0, page
    post = next(r for r in records(page) if r['kind'] == 'post')
    assert post['lines'] and post['url'] == hit['url'] and post['coverage']['label'].startswith('text[')

    blog = hit['blog_id']
    code, card = cli('about', blog, '--json')
    assert code == 0 and records(card), card
    code, listing = cli('profile', blog, '--limit', '3', '--json')
    assert code == 0 and listing['results'], listing


def test_comments_of_a_post():
    code, page = cli('comments', target('POST'), '--json')
    assert code in (0, 7), page
    if code == 0:
        assert page['results'] and all(r.get('text') is not None for r in page['results'])
