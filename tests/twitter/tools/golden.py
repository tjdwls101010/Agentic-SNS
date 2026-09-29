#!/usr/bin/env python3
"""Record every help text and fake-Aside command output of the twitter CLI, then compare two recordings.

    python3 tests/twitter/tools/golden.py capture <dir> [--cli PATH]
    python3 tests/twitter/tools/golden.py compare <before> <after> [--strict]

Each scenario runs in a freshly seeded TWITTER_HOME (state carries over only between the commands of one scenario, such as a continuation chain or an --out resume) with TZ=UTC and PYTHONHASHSEED=0, and records per command the exit code, stdout and the fake Aside's request log; '@file' records an --out file and '@next' runs the previous JSON result's more: command for real. Recording normalises only the scenario's own directory, the clock values reset_at, observed_at, fetched_at and read_at, relative reset minutes, Unix wait times, doctor's cache ages, and the order of `seen` lists. `compare` also equates the CLI prefix of more: commands and argparse's program name, the two differences a relocation of the entry point may make, and says how often it did so; --strict equates nothing.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / '.claude/skills/twitter/scripts'
FAKE_ASIDE = Path(__file__).resolve().parents[1] / 'fake_aside/aside'
COMMANDS = ['home', 'user', 'about', 'post', 'quotes', 'reposts', 'search', 'graph', 'me', 'list', 'trends',
            'community', 'communities', 'doctor', 'refresh', 'schema']
SURFACES = [
    ['home'], ['home', '--feed', 'following'],
    *[['user', '@example', '--tab', tab] for tab in ('posts', 'replies', 'replies-only', 'media', 'highlights', 'articles')],
    ['about', '@example', '@second'], ['about', '@example'], ['about', '@example', '@missing'],
    ['post', '200'], ['post', '200', '201'], ['post', '200', '--sort', 'recent'],
    ['quotes', '200'], ['reposts', '200'],
    ['search', 'example'], ['search', 'example', '--sort', 'top'], ['search', 'example', '--type', 'users'],
    ['search', 'example', '--type', 'media'], ['search', 'example', '--in', 'communities'],
    *[['graph', '@example', relation] for relation in ('following', 'followers', 'verified', 'known')],
    ['me', 'likes'], ['me', 'bookmarks'],
    ['list', '1'], ['list', '1', '--tab', 'members'], ['list', '1', '--tab', 'about'],
    ['trends'], ['trends', '--tab', 'foryou'], ['trends', '--tab', 'news'],
    ['community', '1'], ['community', '1', '--tab', 'media'], ['community', '1', '--tab', 'about'],
    ['community', '1', '--sort', 'recent'], ['communities'],
]
REJECTIONS = [
    ['home', '--since', '2026-01-01'], ['user', '123'], ['about', '@example', '--after', '1'],
    ['search', 'x', '--in', 'communities', '--type', 'users'], ['search', 'x', '--in', 'communities', '--sort', 'top'],
    ['list', '1', '--tab', 'about', '--after', '1'], ['post', '1', '2', '--after', '1'], ['post', '1', '2', '--sort', 'top'],
    ['community', '1', '--tab', 'media', '--sort', 'recent'], ['search', 'x', '--limit', '0'],
    ['user', '@example', '--until', 'nonsense'], ['user', '@example', '--since', '2026-02-01', '--until', '2026-01-01'],
    ['about', '@example', '@second', '--limit', '1'], ['post', '200', '201', '--limit', '1'], ['home', '--after', '0'],
    ['search', 'python', '--type', 'users', '--sort', 'latest'], ['user', '@example', '--chars', '0'], ['search'],
    ['graph', '@example'], ['home', '--tab', 'x'], ['trends', '--after', '1'], ['user', 'https://t.co/x'],
    ['list', 'abc'], ['post', 'https://evil.com/a/status/1'], ['home', '--after', '7'], ['user', '@example', '--out', '{tmp}/a', '--after', '1'],
]


def blocked(home):
    (home / 'budget.json').write_text(json.dumps({'block': {'reason': 'challenge', 'expires_at': None}}))


def other_viewer(home):
    (home / 'session.json').write_text(json.dumps({'ct0': 'synthetic', 'viewer_id': '200', 'read_at': 0}))
    (home / 'cursors').mkdir()
    (home / 'cursors/1.json').write_text('{}')


def cold(home):
    (home / 'session.json').unlink()


# Each scenario: (name, seed(home) or None, extra environment, commands). '@next' runs the previous JSON result's
# more: command; '@file <path>' records a file; '{tmp}' is the scenario's own directory.
SCENARIOS = [
    ('help', None, {}, [['--help'], *[[command, '--help'] for command in COMMANDS]]),
    ('schema', None, {}, [['schema'], ['schema', '--json']]),
    *[(f'surface-{mode}-' + '_'.join(re.sub(r'\W', '', a) for a in args), None, {},
       [[*args, *([] if args[0] == 'about' or args[0] == 'post' and len(args) > 2 and args[2] != '--sort'
                  else ['--limit', '2']), *(['--json'] if mode == 'json' else [])]])
      for args in SURFACES for mode in ('text', 'json')],
    ('surface-defaults', None, {}, [['home'], ['post', '200'], ['search', 'example', '--json'], ['trends', '--json']]),
    *[(f'reject-{index:02d}', None, {}, [args, [*args, '--json']]) for index, args in enumerate(REJECTIONS)],
    ('partial-429', None, {'TWITTER_FAKE_SCENARIO': '429'}, [['home', '--limit', '10', '--json'], '@next']),
    ('partial-429-text', None, {'TWITTER_FAKE_SCENARIO': '429'}, [['home', '--limit', '10']]),
    ('empty', None, {'TWITTER_FAKE_SCENARIO': 'empty'}, [['home', '--json'], ['home'], ['trends', '--json']]),
    ('empty-users', None, {'TWITTER_FAKE_SCENARIO': 'empty_users'},
     [['graph', '@example', 'followers', '--json'], ['graph', '@example', 'following']]),
    ('chain-user', None, {}, [['user', '@example', '--limit', '2', '--json'], '@next', '@next', '@next', '@next']),
    ('chain-user-text', None, {}, [['user', '@example', '--limit', '2'], ['user', '@example', '--limit', '2', '--after', '1']]),
    ('chain-home-following', None, {}, [['home', '--feed', 'following', '--json'], '@next']),
    ('chain-post', None, {}, [['post', '200', '--limit', '1', '--json'], '@next', '@next', '@next']),
    ('chain-graph', None, {}, [['graph', '@example', 'followers', '--limit', '4', '--json'], '@next', '@next']),
    ('chain-search-users', None, {}, [['search', 'x', '--type', 'users', '--limit', '3', '--json'], '@next']),
    ('chain-wrong-context', None, {}, [['user', '@example', '--limit', '2', '--json'],
                                       ['user', '@other', '--limit', '2', '--after', '1', '--json']]),
    ('out-user', None, {}, [['user', '@example', '--limit', '2', '--out', '{tmp}/p.ndjson', '--json'],
                            ['user', '@example', '--limit', '2', '--out', '{tmp}/p.ndjson', '--json'],
                            ['user', '@example', '--limit', '2', '--out', '{tmp}/p.ndjson'],
                            '@file {tmp}/p.ndjson',
                            ['user', '@other', '--out', '{tmp}/p.ndjson', '--json']]),
    ('out-thread', None, {}, [['post', '200', '--limit', '1', '--out', '{tmp}/t.ndjson', '--json'],
                              ['post', '200', '--limit', '1', '--out', '{tmp}/t.ndjson'], '@file {tmp}/t.ndjson']),
    ('out-window', None, {}, [['user', '@example', '--since', '2026-09-01', '--until', '2026-09-06', '--out',
                               '{tmp}/w.ndjson', '--json'], '@file {tmp}/w.ndjson']),
    ('window', None, {}, [['user', '@example', '--since', '2026-09-06', '--json'],
                          ['user', '@example', '--since', '2026-09-01', '--until', '2026-09-06'],
                          ['home', '--feed', 'following', '--until', '2026-09-01', '--json'],
                          ['list', '1', '--since', '2026-01-01T00:00:00Z', '--json']]),
    ('chars', None, {}, [['home', '--chars', '5', '--limit', '1'], ['about', '@example', '--chars', '3'],
                         ['post', '200', '--chars', '4', '--limit', '2']]),
    ('batch-posts', None, {}, [['post', *[str(200 + i) for i in range(25)], '--json']]),
    ('doctor', None, {}, [['doctor'], ['doctor', '--json'], ['doctor', '--unblock']]),
    ('refresh', None, {}, [['refresh'], ['refresh', '--json']]),
    ('blocked', blocked, {}, [['home', '--json'], ['home'], ['doctor', '--json'], ['doctor', '--unblock', '--json'],
                              ['home', '--limit', '1']]),
    ('viewer-changed', other_viewer, {}, [['home', '--limit', '1', '--json'], ['home', '--limit', '1']]),
    ('cold-session', cold, {}, [['user', '@example', '--limit', '1', '--json']]),
]


def seed(home):
    home.mkdir(parents=True)
    (home / 'session.json').write_text(json.dumps({'ct0': 'synthetic', 'viewer_id': '100', 'read_at': time.time()}))
    (home / 'txid.json').write_text(json.dumps({'key_bytes': [1] * 48, 'animation_key': 'synthetic',
                                                'fetched_at': time.time()}))


def default_cli():
    return SCRIPTS / 'cli.py' if (SCRIPTS / 'cli.py').exists() else SCRIPTS / 'twitter.py'


def next_args(command, cli):
    """The arguments of a more: command after its CLI; the prefix must be one this skill has emitted."""
    words = shlex.split(command)
    if words[:3] == ['uv', 'run', str(cli)]:
        return words[3:]
    if words[:2] == ['python3', str(cli)]:
        return words[2:]
    raise SystemExit(f'more: command does not start with this CLI: {command}')


def normalise(text, base):
    text = text.replace(str(base), '<TMP>').replace(str(base.resolve()), '<TMP>')
    text = re.sub(r'("(?:reset_at|observed_at|fetched_at|read_at)": )-?[\d.e+-]+', r'\1<T>', text)
    text = re.sub(r'resets in \d+m', 'resets in <N>m', text)
    text = re.sub(r'Wait until \d+(?:\.\d+)?', 'Wait until <T>', text)
    text = re.sub(r'("(?:registry|txid)_age_days": )[^,}]+', r'\1<AGE>', text)
    text = re.sub(r'((?:registry|txid) age )\S+( days)', r'\1<AGE>\2', text)
    return text


def sort_seen(text):
    """An --out file with each page marker's `seen` list sorted; its order comes from a set."""
    lines = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            lines.append(line)
            continue
        if isinstance(record.get('state'), dict) and isinstance(record['state'].get('seen'), list):
            record['state']['seen'] = sorted(record['state']['seen'])
        lines.append(json.dumps(record, ensure_ascii=False))
    return '\n'.join(lines)


