"""The normalized objects retain navigation handles and distinguish mixed kinds."""
from reddit_skill._models import build_post, build_comment


def test_post_and_comment_with_same_base_id_keep_distinct_identities():
    post = build_post({'id': 'abc', 'title': 'Title', 'subreddit': 'example', 'author': 'reader'}).to_dict()
    comment = build_comment({'id': 'abc', 'link_id': 't3_def', 'parent_id': 't3_def', 'body': '[deleted]'}).to_dict()
    assert post['fullname'] == 't3_abc'
    assert comment['fullname'] == 't1_abc'
    assert comment['url'] == 'https://www.reddit.com/comments/def/_/abc/'
    assert post['score'] is None
    assert comment['author'] == '[deleted]'


def test_media_type_precedence_and_content_are_preserved():
    cases = [({'is_gallery': True, 'media_metadata': {'one': {'s': {'u': 'https://i.redd.it/a'}}}, 'gallery_data': {'items': [{'media_id': 'one', 'caption': 'First'}]}}, 'gallery'),
             ({'poll_data': {'options': [{'text': 'Yes', 'vote_count': 3}]}}, 'poll'),
             ({'crosspost_parent_list': [{'id': 'parent', 'title': 'Original', 'subreddit': 'origin', 'author': 'writer'}]}, 'crosspost'),
             ({'is_video': True, 'media': {'reddit_video': {'fallback_url': 'https://v.redd.it/a'}}}, 'video'),
             ({'is_self': True}, 'self'), ({'post_hint': 'image'}, 'image')]
    for data, expected in cases:
        post = build_post({'id': 'a', **data}).to_dict()
        assert post['post_type'] == expected
    assert build_post({'id': 'a', **cases[0][0]}).media[0]['caption'] == 'First'
    assert build_post({'id': 'a', **cases[2][0]}).crosspost['fullname'] == 't3_parent'
