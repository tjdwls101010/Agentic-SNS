"""The listing scenarios of fixture paging.json, run through the real cli against the scripted Reddit: what a page shows,
what waits in the handle, repeats, empty answers, windows (their days, their closing, their bounds kept across a time-zone
change), and the search refusals."""
import json

import pytest

from tests.sns.reddit.scene import fixture
from tests.sns.reddit.shapes import epoch, listing, post
from tests.sns.support.cli import command_of

PAGING = fixture('paging.json')
SCENARIOS = {s['name']: s for s in PAGING['scenarios']}


def thing(record):
    """A post for a fixture record: {id, created_at, pinned}."""
    identity = record['id'].removeprefix('t3_')
    created = epoch(record['created_at'].replace('Z', '')) if record.get('created_at') else None
    return post(identity, created, **({'stickied': True} if record.get('pinned') else {}))


def page_of(page):
    ids = page.get('ids', [])
    if isinstance(ids, str):  # 'p1..p100'
        first, last = ids.split('..')
        ids = [f'p{n}' for n in range(int(first[1:]), int(last[1:]) + 1)]
    children = [thing(r) for r in page['records']] if 'records' in page else [post(i) for i in ids]
    return listing(children, after=page.get('after'))


def script(reddit, pages, path='/r/example/new.json'):
    """Queue the pages in order: the first asks without `after`, each next asks with the one before it."""
    reddit.me()
    previous = None
    for page in pages:
        reddit.json(path, page_of(page), query={'after': previous} if previous else {'limit': 100})
        previous = page.get('after')


def listing_requests(reddit):
    return [p for p in reddit.paths() if p != '/api/me.json']


def argv_of(options, command='sub'):
    words = ['reddit', command]
    if command == 'sub':
        words.append('r/example')
    elif command == 'related':
        words.append('aaa1')
    for key in ('sort', 'time', 'since', 'until', 'limit'):
        if options.get(key):
            words += [f'--{key}', str(options[key])]
    return words


def words_of(envelope):
    return command_of('more: ' + envelope['next'])


def test_the_fixture_still_has_the_scenarios_this_file_runs():
    assert {'page-of-100-shows-limit', 'no-limit-reads-one-page', 'dedupe-across-pages', 'after-repeated',
            'empty-first-page', 'related-empty-is-not-an-error', 'window-new-only', 'window-closes-on-older',
            'listing-ends-before-window', 'window-resumes-with-saved-bounds', 'window-dst-edge'} <= set(SCENARIOS)


def test_page_of_100_shows_the_limit_and_the_rest_waits(reddit):
    scenario = SCENARIOS['page-of-100-shows-limit']
    script(reddit, scenario['pages'], path='/r/example/hot.json')
    code, out, _ = reddit.run(*argv_of(scenario['options']), '--json')
    envelope = json.loads(out)
    assert code == scenario['expected']['code'] and [r['id'] for r in envelope['results']] == scenario['expected']['shown']
    assert envelope['stop_reason'] == scenario['expected']['stop_reason']
    assert len(listing_requests(reddit)) == scenario['expected']['pages_fetched']
    reddit.me()
    reddit.me()  # the continuation checks the account it was read with
    code, out, _ = reddit.run(*words_of(envelope), '--json')
    then = json.loads(out)
    assert [r['id'] for r in then['results']] == scenario['expected']['then']['shown']
    assert len(listing_requests(reddit)) == scenario['expected']['pages_fetched'], 'no further listing request'


def test_without_a_limit_one_page_is_read_and_25_shown(reddit):
    scenario = SCENARIOS['no-limit-reads-one-page']
    script(reddit, scenario['pages'], path='/r/example/hot.json')
    code, out, _ = reddit.run(*argv_of(scenario['options']), '--json')
    envelope = json.loads(out)
    assert code == 0 and len(envelope['results']) == 25 and envelope['stop_reason'] == 'limit_reached'
    assert len(listing_requests(reddit)) == 1


def test_a_fullname_already_shown_is_not_shown_again(reddit):
    scenario = SCENARIOS['dedupe-across-pages']
    script(reddit, scenario['pages'])
    code, out, _ = reddit.run(*argv_of(scenario['options']), '--json')
    assert code == 0 and [r['id'] for r in json.loads(out)['results']] == scenario['expected']['shown']
    assert len(listing_requests(reddit)) == scenario['expected']['pages_fetched']


def test_the_same_after_twice_is_a_pagination_failure_after_records(reddit):
    scenario = SCENARIOS['after-repeated']
    script(reddit, scenario['pages'][:2])
    code, out, _ = reddit.run(*argv_of(scenario['options']), '--json')
    envelope = json.loads(out)
    assert code == scenario['expected']['code'] and [r['id'] for r in envelope['results']] == scenario['expected']['shown']