def run_scenario(name, seeder, extra, commands, cli):
    base = Path(tempfile.mkdtemp(prefix='twitter-golden-'))
    home = base / 'home'
    seed(home)
    if seeder:
        seeder(home)
    log = base / 'requests.ndjson'
    environment = {**{k: v for k, v in os.environ.items() if not k.startswith('TWITTER_')},
                   'TWITTER_HOME': str(home), 'TWITTER_ASIDE_BIN': str(FAKE_ASIDE), 'TWITTER_FAKE_LOG': str(log),
                   'TZ': 'UTC', 'PYTHONHASHSEED': '0', **extra}
    lines, last, seen = [], None, 0
    for command in commands:
        if command == '@next':
            if not last or not last.get('next'):
                lines.append('@next: none')
                continue
            args = next_args(last['next'], cli)
            lines.append('@next')
        elif isinstance(command, str) and command.startswith('@file '):
            path = Path(command.split(' ', 1)[1].replace('{tmp}', str(base)))
            lines += ['@file ' + str(path), sort_seen(path.read_text()) if path.exists() else '<missing>']
            continue
        else:
            args = [part.replace('{tmp}', str(base)) for part in command]
        done = subprocess.run([sys.executable, str(cli), *args], capture_output=True, text=True, env=environment,
                              cwd=base, timeout=300)
        requests = log.read_text().splitlines() if log.exists() else []
        lines += ['$ ' + shlex.join(args), f'exit {done.returncode}', done.stdout.rstrip('\n'),
                  f'requests {len(requests) - seen}', *requests[seen:]]
        seen = len(requests)
        try:
            last = json.loads(done.stdout)
        except ValueError:
            last = None
    return normalise('\n'.join(lines) + '\n', base)


