"""Local check on real responses captured during reconnaissance (tests/threads/captures, never committed): the
classifier and the record readers handle them without unexpected failures. Skipped when no capture is present."""
import json
from pathlib import Path

import pytest

from threads import threads_web

CAPTURES = Path(__file__).resolve().parent / 'captures'
pytestmark = pytest.mark.skipif(not (CAPTURES / 'r2-callB.json').exists(), reason='no local captures')


def load(name):
    return json.loads((CAPTURES / name).read_text())['result']['data']


def documents():
    pages = load('r2-callB.json')['pages'] + load('r1-learn-home.json')['pages']
    return [page for page in pages if page.get('html')]


def test_real_documents_are_logged_in_pages_without_block_markers():
    for page in documents():
        verdict = threads_web.classify_response({'status': page['status'], 'url': page['url'], 'body': page['html']},
                                                mode='page')
        assert verdict.kind == 'ok', page['path']
        session = threads_web.classify_document(page['html'])
        assert session.kind == 'ok' and session.account_id and session.account_id != '0', page['path']


def test_real_feed_pages_read_into_records():
    for result in load('r2-callB.json')['results']:
        verdict = threads_web.classify_response({'status': 200, 'url': 'https://www.threads.com/api/graphql/',
                                                 'body': result['body']}, mode='graphql')
        assert verdict.kind == 'ok'
        page = threads_web.connection_page(verdict.payload['data'], 'feed')
        assert page.records and all(r['id'] and r['url'] and r['author'] for r in page.records)
        assert page.has_next and page.cursor


def hooked(name_prefix):
    return [item for item in load('r2-callC-dump.json')['hook'] if item['via'] == 'fetch'
            and (item['name'] or '').startswith(name_prefix) and len(item['body']) < 199000]


def test_real_reply_batches_and_search_results_read_into_records():
    for item in hooked('BarcelonaPostPageDownwardQuery'):
        verdict = threads_web.classify_response({'status': 200, 'url': 'x', 'body': item['body']}, mode='graphql')
        assert verdict.kind == 'ok'
        info = verdict.payload['data']['media']['text_post_app_info']
        records, branches = threads_web.reply_batch(info['direct_replies'], 'x', set(), limit=None,
                                                    counts=threads_web.new_counts())
        assert records and all(r['id'] and r['author'] for r in records)
    for item in hooked('BarcelonaSearchResultsQuery'):
        verdict = threads_web.classify_response({'status': 200, 'url': 'x', 'body': item['body']}, mode='graphql')
        assert threads_web.connection_page(verdict.payload['data'], 'search_posts').records
    for item in hooked('useBarcelonaAccountSearch'):
        verdict = threads_web.classify_response({'status': 200, 'url': 'x', 'body': item['body']}, mode='graphql')
        assert threads_web.connection_page(verdict.payload['data'], 'search_accounts').records


def test_app_background_responses_classify_without_false_blocks():
    for item in load('r2-callC-dump.json')['hook']:
        if item['via'] == 'xhr' and item.get('body'):
            verdict = threads_web.classify_response({'status': item['status'], 'url': 'https://www.threads.com' +
                                                     item['url'], 'body': item['body']}, mode='graphql')
            assert verdict.kind not in ('blocked', 'login'), item['name']  # an all-null answer is fine here
