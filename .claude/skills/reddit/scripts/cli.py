#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Reddit through the logged-in Aside browser: feeds, communities, posts and comment trees, people, search."""
import argparse
import json
import os
import re
import shlex
import sys
from datetime import date, datetime, time, timedelta

from reddit import maintenance
from reddit.errors import RedditError
from reddit.render import render_page, render_summary
from reddit.results import failure_envelope

EXIT_CODES = {
    0: 'success: records, a stop that more: or the same --out command resumes (budget, Reddit\'s window spent), an '
       'already complete --out file, or a doctor/schema result',
    2: 'invalid arguments, or a handle or --out file that belongs to another query, an earlier version or has expired',
    3: 'Aside is unavailable, timed out or answered invalidly, or which Aside account to use is unclear',
    4: 'Reddit login is required in the Aside browser, or it is logged in to another Reddit account than a '
       'continuation was read with',
    5: 'requests are blocked for this account (browser challenge, rate limit, or unreadable protection state)',
    6: 'a request failed before any record was read (including a response shape this skill does not know)',
    7: 'Reddit explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or the budget ran out with nothing to continue from',
    9: 'the target cannot be read by this account: missing, private, quarantined, banned, suspended, or a profile '
       'whose history is not visible — retrying does not change it',
}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9}

REQUESTS = ('how requests are counted and paced: every page, post read, comment expansion, redirect and share-link '
            'hop counts, and so does the account check (/api/me.json, 1 request) that a command reading something it '
            'can continue (more: or --out) makes first. Requests are spaced 1-2 s apart across every invocation of '
            'the account, longer when Reddit says its ten-minute window is running low, so N requests take at least '
            'N to 2N seconds. A command never waits out Reddit\'s window: when the bucket it needs is spent it stops '
            '(stopped=window_spent) and more: resumes after the reset the first line shows.')
TEXT_OUTPUT = ('output: first line "<command> · … · N shown · stopped=<reason> · requests=<used>/<budget> · reddit '
               'window <left>/<limit>, resets in <s>s"; dated reads add "window <since>..<until> <tz> · <coverage>"; '
               'then one record per [p1]/[c1]/[s1]/[u1] label, each ending with the URL that names it alone '
               '(post <url>, comments <url>, r/ and u/ names for about and profile); text is shown as '
               'text[N of M chars shown] with > quotes as ❝…❞; then coverage: lines; last, more: <command> when '
               'reading can continue.')
JSON_OUTPUT = ('--json: one JSON envelope instead (ok, command, stop_reason, request_count, max_requests, '
               'reddit_window, account, coverage, next, error, message, fix, results with full texts); schema result '
               'describes every field.')
OUT_OUTPUT = ('--out FILE: records go to an NDJSON file a whole page at a time and stdout gets one summary line (one '
              'JSON object with --json); rerun the same command with the same file to resume. --out cannot be '
              'combined with --after. The file holds other people\'s posts and comments: keep it outside the '
              'repository.')
FAILURE = ('failure: one JSON envelope (ok false, error, message, fix) when nothing was read; records read before a '
           'failure print as usual, followed by a "coverage: incomplete — <message> fix: <fix>" line (with --json, '
           'in the envelope).')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RedditError(2, message, f'Run {self.prog} --help.')


def positive(value):
    if value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    raise argparse.ArgumentTypeError('expected a positive integer')


def count(value):
    if value.isascii() and value.isdigit():
        return int(value)
    raise argparse.ArgumentTypeError('expected 0 or a positive integer')


def budget(value):
    number = positive(value)
    # 성진: 호출당 100회 상한은 실계정 보호용(R7) — Reddit의 일반 버킷 하나(10분 100)를 넘지 않게. 일회용 계정이면 올려도 됨
    if number > 100:
        raise argparse.ArgumentTypeError('at most 100 requests per invocation')
    return number


def day(value):
    try:
        found = date.fromisoformat(value)
        for edge in (found, found + timedelta(days=1)):  # a window's bounds are local midnights, the day after included
            datetime.combine(edge, time()).astimezone().timestamp()
        return found.isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('expected a date as YYYY-MM-DD') from None
    except (OverflowError, OSError):
        raise argparse.ArgumentTypeError('expected a date this computer can turn into a local time') from None


OPTIONS = {
    'limit': (('--limit',), {'type': positive, 'help': 'Records to show (default: one page of 25); with --out, records to save'}),
    'since': (('--since',), {'type': day, 'metavar': 'DAY', 'help': 'First local day to include, YYYY-MM-DD (only with --sort new)'}),
    'until': (('--until',), {'type': day, 'metavar': 'DAY', 'help': 'Last local day to include, YYYY-MM-DD (only with --sort new)'}),
    'chars': (('--chars',), {'type': count, 'help': 'Characters of each text to show (default 180; 0 = all received); --json and --out keep all'}),
    'after': (('--after',), {'type': positive, 'metavar': 'HANDLE', 'help': 'Continue from the numbered handle a more: line printed'}),
    'out': (('--out',), {'metavar': 'FILE', 'help': 'Collect into this NDJSON file, one committed page at a time; rerun the same command to resume'}),
    'json': (('--json',), {'action': 'store_true', 'help': 'Print one JSON envelope instead of text'}),
    'max_requests': (('--max-requests',), {'type': budget, 'default': 25, 'metavar': 'N', 'help': 'Requests this invocation may make (default 25, at most 100)'}),
}
LIST = ('limit', 'chars', 'after', 'out', 'json', 'max_requests')
WINDOW = ('since', 'until')

