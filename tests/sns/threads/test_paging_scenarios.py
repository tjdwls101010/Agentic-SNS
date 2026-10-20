"""The pagination and date-window scenarios of fixtures/paging.json (plus profile_access and exit_priority), run through
the real CLI against the scripted Aside: each scenario serves its pages in order as Threads answers, and the shown ids,
the stop, the pages fetched, what a continuation keeps, the window's coverage and the exit code are compared. All
twenty-two are run here, the seven the old suite never executed (Seoul and UTC day edges, a tombstone is not undated,
a surface out of date order never closes, a kept tail then the end, a sample, an empty single batch) included.

Surface per scenario: a chronological one reads the following feed (newest first), a window on anything else a dated
search (Threads' own filter, so a read to the end covers it), a capped one `graph followers`, a single batch `me liked`,
the rest the for-you feed. Intended changes against the abstract file (S2, the plan's natural-stop rules):
- nothing reads on by itself except a window a newest-first surface can close or a server-filtered one; every scenario
  that expects a read to the end passes --limit 1000 (the file's `limit: null` means "to the natural end");
- a budget does not exist: `budget-stop-resumes` is dropped (the resumable stops are the time limit and a hold after
  records, run below);
- the days are judged in the zone the window was made in and keep that span across more: (the Seoul and UTC cases).
"""
import json
from datetime import datetime

import pytest

from tests.sns.threads.data import fixture
from tests.sns.threads.scenes import command_of, known_tab, queries, query_result, run, state

PAGING = fixture('paging.json')
SCENARIOS = {s['name']: s for s in PAGING['scenarios']}
AUTHOR = {'pk': '1000000001', 'username': 'example.author'}
DROPPED = {'budget-stop-resumes': 'there is no request budget (S2): a resumable stop is the time limit or a hold after '
                                  'records, run by test_a_time_limit_after_records_resumes and '
                                  'test_a_429_after_records_is_a_resumable_hold'}


def pk(identity):
    return str(3000000000000000000 + sum(ord(c) * 131 ** i for i, c in enumerate(identity)) % 10 ** 15)


def post(record):
    if record.get('unavailable'):
        return {'pk': pk(record['id']), 'is_post_unavailable': True}
    raw = {'pk': pk(record['id']), 'code': 'C' + record['id'].replace('-', ''), 'user': AUTHOR,
           'caption': {'text': 'post ' + record['id']}, 'text_post_app_info': {}}
    if record.get('created_at'):
        raw['taken_at'] = int(datetime.fromisoformat(record['created_at'].replace('Z', '+00:00')).timestamp())
    if record.get('pinned'):
        raw['text_post_app_info']['pinned_post_info'] = {'is_pinned_to_profile': True}
    return raw


def account(record):
    return {'pk': pk(record['id']), 'username': 'user.' + record['id'].lower()}


def info(page):
    return {'has_next_page': bool(page.get('has_next')), 'end_cursor': page.get('cursor')}


def body(surface, page):
    """The Threads answer for one scripted page of a surface."""
    groups = page.get('groups', [])
    if surface == 'feed':
        edges = [{'node': {'text_post_app_thread': {'thread_items': [{'post': post(r)} for r in g]}}} for g in groups]
        return {'data': {'feedData': {'edges': edges, 'page_info': info(page)}}}
    if surface == 'search':
        edges = [{'node': {'thread': {'thread_items': [{'post': post(r)} for r in g]}}} for g in groups]
        return {'data': {'searchResults': {'edges': edges, 'page_info': info(page)}}}
    if surface == 'graph':
        return {'data': {'fetch__XDTUserDict': {'followers': {'edges': [{'node': account(r)} for g in groups for r in g]}}}}
    edges = [{'node': {'thread_items': [{'post': post(r)} for r in g]}} for g in groups]
    return {'data': {'xdt_text_app_viewer': {'liked_media': {'edges': edges}}}}


