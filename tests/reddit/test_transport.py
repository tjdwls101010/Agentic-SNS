import json
from pathlib import Path
import pytest
from reddit_skill._errors import RedditError
from reddit_skill._transport import Transport

LISTING = {'kind': 'Listing', 'data': {'children': [{'kind': 't3', 'data': {'name': 't3_abc'}}]}}


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setenv('REDDIT_ASIDE_BIN', str(Path(__file__).parent / 'fake_aside/aside'))
    log = tmp_path / 'calls.ndjson'
    monkeypatch.setenv('REDDIT_FAKE_LOG', str(log))
    def set_response(status=200, body=LISTING, ratelimit=None, url=None, location=None):
        envelope = {'status': status, 'url': url or 'https://www.reddit.com/hot.json',
                    'body': body if isinstance(body, str) else json.dumps(body), 'ratelimit': ratelimit or {}}
        if location:
            envelope['location'] = location
        monkeypatch.setenv('REDDIT_FAKE_OUTPUT', json.dumps(envelope))
    return set_response, log


def test_success_at_header_zero_survives_and_next_request_is_blocked(wire):
    response, log = wire
    response(ratelimit={'remaining': '0', 'used': '100', 'reset': '30'})
    transport = Transport()
    assert transport.get('/hot.json', 'listing') == LISTING
    assert transport.requests == 1
    assert transport.budget['remaining'] == 0
    with pytest.raises(RedditError) as caught:
        transport.get('/hot.json', 'listing')
    assert caught.value.code == 5
    assert len(log.read_text().splitlines()) == 1


@pytest.mark.parametrize('status,body,url,code,block', [
    (429, '<html>limit</html>', None, 5, 'rate_limit'),
    (403, '<html>js_challenge</html>', None, 5, 'challenge'),
    (403, '<html>blocked</html>', 'https://www.reddit.com/?js_challenge=1', 5, 'challenge'),
    (403, '<html>forbidden</html>', None, 6, None),
    (502, '<html>gateway</html>', None, 6, None),
    (404, {'message': 'Not Found', 'error': 404}, None, 9, None),
    (403, {'reason': 'gold_only'}, None, 9, None),
    (403, {'reason': 'quarantined'}, None, 9, None),
    (403, {'reason': 'new_reason'}, None, 6, None),
    (200, '', None, 6, None),
    (200, {'kind': 'Listing', 'data': {'children': []}}, None, 7, None),
])
def test_classification_and_persistent_blocks(wire, status, body, url, code, block):
    response, _ = wire
    response(status, body, url=url)
    transport = Transport()
    with pytest.raises(RedditError) as caught:
        transport.get('/hot.json', 'listing')
    assert caught.value.code == code
    assert (transport.budget['block'] or {}).get('reason') == block
    if block == 'challenge':
        assert transport.budget['block']['expires_at'] is None
    if block == 'rate_limit':
        assert transport.budget['block']['expires_at'] > transport.budget['observed_at']


@pytest.mark.parametrize('expect,body,code', [
    ('thing:t5', {'kind': 't5', 'data': {'display_name': 'python'}}, None),
    ('thing:t2', {'kind': 't2', 'data': {'name': 'example'}}, None),
    ('me', {'kind': 't2', 'data': {}}, 4),
    ('rules', {'rules': []}, None),
    ('morechildren', {'json': {'errors': [], 'data': {'things': []}}}, 7),
    ('morechildren', {'json': {'errors': [['BAD', 'bad request']], 'data': {'things': []}}}, 6),
    ('post_pair', [LISTING, {'kind': 'Listing', 'data': {'children': []}}], None),
    ('duplicates', [LISTING, {'kind': 'Listing', 'data': {'children': []}}], None),
    ('listing', {'kind': 'Listing', 'data': {}}, 6),
    ('listing', {'kind': 'Listing', 'data': {'children': [None]}}, 6),
])
def test_endpoint_envelopes(wire, expect, body, code):
    response, _ = wire
    response(body=body)
    transport = Transport()
    if code:
        with pytest.raises(RedditError) as caught:
            transport.get('/hot.json', expect)
        assert caught.value.code == code
    else:
        assert transport.get('/hot.json', expect) == body


def test_personal_listing_requires_explicit_empty_modhash(wire):
    response, _ = wire
    response(body={'kind': 'Listing', 'data': {'children': [], 'modhash': ''}})
    with pytest.raises(RedditError) as caught:
        Transport().get('/best.json', 'listing', personal=True)
    assert caught.value.code == 4


