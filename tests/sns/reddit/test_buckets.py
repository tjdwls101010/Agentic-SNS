"""Reddit's rate-limit buckets as the commands meet them (fixture limits.json), through the real cli and the protection
store on a real filesystem: what the headers make of a bucket, the slow-down near the end, one bucket not slowing the
other, a challenge blocking every bucket, a reservation that survives a kill, state that cannot be read. The mechanism
itself (reservations, probes, holds, the verified unblock) is tested for every platform in core/test_protection.py."""
import json
import time

from tests.sns.reddit.shapes import CHALLENGE, listing, post
from tests.sns.support.cli import run_cli

NO_HEADERS = {'used': None, 'remaining': None, 'reset': None}


def protection(data_dir, name):
    return json.loads((data_dir / 'reddit/u0/protection' / name).read_text())


def scopes(data_dir):
    return protection(data_dir, 'scopes.json')


def test_the_headers_of_each_answer_make_the_bucket_known(reddit, data_dir):
    reddit.me().json('/r/example/hot.json', listing([post('a')]))
    reddit.run('reddit', 'sub', 'r/example')
    general = scopes(data_dir)['general']
    assert (general['status'], general['limit'], general['remaining']) == ('known', 100, 98)
    assert 290 <= general['reset_at'] - time.time() <= 305


def test_an_answer_without_usable_headers_keeps_the_reservation_of_a_known_bucket(reddit, data_dir):
    reddit.me().json('/r/example/hot.json', listing([post('a')]))
    reddit.run('reddit', 'sub', 'r/example')
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}}, 'ratelimit': NO_HEADERS},
                   path='/api/me.json')
    reddit.run('reddit', 'doctor')
    general = scopes(data_dir)['general']
    assert general['status'] == 'known' and general['remaining'] == 97, 'one less for the request that was sent'


def test_a_bucket_whose_reset_has_passed_is_unknown_again_and_the_next_request_is_a_probe(reddit, data_dir):
    path = data_dir / 'reddit/u0/protection'
    path.mkdir(parents=True)
    (path / 'scopes.json').write_text(json.dumps({'general': {'status': 'known', 'limit': 100, 'remaining': 0,
                                                              'reset_at': time.time() - 1}}))
    reddit.me()
    code = reddit.run('reddit', 'doctor')[0]
    assert code == 0 and scopes(data_dir)['general']['status'] == 'known', 'the probe was answered with headers'


def test_a_bucket_running_low_spaces_the_next_request_by_the_time_left_over_what_is_left(reddit, data_dir):
    """slow-down-when-half-spent: 0 < remaining <= used → wait (seconds to reset / remaining) before the next request."""
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}},
                    'ratelimit': {'used': '80', 'remaining': '20', 'reset': '200'}}, path='/api/me.json')
    reddit.run('reddit', 'doctor')
    slow = scopes(data_dir)['general']['slow_until'] - time.time()
    assert 8 <= slow <= 11, slow


def test_a_bucket_with_more_left_than_used_is_paced_only(reddit, data_dir):
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}},
                    'ratelimit': {'used': '30', 'remaining': '70', 'reset': '200'}}, path='/api/me.json')
    reddit.run('reddit', 'doctor')
    assert 'slow_until' not in scopes(data_dir)['general']


def test_a_spent_general_bucket_does_not_stop_the_wiki(reddit, data_dir):
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}},
                    'ratelimit': {'used': '100', 'remaining': '0', 'reset': '120'}}, path='/api/me.json')
    assert reddit.run('reddit', 'doctor')[0] == 0
    assert reddit.run('reddit', 'doctor')[0] == 10, 'the general bucket is spent: not sent to'
    reddit.json('/r/example/wiki/index.json', {'kind': 'wikipage', 'data': {'content_md': 'x', 'revision_id': 'r'}})
    code, out, _ = reddit.run('reddit', 'wiki', 'r/example')
    assert code == 0 and 'limit wiki 599/600' in out.splitlines()[0]


def test_a_challenge_blocks_every_bucket_until_a_person_clears_it(reddit, data_dir):
    reddit.me().respond(CHALLENGE, path='/r/example/hot.json')
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    assert code == 5
    sent = len(reddit.fetches())
    for argv in (('wiki', 'r/example'), ('feed',), ('about', 'r/example'), ('doctor',)):
        assert reddit.run('reddit', *argv)[0] == 5, argv
    assert len(reddit.fetches()) == sent
    assert protection(data_dir, 'blocks.json')['person']['reason'] == 'challenge'


def test_a_request_killed_after_sending_is_still_counted_and_paced(reddit, data_dir, tmp_path):
    reddit.me().respond({'__kill_parent': True}, path='/r/example/hot.json')
    reddit.browser.write()
    done = run_cli('reddit', 'sub', 'r/example', browser=reddit.browser,
                   env={'SNS_DATA_DIR': str(data_dir), 'SNS_IDLE_SECONDS': 'off'})
    assert done.returncode != 0
    log = [json.loads(line) for line in (data_dir / 'reddit/u0/protection/requests.jsonl').read_text().splitlines()]
    assert [(line['scope'], line['n'], line['outcome']) for line in log if line['n']] == \
        [('general', 1, 'sent'), ('general', 1, 'sent')]
    assert protection(data_dir, 'pace.json')['next_allowed_at'] > time.time()


def test_a_low_bucket_keeps_slowing_down_when_headers_go_missing(reddit, data_dir):
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}},
                    'ratelimit': {'used': '90', 'remaining': '10', 'reset': '100'}}, path='/api/me.json')
    reddit.run('reddit', 'doctor')
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}}, 'ratelimit': NO_HEADERS},
                   path='/api/me.json')
    reddit.run('reddit', 'doctor')
    general = scopes(data_dir)['general']
    assert general['remaining'] == 9 and general['slow_until'] - time.time() > 5, 'still running low: still slowed'


def test_a_killed_unblock_check_keeps_the_block(reddit, data_dir):
    path = data_dir / 'reddit/u0/protection'
    path.mkdir(parents=True)
    (path / 'blocks.json').write_text(json.dumps({'person': {'reason': 'challenge', 'at': time.time(), 'viewer': None},
                                                  'hold': None}))
    reddit.respond({'__kill_parent': True}, path='/api/me.json')
    reddit.browser.write()
    done = run_cli('reddit', 'doctor', '--unblock', browser=reddit.browser,
                   env={'SNS_DATA_DIR': str(data_dir), 'SNS_IDLE_SECONDS': 'off'})
    assert done.returncode != 0
    assert protection(data_dir, 'blocks.json')['person']['reason'] == 'challenge'


def test_protection_state_that_cannot_be_read_refuses_every_request(reddit, data_dir):
    path = data_dir / 'reddit/u0/protection'
    path.mkdir(parents=True)
    (path / 'scopes.json').write_text('{"general": {"status": "maybe"}}')
    code, out, _ = reddit.run('reddit', 'feed', '--sort', 'new')
    assert code == 5 and json.loads(out)['error'] == 'blocked' and reddit.fetches() == []


def test_there_is_no_request_budget(reddit):
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--max-requests', '5')
    assert code == 2 and reddit.fetches() == []
    assert 'max-requests' not in run_cli('reddit', 'sub', '--help').stdout
