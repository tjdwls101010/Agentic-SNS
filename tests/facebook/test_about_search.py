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
    assert result.stdout.splitlines()[1:] == ['directory_bio: Synthetic⏎bio (unavailable)']


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
        'search · 1 shown · stopped=exhausted',
        '[e1] page id=synthetic-page · Synthetic Page · verified=? · url: "https://www.facebook.com/synthetic-page"']


def test_nonempty_search_connection_with_unreadable_results_is_a_failure(tmp_path):
    body = envelope({'data': {'serpResponse': {'results': {'edges': [{'node': {'unknown': 'shape'}}],
                                                           'page_info': {'has_next_page': False}}}}})
    assert Account(tmp_path).run('search', 'synthetic', '--type', 'people', responses=[login(), body]).code == 6


def test_empty_search_text_is_rejected_before_any_request(tmp_path):
    result = Account(tmp_path).run('search', '   ')
    assert result.code == 2 and result.calls == []
    assert json.loads(result.stdout)['message'] == 'Search text must not be empty.'
