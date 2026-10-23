#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read social networks through the logged-in Aside browser: X, Threads, Reddit, Facebook, Naver Blog. Read-only."""
import argparse
import importlib
import importlib.util
import json
import sys
from datetime import date, datetime, time, timedelta

from sns.clock import Deadline
from sns.errors import SnsError
from sns.maintenance import objects, schema
from sns.reading import Invocation, doctor, foreign, idle
from sns.render import page, summary
from sns.results import failure_envelope

PLATFORM_PACKAGES = ('x', 'threads', 'reddit', 'facebook', 'naver_blog')

# The one table from a result's kind to its exit code (units raise kinds, never numbers).
EXIT_CODES = {
    0: 'success: records; a stop that more: (or the same --out command) resumes; an --out file already final; '
       'doctor or schema',
    2: 'invalid arguments, or a handle or --out file of another command, an earlier version or expired, or a URL of '
       'another platform (fix names the command that reads it)',
    3: 'Aside or the browser tab is unavailable, timed out or answered invalidly',
    4: 'login is required in the Aside browser, or the platform account changed',
    5: 'blocked: a checkpoint, challenge, lock or network block a person must clear, an account-wide rate limit before '
       'any record (it passes at the time given), or unreadable protection state',
    6: 'a request failed before any record was read (a changed answer, or the time limit)',
    7: 'the platform explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or a stop could not save where to continue',
    9: 'the target cannot be read by this account: deleted, private, suspended or never existed',
    10: 'a named limit (an X operation, a Reddit bucket) ran out before any record: not an account problem, other '
        'commands still work, the message gives the time',
}
# The same table in a word or two, for the top-level map; each command's --help gives the full meaning.
EXIT_SUMMARY = {0: 'success, or a stop more: resumes', 2: 'bad arguments, handle, --out file or platform',
                3: 'Aside or the browser tab failed', 4: 'login needed, or the account changed',
                5: 'blocked (a person must clear it), or rate-limited before any record',
                6: 'a request failed before any record', 7: 'explicitly nothing', 8: 'partial',
                9: 'not readable by this account', 10: 'a named limit ran out before any record'}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9, 'scope_limit': 10}

TEXT_OUTPUT = ('output: a first line "<platform> <command> · … · N shown · stopped=<reason> · requests=<n>" (plus the '
               'cost of opening a tab, and a limit that stopped it or runs low); dated reads add "window '
               '<since>..<until> <zone> · <coverage>"; then one block per record, each ending with the arguments of '
               'the next command; then coverage: lines; last, more: <command> when reading can continue. Text is '
               'shown as text[N of M chars shown].')
JSON_OUTPUT = '--json: one JSON envelope instead, with full texts; <platform> schema result describes every field.'
OUT_OUTPUT = ('--out FILE: records go to an NDJSON file a whole page at a time (so it can hold a little more than '
              '--limit) and stdout gets one summary line; rerun the same command with the same file to resume. Its '
              'directory must exist, and it cannot be inside the skill\'s data/. The file holds other people\'s '
              'posts: keep it outside the repository.')
FAILURE = ('failure: one JSON envelope (ok false, error, message, fix) when nothing was read; records read before a '
           'failure print as usual, followed by "coverage: incomplete — <message> fix: <fix>".')
REQUESTS = ('requests: there is no request budget; a command ends at its natural end, at --limit, at a platform\'s '
            'limit or block, or at its time limit (about 100 seconds, so it finishes inside two minutes), and more: '
            'continues. Every invocation of an account shares one lock and the platform\'s pacing.')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SnsError('argument', message, f'Run {self.prog} --help.')


def positive(value):
    if value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    raise argparse.ArgumentTypeError('expected a positive integer')


def chars(value):
    if value.isascii() and value.isdigit():
        return int(value)
    raise argparse.ArgumentTypeError('expected 0 (full text) or a positive integer')


def day(value):
    try:
        found = date.fromisoformat(value)
        for edge in (found, found + timedelta(days=1)):  # a window's bounds are midnights, the day after included
            datetime.combine(edge, time()).astimezone().timestamp()
        return found.isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('expected a date as YYYY-MM-DD') from None
    except (OverflowError, OSError):
        raise argparse.ArgumentTypeError('expected a date this computer can turn into a time') from None


def _zone(platform):
    return 'Korea time (KST)' if getattr(platform.window, 'tz', None) is not None else 'this computer\'s time zone'


