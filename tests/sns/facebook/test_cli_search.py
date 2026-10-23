"""search through the real cli.py and a fake Aside."""
import json

from tests.sns.facebook.scenes import (known_tab, look, page_result, queries, query_result, rerun, run, story)


def results_body(edges, has_next=True, cursor='S1'):
    return json.dumps({'data': {'serpResponse': {'results': {
        'edges': edges, 'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}}}})


def person(identity, name='Sample Person', verified=None):
    profile = {'__typename': 'User', 'id': identity, 'name': name, 'url': f'https://www.facebook.com/p.{identity}'}
    if verified is not None:
        profile['is_verified'] = verified
    return {'node': {'role': 'ENTITY_USER', '__typename': 'SearchRenderable'},
            'rendering_strategy': {'view_model': {'profile': profile}}}


def test_people_search_lists_entities_with_their_next_argument(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([person('500', verified=True), person('501')])))
    code, out, _ = run(browser, 'search', 'Sample Person', '--type', 'people', '--limit', '2')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'facebook search · type=people · 2 shown · stopped=limit_reached · requests=1'
    assert lines[1] == '[e1] person id=500 · Sample Person · verified · url: "https://www.facebook.com/p.500"'
    assert lines[2] == '[e2] person id=501 · Sample Person · verified=? · url: "https://www.facebook.com/p.501"'
    sent = queries(browser)[0]['args']
    assert sent['name'] == 'SearchCometResultsPaginatedResultsQuery'
    assert sent['variables']['args']['text'] == 'Sample Person'
    assert sent['variables']['args']['experience']['type'] == 'PEOPLE_TAB'
    assert lines[-1].endswith("facebook search 'Sample Person' --type people --limit 2 --after " + lines[-1].split()[-1])


def test_top_search_mixes_posts_and_entities_in_order(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([person('510'), {'node': {**story('SF1'),
                                                                                         '__typename': 'Story'}}],
                                                                has_next=False)))
    code, out, _ = run(browser, 'search', 'ai')
    assert code == 0
    assert [line.split(' ')[0] for line in out.splitlines() if line.startswith('[')] == ['[e1]', '[p1]']


def test_search_continues_from_its_cursor(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([person('1')], cursor='S1')))
    code, out, _ = run(browser, 'search', 'x', '--type', 'people', '--limit', '1')
    look(browser).respond('facebook.query', query_result(results_body([person('2')], has_next=False)))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 0 and 'id=2' in out
    assert queries(browser)[1]['args']['variables']['cursor'] == 'S1'


def test_option_like_search_text_goes_after_a_double_dash(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([person('1')], cursor='S1')))
    code, out, _ = run(browser, 'search', '--type', 'people', '--limit', '1', '--', '-dash')
    assert code == 0 and out.splitlines()[-1].endswith(' -- -dash')


def test_empty_search_text_is_refused(browser):
    code, out, _ = run(browser, 'search', '   ')
    assert code == 2 and browser.calls() == []


def test_recent_and_date_filters_are_sent_as_facebooks_filter_strings(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([{'node': {**story('SF1'), '__typename': 'Story'}}],
                                                                has_next=False)))
    code, out, _ = run(browser, 'search', 'ai', '--type', 'posts', '--recent', '--since', '2026-09-01', '--until',
                       '2026-09-30', '--json')
    result = json.loads(out)
    assert code == 0 and result['window']['since'] == '2026-09-01' and result['window']['until'] == '2026-09-30'
    assert result['window']['coverage'] == 'closed (server-filtered)'
    filters = [json.loads(f) for f in queries(browser)[0]['args']['variables']['args']['filters']]
    assert filters[0] == {'name': 'recent_posts', 'args': ''}
    assert filters[1]['name'] == 'creation_time'
    assert json.loads(filters[1]['args']) == {'start_year': '2026', 'start_month': '2026-09', 'end_year': '2026',
                                              'end_month': '2026-09', 'start_day': '2026-09-01', 'end_day': '2026-09-30'}


def test_filters_continue_with_the_same_filters(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([{'node': {**story('SF1'), '__typename': 'Story'}}])))
    code, out, _ = run(browser, 'search', 'ai', '--type', 'posts', '--recent', '--limit', '1')
    assert out.splitlines()[-1].split('facebook search ', 1)[1].startswith('ai --type posts --recent --limit 1 --after ')


def test_post_filters_need_a_post_vertical(browser):
    for args in (['--type', 'people', '--recent'], ['--type', 'groups', '--since', '2026-01-01']):
        code, out, _ = run(browser, 'search', 'x', *args)
        assert code == 2 and 'posts' in json.loads(out)['message']
    assert browser.calls() == []


