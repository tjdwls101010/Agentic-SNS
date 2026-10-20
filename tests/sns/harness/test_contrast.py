"""The contrast harness's own contracts (contrast/sns/contrast.py, ledger.py): where a run's state lives, that the
shared links are cut before anything is copied, the variants, task placeholders, and the safety stop."""
import json
import subprocess
import sys
import time

import pytest

from contrast.sns import contrast, ledger


def test_live_state_links_protection_and_session_and_isolates_the_rest(tmp_path):
    real, data = tmp_path / 'real', tmp_path / 'run-data'
    data.mkdir()
    links = contrast.link_shared(data, ['x', 'reddit'], 'u0', real=real)
    assert sorted(str(link.relative_to(data)) for link in links) == [
        'reddit/u0/protection', 'reddit/u0/session', 'x/u0/protection', 'x/u0/session']
    (data / 'x/u0/protection/requests.jsonl').write_text('{}\n')
    assert (real / 'x/u0/protection/requests.jsonl').exists()  # writes reach the real state
    (data / 'handles').mkdir()
    contrast.cut_links(links)
    assert not any(link.exists() or link.is_symlink() for link in links)
    assert (real / 'x/u0/protection/requests.jsonl').exists()  # cutting a link never touches its target


def test_cross_tasks_share_every_platform():
    assert contrast.platforms_of('cross') == list(contrast.PLATFORMS)
    assert contrast.platforms_of('naver-blog') == ['naver_blog']


def test_variants(tmp_path):
    draft = tmp_path / 'SKILL.md'
    draft.write_text('---\nname: sns\n---\n# Title\n\nRun `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" x`.\n\n'
                     '## Keep\n\nk\n\n## Drop me\n\nd\n')
    a = contrast.variant_text('A', '/copy/cli.py', draft)
    assert a.startswith('---') and 'uv run "/copy/cli.py" <platform> <command>' in a
    b = contrast.variant_text('B', '/copy/cli.py', draft)
    assert '"/copy/cli.py"' in b and '${CLAUDE_SKILL_DIR}' not in b
    c = contrast.variant_text('C:Drop', '/copy/cli.py', draft)
    assert '## Keep' in c and '## Drop me' not in c
    with pytest.raises(SystemExit):
        contrast.variant_text('C:Nothing', '/copy/cli.py', draft)


def test_task_placeholders_come_only_from_the_environment(tmp_path, monkeypatch):
    task = tmp_path / 't.txt'
    task.write_text('Read ${SNS_TASK_POST} and say what it is.')
    with pytest.raises(SystemExit):
        contrast.task_text('x', str(task))
    monkeypatch.setenv('SNS_TASK_POST', 'https://x.com/a/status/1')
    assert contrast.task_text('x', str(task)) == 'Read https://x.com/a/status/1 and say what it is.'


def test_request_logs_and_block_signals(tmp_path):
    log = tmp_path / 'x/u0/protection/requests.jsonl'
    log.parent.mkdir(parents=True)
    now = time.time()
    log.write_text('\n'.join(json.dumps(line) for line in [
        {'at': now - 100, 'n': 1, 'outcome': 'sent'}, {'at': now, 'n': 1, 'outcome': 'sent'},
        {'at': now + 1, 'n': 0, 'outcome': 'ok'}, {'at': now + 2, 'n': 0, 'outcome': 'checkpoint'}]) + '\n')
    logs = ledger.request_logs(tmp_path)
    assert logs == [log]
    assert ledger.logged(logs, now - 1) == 1 and ledger.block_signal(logs, now - 1) == 'checkpoint'


def test_watch_stops_the_whole_group_at_a_block_signal(tmp_path):
    log = tmp_path / 'x/u0/protection/requests.jsonl'
    log.parent.mkdir(parents=True)
    started = time.time()
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    seen = []
    log.write_text(json.dumps({'at': started + 0.1, 'n': 0, 'outcome': 'rate_limited'}) + '\n')
    result = ledger.watch(child, logs=lambda: ledger.request_logs(tmp_path), started_at=started, poll=0.05,
                          on_signal=seen.append)
    assert result['outcome'] == 'block_stop' and result['signal'] == 'rate_limited' and seen == ['rate_limited']
    assert child.poll() is not None


def test_the_record_is_written_at_once(tmp_path):
    path = tmp_path / 'record.tsv'
    ledger.add(path, 'P3 recon x', 4, 'notifications')
    assert path.read_text().splitlines()[1].split('\t')[1:] == ['P3 recon x', '4', 'notifications']
