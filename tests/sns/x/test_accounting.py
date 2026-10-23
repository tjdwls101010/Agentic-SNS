"""Request accounting (fixtures/accounting.json, nine cases): a command's requests are its direct requests (exact), the
opening or reload reservation of the tab, and every x.com request the tab's observer saw while it ran that is not
proved the skill's own by its nonce; what the tab did between commands is unwatched and not charged.

Executed in two layers, so the fixture's numbers are never derived from the code under test: the real kit runs under
Node against a fake x.com page (fakes/snippet_harness.mjs) and says what each look and query saw; those answers are then
scripted into the fake Aside and the real CLI reports what it charged. R, the opening reservation, is 20."""
import json

import pytest

from sns.session import Session
from sns.x import web
from tests.sns.fakes.snippet_runner import needs_node, run as run_harness
from tests.sns.x.data import fixture
from tests.sns.x.scenes import ASIDE, START, run
from tests.sns.x.test_cli_feed import entry, home, post
from tests.sns.x.test_snippets import page

pytestmark = needs_node
CASES = fixture('accounting.json')['cases']
R = 20
HOME_QUERY = {'name': 'HomeTimeline', 'allowed': ['HomeTimeline'], 'variables': {}, 'toggles': {}}
ROTATED = '{"errors":[{"message":"Query: Unspecified"}]}'
LOST = 'Error: other side closed\n'


def nonce_of(name):
    return name.split('#xs-')[1] if '#xs-' in name else None


def entries_of(call, mode, direct_path=None):
    """(background entries, an earlier request's own entry arrives, this call's own entry arrives in it)."""
    background, late, own = [], False, False
    for item in call.get('entries') or []:
        nonce = nonce_of(item['name'])
        if nonce is None:
            if mode == 'plain' and direct_path and item['name'].endswith(direct_path):
                continue  # the entry of the skill's own request, without the fragment Chrome dropped
            background.append({'url': item['name'], 'status': 200})
        elif direct_path and nonce == call['direct']['nonce']:
            own = True
        else:
            late = True
    return background, late, own


def plan(case):
    """The Node calls of the whole case, in order, and the commands they make up: each with the calls that are its
    looks and queries. A lost Aside answer ends the command there (the CLI does not go on), so the calls after it
    start a command of their own, which looks at the tab first."""
    mode, steps, commands = case['mode'], [], []
    if not case['commands'][0].get('opened'):
        steps.append({'snippet': 'arm', 'args': {}})  # a tab opened long ago: the kit is already there

    def fresh(opened, index):
        return {'opened': opened, 'looks': [], 'queries': [], 'lost': False, 'arm': None, 'modules': None,
                'index': index, 'feed': 'foryou'}

    def quiet(mine):
        steps.append({'snippet': 'state', 'args': {}})
        mine['looks'].append(len(steps) - 1)

    for index, command in enumerate(case['commands']):
        mine = fresh(command.get('opened', False), index)
        commands.append(mine)
        if mine['opened']:
            mine['arm'] = len(steps)
            steps.append({'snippet': 'arm', 'args': {}})
        for call in command['calls']:
            if call['kind'] == 'look':
                background, late, _ = entries_of(call, mode)
                steps.append({'snippet': 'state', 'args': {}, 'before': background, 'late_own': late})
                mine['looks'].append(len(steps) - 1)
                for _ in range(2 if mine['opened'] else 0):  # the load settles: two looks that see nothing new
                    quiet(mine)
                continue
            if mine['lost']:
                # a lost answer keeps its operation's window a probe until the longest Aside call could have ended
                # (core/test_protection.py): the command after it reads the other feed, whose window is its own
                mine = fresh(False, index)
                mine['feed'] = 'following'
                commands.append(mine)
                quiet(mine)
            background, late, own = entries_of(call, mode, call['direct']['path'])
            steps.append({'snippet': 'query', 'args': HOME_QUERY, 'during': background, 'late_own': late,
                          'no_own_entry': mode != 'plain' and not own})
            mine['queries'].append(len(steps) - 1)
            mine['lost'] = call['direct']['result'] == 'lost'
        if not mine['queries']:  # a command that only looks at the tab is doctor, which also lists the live operations
            steps.append({'snippet': 'modules', 'args': {'names': [], 'hints': []}})
            mine['modules'] = len(steps) - 1
    return steps, commands