def answer(surface, page):
    error = page.get('error')
    if error == 'failed':
        return query_result('oops', status=500)
    if error == 'shape_changed':
        return query_result({'data': {'feedData': None}})
    if error == 'checkpoint':
        return query_result({'errors': [{'code': 368, 'message': 'blocked'}]})
    if error == 'login':
        return query_result({'errors': [{'message': 'login_required'}]})
    assert error is None, error
    return query_result(body(surface, page))


def plan(scenario):
    """(surface, argv, env) of the command that serves a scenario."""
    options = scenario['options']
    window = [word for key in ('since', 'until') if options.get(key) for word in (f'--{key}', options[key])]
    limit = ['--limit', str(options['limit'] or 1000)]
    env = {'TZ': options.get('tz', 'UTC')}
    if options.get('policy') == 'single_batch':
        return 'liked', ['me', 'liked'], env
    if options.get('policy') == 'capped':
        return 'graph', ['graph', '@example.author', 'followers', *limit], env
    if options.get('chronological'):
        return 'feed', ['feed', '--feed', 'following', *window, *(limit if options['limit'] else [])], env
    if window:
        return 'search', ['search', 'words', '--sort', 'recent', *window, *limit], env
    return 'feed', ['feed', *limit], env


def serve(browser, surface, pages):
    known_tab(browser)
    if surface == 'graph':
        browser.respond('threads.query', query_result({'data': {'xdt_text_app_user_by_username': AUTHOR}}))
    for page in pages:
        browser.respond('threads.query', answer(surface, page))


def envelope_of(argv, browser, env):
    code, out, err = run(browser, *argv, '--json', env=env)
    return code, json.loads(out), err


def fetched(browser):
    """Timeline pages asked for: every query but the one that finds the account."""
    return [c for c in queries(browser) if c['args']['name'] != 'BarcelonaProfilePageFallbackQuery']


def names_of(scenario):
    return {pk(r['id']): r['id'] for p in scenario['pages'] for g in p.get('groups', []) for r in g}


def coverage_of(envelope):
    window = envelope.get('window')
    undated = sum(1 for note in envelope.get('coverage', []) if 'undated' in note
                  for _ in range(int(note.split()[0])))
    return (window['coverage'].startswith('closed') if window else None), undated


def scenario_params():
    for name in SCENARIOS:
        if name not in DROPPED and name != 'resume-tail-then-end':
            yield pytest.param(name)


@pytest.mark.parametrize('name', list(scenario_params()))
def test_scenario(name, browser):
    scenario = SCENARIOS[name]
    surface, argv, env = plan(scenario)
    serve(browser, surface, scenario['pages'])
    code, result, err = envelope_of(argv, browser, env)
    expected, names = scenario['expected'], names_of(scenario)
    assert [names[r['id']] for r in result['results']] == expected['shown'], (name, result, err)
    assert code == expected['code'], (name, code, result)
    assert result['stop_reason'] == expected['stop_reason'], (name, result['stop_reason'])
    if 'pages_fetched' in expected:
        assert len(fetched(browser)) == expected['pages_fetched'], (name, [c['args']['name'] for c in queries(browser)])
    if 'window' in expected:
        complete, undated = coverage_of(result)
        assert (complete, undated) == (expected['window']['complete'], expected['window']['undated']), (name, result)
    if 'continues' in expected:
        assert bool(result.get('next')) is expected['continues'], (name, result)
    if expected.get('pending'):
        browser.respond('threads.state', state()).respond('threads.query', answer(surface, {'groups': [], 'has_next': False}))
        again_code, again, _ = envelope_of(words(result['next']), browser, env)
        assert [names[r['id']] for r in again['results']] == expected['pending'], (name, again)  # the kept tail, first
        assert again['stop_reason'] == expected.get('pending_stop_reason', again['stop_reason']), (name, again)
    if 'error' in expected:
        assert result['error'] == 'partial' and result['message'], (name, result)


def words(line):
    """A more: line as the argv `run` takes after the platform word, with --json kept."""
    found = command_of('more: ' + line)
    assert found[0] == 'threads'
    return [*found[1:], '--json'] if '--json' not in found else found[1:]


