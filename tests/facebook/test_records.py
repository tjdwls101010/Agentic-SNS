"""Response → record rules through the public records functions; no request is made here."""
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from facebook.graphql.records import (SCHEMAS, about_collections, about_fields, comment_page, post_page, post_record,
                                      post_story, reply_page, search_page)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
FIXTURES = Path(__file__).with_name('fixtures')
POST_ID = 'ZmVlZGJhY2s6MQ=='


def fixture(name):
    return (FIXTURES / name).read_bytes()


def lines(*values):
    return '\n'.join(json.dumps(v) for v in values).encode()


def posts(raw, source='newsfeed', key='news_feed'):
    return post_page(raw, source=source, connection_key=key, captured_at=NOW)


def record(story, source='newsfeed'):
    return post_record(story, source=source, captured_at=NOW)


# --- decoding and fragment merging ---------------------------------------------------------------------------------

def test_body_is_decoded_from_bytes_not_str():
    page = posts(fixture('basic_status_post.ndjson'))
    assert [r['id'] for r in page.records] == ['fb_001']


def test_ndjson_split_lines_merge_into_one_post():
    page = posts(fixture('split_defer_merge.ndjson'))
    assert [r['id'] for r in page.records] == ['fb_002']
    assert page.records[0]['text'] == 'Post whose fields are split across two synthetic defer-style chunks.'
    assert page.records[0]['reaction_count'] == 42
    assert any(m['kind'] == 'image' for m in page.records[0]['media'])


def test_deferred_fields_merge_and_shared_posts_are_not_top_level():
    first = {'data': {'node': {'feedback': {'id': 'synthetic-post'}, 'message': {'text': 'Synthetic post'},
                               'attached_story': {'feedback': {'id': 'synthetic-share'}}}}}
    second = {'data': {'node': {'feedback': {'id': 'synthetic-post', 'reaction_count': {'count': 42}}}}}
    page = posts(lines(first, second))
    assert [r['id'] for r in page.records] == ['synthetic-post']
    assert page.records[0]['reaction_count'] == 42
    assert page.records[0]['text'] == 'Synthetic post'


def test_id_keyed_lists_merge_by_id_across_fragments():
    first = {'data': {'node': {'feedback': {'id': 'p'}, 'actors': [{'id': '1', 'name': 'Synthetic Actor'}]}}}
    second = {'data': {'node': {'feedback': {'id': 'p'}, 'actors': [
        {'id': '1', 'url': 'https://www.facebook.com/synthetic.actor'}, {'id': '2', 'name': 'Second'}]}}}
    post = posts(lines(first, second)).records[0]
    assert (post['author_id'], post['author_name'], post['author_url']) == (
        '1', 'Synthetic Actor', 'https://www.facebook.com/synthetic.actor')


def test_id_keyed_lists_merge_existing_items_and_keep_new_ones():
    first = {'data': {'node': {'feedback': {'id': 'p'},
                               'attachments': [{'id': 'a1', 'media': {'image': {'uri': 'https://example.test/a.jpg'}}}]}}}
    second = {'data': {'node': {'feedback': {'id': 'p'}, 'attachments': [
        {'id': 'a1', 'media': {'image': {'width': 640}}},
        {'id': 'a2', 'media': {'image': {'uri': 'https://example.test/b.jpg'}}}]}}}
    media = posts(lines(first, second)).records[0]['media']
    assert [(m['url'], m['width']) for m in media] == [('https://example.test/a.jpg', 640),
                                                       ('https://example.test/b.jpg', None)]


def test_lists_without_ids_keep_every_distinct_item_across_fragments():
    first = {'data': {'node': {'feedback': {'id': 'p'},
                               'attachments': [{'media': {'image': {'uri': 'https://example.test/a.jpg'}}}]}}}
    second = {'data': {'node': {'feedback': {'id': 'p'},
                                'attachments': [{'media': {'image': {'uri': 'https://example.test/b.jpg'}}}]}}}
    media = posts(lines(first, second)).records[0]['media']
    assert {m['url'] for m in media} == {'https://example.test/a.jpg', 'https://example.test/b.jpg'}


