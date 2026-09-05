import base64
import json
import time
from pathlib import Path
import pytest
from twitter_skill._blocked import read_state, write_state
from twitter_skill._budget import Budget
from twitter_skill._errors import TwitterError
from twitter_skill._registry import Registry
from twitter_skill._transport import Transport

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/transaction.json').read_text())


def response(body, status=200):
    return {'status': status, 'url': 'https://x.com/', 'body': body if isinstance(body, str) else json.dumps(body),
            'ratelimit': {'limit': 50, 'remaining': 45, 'reset': int(time.time()) + 600}}


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setenv('TWITTER_HOME', str(tmp_path))
    write_state('session.json', {'ct0': 'synthetic-old', 'viewer_id': '100', 'read_at': time.time()})
    write_state('txid.json', {'key_bytes': list(base64.b64decode(FIXTURE['verification'])),
                            'animation_key': FIXTURE['animation_key'], 'fetched_at': time.time()})
    calls, responses = [], []

    def runner(name, args):
        calls.append((name, args))
        assert responses, f'Unexpected browser request: {name}'
        return responses.pop(0)

    instance = Transport(runner=runner, registry=Registry(override={}),
                         budget=Budget(sleep=lambda _: None, jitter=lambda: 0))
    return instance, calls, responses


def profile(transport):
    return transport.query('UserByScreenName', {'screen_name': 'example'})


def test_csrf_recovers_once_and_never_reuses_failed_token(transport):
    client, calls, responses = transport
    responses.extend([response({'errors': [{'code': 353}]}, 403),
                      response({'ct0': 'synthetic-new', 'twid': 'u%3D100'}),
                      response({'data': {'user': {'result': {'rest_id': '100'}}}})])
    assert profile(client)['rest_id'] == '100'
    assert [name for name, _ in calls] == ['graphql', 'cookie', 'graphql']
    assert [args['ct0'] for name, args in calls if name == 'graphql'] == ['synthetic-old', 'synthetic-new']


def test_second_csrf_rejection_stops_without_more_cookie_tabs(transport):
    client, calls, responses = transport
    responses.extend([response({'errors': [{'code': 353}]}, 403),
                      response({'ct0': 'synthetic-new', 'twid': 'u%3D100'}),
                      response({'errors': [{'code': 353}]}, 403)])
    with pytest.raises(TwitterError) as exc:
        profile(client)
    assert exc.value.code == 4
    assert [name for name, _ in calls] == ['graphql', 'cookie', 'graphql']


def test_session_refresh_clears_other_viewer_cursors_and_is_private(transport, tmp_path):
    client, calls, responses = transport
    (tmp_path / 'cursors').mkdir()
    (tmp_path / 'cursors/1.json').write_text('{}')
    responses.append(response({'ct0': 'synthetic-new', 'twid': 'u%3D200'}))
    session = client.session(force=True)
    assert session['viewer_id'] == '200'
    assert client.changed_viewer
    assert not list((tmp_path / 'cursors').glob('*.json'))
    assert (tmp_path / 'session.json').stat().st_mode & 0o777 == 0o600


def test_personal_surface_refreshes_day_old_session(transport):
    client, calls, responses = transport
    write_state('session.json', {'ct0': 'old', 'viewer_id': '100', 'read_at': time.time() - 86401})
    responses.append(response({'ct0': 'new', 'twid': 'u%3D100'}))
    assert client.session(personal=True)['ct0'] == 'new'
    assert [name for name, _ in calls] == ['cookie']


def test_full_bucket_never_reaches_browser(transport):
    client, calls, responses = transport
    qid = client.registry.get('UserByScreenName')['query_id']
    client.budget.observe(qid, {'limit': 50, 'remaining': 0, 'reset': int(time.time()) + 600})
    with pytest.raises(TwitterError) as exc:
        profile(client)
    assert exc.value.error == 'rate_limit'
    assert calls == []


