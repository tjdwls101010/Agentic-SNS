import json

import pytest

from threads_skill._ssr import SSR
from threads_skill._errors import ThreadsError


def post_route(results, post_id='1'):
    loader = {'preloaderID': 'adp_AnyPostQueryRelayPreloader_x', 'queryID': '1001', 'variables': {'postID': post_id}}
    return '<script type="application/json">' + json.dumps([loader, *results]) + '</script>'


def bbox(media):
    return {'__bbox': {'result': {'data': {'media': media}}}}


def test_post_payloads_are_chosen_by_identity_and_shape_without_accepting_decoys():
    thread = {'containing_thread': {'posts': {'edges': []}}}
    replies = {'direct_replies': {'edges': []}}
    html = post_route([bbox({'pk': '1', 'code': 'ONE'}), bbox({'pk': '2', 'code': 'TWO'}),
                       bbox({'pk': '1', 'text_post_app_info': thread}), bbox({'id': '1_42', 'text_post_app_info': replies}),
                       bbox({'id': '2_42', 'text_post_app_info': replies}), bbox({'id': '1_42', 'text_post_app_info': {}})])
    post_id, post, parents, children = SSR(html).post_page('ONE')
    assert (post_id, post['media']['code']) == ('1', 'ONE')
    assert parents['media']['text_post_app_info'] == thread
    assert children['media']['id'] == '1_42'
    with pytest.raises(ThreadsError):
        SSR(html).post_page('TWO')


def test_no_recursive_post_key_fallback_outside_bbox():
    html = post_route([{'data': {'media': {'pk': '1', 'code': 'ONE'}}}])
    with pytest.raises(ThreadsError):
        SSR(html).post_page('ONE')


def test_bootstrap_bbox_requires_are_traversed_to_nested_result():
    value = {'__bbox': {'require': [['ScheduledServerJS', 'handle', None, [
        {'__bbox': {'result': {'data': {'feedData': {'edges': []}}}}}]] ]}}
    html = '<script type="application/json">' + json.dumps(value) + '</script>'
    assert SSR(html).select('BarcelonaFeedDirectQuery') == {'feedData': {'edges': []}}


def test_anonymous_tab_payload_must_match_its_preloader_identity():
    value = [{'preloaderID': 'adp_BarcelonaProfileThreadsTabDirectQueryRelayPreloader_x',
              'queryID': '1001', 'variables': {'userID': '99'}},
             {'__bbox': {'result': {'data': {'mediaData': {'edges': []}}}}}]
    html = '<script type="application/json">' + json.dumps(value) + '</script>'
    with pytest.raises(ThreadsError):
        SSR(html).select('BarcelonaProfileThreadsTabDirectQuery', '42')