def test_path_builders_centralize_mappings_and_validate_targets():
    from reddit_skill._transport import build_request
    assert build_request('post', 'abc', sort='best') == {
        'path': '/comments/abc.json', 'expect': 'post_pair',
        'query': {'limit': 500, 'depth': 10, 'sort': 'confidence'}, 'personal': False}
    assert build_request('user', 'u/example', type='posts')['path'] == '/user/example/submitted.json'
    search = build_request('search', 'r/python', text='a & b', nsfw=True, type='subs', time='week')
    assert search['path'] == '/r/python/search.json'
    assert search['query'] == {'q': 'a & b', 'type': 'sr', 'include_over_18': 'on', 'restrict_sr': 1, 't': 'week'}
    assert build_request('me', type='saved')['personal'] is True
    assert build_request('about', 'u/example')['expect'] == 'thing:t2'
    with pytest.raises(RedditError):
        build_request('about', 'python')
    with pytest.raises(RedditError):
        build_request('sub', 'r/python', sort='../vote')


def test_manual_redirect_is_checked_and_each_hop_is_budgeted(wire, monkeypatch):
    _, log = wire
    monkeypatch.delenv('REDDIT_FAKE_OUTPUT', raising=False)
    monkeypatch.setenv('REDDIT_FAKE_RESPONSES', json.dumps({
        '/user/me/saved.json': {'status': 302, 'url': 'https://www.reddit.com/user/me/saved.json',
            'body': '', 'location': 'https://www.reddit.com/user/example/saved.json', 'ratelimit': {}}}))
    transport = Transport()
    assert transport.get('/user/me/saved.json', 'listing', personal=True) == LISTING
    assert transport.requests == 2
    assert len(log.read_text().splitlines()) == 2


@pytest.mark.parametrize('location', ['https://evil.com/hot.json', '//evil.com/hot.json',
    'https://www.reddit.com:443/hot.json', 'https://u@www.reddit.com/hot.json', '/api/vote.json'])
def test_unsafe_redirect_never_gets_second_request(wire, location):
    response, log = wire
    response(status=302, body='', location=location)
    with pytest.raises(RedditError):
        Transport().get('/hot.json', 'listing')
    assert len(log.read_text().splitlines()) == 1


def test_share_only_resolution_and_doctor(wire):
    response, _ = wire
    transport = Transport()
    assert transport.resolve('https://redd.it/abc').post_id == 'abc'
    assert transport.requests == 0
    response(body='<html>post</html>', url='https://www.reddit.com/comments/abc')
    assert transport.resolve('/r/python/s/xyz').post_id == 'abc'
    assert transport.requests == 1
    response(body={'kind': 't2', 'data': {'name': 'example'}})
    report = transport.doctor()
    assert report['account'] == 'example'
    assert report['requests'] == 2
    assert report['cache_bytes'] == 0
    assert report['budget']['expires_at'] > 0


def test_reject_invalid_request_before_reservation(wire):
    _, log = wire
    transport = Transport()
    for path, expect in [('/api/vote.json', 'listing'), ('https://evil.com/hot.json', 'listing'),
                         ('/hot.json', 'invented')]:
        with pytest.raises(RedditError) as caught:
            transport.get(path, expect)
        assert caught.value.code == 2
    assert transport.requests == 0
    assert not log.exists()


def test_total_request_cap_and_failed_process_reservation(wire, monkeypatch):
    _, log = wire
    transport = Transport(max_requests=1)
    monkeypatch.setenv('REDDIT_FAKE_EXIT', '1')
    with pytest.raises(RedditError) as caught:
        transport.get('/hot.json', 'listing')
    assert caught.value.code == 3
    assert transport.requests == 1
    assert transport.budget['remaining'] == 99
    with pytest.raises(RedditError) as caught:
        transport.get('/hot.json', 'listing')
    assert caught.value.code == 8
    assert len(log.read_text().splitlines()) == 1


def test_valid_encoded_search_query_in_response_url(wire):
    response, _ = wire
    response(url='https://www.reddit.com/search.json?q=a%20b&raw_json=1')
    assert Transport().get('/search.json', 'listing', query={'q': 'a b'}) == LISTING


def test_canonical_subreddit_comment_path_is_supported(wire):
    response, _ = wire
    response(body=[LISTING, {'kind': 'Listing', 'data': {'children': []}}])
    assert Transport().get('/r/python/comments/abc/_/def.json', 'post_pair')[0] == LISTING


def test_redirect_loop_stops_after_three_attempts(wire):
    response, log = wire
    response(status=302, body='', location='/hot.json')
    transport = Transport()
    with pytest.raises(RedditError) as caught:
        transport.get('/hot.json', 'listing')
    assert caught.value.code == 6
    assert transport.requests == 3
    assert len(log.read_text().splitlines()) == 3


