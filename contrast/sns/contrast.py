"""Contrast runs for the sns skill (plan P3/P8): one task, one SKILL.md body (an arm), a clean Claude that may run only
this skill's CLI and read its own run's files, watched for the platforms' block signals.

  python3 contrast.py RUN PLATFORM TASK --body FILE --arm NAME [--model M] [--repeat N] [--fake SCENARIO]
                      [--data-template DIR]

PLATFORM: x, threads, reddit, facebook, naver-blog, or cross (a task that may use every platform). --body is the
SKILL.md body the run gets (after the skill's own frontmatter, without the local-only line that turns automatic use
off); `${CLAUDE_SKILL_DIR}/scripts/cli.py` in it becomes the run's copy of the CLI. The baseline arm A is a body file
too: the invocation paragraph alone (arms/A.md). --arm names the body in the results; --model is any model id. TASK is
a file under tasks/<platform>/ (or a path); ${NAME} in it is filled from the environment, so real people, posts and
URLs never live in the repository.

Each of --repeat repetitions is its own run, RUN-r<k>. A run whose child met a permission denial says nothing about
the skill (it could not do what it tried): it is marked invalid and run again, at most twice, as RUN-r<k>-a<n>. Every
attempt is one line in $SNS_WORK/cells.jsonl (run, task, platform, arm, model, repetition, attempt, valid) — what
aggregate.py counts. blind.py turns runs into what graders see; grader.md is what they are asked.

State per run (SNS_DATA_DIR is a new directory for every run): <platform>/<account>/protection/ and session/ are links
to the skill's real state directory (sns.paths.data_dir(): one account, one lock, one pacing, one block record, one
dedicated tab across every run and every ordinary invocation); handles, images and Reddit snapshots are the run's own,
so no run continues another's. Before linking, a live run takes in the skill's old data/ (from before the state moved)
the way any invocation would, and does not start when that fails: a contrast run may be the install's first. When a
run ends — normally, stopped at a block signal, or by an exception — the dedicated tab is emptied
(`<platform> idle --token any --after 0`), the links are cut before anything is copied, and summary.json is written.

A --fake run uses tests/sns/fakes/fake_aside.py with SCENARIO and a throwaway data directory (from --data-template when
given, e.g. one holding a recorded block) and its shell is held by the OS sandbox; a live run only by the permission
rules (aside cannot sign its daemon challenge inside the OS sandbox) — that is not OS isolation, and reports never call
it that. CONTRAST_CLAUDE names the claude executable (tests give a stand-in).

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
RETRIES = 2   # a run invalidated by a permission denial is run again at most this many times

sys.path.insert(0, str(HERE))
import ledger  # noqa: E402


def work_dir():
    """ledger.work_dir(), refused inside the repository: runs hold other people's posts."""
    path = ledger.work_dir().resolve()
    if path == REPO or REPO in path.parents:
        raise SystemExit(f'SNS_WORK ({path}) is inside the repository; runs hold other people\'s posts')
    return path


def platforms_of(platform):
    return list(PLATFORMS) if platform == 'cross' else [platform.replace('-', '_')]


def body_text(body, cli, text=None):
    """The SKILL.md a run reads: the skill's frontmatter (without the local-only line that turns automatic use off) and
    the arm's body, with the skill's CLI path made the run's copy."""
    head = (SKILL / 'SKILL.md').read_text().split('\n---\n', 1)[0] + '\n---\n'
    head = '\n'.join(line for line in head.splitlines() if not line.startswith('disable-model-invocation:')) + '\n'
    text = Path(body).read_text() if text is None else text
    return head + '\n' + text.replace('${CLAUDE_SKILL_DIR}/scripts/cli.py', cli).lstrip('\n')


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


def skill_units():
    """The skill's package on the path, for the unit interfaces maintenance code may use."""
    if str(SKILL / 'scripts') not in sys.path:
        sys.path.insert(0, str(SKILL / 'scripts'))


def real_state():
    """Where an ordinary invocation of the skill keeps its state in this environment."""
    skill_units()
    from sns.paths import data_dir
    return data_dir()


def take_in_old_state(platforms, account, real, legacy=None):
    """Take the skill's old data/ in for each platform, into `real`, as the first invocation would; raises SystemExit
    (the run does not start) when it cannot."""
    skill_units()
    import importlib
    from sns.clock import Deadline
    from sns.errors import SnsError
    from sns.reading import adopt
    saved = os.environ.get('SNS_DATA_DIR')
    os.environ['SNS_DATA_DIR'] = str(real)
    try:
        for platform in platforms:
            adapter = importlib.import_module(f'sns.{platform}').PLATFORM
            try:
                adopt(adapter, account, Deadline(60), legacy=legacy or _old_data())
            except SnsError as error:
                raise SystemExit(f'cannot take the old state in for {platform}: {error.message}') from None
    finally:
        if saved is None:
            os.environ.pop('SNS_DATA_DIR', None)
        else:
            os.environ['SNS_DATA_DIR'] = saved


def _old_data():
    old = SKILL / 'data'
    return old if old.is_dir() else None


def link_shared(data_dir, platforms, account, real):
    """Link each platform's protection and session state to the skill's real state; returns the links made."""
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
    skill_units()
    from sns.aside import active_account  # maintenance code reads the skill through its unit interface
    done = subprocess.run([env.get('SNS_ASIDE_BIN') or 'aside', 'account', 'status'], capture_output=True, text=True,
                          env=env)
    account = active_account(done.stdout)
    if not account:
        raise SystemExit('cannot tell the active Aside account; set SNS_ASIDE_ACCOUNT')
    return account


