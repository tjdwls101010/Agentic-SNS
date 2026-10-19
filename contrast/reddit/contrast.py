"""Contrast runs for the reddit skill (plan appendix C): one task, one SKILL.md variant, a clean Claude that may run
only this skill's CLI, watched for Reddit's block signals.

  python3 contrast.py RUN VARIANT TASK [--fake SCENARIO] [--data-template DIR]

VARIANT: A (CLI only: the invocation line), B (the draft), C:<heading> (the draft without the section whose heading
starts with <heading>). A --fake run's shell is held by the OS sandbox; a live run only by the permission rules (aside
cannot sign its daemon challenge inside the sandbox). TASK is a file under tasks/ (or a path); ${NAME} in it is filled
from the environment, so real communities, people and post URLs never live in the repository. --fake runs against
tests/reddit/fake_aside.py with SCENARIO and a throwaway data directory (copied from --data-template when given, e.g.
one holding a recorded block); nothing then reaches the real browser.

A live run gets its own empty data directory (no handles or snapshots another run left, so one condition never reads
another's cache) whose protection/ links to the skill's real data/protection: one lock, one set of bucket states, one
block record and one request log across every run and every restart of this harness. Before a live run starts, the
shared protection state is read: a recorded block refuses the run, and a spent bucket is waited out until its reset.

Outputs go to $REDDIT_WORK/runs/<RUN>/ (outside the repository: they hold other people's posts): work/, settings.json,
events.jsonl, summary.json. A live run's requests are written to $REDDIT_WORK/budget-ledger.tsv as soon as it ends.
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
SKILL = REPO / '.claude/skills/reddit'
DATA = SKILL / 'data'
PROTECTION = DATA / 'protection'


def _project_dir():
    """Claude Code's folder for the main checkout of this repository (a worktree shares it)."""
    common = subprocess.run(['git', '-C', str(HERE), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            capture_output=True, text=True).stdout.strip()
    main = Path(common).parent if common else REPO
    return Path.home() / '.claude/projects' / re.sub(r'[^A-Za-z0-9]', '-', str(main))


WORK = Path(os.environ.get('REDDIT_WORK') or _project_dir() / 'reddit-rebuild')
LEDGER = WORK / 'budget-ledger.tsv'
DRAFT = WORK / 'drafts/SKILL.md'
MODEL = 'claude-opus-5-5'
# 성진: 버킷이 바닥났을 때 리셋까지 기다리는 최대 시간 — Reddit 창이 10분이라 그보다 길게 기다릴 일은 없다
MAX_WAIT_SECONDS = 660


def variant_text(variant, cli):
    head = (SKILL / 'SKILL.md').read_text().split('\n---\n', 1)[0] + '\n---\n'
    if variant == 'A':
        return head + ('\n# Reddit through the user\'s own browser\n\n'
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


def shared_state():
    """What the skill's guard reports for every account key under the real protection directory."""
    sys.path.insert(0, str(SKILL / 'scripts'))   # maintenance code reads the skill through its unit interface
    from reddit import guard
    return {path.name: guard.status(path) for path in sorted(PROTECTION.iterdir()) if path.is_dir()} \
        if PROTECTION.exists() else {}


def wait_for_buckets():
    """Refuse a live run over a recorded block; wait a spent bucket out until its reset (at most MAX_WAIT_SECONDS)."""
    for key, state in shared_state().items():
        if state['blocked']:
            sys.exit(f'account {key} is blocked ({state["block_reason"]}); a person must check Reddit first')
    deadline = time.time() + MAX_WAIT_SECONDS
    while True:
        waits = [bucket['wait_seconds'] for state in shared_state().values() for bucket in state['buckets'].values()
                 if bucket['wait_seconds'] > 0]
        if not waits:
            return
        if time.time() + max(waits) > deadline:
            sys.exit(f'a bucket stays closed for {max(waits):.0f} s more; start the run later')
        print(f'waiting {max(waits):.0f} s for a bucket to reset', file=sys.stderr)
        time.sleep(max(waits) + 1)


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
        wait_for_buckets()
    root.mkdir(parents=True)
    # The child's sandbox cannot write under ~/.claude whatever allowWrite says, so everything it writes (its cwd, the
    # skill copy, its data and a fake run's scenario) lives in a temporary workspace, copied into the run directory after.
    scratch = Path(tempfile.mkdtemp(prefix=f'reddit-contrast-{args.run}-'))
    copy = scratch / 'skill'
    shutil.copytree(SKILL / 'scripts', copy / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    if (SKILL / 'references').exists():
        shutil.copytree(SKILL / 'references', copy / 'references')
    cli = str(copy / 'scripts/cli.py')
    (copy / 'SKILL.md').write_text(variant_text(args.variant, cli))
    # REDDIT_ASIDE_ACCOUNT stays: it picks the browser profile, and with it the protection state the run shares
    env = {k: v for k, v in os.environ.items() if not k.startswith('REDDIT_') or k == 'REDDIT_ASIDE_ACCOUNT'}
    data_dir = scratch / 'data'
    data_dir.mkdir()
    if args.fake:
        if args.data_template:
            shutil.copytree(args.data_template, data_dir, dirs_exist_ok=True)
        shutil.copy(args.fake, scratch / 'scenario.json')  # the fake marks responses used: never the original
        env.update(REDDIT_ASIDE_BIN=str(REPO / 'tests/reddit/fake_aside.py'),
                   REDDIT_FAKE_SCENARIO=str(scratch / 'scenario.json'), REDDIT_FAKE_LOG=str(scratch / 'fake-log.jsonl'))
        protection = data_dir / 'protection'
    else:
        PROTECTION.mkdir(parents=True, exist_ok=True, mode=0o700)
        (data_dir / 'protection').symlink_to(PROTECTION, target_is_directory=True)
        protection = PROTECTION
    env['REDDIT_DATA_DIR'] = str(data_dir)
    settings = root / 'settings.json'
    settings.write_text(json.dumps(sandbox_settings(scratch, data_dir), indent=1))
    prompt = (f'먼저 {copy}/SKILL.md를 읽고 따르세요. {copy}/scripts 아래 파일은 읽지 말고, 도구는 --help와 schema 명령, '
              f'그리고 출력으로 익히세요.\n\n과제: {task}')
    # 성진(T18): a live run has no OS sandbox — inside it aside cannot sign its daemon challenge with the keychain key;
    # only the permission rules hold it (the skill's CLI is the one command it may run), and summary lists its --out files
    sandbox = ['--settings', str(settings)] if args.fake else []
    command = ['claude', '-p', '--safe-mode', '--restricted', '--no-session-persistence', *sandbox,
               '--tools', 'Bash,Read,Grep,Glob', '--allowedTools', f'Bash(uv run "{cli}" *)',
               '--model', MODEL, '--output-format', 'stream-json', '--verbose', prompt]
    started = time.time()
    with (root / 'events.jsonl').open('w') as events, (root / 'stderr.txt').open('w') as errors:
        child = subprocess.Popen(command, cwd=scratch, env=env, stdout=events, stderr=errors, start_new_session=True)
        watched = ledger.watch(child, logs=lambda: ledger.request_logs(protection), started_at=started)
    if not args.fake:
        (data_dir / 'protection').unlink()   # never copy the shared protection state into the run directory
    shutil.copytree(scratch, root / 'work', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.rmtree(scratch, ignore_errors=True)
    summary = summarize(root / 'events.jsonl')
    logged = watched['counted']
    summary['out_files'] = sorted({m for c in summary['commands'] if c['tool'] == 'Bash'
                                   for m in re.findall(r'--out[= ](\S+)', c['input'])})
    summary.update(run=args.run, variant=args.variant, task=task, exit=child.returncode, fake=bool(args.fake),
                   watch=watched['outcome'], block_signal=watched['signal'], logged_requests=logged,
                   stderr=(root / 'stderr.txt').read_text()[-2000:])
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    if not args.fake:
        ledger.add(LEDGER, f'P6 contrast {args.run}', max(logged, summary['requests']),
                   f'{args.variant}' + (f' — stopped at {watched["signal"]}' if watched['signal'] else ''))
    print(json.dumps({k: summary[k] for k in ('run', 'variant', 'exit', 'watch', 'block_signal', 'turns', 'requests',
                                              'logged_requests', 'permission_denials')}, ensure_ascii=False))


def summarize(path):
    """Commands the child ran with the head of each output, its final answer, denials, and the requests its outputs
    reported (requests=N/M)."""
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
        if command['tool'] != 'Bash':
            continue  # a Read of a saved output repeats its first line; only the call that ran made requests
        match = re.search(r'requests=(\d+)/\d+', text) or re.search(r'"request_count":\s*(\d+)', text)
        if match:
            requests += int(match.group(1))
    return {'commands': commands, 'final': final, 'turns': turns, 'permission_denials': denials, 'requests': requests}


if __name__ == '__main__':
    main()
