"""Contrast runs for the sns skill (plan P6): one task, one SKILL.md variant, a clean Claude that may run only this
skill's CLI, watched for the platforms' block signals.

  python3 contrast.py RUN PLATFORM VARIANT TASK [--model M] [--fake SCENARIO] [--data-template DIR]

PLATFORM: x, threads, reddit, facebook, naver-blog, or cross (a task that may use every platform). VARIANT: A (the
frontmatter and the invocation line), B (the draft), C:<heading> (the draft without the section whose heading starts
with <heading>). TASK is a file under tasks/<platform>/ (or a path); ${NAME} in it is filled from the environment, so
real people, posts and URLs never live in the repository.

State per run (SNS_DATA_DIR is a new directory for every run): data/<platform>/<account>/protection/ and session/ are
links to the skill's real data/ (one account: one lock, one pacing, one block record, one dedicated tab across every
run); handles, images and Reddit snapshots are the run's own, so no run continues another's. When a run ends — normally,
stopped at a block signal, or by an exception — the dedicated tab is emptied (`<platform> idle --token any --after 0`),
the links are cut before anything is copied, and summary.json is written.

A --fake run uses tests/sns/fakes/fake_aside.py with SCENARIO and a throwaway data directory (from --data-template when
given, e.g. one holding a recorded block) and its shell is held by the OS sandbox; a live run only by the permission
rules (aside cannot sign its daemon challenge inside the OS sandbox) — that is not OS isolation, and reports never call
it that. Before a set of live runs, legacy_hook('import'); after it and right after a block signal, legacy_hook('export').

Outputs go to $SNS_WORK/runs/<RUN>/ (outside the repository: they hold other people's posts): work/, settings.json,
events.jsonl, summary.json.
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILL = REPO / '.claude/skills/sns'
DATA = SKILL / 'data'
FAKE = REPO / 'tests/sns/fakes/fake_aside.py'


def fake_launcher(directory):
    """A one-line launcher for the fake Aside (a Python file without the executable bit), run by this Python."""
    launcher = Path(directory) / 'aside'
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    launcher.chmod(0o755)
    return launcher
PLATFORMS = ('x', 'threads', 'reddit', 'facebook', 'naver_blog')
TAB_PLATFORMS = ('x', 'threads', 'facebook')
SHARED = ('protection', 'session')
MODELS = ('claude-opus-5-5', 'claude-sonnet-5-5')

sys.path.insert(0, str(HERE))
import ledger  # noqa: E402


def work_dir():
    return Path(os.environ.get('SNS_WORK') or Path.home() / '.claude/projects/-Users-seongjin-Coding-Agentic-SNS'
                / 'sns-unification')


def legacy_hook(action):
    """import or export protection state between the old skills and sns while both exist; nothing once the converter
    is gone (the last commit of the sns PR removes it with the old skills)."""
    script = HERE / 'legacy_state.py'
    if not script.exists():
        return None
    done = subprocess.run(['uv', 'run', str(script), action], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else f'legacy {action} failed: {done.stderr[-500:]}'


def platforms_of(platform):
    return list(PLATFORMS) if platform == 'cross' else [platform.replace('-', '_')]


def variant_text(variant, cli, draft):
    head = (SKILL / 'SKILL.md').read_text().split('\n---\n', 1)[0] + '\n---\n'
    if variant == 'A':
        return head + ('\n# Social networks through the user\'s own browser\n\n'
                       f'Run `uv run "{cli}" <platform> <command> …` on one line. `--help` maps every platform\'s '
                       'commands, `<platform> <command> --help` explains one, `<platform> schema` what results, files '
                       'and fields mean, and each error\'s `fix` how to recover.\n')
    text = Path(draft).read_text().replace('${CLAUDE_SKILL_DIR}/scripts/cli.py', cli)
    if variant == 'B':
        return text
    heading = variant.split(':', 1)[1]
    parts = re.split(r'(?m)^(?=## )', text)
    kept = [p for p in parts if not p.startswith('## ' + heading)]
    if len(kept) == len(parts):
        raise SystemExit(f'no section starting with "## {heading}"')
    return ''.join(kept)


def task_text(platform, name):
    path = Path(name) if Path(name).exists() else HERE / 'tasks' / platform / (
        name if name.endswith('.txt') else name + '.txt')
    text = path.read_text().strip()
    missing = sorted({m for m in re.findall(r'\$\{([A-Z0-9_]+)\}', text) if m not in os.environ})
    if missing:
        raise SystemExit('set ' + ', '.join(missing) + ' for this task')
    return re.sub(r'\$\{([A-Z0-9_]+)\}', lambda m: os.environ[m.group(1)], text)


def sandbox_settings(root, data_dir):
    """The OS sandbox a fake run's shell runs in: writes only to the run's workspace and data, no escape."""
    return {'sandbox': {'enabled': True, 'failIfUnavailable': True, 'allowUnsandboxedCommands': False,
                        'autoAllowBashIfSandboxed': False,
                        'filesystem': {'allowWrite': [str(root), str(data_dir), str(Path.home() / '.cache/uv')]},
                        'network': {'allowLocalBinding': True, 'allowAllUnixSockets': True}}}


def link_shared(data_dir, platforms, account, real=DATA):
    """Link each platform's protection and session state to the skill's real data/; returns the links made."""
    links = []
    for platform in platforms:
        for kind in SHARED:
            target = real / platform / account / kind
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            link = data_dir / platform / account / kind
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target, target_is_directory=True)
            links.append(link)
    return links


def cut_links(links):
    for link in links:
        if link.is_symlink():
            link.unlink()


def empty_tabs(cli, platforms, account, env):
    """Empty the dedicated tab of each tab platform the run used (a command stopped by force left no cleanup)."""
    for platform in platforms:
        if platform in TAB_PLATFORMS:
            subprocess.run([sys.executable, cli, platform.replace('_', '-'), 'idle', '--account', account, '--token',
                            'any', '--after', '0'], env=env, capture_output=True, text=True, timeout=120)


def resolve_account(env):
    named = env.get('SNS_ASIDE_ACCOUNT')
    if named:
        return named
    sys.path.insert(0, str(SKILL / 'scripts'))
    from sns.aside import active_account  # maintenance code reads the skill through its unit interface
    done = subprocess.run([env.get('SNS_ASIDE_BIN') or 'aside', 'account', 'status'], capture_output=True, text=True,
                          env=env)
    account = active_account(done.stdout)
    if not account:
        raise SystemExit('cannot tell the active Aside account; set SNS_ASIDE_ACCOUNT')
    return account


def run(args):
    root = work_dir() / 'runs' / args.run
    if root.exists():
        raise SystemExit(f'{root} exists; pick a new run name')
    platforms = platforms_of(args.platform)
    task = task_text(args.platform.replace('_', '-'), args.task)
    root.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix=f'sns-contrast-{args.run}-'))
    copy = scratch / 'skill'
    shutil.copytree(SKILL / 'scripts', copy / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    if (SKILL / 'references').exists():
        shutil.copytree(SKILL / 'references', copy / 'references')
    cli = str(copy / 'scripts/cli.py')
    (copy / 'SKILL.md').write_text(variant_text(args.variant, cli, work_dir() / 'drafts/SKILL.md'))
    env = {k: v for k, v in os.environ.items() if not k.startswith('SNS_') or k.startswith('SNS_ASIDE_ACCOUNT')}
    data_dir = scratch / 'data'
    data_dir.mkdir()
    links = []
    if args.fake:
        if args.data_template:
            shutil.copytree(args.data_template, data_dir, dirs_exist_ok=True)
        shutil.copy(args.fake, scratch / 'scenario.json')  # the fake marks responses used: never the original
        env.update(SNS_ASIDE_BIN=str(fake_launcher(scratch)), SNS_FAKE_SCENARIO=str(scratch / 'scenario.json'),
                   SNS_FAKE_LOG=str(scratch / 'fake-log.jsonl'), SNS_IDLE_SECONDS='off')
        account = resolve_account(env)
    else:
        account = resolve_account(env)
        links = link_shared(data_dir, platforms, account)
    env['SNS_DATA_DIR'] = str(data_dir)
    settings = root / 'settings.json'
    settings.write_text(json.dumps(sandbox_settings(scratch, data_dir), indent=1))
    prompt = (f'먼저 {copy}/SKILL.md를 읽고 따르세요. {copy}/scripts 아래 파일은 읽지 말고, 도구는 --help와 schema 명령, '
              f'그리고 출력으로 익히세요.\n\n과제: {task}')
    sandbox = ['--settings', str(settings)] if args.fake else []
    command = ['claude', '-p', '--safe-mode', '--restricted', '--no-session-persistence', *sandbox,
               '--tools', 'Bash,Read,Grep,Glob', '--allowedTools', f'Bash(uv run "{cli}" *)',
               '--model', args.model, '--output-format', 'stream-json', '--verbose', prompt]
    started = time.time()
    child, watched = None, {'outcome': 'not started', 'signal': None, 'counted': 0}
    try:
        with (root / 'events.jsonl').open('w') as events, (root / 'stderr.txt').open('w') as errors:
            child = subprocess.Popen(command, cwd=scratch, env=env, stdout=events, stderr=errors,
                                     start_new_session=True)
            watched = ledger.watch(child, logs=lambda: ledger.request_logs(data_dir, platforms), started_at=started,
                                   on_signal=None if args.fake else (lambda _: legacy_hook('export')))
    finally:
        if child is not None and child.poll() is None:
            ledger.stop_group(child)
        if not args.fake:
            empty_tabs(cli, platforms, account, env)
        cut_links(links)  # never copy the shared state into the run directory
        shutil.copytree(scratch, root / 'work', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.rmtree(scratch, ignore_errors=True)
    summary = summarize(root / 'events.jsonl')
    summary['out_files'] = sorted({m for c in summary['commands'] if c['tool'] == 'Bash'
                                   for m in re.findall(r'--out[= ](\S+)', c['input'])})
    summary.update(run=args.run, platform=args.platform, variant=args.variant, model=args.model, task=task,
                   exit=child.returncode if child else None, fake=bool(args.fake), watch=watched['outcome'],
                   block_signal=watched['signal'], logged_requests=watched['counted'],
                   stderr=(root / 'stderr.txt').read_text()[-2000:])
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    if not args.fake:
        ledger.add(work_dir() / 'request-record.tsv', f'P6 contrast {args.run}', watched['counted'],
                   f'{args.platform} {args.variant} {args.model}'
                   + (f' — stopped at {watched["signal"]}' if watched['signal'] else ''))
    return summary


def summarize(path):
    """Commands the child ran with the head of each output, its final answer, denials, and the requests its outputs
    reported (requests=N)."""
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
            continue
        match = re.search(r'requests=(\d+)', text) or re.search(r'"request_count":\s*(\d+)', text)
        if match:
            requests += int(match.group(1))
    return {'commands': commands, 'final': final, 'turns': turns, 'permission_denials': denials, 'requests': requests}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('platform', choices=['x', 'threads', 'reddit', 'facebook', 'naver-blog', 'cross'])
    parser.add_argument('variant')
    parser.add_argument('task')
    parser.add_argument('--model', choices=MODELS, default=MODELS[0])
    parser.add_argument('--fake')
    parser.add_argument('--data-template')
    summary = run(parser.parse_args(argv))
    print(json.dumps({k: summary[k] for k in ('run', 'platform', 'variant', 'model', 'exit', 'watch', 'block_signal',
                                              'turns', 'requests', 'logged_requests', 'permission_denials')},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
