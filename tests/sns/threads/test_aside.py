"""What Threads needs of Aside (sns.aside, the core's system): the output cases of fixtures/aside_output.json through the
real wrapper, and `aside <url>` (how a Threads tab is opened). The account, the deadline clamp and the protocol itself are
core/test_aside.py."""
import stat
import sys

import pytest

from sns.aside import Aside, parse
from sns.clock import Deadline
from sns.errors import SnsError
from tests.sns.threads.data import fixture

CASES = fixture('aside_output.json')['cases']


@pytest.fixture(autouse=True)
def _account(monkeypatch, data_dir):
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT', 'u0')  # no `aside account status` in these tests


def aside(seconds=30):
    return Aside('threads', Deadline(seconds))


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
    # the process-timeout case is a run that never finishes: a one-second limit stands in for the REPL's 125 s
    seconds = 1 if case.get('timed_out') else None
    if 'value' in case['outcome']:
        assert aside().evaluate('T1', 'async () => 1', {}, seconds) == case['outcome']['value']
        assert parse(case['stdout']) == case['outcome']['value']
        return
    with pytest.raises(SnsError) as error:
        aside().evaluate('T1', 'async () => 1', {}, seconds)
    assert error.value.kind == 'aside'
    kind = case['outcome']['error']
    assert (error.value.reason == 'tab_missing') is (kind == 'tab_missing')
    if kind == 'lost':
        assert 'lost its connection' in error.value.message
    if kind == 'timeout':
        assert error.value.reason == 'timeout'  # the request may have been made: the caller keeps the slot charged


def test_a_tab_is_opened_by_its_address_and_a_failed_open_is_an_aside_failure(tmp_path, monkeypatch):
    script = tmp_path / 'aside'
    script.write_text(f'#!{sys.executable}\nimport sys\nopen({str(tmp_path / "args")!r}, "w").write(" ".join(sys.argv[1:]))\n'
                      'sys.exit(1 if "--fail" in sys.argv else 0)\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('SNS_ASIDE_BIN', str(script))
    aside().open('https://www.threads.com/search')
    assert (tmp_path / 'args').read_text() == '--account u0 https://www.threads.com/search'
    with pytest.raises(SnsError) as error:
        aside().open('--fail')
    assert error.value.kind == 'aside'
