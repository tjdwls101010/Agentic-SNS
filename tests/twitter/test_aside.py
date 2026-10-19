"""aside: reading what one `aside repl` run prints (fixtures/aside_output.json), through the real Aside wrapper."""
import json
import stat
import sys

import pytest

from conftest import fixture
from twitter.aside import Aside, parse
from twitter.errors import TwitterError

CASES = [c for c in fixture('aside_output.json')['cases'] if not c.get('timed_out')]



def fake_binary(tmp_path, case):
    script = tmp_path / 'aside'
    script.write_text(f'#!{sys.executable}\nimport sys\nsys.stdout.write({case["stdout"]!r})\n'
                      f'sys.stderr.write({case["stderr"]!r})\nsys.exit({case["exit"]})\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_aside_output(tmp_path, monkeypatch, case):
    monkeypatch.setenv('TWITTER_ASIDE_BIN', str(fake_binary(tmp_path, case)))
    if 'value' in case['outcome']:
        assert Aside().evaluate('T1', 'async () => 1', {}) == case['outcome']['value']
        assert parse(case['stdout']) == case['outcome']['value']
        return
    with pytest.raises(TwitterError) as error:
        Aside().evaluate('T1', 'async () => 1', {})
    assert error.value.code == 3
    kind = case['outcome']['error']
    assert (error.value.reason == 'tab_missing') is (kind == 'tab_missing')
    if kind == 'lost':
        assert 'lost its connection' in error.value.message


def test_the_account_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv('TWITTER_ASIDE_ACCOUNT', 'u1')
    assert Aside().account_key == 'u1'
    monkeypatch.delenv('TWITTER_ASIDE_ACCOUNT')
    assert Aside().account_key == 'default'


def opener_binary(tmp_path, answer, after=''):
    """A fake `aside repl` that reads the opener from stdin, prints `answer`, and records when stdin closed."""
    script = tmp_path / 'aside'
    log = tmp_path / 'opener.log'
    script.write_text(f"""#!{sys.executable}
import sys, time
line = sys.stdin.readline()
open({str(log)!r}, 'a').write('got:' + ('opener' if 'twitter-opener' in line else 'other') + '\\n')
sys.stdout.write('\\x1b[2maccount: u0\\x1b[0m\\nrepl > ' + {answer!r} + '\\n')
sys.stdout.flush()
{after}
sys.stdin.read()
open({str(log)!r}, 'a').write('eof\\n')
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def test_the_opener_yields_the_one_new_tab_and_ends_its_session_after_the_block(tmp_path, monkeypatch):
    script, log = opener_binary(tmp_path, json.dumps({'kind': 'opened', 'tabs': ['NEW1']}))
    monkeypatch.setenv('TWITTER_ASIDE_BIN', str(script))
    with Aside().opener() as target:
        assert target == 'NEW1'
        assert log.read_text() == 'got:opener\n'  # still held while the caller records and attaches the tab
    assert log.read_text() == 'got:opener\neof\n'


@pytest.mark.parametrize('answer', [json.dumps({'kind': 'opened', 'tabs': ['A', 'B']}),
                                    json.dumps({'kind': 'opened', 'tabs': []})])
def test_an_opener_that_cannot_name_one_tab_is_refused(tmp_path, monkeypatch, answer):
    script, log = opener_binary(tmp_path, answer)
    monkeypatch.setenv('TWITTER_ASIDE_BIN', str(script))
    with pytest.raises(TwitterError) as error:
        with Aside().opener():
            pytest.fail('no tab to use')
    assert error.value.code == 3
    assert log.read_text().endswith('eof\n')  # the held session is ended anyway


def test_an_opener_that_does_not_answer_in_time_is_refused(tmp_path, monkeypatch):
    script, log = opener_binary(tmp_path, 'nothing useful', after='time.sleep(3)')
    monkeypatch.setenv('TWITTER_ASIDE_BIN', str(script))
    with pytest.raises(TwitterError) as error:
        with Aside().opener(seconds=1):
            pytest.fail('no tab to use')
    assert error.value.code == 3 and 'in time' in error.value.message