def test_a_resumed_read_shows_the_kept_tail_first_then_requests_from_the_saved_cursor(browser):
    """resume-tail-then-end: the state the file starts from is exactly what the limit scenario leaves behind."""
    first, second = SCENARIOS['limit-keeps-unshown-tail'], SCENARIOS['resume-tail-then-end']
    surface, argv, env = plan(first)
    serve(browser, surface, first['pages'])
    code, result, _ = envelope_of(argv, browser, env)
    assert [names_of(first)[r['id']] for r in result['results']] == ['A', 'B', 'C']
    browser.respond('threads.state', state()).respond('threads.query', answer(surface, second['pages'][0]))
    code, again, _ = envelope_of(words(result['next']), browser, env)
    expected = second['expected']
    names = {**names_of(first), **names_of(second)}
    assert code == expected['code'] and [names[r['id']] for r in again['results']] == expected['shown'], again
    assert again['stop_reason'] == expected['stop_reason'] and not again.get('next')
    assert [c['args']['variables'].get('after') for c in queries(browser)][-1] == first['pages'][0]['cursor']
    assert len(queries(browser)) == 2  # one request for the whole resumed read


def test_the_dropped_scenario_is_the_one_only_a_budget_could_make():
    assert set(DROPPED) == {'budget-stop-resumes'} and set(DROPPED) <= set(SCENARIOS)


def test_every_scenario_of_the_file_is_run_or_named_as_dropped():
    """The suite once skipped seven of the file's scenarios (appendix C); none may go unrun again."""
    run_names = {p.values[0] for p in scenario_params()} | {'resume-tail-then-end'}
    assert run_names | set(DROPPED) == set(SCENARIOS) and len(SCENARIOS) == 22


# --- the saved window: a continuation judges the days in the zone the window was made in --------------------------------

def test_a_continued_window_keeps_the_span_it_started_with_when_the_zone_changes(browser):
    """The old reader recomputed the local day on every run (appendix C): a window begun in Asia/Seoul and continued
    in UTC would silently move by nine hours. The bounds are saved with the continuation."""
    pages = [{'groups': [[{'id': 'N1', 'created_at': '2026-10-07T14:59:59Z'}], [{'id': 'N2', 'created_at': '2026-10-04T15:00:00Z'}]],
              'has_next': True, 'cursor': 'CUR1'},
             {'groups': [[{'id': 'N3', 'created_at': '2026-10-04T14:59:59Z'}], [{'id': 'N4', 'created_at': '2026-10-04T16:00:00Z'}]],
              'has_next': False, 'cursor': None}]
    known_tab(browser).respond('threads.query', answer('search', pages[0]))
    code, first, _ = envelope_of(['search', 'words', '--since', '2026-10-05', '--until', '2026-10-07', '--limit', '2'],
                                 browser, {'TZ': 'Asia/Seoul'})
    assert code == 0 and first['window']['start_utc'] == '2026-10-04T15:00:00+00:00', first
    sent = queries(browser)[0]['args']['variables']['power_search_info']
    assert (sent['lookback_min_unixtime'], sent['lookback_max_unixtime']) == (1791126000, 1791385200)
    browser.respond('threads.state', state()).respond('threads.query', answer('search', pages[1]))
    code, again, _ = envelope_of(words(first['next']), browser, {'TZ': 'UTC'})
    assert code == 0 and again['window']['start_utc'] == first['window']['start_utc']
    assert again['window']['tz'] == first['window']['tz']
    sent = queries(browser)[-1]['args']['variables']['power_search_info']
    assert (sent['lookback_min_unixtime'], sent['lookback_max_unixtime']) == (1791126000, 1791385200)
    # N1 and N2 are inside the Seoul days; N3 is the day before them, N4 is inside again
    assert [r['id'] for r in first['results']] == [pk('N1'), pk('N2')]
    assert [r['id'] for r in again['results']] == [pk('N4')]
    assert len(queries(browser)) == 2  # the continuation needed a request, so the bounds it sent are the saved ones


