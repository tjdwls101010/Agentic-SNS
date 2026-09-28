"""Record every help text and fixture command's output, then compare two recordings.

    python3 -m tests.threads.tools.golden capture <dir> [--cli PATH]
    python3 -m tests.threads.tools.golden compare <before> <after>

Each scenario runs in a fresh THREADS_HOME with TZ=UTC against the fake Aside, in a fixed order, and records the exit
code, stdout, any --out file and the fake's request log (name, variables and doc_id of every request). Only the
scenario's temporary directory and three clock-dependent values (registry_age_days, and started_at or created_at
when they record the time of the run) are normalised when recording. `compare` additionally equates the CLI's own path in more: commands and argparse's program
name, the two differences a relocation of the entry point is allowed to make, and reports how often it did so.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from ..fixtures.builders import (ERRORS, Routes, collections, envelope, feed, listed_post, null_profile,
                                 person, tab, users)
from ..helpers import CLI, FAKE_ASIDE, POST as POST_URL, PROCESS_DOUBLES

COMMANDS = ('home', 'user', 'about', 'post', 'graph', 'search', 'me', 'doctor', 'refresh', 'schema')
FOLLOWING = 'BarcelonaFeedDirectQuery'


def viewer(routes):
    routes.copy('/@fixture_user', '/@fixture_viewer')


def graph(routes):
    routes.set('BarcelonaFriendshipsFollowersTabQuery',
               envelope(users('followers', [person(50), person(51)], cursor=False, counts={'followers': 1000})))
    routes.set('BarcelonaFriendshipsFollowingTabQuery',
               envelope(users('following', [person(60), person(61)], cursor='2', counts={'following': 4})))
    routes.set('BarcelonaFriendshipsFollowingTabRefetchableQuery:after=2',
               envelope(users('following', [person(62), person(63)], root='fetch__XDTUserDict')))


def blocked(routes):
    routes.set(FOLLOWING, ERRORS['checkpoint'])


def capped(routes):
    routes.set(FOLLOWING, envelope(feed([listed_post(1)], 'c1')))
    for n in range(1, 20):
        routes.set(f'{FOLLOWING}:after=c{n}', envelope(feed([listed_post(n + 1)], f'c{n + 1}')))


def restart(routes):
    routes.set('BarcelonaProfileThreadsTabDirectQuery:after', ERRORS['rotated'])
    routes.set('BarcelonaProfileThreadsTabDirectQuery', envelope(tab([listed_post(i) for i in range(1, 8)], 'B')))


def captured(routes):
    query = {'name': 'BarcelonaFriendshipsFollowersTabQuery', 'doc_id': '3001',
             'variables': {'userID': '42', 'first': 20, '__relay_internal__pv__Examplerelayprovider': True}}
    routes.set('capture', envelope(json.dumps({'queries': [query], 'missing': [], 'envelopes': [], 'request_count': 3,
                                               'count_complete': True, 'failed': None, 'attempts': []}), url=POST_URL))
    routes.set('BarcelonaFriendshipsFollowersTabQuery',
               envelope(users('followers', [person(50)], cursor=False, counts={'followers': 1})))


def window(routes):
    routes.set(FOLLOWING, envelope(feed([listed_post(1, taken_at=1790000000), listed_post(2, taken_at=1780000000)])))


# Each scenario: (name, fixture edits, commands). '@next' runs the previous JSON result's more: command;
# '@file <path>' records a file's content; '{tmp}' is the scenario's own directory.
SCENARIOS = [
    ('help', None, [['--help'], *[[command, '--help'] for command in COMMANDS]]),
    ('home-json', None, [['home', '--limit', '3', '--json'], '@next', '@next']),
    ('home-text', None, [['home', '--limit', '3'], ['home'], ['home', '--chars', '0', '--limit', '1']]),
    ('home-following', None, [['home', '--feed', 'following', '--limit', '3', '--json'], ['home', '--feed', 'following']]),
    ('home-window', window, [['home', '--feed', 'following', '--since', '2026-09-01', '--json'],
                             ['home', '--feed', 'following', '--until', '2026-09-01']]),
    ('user', None, [['user', '@fixture_user', '--json'], ['user', '@fixture_user', '--limit', '6'],
                    ['user', 'https://www.threads.com/@fixture_user/replies', '--json']]),
    ('user-window', None, [['user', '@fixture_user', '--since', '2027-01-01', '--out', '{tmp}/w.ndjson', '--json'],
                           ['user', '@fixture_user', '--since', '2027-01-01', '--out', '{tmp}/w.ndjson'],
                           '@file {tmp}/w.ndjson']),
    ('user-restart', restart, [['user', '@fixture_user', '--limit', '6', '--json']]),
    ('home-out', None, [['home', '--limit', '2', '--out', '{tmp}/h.ndjson', '--json'], '@next',
                        ['home', '--limit', '2', '--out', '{tmp}/h.ndjson'], '@file {tmp}/h.ndjson']),
    ('about', None, [['about', '@fixture_user'], ['about', '@fixture_user', '--json'],
                     ['about', '@fixture_user', '--out', '{tmp}/a.ndjson', '--json'], '@file {tmp}/a.ndjson']),
    ('about-null', null_profile, [['about', '@fixture_user', '--json']]),
    ('post', None, [['post', POST_URL], ['post', POST_URL, '--json'], ['post', POST_URL, '--limit', '1'],
                    ['post', POST_URL, '--sort', 'recent', '--json'], ['post', 'FIX_2', '--json'],
                    ['post', POST_URL, '--out', '{tmp}/p.ndjson', '--json'], '@file {tmp}/p.ndjson']),
    ('graph', graph, [['graph', '@fixture_user', 'followers'], ['graph', '@fixture_user', 'followers', '--json'],
                      ['graph', '@fixture_user', 'following', '--limit', '3', '--json'], '@next',
                      ['graph', '@fixture_user', 'following']]),
    ('collections', collections, [['search', 'python', '--limit', '3', '--json'], '@next',
                                  ['search', 'python', '--tag', '--limit', '2'],
                                  ['search', 'python', '--sort', 'recent', '--json'],
                                  ['search', 'python', '--type', 'users', '--limit', '1', '--json'], '@next',
                                  ['search', 'python', '--type', 'users'],
                                  ['me', 'liked', '--limit', '3', '--json'], '@next', ['me', 'liked'],
                                  ['me', 'saved', '--json']]),
    ('arguments', None, [['user', '/activity', '--json'], ['search', 'python', '--type', 'users', '--tag'],
                         ['home', '--since', '2026-01-01'], ['post', 'https://example.com/@a/post/B', '--json'],
                         ['home', '--after', '99'], ['home', '--chars', '-1'], ['graph', '@fixture_user'],
                         ['user', '@fixture_user', '--since', '2026-02-01', '--until', '2026-01-01']]),
    ('doctor', None, [['doctor'], ['doctor', '--unblock']]),
    ('refresh', viewer, [['refresh', '--json'], ['refresh', '--post', POST_URL], ['refresh', '--capture', '--json']]),
    ('capture', captured, [['refresh', '--capture', '--post', POST_URL, '--json'],
                           ['graph', '@fixture_user', 'followers', '--json']]),
    ('schema', None, [['schema'], ['schema', '--json']]),
    ('blocked', blocked, [['home', '--feed', 'following', '--json'], ['home'], ['doctor']]),
    ('capped', capped, [['home', '--feed', 'following', '--json'], '@next', ['home', '--feed', 'following']]),
]


def next_args(command):
    """The arguments of a more: command after the CLI path, whatever interpreter prefix it carries."""
    words = shlex.split(command)
    index = next(i for i, word in enumerate(words) if word.endswith(('threads.py', 'cli.py')))
    return words[index + 1:]


def run_scenario(name, edit, commands, cli):
    base = Path(tempfile.mkdtemp(prefix='threads-golden-'))
    routes = Routes(base)
    if edit:
        edit(routes)
    routes.write()
    log = base / 'requests.ndjson'
    environment = {**os.environ, 'THREADS_ASIDE_BIN': str(FAKE_ASIDE), 'THREADS_FIXTURES': str(routes.path),
                   'THREADS_FAKE_LOG': str(log), 'THREADS_HOME': str(base / 'home'), 'TZ': 'UTC',
                   'PYTHONPATH': str(PROCESS_DOUBLES), 'FAKE_NO_SLEEP': '1'}
    environment.pop('FAKE_CLOCK_OFFSET', None)
    lines, last, seen = [], None, 0
    for command in commands:
        if command == '@next':
            if not last or not last.get('next'):
                lines.append('@next: none')
                continue
            args = next_args(last['next'])
        elif isinstance(command, str) and command.startswith('@file '):
            path = Path(command.split(' ', 1)[1].replace('{tmp}', str(base)))
            lines += ['@file ' + str(path), path.read_text() if path.exists() else '<missing>']
            continue
        else:
            args = [part.replace('{tmp}', str(base)) for part in command]
        done = subprocess.run([sys.executable, str(cli), *args], capture_output=True, text=True, env=environment,
                              cwd=base, timeout=120)
        made = log.read_text().splitlines() if log.exists() else []
        lines += ['$ ' + shlex.join(args), f'exit {done.returncode}', done.stdout.rstrip('\n'),
                  'requests:', *made[seen:]]
        seen = len(made)
        try:
            last = json.loads(done.stdout)
        except ValueError:
            last = None
    text = '\n'.join(lines) + '\n'
    for path in sorted({str(base), os.path.realpath(base)}, key=len, reverse=True):
        text = text.replace(path, '<TMP>')
    text = re.sub(r'"registry_age_days": \d+', '"registry_age_days": <AGE>', text)
    # Execution times are written with +00:00; a post's own time uses Z and is kept.
    text = re.sub(r'"(started_at|created_at)": ?"[^"]*\+00:00"', r'"\1": "<TIME>"', text)
    return text


def capture(directory, cli):
    directory.mkdir(parents=True, exist_ok=True)
    for name, edit, commands in SCENARIOS:
        (directory / f'{name}.txt').write_text(run_scenario(name, edit, commands, cli))
    print(f'{len(SCENARIOS)} scenarios recorded in {directory}')


RELOCATION = [
    # The CLI in a more: command: shlex-quoted threads.py before, the double-quoted allowed-tools form after (escaped
    # once more inside JSON).
    (re.compile(r"python3 (?:'[^']*/threads\.py'|\S*/threads\.py)"), '<CLI>'),
    (re.compile(r'uv run (?:"[^"]*/cli\.py"|\\"[^"\\]*/cli\.py\\")'), '<CLI>'),
    # argparse's usage block, re-wrapped when the program name changes length.
    (re.compile(r'usage: (?:threads|cli)\.py(.*?)(?=\n\n|\Z)', re.S), lambda m: 'usage: <PROG>' + ' '.join(m[1].split())),
]


def compare(before, after):
    failures, allowed = [], 0
    names = sorted({p.name for p in before.glob('*.txt')} | {p.name for p in after.glob('*.txt')})
    for name in names:
        a, b = before / name, after / name
        if not a.exists() or not b.exists():
            failures.append(f'{name}: recorded on one side only')
            continue
        left, right = a.read_text(), b.read_text()
        if left == right:
            continue
        for pattern, replacement in RELOCATION:
            left, right = pattern.sub(replacement, left), pattern.sub(replacement, right)
        allowed += left == right
        if left != right:
            for number, (x, y) in enumerate(zip(left.splitlines(), right.splitlines()), 1):
                if x != y:
                    failures.append(f'{name}:{number}\n  - {x[:300]}\n  + {y[:300]}')
                    break
            else:
                failures.append(f'{name}: line count differs')
    print('\n'.join(failures) if failures else f'identical over {len(names)} scenarios; {allowed} differ only in '
                                                 f'the CLI path in more: or the program name')
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    record = commands.add_parser('capture', help='Record every scenario into a directory')
    record.add_argument('directory', type=Path)
    record.add_argument('--cli', type=Path, default=CLI, help='The entry point to run; default the current one')
    check = commands.add_parser('compare', help='Compare two recordings; exit 1 on any other difference')
    check.add_argument('before', type=Path)
    check.add_argument('after', type=Path)
    args = parser.parse_args()
    if args.command == 'capture':
        capture(args.directory, args.cli)
        return 0
    return compare(args.before, args.after)


if __name__ == '__main__':
    sys.exit(main())