def test_an_unmergeable_patch_of_a_read_field_marks_the_story_it_reaches():
    body = b'{"data":{"node":{"feedback":{"id":"synthetic-post"}}}}\n'
    patch = b'{"path":["node","feedback"],"data":{"reaction_count":{"count":7}}}\n'
    page = posts(body + patch)
    assert page.issues == []
    assert page.records[0]['incomplete'] is True
    complete = posts(body)
    assert complete.issues == [] and complete.records[0]['incomplete'] is False


def test_unparseable_line_is_skipped_and_reported_for_the_whole_response():
    story, issues = post_story(b'{"data": {"node": {"feedback": {"id": "ok"}}}}\nnot json at all\n')
    assert issues == ['malformed_json']
    post = record(story, source='permalink')
    assert post['id'] == 'ok' and post['incomplete'] is False


def test_comment_feedback_does_not_become_a_post():
    body = json.dumps({'data': {'node': {'id': 'synthetic-comment', 'depth': 0, 'author': {},
                                         'body': {'text': 'Synthetic comment'},
                                         'feedback': {'id': 'synthetic-comment-feedback'}}}}).encode()
    assert posts(body).records == []


def test_comment_preview_is_not_a_top_level_post():
    page = posts(fixture('comment_preview_and_universal_marker.ndjson'))
    assert [r['id'] for r in page.records] == ['fb_007']


def test_several_bodies_in_one_response_are_all_parsed():
    page = posts(fixture('basic_status_post.ndjson') + b'\n' + fixture('truncated_post.ndjson'))
    assert {r['id'] for r in page.records} == {'fb_001', 'fb_005'}


# --- shares ----------------------------------------------------------------------------------------------------------

def test_shared_post_is_not_double_counted_as_top_level():
    page = posts(fixture('shared_post.ndjson'))
    assert [r['id'] for r in page.records] == ['fb_003_wrapper']
    assert page.records[0]['shared_post']['id'] == 'fb_003_shared_original'


def test_shared_post_also_appearing_standalone_is_not_dropped():
    standalone = {'feedback': {'id': 'B'}, 'creation_time': 1}
    wrapper = {'feedback': {'id': 'A'}, 'creation_time': 2, 'attached_story': {'feedback': {'id': 'B'}, 'creation_time': 1}}
    assert {r['id'] for r in posts(lines(standalone, wrapper)).records} == {'A', 'B'}
    assert {r['id'] for r in posts(lines(wrapper, standalone)).records} == {'A', 'B'}


def test_shared_story_gets_deferred_fields_in_parent_view():
    first = {'data': {'node': {'feedback': {'id': 'synthetic-parent'},
                               'attached_story': {'feedback': {'id': 'synthetic-child'}}}}}
    later = {'path': ['node', 'attached_story'], 'data': {
        'feedback': {'id': 'synthetic-child'}, 'message': {'text': 'Synthetic complete share'}}}
    page = posts(lines(first, later))
    assert [r['id'] for r in page.records] == ['synthetic-parent']
    assert page.records[0]['shared_post']['text'] == 'Synthetic complete share'
    assert page.issues == [] and page.records[0]['incomplete'] is False


def test_shared_discovery_does_not_reorder_later_top_level_results():
    assert [r['id'] for r in posts(fixture('shared_top_level_order.ndjson')).records] == ['A', 'C', 'B']


def test_cyclic_share_chain_is_cut_and_reported():
    first = {'data': {'node': {'feedback': {'id': 'A'}, 'attached_story': {'feedback': {'id': 'B'}}}}}
    second = {'data': {'other': {'feedback': {'id': 'B'}, 'attached_story': {'feedback': {'id': 'A'}}}}}
    page = posts(lines(first, second))
    assert 'cyclic_shared_story' in page.issues
    assert page.records[0]['shared_post']['id'] == 'B'


