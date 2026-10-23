"""Real answers captured during recon (tests/sns/captures/reddit/, local only, never committed): the readers turn every one
of them into records without an unexpected error. Skipped when there are no captures."""
import json
from pathlib import Path

import pytest

from sns.errors import SnsError
from sns.reddit import web

CAPTURES = Path(__file__).resolve().parents[1] / 'captures' / 'reddit'
FILES = sorted(CAPTURES.glob('*.json')) if CAPTURES.exists() else []


def expect_of(request):
    path = request.get('path') or ''
    if path.endswith('/api/morechildren.json'):
        return 'morechildren'
    if '/comments/' in path:
        return 'post_pair'
    if path.startswith('/duplicates/'):
        return 'duplicates'
    if path == '/api/me.json':
        return 'me'
    if path.endswith('/about/rules.json'):
        return 'rules'
    if path.startswith('/user/') and path.endswith('/about.json'):
        return 'thing:t2'
    if path.endswith('/about.json'):
        return 'thing:t5'
    if path.endswith('/wiki/pages.json'):
        return 'wiki_index'
    if '/wiki/' in path:
        return 'wiki_page'
    if path.endswith('/moderators.json'):
        return 'moderators'
    if path.endswith('/sticky.json') or not path:
        return None  # a redirect, or a share link page
    return 'listing'


@pytest.mark.skipif(not FILES, reason='no local captures')
@pytest.mark.parametrize('path', FILES, ids=lambda p: p.stem)
def test_a_captured_answer_reads_cleanly(path):
    capture = json.loads(path.read_text())
    expect = expect_of(capture['request'])
    if expect is None or capture['status'] != 200:
        pytest.skip('not a 200 answer of a surface this skill reads')
    try:
        body = web.classify(capture, expect, wiki=expect.startswith('wiki'))
    except SnsError as error:
        assert error.kind == 'empty', (expect, error.message)
        return
    if expect == 'listing':
        records, _ = web.page(body)
        assert all(r['id'] for r in records)
    elif expect == 'post_pair':
        post, items = web.thread(body)
        assert post['id'].startswith('t3_') and all(i['type'] in ('comment', 'gap') for i in items)
    elif expect == 'morechildren':
        assert all(i['type'] in ('comment', 'gap') for i in web.expansion(body))
    elif expect == 'duplicates':
        web.page(body[1])
    elif expect == 'thing:t2':
        assert web.user(body['data'])['name']
    elif expect == 'wiki_page':
        assert web.wiki_page('x', 'index', body['data'])['text']
    elif expect == 'wiki_index':
        assert web.wiki_index('x', body['data'])['pages']
    elif expect == 'moderators':
        assert all(web.moderator(m)['name'] for m in body['data']['children'])
    elif expect == 'thing:t5':
        assert web.community(body['data'])['name']
