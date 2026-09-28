"""Run Claude on a Threads task with the skill body, without it, or without one paragraph, and summarise the runs.

    python3 -m tests.threads.tools.ablation run TASK ARM --body SKILL.md --runs DIR [--mode record|replay|fixture]
        [--snapshot DIR] [--model claude-opus-5-5]
    python3 -m tests.threads.tools.ablation summary DIR...

ARM is FULL, CLI (only the invocation paragraph) or minus-<paragraph id> (see PARAGRAPHS). Each run gets its own copy
of the skill, an empty working directory, and its own THREADS_HOME seeded with the registry override of the account's
own cache, so replayed doc_ids match the recording. Live tasks record through the live bridge (--mode record) or
replay a frozen snapshot (--mode replay); offline F tasks run on synthetic fixtures. A run is invalid when replay
missed a key; summary says so.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..fixtures.builders import ERRORS, Routes, envelope, listed_post, preloader, route, tab
from ..helpers import FAKE_ASIDE, PROCESS_DOUBLES, SKILL

LIVE_BRIDGE = Path(__file__).parents[1] / 'live_bridge' / 'aside'
TASKS = {
    'T1': 'Threads에서 Opus 5.5에 대한 반응을 조사해서 요약해줘',
    'T2': "지난 일주일 Threads에서 '클로드 코드 크레딧' 얘기가 어떻게 돌고 있어?",
    'T3': '@golbin이 최근 2주 동안 쓴 글과 답글 활동을 정리해줘',
    'T4': '@golbin은 누구를 팔로우하고, 팔로잉·팔로워는 몇이야?',
    'F1': 'Threads에서 @fixture_user의 최근 스레드 글 6개를 보여줘',
    'F2': 'Threads 팔로잉 피드에서 최근 글 5개 보여줘',
    'F3': 'Threads에서 @fixture_user가 지금까지 쓴 글 전체를 보고, 가장 자주 다룬 주제 세 가지를 알려줘',
}
# Paragraph ids for minus-X arms: the opening words of each removable paragraph of the body.
PARAGRAPHS = {
    'account': 'Threads sends no rate-limit headers',
    'replies': 'The replies a post shows',
    'attribution': 'A quote or repost carries',
    'dates': 'Dates are when a post was written',
    'about': 'When who someone is',
    'collections': 'Use `--out` when the corpus',
}
HARNESS = ('\n\nThis task is run in a test harness: use the CLI above; its source code and any skill files are out of '
           'scope, do not read them.')


def body_for(arm, text):
    body = re.sub(r'\A---\n.*?\n---\n', '', text, count=1, flags=re.S).strip()
    if arm == 'FULL':
        return body
    if arm == 'CLI':
        return next(p for p in body.split('\n\n') if p.startswith('Run `uv run'))
    start = PARAGRAPHS[arm.removeprefix('minus-')]
    paragraphs = [p for p in body.split('\n\n') if not p.startswith(start)]
    assert len(paragraphs) == len(body.split('\n\n')) - 1, arm
    # A heading left with nothing under it goes too.
    kept = [p for i, p in enumerate(paragraphs)
            if not (p.startswith('## ') and (i + 1 == len(paragraphs) or paragraphs[i + 1].startswith('## ')))]
    return '\n\n'.join(kept)


def fixtures(task, directory):
    """Offline tasks: a rotated query refresh repairs (F1), a checkpoint (F2), a corpus larger than the answer (F3)."""
    routes = Routes(directory)
    if task == 'F1':
        routes.copy('/@fixture_user', '/@fixture_viewer')
        tab_page = envelope(tab([listed_post(i) for i in range(1, 8)], 'B'))
        routes.set('BarcelonaProfileThreadsTabDirectQuery:after', ERRORS['rotated'], ERRORS['rotated'],
                   envelope(tab([listed_post(i) for i in range(5, 9)])))
        routes.set('BarcelonaProfileThreadsTabDirectQuery', ERRORS['rotated'], tab_page, tab_page)
    elif task == 'F2':
        routes.set('/following', envelope('synthetic checkpoint page <form action="/challenge/"></form>',
                                          url='https://www.threads.com/following'))
    elif task == 'F3':
        topics = ['coffee roasting', 'marathon training', 'home espresso', 'trail running', 'sourdough baking']
        pages = [[listed_post(n, caption={'text': f'Synthetic note {n} about {topics[n % len(topics)]}'})
                  for n in range(p * 10 + 1, p * 10 + 11)] for p in range(12)]
        first = route([preloader('BarcelonaProfilePageDirectQuery', userID='42', canSeeFeedsTab=True,
                                 showLinkedIGStats=False),
                       preloader('BarcelonaProfileThreadsTabDirectQuery', userID='42', first=4,
                                 allow_page_info_for_lox_user=False),
                       {'__bbox': {'result': {'data': {'user': {'pk': '42', 'username': 'fixture_user',
                                                                 'full_name': 'Synthetic Person'}}}}},
                       {'__bbox': {'result': {'data': tab(pages[0], 'p1')['data']}}}],
                      url='https://www.threads.com/@fixture_user')
        routes.set('/@fixture_user', first)
        for index, posts in enumerate(pages[1:], 1):
            routes.set(f'BarcelonaProfileThreadsTabDirectQuery:after=p{index}',
                       envelope(tab(posts, f'p{index + 1}' if index < len(pages) - 1 else None)))
    return routes.write()


def run(args):
    runs = Path(args.runs).resolve()
    runs.mkdir(parents=True, exist_ok=True)
    if args.snapshot:
        args.snapshot = str(Path(args.snapshot).resolve())
    number = 1
    while True:  # claim a run folder; concurrent runs of one arm take the next number
        base = runs / f'{args.task}-{args.arm}-{number}'
        try:
            base.mkdir()
            break
        except FileExistsError:
            number += 1
    skill = base / 'skill' / 'threads'
    shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns('__pycache__'))
    (base / 'work').mkdir()
    home = base / 'home'
    home.mkdir()
    own = Path.home() / '.cache/threads-skill/registry.json'
    if own.exists() and args.task.startswith('T'):
        shutil.copy(own, home / 'registry.json')
    body = body_for(args.arm, Path(args.body).read_text()).replace('${CLAUDE_SKILL_DIR}', str(skill)) + HARNESS
    (base / 'system.md').write_text(body)
    env = {**os.environ, 'THREADS_ASIDE_BIN': str(FAKE_ASIDE), 'THREADS_FAKE_LOG': str(base / 'requests.ndjson'),
           'THREADS_HOME': str(home), 'THREADS_HARNESS_LOG': str(base / 'misses.ndjson')}
    for name in ('THREADS_RECORD', 'THREADS_REPLAY', 'THREADS_FIXTURES', 'FAKE_NO_SLEEP', 'PYTHONPATH'):
        env.pop(name, None)
    if args.mode == 'record':
        env.update(THREADS_RECORD=args.snapshot, THREADS_REAL_ASIDE=str(LIVE_BRIDGE),
                   THREADS_LIVE_ASIDE=shutil.which('aside'), THREADS_LIVE_LEDGER=str(Path(args.snapshot) / 'ledger.json'),
                   THREADS_LIVE_CAP=str(args.cap))
    else:
        env.update(PYTHONPATH=str(PROCESS_DOUBLES), FAKE_NO_SLEEP='1')
        if args.mode == 'replay':
            env['THREADS_REPLAY'] = args.snapshot
        else:
            env['THREADS_FIXTURES'] = str(fixtures(args.task, base))
    command = ['claude', '-p', '--safe-mode', '--restricted', '--permission-mode', 'acceptEdits', '--tools', 'Bash,Read',
               '--allowedTools', 'Bash', '--model', args.model, '--append-system-prompt-file', str(base / 'system.md'),
               '--output-format', 'stream-json', '--verbose', TASKS[args.task]]
    started = time.time()
    with (base / 'stream.jsonl').open('w') as stream:
        done = subprocess.run(command, cwd=base / 'work', env=env, stdin=subprocess.DEVNULL, stdout=stream,
                              stderr=subprocess.PIPE, text=True, timeout=args.timeout)
    (base / 'meta.json').write_text(json.dumps({'task': args.task, 'arm': args.arm, 'mode': args.mode,
                                                'exit': done.returncode, 'seconds': round(time.time() - started),
                                                'stderr': done.stderr[-2000:]}))
    print(json.dumps(summarise(base), ensure_ascii=False))


def summarise(base):
    base = Path(base)
    events = [json.loads(line) for line in (base / 'stream.jsonl').read_text().splitlines() if line.startswith('{')]
    commands, answer = [], ''
    for event in events:
        if event.get('type') == 'assistant':
            for block in event['message'].get('content', []):
                if block.get('type') == 'tool_use' and block.get('name') == 'Bash':
                    commands.append(block['input'].get('command', ''))
        if event.get('type') == 'result':
            answer = event.get('result') or ''
    requests = (base / 'requests.ndjson').read_text().splitlines() if (base / 'requests.ndjson').exists() else []
    misses = (base / 'misses.ndjson').read_text().splitlines() if (base / 'misses.ndjson').exists() else []
    cli = [c for c in commands if 'cli.py' in c]
    return {'run': base.name, 'valid': not misses, 'misses': len(misses), 'cli_calls': len(cli),
            'other_commands': len(commands) - len(cli), 'requests': len(requests),
            'commands': [re.sub(r'uv run "[^"]*/cli\.py"', 'T', c)[:200] for c in commands], 'answer': answer}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('run', help='Run one task under one arm')
    one.add_argument('task', choices=TASKS)
    one.add_argument('arm', help='FULL, CLI or minus-<paragraph id>: ' + ', '.join(PARAGRAPHS))
    one.add_argument('--body', required=True, help='The candidate SKILL.md')
    one.add_argument('--runs', required=True, help='Directory the run folder is made in')
    one.add_argument('--mode', choices=['record', 'replay', 'fixture'], default='fixture')
    one.add_argument('--snapshot', help='Snapshot directory for record/replay')
    one.add_argument('--cap', type=int, default=20, help='Live requests the recording may make (default 20)')
    one.add_argument('--model', default='claude-opus-5-5')
    one.add_argument('--timeout', type=int, default=1200)
    many = commands.add_parser('summary', help='Summarise finished runs as JSON lines')
    many.add_argument('runs', nargs='+')
    args = parser.parse_args()
    if args.command == 'run':
        run(args)
    else:
        for path in args.runs:
            print(json.dumps(summarise(path), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
