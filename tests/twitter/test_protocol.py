"""The wire to X through Aside: response classification, one-shot recoveries, protection state, registry learning and
refresh, and the Aside envelope contract."""
import base64
import json
import time

import pytest

from .fake_data import user, wrap
from .helpers import FIXTURES, calls, home, invoke, script, trace

FIXTURE = json.loads((FIXTURES / 'transaction.json').read_text())
PROFILE = ['about', '@example']


def snippets(env):
    return [t['snippet'] for t in trace(env)]


def real_material(env):
    """Replace the seeded signature material with material derived from the public fixture."""
    (home(env) / 'txid.json').write_text(json.dumps({'key_bytes': list(base64.b64decode(FIXTURE['verification'])),
                                                     'animation_key': FIXTURE['animation_key'],
                                                     'fetched_at': time.time()}))


def material_pages():
    """The two public pages a signature refresh reads: x.com's HTML and the ondemand chunk."""
    frames = ''.join('<svg id="loading-x-anim-' + index + '"><g>' +
                     ''.join('<path d="' + path + '"></path>' for path in paths) + '</g></svg>'
                     for index, paths in FIXTURE['frames'].items())
    html = '<meta name="twitter-site-verification" content="' + FIXTURE['verification'] + '">' + frames
    html += ',1:"ondemand.s",1:"abc123"'
    js = ';'.join('(a[' + str(index) + '],16)' for index in FIXTURE['indices'])
    return [{'snippet': 'page', 'body': html}, {'snippet': 'page', 'body': js}]


@pytest.mark.parametrize('status,body,error,code', [
    (403, '<!DOCTYPE html>cf-challenge', 'challenge', 5),
    (429, {'errors': [{'code': 326}]}, 'account_locked', 5),
    (200, {'errors': [{'code': 64}]}, 'account_locked', 5),
    (200, {'data': {'user': {'result': {'__typename': 'UserUnavailable'}}}}, 'unavailable', 9),
    (429, {}, 'rate_limit', 5),
    (401, {}, 'session', 4),
    (200, {'errors': [{'code': 32}]}, 'session', 4),
    (400, {'errors': [{'message': 'The following features cannot be null: new_flag'}]}, 'operation_rotated', 6),
    (422, {'errors': [{'message': 'Variable x must be defined'}]}, 'contract_drift', 6),
    (502, 'bad', 'transient', 6),
    (200, {'data': {}}, 'unavailable', 9),
    (200, {'data': {'different': []}}, 'envelope_drift', 6),
    (200, {'data': {'user': {'result': {'unexpected': 'shape'}}}}, 'envelope_drift', 6),
])
def test_responses_are_classified_into_recoverable_errors(status, body, error, code, fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'status': status, 'body': body})
    assert (lambda r: (r[1]['error'], r[0]))(invoke(PROFILE, fake_env)) == (error, code)


def test_malformed_timeline_instructions_are_drift(fake_env):
    script(fake_env, {'op': 'UserTweets', 'body': wrap('UserTweets', {})})
    code, doc = invoke(['user', '@example'], fake_env)
    assert (code, doc['error']) == (6, 'envelope_drift')


def test_data_with_errors_succeeds_and_reports_warnings(fake_env):
    body = {'data': {'list': {'id_str': '1', 'name': 'Example'}}, 'errors': [{'code': 214}]}
    script(fake_env, {'op': 'ListByRestId', 'body': body})
    code, doc = invoke(['list', '1', '--tab', 'about'], fake_env)
    assert code == 0 and doc['results'][0]['name'] == 'Example' and len(doc['warnings']) == 1


def test_csrf_rejection_rereads_the_cookie_once_and_never_reuses_the_failed_token(fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'status': 403, 'body': {'errors': [{'code': 353}]}},
           {'snippet': 'cookie', 'body': {'ct0': 'synthetic-new', 'twid': 'u%3D100'}})
    code, doc = invoke(PROFILE, fake_env)
    assert code == 0 and snippets(fake_env) == ['graphql', 'cookie', 'graphql']
    assert [t['ct0'] for t in trace(fake_env) if t['snippet'] == 'graphql'] == ['synthetic', 'synthetic-new']


def test_second_csrf_rejection_stops_without_another_cookie_read(fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'status': 403, 'body': {'errors': [{'code': 353}]}},
           {'snippet': 'cookie', 'body': {'ct0': 'synthetic-new', 'twid': 'u%3D100'}},
           {'op': 'UserByScreenName', 'status': 403, 'body': {'errors': [{'code': 353}]}})
    code, doc = invoke(PROFILE, fake_env)
    assert (code, doc['error']) == (4, 'csrf') and snippets(fake_env) == ['graphql', 'cookie', 'graphql']


