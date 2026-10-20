"""What X needs of Aside (sns.aside, the core's system): the output cases of fixtures/aside_output.json through the real
wrapper, the opener that opens X's tab without an agent, and a load that answers only from the new document. The
account, the deadline clamp and the protocol itself are core/test_aside.py."""
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


def opener_binary(tmp_path, answer, after=''):
    """A fake `aside repl` that reads the opener from stdin, prints `answer`, and records when stdin closed."""
    script = tmp_path / 'aside'
    log = tmp_path / 'opener.log'
    script.write_text(f"""#!{sys.executable}
import sys, time
line = sys.stdin.readline()
open({str(log)!r}, 'a').write('got:' + ('opener' if 'sns-opener' in line else 'other') + '\\n')
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
    monkeypatch.setenv('SNS_ASIDE_BIN', str(script))
    with aside().opener() as target:
        assert target == 'NEW1'
        assert log.read_text() == 'got:opener\n'  # still held while the caller records and attaches the tab
    assert log.read_text() == 'got:opener\neof\n'


@pytest.mark.parametrize('answer', [json.dumps({'kind': 'opened', 'tabs': ['A', 'B']}),
                                    json.dumps({'kind': 'opened', 'tabs': []})])
def test_an_opener_that_cannot_name_one_tab_is_refused(tmp_path, monkeypatch, answer):
    script, log = opener_binary(tmp_path, answer)
    monkeypatch.setenv('SNS_ASIDE_BIN', str(script))
    with pytest.raises(SnsError) as error:
        with aside().opener():
            pytest.fail('no tab to use')
    assert error.value.kind == 'aside'
    assert log.read_text().endswith('eof\n')  # the held session is ended anyway


def test_an_opener_that_does_not_answer_in_time_is_refused(tmp_path, monkeypatch):
    script, log = opener_binary(tmp_path, 'nothing useful', after='time.sleep(3)')
    monkeypatch.setenv('SNS_ASIDE_BIN', str(script))
    with pytest.raises(SnsError) as error:
        with aside().opener(seconds=1):
            pytest.fail('no tab to use')
    assert error.value.kind == 'aside' and 'in time' in error.value.message


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