def test_shared_markers_never_leak_to_parent_and_media_links_survive():
    original = {'feedback': {'id': 'synthetic-original'}, 'is_sponsored': True, 'is_pinned_story': True,
                'is_truncated_body': True, 'message': {'text': 'Synthetic original'}}
    post = record({'feedback': {'id': 'synthetic-wrapper'}, 'attached_story': original, 'creation_time': 0,
                   'message_truncation_line_limit': 5}, source='timeline')
    assert post['type'] == 'shared' and post['created_at'] == '1970-01-01T00:00:00Z'
    assert not post['sponsored'] and not post['pinned'] and not post['text_truncated']
    assert post['shared_post']['sponsored'] and post['shared_post']['text_truncated']
    video = posts(fixture('media_and_links.ndjson')).records[0]
    assert video['type'] == 'video'
    assert {m['kind'] for m in video['media']} == {'image', 'video'}
    assert video['links'][0]['title'] == 'Synthetic Article Title'


def test_unidentified_attached_story_keeps_parent_as_incomplete_share():
    post = record({'feedback': {'id': 'synthetic-parent'},
                   'attached_story': {'message': {'text': 'Synthetic unidentifiable share'}}}, source='timeline')
    assert post['type'] == 'shared' and post['shared_post'] is None and post['incomplete']


def test_shared_story_under_identity_free_wrapper_is_discovered_and_attached():
    body = fixture('shared_without_intermediate_id.ndjson')
    page = posts(body)
    assert [r['id'] for r in page.records] == ['A']
    for post in (page.records[0], record(json.loads(body)['data']['node'])):
        assert post['type'] == 'shared' and not post['incomplete']
        assert post['shared_post']['id'] == 'B'
        assert post['shared_post']['text'] == 'Synthetic nested original'
        assert post['shared_post']['url'] == 'https://example.test/posts/B'


# --- post fields -------------------------------------------------------------------------------------------------------

def test_creation_time_uses_exact_story_root_key_not_a_decoy_int():
    by_id = {r['id']: r for r in posts(fixture('pinned_decoy_and_missing_date.ndjson')).records}
    assert by_id['fb_004_pinned']['created_at'] == '2025-06-15T15:13:20Z'  # 1750000400, not the nested decoy
    assert by_id['fb_004_no_date']['created_at'] is None and by_id['fb_004_no_date']['undated'] is True


def test_media_kinds_links_permalink_and_author():
    video = posts(fixture('media_and_links.ndjson')).records[0]
    assert video['links'] == [{'url': 'https://example.com/synthetic-article', 'title': 'Synthetic Article Title',
                               'description': 'A synthetic description of the linked article.'}]
    basic = posts(fixture('basic_status_post.ndjson')).records[0]
    assert basic['url'] == 'https://www.facebook.com/100000000000001/posts/1'
    assert basic['author_name'] == 'Synthetic Alice'
    preview = posts(fixture('comment_preview_and_universal_marker.ndjson')).records[0]
    assert preview['url'] == 'https://www.facebook.com/synthetic.profile/posts/8'


def test_post_preserves_unknown_counts_and_marks_sponsored_pinned_undated():
    post = record({'feedback': {'id': 'synthetic-post', 'reaction_count': {'count': 0}}, 'is_sponsored': True,
                   'is_pinned_story': True, 'incomplete': True, 'message': {'text': 'Synthetic post'}})
    assert post['reaction_count'] == 0
    assert post['comment_count'] is None and post['share_count'] is None
    assert all(post[key] for key in ('sponsored', 'pinned', 'is_pinned', 'undated', 'incomplete'))
    assert post['captured_at'] == '2026-09-05T00:00:00Z'
    assert post['source'] == 'newsfeed'
    assert {'sponsored', 'pinned', 'undated', 'incomplete'} <= set(SCHEMAS['post']['properties'])


