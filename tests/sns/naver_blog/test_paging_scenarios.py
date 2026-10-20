"""The paging scenarios of fixture paging.json: how Naver's numbered pages end (a short page, the last page it names, the
1,000-result ceiling, the same page twice), what a window closes on, what waits in a handle, and what each stop becomes
as a result — Naver's page rules (web.numbered) driven through the shared list reading and the result kinds.

The scenarios use small page sizes of their own, so they run below the CLI; the commands' wiring is tested through the
CLI in the other files."""
import re
from types import SimpleNamespace

import pytest

import cli
from sns import reading
from sns.errors import SnsError
from sns.naver_blog import PLATFORM, web
from sns.results import finish
from tests.sns.naver_blog.scene import KIND_OF, fixture

SCENARIOS = fixture('paging.json')['scenarios']


def expand(pages):
    out = []
    for page in pages:
        if 'repeat' in page:
            start = 1 + sum(p.get('count', 0) for p in out)
            for _ in range(page['repeat']):
                out.append({'count': page['count'], 'start': start})
                start += page['count']
        else:
            out.append(page)
    return out


class Server:
    """Naver's pages as the scenario scripts them; asking for a page it does not have is a test bug."""

    def __init__(self, pages):
        self.pages, self.served, self.dated = expand(pages), [], 0

    def items(self, page):
        if 'ids' in page:
            return [{'id': i} for i in page['ids']]
        if 'dated' in page:
            out = []
            for when in page['dated']:
                self.dated += 1
                out.append({'id': f'd{self.dated}', 'created_at': when + '+09:00' if when else None})
            return out
        return [{'id': f'r{page["start"] + i}'} for i in range(page['count'])]

    def __call__(self, number):
        assert len(self.served) < len(self.pages), 'the reading asked for a page the scenario does not have'
        page = self.pages[len(self.served)]
        self.served.append(number)
        if 'error' in page:
            raise SnsError(KIND_OF[page['error']['code']], page['error']['reason'], 'fix', reason=page['error']['reason'])
        if isinstance(page.get('marker'), str):
            raise SnsError('failed', 'marker', 'fix', reason='drift')
        items = self.items(page)
        total = page.get('reported_total')
        return web.Fetched(items=items, raw_count=len(items), last_page=page.get('marker'),
                           reported_total=None if total == 0 and items else total)


def read(scenario, server, *, state=None, limit=None):
    policy = web.Policy(scenario['policy']['pagination'], scenario['policy'].get('page_size'),
                        scenario['policy'].get('ceiling'))
    options = {key: value for key, value in {**scenario['options'], 'limit': limit or scenario['options'].get('limit')}.items()
               if key in ('limit', 'since', 'until') and value}
    connection = SimpleNamespace(options=options, platform=PLATFORM)
    order = 'newest_first' if scenario['options'].get('monotonic') else 'finite'
    result = reading.read_list(connection, state, None, order=order, fetch=web.numbered(policy, server), command='x',
                               target=None, identity={}, end_covers_window=True)
    result['continuable'] = 'continuation' in result   # the pipeline saves a handle for a continuation
    return result


@pytest.mark.parametrize('scenario', SCENARIOS, ids=lambda s: s['name'])
def test_scenario(scenario):
    server, expect = Server(scenario['pages']), scenario['expect']
    result = read(scenario, server)
    kind, envelope = finish(result, platform='naver_blog', command='x')
    failure = result.get('failure')
    state = (result.get('continuation') or {}).get('state') or {}
    undated = re.search(r'(\d+) undated', ' '.join(result.get('coverage') or []))
    got = {'shown_count': len(result['results']), 'shown': [r['id'] for r in result['results']],
           'stop_reason': envelope['stop_reason'], 'exit': cli.KIND_EXIT[kind], 'pending': len(state.get('pending') or []),
           'pages_fetched': len(server.served), 'reported_total': result.get('reported_total'),
           'undated': int(undated[1]) if undated else 0,
           'failure': failure and {'code': next(c for c, k in KIND_OF.items() if k == failure.kind),
                                   'reason': failure.reason}}
    assert {key: got[key] for key in expect} == expect
    if 'continue' in scenario:
        more = scenario['continue']
        again = read(scenario, server, state=state, limit=more['options']['limit'])
        assert [r['id'] for r in again['results']] == more['expect']['shown']
        assert len(server.served) - got['pages_fetched'] == more['expect']['pages_fetched']
        assert len(((again.get('continuation') or {}).get('state') or {}).get('pending') or []) == \
            more['expect']['pending']


def test_a_hold_after_records_is_a_stop_where_more_resumes_not_a_failure():
    scenario = next(s for s in SCENARIOS if s['name'] == 'block-after-records')
    server = Server(scenario['pages'])
    result = read(scenario, server)
    kind, envelope = finish(result, platform='naver_blog', command='x')
    assert kind == 'resumable' and result['continuation']['state']['cursor'] == {'page': 2, 'position': 30}
    assert envelope['stop_reason'] == 'rate_limited'


def test_a_person_block_after_records_keeps_them_and_stops_for_good():
    scenario = {**next(s for s in SCENARIOS if s['name'] == 'block-after-records')}
    scenario['pages'] = [scenario['pages'][0]]
    server = Server(scenario['pages'])

    def person(number):
        if len(server.served) == 1:
            raise SnsError('blocked', 'blocked', 'fix', reason='network_blocked')
        return server(number)
    policy = web.Policy('plain', 30, None)
    connection = SimpleNamespace(options={'limit': 100}, platform=PLATFORM)
    result = reading.read_list(connection, None, None, order='finite', fetch=web.numbered(policy, person), command='x',
                               target=None, identity={})
    kind, envelope = finish(result, platform='naver_blog', command='x')
    assert kind == 'blocked' and len(result['results']) == 30 and envelope['stop_reason'] == 'blocked'


@pytest.mark.parametrize('after,kind,exit_code', [(True, 'resumable', 0), (False, 'failed', 6)])
def test_the_time_limit_resumes_after_records_and_fails_before_any(after, kind, exit_code):
    pages = [{'count': 30, 'start': 1}] if after else []
    server = Server(pages)

    def limited(number):
        if len(server.served) >= len(pages):
            raise SnsError('failed', 'time limit', 'fix', reason='time_limit')
        return server(number)
    connection = SimpleNamespace(options={'limit': 100}, platform=PLATFORM)
    result = reading.read_list(connection, None, None, order='finite',
                               fetch=web.numbered(web.Policy('plain', 30, None), limited), command='x', target=None,
                               identity={})
    result['continuable'] = 'continuation' in result
    got, envelope = finish(result, platform='naver_blog', command='x')
    assert (got, cli.KIND_EXIT[got]) == (kind, exit_code)
    assert envelope['stop_reason'] == 'time_limit'