COMMANDS = {
    'doctor': {
        'help': 'Check Aside, the Reddit login and account protection; always JSON.',
        'run': maintenance.doctor,
        'arguments': [(('--unblock',), {'action': 'store_true', 'help': 'Only after a person has checked Reddit in the Aside browser (and solved any challenge there): make one check and lift a saved challenge if Reddit answers normally'})],
        'epilog': ['requests: 1 (/api/me.json, the login check). A saved block is reported as exit 5 without any request.',
                   'output: one JSON envelope; results[0] holds aside_account (the Aside account used: REDDIT_ASIDE_ACCOUNT, or the one `aside account status` marks active), reddit_account (who the browser is logged in to Reddit as), blocked and block_reason, buckets (each of Reddit\'s request buckets this account has used: remaining, limit, resets_in, rate_limited_for, wait_seconds), requests_last_hour and requests_last_day (every command of this Aside account, logged), data_dir, snapshot_bytes, protection_state and holds_personal_data.',
                   '--unblock keeps the block while it checks: one /api/me.json request. Only a clean answer lifts a challenge; a challenge again, a logged-out answer or an interrupted run leaves it. A bucket\'s rate limit or spent window is never lifted: it ends at Reddit\'s reset. It means nothing unless a person has looked at Reddit in the Aside browser first.'],
        'exits': (0, 2, 3, 4, 5, 6),
    },
    'schema': {
        'help': 'Describe results, files and record fields; always JSON, no request.',
        'run': maintenance.schema,
        'arguments': [(('object',), {'nargs': '?', 'choices': maintenance.SCHEMA_OBJECTS, 'help': 'What to describe; omitted: the list of objects'})],
        'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, stop reasons, exit codes, window coverage, request counting and the text page; out: the --out file; post, comment, subreddit, user: record fields), or one line per object.'],
        'exits': (0, 2),
    },
}
READS = ()


def epilog(name, spec):
    lines = list(spec['epilog'])
    if name in READS:
        lines += [REQUESTS, TEXT_OUTPUT, JSON_OUTPUT]
        if 'out' in [a for a in spec['arguments'] if isinstance(a, str)]:
            lines.append(OUT_OUTPUT)
        lines.append(FAILURE)
    lines.append('exit codes:\n' + '\n'.join(f'  {code}  {EXIT_CODES[code]}' for code in spec['exits']))
    return '\n\n'.join(lines)


def parser():
    root = Parser(prog='cli.py', description=__doc__, formatter_class=argparse.RawTextHelpFormatter,
                  epilog='Read-only. Run <command> --help for its arguments, output, requests and exit codes; schema '
                         'describes every output field.\n\nexit codes:\n'
                         + '\n'.join(f'  {code}  {meaning}' for code, meaning in EXIT_CODES.items()))
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    commands = root.add_subparsers(dest='command', required=True, metavar='<command>')
    for name, spec in COMMANDS.items():
        sub = commands.add_parser(name, help=spec['help'], description=spec['help'], epilog=epilog(name, spec),
                                  formatter_class=argparse.RawTextHelpFormatter, prog=f'cli.py {name}')
        for argument in spec['arguments']:
            flags, settings = OPTIONS[argument] if isinstance(argument, str) else argument
            sub.add_argument(*flags, **settings)
    return root


def validate(options):
    for key in ('target', 'out', 'text', 'within'):
        value = options.get(key)
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise RedditError(2, f'The {key} contains a line break or another control character.', 'Pass it on one line.')
    if options.get('since') and options.get('until') and options['since'] > options['until']:
        raise RedditError(2, '--since must not be later than --until.', 'Swap the two dates.')
    if (options.get('since') or options.get('until')) and options.get('sort') not in (None, 'new'):
        raise RedditError(2, 'A date window needs --sort new: other orders are rankings, not a timeline.',
                          'Use --sort new with --since/--until, or --time for a ranking\'s server period.')
    if options.get('after') and options.get('out'):
        raise RedditError(2, '--after and --out cannot be combined; --out resumes its own file.',
                          'Rerun the same command with the same --out path.')


def invocation():
    """This file as it was invoked, double-quoted the way the skill's allowed-tools spells it."""
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', os.path.abspath(__file__)) + '"'


def command_line(words):
    return invocation() + ' ' + shlex.join(words)


def emit(kind, envelope, options):
    if isinstance(envelope.get('next'), list):
        envelope['next'] = command_line(envelope['next'])
    machine = options.get('json') or options['command'] in ('doctor', 'schema')
    if options.get('out') and envelope.get('out') is not None and (envelope['ok'] or envelope.get('count')):
        print(json.dumps({k: v for k, v in envelope.items() if k != 'results'}, ensure_ascii=False) if machine
              else render_summary(envelope))
    elif machine or (not envelope['ok'] and not envelope.get('results')):
        print(json.dumps(envelope, ensure_ascii=False))
    else:
        print(render_page(envelope, chars=options.get('chars'), command=options['command']))
    return KIND_EXIT[kind]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    options = {'command': None}
    try:
        options = vars(parser().parse_args(argv))
        validate(options)
        if options['command'] == 'schema':
            options['exit_codes'] = [(code, meaning, [k for k, c in KIND_EXIT.items() if c == code])
                                     for code, meaning in EXIT_CODES.items()]
        kind, envelope = COMMANDS[options['command']]['run'](options)
    except RedditError as error:
        kind, envelope = failure_envelope(error, options.get('command'))
    return emit(kind, envelope, options)


if __name__ == '__main__':
    sys.exit(main())
