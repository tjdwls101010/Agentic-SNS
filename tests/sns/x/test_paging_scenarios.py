"""The pagination and date-window scenarios of fixtures/paging.json (plus profile_access and exit_priority), run through
the real CLI against the scripted Aside: each scenario serves its pages in order as X timeline answers and the shown
ids, the stop, the pages fetched, what a continuation keeps, the window's coverage and the exit code are compared.

Surface per scenario: a chronological window reads the profile posts tab (newest first), any other window the media tab
(finite), an account list `graph followers`, a search window `search … since:/until:`, a single batch `trends foryou`,
the rest a list's posts. Intended changes against the abstract file (S2, 'natural stop' rules of the plan):
- nothing reads on by itself except a window a newest-first surface can close or a server-filtered one; every scenario
  that expects a read to the end passes --limit 1000 (the file's `limit: null` means "to the natural end");
- a budget does not exist: `budget-stop-resumes` is dropped (the resumable stops are time-limit-after-records and
  rate-limited-after-records below), `resume-state-not-saved` keeps its meaning with the time limit as the stop;
- the stop of three account pages without anything new is stopped=query_failure (exit 8), not "empty_pages".
"""
import json
import re
import time
from datetime import datetime

import pytest

from tests.sns.x.data import fixture
from tests.sns.x.scenes import command_of, known_tab, queries, query_result, run, state

PAGING = fixture('paging.json')
SCENARIOS = {s['name']: s for s in PAGING['scenarios']}
RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}
USER = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}
LIST_ID = '1500000000000000001'
# The shared window closes a newest-first read at the first unit older than --since (everything after it is older), not
# at the first page wholly older: the same posts are shown with fewer requests.
FEWER_PAGES = {'pinned-never-closes': 2, 'repost-dated-when-reposted': 1}
DROPPED = {'budget-stop-resumes': 'there is no request budget (S2): a resumable stop is the time limit or an operation '
                                  'limit after records, run by time-limit-after-records and rate-limited-after-records'}


def x_time(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).strftime('%a %b %d %H:%M:%S +0000 %Y')


def tweet(record):
    if record.get('unavailable'):
        return {'__typename': 'TweetTombstone', 'tombstone': {'text': {'text': 'gone'}}}
    legacy = {'full_text': f'post {record["id"]}'}
    if record.get('created_at'):
        legacy['created_at'] = x_time(record['created_at'])
    return {'__typename': 'Tweet', 'rest_id': record['id'], 'core': {'user_results': {'result': USER}}, 'legacy': legacy}


def account(record):
    return {'__typename': 'User', 'rest_id': record['id'], 'core': {'screen_name': 'user_' + record['id'].lower()}}


def item(record, accounts):
    if accounts:
        return {'itemType': 'TimelineUser', 'user_results': {'result': account(record)}}
    return {'itemType': 'TimelineTweet', 'tweet_results': {'result': tweet(record)}}


def entries(page, accounts):
    """The timeline instructions of one scripted page: a group is one entry, or a conversation module of several."""
    added, pinned = [], []
    for group in page.get('groups', []):
        if len(group) == 1:
            entry = {'entryId': f'tweet-{group[0]["id"]}', 'content': {'itemContent': item(group[0], accounts)}}
            if group[0].get('pinned'):
                pinned.append(entry)
                continue
            added.append(entry)
        else:
            added.append({'entryId': f'profile-conversation-{group[0]["id"]}', 'content': {
                'items': [{'entryId': f'tweet-{r["id"]}', 'item': {'itemContent': item(r, accounts)}} for r in group]}})
    if page.get('has_next') or page.get('cursor'):
        added.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': page['cursor']}})
    instructions = [{'type': 'TimelinePinEntry', 'entry': entry} for entry in pinned]
    instructions.append({'type': 'TimelineAddEntries', 'entries': added})
    if page.get('terminated'):
        instructions.append({'type': 'TimelineTerminateTimeline', 'direction': 'Bottom'})
    return instructions


