"""The live guard refuses before sending: a capped ledger or a full window never reaches the real Aside."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

GUARD = Path(__file__).with_name('live') / 'guard_aside.py'
CODE = 'const ARGS = {};\n// twitter-snippet: graphql\n'


def fake_aside(tmp_path):
    """A stand-in real Aside that records each invocation and answers with an empty envelope."""
    sent = tmp_path / 'sent.log'
    binary = tmp_path / 'aside'
    binary.write_text(f'#!{sys.executable}\nimport sys\nopen({str(sent)!r}, "a").write("sent\\n")\nprint("{{}}")\n')
    binary.chmod(0o700)
    return binary, sent


def guard(tmp_path, ledger, **caps):
    binary, sent = fake_aside(tmp_path)
    env = {**os.environ, 'TWITTER_LIVE_LEDGER': str(ledger), 'TWITTER_REAL_ASIDE': str(binary), **caps}
    return subprocess.run([sys.executable, str(GUARD), '--account', 'u0', 'repl', CODE], capture_output=True, text=True, env=env)


def sent(tmp_path):
    log = tmp_path / 'sent.log'
    return len(log.read_text().splitlines()) if log.exists() else 0


def test_attempts_under_the_caps_are_forwarded_and_counted(tmp_path):
    ledger = tmp_path / 'ledger.json'
    for _ in range(2):
        assert guard(tmp_path, ledger, TWITTER_LIVE_TOTAL='5').returncode == 0
    data = json.loads(ledger.read_text())
    assert sent(tmp_path) == 2 and data['total'] == 2 and data['kinds'] == {'graphql': 2}


def test_total_cap_refuses_without_sending(tmp_path):
    ledger = tmp_path / 'ledger.json'
    ledger.write_text(json.dumps({'total': 3, 'times': [], 'kinds': {}}))
    done = guard(tmp_path, ledger, TWITTER_LIVE_TOTAL='3')
    assert done.returncode != 0 and 'allowance exhausted' in done.stderr and sent(tmp_path) == 0
    assert json.loads(ledger.read_text())['total'] == 3


def test_full_window_refuses_without_sending(tmp_path):
    ledger = tmp_path / 'ledger.json'
    ledger.write_text(json.dumps({'total': 2, 'times': [time.time() - 5, time.time() - 1], 'kinds': {}}))
    done = guard(tmp_path, ledger, TWITTER_LIVE_WINDOW='2/600')
    assert done.returncode != 0 and 'window is full' in done.stderr and sent(tmp_path) == 0


def test_attempts_older_than_the_window_do_not_count_against_it(tmp_path):
    ledger = tmp_path / 'ledger.json'
    ledger.write_text(json.dumps({'total': 2, 'times': [time.time() - 700, time.time() - 650], 'kinds': {}}))
    assert guard(tmp_path, ledger, TWITTER_LIVE_WINDOW='2/600').returncode == 0 and sent(tmp_path) == 1


def test_a_per_kind_ledger_from_the_earlier_guard_counts_toward_the_total(tmp_path):
    ledger = tmp_path / 'ledger.json'
    ledger.write_text(json.dumps({'graphql': 18, 'auxiliary': 3}))
    done = guard(tmp_path, ledger, TWITTER_LIVE_TOTAL='21')
    assert done.returncode != 0 and sent(tmp_path) == 0


def test_concurrent_attempts_never_exceed_the_cap(tmp_path):
    ledger = tmp_path / 'ledger.json'
    binary, _ = fake_aside(tmp_path)
    env = {**os.environ, 'TWITTER_LIVE_LEDGER': str(ledger), 'TWITTER_REAL_ASIDE': str(binary), 'TWITTER_LIVE_TOTAL': '3'}
    runs = [subprocess.Popen([sys.executable, str(GUARD), CODE], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(6)]
    codes = [run.wait() for run in runs]
    assert codes.count(0) == 3 and sent(tmp_path) == 3
