"""Synthetic structures derived from live responses, with no captured identities."""
import json

from _transport import classify


def test_comment_connection_is_not_confused_with_its_count_only_preview():
    data = {'data': {'node': {
        'comment_rendering_instance_for_feed_location': {'comments': {
            'edges': [{'node': {'id': 'synthetic-comment'}}],
            'page_info': {'has_next_page': False}}},
        'comment_rendering_instance': {'comments': {'total_count': 20}},
    }}}
    envelope = dict(status=200, url='https://www.facebook.com/api/graphql/', body=json.dumps(data))
    assert classify(envelope, 'comments') == [data]


def test_static_bundle_auth_identifiers_are_source_code_not_account_challenges():
    envelope = dict(status=200, url='https://static.xx.fbcdn.net/rsrc.php/example.js',
                    body='const config={"checkpoint_url":"/checkpoint/","error":1357001};')
    assert classify(envelope, html=True, asset=True) == envelope
