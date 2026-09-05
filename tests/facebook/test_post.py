from datetime import UTC, datetime
from _post import build_post, json_schema


NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_post_preserves_unknown_counts_and_marks_sponsored_pinned_undated():
    post = build_post({'feedback': {'id': 'synthetic-post', 'reaction_count': {'count': 0}},
                       'is_sponsored': True, 'is_pinned_story': True, 'incomplete': True,
                       'message': {'text': 'Synthetic post'}}, captured_at=NOW, source='newsfeed')
    data = post.to_dict()
    assert data['reaction_count'] == 0
    assert data['comment_count'] is None and data['share_count'] is None
    assert all(data[key] for key in ('sponsored', 'pinned', 'is_pinned', 'undated', 'incomplete'))
    assert data['captured_at'] == '2026-09-05T00:00:00Z'
    assert data['source'] == 'newsfeed'
    assert {'sponsored', 'pinned', 'undated', 'incomplete'} <= set(json_schema()['properties'])


def test_shared_markers_never_leak_to_parent_and_media_links_survive():
    original = {'feedback': {'id': 'synthetic-original'}, 'is_sponsored': True,
                'is_pinned_story': True, 'is_truncated_body': True,
                'message': {'text': 'Synthetic original'}}
    post = build_post({'feedback': {'id': 'synthetic-wrapper'}, 'attached_story': original,
                       'creation_time': 0, 'message_truncation_line_limit': 5},
                      captured_at=NOW, source='timeline')
    assert post.type == 'shared' and post.created_at.year == 1970
    assert not post.sponsored and not post.pinned and not post.text_truncated
    assert post.shared_post.sponsored and post.shared_post.text_truncated
    from pathlib import Path
    from _parse import parse_story_nodes
    body = (Path(__file__).parent / 'fixtures/media_and_links.ndjson').read_bytes()
    story = parse_story_nodes([body]).stories['fb_006']
    media_post = build_post(story, captured_at=NOW, source='timeline')
    assert media_post.type == 'video'
    assert {m.kind for m in media_post.media} == {'image', 'video'}
    assert media_post.links[0].title == 'Synthetic Article Title'


def test_invalid_scalar_counts_and_timestamps_are_unknown_not_zero_or_crashes():
    post = build_post({'feedback': {'id': 'synthetic-post', 'reaction_count': {'count': True},
                       'share_count': -1, 'comment_rendering_instance': {'comments': {'total_count': False}}},
                       'creation_time': 10**100}, captured_at=NOW, source='timeline')
    assert post.created_at is None and post.undated
    assert post.reaction_count is None and post.comment_count is None and post.share_count is None


def test_unidentified_attached_story_keeps_parent_as_incomplete_share():
    post = build_post({'feedback': {'id': 'synthetic-parent'},
        'attached_story': {'message': {'text': 'Synthetic unidentifiable share'}}},
        captured_at=NOW, source='timeline')
    assert post.type == 'shared'
    assert post.shared_post is None
    assert post.incomplete


def test_capability_keys_are_not_pinned_and_non_null_sponsored_data_is_an_ad():
    post = build_post({'feedback': {'id': 'synthetic-post'}, 'can_view_pinned_posts': True,
                       'sponsored_data': {}}, captured_at=NOW, source='newsfeed')
    assert post.pinned is False
    assert post.sponsored is True


def test_shared_story_under_identity_free_wrapper_is_discovered_and_attached():
    import json
    from pathlib import Path
    from _parse import parse_story_nodes
    body = (Path(__file__).parent / 'fixtures/shared_without_intermediate_id.ndjson').read_bytes()
    parsed = parse_story_nodes([body])
    assert set(parsed.stories) == {'A', 'B'}
    assert parsed.top_level_ids() == ['A']
    for story in (parsed.stories['A'], json.loads(body)['data']['node']):
        post = build_post(story, captured_at=NOW, source='newsfeed')
        assert post.type == 'shared' and not post.incomplete
        assert post.shared_post.id == 'B'
        assert post.shared_post.text == 'Synthetic nested original'
        assert post.shared_post.url == 'https://example.test/posts/B'


def test_external_link_thumbnail_does_not_classify_as_a_photo():
    import json
    from pathlib import Path
    body = (Path(__file__).parent / 'fixtures/link_thumbnail.ndjson').read_bytes()
    story = json.loads(body)['data']['node']
    post = build_post(story, captured_at=NOW, source='newsfeed')
    assert post.type == 'link'
    assert post.links[0].url == 'https://example.test/article'
    assert post.media[0].url == 'https://example.test/thumbnail.jpg'
    story['attachments'].append({'media': {'image': {'uri': 'https://example.test/photo.jpg'}}})
    assert build_post(story, captured_at=NOW, source='newsfeed').type == 'photo'
