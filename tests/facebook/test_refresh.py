"""Refresh public seam: real extractor JS, injected network, isolated cache."""
import json
from pathlib import Path

import pytest

from _blocked import cache_dir
from _errors import FacebookError
from _registry import load_registry

@pytest.fixture(autouse=True)
def offline_browser(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Live Aside is forbidden')
    monkeypatch.setattr('_aside.run_snippet', forbidden)
    monkeypatch.setattr('_transport.run_snippet', forbidden)


class Transport:
    def __init__(self, *, reject=()):
        self.request_count = 0
        self.limit = 400
        self.tokens = {'fb_dtsg': 'SECRET'}
        self.account_id = 'u0'
        self.urls = []
        self.replays = []
        self.captures = []
        self.reject = reject

    def start(self):
        self.request_count += 1

    def html(self, url):
        self.request_count += 1
        self.urls.append(url)
        if 'fbcdn.net' in url:
            body = ''.join('__d("' + spec['name'] + '_facebookRelayOperation",[],(function(a){a.exports="' +
                           str(100 + i) + '"}),null);' for i, (key, spec) in
                           enumerate(load_registry()['queries'].items()) if key not in ('comments', 'comments_page', 'replies'))
        else:
            body = '<script type="application/json">{"data":{"node":{"__typename":"Story","id":"PUBLIC_STORY","post_id":"123","url":"https://www.facebook.com/example/posts/123"}}}</script>"storyID":"PUBLIC_STORY"<script src="https://static.xx.fbcdn.net/rsrc.php/v4/test.js"></script>'
        return {'status': 200, 'url': url, 'body': body}

    def query(self, key, overrides=None, referer=None):
        raise AssertionError('Must replay the candidate, never the cached doc_id')

    def mine(self, url, names):
        envelope = self.html(url)
        envelope['queries'] = [{'name': spec['name'], 'doc_id': str(100 + i)}
                               for i, (key, spec) in enumerate(load_registry()['queries'].items())
                               if key not in ('comments', 'comments_page', 'replies')] if 'fbcdn.net' in url else []
        envelope['scripts'] = [] if 'fbcdn.net' in url else ['https://static.xx.fbcdn.net/rsrc.php/v4/test.js']
        return envelope

    def capture(self, args):
        self.captures.append(args)
        available = self.limit - self.request_count
        envelope = self.captured({**args, 'request_budget': available})
        result = json.loads(envelope['body'])
        assert result['count_complete'] is True
        assert 1 <= result['request_count'] <= available
        self.request_count += result['request_count']
        return envelope

    def query_spec(self, spec, overrides=None, referer=None):
        from dataclasses import asdict
        key = next(key for key, value in load_registry()['queries'].items() if value['name'] == spec.name)
        spec = asdict(spec)
        self.request_count += 1
        self.replays.append((key, spec, overrides, referer))
        if key in self.reject:
            raise FacebookError(6, 'SECRET remote failure')
        expected = spec.get('expected_key') or spec['connection_key']
        value = {'id': 'synthetic'} if spec.get('expected_kind') == 'object' else {'edges': [{'node': {'__typename': 'Story', 'id': 'synthetic', 'post_id': '123', 'feedback': {'id': 'feedback'}, 'permalink_url': 'https://www.facebook.com/example/posts/123'}}]}
        return json.dumps({'data': {expected: value}}).encode()


def test_refresh_verifies_six_mined_candidates_and_preserves_other_overrides(monkeypatch):
    import _refresh
    cache_dir().mkdir(parents=True)
    previous = {'queries': {'comments': {'doc_id': '777'}, 'newsfeed': {'variables': {'count': 9}}},
                'relay_provider_flags': {'__relay_internal__pv__Existingrelayprovider': True}}
    (cache_dir() / 'registry.json').write_text(json.dumps(previous))
    transport = Transport()
    result = _refresh.refresh(transport, post='https://www.facebook.com/example/posts/123')
    seeds = {key: overrides for key, _, overrides, _ in transport.replays}
    assert seeds['timeline']['id'] == '4'
    assert seeds['group']['id'] == '1084901568224581'
    assert seeds['about']['sectionToken'] == 'YXBwX3NlY3Rpb246NDoyMzI3MTU4MjI3'
    assert seeds['search']['args']['text'] == 'facebook'
    assert seeds['search']['args']['callsite'] == 'COMET_GLOBAL_SEARCH'
    assert seeds['post']['storyID'] == 'PUBLIC_STORY'
    assert set(result['updated']) == {'newsfeed', 'timeline', 'about', 'search', 'group', 'post'}
    assert set(result['missing']) == {'comments', 'comments_page', 'replies'}
    assert result['failed'] == {}
    saved = json.loads((cache_dir() / 'registry.json').read_text())
    assert saved['queries']['comments'] == {'doc_id': '777'}
    assert saved['queries']['newsfeed']['variables'] == {'count': 9}
    assert saved['relay_provider_flags'] == previous['relay_provider_flags']
    assert len([u for u in transport.urls if 'fbcdn.net' in u]) == 1
    assert transport.request_count == 1 + len(transport.urls) + 6
    assert all(spec['doc_id'] != '27790894430578947' for _, spec, _, _ in transport.replays)
    assert 'SECRET' not in json.dumps(saved)


def test_capture_only_saves_verified_metadata_and_replays_instance_variables(monkeypatch):
    import _refresh
    def snippets(args):
        assert 1 <= args['request_budget'] <= 400
        registry = load_registry()['queries']
        return {'status': 200, 'url': args['url'], 'body': json.dumps({'queries': [
            {'name': registry[key]['name'], 'doc_id': str(800 + index), 'variables': {
                'feedbackID': 'PRIVATE', 'cursor': 'PRIVATE_CURSOR', 'fb_dtsg': 'SECRET',
                '__relay_internal__pv__Validrelayprovider': True,
                '__relay_internal__pv__Stringrelayprovider': 'AUTO_TRANSLATE',
                '__relay_internal__pv__Invalidrelayprovider': {'token': 'SECRET'},
                '__relay_internal__pv__FailedOnlyrelayprovider': key == 'replies',
            }} for index, key in enumerate(('comments', 'comments_page', 'replies'))], 'failed': None, 'request_count': 4, 'count_complete': True})}
    transport = Transport(reject={'replies'})
    transport.captured = snippets
    result = _refresh.refresh(transport, capture=True, post='https://www.facebook.com/example/posts/123')
    assert set(result['updated']) == {'newsfeed', 'timeline', 'about', 'search', 'group', 'post', 'comments', 'comments_page'}
    assert result['failed'] == {'replies': 'replay_failed'}
    assert transport.request_count == 1 + len(transport.urls) + len(transport.replays) + 4 * len(transport.captures)
    saved_text = (cache_dir() / 'registry.json').read_text()
    assert all(secret not in saved_text for secret in ('PRIVATE', 'SECRET', 'feedbackID', 'cursor', 'fb_dtsg'))
    saved = json.loads(saved_text)
    assert saved['relay_provider_flags'] == {
        '__relay_internal__pv__Validrelayprovider': True,
        '__relay_internal__pv__Stringrelayprovider': 'AUTO_TRANSLATE',
        '__relay_internal__pv__FailedOnlyrelayprovider': False}
    assert 'replies' not in saved['queries']
    replay = next(row for row in transport.replays if row[0] == 'comments')
    assert replay[1]['doc_id'] == '800'
    assert replay[2]['feedbackID'] == 'PRIVATE'
    assert replay[3] == 'https://www.facebook.com/example/posts/123'


@pytest.mark.parametrize('body', [b'', b'{"data":null}', b'{"data":{"wrong":{}}}',
                                  b'{"errors":[{"severity":"CRITICAL"}]}'])
def test_unverified_replay_responses_never_replace_cache(monkeypatch, body):
    import _refresh
    transport = Transport()
    transport.query_spec = lambda *args, **kwargs: body
    result = _refresh.refresh(transport)
    assert result['updated'] == []
    assert set(result['failed'].values()) == {'replay_failed', 'sample_post_missing'}
    assert not (cache_dir() / 'registry.json').exists()


def test_missing_candidate_protocol_does_not_replay_cached_query_or_write(monkeypatch):
    import _refresh
    transport = Transport()
    transport.query_spec = None
    result = _refresh.refresh(transport)
    assert result['updated'] == []
    assert len(result['failed']) == 6
    assert set(result['failed'].values()) == {'candidate_replay_unsupported'}
    assert not (cache_dir() / 'registry.json').exists()


def test_atomic_replace_failure_preserves_old_cache_and_removes_temporary(monkeypatch):
    import _refresh
    cache_dir().mkdir(parents=True)
    original = '{"queries":{"comments":{"doc_id":"777"}}}\n'
    path = cache_dir() / 'registry.json'
    path.write_text(original)
    def fail_replace(source, destination):
        assert Path(source).parent == path.parent
        assert Path(destination) == path
        assert json.loads(Path(source).read_text())['queries']['comments'] == {'doc_id': '777'}
        assert path.read_text() == original
        raise OSError('disk unavailable')
    monkeypatch.setattr(_refresh.os, 'replace', fail_replace)
    with pytest.raises(FacebookError) as error:
        _refresh.refresh(Transport())
    assert error.value.code == 6
    assert path.read_text() == original
    assert set(cache_dir().iterdir()) == {path, cache_dir() / 'account.lock'}


@pytest.mark.parametrize('code', [4, 5, 8])
def test_login_blocked_or_budget_error_stops_further_requests_and_cache_write(monkeypatch, code):
    import _refresh
    transport = Transport()
    attempts = []
    def stopped(*args, **kwargs):
        attempts.append(args[0])
        raise FacebookError(code, 'Stop')
    transport.query_spec = stopped
    with pytest.raises(FacebookError) as error:
        _refresh.refresh(transport)
    assert error.value.code == code
    assert len(attempts) == 1
    assert not (cache_dir() / 'registry.json').exists()


@pytest.mark.parametrize('post', [None, 'https://evil.example/posts/1', 'https://www.facebook.com:bad/posts/1'])
def test_invalid_capture_url_is_rejected_before_network(post):
    import _refresh
    transport = Transport()
    with pytest.raises(FacebookError) as error:
        _refresh.refresh(transport, capture=True, post=post)
    assert error.value.code == 2
    assert transport.request_count == 0


def test_transport_rejecting_bundle_urls_reports_failed_queries_without_bypass(monkeypatch):
    import _refresh
    transport = Transport()
    original_html = transport.html
    def facebook_only(url):
        if 'fbcdn.net' in url:
            raise FacebookError(2, 'Facebook URLs only')
        return original_html(url)
    transport.html = facebook_only
    result = _refresh.refresh(transport)
    assert result['updated'] == []
    assert set(result['failed']) == {'newsfeed', 'timeline', 'about', 'search', 'group', 'post'}
    assert set(result['failed'].values()) == {'mining_request_failed'}
    assert set(result['missing']) == {'comments', 'comments_page', 'replies'}
    assert not (cache_dir() / 'registry.json').exists()


def test_post_referer_is_validated_even_without_capture(monkeypatch):
    import _refresh
    transport = Transport()
    with pytest.raises(FacebookError) as error:
        _refresh.refresh(transport, post='https://evil.example/post')
    assert error.value.code == 2
    assert transport.request_count == 0


def test_verified_home_feed_supplies_post_sample_without_saving_its_handle():
    import _refresh
    transport = Transport()
    result = _refresh.refresh(transport)
    assert 'post' in result['updated']
    replay = next(row for row in transport.replays if row[0] == 'post')
    assert replay[2]['storyID'] == 'PUBLIC_STORY'
    assert replay[3] == 'https://www.facebook.com/example/posts/123'
    saved = (cache_dir() / 'registry.json').read_text()
    assert 'PUBLIC_STORY' not in saved
    assert 'example/posts' not in saved


@pytest.mark.parametrize('observation', [
    {'status': 429, 'url': 'https://www.facebook.com/api/graphql/', 'body': '{}'},
    {'status': 200, 'url': 'https://www.facebook.com/checkpoint/', 'body': '{}'},
])
def test_capture_observation_persists_block_before_replay(observation):
    import _refresh
    from _blocked import check_blocked
    transport = Transport()
    transport.captured = lambda args: {'status': 200, 'url': args['url'], 'body': json.dumps({
        'queries': [], 'envelopes': [observation], 'failed': None,
        'request_count': 2, 'count_complete': True})}
    with pytest.raises(FacebookError) as error:
        _refresh.refresh(transport, capture=True, post='https://www.facebook.com/example/posts/123')
    assert error.value.code == 5
    assert transport.replays == []
    with pytest.raises(FacebookError) as blocked:
        check_blocked()
    assert blocked.value.code == 5
    assert not (cache_dir() / 'registry.json').exists()


def test_capture_is_run_through_real_transport_guard(monkeypatch):
    from _transport import Transport as GuardedTransport
    from _blocked import set_blocked
    transport = GuardedTransport()
    set_blocked('checkpoint')
    with pytest.raises(FacebookError) as error:
        transport.capture({'url': 'https://www.facebook.com/example/posts/123',
                           'targets': [load_registry()['queries']['comments']['name']]})
    assert error.value.code == 5
    assert transport.request_count == 0


def test_missing_mining_protocol_reports_failure_without_bypassing_transport():
    import _refresh
    transport = Transport()
    transport.mine = None
    result = _refresh.refresh(transport)
    assert set(result['failed'].values()) == {'mining_transport_unsupported'}
    assert transport.urls == []
    assert result['updated'] == []


def test_captured_common_flag_reaches_mined_candidate_in_same_refresh():
    import _refresh
    flag = '__relay_internal__pv__NewCommonrelayprovider'
    transport = Transport()
    name = load_registry()['queries']['comments']['name']
    transport.captured = lambda args: {'status': 200, 'url': args['url'], 'body': json.dumps({
        'queries': [{'name': name, 'doc_id': '800', 'variables': {flag: True}}],
        'failed': None, 'request_count': 2, 'count_complete': True})}
    replay = transport.query_spec
    def verify(spec, **kwargs):
        if spec.name == load_registry()['queries']['newsfeed']['name'] and not spec.relay_provider_flags.get(flag):
            raise FacebookError(6, 'Missing common provider flag')
        return replay(spec, **kwargs)
    transport.query_spec = verify
    result = _refresh.refresh(transport, capture=True, post='https://www.facebook.com/example/posts/123')
    assert 'newsfeed' in result['updated']
    assert json.loads((cache_dir() / 'registry.json').read_text())['relay_provider_flags'][flag] is True


def test_prefetched_provider_flags_verify_new_queries_without_opening_tabs():
    import _refresh
    flag = '__relay_internal__pv__PrefetchedCurrentrelayprovider'
    transport = Transport()
    mine = transport.mine
    def prefetched(url, names):
        result = mine(url, names)
        if url == 'https://www.facebook.com/':
            result['relay_provider_flags'] = {flag: False}
        return result
    transport.mine = prefetched
    replay = transport.query_spec
    def verify(spec, **kwargs):
        if flag not in spec.relay_provider_flags:
            raise FacebookError(6, 'Missing prefetch provider')
        return replay(spec, **kwargs)
    transport.query_spec = verify
    result = _refresh.refresh(transport)
    assert len(result['updated']) == 6
    assert transport.captures == []
    assert json.loads((cache_dir() / 'registry.json').read_text())['relay_provider_flags'][flag] is False
