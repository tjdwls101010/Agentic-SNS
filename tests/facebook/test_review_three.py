"""Final-review cases: comments and About keep what a response could not deliver visible, files keep coverage, and the
documentation says what the code does."""
import json


from tests.facebook.helpers import (POST_URL, Account, about_overview, about_section, chunks,
                                    comment_node, comment_page, envelope, login, post_response, story_id_page)

COLLECTIONS = [('work', 'Work'), ('education', 'Education')]


def opened(*pages):
    return [login(), story_id_page(), post_response(), *pages]


def test_a_comment_without_an_author_is_still_a_comment(tmp_path):
    ghost = comment_node('c1')
    ghost['author'] = None
    result = Account(tmp_path).run('comments', POST_URL, '--json', responses=opened(comment_page([ghost])))
    assert result.code == 0 and result.ids == ['c1'] and result.data['results'][0]['author_name'] is None


def test_a_nonempty_comment_page_with_nothing_readable_is_a_failure_not_empty(tmp_path):
    page = envelope({'data': {'node': {'comments': {'edges': [{'node': {'unknown': 'shape'}}],
                                                    'page_info': {'has_next_page': False}}}}})
    result = Account(tmp_path).run('comments', POST_URL, '--json', responses=opened(page))
    assert result.code == 6 and result.data['error'] == 'failed'


def test_an_unknown_reply_count_still_uses_the_reply_handle(tmp_path):
    parent = comment_node('c1')
    parent['feedback']['replies_fields']['total_count'] = None
    result = Account(tmp_path).run('comments', POST_URL, '--replies', '--json', responses=opened(
        comment_page([parent]), comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')))
    assert result.code == 0 and result.ids == ['c1', 'r1']


def test_a_comment_page_error_on_a_read_field_reaches_coverage(tmp_path):
    body = chunks(json.loads(comment_page([comment_node('c1')])['body']),
                  {'errors': [{'message': 'x', 'path': ['node', 'comments', 'edges', 0, 'node', 'body']}],
                   'data': {'node': {}}})
    result = Account(tmp_path).run('comments', POST_URL, '--json', responses=opened(body))
    assert result.code == 0
    assert result.data['coverage'] == ['Facebook reported errors for part of this response; '
                                       'some records may lack fields']


def test_about_does_not_call_a_section_absent_over_an_incomplete_response(tmp_path):
    overview = chunks(json.loads(about_overview([about_section('directory_bio', 'Bio')])['body']),
                      {'errors': [{'message': 'x', 'path': ['user', 'about_app_sections', 'nodes', 1, 'title']}],
                       'data': {'user': {}}})
    result = Account(tmp_path).run('about', '42', '--section', 'directory_work', '--json', responses=[login(), overview])
    assert "not in this profile's visible About" not in json.dumps(result.data)
    assert 'Facebook reported errors for part of this response; some records may lack fields' in result.data['coverage']


def test_a_patch_to_a_field_the_record_reads_counts_by_its_destination(tmp_path):
    from datetime import UTC, datetime
    from facebook.graphql.records import post_page
    raw = '\n'.join(json.dumps(o) for o in [
        {'data': {'node': {'feedback': {'id': 'p'}, 'actors': [{'name': 'Someone'}]}}},
        {'path': ['node', 'actors', 0], 'data': {'id': '42'}}]).encode()
    page = post_page(raw, source='timeline', connection_key='x', captured_at=datetime(2026, 9, 5, tzinfo=UTC))
    assert page.records[0]['incomplete'] is True


def test_output_summary_and_file_keep_coverage(tmp_path):
    replies = json.loads(comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')['body'])
    replies['data']['node']['replies_connection']['page_info'] = {'has_next_page': True, 'end_cursor': 'more'}
    path = tmp_path / 'c.ndjson'
    result = Account(tmp_path).run('comments', POST_URL, '--replies', '--out', str(path), responses=opened(
        comment_page([comment_node('c1')]), envelope(replies)))
    assert result.code == 0
    note = 'replies to c1: first batch only; Facebook offers no further reply page here'
    assert f' · coverage: {note}' in result.stdout
    markers = [json.loads(line) for line in path.read_text().splitlines() if '"kind":"page"' in line]
    assert markers[-1]['coverage'] == [note]


def test_schema_out_names_the_real_page_marker_and_the_comment_limit(tmp_path):
    out = Account(tmp_path).run('schema', 'out').data['results'][0]
    assert 'no "id"' in out['control_records']['page']
    assert 'about' not in out['records']
    assert 'parent comments' in out['resume']


def test_help_and_schema_state_what_the_code_does(tmp_path):
    account = Account(tmp_path)
    about_help = account.run('about', '--help').stdout
    assert '--section stops' in ' '.join(about_help.split())
    comments_help = ' '.join(account.run('comments', '--help').stdout.split())
    assert 'parent comments' in comments_help and 'counts' in comments_help
    post = account.run('schema', 'post').data['results'][0]['fields']
    assert 'never edited' not in post['edited_at']
    result = account.run('schema', 'result').data['results'][0]
    assert 'feed' in result['text_markers']['sponsored']
    assert result['text_markers']['unavailable'].startswith('the value in that place was not sent')
    assert 'reading commands' in result['description']


def test_doctor_names_the_cache_and_which_files_are_protection_state(tmp_path):
    account = Account(tmp_path)
    doctor = account.run('doctor', responses=[login()]).data['results'][0]
    assert doctor['cache_dir'] == str(account.home)
    assert set(doctor['protection_state']) == {'blocked.json', 'pace.json', 'account.lock'}
    assert doctor['holds_personal_data'] == ['cursors/']


def test_a_nonempty_reply_page_with_nothing_readable_is_a_retryable_failure(tmp_path):
    unreadable = envelope({'data': {'node': {'replies_connection': {'edges': [{'node': {'unknown': 'shape'}}],
                                                                    'page_info': {'has_next_page': False}}}}})
    result = Account(tmp_path).run('comments', POST_URL, '--replies', '--json', responses=opened(
        comment_page([comment_node('c1')]), unreadable))
    assert result.code == 8 and result.ids == ['c1'] and result.data['next']
    assert result.data['replies_incomplete'][0]['retryable'] is True


def test_an_error_on_an_about_container_keeps_the_section_open(tmp_path):
    overview = chunks(json.loads(about_overview([about_section('directory_bio', 'Bio')])['body']),
                      {'errors': [{'message': 'partial', 'path': ['user', 'about_app_sections']}], 'data': {'user': {}}})
    result = Account(tmp_path).run('about', '42', '--section', 'directory_work', '--json', responses=[login(), overview])
    assert "not in this profile's visible About" not in json.dumps(result.data)


def test_post_keeps_the_issues_of_its_comment_batch(tmp_path):
    body = chunks(json.loads(comment_page([comment_node('c1')])['body']),
                  {'errors': [{'message': 'x', 'path': ['node', 'comments', 'edges', 0, 'node', 'body']}],
                   'data': {'node': {}}})
    result = Account(tmp_path).run('post', POST_URL, '--json', responses=opened(body))
    assert result.code == 0
    assert result.data['coverage'] == ['Facebook reported errors for part of this response; '
                                       'some records may lack fields']
