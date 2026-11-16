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


def test_a_body_file_gets_the_skills_frontmatter_without_the_local_only_line(tmp_path):
    body = tmp_path / 'F.md'
    body.write_text('# Title\n\nRun `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" x`.\n')
    text = contrast.body_text(body, '/copy/cli.py')
    head, rest = text.split('\n---\n', 1)
    assert head.startswith('---\nname: sns') and 'disable-model-invocation' not in head and 'allowed-tools' in head
    assert '"/copy/cli.py"' in rest and '${CLAUDE_SKILL_DIR}' not in rest
    baseline = contrast.body_text(contrast.HERE / 'arms/A.md', '/copy/cli.py')
    assert 'Run `uv run "/copy/cli.py" <platform> <command>' in baseline


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


def test_a_fake_run_gets_a_launcher_that_runs_the_fake_aside(tmp_path):
    """The fake is a Python file without the executable bit; the run's SNS_ASIDE_BIN must be something the skill can
    execute (found by the first fake rehearsal: PermissionError before the run started)."""
    launcher = contrast.fake_launcher(tmp_path)
    (tmp_path / 'scenario.json').write_text(json.dumps({'tabs': [], 'responses': []}))
    done = subprocess.run([str(launcher), 'account', 'status'], capture_output=True, text=True, timeout=30,
                          env={'SNS_FAKE_SCENARIO': str(tmp_path / 'scenario.json'), 'SNS_FAKE_LOG': str(tmp_path / 'log'),
                               'PATH': '/usr/bin:/bin'})
    assert done.returncode == 0 and 'u0' in done.stdout, done.stderr


