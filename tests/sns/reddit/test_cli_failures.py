"""How a reading ends when Reddit pushes back or changes, through the real cli: blocks outrank everything, records read
before a failure are kept, a 429 or a spent bucket stops only its bucket (exit 10 before records, a resumable stop
after), an answer with no rate-limit headers leaves the window unknown and pacing alone spaces requests, and nothing is
sent after a block."""
import json
import time

from tests.sns.reddit.shapes import CHALLENGE, listing, post
from tests.sns.support.cli import command_of, more_line

NO_HEADERS = {'used': None, 'remaining': None, 'reset': None}


def two_pages(reddit, second):
    reddit.me().json('/r/example/new.json', listing([post('a')], after='t3_a'), query={'limit': 100})
    reddit.respond(second, path='/r/example/new.json', query={'after': 't3_a'})


def test_a_challenge_after_records_is_exit_5_with_the_records_and_blocks_the_next_command(reddit):
    two_pages(reddit, CHALLENGE)
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    assert code == 5 and 'title a' in out and 'coverage: incomplete — Reddit showed a browser challenge' in out
    assert 'more:' not in out, 'no invitation to send again'
    sent = len(reddit.fetches())
    code, out, _ = reddit.run('reddit', 'feed')
    assert code == 5 and 'doctor --unblock' in json.loads(out)['fix'] and len(reddit.fetches()) == sent


def test_a_429_after_records_stops_its_bucket_where_more_resumes(reddit):
    two_pages(reddit, {'status': 429, 'body': '', 'ratelimit': {'used': '100', 'remaining': '0', 'reset': '200'}})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '5', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['stop_reason'] == 'rate_limited' and envelope['results'][0]['id'] == 't3_a'
    assert envelope['limit']['scope'] == 'general' and 190 < envelope['limit']['reset'] - time.time() < 215
    assert 'sub r/example' in envelope['next'] and '--after' in envelope['next']
    sent = len(reddit.fetches())
    code, out, _ = reddit.run('reddit', 'doctor')
    assert code == 10 and json.loads(out)['error'] == 'scope_limit' and len(reddit.fetches()) == sent


def test_a_429_stops_only_its_bucket(reddit):
    reddit.respond({'status': 429, 'body': '', 'ratelimit': {'used': '600', 'remaining': '0', 'reset': '200'}},
                   path='/r/example/wiki/index.json')
    code, out, _ = reddit.run('reddit', 'wiki', 'r/example')
    assert code == 10 and json.loads(out)['limit']['scope'] == 'wiki'
    sent = len(reddit.fetches())
    code, out, _ = reddit.run('reddit', 'wiki', 'r/example')
    assert code == 10 and len(reddit.fetches()) == sent, 'the wiki bucket is not sent to'
    reddit.me().json('/r/example/hot.json', listing([post('a')]))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    assert code == 0, 'the general bucket goes on'


def test_a_429_without_a_reset_lasts_the_policys_ten_minutes(reddit):
    reddit.respond({'status': 429, 'body': '', 'ratelimit': NO_HEADERS}, path='/api/me.json')
    code, out, _ = reddit.run('reddit', 'feed', '--json')
    envelope = json.loads(out)
    assert code == 10 and 590 < envelope['limit']['reset'] - time.time() < 615


def test_a_spent_window_before_any_record_is_exit_10_and_after_records_resumes(reddit):
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}},
                    'ratelimit': {'used': '100', 'remaining': '0', 'reset': '120'}}, path='/api/me.json')
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--json')
    envelope = json.loads(out)
    assert code == 10 and envelope['error'] == 'scope_limit' and envelope['limit']['scope'] == 'general'
    assert len(reddit.fetches()) == 1, 'the spent bucket was not sent to'


def test_a_spent_window_after_records_stops_where_more_resumes(reddit):
    reddit.me().json('/r/example/new.json', listing([post('a')], after='t3_a'), query={'limit': 100},
                     ratelimit={'used': '100', 'remaining': '0', 'reset': '120'})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    first = out.splitlines()[0]
    assert code == 0 and 'stopped=rate_limited' in first and 'limit general' in first and 'title a' in out
    assert more_line(out) is not None and len(reddit.fetches()) == 2, 'the spent bucket was not sent to'


def test_a_changed_response_shape_is_exit_6_before_records_and_8_after(reddit):
    reddit.me().json('/r/example/new.json', {'kind': 'Listing', 'data': {'children': [{'kind': 't9', 'data': {}}]}})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new')
    assert code == 6 and json.loads(out)['error'] == 'failed'
    two_pages(reddit, {'body': {'kind': 'Listing', 'data': {'children': [{'kind': 't9', 'data': {}}]}}})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    assert code == 8 and 'title a' in out and 'shape' in out


def test_aside_failing_is_exit_3(reddit):
    reddit.me().respond({'__raw_stdout': 'nothing useful\n'}, path='/r/example/hot.json')
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    assert code == 3 and json.loads(out)['error'] == 'aside'


def test_an_envelope_the_snippet_did_not_return_whole_is_an_aside_failure(reddit):
    reddit.me().respond({'__raw_stdout': json.dumps({'kind': 'result', 'chunks': 0, 'body': json.dumps(
        {'status': 200, 'url': 'x', 'body': 5})}) + '\n'}, path='/r/example/hot.json')
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    assert code == 3 and 'cannot read' in json.loads(out)['message']


def test_a_first_answer_without_rate_limit_headers_does_not_stop_the_bucket(reddit):
    """Reddit not reporting its window is not a reason to refuse (plan S2): the bucket stays unknown, only the pacing
    spaces requests, and the first line says the window was not reported."""
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}}, 'ratelimit': NO_HEADERS},
                   path='/api/me.json')
    reddit.respond({'body': listing([post('a')]), 'ratelimit': NO_HEADERS}, path='/r/example/hot.json')
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    first = out.splitlines()[0]
    assert code == 0 and len(reddit.fetches()) == 2 and 'title a' in out
    assert 'general window not reported' in first and 'requests=2' in first


def test_a_failure_after_a_continuation_point_keeps_the_handle(reddit):
    two_pages(reddit, {'status': 503, 'body': '{}'})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    assert code == 8 and 'title a' in out and more_line(out) is not None


def test_a_continuation_after_a_429_resumes_once_the_bucket_reopens(reddit, monkeypatch):
    two_pages(reddit, {'status': 429, 'body': '', 'ratelimit': {'used': '100', 'remaining': '0', 'reset': '200'}})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    words = command_of(more_line(out))
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + 400)  # the window has reset
    reddit.me().json('/r/example/new.json', listing([post('b')]), query={'after': 't3_a'})
    code, out, _ = reddit.run(*words)
    assert code == 0 and 'title b' in out