@pytest.mark.parametrize('reason', [[], {}, ['private']])
def test_malformed_closed_reason_is_envelope_error(wire, reason):
    response, _ = wire
    response(status=403, body={'reason': reason})
    with pytest.raises(RedditError) as caught:
        Transport().get('/hot.json', 'listing')
    assert caught.value.code == 6


def test_doctor_rejects_non_text_identity(wire):
    response, _ = wire
    response(body={'kind': 't2', 'data': {'name': 123}})
    with pytest.raises(RedditError) as caught:
        Transport().doctor()
    assert caught.value.code == 6


def test_malformed_thing_kind_is_envelope_error(wire):
    response, _ = wire
    response(body={'kind': 'Listing', 'data': {'children': [{'kind': [], 'data': {}}]}})
    with pytest.raises(RedditError) as caught:
        Transport().get('/hot.json', 'listing')
    assert caught.value.code == 6


@pytest.mark.parametrize('replies', [{'kind': 'Listing', 'data': None},
    {'kind': 'Listing', 'data': {'children': [None]}}, '<html>unexpected</html>'])
def test_malformed_nested_replies_are_rejected(wire, replies):
    response, _ = wire
    comment = {'kind': 't1', 'data': {'name': 't1_def', 'replies': replies}}
    response(body=[LISTING, {'kind': 'Listing', 'data': {'children': [comment]}}])
    with pytest.raises(RedditError) as caught:
        Transport().get('/comments/abc.json', 'post_pair')
    assert caught.value.code == 6


def test_share_redirect_to_post_is_parsed_without_redundant_fetch(wire):
    response, log = wire
    response(status=302, body='', location='/r/python/comments/abc/title/',
             url='https://www.reddit.com/r/python/s/xyz')
    client = Transport()
    assert client.resolve('/r/python/s/xyz').post_id == 'abc'
    assert client.requests == 1
    assert len(log.read_text().splitlines()) == 1


def test_share_intermediate_zero_stops_before_next_hop(wire):
    response, log = wire
    response(status=302, body='', location='/r/python/s/next',
             url='https://www.reddit.com/r/python/s/xyz',
             ratelimit={'remaining': '0', 'used': '100', 'reset': '30'})
    client = Transport()
    with pytest.raises(RedditError) as caught:
        client.resolve('/r/python/s/xyz')
    assert caught.value.code == 5
    assert client.requests == 1
    assert len(log.read_text().splitlines()) == 1


def test_share_each_actual_hop_has_reservation(wire, monkeypatch):
    _, log = wire
    monkeypatch.delenv('REDDIT_FAKE_OUTPUT', raising=False)
    monkeypatch.setenv('REDDIT_FAKE_RESPONSES', json.dumps({
        'https://www.reddit.com/r/python/s/xyz': {'status': 302,
            'url': 'https://www.reddit.com/r/python/s/xyz', 'body': '',
            'location': '/r/python/s/next', 'ratelimit': {}},
        'https://www.reddit.com/r/python/s/next': {'status': 302,
            'url': 'https://www.reddit.com/r/python/s/next', 'body': '',
            'location': '/comments/abc', 'ratelimit': {}}}))
    client = Transport()
    assert client.resolve('/r/python/s/xyz').post_id == 'abc'
    assert client.requests == 2
    assert client.budget['remaining'] == 98
    assert len(log.read_text().splitlines()) == 2


def test_share_never_makes_fourth_actual_request(wire):
    response, log = wire
    response(status=302, body='', location='/r/python/s/next',
             url='https://www.reddit.com/r/python/s/xyz')
    client = Transport()
    with pytest.raises(RedditError) as caught:
        client.resolve('/r/python/s/xyz')
    assert caught.value.code == 2
    assert client.requests == 3
    assert len(log.read_text().splitlines()) == 3


@pytest.mark.parametrize('location', ['https://evil.com/comments/abc', '//evil.com/comments/abc',
    'https://user@www.reddit.com/comments/abc', 'https://www.reddit.com:443/comments/abc'])
def test_share_validates_every_redirect_before_request(wire, location):
    response, log = wire
    response(status=302, body='', location=location, url='https://www.reddit.com/r/python/s/xyz')
    with pytest.raises(RedditError) as caught:
        Transport().resolve('/r/python/s/xyz')
    assert caught.value.code == 2
    assert len(log.read_text().splitlines()) == 1


def test_share_zero_can_return_locally_parsed_encoded_permalink(wire):
    response, log = wire
    response(status=302, body='', location='/r/python/comments/abc/hello%20world/def/',
             url='https://www.reddit.com/r/python/s/xyz',
             ratelimit={'remaining': '0', 'used': '100', 'reset': '30'})
    client = Transport()
    assert client.resolve('/r/python/s/xyz').comment_id == 'def'
    assert client.budget['remaining'] == 0
    assert len(log.read_text().splitlines()) == 1
