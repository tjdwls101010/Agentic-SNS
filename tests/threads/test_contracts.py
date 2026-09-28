"""Pure contracts, tested in-process: response classification, record normalization, target parsing."""
import json

import pytest

from threads.errors import ThreadsError
from threads.graphql.normalize import build_counts, build_post, build_user
from threads.graphql.target import parse_target
from threads.graphql.transport import classify

from .fixtures.builders import raw_post


def envelope(body, status=200, url='https://www.threads.com/graphql/query'):
    return {'status': status, 'url': url, 'body': body if isinstance(body, str) else json.dumps(body)}


# --- classification: checkpoint > rate limit > login > HTTP > data -------------------------------------------------

@pytest.mark.parametrize('body,status,url,code,kind', [
    ({'errors': [{'message': 'checkpoint_required'}]}, 429, '', 5, 'checkpoint'),
    ({'error': {'error_subcode': 368}}, 200, '', 5, 'checkpoint'),
    ({'errors': [{'code': 459}]}, 200, '', 5, 'checkpoint'),
    ({}, 429, '', 5, 'rate_limit'),
    ({'error_code': 17}, 200, '', 5, 'rate_limit'),
    ({'error_code': '368'}, 200, '', 5, 'checkpoint'),
    ({'error_subcode': '459'}, 200, '', 5, 'checkpoint'),
    ({'errors': [{'message': 'login_required'}]}, 200, '', 4, 'login'),
    ('', 302, 'https://www.threads.com/accounts/login/', 4, 'login'),
    ('bad gateway', 502, '', 6, 'transient'),
    ('{"data":', 200, '', 6, 'transient'),
    ({'errors': [{'message': 'execution error', 'severity': 'CRITICAL'}], 'data': None}, 200, '', 6, 'operation_rotated'),
    ({'data': {'user': None}}, 200, '', 6, 'envelope_drift'),
])
def test_error_contract(body, status, url, code, kind):
    with pytest.raises(ThreadsError) as error:
        classify(envelope(body, status, url), 'graphql')
    assert (error.value.code, error.value.error) == (code, kind)


def test_normal_post_text_does_not_block_and_partial_data_is_readable():
    payload = {'data': {'feedData': {'edges': [{'caption': 'challenge try again later checkpoint_required'}]}},
               'errors': [{'message': 'field_exception', 'path': ['optional_field']}]}
    assert classify(envelope(payload), 'graphql') == payload
    html = '<script type="application/json">{"caption":{"text":"checkpoint_required challenge"}}</script>'
    assert classify(envelope(html), 'page') == html


def test_structural_html_challenge_is_a_checkpoint():
    with pytest.raises(ThreadsError) as error:
        classify(envelope('<form action="/challenge/"></form>'), 'page')
    assert error.value.error == 'checkpoint'


def test_error_paths_and_source_locations_are_not_rate_limit_codes():
    payload = {'data': {'feedData': {'edges': []}}, 'errors': [{'message': 'field_exception',
               'path': ['feedData', 'edges', 4, 'caption'], 'locations': [{'line': 17, 'column': 4}]}]}
    assert classify(envelope(payload), 'graphql') == payload


# --- normalization --------------------------------------------------------------------------------------------------

def test_nested_tombstone_preserves_the_outer_post_and_relationship():
    raw = raw_post(text_post_app_info={'is_reply': True, 'reply_to_id': '99',
                                       'share_info': {'quoted_post': {'is_post_unavailable': True}}})
    post = build_post(raw).to_dict()
    assert post['id'] == '1' and post['reply_to_id'] == '99'
    assert post['quoted_post']['unavailable'] is True
    assert post['url'] == 'https://www.threads.com/@fixture_user/post/FIX_1'


def test_a_quote_cycle_ends_in_a_marked_record_instead_of_recursing():
    raw = raw_post('1')
    raw['text_post_app_info'] = {'share_info': {'quoted_post': raw}}
    quoted = build_post(raw).to_dict()['quoted_post']
    assert quoted['unavailable'] is True and 'cycle' in quoted['unavailable_reason']


def test_carousel_selects_largest_media_and_link_preview():
    raw = raw_post(media_type=8, carousel_media=[{'media_type': 1, 'image_versions2': {'candidates': [
        {'url': 'https://example.invalid/small', 'width': 1, 'height': 1},
        {'url': 'https://example.invalid/big', 'width': 200, 'height': 100}]}}],
        text_post_app_info={'link_preview_attachment': {'title': 'Fixture', 'url': 'https://example.invalid/'}})
    post = build_post(raw).to_dict()
    assert post['media'][0]['url'] == 'https://example.invalid/big'
    assert post['media_type'] == 'carousel'
    assert post['link_preview']['title'] == 'Fixture'


def test_user_privacy_links_relationships_and_missing_counts_are_distinct_from_zero():
    user = build_user({'pk': '42', 'username': 'fixture_user', 'text_post_app_is_private': True,
                       'bio_links': [{'url': 'https://example.invalid/'}],
                       'friendship_status': {'following': False}}).to_dict()
    assert user['private'] and user['friendship_status']['following'] is False
    assert user['bio_links'] == ['https://example.invalid/']
    assert build_counts({'followers': 1, 'following': 0}).to_dict() == {'followers': 1, 'following': 0, 'mutuals': None}


# --- targets --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('text', ['@alice', 'alice', '/@alice/', 'https://threads.net/@alice?x=1',
                                  'https://www.threads.com/@alice/replies', 'threads.com/@alice/media', '/@alice/reposts'])
def test_user_handles_and_tab_urls_are_composable(text):
    target = parse_target(text, 'user')
    assert (target.kind, target.username, target.path) == ('user', 'alice', '/@alice')


@pytest.mark.parametrize('text', ['https://evil.test/@alice', '//evil.test/@alice', '/activity', '/settings',
                                  '/@alice/../../activity', 'https://www.threads.com:444/@alice',
                                  'https://name@www.threads.com/@alice', '/@alice/post/ABC'])
def test_user_command_rejects_other_surfaces(text):
    with pytest.raises(ThreadsError) as error:
        parse_target(text, 'user')
    assert error.value.code == 2


def test_short_post_code_uses_budgeted_redirect_and_numeric_user_stays_a_name():
    assert parse_target('ABC_12-z', 'post').path == '/t/ABC_12-z'
    assert parse_target('https://threads.net/@alice/post/ABC/?x=1', 'post').code == 'ABC'
    assert parse_target('123', 'user').username == '123'
