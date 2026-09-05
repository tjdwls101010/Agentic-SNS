from threads_skill._models import build_post
from threads_skill._entities import build_user, build_counts


def raw_post(pk='1', **extra):
    return {'pk': pk, 'code': 'FIX_' + pk, 'taken_at': 1788566400,
            'user': {'pk': '42', 'username': 'fixture_user', 'full_name': 'Synthetic Person'},
            'caption': {'text': 'A synthetic post'}, **extra}


def test_nested_tombstone_preserves_the_outer_post_and_relationship():
    raw = raw_post(text_post_app_info={'is_reply': True, 'reply_to_id': '99',
        'share_info': {'quoted_post': {'is_post_unavailable': True}}})
    post = build_post(raw).to_dict()
    assert post['id'] == '1' and post['reply_to_id'] == '99'
    assert post['quoted_post']['unavailable'] is True
    assert post['url'] == 'https://www.threads.com/@fixture_user/post/FIX_1'


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
        'bio_links': [{'url': 'https://example.invalid/'}], 'friendship_status': {'following': False}}).to_dict()
    assert user['private'] and user['friendship_status']['following'] is False
    assert user['bio_links'] == ['https://example.invalid/']
    assert build_counts({'followers': 1, 'following': 0}).to_dict() == {'followers': 1, 'following': 0, 'mutuals': None}
