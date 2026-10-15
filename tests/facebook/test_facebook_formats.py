"""Facebook's response meaning, URL forms and the Aside program output (fixtures classify, targets, aside_output)."""
import json
import re

import pytest

from conftest import TESTS, fixture
from facebook import aside, graphql
from facebook.errors import FacebookError

CLASSIFY = fixture('classify.json')['cases']
OBSOLETE = {'asset': 'the skill no longer fetches static assets: query ids come from the live tab (R1)'}


def envelope(case):
    env = dict(case['envelope'])
    if 'body_lines' in env:
        env['body'] = env.pop('prefix', '') + '\n'.join(json.dumps(line) for line in env.pop('body_lines'))
    env.pop('prefix', None)
    return env


def outcome(case):
    if case['mode'] == 'home':
        # The logged-in user now comes from the tab's runtime; the same rule decides it.
        user = re.search(r'"USER_ID"\s*:\s*"(\d+)"', case['envelope']['body'])
        verdict = graphql.classify_location(case['envelope']['url'], user.group(1) if user else None)
    else:
        expected = case.get('expected')
        verdict = graphql.classify_response(envelope(case), mode=case['mode'],
                                            expected=(expected['key'], expected['kind']) if expected else None,
                                            retried=case.get('retried', False))
    if verdict.kind == 'blocked':
        return {'outcome': 'blocked', 'reason': verdict.block}
    if verdict.kind in ('failed', 'stale'):
        assert verdict.error.code == 6
        return {'outcome': 'failed'}
    if verdict.kind == 'login':
        assert verdict.error.code == 4
    result = {'outcome': verdict.kind}
    if verdict.kind == 'ok' and case['mode'] == 'graphql':
        result['chunks'] = len(verdict.chunks)
    return result


@pytest.mark.parametrize('case', [pytest.param(c, id=c['name']) for c in CLASSIFY])
def test_response_classification(case):
    if case['mode'] in OBSOLETE:
        pytest.skip(OBSOLETE[case['mode']])
    expected = dict(case['outcome'])
    if case['mode'] != 'graphql':
        expected.pop('chunks', None)
    assert outcome(case) == expected


TARGETS = fixture('targets.json')


@pytest.mark.parametrize('case', [pytest.param(c, id=c['command'] + ' ' + c['input']) for c in TARGETS['targets']])
def test_target_forms(case):
    normalize = {'profile': graphql.normalize_profile, 'group': graphql.normalize_group,
                 'post': graphql.normalize_post}[case['command']]
    if case.get('refused'):
        with pytest.raises(FacebookError) as error:
            normalize(case['input'])
        assert error.value.code == 2
    else:
        assert normalize(case['input']) == case['normalized']


@pytest.mark.parametrize('case', TARGETS['resolve'])
def test_ids_found_in_pages(case):
    assert graphql.find_id(case['kind'], case['html']) == case['id']


@pytest.mark.parametrize('case', [pytest.param(c, id=c['name']) for c in fixture('aside_output.json')['cases']])
def test_aside_program_output(case, tmp_path, monkeypatch):
    scenario = {'tabs': [{'id': 'T1', 'url': 'https://www.facebook.com/'}],
                'responses': [{'op': 'state', 'match': {}, 'response': {'__raw_stdout': case['stdout'] + case['stderr'],
                                                                        '__exit': case['exit']}}]}
    (tmp_path / 's.json').write_text(json.dumps(scenario))
    monkeypatch.setenv('FACEBOOK_ASIDE_BIN', str(TESTS / 'fake_aside.py'))
    monkeypatch.setenv('FACEBOOK_FAKE_SCENARIO', str(tmp_path / 's.json'))
    monkeypatch.setenv('FACEBOOK_FAKE_LOG', str(tmp_path / 'log'))
    monkeypatch.delenv('FACEBOOK_ASIDE_ACCOUNT', raising=False)
    call = lambda: aside.Aside().evaluate('T1', 'async () => { // facebook-snippet: state\n}', {})
    expected = case['outcome']
    if 'value' in expected:
        assert call() == expected['value']
        return
    with pytest.raises(FacebookError) as error:
        call()
    assert error.value.code == 3
    kind = expected['error']
    if kind == 'tab_missing':
        assert error.value.reason == 'tab_missing'
    elif kind == 'invalid':
        assert 'cannot read' in error.value.message
    elif kind == 'lost':
        assert 'lost its connection' in error.value.message
    else:
        assert error.value.reason != 'tab_missing' and 'cannot read' not in error.value.message