# --- profile_access ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('case', PAGING['profile_access']['cases'], ids=lambda c: c['name'])
def test_an_empty_tab_of_a_private_profile_is_unavailable_unless_followed(case, browser):
    profile = {'pk': '1000000001', 'username': 'example.author', **case['profile']}
    known_tab(browser).respond('threads.query', query_result({'data': {'xdt_text_app_user_by_username': profile}}))
    posts = [{'id': f'P{n}', 'created_at': '2026-10-06T10:00:00Z'} for n in range(case['records'])]
    edges = [{'node': {'thread_items': [{'post': post(p)}]}} for p in posts]
    browser.respond('threads.query', query_result({'data': {'mediaData': {'edges': edges, 'page_info': {
        'has_next_page': False, 'end_cursor': None}}}}))
    code, out, _ = run(browser, 'profile', '@example.author', '--json')
    assert code == case['expected']['code'], out


# --- exit_priority ----------------------------------------------------------------------------------------------------

CHECKPOINT_SIGNAL = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'at': 5,
                     'summary': json.dumps({'message': 'checkpoint_required', 'status': 'fail'})}
LOGIN_SIGNAL = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'at': 6,
                'summary': json.dumps({'errors': [{'message': 'login_required'}]})}
RATE_BODY = {'error': {'code': 4, 'message': 'Please wait a few minutes before you try again later.'}}


@pytest.mark.parametrize('answered, code', [
    (query_result(RATE_BODY, signals=[CHECKPOINT_SIGNAL]), 5),                      # a block outranks the limit
    (query_result({'data': {}}, signals=[CHECKPOINT_SIGNAL, LOGIN_SIGNAL]), 5),      # a block outranks a login
    (query_result(RATE_BODY, signals=[LOGIN_SIGNAL]), 5),                           # a hold outranks a login
    (query_result(RATE_BODY), 5),                                                    # the hold before any record
    (query_result('oops', status=500), 6),                                          # any other failure
], ids=['block>limit', 'block>login', 'limit+login', 'limit', 'other'])
def test_when_several_outcomes_apply_the_exit_code_follows_the_priority(answered, code, browser):
    assert PAGING['exit_priority']['order'] == [5, 4, 9, 6]
    known_tab(browser).respond('threads.query', answered)
    assert run(browser, 'feed')[0] == code


def test_a_login_signal_alone_is_exit_4(browser):
    known_tab(browser).respond('threads.query', query_result({'data': {}}, signals=[LOGIN_SIGNAL]))
    assert run(browser, 'feed')[0] == 4


def test_a_tombstone_in_a_list_is_a_record_marker_never_exit_9(browser):
    page = {'groups': [[{'id': 'T1', 'unavailable': True}], [{'id': 'T2', 'created_at': '2026-10-06T10:00:00Z'}]],
            'has_next': False}
    known_tab(browser).respond('threads.query', answer('feed', page))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 0 and [r['unavailable'] for r in json.loads(out)['results']] == [True, False]


# --- the resumable stops that replace the budget ---------------------------------------------------------------------

def test_a_time_limit_after_records_resumes(browser):
    page = {'groups': [[{'id': 'A', 'created_at': '2026-10-06T10:00:00Z'}]], 'has_next': True, 'cursor': 'CUR1'}
    known_tab(browser).respond('threads.query', answer('feed', page))
    browser.respond('threads.query', {'__sleep': 30, **query_result({})})
    code, out, _ = run(browser, 'feed', '--limit', '10', '--json', env={'SNS_DEADLINE_SECONDS': '5'})
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'time_limit' and result['next'] and len(result['results']) == 1, out


def test_a_429_after_records_is_a_resumable_hold(browser, data_dir):
    page = {'groups': [[{'id': 'A', 'created_at': '2026-10-06T10:00:00Z'}]], 'has_next': True, 'cursor': 'CUR1'}
    known_tab(browser).respond('threads.query', answer('feed', page))
    browser.respond('threads.query', query_result('', status=429))
    code, out, _ = run(browser, 'feed', '--limit', '10', '--json')
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'rate_limited' and result['next'], out
    assert result['limit']['scope'] is None  # the whole account, not a named window