def option(name, platform):
    """A shared option: (flags, settings)."""
    return {
        'limit': (('--limit',), {'type': positive, 'help': 'How many to show (with --out: to save); what one counts '
                                                           'and the default are in the description below'}),
        'since': (('--since',), {'type': day, 'metavar': 'DAY', 'help': f'First day to include, YYYY-MM-DD, in '
                                                                        f'{_zone(platform)}'}),
        'until': (('--until',), {'type': day, 'metavar': 'DAY', 'help': f'Last day to include, YYYY-MM-DD, in '
                                                                        f'{_zone(platform)}'}),
        'chars': (('--chars',), {'type': chars, 'help': 'Characters of each text to show (default 180; 0 = all '
                                                         'received); --json and --out keep all'}),
        'after': (('--after',), {'type': positive, 'metavar': 'HANDLE', 'help': 'Continue from the numbered handle a '
                                                                                'more: or replies line printed'}),
        'out': (('--out',), {'metavar': 'FILE', 'help': 'Collect into this NDJSON file one committed page at a time; '
                                                        'rerun the same command to resume; cannot be combined with '
                                                        '--after'}),
        'json': (('--json',), {'action': 'store_true', 'help': 'Print one JSON envelope instead of text'}),
    }[name]


def shared_commands(platform):
    """doctor and schema, which every platform has."""
    return {
        'doctor': {
            'help': f'Check Aside, the browser, {platform.title} login and account protection; always JSON.',
            'run': lambda invocation: doctor(platform, invocation),
            'arguments': [(('--unblock',), {'action': 'store_true',
                                            'help': f'Only after a person has checked {platform.site} in the Aside '
                                                    'browser and cleared what it showed: make one check and lift a '
                                                    'saved block if the answer is normal'})],
            'epilog': [f'output: one JSON envelope; results[0] holds aside, aside_account, login, viewer (the '
                       f'{platform.title} account in use), blocked, block_reason, hold_until, limits, '
                       'requests_last_hour and requests_last_day (every command of this account), idle_seconds, '
                       'data_dir, protection_state, holds_personal_data and the platform\'s own checks. A saved block '
                       'is reported as exit 5 without touching the browser.',
                       '--unblock keeps the block while it checks with one request; only an answer for the account '
                       'the block was recorded for lifts it, and anything else leaves it (exit 5 with '
                       'verification_reason). '
                       + ('When the dedicated tab is gone, opening it is the check (the site loads as when a person '
                          'opens it, and its first look is judged) and nothing more is sent. '
                          if platform.transport == 'tab' else '')
                       + 'A rate limit (a hold, or a limit on one operation or bucket) is never '
                       'lifted by it: it passes at its time. It means nothing unless a person has looked at the site '
                       'in the Aside browser first. SNS_ASIDE_ACCOUNT (or SNS_ASIDE_ACCOUNT_<PLATFORM>) picks the '
                       'Aside account; SNS_IDLE_SECONDS sets when an unused dedicated tab is emptied (default 300, '
                       'off to keep it).'],
            'exits': (0, 2, 3, 4, 5, 6, 10),
        },
        'schema': {
            'help': 'Describe results, --out files and record fields; always JSON, no request.',
            'run': lambda invocation: schema(platform, invocation),
            'arguments': [(('object',), {'nargs': '?', 'choices': objects(platform),
                                         'help': 'What to describe; omitted: the list of objects'})],
            'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, '
                       'stop reasons, kinds, exit codes and window coverage; out: the --out file; the others: record '
                       'fields), or one line per object.'],
            'exits': (0, 2),
        },
    }


def epilog(spec):
    lines = list(spec.get('epilog') or [])
    names = [a for a in spec['arguments'] if isinstance(a, str)]
    if spec.get('reads', True) and 'json' in names:
        lines += [REQUESTS, TEXT_OUTPUT, JSON_OUTPUT]
        if 'out' in names:
            lines.append(OUT_OUTPUT)
        lines.append(FAILURE)
    lines.append('exit codes:\n' + '\n'.join(f'  {code}  {EXIT_CODES[code]}' for code in spec['exits']))
    return '\n\n'.join(lines)


def load_platforms():
    """The platform packages that exist, as {word: module}; each exports PLATFORM, COMMANDS and CHOICES."""
    found = {}
    for name in PLATFORM_PACKAGES:
        if importlib.util.find_spec(f'sns.{name}') is not None:
            module = importlib.import_module(f'sns.{name}')
            found[module.PLATFORM.word] = module
    return found


def surface(module):
    """A platform's commands with the shared ones after them."""
    return {**module.COMMANDS, **shared_commands(module.PLATFORM)}


