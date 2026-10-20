"""How a reading ends when Reddit pushes back or changes, through the real cli.py: blocks outrank everything, records
read before a failure are kept, a spent Reddit window stops where more: resumes, and nothing is sent after a block."""
import json

from conftest import run_cli
from test_cli_lists import listing, more_line, post

CHALLENGE = {'status': 403, 'body': '<html><script src="/js_challenge.js"></script></html>'}


def two_pages(reddit, second):
    reddit.me().json('/r/example/new.json', listing([post('a')], after='t3_a'), query={'limit': '100'})
    reddit.respond(second, path='/r/example/new.json', query={'after': 't3_a'})


def test_a_challenge_after_records_is_exit_5_with_the_records_and_blocks_the_next_command(reddit):
    two_pages(reddit, CHALLENGE)
    code, out, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    assert code == 5 and 'title a' in out and 'coverage: incomplete — Reddit showed a browser challenge' in out
    assert 'more:' not in out, 'no invitation to send again'
    sent = len(reddit.fetches())
    code, out, _ = run_cli(reddit, 'feed')
    assert code == 5 and json.loads(out)['reason'] == 'challenge' and len(reddit.fetches()) == sent


def test_a_rate_limit_blocks_its_bucket(reddit):
    two_pages(reddit, {'status': 429, 'body': '', 'ratelimit': {'used': '100', 'remaining': '0', 'reset': '200'}})
    code, out, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    assert code == 5 and 'retry after 200 seconds' in out
    sent = len(reddit.fetches())
    code, out, _ = run_cli(reddit, 'doctor')
    assert code == 5 and json.loads(out)['reason'] == 'rate_limit' and len(reddit.fetches()) == sent


def test_a_spent_window_stops_where_more_resumes(reddit):
    reddit.me().json('/r/example/new.json', listing([post('a')], after='t3_a'), query={'limit': '100'},
                     ratelimit={'used': '100', 'remaining': '0', 'reset': '120'})
    code, out, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    first = out.splitlines()[0]
    assert code == 0 and 'stopped=window_spent' in first and 'reddit window 0/100, resets in 12' in first
    assert 'it resets in 12' in out and more_line(out) is not None
    assert len(reddit.fetches()) == 2, 'the spent bucket was not sent to'


def test_a_changed_response_shape_is_exit_6_before_records_and_8_after(reddit):
    reddit.me().json('/r/example/new.json', {'kind': 'Listing', 'data': {'children': [{'kind': 't9', 'data': {}}]}})
    code, out, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new')
    assert code == 6 and json.loads(out)['error'] == 'failed'
    two_pages(reddit, {'body': {'kind': 'Listing', 'data': {'children': [{'kind': 't9', 'data': {}}]}}})
    code, out, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    assert code == 8 and 'title a' in out and 'shape' in out


def test_aside_failing_is_exit_3(reddit):
    reddit.me().respond({'__raw_stdout': 'nothing useful\n'}, path='/r/example/hot.json')
    code, out, _ = run_cli(reddit, 'sub', 'r/example')
    assert code == 3 and json.loads(out)['error'] == 'aside'


def test_a_first_request_without_rate_limit_headers_stops_that_bucket(reddit):
    reddit.respond({'body': {'kind': 't2', 'data': {'name': 'example_viewer'}},
                    'ratelimit': {'used': None, 'remaining': None, 'reset': None}}, path='/api/me.json')
    code, out, _ = run_cli(reddit, 'sub', 'r/example')
    envelope = json.loads(out)
    assert code == 6 and envelope['reason'] == 'unmetered' and len(reddit.fetches()) == 1


def test_a_failure_after_a_continuation_point_keeps_the_handle(reddit):
    two_pages(reddit, {'status': 503, 'body': '{}'})
    code, out, _ = run_cli(reddit, 'sub', 'r/example', '--sort', 'new', '--limit', '5')
    assert code == 8 and 'title a' in out and more_line(out) is not None