def test_a_live_run_takes_the_old_state_in_before_linking_and_meets_its_block(tmp_path, monkeypatch):
    """⑧ (plan P2) A contrast run may be the install's first: a block only the old data/ holds is taken into the real
    state before the run's links are made, so the run's first command meets it and sends nothing."""
    from tests.sns.support.browser import Browser
    old = tmp_path / 'old-data'
    blocks = old / 'reddit' / 'u0' / 'protection'
    blocks.mkdir(parents=True)
    (blocks / 'blocks.json').write_text(json.dumps({'person': {'reason': 'challenge', 'at': time.time() - 60,
                                                               'viewer': None}, 'hold': None}))
    real, data = tmp_path / 'real', tmp_path / 'run-data'
    data.mkdir()
    contrast.take_in_old_state(['reddit'], 'u0', real, legacy=old)
    links = contrast.link_shared(data, ['reddit'], 'u0', real=real)
    browser = Browser(tmp_path / 'browser')
    browser.root.mkdir()
    browser.write()
    env = {k: v for k, v in __import__('os').environ.items()}
    env.update(browser.env(), SNS_DATA_DIR=str(data))
    done = subprocess.run([sys.executable, str(contrast.SKILL / 'scripts/cli.py'), 'reddit', 'sub', 'r/python'],
                          capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 5, done.stdout
    assert [c for c in browser.calls() if c['op'] == 'reddit.fetch'] == []
    assert (real / 'reddit/u0/protection/blocks.json').exists()  # the block now lives in the real state
    contrast.cut_links(links)


def test_an_old_state_that_cannot_be_taken_in_stops_the_run_before_it_starts(tmp_path, monkeypatch):
    old = tmp_path / 'old-data' / 'reddit' / 'u0' / 'protection'
    old.mkdir(parents=True)
    (old / 'blocks.json').write_text('{}')
    real = tmp_path / 'real'
    real.mkdir()
    (real / 'reddit').write_text('a file where a directory must be')
    with pytest.raises(SystemExit) as stopped:
        contrast.take_in_old_state(['reddit'], 'u0', real, legacy=tmp_path / 'old-data')
    assert 'old state' in str(stopped.value)


STUB = r"""#!{python}
import json, os, sys
from pathlib import Path
argv = sys.argv[1:]
Path(os.environ['STUB_LOG']).open('a').write(json.dumps(argv) + '\n')
counter = Path(os.environ['STUB_COUNTER'])
seen = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(seen + 1))
deny = seen < int(os.environ.get('STUB_DENY', '0'))
skill = argv[-1].split('먼저 ')[1].split('/SKILL.md')[0] + '/SKILL.md'
events = [
    {{'type': 'assistant', 'message': {{'content': [{{'type': 'tool_use', 'id': 't1', 'name': 'Read', 'input': {{'file_path': skill}}}}]}}}},
    {{'type': 'user', 'message': {{'content': [{{'type': 'tool_result', 'tool_use_id': 't1', 'content': Path(skill).read_text()}}]}}}},
    {{'type': 'assistant', 'message': {{'content': [{{'type': 'tool_use', 'id': 't2', 'name': 'Bash', 'input': {{'command': 'uv run cli.py x feed'}}}}]}}}},
    {{'type': 'user', 'message': {{'content': [{{'type': 'tool_result', 'tool_use_id': 't2', 'content': 'x feed · 5 shown · requests=1'}}]}}}},
    {{'type': 'result', 'result': 'Five posts were read. As told: only the F arm carries, long enough.',
      'num_turns': 3, 'permission_denials': [{{'tool_name': 'Bash'}}] if deny else []}},
]
if os.environ.get('STUB_NO_RESULT'):
    events = events[:-1]
if os.environ.get('STUB_ERROR'):  # what claude -p ends with when the subscription's usage limit is reached
    events[-1] = {{'type': 'result', 'subtype': 'success', 'is_error': True, 'num_turns': 1, 'permission_denials': [],
                  'result': os.environ['STUB_ERROR']}}
print('\n'.join(json.dumps(e) for e in events))
"""


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """A fake run setup: a stand-in claude, the fake Aside's scenario, and a work directory."""
    stub = tmp_path / 'claude'
    stub.write_text(STUB.format(python=sys.executable))
    stub.chmod(0o755)
    scenario = tmp_path / 'scenario.json'
    scenario.write_text(json.dumps({'tabs': [], 'responses': []}))
    body = tmp_path / 'F-candidate.md'
    body.write_text('# Social networks\n\nRun `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <platform>` on one line.\n\n'
                    'A candidate fact that only the F arm carries, long enough to be recognised in a transcript.\n')
    monkeypatch.setenv('SNS_WORK', str(tmp_path / 'work'))
    monkeypatch.setenv('CONTRAST_CLAUDE', str(stub))
    monkeypatch.setenv('STUB_LOG', str(tmp_path / 'stub.log'))
    monkeypatch.setenv('STUB_COUNTER', str(tmp_path / 'stub.count'))
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT', 'u0')
    return {'scenario': scenario, 'body': body, 'work': tmp_path / 'work', 'log': tmp_path / 'stub.log'}


def cells(work):
    return [json.loads(line) for line in (work / 'cells.jsonl').read_text().splitlines()]


def test_a_fake_rehearsal_runs_any_body_with_any_model_id_and_repeats(harness):
    contrast.main(['reh', 'x', 'rehearsal', '--body', str(harness['body']), '--arm', 'F', '--model', 'some-model-9',
                   '--repeat', '3', '--fake', str(harness['scenario'])])
    lines = cells(harness['work'])
    assert [(c['run'], c['repetition'], c['valid']) for c in lines] == [('reh-r1', 1, True), ('reh-r2', 2, True),
                                                                         ('reh-r3', 3, True)]
    assert all(c['arm'] == 'F' and c['model'] == 'some-model-9' and c['task_name'] == 'rehearsal' for c in lines)
    calls = [json.loads(line) for line in harness['log'].read_text().splitlines()]
    assert all(argv[argv.index('--model') + 1] == 'some-model-9' for argv in calls)
    assert all(any(a.startswith('Read(//') for a in argv) for argv in calls)  # the run may read its own files


def test_a_run_with_a_permission_denial_is_invalid_and_run_again_at_most_twice(harness, monkeypatch):
    monkeypatch.setenv('STUB_DENY', '1')
    contrast.main(['deny', 'x', 'rehearsal', '--body', str(harness['body']), '--arm', 'F', '--repeat', '1',
                   '--fake', str(harness['scenario'])])
    assert [(c['run'], c['valid']) for c in cells(harness['work'])] == [('deny-r1', False), ('deny-r1-a1', True)]
    (harness['work'] / 'cells.jsonl').unlink()
    monkeypatch.setenv('STUB_DENY', '99')
    contrast.main(['always', 'x', 'rehearsal', '--body', str(harness['body']), '--arm', 'F', '--repeat', '1',
                   '--fake', str(harness['scenario'])])
    assert [(c['run'], c['valid']) for c in cells(harness['work'])] == [
        ('always-r1', False), ('always-r1-a1', False), ('always-r1-a2', False)]


def test_a_blind_copy_carries_neither_run_arm_model_nor_body(harness, tmp_path):
    from contrast.sns import blind
    contrast.main(['blindme', 'x', 'rehearsal', '--body', str(harness['body']), '--arm', 'F-secret',
                   '--model', 'model-xyz', '--repeat', '1', '--fake', str(harness['scenario'])])
    harness['body'].write_text('moved and edited after the run')  # the copy uses the body the run was given
    out, key_file = tmp_path / 'graders' / 'round1', tmp_path / 'keys' / 'round1.json'
    with pytest.raises(SystemExit):
        blind.main([str(out), str(out / 'key.json'), str(harness['work'] / 'runs' / 'blindme-r1')])
    with pytest.raises(SystemExit):
        blind.main([str(contrast.REPO / 'blind-out'), str(key_file), 'blindme-r1'])
    blind.main([str(out), str(key_file), str(harness['work'] / 'runs' / 'blindme-r1')])
    copies = list(out.glob('*'))
    assert len(copies) == 1 and copies[0].suffix == '.md'
    text = copies[0].read_text()
    assert 'Five posts were read.' in text and 'x feed · 5 shown' in text and '# Task' in text
    for hidden in ('blindme', 'F-secret', 'model-xyz', 'A candidate fact that only the F arm carries',
                   'only the F arm carries, long enough', 'sns-contrast-', 'on one line'):
        assert hidden not in text, hidden
    assert list(json.loads(key_file.read_text()).values()) == ['blindme-r1']


def test_a_run_without_a_final_answer_is_invalid_and_not_repeated(harness, monkeypatch):
    monkeypatch.setenv('STUB_NO_RESULT', '1')
    contrast.main(['cut', 'x', 'rehearsal', '--body', str(harness['body']), '--arm', 'F', '--repeat', '1',
                   '--fake', str(harness['scenario'])])
    assert [(c['run'], c['valid']) for c in cells(harness['work'])] == [('cut-r1', False)]


def test_a_run_that_ended_in_an_error_is_invalid_and_stops_its_cell(harness, monkeypatch, capsys):
    """A usage limit (or any API error) ends claude -p with an error result: its text is not an answer, and the
    repetitions after it would meet the same limit, so the cell stops and says why (A13: discard and wait)."""
    monkeypatch.setenv('STUB_ERROR', "You've hit your limit · resets 8pm")
    contrast.main(['lim', 'x', 'rehearsal', '--body', str(harness['body']), '--arm', 'F', '--repeat', '3',
                   '--fake', str(harness['scenario'])])
    assert [(c['run'], c['valid']) for c in cells(harness['work'])] == [('lim-r1', False)]
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert printed[-1]['error'] == "You've hit your limit · resets 8pm" and printed[-1]['valid'] is False
    summary = json.loads((harness['work'] / 'runs' / 'lim-r1' / 'summary.json').read_text())
    assert summary['final'] is None


def test_work_inside_the_repository_is_refused(monkeypatch):
    monkeypatch.setenv('SNS_WORK', str(contrast.REPO / 'runs-here'))
    with pytest.raises(SystemExit):
        contrast.work_dir()


def test_aggregation_counts_defects_over_valid_runs_per_model_arm_and_row(tmp_path, monkeypatch):
    from contrast.sns import aggregate
    monkeypatch.setattr(aggregate, 'HERE', tmp_path)
    cell = lambda run, arm, model, valid=True, task='t1', signal=None: {  # noqa: E731
        'run': run, 'arm': arm, 'model': model, 'valid': valid, 'task_name': task, 'block_signal': signal}
    runs = [cell(f'a{i}', 'A', 'opus') for i in range(1, 5)] + [cell(f'f{i}', 'F', 'opus') for i in range(1, 4)] + [
        cell('a9', 'A', 'opus', valid=False), cell('ab', 'A', 'opus', signal='checkpoint'),
        cell('s1', 'A', 'sonnet', task='other'), cell('t1', 'A', 'opus', task='t2')]
    (tmp_path / 'cells.jsonl').write_text('\n'.join(json.dumps(c) for c in runs) + '\n')
    both = lambda run, verdict: [{'run': run, 'row': 1, 'verdict': verdict, 'grader': g}  # noqa: E731
                                 for g in ('codex', 'claude')]
    grades = both('a1', 'defect') + both('a2', 'ok') + both('a3', 'defect') + both('f1', 'ok') + both('f2', 'ok') \
        + both('f3', 'defect') + both('a9', 'defect') + both('ab', 'ok') + both('s1', 'defect') + both('t1', 'defect') \
        + [{'run': 'a4', 'row': 1, 'verdict': 'ok', 'grader': 'codex'},       # one grader only: not counted
           {'run': 'a4', 'row': 2, 'verdict': 'ok', 'grader': 'codex'},
           {'run': 'a4', 'row': 2, 'verdict': 'defect', 'grader': 'claude'}]  # split: not counted until settled
    (tmp_path / 'grades.jsonl').write_text('\n'.join(json.dumps(g) for g in grades) + '\n')
    aggregate.main(['pilot', str(tmp_path / 'grades.jsonl'), '--cells', str(tmp_path / 'cells.jsonl'),
                    '--tasks', 't1', 't2'])
    text = (tmp_path / 'results' / 'pilot.md').read_text()
    assert '| 1 | opus | 2/3 | 1/3 |' in text  # the invalid and the block-stopped runs never count
    assert 'Unsettled grader disagreements: 2.' in text and 'sonnet' not in text
    assert 'Left out for too few valid runs: 1.' in text and 'opus, A, t2' in text and 'sonnet' not in text


def test_a_task_whose_runs_were_all_invalid_or_not_applicable_is_handled_by_its_runs(tmp_path, monkeypatch):
    from contrast.sns import aggregate
    cells = [{'run': f'r{i}', 'arm': 'A', 'model': 'opus', 'valid': i < 3, 'task_name': 't', 'block_signal': None}
             for i in range(5)] + [{'run': 'x', 'arm': 'A', 'model': 'opus', 'valid': False, 'task_name': 'dead'}]
    decided = {('r0', '1'): 'ok', ('r1', '1'): 'ok', ('r2', '1'): 'n.a.'}
    counts, short = aggregate.table(decided, cells)
    assert counts == {'1': {'opus': {'A': {'defects': 0, 'valid': 2}}}}  # three valid runs; n.a. is not a run of row 1
    assert short == [('opus', 'A', 'dead')]


def test_a_probe_set_names_tasks_with_their_platform(tmp_path, monkeypatch):
    """Task files are named per platform (x/t3 and facebook/t3 are different tasks): probes.md lists them as
    platform/task, and only that task counts."""
    from contrast.sns import aggregate
    monkeypatch.setattr(aggregate, 'HERE', tmp_path)
    cells = [{'run': f'{p}{i}', 'arm': 'A', 'model': 'sonnet', 'valid': True, 'task_name': 't3', 'platform': p,
              'block_signal': None} for p in ('x', 'facebook') for i in range(3)]
    (tmp_path / 'cells.jsonl').write_text('\n'.join(json.dumps(c) for c in cells) + '\n')
    grades = [{'run': c['run'], 'row': 1, 'verdict': 'defect' if c['platform'] == 'facebook' else 'ok',
               'grader': 'sonnet'} for c in cells]
    (tmp_path / 'grades.jsonl').write_text('\n'.join(json.dumps(g) for g in grades) + '\n')
    aggregate.main(['probe', str(tmp_path / 'grades.jsonl'), '--cells', str(tmp_path / 'cells.jsonl'),
                    '--graders', 'sonnet', '--tasks', 'x/t3'])
    assert '| 1 | sonnet | 0/3 |' in (tmp_path / 'results' / 'probe.md').read_text()


def test_blinding_keeps_what_every_arm_shares_and_sees_through_grep_prefixes():
    from contrast.sns import blind
    body = (contrast.HERE / 'arms/A.md').read_text() + '\nA claim only this arm makes about the reader of posts.\n'
    shared = 'the permission rule matches the whole command line, so a'
    assert blind.strip_body(shared, body) == shared
    grep = 'SKILL.md:7:A claim only this arm makes about the reader of posts.'
    assert 'only this arm makes' not in blind.strip_body(grep, body)


def test_grading_tasks_and_collected_verdicts_feed_aggregate(tmp_path):
    """grade.py (A18): one Sonnet worker task per blinded copy, labelled with its id; the workers' JSON answers become
    the {id, row, verdict, grader} lines aggregate.py counts; an answer that is not grader.md's object is named, never
    guessed."""
    from contrast.sns import grade
    copies = tmp_path / 'copies'
    copies.mkdir()
    for name in ('aaaa1111', 'bbbb2222'):
        (copies / f'{name}.md').write_text('# Task\n')
    lines = [json.loads(line) for line in grade.tasks(copies)]
    assert [line['label'] for line in lines] == ['g-aaaa1111', 'g-bbbb2222']
    assert str(copies / 'aaaa1111.md') in lines[0]['prompt'] and 'grader.md' in lines[0]['prompt']
    answer = {'rows': {str(n): {'verdict': 'defect' if n == 6 else 'n.a.' if n in (7, 8) else 'ok', 'evidence': 'e'}
                       for n in range(1, 9)}, 'misread': [], 'tool': []}
    printed = ('{"group": "g", "members": []}\n'
               '--- [1:g-aaaa1111] run=r1 state=completed bytes=10\n' + json.dumps(answer) + '\n'
               '--- [2:g-bbbb2222] run=r2 state=completed bytes=10\n' + 'I could not finish.\n')
    found, missing = grade.collect(printed, 'sonnet')
    assert missing == ['bbbb2222'] and len(found) == 8
    # the print saved by a background shell ends with its own trailer after the last answer
    found, missing = grade.collect('--- [1:g-aaaa1111] run=r1\n' + json.dumps(answer) + '\n\n[exited with code 0]\n',
                                   'sonnet')
    assert missing == [] and len(found) == 8
    assert {'id': 'aaaa1111', 'row': '6', 'verdict': 'defect', 'grader': 'sonnet'} in found
    assert {line['verdict'] for line in found if line['row'] in ('7', '8')} == {'n.a.'}
    schema = json.loads((grade.HERE / 'grader.schema.json').read_text())
    assert set(schema['properties']['rows']['required']) == set(answer['rows'])