def test_invalid_scalar_counts_and_timestamps_are_unknown_not_zero_or_crashes():
    post = record({'feedback': {'id': 'synthetic-post', 'reaction_count': {'count': True}, 'share_count': -1,
                                'comment_rendering_instance': {'comments': {'total_count': False}}},
                   'creation_time': 10**100}, source='timeline')
    assert post['created_at'] is None and post['undated']
    assert post['reaction_count'] is None and post['comment_count'] is None and post['share_count'] is None


def test_capability_keys_are_not_pinned_and_non_null_sponsored_data_is_an_ad():
    post = record({'feedback': {'id': 'synthetic-post'}, 'can_view_pinned_posts': True, 'sponsored_data': {}})
    assert post['pinned'] is False and post['sponsored'] is True


def test_external_link_thumbnail_does_not_classify_as_a_photo():
    story = json.loads(fixture('link_thumbnail.ndjson'))['data']['node']
    post = record(story)
    assert post['type'] == 'link'
    assert post['links'][0]['url'] == 'https://example.test/article'
    assert post['media'][0]['url'] == 'https://example.test/thumbnail.jpg'
    story['attachments'].append({'media': {'image': {'uri': 'https://example.test/photo.jpg'}}})
    assert record(story)['type'] == 'photo'


@pytest.mark.parametrize('kind', ['photo', 'shared'])
def test_projected_live_post_keeps_attachment_type(kind):
    page = posts(fixture(f'live_shape_{kind}.ndjson'), source='group')
    assert [p['type'] for p in page.records] == [kind]
    assert page.records[0]['media'] if kind == 'photo' else page.records[0]['shared_post'] is not None


def test_permalink_story_is_the_requested_root_not_a_decoy():
    body = lines({'data': {'unrelated': {'feedback': {'id': 'decoy'}, 'message': {'text': 'Wrong post'}},
                           'node': {'feedback': {'id': 'post-feedback'}, 'message': None}}},
                 {'path': ['node'], 'data': {'feedback': {'id': 'post-feedback'}, 'message': {'text': 'Deferred'}}})
    story, issues = post_story(body)
    assert record(story, source='permalink')['id'] == 'post-feedback'
    assert record(story, source='permalink')['text'] == 'Deferred'
    assert post_story(lines({'data': {'viewer': {'feedback': {'id': 'x'}}}}))[0] is None


# --- comments ----------------------------------------------------------------------------------------------------------

def comment(node_id, *, depth=0, text='hello', parent=None, replies=0, reactors_count=None, reactors_reduced=None,
            action_link_count=None, expansion=None):
    reactors = {}
    if reactors_count is not None:
        reactors['count'] = reactors_count
    if reactors_reduced is not None:
        reactors['count_reduced'] = reactors_reduced
    node = {'id': node_id, 'depth': depth, 'created_time': 1784342488,
            'author': {'id': '42', 'name': 'A Commenter', 'url': 'https://www.facebook.com/someone'},
            'body': {'text': text},
            'feedback': {'id': f'feedback:{node_id}', 'reaction_count': None, 'reactors': reactors,
                         'replies_fields': {'count': replies, 'total_count': replies}}}
    if parent is not None:
        node['comment_direct_parent'] = {'id': parent}
    if expansion is not None:
        node['feedback']['expansion_info'] = {'expansion_token': expansion}
    if action_link_count is not None:
        node['comment_action_links'] = [{'comment': {'feedback': {'reactors': {'count': action_link_count}}}}]
    return node


def comment_body(*nodes):
    return json.dumps({'data': {'node': {'comments': {'edges': [{'node': n} for n in nodes]}}}}).encode()


def comments(raw, parents_only=False):
    return comment_page(raw, post_id=POST_ID, captured_at=NOW, parents_only=parents_only)


