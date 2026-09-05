import json
from argparse import Namespace

import pytest

from threads_skill._thread import read_thread
from threads_skill._session import Session
from threads_skill._target import parse_target
from threads_skill._errors import ThreadsError
from .test_models import raw_post


def thread_html():
    parent, target, reply, child = [raw_post(str(n)) for n in range(1, 5)]
    target['text_post_app_info'] = {'direct_reply_count': 12}
    child['text_post_app_info'] = {'reply_to_id': '3', 'is_reply': True}
    objects = [('Target', target), ('Upward', {'pk': '2', 'text_post_app_info': {'containing_thread': {'posts': {'edges': [{'node': parent}]}}}}),
               ('Downward', {'pk': '2', 'text_post_app_info': {'direct_replies': {'edges': [
                   {'node': {'posts': {'edges': [{'node': reply}, {'node': child}]}}},
                   {'node': {'posts': {'edges': [{'node': raw_post('5')}, {'node': raw_post('6')}]}}}],
                   'page_info': {'has_next_page': True, 'end_cursor': 'UNREPLAYABLE'}}}})]
    items = []
    for suffix, media in objects:
        name = 'BarcelonaPostPageStrongId' + suffix + 'Query'
        items.extend([{'preloaderID': 'adp_' + name + 'RelayPreloader_x', 'queryID': '1001', 'variables': {'postID': '2'}},
                      {'queryName': name, '__bbox': {'result': {'data': {'media': media}}}}])
    return '<script type="application/json">' + json.dumps({'csrf_token': 'fixture', 'NON_FACEBOOK_USER_ID': '42', 'username': 'fixture', 'items': items}) + '</script>'


def test_thread_coverage_counts_direct_and_descendants_separately(tmp_path):
    html = thread_html()
    args = Namespace(target=parse_target('/@fixture_user/post/FIX_2', 'post'), limit=1, sort='top', out=None, command='post')
    result = read_thread(html, Session.from_html(html), args)
    assert [p['id'] for p in result['results']] == ['1', '2', '3', '4']
    assert result['completeness'] == {'reported_direct': 12, 'received_direct': 2, 'shown_direct': 1,
        'shown_descendants': 1, 'unshown_received': 1, 'unavailable': 0, 'unfetched': 10, 'unfetched_is_estimate': True}
    assert result['stop_reason'] == 'not_paginable' and result['next'] is None
    assert result['results'][-1]['reply_to_id'] == '3'
    assert result['results'][-1]['depth'] == 1
    args.limit = 2
    result = read_thread(html, Session.from_html(html), args)
    assert result['results'][-1]['relation'] == 'thread continuation'
    assert result['results'][-1]['reply_to_id'] is None


def test_post_code_mismatch_is_never_rendered():
    html = thread_html()
    args = Namespace(target=parse_target('/@fixture_user/post/WRONG', 'post'), limit=1, sort='top', out=None)
    with pytest.raises(ThreadsError):
        read_thread(html, Session.from_html(html), args)


def test_tombstone_does_not_discard_its_received_descendants():
    html = thread_html().replace(json.dumps(raw_post('3')), json.dumps({'pk': '3', 'is_post_unavailable': True}))
    args = Namespace(target=parse_target('/@fixture_user/post/FIX_2', 'post'), limit=10, sort='top', out=None)
    result = read_thread(html, Session.from_html(html), args)
    assert '4' in [item['id'] for item in result['results']]
    assert result['completeness']['unavailable'] == 1
    assert result['completeness']['shown_descendants'] == 2