def test_csrf_recovery_that_finds_another_account_stops_before_replaying(fake_env):
    script(fake_env, {'op': 'Likes', 'status': 403, 'body': {'errors': [{'code': 353}]}},
           {'snippet': 'cookie', 'body': {'ct0': 'new-account', 'twid': 'u%3D200'}})
    code, doc = invoke(['me', 'likes'], fake_env)
    assert (code, doc['error']) == (2, 'viewer_changed') and snippets(fake_env) == ['graphql', 'cookie']


def test_viewer_change_clears_continuations_and_keeps_the_session_private(fake_env):
    session = home(fake_env) / 'session.json'
    session.write_text(json.dumps({'ct0': 'old', 'viewer_id': '100', 'read_at': 0}))
    (home(fake_env) / 'cursors').mkdir()
    (home(fake_env) / 'cursors/1.json').write_text('{}')
    script(fake_env, {'snippet': 'cookie', 'body': {'ct0': 'synthetic-new', 'twid': 'u%3D200'}})
    code, doc = invoke(['home', '--limit', '1'], fake_env)
    assert code == 0 and doc['viewer_changed'] is True and doc['viewer_id'] == '200'
    saved = [json.loads(p.read_text()) for p in (home(fake_env) / 'cursors').glob('*.json')]
    assert [s['context']['viewer_id'] for s in saved] == ['200']
    assert session.stat().st_mode & 0o777 == 0o600


def test_personal_surfaces_reread_a_day_old_session_and_others_do_not(fake_env):
    (home(fake_env) / 'session.json').write_text(json.dumps({'ct0': 'old', 'viewer_id': '100',
                                                             'read_at': time.time() - 86401}))
    invoke(['user', '@example', '--limit', '1'], fake_env)
    assert 'cookie' not in snippets(fake_env)
    script(fake_env, {'snippet': 'cookie', 'body': {'ct0': 'new', 'twid': 'u%3D100'}})
    invoke(['home', '--limit', '1'], fake_env)
    last = trace(fake_env)[-2:]
    assert [t['snippet'] for t in last] == ['cookie', 'graphql'] and last[-1]['ct0'] == 'new'


def test_exhausted_bucket_refuses_the_next_request_without_reaching_the_browser(fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'status': 429, 'body': {}})
    assert invoke(PROFILE, fake_env)[1]['error'] == 'rate_limit'
    before = len(calls(fake_env))
    code, doc = invoke(PROFILE, fake_env)
    assert (code, doc['error']) == (5, 'rate_limit') and len(calls(fake_env)) == before


def test_account_lock_is_permanent_until_unblocked(fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'status': 429, 'body': {'errors': [{'code': 64}]}})
    assert invoke(PROFILE, fake_env)[1]['error'] == 'account_locked'
    code, doc = invoke(['doctor'], fake_env)
    assert (code, doc['error']) == (5, 'account_locked') and len(calls(fake_env)) == 1
    assert json.loads((home(fake_env) / 'budget.json').read_text())['block']['expires_at'] is None


def test_challenge_block_outlives_every_rate_limit_reset(fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'status': 403, 'body': '<!DOCTYPE html><html>challenge</html>'})
    assert invoke(PROFILE, fake_env)[1]['error'] == 'challenge'
    code, doc = invoke(['doctor'], dict(fake_env, FAKE_CLOCK_OFFSET='100000'))
    assert (code, doc['error']) == (5, 'challenge') and len(calls(fake_env)) == 1
    assert json.loads((home(fake_env) / 'budget.json').read_text())['block']['expires_at'] is None


def test_transient_failure_does_not_block_the_next_read(fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'status': 502, 'body': 'bad gateway'})
    assert invoke(PROFILE, fake_env)[1]['error'] == 'transient'
    code, doc = invoke(PROFILE, fake_env)
    assert code == 0 and 'block' not in json.loads((home(fake_env) / 'budget.json').read_text())


def test_missing_features_accumulate_for_refresh(fake_env):
    for flag in ('flag_a', 'flag_b', 'flag_a', 'flag_c'):
        script(fake_env, {'op': 'UserByScreenName', 'status': 400,
                          'body': {'errors': [{'message': 'The following features cannot be null: ' + flag}]}})
        assert invoke(PROFILE, fake_env)[1]['error'] == 'operation_rotated'
    saved = json.loads((home(fake_env) / 'registry.json').read_text())['missing_features']
    assert saved[:2] == ['flag_a', 'flag_b'] and sorted(saved) == ['flag_a', 'flag_b', 'flag_c']


def test_signature_rejection_refreshes_material_once_then_reports(fake_env):
    real_material(fake_env)
    script(fake_env, {'op': 'UserByScreenName', 'status': 404, 'body': ''}, *material_pages(),
           {'op': 'UserByScreenName', 'status': 404, 'body': ''})
    code, doc = invoke(PROFILE, fake_env)
    assert (code, doc['error']) == (6, 'transaction_rejected')
    assert snippets(fake_env) == ['graphql', 'page', 'page', 'graphql']


