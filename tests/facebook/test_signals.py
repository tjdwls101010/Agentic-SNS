"""Signal quality, on shapes derived from real responses: incomplete names only the story a problem reaches,
truncated comes only from the post itself, and a comment that is only an attachment says so."""
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from facebook.graphql.records import SCHEMAS, comment_page, post_page, post_record, post_story, search_page
from tests.facebook.helpers import (POST_URL, Account, chunks, envelope, fixture_response, login, story,
                                    story_id_page)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
FIXTURES = Path(__file__).with_name('fixtures')


def lines(name):
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines()]


def ndjson(objects):
    return '\n'.join(json.dumps(o) for o in objects).encode()


def timeline(objects):
    return post_page(ndjson(objects), source='timeline', connection_key='timeline_list_feed_units', captured_at=NOW)


# --- incomplete ------------------------------------------------------------------------------------------------------

def test_page_info_and_video_internals_patches_do_not_make_stories_incomplete():
    page = timeline(lines('live_shape_timeline_patches.ndjson'))
    assert len(page.records) == 3
    assert [r['incomplete'] for r in page.records] == [False, False, False]
    assert page.issues == []
    assert page.page_info is not None


def test_a_patch_carrying_a_field_records_read_marks_only_the_story_it_reaches():
    objects = lines('live_shape_timeline_patches.ndjson')
    patch = copy.deepcopy(objects[1])
    patch['path'] = ['node', 'timeline_list_feed_units', 'edges', 1, 'node', 'comet_sections']
    patch['data'] = {'message': {'text': 'late text'}}
    page = timeline([*objects, patch])
    assert [r['incomplete'] for r in page.records] == [False, True, False]
    assert page.issues == []


def test_a_field_patch_that_reaches_no_story_is_a_page_issue():
    objects = lines('live_shape_timeline_patches.ndjson')
    page = timeline([*objects, {'path': ['elsewhere', 0], 'data': {'message': {'text': 'orphan'}}}])
    assert [r['incomplete'] for r in page.records] == [False, False, False]
    assert page.issues == ['unsupported_path_patch']


def test_an_error_on_a_read_field_marks_its_story_and_a_harmless_one_nothing():
    objects = lines('live_shape_timeline_patches.ndjson')
    harmful = {'errors': [{'message': 'x', 'path': ['node', 'timeline_list_feed_units', 'edges', 0, 'node', 'message']}],
               'data': {'node': {}}}
    harmless = {'errors': [{'message': 'x', 'path': ['node', 'timeline_list_feed_units', 'edges', 2, 'node',
                                                      'encrypted_tracking']}], 'data': {'node': {}}}
    page = timeline([*objects, harmful, harmless])
    assert [r['incomplete'] for r in page.records] == [True, False, False]
    assert page.issues == []
    unplaced = timeline([*objects, {'errors': [{'message': 'x'}], 'data': {'node': {}}}])
    assert [r['incomplete'] for r in unplaced.records] == [False, False, False]
    assert unplaced.issues == ['graphql_errors']


def test_page_issues_reach_the_coverage_line_of_a_feed(tmp_path):
    body = chunks({'data': {'viewer': {'news_feed': {'edges': [{'node': story('p1')}],
                                                     'page_info': {'has_next_page': False}}}}},
                  {'errors': [{'message': 'partial'}], 'data': {'viewer': {}}})
    result = Account(tmp_path).run('feed', '--json', responses=[login(), body])
    assert result.code == 0 and result.data['results'][0]['incomplete'] is False
    assert result.data['coverage'] == ['Facebook reported errors for part of this response; '
                                       'some records may lack fields']


def test_permalink_issues_reach_the_coverage_line(tmp_path):
    body = chunks({'data': {'node': story('post-feedback')}}, {'errors': [{'message': 'partial'}], 'data': {'node': {}}})
    result = Account(tmp_path).run('post', POST_URL, '--json', responses=[
        login(), story_id_page(), body,
        envelope({'data': {'node': {'comments': {'edges': [], 'page_info': {'has_next_page': False}}}}})])
    assert result.code == 0
    assert result.data['coverage'] == ['Facebook reported errors for part of this response; '
                                       'some records may lack fields']


