"""aside: reading what one `aside repl` run prints (fixtures/aside_output.json), through the real Aside wrapper."""
import json
import stat
import sys

import pytest

from conftest import fixture
from threads.aside import Aside, parse
from threads.errors import ThreadsError

CASES = [c for c in fixture('aside_output.json')['cases'] if not c.get('timed_out')]



def fake_binary(tmp_path, case):
    script = tmp_path / 'aside'
    script.write_text(f'#!{sys.executable}\nimport sys\nsys.stdout.write({case["stdout"]!r})\n'
                      f'sys.stderr.write({case["stderr"]!r})\nsys.exit({case["exit"]})\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_aside_output(tmp_path, monkeypatch, case):
    monkeypatch.setenv('THREADS_ASIDE_BIN', str(fake_binary(tmp_path, case)))
    if 'value' in case['outcome']:
        assert Aside().evaluate('T1', 'async () => 1', {}) == case['outcome']['value']
        assert parse(case['stdout']) == case['outcome']['value']
        return
    with pytest.raises(ThreadsError) as error:
        Aside().evaluate('T1', 'async () => 1', {})
    assert error.value.code == 3
    kind = case['outcome']['error']
    assert (error.value.reason == 'tab_missing') is (kind == 'tab_missing')
    if kind == 'lost':
        assert 'lost its connection' in error.value.message


def test_the_account_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv('THREADS_ASIDE_ACCOUNT', 'u1')
    assert Aside().account_key == 'u1'
    monkeypatch.delenv('THREADS_ASIDE_ACCOUNT')
    assert Aside().account_key == 'default'