@pytest.mark.parametrize('name, command, path', [('empty-first-page', 'sub', '/r/example/new.json'),
                                                 ('related-empty-is-not-an-error', 'related', '/duplicates/aaa1.json')])
def test_an_explicitly_empty_listing_is_exit_7(reddit, name, command, path):
    scenario = SCENARIOS[name]
    reddit.me().json(path, [listing([post('aaa1')]), listing([])] if command == 'related' else listing([]))
    code, out, _ = reddit.run(*argv_of(scenario['options'], command))
    assert code == scenario['expected']['code'] == 7


def test_a_window_needs_sort_new_and_an_unstated_sort_is_new(reddit):
    scenario = SCENARIOS['window-new-only']
    code, out, _ = reddit.run(*argv_of(scenario['options']))
    assert code == scenario['expected']['code'] and reddit.fetches() == []
    reddit.me().json('/r/example/new.json', listing([post('a', epoch('2026-10-06T01:00:00')),
                                                     post('b', epoch('2026-09-01T00:00:00'))], after='t3_b'))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--since', scenario['options']['since'])
    assert code == 0 and 'sort=new (window)' in out.splitlines()[0]


def test_the_window_closes_on_the_first_older_post_and_keeps_the_pinned_and_undated_out(reddit):
    scenario = SCENARIOS['window-closes-on-older']
    script(reddit, scenario['pages'])
    code, out, _ = reddit.run(*argv_of(scenario['options']), '--json', env={'TZ': scenario['options']['tz']})
    envelope = json.loads(out)
    assert code == 0 and [r['id'] for r in envelope['results']] == scenario['expected']['shown']
    assert envelope['stop_reason'] == scenario['expected']['stop_reason']
    assert len(listing_requests(reddit)) == scenario['expected']['pages_fetched']


def test_a_listing_that_ends_before_the_window_is_partial_8(reddit):
    scenario = SCENARIOS['listing-ends-before-window']
    script(reddit, scenario['pages'])
    code, out, _ = reddit.run(*argv_of(scenario['options']), '--json', env={'TZ': scenario['options']['tz']})
    envelope = json.loads(out)
    assert code == 8 and scenario['expected']['message_contains'] in envelope['message']
    assert [r['id'] for r in envelope['results']] == scenario['expected']['shown']


def test_a_windows_bounds_are_kept_when_the_time_zone_changes_before_the_continuation(reddit):
    scenario = SCENARIOS['window-resumes-with-saved-bounds']
    options = scenario['options']
    reddit.me().json('/r/example/new.json', listing([post('a', epoch('2026-10-05T01:00:00'))], after='t3_a'),
                     query={'limit': 100})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--since', options['since'], '--until',
                              options['until'], '--limit', '1', '--json', env={'TZ': options['tz']})
    first = json.loads(out)['window']
    assert [first['start_utc'], first['end_utc']] == scenario['expected']['bounds_utc'] and first['tz'] == 'KST'
    reddit.me().json('/r/example/new.json', listing([post('b', epoch('2026-10-05T00:30:00')),
                                                     post('old', epoch('2026-09-01T00:00:00'))], after='t3_old'),
                     query={'after': 't3_a'})
    reddit.me()
    code, out, _ = reddit.run(*words_of(json.loads(out)), '--json', env={'TZ': options['then_tz']})
    again = json.loads(out)['window']
    assert code == 0 and [again['start_utc'], again['end_utc']] == scenario['expected']['bounds_utc']
    assert again['tz'] == 'KST', 'the zone the window was made in, not the computer\'s zone now'


def test_a_daylight_saving_day_is_its_local_midnights(reddit):
    scenario = SCENARIOS['window-dst-edge']
    options = scenario['options']
    reddit.me().json('/r/example/new.json', listing([post('a', epoch('2026-11-01T12:00:00')),
                                                     post('old', epoch('2026-10-01T00:00:00'))], after='t3_old'))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--since', options['since'], '--until',
                              options['until'], '--json', env={'TZ': options['tz']})
    window = json.loads(out)['window']
    assert [window['start_utc'], window['end_utc']] == scenario['expected']['bounds_utc']


@pytest.mark.parametrize('case', PAGING['search']['cases'][:2], ids=lambda c: c['name'])
def test_search_in_needs_posts_and_one_community(reddit, case):
    options = case['options']
    code, out, _ = reddit.run('reddit', 'search', 'x', '--type', options['type'], '--in', options['in'])
    assert code == case['expected']['code'] == 2 and reddit.fetches() == []


def test_an_empty_search_is_one_request_and_exit_7(reddit):
    case = PAGING['search']['cases'][2]
    reddit.me().json('/search.json', listing([]))
    code, out, _ = reddit.run('reddit', 'search', 'x')
    assert code == case['expected']['code'] and len(listing_requests(reddit)) == case['expected']['requests']