def answer(surface, page, accounts):
    """The scripted Aside answer for one scenario page."""
    error = page.get('error')
    if error == 'failed':
        return query_result('', status=500)
    if error == 'blocked':
        return query_result('{"errors":[{"code":326,"message":"locked"}]}', status=403)
    if error == 'login':
        return query_result('{"errors":[{"code":32}]}', status=401)
    if error == 'rate_limited':
        return query_result('{"errors":[{"code":88}]}', status=429, headers={
            'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(int(time.time()) + 600)})
    if error == 'time_limit':
        return {'__sleep': 30, **query_result({}, headers=RATE)}  # the deadline cuts the call: the time limit
    assert error is None, error
    instructions = entries(page, accounts)
    if surface == 'profile':
        body = {'data': {'user': {'result': {'timeline': {'timeline': {'instructions': instructions}}}}}}
    elif surface == 'graph':
        body = {'data': {'user': {'result': {'timeline': {'timeline': {'instructions': instructions}}}}}}
    elif surface == 'search':
        body = {'data': {'search_by_raw_query': {'search_timeline': {'timeline': {'instructions': instructions}}}}}
    elif surface == 'trends':
        body = {'data': {'explore_page': {'body': {'__typename': 'SegmentedTimelines', 'initialTimeline': {
            'id': 'for_you', 'timeline': {'timeline': {'instructions': instructions}}}, 'timelines': [
            {'id': 'for_you', 'timeline': {'id': 'VEZPUllPVQ=='}}]}}}}
    elif surface == 'home':
        body = {'data': {'home': {'home_timeline_urt': {'instructions': instructions}}}}
    else:
        body = {'data': {'list': {'tweets_timeline': {'timeline': {'instructions': instructions}}}}}
    return query_result(body, headers=RATE)


def plan(scenario):
    """(surface, argv, env) of the command that serves a scenario."""
    options = scenario['options']
    window = [word for key in ('since', 'until') if options.get(key) for word in (f'--{key}', options[key])]
    limit = ['--limit', str(options['limit'] or 1000)]
    env = {'TZ': options.get('tz', 'UTC')}
    if options.get('server_window'):
        return 'search', ['search', 'topic since:2026-10-01 until:2026-10-31', '--sort', 'latest', *limit], env
    if options.get('policy') == 'single_batch':
        return 'trends', ['trends', '--tab', 'foryou'], env
    if options.get('accounts'):
        return 'graph', ['graph', 'author_a', 'followers', *limit], env
    if options.get('chronological'):
        return 'profile', ['profile', 'author_a', *window, *(limit if options['limit'] else [])], env
    if window:
        return 'profile', ['profile', 'author_a', '--tab', 'media', *window, *limit], env
    return 'list', ['list', LIST_ID, '--tab', 'posts', *limit], env


def lookup():
    return query_result({'data': {'user': {'result': {**USER, 'privacy': {'protected': False}}}}}, headers=RATE)


def serve(browser, surface, pages, accounts):
    known_tab(browser)
    if surface in ('profile', 'graph'):
        browser.respond('x.query', lookup())
    for page in pages:
        browser.respond('x.query', answer(surface, page, accounts))


def envelope_of(argv, browser, env):
    code, out, err = run(browser, *argv, '--json', env=env)
    return code, json.loads(out), err


def fetched(browser):
    """Timeline pages asked for: every query but the one that finds the account."""
    return [c for c in queries(browser) if c['args']['name'] != 'UserByScreenName']


def coverage_of(envelope):
    window = envelope.get('window')
    undated = sum(int(m.group(1)) for note in envelope.get('coverage', []) if (m := re.match(r'(\d+) undated', note)))
    return (window['coverage'].startswith('closed') if window else None), undated


def scenario_params():
    for name in SCENARIOS:
        if name in DROPPED or name == 'resume-tail-then-end':
            continue
        yield pytest.param(name)


@pytest.mark.parametrize('name', list(scenario_params()))
def test_scenario(name, browser, data_dir):
    scenario = SCENARIOS[name]
    surface, argv, env = plan(scenario)
    options = scenario['options']
    if options.get('save_fails'):
        (data_dir).mkdir(parents=True, exist_ok=True)
        (data_dir / 'handles').write_text('a file where the handle directory should be')
    pages = [{**p, 'error': 'time_limit'} if p.get('error') == 'budget' else p for p in scenario['pages']]
    if any(p.get('error') == 'time_limit' for p in pages):
        env['SNS_DEADLINE_SECONDS'] = '0.2' if pages[0].get('error') else '5'
    serve(browser, surface, pages, bool(options.get('accounts')))
    code, result, _ = envelope_of(argv, browser, env)
    expected = scenario['expected']
    shown = [r['id'] for r in result['results']]
    assert shown == expected['shown'], (name, result)
    assert code == expected['code'], (name, code, result)
    stop = {'empty_pages': 'query_failure'}.get(expected['stop_reason'], expected['stop_reason'])
    if scenario['name'] == 'resume-state-not-saved':
        stop = 'time_limit'
    assert result['stop_reason'] == stop, (name, result['stop_reason'])
    if 'pages_fetched' in expected and not any(p.get('error') == 'time_limit' for p in pages):
        count = FEWER_PAGES.get(name, expected['pages_fetched'])
        assert len(fetched(browser)) == count, (name, [c['args']['name'] for c in queries(browser)])
    if 'window' in expected:
        complete, undated = coverage_of(result)
        assert (complete, undated) == (expected['window']['complete'], expected['window']['undated']), (name, result)
    if 'continues' in expected:
        assert bool(result.get('next')) is expected['continues'], (name, result)
    if expected.get('pending'):
        browser.respond('x.state', state()).respond('x.query', answer(surface, {'groups': [], 'has_next': False}, False))
        code, again, _ = envelope_of(command_words(result['next']), browser, env)
        assert [r['id'] for r in again['results']] == expected['pending'], (name, again)  # the kept tail, first
    if 'error' in expected:
        assert result['error'] == 'partial' and result['message'], (name, result)


def command_words(line):
    """A more: line as the argv `run` takes after the platform word, with --json kept."""
    words = command_of('more: ' + line)
    assert words[0] == 'x'
    return [*words[1:], '--json'] if '--json' not in words else words[1:]


def test_a_resumed_read_shows_the_kept_tail_first_then_requests_from_the_saved_cursor(browser):
    """resume-tail-then-end: the state the file starts from is exactly what the limit scenario leaves behind."""
    first, second = SCENARIOS['limit-keeps-unshown-tail'], SCENARIOS['resume-tail-then-end']
    surface, argv, env = plan(first)
    serve(browser, surface, first['pages'], False)
    code, result, _ = envelope_of(argv, browser, env)
    assert [r['id'] for r in result['results']] == ['A', 'B', 'C']
    browser.respond('x.state', state()).respond('x.query', answer(surface, second['pages'][0], False))
    code, again, _ = envelope_of(command_words(result['next']), browser, env)
    expected = second['expected']
    assert code == expected['code'] and [r['id'] for r in again['results']] == expected['shown'], again
    assert again['stop_reason'] == expected['stop_reason'] and not again.get('next')
    assert [c['args']['variables'].get('cursor') for c in queries(browser)][-1] == second['start']['after']
    assert len(queries(browser)) == 2  # one request for the whole resumed read


def test_the_dropped_scenario_is_the_one_only_a_budget_could_make():
    assert set(DROPPED) == {'budget-stop-resumes'} and set(DROPPED) <= set(SCENARIOS)


# --- profile_access ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('case', PAGING['profile_access']['cases'], ids=lambda c: c['name'])
def test_an_empty_tab_of_a_protected_account_is_unavailable_unless_followed(case, browser):
    profile = case['profile']
    card = {**USER, 'privacy': {'protected': profile['private']},
            'relationship_perspectives': {'following': profile['relationship']['following'], 'followed_by': False}}
    known_tab(browser).respond('x.query', query_result({'data': {'user': {'result': card}}}, headers=RATE))
    posts = [{'id': f'P{n}', 'created_at': '2026-10-06T10:00:00Z'} for n in range(case['records'])]
    browser.respond('x.query', answer('profile', {'groups': [[p] for p in posts], 'has_next': False}, False))
    code, out, _ = run(browser, 'profile', 'author_a', '--json')
    assert code == case['expected']['code'], out


# --- exit_priority ----------------------------------------------------------------------------------------------------

LOCK = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None, 'at': 5}
LOGIN = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 401, 'codes': [32], 'html': False, 'rate': None, 'at': 6}