def test_operation_found_to_need_a_signature_is_learned_as_gated(fake_env):
    (home(fake_env) / 'txid.json').unlink()
    script(fake_env, {'snippet': 'page', 'body': 'no ingredients'},
           {'op': 'UserByScreenName', 'status': 404, 'body': ''}, *material_pages())
    code, doc = invoke(PROFILE, fake_env)
    signatures = [t['txid'] for t in trace(fake_env) if t['snippet'] == 'graphql']
    assert code == 0 and signatures[0] is None and signatures[1]
    assert json.loads((home(fake_env) / 'registry.json').read_text())['operations']['UserByScreenName']['gated'] is True


def test_every_request_carries_a_fresh_signature(fake_env):
    real_material(fake_env)
    invoke(['user', '@example', '--limit', '1'], fake_env)
    signatures = [t['txid'] for t in trace(fake_env) if t['snippet'] == 'graphql']
    assert len(signatures) == 2 and all(signatures) and signatures[0] != signatures[1]


@pytest.mark.parametrize('query', ['price < 100', 'cats | dogs', '…'])
def test_search_text_passes_through_without_template_interpretation(query, fake_env):
    invoke(['search', query, '--limit', '1'], fake_env)
    assert calls(fake_env)[0]['variables']['rawQuery'] == query


def bundle():
    html = '<meta name="twitter-site-verification" content="' + FIXTURE['verification'] + '">'
    for index, paths in FIXTURE['frames'].items():
        html += f'<svg id="loading-x-anim-{index}"><g>' + ''.join(f'<path d="{p}"></path>' for p in paths) + '</g></svg>'
    js = ';'.join(f'(a[{index}], 16)' for index in FIXTURE['indices'])
    return {'operations': {'Viewer': 'new-viewer'}, 'features': {'new_flag': True},
            'txid_ingredients': {'html': html, 'ondemand_js': js, 'ondemand_url': 'https://abs.twimg.com/example.js'}}


def test_refresh_keeps_undiscovered_ids_and_flags_after_two_replays(fake_env):
    (home(fake_env) / 'registry.json').write_text(json.dumps({
        'operations': {'HomeTimeline': {'query_id': 'current'}}, 'features': {'keep_flag': True},
        'missing_features': ['new_flag', 'absent_flag']}))
    script(fake_env, {'snippet': 'bundles', 'body': bundle()})
    code, doc = invoke(['refresh'], fake_env)
    saved = json.loads((home(fake_env) / 'registry.json').read_text())
    assert code == 0 and saved['operations']['HomeTimeline']['query_id'] == 'current'
    assert saved['operations']['Viewer']['query_id'] == 'new-viewer'
    assert (saved['features']['keep_flag'], saved['features']['new_flag'], saved['features']['absent_flag']) == (
        True, True, False)
    assert doc['verified'] == ['UserByScreenName', 'SearchTimeline'] and 'HomeTimeline' in doc['missing']
    assert [c['op'] for c in calls(fake_env) if 'op' in c] == doc['verified']
    assert json.loads((home(fake_env) / 'txid.json').read_text())['key_bytes'] != [1] * 48


def test_refresh_whose_replay_fails_saves_nothing(fake_env):
    registry = home(fake_env) / 'registry.json'
    registry.write_text(json.dumps({'features': {'old': True}}))
    original = registry.read_bytes()
    (home(fake_env) / 'txid.json').unlink()
    script(fake_env, {'snippet': 'bundles', 'body': bundle()}, {'op': 'UserByScreenName', 'status': 500, 'body': {}})
    code, doc = invoke(['refresh'], fake_env)
    assert code == 6 and registry.read_bytes() == original and not (home(fake_env) / 'txid.json').exists()


@pytest.mark.parametrize('chunks', [None, 2])
def test_aside_is_called_as_the_u0_repl_and_chunked_bodies_are_reassembled(chunks, fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'body': wrap('UserByScreenName', user(handle='chunked')),
                      **({'chunks': chunks} if chunks else {})})
    code, doc = invoke(PROFILE, fake_env)
    assert code == 0 and doc['results'][0]['screen_name'] == 'chunked'
    assert all(t['argv'] == ['--account', 'u0', 'repl'] for t in trace(fake_env))


@pytest.mark.parametrize('raw', [
    [{'status': 200, 'url': 'https://x.com/', 'body_file': '/etc/passwd'}],
    [{'kind': 'body_chunk', 'index': 1, 'body': 'x'}, {'status': 200, 'url': 'https://x.com/', 'body_chunks': 1}],
    [{'status': True, 'url': 'https://x.com/', 'body': ''}],
])
def test_untrusted_envelope_is_rejected_without_echoing_it(raw, fake_env):
    script(fake_env, {'op': 'UserByScreenName', 'raw': '\n'.join(json.dumps(r) for r in raw)})
    done = invoke(PROFILE, fake_env)
    assert done[0] == 3 and '/etc/passwd' not in json.dumps(done[1])
