"""Contrast runs for the threads skill (plan appendix C): one task, one SKILL.md variant, a clean Claude that may run
only this skill's CLI, inside the OS sandbox, watched against the day's request target.

  python3 contrast.py RUN VARIANT TASK [--fake SCENARIO] [--data-template DIR]

VARIANT: A (CLI only: the invocation line), B (the draft), C:<heading> (the draft without the section whose heading
starts with <heading>). TASK is a file under tasks/ (or a path); ${NAME} in it is filled from the environment, so real
accounts and post URLs never live in the repository. --fake runs against tests/threads/fake_aside.py with SCENARIO and
a throwaway data directory (copied from --data-template when given, e.g. one holding a recorded block); nothing then
reaches the real browser. Without --fake the run shares the skill's real data/ (one protection state, one tab).

Outputs go to $THREADS_WORK/runs/<RUN>/ (outside the repository: they hold other people's posts): skill/, settings.json,
events.jsonl, summary.json. A live run's requests are written to $THREADS_WORK/budget-ledger.tsv as soon as it ends.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import ledger

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILL = REPO / '.claude/skills/threads'
DATA = SKILL / 'data'
WORK = Path(os.environ.get('THREADS_WORK', Path.home() / '.claude/projects/-Users-seongjin-Coding-Agentic-SNS/threads-rebuild'))
LEDGER = WORK / 'budget-ledger.tsv'
DRAFT = WORK / 'drafts/SKILL.md'
MODEL = 'claude-opus-5-5'
DAY_TARGET = ledger.DAY_TARGET


def variant_text(variant, cli):
    head = (SKILL / 'SKILL.md').read_text().split('\n---\n', 1)[0] + '\n---\n'
    if variant == 'A':
        return head + ('\n# Threads through the person\'s own browser\n\n'
                       f'Run `uv run "{cli}" <command> …` on one line. `--help` gives the commands and their '
                       'arguments, `schema` what results, files and fields mean, and each error\'s `fix` how to '
                       'recover.\n')
    draft = DRAFT.read_text().replace('${CLAUDE_SKILL_DIR}/scripts/cli.py', cli)
    if variant == 'B':
        return draft
    heading = variant.split(':', 1)[1]
    parts = re.split(r'(?m)^(?=## )', draft)
    kept = [p for p in parts if not p.startswith('## ' + heading)]
    if len(kept) == len(parts):
        sys.exit(f'no section starting with "## {heading}"')
    return ''.join(kept)


def task_text(name):
    path = Path(name) if Path(name).exists() else HERE / 'tasks' / (name if name.endswith('.txt') else name + '.txt')
    text = path.read_text().strip()
    missing = sorted({m for m in re.findall(r'\$\{([A-Z0-9_]+)\}', text) if m not in os.environ})
    if missing:
        sys.exit('set ' + ', '.join(missing) + ' for this task')
    return re.sub(r'\$\{([A-Z0-9_]+)\}', lambda m: os.environ[m.group(1)], text)


def sandbox_settings(root, data_dir):
    """The OS sandbox the child's shell runs in: writes only to the run directory and the skill data, no escape."""
    return {'sandbox': {'enabled': True, 'failIfUnavailable': True, 'allowUnsandboxedCommands': False,
                        'autoAllowBashIfSandboxed': False,
                        'filesystem': {'allowWrite': [str(root), str(data_dir), str(Path.home() / '.cache/uv')]},
                        # 성진: Aside's daemon endpoint is confirmed in the P6 rehearsal; widen only what it shows.
                        'network': {'allowLocalBinding': True, 'allowAllUnixSockets': True}}}


def blank_tab(data_dir):
    """Navigate the skill's recorded dedicated tab to about:blank (no request), so its background polling stops."""
    # 성진: wired to the skill's session/aside unit interfaces once P3 defines them; until then a budget stop leaves
    # the tab open and says so.
    raise NotImplementedError('blank the dedicated tab by hand: the skill\'s tab interface is not built yet')