def test_search_inside_one_group(browser):
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/groups/examplegroup/',
                                                 '<script>{"groupID":"700"}</script>'))
    browser.respond('facebook.query', query_result(results_body([{'node': {**story('G1'), '__typename': 'Story'}}],
                                                                has_next=False)))
    code, out, _ = run(browser, 'search', 'pandas', '--in-group', 'examplegroup', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['G1'] and result['request_count'] == 2
    args = queries(browser)[0]['args']['variables']
    assert args['args']['callsite'] == 'comet:scoped:group' and args['renderLocation'] == 'group_serp'
    assert args['args']['experience']['type'] == 'GROUPS_SCOPED' and args['args']['experience']['fbid'] == '700'


def test_in_group_search_is_for_posts(browser):
    code, out, _ = run(browser, 'search', 'x', '--type', 'people', '--in-group', '700')
    assert code == 2 and browser.calls() == []


def test_a_result_with_no_date_is_left_out_of_a_dated_search_and_counted(browser):
    """Intended change (one window unit): the people of a mixed top search have no date to place in the window."""
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([person('510'), {'node': {**story('SF1'),
                                                                                         '__typename': 'Story'}}],
                                                                has_next=False)))
    code, out, _ = run(browser, 'search', 'ai', '--since', '2026-01-01', '--json')
    result = json.loads(out)
    assert [r['id'] for r in result['results']] == ['SF1']
    assert '1 undated record left out: no date places it in the window' in result['coverage']


def module(kind, entities):
    """A top search module (observed 2026-10-21): a titled list of entities whose kind Facebook names in the module's
    see-more type, not in the entities (a page arrives as a User)."""
    return {'node': {'role': 'MODULE', '__typename': 'SearchRenderable'}, 'rendering_strategy': {
        '__typename': 'SearchListCellListModuleRenderingStrategy',
        'view_model': {'__typename': 'SearchSimpleModuleViewModel', 'title': '그룹',
                       'see_more_model': {'type': kind, 'label': 'See all'}},
        'result_rendering_strategies': [
            {'__typename': 'XFBSearchListCellProfileRenderingStrategy',
             'view_model': {'__typename': 'SearchProfileViewModel', 'profile': profile}} for profile in entities]}}


def entity(typename, identity):
    return {'__typename': typename, 'id': identity, 'name': f'Name {identity}',
            'url': f'https://www.facebook.com/e.{identity}'}


def test_a_top_page_of_entity_modules_lists_each_entity_with_the_kind_its_module_names(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(results_body([
        module('browse_type_group', [entity('Group', '601')]),
        module('browse_type_profile_with_biz_tools', [entity('User', '602'), entity('User', '603')]),
        module('browse_type_user', [entity('User', '604')])], has_next=False)))
    code, out, _ = run(browser, 'search', 'sample', '--json')
    result = json.loads(out)
    assert code == 0, result
    assert [(r['kind'], r['id']) for r in result['results']] == [('group', '601'), ('page', '602'), ('page', '603'),
                                                                  ('person', '604')]


def deferred(chunks):
    return query_result('\n'.join(json.dumps(c) for c in chunks))


def test_an_entity_of_a_module_that_arrives_in_a_later_piece_keeps_the_modules_kind(browser):
    """Found by review: a top-search entity delivered as a deferred piece into its module lost the module's see-more
    type and was called a person although the module lists pages."""
    piece = {'path': ['serpResponse', 'results', 'edges', 0, 'rendering_strategy', 'result_rendering_strategies', 0],
             'data': {'view_model': {'profile': entity('User', '602')}}}
    known_tab(browser)
    browser.respond('facebook.query', deferred([json.loads(results_body([
        module('browse_type_profile_with_biz_tools', []), {'node': {**story('POST1'), '__typename': 'Story'}}],
        has_next=False)), piece]))
    code, out, _ = run(browser, 'search', 'sample', '--json')
    result = json.loads(out)
    assert code == 0, out
    assert [(r.get('kind'), r['id']) for r in result['results']] == [('page', '602'), ('post', 'POST1')]


def test_an_entity_repeated_in_a_later_piece_is_listed_once(browser):
    piece = {'path': ['serpResponse', 'results', 'edges', 0, 'rendering_strategy', 'result_rendering_strategies', 0],
             'data': {'view_model': {'profile': entity('User', '602')}}}
    known_tab(browser)
    browser.respond('facebook.query', deferred([json.loads(results_body([
        module('browse_type_profile_with_biz_tools', [entity('User', '602')])], has_next=False)), piece]))
    code, out, _ = run(browser, 'search', 'sample', '--json')
    assert [(r['kind'], r['id']) for r in json.loads(out)['results']] == [('page', '602')]


def test_a_modules_kind_that_arrives_in_a_later_piece_applies_to_its_entities(browser):
    """Found by the second review: the module's see-more type itself came in a later piece (at the edge's
    rendering_strategy), and the entity already delivered was called a person."""
    edge = module('browse_type_profile_with_biz_tools', [entity('User', '602')])
    edge['rendering_strategy']['view_model'].pop('see_more_model')
    piece = {'path': ['serpResponse', 'results', 'edges', 0, 'rendering_strategy'],
             'data': {'view_model': {'see_more_model': {'type': 'browse_type_profile_with_biz_tools'}}}}
    known_tab(browser)
    browser.respond('facebook.query', deferred([json.loads(results_body([edge], has_next=False)), piece]))
    code, out, _ = run(browser, 'search', 'sample', '--json')
    assert [(r['kind'], r['id']) for r in json.loads(out)['results']] == [('page', '602')], out
