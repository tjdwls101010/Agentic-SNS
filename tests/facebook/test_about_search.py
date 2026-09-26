"""About fields across their collections, and search results in the server's own order."""
import json

import pytest

from tests.facebook.helpers import (LIMITED, Account, about_collection, about_overview, about_section, chunks,
                                    entity, envelope, login, profile_page, search_page, story)


def test_about_reads_the_overview_then_every_collection(tmp_path):
    result = Account(tmp_path).run('about', '42', '--json', responses=[
        login(), about_overview([about_section('directory_bio', 'Synthetic bio')],
                                [('work', 'Work'), ('education', 'Education')]),
        about_collection(about_section('directory_work', 'Synthetic Work', url='https://example.test/work')),
        about_collection(about_section('directory_college', 'Synthetic College'))])
    assert result.code == 0
    assert [(r['section'], r['collection'], r['text']) for r in result.data['results']] == [
        ('directory_bio', None, 'Synthetic bio'), ('directory_work', 'Work', 'Synthetic Work'),
        ('directory_college', 'Education', 'Synthetic College')]
    tokens = [call['args']['variables']['collectionToken'] for call in result.calls if call['name'] == 'graphql']
    assert tokens == [None, 'work', 'education']
    variables = result.graphql()['variables']
    assert variables['userID'] == variables['pageID'] == '42'
    assert variables['sectionToken'] == 'YXBwX3NlY3Rpb246NDI6MjMyNzE1ODIyNw=='  # app_section:42:2327158227


def test_about_section_filter_and_text_rendering(tmp_path):
    result = Account(tmp_path).run('about', '42', '--section', 'directory_bio', responses=[
        login(), about_overview([about_section('directory_bio', 'Synthetic\nbio')], [('work', 'Work')]),
        about_collection(about_section('directory_work', 'Synthetic Work'))])
    assert result.code == 0
    assert result.stdout.splitlines()[1:] == ['directory_bio: Synthetic⏎bio']


def test_about_reports_partial_collection_failure_and_stops_on_block(tmp_path):
    account = Account(tmp_path)
    result = account.run('about', '42', '--json', responses=[
        login(), about_overview([about_section('directory_bio', 'Synthetic bio')],
                                [('work', 'Work'), ('education', 'Education')]), LIMITED])
    assert result.code == 5, result.stdout
    assert result.data['results'][0]['section'] == 'directory_bio'
    assert result.data['failed_sections'][0]['section'] == 'Work'
    assert len(result.calls) == 3 and account.blocked()


def test_about_resolves_a_vanity_name_first(tmp_path):
    result = Account(tmp_path).run('about', 'synthetic.vanity', '--json', responses=[
        login(), profile_page('77'), about_overview([about_section('directory_bio', 'Bio')])])
    assert result.code == 0 and result.snippets == ['tokens', 'page', 'graphql']
    assert result.data['results'][0]['profile_id'] == '77'


def test_top_search_preserves_mixed_server_order(tmp_path):
    nodes = [entity('group-first', 'Group'), {'__typename': 'Story', **story('post-second')}]
    result = Account(tmp_path).run('search', 'synthetic', '--type', 'top', '--limit', '2', '--json',
                                   responses=[login(), search_page(nodes)])
    assert result.code == 0 and result.ids == ['group-first', 'post-second']


@pytest.mark.parametrize('deferred', [False, True])
def test_top_search_nodes_and_deferred_result_positions_keep_server_order(tmp_path, deferred):
    group = entity('first-group', 'Group')
    post = {'__typename': 'Story', **story('second-post')}
    connection = {'nodes': [group, post], 'page_info': {'has_next_page': False, 'end_cursor': None}}
    if deferred:
        connection['nodes'] = [{}]
        body = chunks({'data': {'serpResponse': {'results': connection}}},
                      {'path': ['serpResponse', 'results', 'nodes', 1], 'data': post},
                      {'path': ['serpResponse', 'results', 'nodes', 0], 'data': group})
    else:
        body = chunks({'data': {'serpResponse': {'results': connection}}})
    result = Account(tmp_path).run('search', 'synthetic', '--type', 'top', '--limit', '2', '--json',
                                   responses=[login(), body])
    assert result.code == 0 and result.ids == ['first-group', 'second-post']


def test_search_entities_render_as_dense_rows(tmp_path):
    page = search_page([{'__typename': 'Page', 'id': 'synthetic-page', 'name': 'Synthetic Page',
                         'url': 'https://www.facebook.com/synthetic-page'}])
    result = Account(tmp_path).run('search', 'synthetic', '--type', 'pages', responses=[login(), page])
    assert result.stdout.splitlines() == [
        'search · type=pages · 1 shown · stopped=exhausted · requests=2/25',
        '[e1] page id=synthetic-page · Synthetic Page · verified=? · url: "https://www.facebook.com/synthetic-page"']


