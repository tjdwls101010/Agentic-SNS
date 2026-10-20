"""Query rotation (fixtures/rotation.json): which renamed query is the successor of a lost one, and when a query found on
the screen is adopted (its name and id saved) — only after one replay that decodes as the declared connection, carries
the identity asked for and plays the declared role; an empty replay proves nothing. The refusal-to-recovery flow itself is
test_cli_recovery.py."""
import json

import pytest

from sns.session import Session
from sns.threads import web
from tests.sns.threads.data import fixture
from tests.sns.threads.scenes import ASIDE, known_tab, query_result, run
from tests.sns.threads.test_cli_profile import by_name, repost_screen

ROTATION = fixture('rotation.json')


@pytest.mark.parametrize('case', ROTATION['successors'], ids=lambda c: c['name'])
def test_successor(case):
    catalog = {c['name']: {k: v for k, v in c.items() if k != 'name'} for c in case['candidates']}
    assert web.learn_successor(case['lost'], catalog, set(case['claimed'])) == case['expected']


def sender(operation, replay):
    """(command words, learned query name) of the operation a replay case names."""
    return {'profile.replies': (['profile', '@example.author', '--tab', 'replies'], 'BarcelonaProfileRepliesTabDirectQuery',
                                'profile_replies'),
            'profile.page': (['about', '@example.author'], 'BarcelonaProfilePageDirectQuery', 'profile_card')}[operation]


@pytest.mark.parametrize('case', [c for c in ROTATION['replays']['cases'] if c['operation'] == 'profile.replies'],
                         ids=lambda c: c['name'])
def test_a_query_found_on_the_screen_is_adopted_only_after_a_replay_that_proves_it(browser, case):
    words, name, key = sender(case['operation'], case['replay'])
    known_tab(browser).respond('threads.query', by_name()).respond('threads.page', repost_screen(name))
    browser.respond('threads.query', query_result(case['replay'], source='stored'))
    code, out, _ = run(browser, *words, '--json')
    adopted = Session('threads', ASIDE).renamed(key) == name
    assert adopted is case['expected']['adopted'], (case['name'], out)
    if case['expected']['adopted']:
        assert code == 0
    elif case['expected']['why'] == 'empty-proves-nothing':
        assert code == 7
    else:
        assert code == 6
        assert Session('threads', ASIDE).query(name) is None  # nothing of it was kept either


def test_a_card_about_another_account_than_the_one_asked_for_is_refused_and_nothing_is_learned(browser):
    """replay-wrong-identity: the card's user must be the id the lookup found, whichever query answered."""
    case = next(c for c in ROTATION['replays']['cases'] if c['name'] == 'replay-wrong-identity')
    known_tab(browser).respond('threads.query', by_name())
    browser.respond('threads.query', query_result({'data': {'user': {**case['replay']['data']['user'],
                                                                     'username': 'example.author'}}}))
    code, out, _ = run(browser, 'about', '@example.author', '--json')
    assert code == 6 and json.loads(out)['error'] == 'failed' and 'another account' in json.loads(out)['message']
    assert Session('threads', ASIDE).renamed('profile_card') is None


@pytest.mark.parametrize('case', ROTATION['roles']['cases'], ids=lambda c: c['name'])
def test_a_learned_profile_tab_must_play_its_role(browser, case):
    """Every group of an authored tab holds a post of the profile; a reposts tab also a reposted post in every group."""
    tab = 'reposts' if case['role'] == 'reposted' else 'replies'
    name = 'BarcelonaProfileRepostsTabDirectQuery' if tab == 'reposts' else 'BarcelonaProfileRepliesTabDirectQuery'
    counter = iter(range(900, 999))
    edges = []
    for group in case['groups']:
        items = []
        for record in group:
            raw = {'pk': f'30000000000000009{next(counter)}', 'code': 'C' + str(next(counter)),
                   'user': {'pk': record['author']['id'], 'username': 'u' + record['author']['id'][-2:]},
                   'text_post_app_info': {}}
            if record.get('reposted_post'):
                original = {'pk': record['reposted_post']['id'], 'code': 'Corig', 'user': {'pk': '1000000002', 'username': 'o'}}
                raw['text_post_app_info'] = {'share_info': {'reposted_post': original}}
            items.append({'post': raw})
        edges.append({'node': {'thread_items': items}})
    body = {'data': {'mediaData': {'edges': edges, 'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    known_tab(browser).respond('threads.query', by_name()).respond('threads.page', repost_screen(name))
    browser.respond('threads.query', query_result(body, source='stored'))
    code, out, _ = run(browser, 'profile', '@example.author', '--tab', tab, '--json')
    adopted = Session('threads', ASIDE).renamed('profile_' + tab) == name
    assert adopted is case['plays'], (case['name'], out)
    assert (code == 0) is case['plays']