def capture(directory, cli):
    directory.mkdir(parents=True, exist_ok=True)
    for name, seeder, extra, commands in SCENARIOS:
        (directory / f'{name}.txt').write_text(run_scenario(name, seeder, extra, commands, cli))
        print(name, file=sys.stderr)
    print(f'captured {len(SCENARIOS)} scenarios with {cli}')


def relocation(text):
    """Equate the two differences an entry-point move may make: the more: prefix and the usage block's program name."""
    count = 0

    def prefix(match):
        nonlocal count
        count += 1
        return '<CLI>'
    text = re.sub(r"""uv run \\?"[^"\\]*/scripts/cli\.py\\?"|python3 '?[^' ]*/scripts/twitter\.py'?""", prefix, text)

    def usage(match):
        nonlocal count
        block = re.sub(r'\s+', ' ', match[0].replace('cli.py', '<PROG>').replace('twitter.py', '<PROG>'))
        count += block != re.sub(r'\s+', ' ', match[0])
        return block
    text = re.sub(r'usage: .*?(?=\n\n|\n[a-z]+ |\Z)', usage, text, flags=re.S)
    return text, count


def compare(before, after, strict):
    names = sorted({p.name for p in before.glob('*.txt')} | {p.name for p in after.glob('*.txt')})
    differing, equated = [], 0
    for name in names:
        left, right = before / name, after / name
        if not left.exists() or not right.exists():
            differing.append(f'{name}: only in {"after" if not left.exists() else "before"}')
            continue
        a, b = left.read_text(), right.read_text()
        if not strict:
            (a, x), (b, y) = relocation(a), relocation(b)
            equated += x + y
        if a != b:
            import difflib
            diff = ''.join(list(difflib.unified_diff(a.splitlines(True), b.splitlines(True), name, name))[:60])
            differing.append(diff)
    print(f'{len(names)} scenarios · {len(differing)} differ · {equated} relocation equivalences applied')
    for item in differing:
        print(item)
    return 1 if differing else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    record = commands.add_parser('capture', help='Record every scenario into a directory.')
    record.add_argument('directory', type=Path, help='Destination; one <scenario>.txt per scenario.')
    record.add_argument('--cli', type=Path, default=None, help='CLI to record; default the skill\'s current entry point.')
    check = commands.add_parser('compare', help='Compare two recordings; exit 1 when any scenario differs.')
    check.add_argument('before', type=Path, help='Earlier recording.')
    check.add_argument('after', type=Path, help='Later recording.')
    check.add_argument('--strict', action='store_true', help='Equate nothing, not even the relocation differences.')
    options = parser.parse_args()
    if options.command == 'capture':
        capture(options.directory, (options.cli or default_cli()).absolute())
    else:
        sys.exit(compare(options.before, options.after, options.strict))