def test_search_issues_reach_the_coverage_line(tmp_path):
    body = chunks({'data': {'serpResponse': {'results': {'edges': [{'node': story('p1')}],
                                                         'page_info': {'has_next_page': False}}}}},
                  {'path': ['serpResponse', 'nowhere'], 'data': {'message': {'text': 'orphan'}}})
    result = Account(tmp_path).run('search', 'x', '--type', 'posts', '--json', responses=[login(), body])
    assert result.code == 0
    assert result.data['coverage'] == ['part of this response could not be placed on any record; '
                                       'some records may lack fields']
    assert search_page(ndjson([json.loads(line) for line in body['body'].splitlines()]), search_type='posts',
                       captured_at=NOW).issues == ['unsupported_path_patch']


# --- truncated and the post's own fields ---------------------------------------------------------------------------

def test_comments_embedded_in_a_permalink_do_not_mark_the_post_truncated_or_lend_it_their_media():
    raw = (FIXTURES / 'live_shape_permalink_comments.ndjson').read_bytes()
    story_node, issues = post_story(raw)
    post = post_record(story_node, source='permalink', captured_at=NOW)
    assert post['text_truncated'] is False
    node = json.loads(raw)['data']['node']
    comment_urls = {json.dumps(e['node']['attachments']) for e in
                    node['feedback']['comment_rendering_instance_for_feed_location']['comments']['edges']}
    assert post['media'] and not any(m['url'] in text for m in post['media'] for text in comment_urls)


def test_a_post_that_says_its_body_is_cut_is_still_truncated():
    post = post_page((FIXTURES / 'truncated_post.ndjson').read_bytes(), source='timeline', connection_key='x',
                     captured_at=NOW).records[0]
    assert post['text_truncated'] is True


# --- comments that are only an attachment ----------------------------------------------------------------------------

def attachment_comments():
    return comment_page((FIXTURES / 'live_shape_comment_attachments.ndjson').read_bytes(), post_id='p',
                        captured_at=NOW, parents_only=False).records


def test_attachment_only_comments_name_their_attachment_and_a_truly_empty_one_does_not():
    rows = attachment_comments()
    assert [(r['text'] == '', [a['kind'] for a in r['attachments']]) for r in rows] == [
        (True, ['photo']), (True, ['gif']), (False, ['gif']), (False, []), (True, [])]
    assert 'attachments[].kind' in SCHEMAS['comment']['fields']
    assert all('url' not in a for r in rows for a in r['attachments'])


def test_attachment_only_comment_renders_its_kind(tmp_path):
    result = Account(tmp_path).run('comments', POST_URL, responses=[
        login(), story_id_page(), envelope({'data': {'node': story('post-feedback')}}),
        fixture_response('live_shape_comment_attachments.ndjson')])
    text_lines = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith('text[')]
    assert text_lines[0] == 'text[0 of 0 chars shown, complete]: "" · attachment=photo'
    assert text_lines[1] == 'text[0 of 0 chars shown, complete]: "" · attachment=gif'
    assert text_lines[4] == 'text[0 of 0 chars shown, complete]: ""'


def test_feed_with_real_video_patch_shapes_has_no_incomplete_marker(tmp_path):
    objects = lines('live_shape_timeline_patches.ndjson')
    first = copy.deepcopy(objects[0])
    edges = first['data']['node'].pop('timeline_list_feed_units')['edges']
    first['data'] = {'viewer': {'news_feed': {'edges': edges}}}
    patches = [dict(o, path=['viewer', 'news_feed', *o['path'][2:]]) for o in objects[1:]]
    patches[-1]['data']['page_info'] = {'has_next_page': False, 'end_cursor': None}
    result = Account(tmp_path).run('feed', '--json', responses=[login(), envelope(ndjson([first, *patches]).decode())])
    assert result.code == 0, result.stdout
    assert [r['incomplete'] for r in result.data['results']] == [False, False, False]
    assert 'coverage' not in result.data