def test_comment_maps_every_field():
    row = comments(comment_body(comment('c1', replies=3, reactors_count=7))).records[0]
    assert row == {'id': 'c1', 'post_id': POST_ID, 'author_name': 'A Commenter',
                   'author_url': 'https://www.facebook.com/someone', 'author_id': '42', 'text': 'hello',
                   'created_at': '2026-07-18T02:41:28Z', 'depth': 0, 'parent_id': None, 'reaction_count': 7,
                   'reply_count': 3, 'attachments': [], 'captured_at': '2026-09-05T00:00:00Z'}
    assert set(SCHEMAS['comment']['properties']) == set(row)


def test_depth_distinguishes_a_reply_from_a_top_level_comment():
    rows = comments(comment_body(comment('c1'), comment('c2', depth=1, parent='c1'))).records
    assert [(r['id'], r['depth'], r['parent_id']) for r in rows] == [('c1', 0, None), ('c2', 1, 'c1')]


@pytest.mark.parametrize('fields,expected', [
    ({'reactors_reduced': '1.2K', 'action_link_count': 1234}, 1234),
    ({'reactors_reduced': '6'}, 6),
    ({'reactors_reduced': '1.2K'}, None),
])
def test_reaction_count_prefers_exact_integers_and_never_guesses_abbreviations(fields, expected):
    assert comments(comment_body(comment('c1', **fields))).records[0]['reaction_count'] == expected


def test_repeated_comments_in_one_response_are_one_comment():
    raw = comment_body(comment('c1'), comment('c2')) + b'\n' + comment_body(comment('c2'), comment('c3'))
    assert [r['id'] for r in comments(raw).records] == ['c1', 'c2', 'c3']


def test_post_shaped_nodes_are_not_comments():
    post_like = {'feedback': {'id': 'feedback:post'}, 'creation_time': 1, 'message': {'text': 'x'}}
    raw = json.dumps({'data': {'node': post_like, 'extra': comment('c1')}}).encode()
    assert [r['id'] for r in comments(raw).records] == ['c1']


def test_parent_page_returns_reply_expansion_handles_beside_records():
    page = comments(comment_body(comment('c1', expansion='TOK'), comment('c2'), comment('r', depth=1, parent='c1')),
                    parents_only=True)
    assert [r['id'] for r in page.records] == ['c1', 'c2']
    assert page.handles == {'c1': {'feedback_id': 'feedback:c1', 'expansion_token': 'TOK'},
                            'c2': {'feedback_id': 'feedback:c2', 'expansion_token': None}}
    assert all('handle' not in key for r in page.records for key in r)


def test_duplicate_parent_references_merge_without_becoming_new_comments():
    parent = {'id': 'synthetic-parent', 'depth': 0, 'author': {'name': 'Synthetic Parent'},
              'body': {'text': 'Synthetic parent'}, 'created_time': 20}
    reply = {'id': 'synthetic-reply', 'depth': 1, 'author': {}, 'body': {'text': 'Synthetic reply'},
             'created_time': 30, 'comment_direct_parent': parent}
    update = dict(parent, feedback={'reactors': {'count': 0}, 'replies_fields': {'total_count': 1}})
    rows = comments(json.dumps({'data': {'comments': [reply, parent, update]}}).encode()).records
    assert [r['id'] for r in rows] == ['synthetic-parent', 'synthetic-reply']
    assert rows[0]['reaction_count'] == 0 and rows[0]['reply_count'] == 1
    assert rows[1]['parent_id'] == 'synthetic-parent' and rows[1]['reaction_count'] is None


def test_comment_invalid_date_and_boolean_counts_stay_unknown():
    node = comment('synthetic-comment', reactors_count=True)
    node['created_time'] = 10**100
    node['feedback']['replies_fields']['total_count'] = False
    row = comments(comment_body(node)).records[0]
    assert row['created_at'] is None and row['reaction_count'] is None and row['reply_count'] is None


