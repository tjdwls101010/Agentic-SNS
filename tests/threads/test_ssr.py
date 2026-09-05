import json

import pytest

from threads_skill._ssr import SSR
from threads_skill._errors import ThreadsError


def test_selects_operation_and_requested_identity_without_accepting_decoys():
    payload = [{'queryName': 'BarcelonaPostPageStrongIdTargetQuery', 'variables': {'postID': '1'},
                '__bbox': {'result': {'data': {'media': {'pk': '1', 'code': 'ONE'}}}}},
               {'queryName': 'BarcelonaPostPageStrongIdTargetQuery', 'variables': {'postID': '2'},
                '__bbox': {'result': {'data': {'media': {'pk': '2', 'code': 'TWO'}}}}}]
    html = '<script type="application/json">' + json.dumps(payload) + '</script>'
    ssr = SSR(html)
    assert ssr.select('BarcelonaPostPageStrongIdTargetQuery', '1')['media']['code'] == 'ONE'
    with pytest.raises(ThreadsError):
        ssr.select('BarcelonaPostPageStrongIdTargetQuery', '3')


def test_no_recursive_post_key_fallback_outside_bbox():
    with pytest.raises(ThreadsError):
        SSR('<script type="application/json">{"data":{"media":{"pk":"1"}}}</script>').select('BarcelonaPostPageStrongIdTargetQuery', '1')


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