def scripted(browser, mine, results):
    """Script the fake Aside with what the kit answered for one command's calls."""
    if mine['opened']:
        browser.respond('opener', {'tabs': ['NEW1']})
        browser.respond('load:x.arm', results[mine['arm']])
    else:
        browser.tab('T1', url=START)
        Session('x', ASIDE).set_tab('T1')
    for index in mine['looks']:
        browser.respond('x.state', results[index])
    for index in mine['queries']:
        if mine['lost']:
            browser.respond('x.query', {'__raw_stdout': LOST, '__exit': 1})
        else:
            browser.respond('x.query', results[index])
    if mine['modules'] is not None:
        browser.respond('x.modules', results[mine['modules']])


def total_of(text):
    return sum(R if part.strip() == 'R' else int(part) for part in text.split('+'))


@pytest.mark.parametrize('case', [c for c in CASES if c['name'] != 'reload-is-charged-whole'],
                         ids=lambda c: c['name'])
def test_accounting(case, browser, tmp_path):
    steps, commands = plan(case)
    # each query's page: a post of its own, and a cursor unless it is its command's last (so --limit asks for the next)
    fetches, number = [], 0
    for mine in commands:
        for position in range(len(mine['queries'])):
            number += 1
            last = position == len(mine['queries']) - 1
            fetches.append({'status': 200, 'body': json.dumps(home([entry(post(f'18500000000000000{number:02d}'))],
                                                                  bottom=None if last else f'CUR{number}'))})
    spec = page(location=START, fetch=fetches, fragment=case['mode'] != 'plain')
    sources = {name: web.snippet(name) for name in web.SNIPPET_NAMES}
    results = run_harness(tmp_path, 'webpack', steps, spec, sources)['results']
    split = any(c['lost'] for c in commands)  # the lost result split one command of the case into two runs
    charged = {'direct': 0, 'background': 0}
    for mine in commands:
        expected = case['expected'][mine['index']]
        scripted(browser, mine, results)
        code, out, err = run(browser, *(('feed', '--feed', mine['feed'], '--limit', '40', '--json') if mine['queries'] else ('doctor',)))
        envelope = json.loads(out)
        direct = len(mine['queries'])
        if mine['lost']:  # the Aside answer is lost: the command ends there (3) with the request charged once
            assert code == 3 and envelope['request_count'] == direct, envelope
        else:
            assert code == 0, (envelope.get('message'), envelope.get('fix'))
        total, setup = envelope['request_count'], envelope.get('setup_requests', 0)
        opening = R if expected['charged']['opening'] == 'R' else 0
        if opening:
            assert setup >= R, envelope  # the reservation, and the document and what the kit saw on top
        else:
            assert setup == 0, envelope
        assert envelope.get('unwatched_requests', 0) == expected['unwatched'], envelope
        if not split:
            assert total == total_of(expected['total']), (envelope, expected)
            assert total - direct - opening == expected['charged']['background'], (envelope, expected)
        charged['direct'] += direct
        charged['background'] += total - direct - opening
    if split:
        want = case['expected'][0]['charged']
        assert charged == {'direct': want['direct'], 'background': want['background']}, charged


def test_a_reload_is_charged_whole_as_setup(browser, tmp_path):
    """reload-is-charged-whole: a recovery reload (the tab's app is older than X's servers) is charged like an opening —
    the reservation, because the kit came after the new document's app — and counted apart from the reads."""
    case = next(c for c in CASES if c['name'] == 'reload-is-charged-whole')
    fetches = [{'status': 200, 'body': ROTATED},
               {'status': 200, 'body': json.dumps(home([entry(post('1850000000000000001'))], bottom=None))}]
    steps = [{'snippet': 'arm', 'args': {}}, {'snippet': 'state', 'args': {}},
             {'snippet': 'query', 'args': HOME_QUERY},
             {'snippet': 'arm', 'args': {}, 'reload': True}, {'snippet': 'state', 'args': {}},
             {'snippet': 'state', 'args': {}}, {'snippet': 'state', 'args': {}},
             {'snippet': 'query', 'args': HOME_QUERY}]
    sources = {name: web.snippet(name) for name in web.SNIPPET_NAMES}
    results = run_harness(tmp_path, 'webpack', steps, page(location=START, fetch=fetches), sources)['results']
    browser.tab('T1', url=START)
    Session('x', ASIDE).set_tab('T1')
    browser.respond('x.state', results[1]).respond('x.query', results[2]).respond('load:x.arm', results[3])
    for index in (4, 5, 6):
        browser.respond('x.state', results[index])
    browser.respond('x.query', results[7])
    code, out, _ = run(browser, 'feed', '--json')
    envelope = json.loads(out)
    expected = case['expected'][0]
    assert code == 0 and expected['setup_outside_max_requests'] and expected['unwatched'] == 0, envelope.get('message')
    assert envelope['setup_requests'] == R  # the whole reservation; nothing was seen after the late install
    assert envelope['request_count'] == R + 2  # and the two reads, the refused one included