def parser(platforms, hidden=False):
    lines = [f'  {word:<11} {" ".join(surface(module))}' for word, module in platforms.items()]
    root = Parser(prog='cli.py', usage='cli.py [--verbose] <platform> <command> [options]', description=__doc__,
                  formatter_class=argparse.RawTextHelpFormatter, add_help=True,
                  epilog='platforms and their commands (cli.py <platform> <command> --help explains one):\n'
                         + '\n'.join(lines) + '\n\nA URL of another platform is refused with the command that reads '
                         'it. Every result ends with the\nnext command (more:, replies <handle>, post <url>); '
                         '<platform> schema describes every field.\n\nexit codes:\n'
                         + '\n'.join(f'  {code:<2} {meaning}' for code, meaning in EXIT_SUMMARY.items()))
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    branches = root.add_subparsers(dest='platform', required=True, metavar='<platform>', help=argparse.SUPPRESS)
    for word, module in platforms.items():
        platform = module.PLATFORM
        commands = surface(module)
        branch = branches.add_parser(word, prog=f'cli.py {word}', formatter_class=argparse.RawTextHelpFormatter,
                                     description=f'{platform.title}: its commands. Run cli.py {word} <command> '
                                                 '--help for one.')
        leaves = branch.add_subparsers(dest='command', required=True, metavar='<command>')
        for name, spec in commands.items():
            leaf = leaves.add_parser(name, help=spec['help'], description=spec['help'], epilog=epilog(spec),
                                     formatter_class=argparse.RawTextHelpFormatter, prog=f'cli.py {word} {name}')
            for argument in spec['arguments']:
                flags, settings = option(argument, platform) if isinstance(argument, str) else argument
                leaf.add_argument(*flags, **settings)
        if hidden:  # the idle cleanup the skill starts itself; not part of the help
            leaf = leaves.add_parser('idle', prog=f'cli.py {word} idle')
            leaf.add_argument('--account', required=True)
            leaf.add_argument('--token', required=True)
            leaf.add_argument('--after', type=int, default=300)
    return root


def validate(options, spec):
    for key in ('target', 'out'):
        values = options.get(key)
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise SnsError('argument', f'The {key} contains a line break or another control character.',
                               'Pass it on one line.')
    if options.get('since') and options.get('until') and options['since'] > options['until']:
        raise SnsError('argument', '--since must not be later than --until.', 'Swap the two dates.')
    if options.get('after') and options.get('out'):
        raise SnsError('argument', '--after and --out cannot be combined; --out resumes its own file.',
                       'Rerun the same command with the same --out path.')
    if spec.get('check'):
        spec['check'](options)


def emit(kind, envelope, options, module):
    machine = options.get('json') or options.get('command') in ('doctor', 'schema', 'idle') or module is None
    if options.get('out') and envelope.get('out') is not None and (envelope['ok'] or envelope.get('count')):
        print(json.dumps({k: v for k, v in envelope.items() if k != 'results'}, ensure_ascii=False) if machine
              else summary(envelope))
    elif machine or (not envelope['ok'] and not envelope.get('results') and not envelope.get('sections')):
        print(json.dumps(envelope, ensure_ascii=False))
    else:
        drawn = module.PLATFORM.render(envelope, options.get('chars'), options['command'])
        lines, shown = drawn if isinstance(drawn, tuple) else (drawn, None)
        print(page(envelope, lines, shown))
    return KIND_EXIT[kind]


def main(argv=None, platforms=None):
    deadline = Deadline()  # the invocation's one deadline, made first: everything after it fits inside
    argv = sys.argv[1:] if argv is None else argv
    platforms = load_platforms() if platforms is None else platforms
    options, module = {'command': None}, None
    try:
        hidden = len(argv) >= 2 and argv[1] == 'idle'
        options = vars(parser(platforms, hidden=hidden).parse_args(argv))
        module = platforms[options['platform']]
        if options['command'] == 'idle':
            outcome = idle(module.PLATFORM, Invocation(options, deadline, platforms, cli_path()), options['account'],
                           options['token'], options['after'])
            print(json.dumps({'ok': True, 'command': 'idle', 'outcome': outcome}))
            return 0
        spec = surface(module)[options['command']]
        validate(options, spec)
        exit_codes = [(code, meaning, [k for k, c in KIND_EXIT.items() if c == code])
                      for code, meaning in EXIT_CODES.items()]
        invocation = Invocation(options, deadline, {w: m.PLATFORM for w, m in platforms.items()}, cli_path(),
                                exit_codes)
        foreign(module.PLATFORM, invocation, options.get('target'))  # another platform's link: name its command
        kind, envelope = spec['run'](invocation)
    except SnsError as error:
        kind, envelope = failure_envelope(error, module.PLATFORM.key if module else None, options.get('command'))
    return emit(kind, envelope, options, module)


def cli_path():
    return __file__


if __name__ == '__main__':
    sys.exit(main())