def test_nonempty_search_connection_with_unreadable_results_is_a_failure(tmp_path):
    body = envelope({'data': {'serpResponse': {'results': {'edges': [{'node': {'unknown': 'shape'}}],
                                                           'page_info': {'has_next_page': False}}}}})
    assert Account(tmp_path).run('search', 'synthetic', '--type', 'people', responses=[login(), body]).code == 6


def test_empty_search_text_is_rejected_before_any_request(tmp_path):
    result = Account(tmp_path).run('search', '   ')
    assert result.code == 2 and result.calls == []
    assert json.loads(result.stdout)['message'] == 'Search text must not be empty.'


# --- --section reads only as far as the section ---------------------------------------------------------------------

COLLECTIONS = [('work', 'Work'), ('education', 'Education'), ('places', 'Places')]
FAILURE = envelope('{"errors":[{"message":"Synthetic failure"}]}')


def about(tmp_path, *args, responses):
    return Account(tmp_path).run('about', *args, '--json', responses=[login(), *responses])


def test_a_section_in_the_overview_needs_no_collection(tmp_path):
    result = about(tmp_path, '42', '--section', 'directory_bio', responses=[
        about_overview([about_section('directory_bio', 'Bio')], COLLECTIONS)])
    assert result.code == 0 and [r['section'] for r in result.data['results']] == ['directory_bio']
    assert result.data['request_count'] == 2 and result.left == 0


def test_a_section_stops_at_the_first_collection_that_has_it(tmp_path):
    result = about(tmp_path, '42', '--section', 'directory_work', responses=[
        about_overview([about_section('directory_bio', 'Bio')], COLLECTIONS),
        about_collection(about_section('directory_work', 'Work')), about_collection(about_section('x', 'never'))])
    assert result.code == 0 and [r['text'] for r in result.data['results']] == ['Work']
    assert result.data['stop_reason'] == 'exhausted' and result.data['request_count'] == 3 and result.left == 1


def test_a_section_in_a_later_collection_costs_home_id_overview_and_its_position(tmp_path):
    result = about(tmp_path, 'synthetic.vanity', '--section', 'directory_places', responses=[
        profile_page('42'), about_overview([], COLLECTIONS), about_collection(about_section('directory_work', 'W')),
        about_collection(about_section('directory_college', 'C')), about_collection(about_section('directory_places', 'P'))])
    assert result.code == 0 and [r['text'] for r in result.data['results']] == ['P']
    assert result.data['request_count'] == 1 + 1 + 1 + 3


def test_a_failed_collection_before_the_match_is_reported_as_where_the_section_may_be(tmp_path):
    result = about(tmp_path, '42', '--section', 'directory_college', responses=[
        about_overview([], COLLECTIONS), FAILURE, about_collection(about_section('directory_college', 'C'))])
    assert result.code == 8 and [r['text'] for r in result.data['results']] == ['C']
    assert result.data['coverage'] == ['collection Work failed — the section may be there']


def test_a_section_missing_everywhere_is_said_only_after_every_collection_was_read(tmp_path):
    result = about(tmp_path, '42', '--section', 'directory_family', responses=[
        about_overview([about_section('directory_bio', 'Bio')], COLLECTIONS),
        *[about_collection(about_section('directory_work', 'W')) for _ in COLLECTIONS]])
    assert result.code == 7 and result.data['results'] == []
    assert result.data['coverage'] == ['section directory_family is not in this profile\'s visible About']
    failed = about(tmp_path / 'b', '42', '--section', 'directory_family', responses=[
        about_overview([], COLLECTIONS), FAILURE, about_collection(), about_collection()])
    assert failed.code == 6 and failed.data['coverage'] == ['collection Work failed — the section may be there']


def test_a_block_while_looking_for_a_section_stops_with_the_block(tmp_path):
    result = about(tmp_path, '42', '--section', 'directory_places', responses=[
        about_overview([about_section('directory_bio', 'Bio')], COLLECTIONS), LIMITED])
    assert result.code == 5 and result.data['stop_reason'] == 'blocked'


def test_about_text_shows_a_link_only_when_there_is_one(tmp_path):
    result = Account(tmp_path).run('about', '42', responses=[
        login(), about_overview([about_section('directory_bio', 'Bio'),
                                 about_section('directory_work', 'Work', url='https://www.facebook.com/work')])])
    assert result.code == 0
    assert result.stdout.splitlines()[1:] == ['directory_bio: Bio', 'directory_work: Work ("https://www.facebook.com/work")']
    assert 'unavailable' not in result.stdout
