"""What Facebook needs of Aside (sns.aside, the core's system): the output cases of fixtures/aside_output.json through
the real wrapper. The account, the deadline clamp and the protocol itself are core/test_aside.py; the opening of
Facebook's tab (`aside <url>`) is exercised through doctor in test_cli_doctor.py."""
import json
import stat
import sys

import pytest

from sns.aside import Aside, parse
from sns.clock import Deadline
from sns.errors import SnsError
from tests.sns.facebook.data import fixture

CASES = fixture('aside_output.json')['cases']


@pytest.fixture(autouse=True)
def _account(monkeypatch, data_dir):
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT', 'u0')  # no `aside account status` in these tests


def fake_binary(tmp_path, case):
    script = tmp_path / 'aside'
    sleep = 'import time\ntime.sleep(5)\n' if case.get('timed_out') else ''
    script.write_text(f'#!{sys.executable}\nimport sys\n{sleep}sys.stdout.write({case["stdout"]!r})\n'
                      f'sys.stderr.write({case["stderr"]!r})\nsys.exit({case["exit"] or 0})\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_aside_output(tmp_path, monkeypatch, case):
    monkeypatch.setenv('SNS_ASIDE_BIN', str(fake_binary(tmp_path, case)))
    seconds = 1 if case.get('timed_out') else None
    aside = Aside('facebook', Deadline(30))
    if 'value' in case['outcome']:
        assert aside.evaluate('T1', 'async () => 1', {}, seconds) == case['outcome']['value']
        assert parse(case['stdout']) == case['outcome']['value']
        return
    with pytest.raises(SnsError) as error:
        aside.evaluate('T1', 'async () => 1', {}, seconds)
    assert error.value.kind == 'aside'
    kind = case['outcome']['error']
    assert (error.value.reason == 'tab_missing') is (kind == 'tab_missing')
    if kind == 'lost':
        assert 'lost its connection' in error.value.message
    if kind == 'timeout':
        assert error.value.reason == 'timeout'


@pytest.mark.parametrize('character', [' ', ' ', '\u0085'])
def test_line_separators_inside_strings_survive_the_program_output(character):
    """JSON.stringify leaves these literal; only a newline ends a line of program output."""
    body = json.dumps({'text': f'A{character}B'}, ensure_ascii=False)
    stdout = json.dumps({'kind': 'result', 'chunks': 0, 'body': body}, ensure_ascii=False) + '\n'
    assert parse(stdout) == {'text': f'A{character}B'}