def test_account_lock_persists_before_later_requests(transport):
    client, calls, responses = transport
    responses.append(response({'errors': [{'code': 64}]}, 429))
    with pytest.raises(TwitterError) as exc:
        profile(client)
    assert exc.value.error == 'account_locked'
    with pytest.raises(TwitterError) as exc:
        client.query('Viewer')
    assert exc.value.error == 'account_locked'
    assert len(calls) == 1
    assert read_state('budget.json')['block']['expires_at'] is None


def test_api_errors_accumulate_features_for_repair(transport):
    client, calls, responses = transport
    for flag in ('flag_a', 'flag_b'):
        responses.append(response({'errors': [{'message': 'The following features cannot be null: ' + flag}]}, 400))
        with pytest.raises(TwitterError) as exc:
            profile(client)
        assert exc.value.error == 'operation_rotated'
    assert read_state('registry.json')['missing_features'] == ['flag_a', 'flag_b']


def public_material_responses():
    frames = ''.join('<svg id="loading-x-anim-' + index + '"><g>' +
                     ''.join('<path d="' + path + '"></path>' for path in paths) + '</g></svg>'
                     for index, paths in FIXTURE['frames'].items())
    html = '<meta name="twitter-site-verification" content="' + FIXTURE['verification'] + '">' + frames
    html += ',1:"ondemand.s",1:"abc123"'
    js = ';'.join('(a[' + str(index) + '],16)' for index in FIXTURE['indices'])
    return [response(html), response(js)]


def test_signature_refresh_retries_once_then_reports_rejection(transport):
    client, calls, responses = transport
    responses.extend([response('', 404), *public_material_responses(), response('', 404)])
    with pytest.raises(TwitterError) as exc:
        profile(client)
    assert exc.value.error == 'transaction_rejected'
    assert [name for name, _ in calls] == ['graphql', 'page', 'page', 'graphql']


def test_newly_gated_operation_is_learned_after_success(transport, tmp_path):
    client, calls, responses = transport
    (tmp_path / 'txid.json').unlink()
    responses.extend([response('no ingredients'), response('', 404), *public_material_responses(),
                      response({'data': {'user': {'result': {'rest_id': '100'}}}})])
    assert profile(client)['rest_id'] == '100'
    requests = [args for name, args in calls if name == 'graphql']
    assert requests[0]['txid'] is None
    assert requests[1]['txid']
    assert read_state('registry.json')['operations']['UserByScreenName']['gated'] is True


def test_each_request_mints_a_fresh_signature(transport, monkeypatch):
    import random
    client, calls, responses = transport
    random_bytes = iter([1, 2])
    monkeypatch.setattr(random, 'randint', lambda *_: next(random_bytes))
    responses.extend([response({'data': {'user': {'result': {'rest_id': '100'}}}})] * 2)
    profile(client)
    profile(client)
    signatures = [args['txid'] for name, args in calls if name == 'graphql']
    assert len(signatures) == 2 and signatures[0] != signatures[1]


def test_challenge_is_permanent_even_after_rate_header_expiry(transport):
    client, calls, responses = transport
    responses.append(response('<!DOCTYPE html><html>challenge</html>', 403))
    with pytest.raises(TwitterError) as exc:
        profile(client)
    assert exc.value.error == 'challenge'
    client.budget.observe('different', {'limit': 50, 'remaining': 0, 'reset': 1}, 429)
    client.budget.clock = lambda: time.time() + 100000
    with pytest.raises(TwitterError) as exc:
        client.query('Viewer')
    assert exc.value.error == 'challenge'
    assert len(calls) == 1
    assert read_state('budget.json')['block']['expires_at'] is None


def test_transient_failure_does_not_poison_next_read(transport):
    client, calls, responses = transport
    responses.extend([response('bad gateway', 502), response({'data': {'user': {'result': {'rest_id': '100'}}}})])
    with pytest.raises(TwitterError) as exc:
        profile(client)
    assert exc.value.error == 'transient'
    assert profile(client)['rest_id'] == '100'
    assert not read_state('budget.json').get('block')
