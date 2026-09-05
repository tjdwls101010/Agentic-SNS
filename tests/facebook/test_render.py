from datetime import UTC, datetime
from _post import build_post
from _render import render_posts


NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_dense_post_golden_separates_display_clipping_from_server_truncation():
    post = build_post({'feedback': {'id': 'synthetic-post', 'reaction_count': {'count': 0}},
        'creation_time': 0, 'actors': [{'name': 'Synthetic Author'}],
        'message': {'text': 'One\nTwo more'}}, captured_at=NOW, source='newsfeed')
    text = render_posts([post], chars=7, timezone='Asia/Seoul')
    assert text == ('[p1] Synthetic Author · 1970-01-01T09:00+09:00 · status · reactions=0 comments=? shares=?\n'
                    '     text[7/12 chars, complete]: "One⏎Two…"\n'
                    '     url: unavailable   author: unavailable')


def test_render_mixed_results_replies_and_followup_are_dense():
    from _comment import build_comment
    from _entity import Entity
    from _about import ProfileField
    from _render import render_results
    parent = build_comment({'id': 'synthetic-parent', 'depth': 0, 'body': {'text': 'Parent'}, 'author': {}},
                           post_id='synthetic-post', captured_at=NOW)
    reply = build_comment({'id': 'synthetic-reply', 'depth': 1, 'body': {'text': 'Reply\nline'}, 'author': {},
                           'comment_direct_parent': {'id': parent.id}}, post_id='synthetic-post', captured_at=NOW)
    entity = Entity('page', 'synthetic-page', 'Synthetic Page', None, None, NOW)
    field = ProfileField('synthetic-profile', 'directory_bio', None, None, 'Synthetic\nbio', None, NOW)
    text = render_results([parent, reply, entity, field], command='search', sort='top',
                          stop_reason='exhausted', more='python3 "facebook.py" search synthetic --after 12')
    assert '[c1]' in text and '  [c2 reply-to=c1]' in text
    assert '"Reply⏎line"' in text
    assert '[e1] page id=synthetic-page · Synthetic Page · verified=? · url: unavailable' in text
    assert 'directory_bio: Synthetic⏎bio (unavailable)' in text
    assert text.startswith('search · sort=top · 4 shown · stopped=exhausted\n')
    assert text.endswith('more: python3 "facebook.py" search synthetic --after 12')


def test_nested_shared_chain_renders_every_body_handle_and_truncation():
    from pathlib import Path
    from _parse import parse_story_nodes
    body = (Path(__file__).parent / 'fixtures/nested_shared_chain.ndjson').read_bytes()
    post = build_post(parse_story_nodes([body]).stories['A'], captured_at=NOW, source='newsfeed')
    for value in (post, post.to_dict()):
        text = render_posts([value], chars=None)
        assert 'text[11/11 chars, complete]: "Synthetic B"' in text
        assert 'url: "https://example.test/posts/B"' in text
        assert 'text[15/15 chars, truncated]: "Synthetic C cut"' in text
        assert 'url: "https://example.test/posts/C"' in text
        assert text.index('Synthetic B') < text.index('Synthetic C cut')


def test_shared_rendering_bounds_cycles_for_models_and_dictionaries():
    from _render import render_results
    post = build_post({'feedback': {'id': 'synthetic-cycle'}}, captured_at=NOW, source='newsfeed')
    data = post.to_dict()
    post.shared_post = post
    data['shared_post'] = data
    for value in (post, data):
        text = render_results([value], command='post', chars=None)
        assert 'shared-from: incomplete (cycle)' in text
        assert len(text.splitlines()) < 10


def test_deep_shared_rendering_does_not_recurse_or_silently_drop_the_tail():
    tail = {'id': 'synthetic-tail', 'text': 'Deepest synthetic', 'url': 'https://example.test/tail'}
    root = tail
    for _ in range(1100):
        root = {'text': 'Synthetic wrapper', 'shared_post': root}
    text = render_posts([root], chars=None)
    assert 'text[17/17 chars, complete]: "Deepest synthetic"' in text
    assert 'url: "https://example.test/tail"' in text
    assert 'incomplete (cycle)' not in text
