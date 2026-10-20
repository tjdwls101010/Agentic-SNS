"""What one request is, through the real cli and the fake Aside (fixtures redirects, aside_output): where a redirect may
lead and how many hops a read follows, how a share link is resolved, what makes an answer from the fetch snippet unusable,
and what the diagnostic line shows."""
import json

import pytest

from tests.sns.reddit.scene import fixture
from tests.sns.reddit.shapes import listing, pair, post, t1

REDIRECTS = fixture('redirects.json')
FIRST = '/r/example/hot.json'


def follows(case):
    return case.get('follow', False)


@pytest.mark.parametrize('case', REDIRECTS['locations']['cases'], ids=lambda c: str(c['location']))
def test_a_redirect_is_followed_only_to_www_reddit_com_and_an_allowed_path(reddit, case):
    reddit.me().respond({'status': 301, 'location': case['location']}, path=FIRST)
    if follows(case):
        reddit.json(case['path'], listing([post('a')]), query=case.get('query'))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    if follows(case):
        assert code == 0 and reddit.paths()[-1] == case['path'], case
    else:
        assert code == 6 and reddit.paths() == ['/api/me.json', FIRST], 'the refused location is never requested'


@pytest.mark.parametrize('case', REDIRECTS['hops']['cases'], ids=lambda c: c['name'])
def test_each_redirect_hop_is_a_request_and_three_in_a_row_fail(reddit, case):
    reddit.me()
    path = FIRST
    for answer in case['answers']:
        response = {'status': answer['status']}
        if answer['status'] == 200:
            response['body'] = listing([post('a')])
        else:
            response['location'] = answer['location']
        reddit.respond(response, path=path)
        path = answer.get('location', path)
        if path.startswith('http'):
            break
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--json')
    envelope = json.loads(out)
    assert envelope['request_count'] == case['charged'] + 1, 'the hops and the account check'
    assert (code == 0) == (case['outcome'] == 'ok'), out
    if case['outcome'] != 'ok':
        assert code == 6 and envelope['error'] == 'failed'


def share_run(reddit, case, *extra):
    reddit.me()
    for answer in case['answers']:  # every share case is one answer to the share link itself
        reddit.respond({key: value for key, value in answer.items() if key in ('status', 'location', 'body', 'url')},
                       url=case['url'])
    return reddit.run('reddit', 'post', case['url'], '--json', *extra)


@pytest.mark.parametrize('case', [c for c in REDIRECTS['share']['cases'] if 'resolves_to' in c], ids=lambda c: c['name'])
def test_a_share_link_resolves_to_its_post_or_comment_one_request_per_hop(reddit, case):
    target = case['resolves_to']
    path = f'/comments/{target["post_id"]}' + (f'/_/{target["comment_id"]}' if target['comment_id'] else '') + '.json'
    reddit.json(path, pair([t1(target['comment_id'] or 'c1', 't3_aaa1')]))
    code, out, _ = share_run(reddit, case)
    shares = [p for p in reddit.paths() if p.startswith('https://')]
    assert code == 0, out
    assert len(shares) == case['charged'] and reddit.paths()[-1] == path


def test_a_share_link_that_leads_nowhere_is_an_argument_error(reddit):
    case = next(c for c in REDIRECTS['share']['cases'] if c['name'] == 'share-unresolved')
    code, out, _ = share_run(reddit, case)
    assert code == 2 and 'Open the share link in the Aside browser' in json.loads(out)['fix']


def test_a_429_on_a_share_link_stops_share_links_only(reddit):
    share = 'https://www.reddit.com/r/example/s/AbC123'
    reddit.me().respond({'status': 429, 'body': '', 'ratelimit': {'used': None, 'remaining': None, 'reset': '300'}}, url=share)
    code, out, _ = reddit.run('reddit', 'post', share, '--json')
    assert code == 10 and json.loads(out)['limit']['scope'] == 'share'
    sent = len(reddit.fetches())
    reddit.me()
    code, out, _ = reddit.run('reddit', 'post', share)
    assert code == 10 and reddit.paths()[sent:] == ['/api/me.json'], 'the share link is not sent again'
    reddit.me().json('/comments/aaa1.json', pair([t1('c1', 't3_aaa1')]))
    code, out, _ = reddit.run('reddit', 'post', 'aaa1')
    assert code == 0, 'a post by its id still reads: the general bucket is not stopped'


def test_a_challenge_on_a_share_link_blocks_the_account(reddit):
    case = next(c for c in REDIRECTS['share']['cases'] if c['name'] == 'share-blocked')
    code, out, _ = share_run(reddit, case)
    assert code == 5 and json.loads(out)['error'] == 'blocked'


# --- what the fetch snippet may return -------------------------------------------------------------------------------

GOOD = {'status': 200, 'url': 'https://www.reddit.com/r/example/hot.json', 'body': '{}', 'location': None,
        'ratelimit': {'used': '1', 'remaining': '99', 'reset': '300'}}


def raw(envelope):
    return {'__raw_stdout': json.dumps({'kind': 'result', 'chunks': 0, 'body': json.dumps(envelope)}) + '\n'}


@pytest.mark.parametrize('name, change', [
    ('status-out-of-range', {'status': 99}), ('status-above-range', {'status': 600}),
    ('status-not-a-number', {'status': '200'}), ('ratelimit-missing', {'ratelimit': None}),
    ('ratelimit-not-a-dict', {'ratelimit': '1/99'}), ('url-missing', {'url': None}), ('body-not-a-string', {'body': {}}),
    ('location-a-number', {'location': 3})], ids=lambda v: v if isinstance(v, str) else '')
def test_an_envelope_the_snippet_returned_malformed_is_an_aside_failure(reddit, name, change):
    reddit.me().respond(raw({**GOOD, **change}), path=FIRST)
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    assert code == 3 and json.loads(out)['error'] == 'aside', name


@pytest.mark.parametrize('case', [c for c in fixture('aside_output.json')['cases'] if c.get('exit')],
                         ids=lambda c: c['name'])
def test_aside_exiting_abnormally_is_an_aside_failure(reddit, case):
    """lost-connection, daemon-unreachable, other-failure: a nonzero exit of the REPL run is exit 3 whatever it said."""
    reddit.me().respond({'__raw_stdout': case['stdout'] + case['stderr'], '__exit': case['exit']}, path=FIRST)
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    assert code == 3 and json.loads(out)['error'] == 'aside'


def test_the_fixtures_error_cases_are_covered_by_the_core_protocol_tests():
    """aside_output.json describes the old body_chunk protocol; what Aside prints and how it is read (chunks in order,
    lost connection, timeout) is the shared protocol of aside/program.js, tested in core/test_aside.py. The cases that
    are about the envelope itself are the ones above."""
    names = {case['name'] for case in fixture('aside_output.json')['cases']}
    assert {'status-out-of-range', 'ratelimit-missing', 'lost-connection', 'process-timeout'} <= names


def test_the_diagnostic_line_shows_request_metadata_without_credentials(reddit):
    reddit.me().json(FIRST, listing([post('a')]))
    code, out, err = reddit.run('--verbose', 'reddit', 'sub', 'r/example')
    stages = [json.loads(line) for line in err.splitlines() if line.startswith('{')]
    assert code == 0 and [s['path'] for s in stages] == ['/api/me.json', FIRST]
    assert all(s['stage'] == 'request' and s['status'] == 200 and 'remaining' in s['ratelimit'] for s in stages)
    assert 'cookie' not in err.lower() and 'modhash' not in err.lower()
