"""What X needs of Aside (sns.aside, the core's system): the output cases of fixtures/aside_output.json through the real
wrapper and a load that answers only from the new document. Opening X's tab is x/test_cli_doctor.py's; the account,
the deadline clamp and the protocol itself are core/test_aside.py."""
import json
import shutil
import stat
import sys

import pytest

from sns.aside import Aside, parse
from sns.clock import Deadline
from sns.errors import SnsError
from tests.sns.x.data import fixture

CASES = fixture('aside_output.json')['cases']


@pytest.fixture(autouse=True)
def _account(monkeypatch, data_dir):
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT', 'u0')  # no `aside account status` in these tests


def aside(seconds=30):
    return Aside('x', Deadline(seconds))


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


def node_binary(tmp_path):
    """A fake `aside repl <program>` that runs the skill's real browser program under Node against a fake tab: after
    location.replace the old document keeps answering for a few calls before the new one (a new timeOrigin) exists."""
    prelude = tmp_path / 'prelude.mjs'
    prelude.write_text("""import vm from 'node:vm';
let doc = 1, origin = 1000, href = 'https://x.com/i/xskill', pending = 0, next = null;
const page = () => ({DOC: doc, location: {href, replace: (url) => { next = url; pending = 4; }},
                     performance: {timeOrigin: origin}});
globalThis.listBrowserTabs = async () => [{targetId: 'T1', url: href}];
globalThis.attachBrowserTab = async (id) => id !== 'T1' ? null : {
  evaluate: async (fn, arg) => {
    if (pending > 0 && --pending === 0) { doc += 1; origin += 500; href = next; }
    return vm.runInNewContext('(' + fn.toString() + ')', page())(arg);
  },
};
""")
    script = tmp_path / 'aside'
    script.write_text(f"""#!{sys.executable}
import subprocess, sys
program = open({str(prelude)!r}).read() + sys.argv[-1]
path = {str(tmp_path / 'program.mjs')!r}
open(path, 'w').write(program)
done = subprocess.run(['node', path], capture_output=True, text=True)
sys.stdout.write(done.stdout); sys.stderr.write(done.stderr); sys.exit(done.returncode)
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_a_load_answers_only_from_the_new_document(tmp_path, monkeypatch):
    """The old x.com document is still there for a moment after location.replace; a page function run in it would
    install nothing new and report the old load (P3 review 2)."""
    monkeypatch.setenv('SNS_ASIDE_BIN', str(node_binary(tmp_path)))
    answer = aside().load('T1', 'https://x.com/i/xskill?again', '() => ({doc: DOC, href: location.href})', {}, 20)
    assert answer == {'doc': 2, 'href': 'https://x.com/i/xskill?again'}