def run(args):
    """Every repetition of one cell (task × arm × model): each until it is valid or out of retries. Returns the
    summaries of every attempt, in order."""
    task = task_text(args.platform.replace('_', '-'), args.task)  # refuses before anything starts
    summaries = []
    for repetition in range(1, args.repeat + 1):
        for attempt in range(RETRIES + 1):
            name = f'{args.run}-r{repetition}' + (f'-a{attempt}' if attempt else '')
            summary = run_once(args, name, task)
            # evidence only from a run that finished on its own: no denial (it could not do what it tried), a final
            # answer, and no block signal (a platform pushed back and the run was stopped)
            summary.update(repetition=repetition, attempt=attempt,
                           valid=not summary['permission_denials'] and summary['final'] is not None
                           and not summary.get('block_signal'))
            (work_dir() / 'runs' / name / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
            record(summary)
            summaries.append(summary)
            if summary['valid'] or summary.get('block_signal') or not summary['permission_denials']:
                break  # only a denial is retried: a block stops everything, a run without an answer is not repeated
        if summaries[-1].get('block_signal'):
            break  # a platform pushed back: nothing more goes out
    return summaries


def record(summary):
    """One line per attempt in the cell index aggregate.py reads."""
    line = {k: summary.get(k) for k in ('run', 'task_name', 'platform', 'arm', 'model', 'repetition', 'attempt',
                                         'valid', 'block_signal', 'fake')}
    with (work_dir() / 'cells.jsonl').open('a') as stream:
        stream.write(json.dumps(line, ensure_ascii=False) + '\n')


def run_once(args, name, task):
    root = work_dir() / 'runs' / name
    if root.exists():
        raise SystemExit(f'{root} exists; pick a new run name')
    platforms = platforms_of(args.platform)
    root.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix=f'sns-contrast-{name}-'))
    copy = scratch / 'skill'
    shutil.copytree(SKILL / 'scripts', copy / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    if (SKILL / 'references').exists():
        shutil.copytree(SKILL / 'references', copy / 'references')
    cli = str(copy / 'scripts/cli.py')
    given = Path(args.body).read_text()  # read once: what the run gets is what the summary keeps
    (copy / 'SKILL.md').write_text(body_text(args.body, cli, given))
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
        real = real_state()
        take_in_old_state(platforms, account, real)
        links = link_shared(data_dir, platforms, account, real)
    env['SNS_DATA_DIR'] = str(data_dir)
    settings = root / 'settings.json'
    settings.write_text(json.dumps(sandbox_settings(scratch, data_dir), indent=1))
    prompt = (f'먼저 {copy}/SKILL.md를 읽고 따르세요. {copy}/scripts 아래 파일은 읽지 말고, 도구는 --help와 schema 명령, '
              f'그리고 출력으로 익히세요.\n\n과제: {task}')
    sandbox = ['--settings', str(settings)] if args.fake else []
    command = [os.environ.get('CONTRAST_CLAUDE') or 'claude', '-p', '--safe-mode', '--restricted',
               '--no-session-persistence', *sandbox, '--tools', 'Bash,Read,Grep,Glob',
               '--allowedTools', f'Bash(uv run "{cli}" *)', f'Read(/{data_dir}/**)',
               '--model', args.model, '--output-format', 'stream-json', '--verbose', prompt]
    started = time.time()
    child, watched = None, {'outcome': 'not started', 'signal': None, 'counted': 0}
    try:
        with (root / 'events.jsonl').open('w') as events, (root / 'stderr.txt').open('w') as errors:
            child = subprocess.Popen(command, cwd=scratch, env=env, stdout=events, stderr=errors,
                                     start_new_session=True)
            watched = ledger.watch(child, logs=lambda: ledger.request_logs(data_dir, platforms), started_at=started)
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
    summary.update(run=name, platform=args.platform, arm=args.arm, body=str(args.body),
                   body_text=given, model=args.model, task=task,
                   task_name=args.task,
                   exit=child.returncode if child else None, fake=bool(args.fake), watch=watched['outcome'],
                   block_signal=watched['signal'], logged_requests=watched['counted'],
                   stderr=(root / 'stderr.txt').read_text()[-2000:])
    (root / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    if not args.fake:
        ledger.add(work_dir() / 'request-record.tsv', f'contrast {name}', watched['counted'],
                   f'{args.platform} {args.arm} {args.model}'
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
    parser.add_argument('task')
    parser.add_argument('--body', required=True, type=Path, help='the SKILL.md body this arm gets')
    parser.add_argument('--arm', required=True, help='the name this body has in the results (A, F, F-1, …)')
    parser.add_argument('--model', default='claude-opus-5-5', help='any model id the claude CLI takes')
    parser.add_argument('--repeat', type=int, default=3, help='repetitions of this cell (default 3)')
    parser.add_argument('--fake')
    parser.add_argument('--data-template')
    args = parser.parse_args(argv)
    if not args.body.is_file():
        parser.error(f'--body {args.body} is not a file')
    if args.repeat < 1:
        parser.error('--repeat must be at least 1')
    for summary in run(args):
        print(json.dumps({k: summary.get(k) for k in ('run', 'platform', 'arm', 'model', 'repetition', 'attempt',
                                                       'valid', 'exit', 'watch', 'block_signal', 'turns', 'requests',
                                                       'logged_requests', 'permission_denials')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
