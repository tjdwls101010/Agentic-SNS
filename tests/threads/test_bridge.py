"""The Aside bridge through the CLI: a large page arrives in ordered chunks, and anything else is refused."""
import json

import pytest

from .helpers import data, run_cli


def chunked(body, parts=3, order=None, declared=None, extra=''):
    size = len(body) // parts + 1
    pieces = [body[i:i + size] for i in range(0, len(body), size)]
    order = order or list(range(len(pieces)))
    lines = [json.dumps({'kind': 'body_chunk', 'index': j, 'body': pieces[j]}) for j in order]
    footer = {'status': 200, 'url': 'https://www.threads.com/', 'body': '',
              'body_chunks': len(pieces) if declared is None else declared}
    return extra + '\n'.join(lines + [json.dumps(footer)]) + '\n'


def test_a_chunked_page_is_reassembled_in_order(routes):
    routes.set('/', {'raw_stdout': chunked(routes.body('/'))}).write()
    result = run_cli('doctor')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data(result)['viewer'] == 'fixture_viewer'


def test_terminal_colour_codes_around_the_envelope_are_ignored(routes):
    envelope = json.dumps({'status': 200, 'url': 'https://www.threads.com/', 'body': routes.body('/')})
    routes.set('/', {'raw_stdout': 'Aside ready\n\x1b[32m' + envelope + '\x1b[0m\n'}).write()
    assert run_cli('doctor').returncode == 0


@pytest.mark.parametrize('stdout', [
    lambda body: chunked(body, order=[1, 0, 2]),
    lambda body: chunked(body, declared=4),
    lambda body: chunked(body, declared=2),
    lambda body: '{broken\n',
    lambda body: json.dumps({'status': 200, 'url': 'https://www.threads.com/', 'body': body}) * 2 + '\n',
    lambda body: json.dumps({'status': 200, 'url': 'https://www.threads.com/', 'body_file': '/tmp/x'}) + '\n',
    lambda body: json.dumps({'status': 42, 'url': 'https://www.threads.com/', 'body': body}) + '\n',
], ids=['out-of-order', 'missing-chunk', 'extra-chunk', 'malformed', 'two-envelopes', 'body-file', 'bad-status'])
def test_an_envelope_that_is_not_exactly_one_response_is_refused(routes, stdout):
    routes.set('/', {'raw_stdout': stdout(routes.body('/'))}).write()
    result = run_cli('doctor')
    assert result.returncode == 3
    assert data(result)['error'] == 'aside'


def test_a_lost_connection_is_reported_as_the_bridge(routes):
    routes.set('/', {'mode': 'timeout'}).write()
    result = run_cli('doctor')
    assert result.returncode == 3
    assert 'lost its connection' in data(result)['message']