def test_reply_page_keeps_only_replies_of_the_requested_parent():
    raw = json.dumps({'data': {'node': {'replies_connection': {
        'edges': [{'node': comment('r1', depth=1)}, {'node': comment('r2', depth=1, parent='other')},
                  {'node': comment('c9')}],
        'page_info': {'has_next_page': True, 'end_cursor': 'more'}}}}}).encode()
    page = reply_page(raw, post_id=POST_ID, parent_id='c1', captured_at=NOW)
    assert [(r['id'], r['parent_id']) for r in page.records] == [('r1', 'c1')]
    assert page.page_info == {'has_next_page': True, 'end_cursor': 'more'}


# --- search entities -----------------------------------------------------------------------------------------------------

def search_body(*nodes):
    return json.dumps({'data': {'serpResponse': {'results': {'edges': [{'node': n} for n in nodes]}}}}).encode()


def searched(raw, search_type):
    return search_page(raw, search_type=search_type, captured_at=NOW).records


def entity(entity_id, typename='User', *, verified=None, name='Someone'):
    node = {'__typename': typename, 'id': entity_id, 'name': name, 'url': f'https://www.facebook.com/{entity_id}'}
    if verified is not None:
        node['is_verified'] = verified
    return node


@pytest.mark.parametrize('search_type,expected', [('people', 'person'), ('pages', 'page')])
def test_entity_kind_comes_from_the_requested_vertical(search_type, expected):
    assert [e['kind'] for e in searched(search_body(entity('1', 'User')), search_type)] == [expected]


def test_top_search_falls_back_to_typename():
    rows = searched(search_body(entity('1', 'Group'), entity('2', 'User')), 'top')
    assert [(e['id'], e['kind']) for e in rows] == [('1', 'group'), ('2', 'person')]


def test_group_typename_is_authoritative_and_nested_users_are_not_group_results():
    group = entity('group-1', 'Group', name='Real Group')
    group['member_preview'] = entity('user-1', 'User', name='Nested Member')
    assert [(e['id'], e['kind']) for e in searched(search_body(group), 'groups')] == [('group-1', 'group')]
    assert [(e['id'], e['kind']) for e in searched(search_body(entity('group-2', 'Group')), 'people')] == [
        ('group-2', 'group')]


def test_repeated_entities_in_one_response_are_one_result():
    raw = search_body(entity('1'), entity('2')) + b'\n' + search_body(entity('2'), entity('3'))
    assert [e['id'] for e in searched(raw, 'people')] == ['1', '2', '3']


def test_entity_fields_map_through_and_missing_verified_is_null():
    row = searched(search_body(entity('42', verified=True, name='A Page')), 'pages')[0]
    assert (row['id'], row['name'], row['verified'], row['url']) == ('42', 'A Page', True,
                                                                     'https://www.facebook.com/42')
    assert searched(search_body(entity('1', 'Group')), 'groups')[0]['verified'] is None
    assert set(SCHEMAS['entity']['properties']) == set(row)


def test_nodes_without_a_url_or_name_are_not_entities():
    assert searched(search_body({'__typename': 'User', 'id': '1'}), 'people') == []


def test_only_result_entities_are_returned_and_explicit_page_wins():
    page = entity('synthetic-page', 'Page')
    page['admin'] = entity('synthetic-admin', 'User')
    post = {'__typename': 'Story', 'feedback': {'id': 'synthetic-post'}, 'actors': [entity('synthetic-author', 'User')]}
    raw = json.dumps({'data': {'viewer': entity('synthetic-viewer', 'User'), 'serpResponse': {'results': {'edges': [
        {'node': page}, {'node': post}, {'node': {'result': entity('synthetic-group', 'Group')}}]}}}}).encode()
    rows = [row for row in searched(raw, 'top') if 'kind' in row]
    assert [(e['id'], e['kind']) for e in rows] == [('synthetic-page', 'page'), ('synthetic-group', 'group')]
    assert rows[0]['verified'] is None


