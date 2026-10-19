#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read X (Twitter) through the logged-in Aside browser, read-only."""
import argparse
import json
import os
import re
import shlex
import sys

from twitter import maintenance
from twitter.errors import TwitterError
from twitter.results import failure_envelope

EXIT_CODES = {
    0: 'success: records, a stop that more: (or the same --out command) resumes, an already complete --out file, or '
       'a doctor/schema result',
    2: 'invalid arguments, or a handle or --out file that belongs to another query, an earlier version or has expired',
    3: 'Aside or the browser tab is unavailable, timed out or answered invalidly',
    4: 'X login is required in the Aside browser (or it changed accounts mid-command)',
    5: 'requests are blocked until a person clears it (a lock or a challenge), or protection state is unreadable',
    6: 'a request failed before any record was read (a read X no longer accepts, or the time limit)',
    7: 'X explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or a stop could not save where to continue',
    9: 'the target cannot be read by this account: deleted, suspended, protected and not followed, or never existed',
    10: 'X\'s limit for this operation ran out before any record: not an account problem, other commands still work',
}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9, 'rate_limited': 10}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TwitterError(2, message, f'Run {self.prog} --help.')


COMMANDS = {
    'doctor': {
        'help': 'Check Aside, the browser tab, login, account protection and X\'s limits; always JSON.',
        'run': maintenance.doctor,
        'arguments': [(('--unblock',), {'action': 'store_true', 'help': 'Only after a person has checked x.com in the '
                                        'Aside browser: make one check and lift a saved block if X answers normally'})],
        'epilog': ['It opens the dedicated x.com tab if none is open (about 14 requests the page makes itself, measured; '
                   '20 when they cannot be measured) and otherwise makes no request.',
                   'output: one JSON envelope; results[0] holds aside, tab {target_id, opened_now, reopened, '
                   'opening_measured}, login, account_id (the X account in use), blocked and block_reason, limits (X\'s '
                   'per-operation limits seen and not yet reset: {limit, remaining, reset}), requests_last_hour and '
                   'requests_last_day (every command of this account, logged), operations (what the tab\'s app '
                   'defines), signature_generator, bearer, own_request_matching (whether the skill\'s own requests are '
                   'told apart in the tab\'s timing list), idle_close_seconds, data_dir, protection_state and '
                   'holds_personal_data. A saved block is reported as exit 5 without touching the browser.',
                   'The tab is closed about 5 minutes after the last command, which stops the app\'s own polling; set '
                   'TWITTER_IDLE_SECONDS to change the delay, or to off to leave it open. TWITTER_ASIDE_ACCOUNT picks '
                   'the Aside account (default: Aside\'s own).',
                   '--unblock keeps the block while it checks: the tab\'s login and one Viewer read (one request, '
                   'outside any budget, inside X\'s Viewer limit). Only an answer for the account the block was '
                   'recorded for lifts it; anything else leaves it and exits 5 with verification_reason '
                   '(rate_limited, logged_out, account_mismatch, moved, time_limit, aside). Per-operation limits are '
                   'never cleared by it. It means nothing unless a person has looked at x.com in the Aside browser '
                   'first.'],
        'exits': (0, 2, 3, 4, 5, 6),
    },
    'schema': {
        'help': 'Describe results, files and record fields; always JSON, no request.',
        'run': maintenance.schema,
        'arguments': [(('object',), {'nargs': '?', 'choices': maintenance.SCHEMA_OBJECTS,
                                     'help': 'What to describe; omitted: the list of objects'})],
        'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, stop '
                   'reasons, exit codes, window coverage, request counting and the text page; out: the --out file; '
                   'post, account, trend: record fields), or one line per object.'],
        'exits': (0, 2),
    },
}
HIDDEN = {'idle': {'run': maintenance.idle,
                   'arguments': [(('--token',), {'required': True}), (('--after',), {'type': int, 'default': 300})]}}


def epilog(name, spec):
    lines = list(spec['epilog'])
    lines.append('exit codes:\n' + '\n'.join(f'  {code}  {EXIT_CODES[code]}' for code in spec['exits']))
    return '\n\n'.join(lines)


def parser(hidden=False):
    root = Parser(prog='cli.py', description=__doc__, formatter_class=argparse.RawTextHelpFormatter,
                  epilog='Run <command> --help for its arguments, output, requests and exit codes; schema describes '
                         'every output field.\n\nexit codes:\n'
                         + '\n'.join(f'  {code}  {meaning}' for code, meaning in EXIT_CODES.items()))
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    commands = root.add_subparsers(dest='command', required=True, metavar='<command>')
    for name, spec in COMMANDS.items():
        sub = commands.add_parser(name, help=spec['help'], description=spec['help'], epilog=epilog(name, spec),
                                  formatter_class=argparse.RawTextHelpFormatter, prog=f'cli.py {name}')
        for flags, settings in spec['arguments']:
            sub.add_argument(*flags, **settings)
    if hidden:  # the idle cleanup the skill starts itself; not part of the help
        for name, spec in HIDDEN.items():
            sub = commands.add_parser(name, prog=f'cli.py {name}')
            for flags, settings in spec['arguments']:
                sub.add_argument(*flags, **settings)
    return root


def invocation():
    """This file as it was invoked, double-quoted the way the skill's allowed-tools spells it."""
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', os.path.abspath(__file__)) + '"'


def command_line(words):
    return invocation() + ' ' + shlex.join(words)


def emit(kind, envelope, options):
    if isinstance(envelope.get('next'), list):
        envelope['next'] = command_line(envelope['next'])
    print(json.dumps(envelope, ensure_ascii=False))
    return KIND_EXIT[kind]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    options = {'command': None}
    try:
        options = vars(parser(hidden=bool(argv) and argv[0] in HIDDEN).parse_args(argv))
        if options['command'] == 'schema':
            options['exit_codes'] = [(code, meaning, [k for k, c in KIND_EXIT.items() if c == code])
                                     for code, meaning in EXIT_CODES.items()]
        spec = COMMANDS.get(options['command']) or HIDDEN[options['command']]
        kind, envelope = spec['run'](options)
    except TwitterError as error:
        kind, envelope = failure_envelope(error, options.get('command'))
    return emit(kind, envelope, options)


if __name__ == '__main__':
    sys.exit(main())