def limited(**extra):
    return query_result('{"errors":[{"code":88}]}', status=429, headers={
        'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(int(time.time()) + 600)},
        **extra)


@pytest.mark.parametrize('answered, code', [
    (limited(signals=[LOCK]), 5),                                  # a block outranks the operation's limit
    (query_result({'data': {}}, signals=[LOCK, LOGIN]), 5),        # a block outranks a login
    (limited(signals=[LOGIN]), 4),                                 # a login outranks the limit
    (limited(), 10),                                               # the limit before any record
    (query_result('', status=500), 6),                             # any other failure
], ids=['block>limit', 'block>login', 'login>limit', 'limit', 'other'])
def test_when_several_outcomes_apply_the_exit_code_follows_the_priority(answered, code, browser):
    assert PAGING['exit_priority']['order'] == [5, 4, 9, 10, 6]
    known_tab(browser).respond('x.query', answered)
    assert run(browser, 'feed')[0] == code


def test_a_tombstone_in_a_list_is_a_record_marker_never_exit_9(browser):
    known_tab(browser).respond('x.query', answer('list', {'groups': [[{'id': 'T1', 'unavailable': True}],
                                                                     [{'id': 'T2', 'created_at': '2026-10-06T10:00:00Z'}]],
                                                          'has_next': False}, False))
    code, out, _ = run(browser, 'list', LIST_ID, '--json')
    assert code == 0 and [r['id'] for r in json.loads(out)['results'] if r['id']] == ['T2']


def batch(*ids):
    nodes = [{'result': {'__typename': 'Tweet', 'rest_id': i, 'core': {'user_results': {'result': USER}},
                         'legacy': {'full_text': 'x', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}}
             for i in ids]
    return query_result({'data': {'tweetResult': nodes}}, headers=RATE)


def test_a_batch_where_nothing_resolved_is_7_with_every_target_unresolved(browser):
    known_tab(browser).respond('x.query', batch())
    code, out, _ = run(browser, 'post', '1850000000000000001', '1850000000000000002', '--json')
    assert code == 7 and json.loads(out)['unresolved'] == ['1850000000000000001', '1850000000000000002']


def test_one_target_that_is_gone_is_exit_9(browser):
    known_tab(browser).respond('x.query', query_result({'data': {}}, headers=RATE))
    code, out, _ = run(browser, 'about', 'nobody_here', '--json')
    assert code == 9


# --- the window of a ranked feed ----------------------------------------------------------------------------------------

def test_the_window_of_a_ranked_feed_is_a_one_page_sample_that_more_continues(browser):
    """Neither home feed closes a window: with --since and no --limit it reads one page, keeps the posts dated inside
    the window, says it is a sample, and offers more:."""
    moment = time.time() - 600
    day = time.strftime('%Y-%m-%d', time.gmtime(moment))
    page = [{'id': 'F1', 'created_at': datetime.fromtimestamp(moment).astimezone().isoformat()},
            {'id': 'F2', 'created_at': datetime.fromtimestamp(moment - 40 * 86400).astimezone().isoformat()}]
    known_tab(browser).respond('x.query', answer('home', {'groups': [[p] for p in page], 'has_next': True, 'cursor': 'C1'},
                                                 False))
    code, out, _ = run(browser, 'feed', '--since', day, '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['F1'], out
    assert result['window']['coverage'] == 'sample (not in date order)' and result['next']
    assert len(queries(browser)) == 1  # one page, however old the next one would be