def test_deferred_entity_result_does_not_admit_a_deferred_author():
    parts = [{'path': ['serpResponse', 'results', 'edges', 0, 'node'], 'data': entity('synthetic-result', 'Page')},
             {'path': ['serpResponse', 'results', 'edges', 1, 'node', 'actors', 0],
              'data': entity('synthetic-author', 'User')}]
    assert [e['id'] for e in searched(lines(*parts), 'top')] == ['synthetic-result']
    assert [e['id'] for e in searched(json.dumps({'incremental': parts}).encode(), 'top')] == ['synthetic-result']


def test_entity_in_edge_rendering_strategy_is_a_search_result():
    edge = {'node': {'__typename': 'SearchResult', 'id': 'opaque-result'},
            'rendering_strategy': {'view_model': {
                'profile': {'__typename': 'Group', 'id': '100', 'name': 'Synthetic group',
                            'url': 'https://www.facebook.com/groups/100/'},
                'ctas': {'primary': [{'profile': {'__typename': 'User', 'id': '200', 'name': 'Not a result',
                                                  'url': 'https://www.facebook.com/200'}}]}}}}
    raw = json.dumps({'data': {'serpResponse': {'results': {'edges': [edge]}}}}).encode()
    assert [e['id'] for e in searched(raw, 'groups')] == ['100']


# --- About ---------------------------------------------------------------------------------------------------------------

def test_about_discovers_collections_and_deduplicates_fields_by_section():
    section = {'field_section_type': 'directory_work', 'profile_fields': {'nodes': [
        {'field_type': 'work', 'title': {'text': 'Synthetic Work'}, 'link_url': 'https://example.test/work'}]}}
    body = json.dumps({'data': {'user': {'all_collections': {'nodes': [
        {'id': 'synthetic-work', 'name': '직장'}, {'id': 'synthetic-work', 'name': '직장'}]},
        'sections': [section, section]}}}).encode()
    assert about_collections(body) == [{'id': 'synthetic-work', 'name': '직장'}]
    assert about_fields([body, body], profile_id='synthetic-profile', collection_names=[None, '직장'],
                        captured_at=NOW) == [{'profile_id': 'synthetic-profile', 'section': 'directory_work',
                                              'collection': None, 'field_type': 'work', 'text': 'Synthetic Work',
                                              'url': 'https://example.test/work',
                                              'captured_at': '2026-09-05T00:00:00Z'}]
    assert SCHEMAS['about']['title'] == 'ProfileField'


# --- fixtures and their tools (no production code) -----------------------------------------------------------------

def test_every_fixture_line_is_valid_json():
    for path in FIXTURES.glob('*.ndjson'):
        for line in path.read_text().splitlines():
            json.loads(line)


def test_fixture_derivation_preserves_structure_without_source_values(tmp_path):
    source = tmp_path / 'capture.ndjson'
    output = tmp_path / 'fixture.ndjson'
    source.write_text(json.dumps({'data': {'node': {'__typename': 'Page', 'id': 'private-id',
        'name': 'Private Person', 'url': 'https://scontent.example.fbcdn.net/private?token=secret',
        'text': 'private@example.com', 'is_verified': True, 'count': 25, 'unknown': None}}}) + '\n')
    tools = Path(__file__).with_name('tools')
    run = subprocess.run([sys.executable, str(tools / 'derive_fixture.py'), str(source), str(output)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    derived = output.read_text()
    assert all(value not in derived for value in ['Private Person', 'private-id', 'private@example.com', 'secret', 'fbcdn'])
    node = json.loads(derived)['data']['node']
    assert node['__typename'] == 'Page' and node['is_verified'] is True
    assert type(node['count']) is int and node['unknown'] is None
    gate = tools / 'check_fixtures_pii.py'
    assert subprocess.run([sys.executable, str(gate), str(output)], capture_output=True).returncode == 0
    assert subprocess.run([sys.executable, str(gate), str(source)], capture_output=True).returncode == 1