def _try(function, *args):
    try:
        function(*args)
        return 'blanked'
    except Exception as error:  # noqa: BLE001 — the run summary must still be written
        return f'not blanked: {error}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('variant')
    parser.add_argument('task')
    parser.add_argument('--fake')
    parser.add_argument('--data-template')
    args = parser.parse_args()
    root = WORK / 'runs' / args.run
    if root.exists():
        sys.exit(f'{root} exists; pick a new run name')
    task = task_text(args.task)
    if not args.fake:
        fits = ledger.check(LEDGER, 'tab_open', stage='P6')
        if not fits['ok']:
            sys.exit(f'today\'s ledger leaves {fits["left_day"]}; a run reserves at least {fits["reservation"]}')
    copy = root / 'skill'
    shutil.copytree(SKILL / 'scripts', copy / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    cli = str(copy / 'scripts/cli.py')
    (copy / 'SKILL.md').write_text(variant_text(args.variant, cli))
    env = {k: v for k, v in os.environ.items() if not k.startswith('THREADS_')}
    if args.fake:
        data_dir = Path(tempfile.mkdtemp(dir=root, prefix='data-'))
        if args.data_template:
            shutil.copytree(args.data_template, data_dir, dirs_exist_ok=True)
        env.update(THREADS_ASIDE_BIN=str(REPO / 'tests/threads/fake_aside.py'), THREADS_FAKE_SCENARIO=args.fake,
                   THREADS_FAKE_LOG=str(root / 'fake-log.jsonl'))
    else:
        data_dir = DATA   # the one authoritative protection state and tab, shared with every other use
    env['THREADS_DATA_DIR'] = str(data_dir)
    settings = root / 'settings.json'
    settings.write_text(json.dumps(sandbox_settings(root, data_dir), indent=1))
    prompt = (f'먼저 {copy}/SKILL.md를 읽고 따르세요. {copy}/scripts 아래 파일은 읽지 말고, 도구는 --help와 schema 명령, '
              f'그리고 출력으로 익히세요.\n\n과제: {task}')
    command = ['claude', '-p', '--safe-mode', '--restricted', '--no-session-persistence', '--settings', str(settings),
               '--tools', 'Bash,Read,Grep,Glob', '--allowedTools', f'Bash(uv run "{cli}" *)',
               '--model', MODEL, '--output-format', 'stream-json', '--verbose', prompt]
    started, blanked = time.time(), []
    with (root / 'events.jsonl').open('w') as events, (root / 'stderr.txt').open('w') as errors:
        child = subprocess.Popen(command, cwd=root, env=env, stdout=events, stderr=errors, start_new_session=True)
        if args.fake:
            child.wait(timeout=3600)
            watched = {'outcome': 'finished', 'counted': 0}
        else:
            watched = ledger.watch(child, ledger=LEDGER, log=data_dir / 'protection/requests.jsonl',
                                   started_at=started, limit=DAY_TARGET, on_stop=lambda: blanked.append(_try(blank_tab, data_dir)))
    summary = summarize(root / 'events.jsonl')
    logged = 0 if args.fake else ledger.logged(data_dir / 'protection/requests.jsonl', started)
    summary.update(run=args.run, variant=args.variant, task=task, exit=child.returncode, fake=bool(args.fake),
                   watch=watched['outcome'], logged_requests=logged, tab_blanked=blanked,
                   stderr=(root / 'stderr.txt').read_text()[-2000:])
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    if not args.fake:
        ledger.add(LEDGER, f'P6 contrast {args.run}', max(logged, summary['requests']),
                   f'{args.variant}' + (' — stopped by budget' if watched['outcome'] == 'budget_stop' else ''))
    print(json.dumps({k: summary[k] for k in ('run', 'variant', 'exit', 'watch', 'turns', 'requests',
                                              'logged_requests', 'permission_denials')}, ensure_ascii=False))


def summarize(path):
    """Commands the child ran with the head of each output, its final answer, denials, and the requests its outputs
    reported (requests=N/M plus a tab opening)."""
    commands, outputs, denials, final, turns, requests = [], {}, [], None, 0, 0
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'assistant':
            for block in event.get('message', {}).get('content', []):
                if block.get('type') == 'tool_use':
                    commands.append({'id': block['id'], 'tool': block['name'],
                                     'input': block['input'].get('command') or block['input'].get('file_path')
                                     or json.dumps(block['input'])[:200]})
        elif event.get('type') == 'user':
            for block in event.get('message', {}).get('content', []):
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    content = block.get('content')
                    text = content if isinstance(content, str) else ''.join(
                        c.get('text', '') for c in content or [] if isinstance(c, dict))
                    outputs[block.get('tool_use_id')] = text
        elif event.get('type') == 'result':
            final, turns, denials = event.get('result'), event.get('num_turns', 0), event.get('permission_denials', [])
    for command in commands:
        text = outputs.get(command['id'], '')
        command['output_head'] = text[:400]
        match = re.search(r'requests=(\d+)/\d+(?: · tab opened \(\+(\d+) requests\))?', text)
        if match:
            requests += int(match.group(1)) + int(match.group(2) or 0)
    return {'commands': commands, 'final': final, 'turns': turns, 'permission_denials': denials, 'requests': requests}


if __name__ == '__main__':
    main()
