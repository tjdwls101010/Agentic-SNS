#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Facebook through the logged-in Aside browser."""
import argparse
from dataclasses import dataclass, field
from datetime import date
import json
import os
import re
import shlex
import sys

from facebook.errors import FacebookError
from facebook.reading import dispatch
from facebook.outcome import failure_envelope
from facebook.render import render_page

EXIT_CODES = {
    0: 'success: records, a stop that more: or the same --out command resumes, an already complete --out file, '
       'or a doctor/refresh/schema result',
    2: 'invalid arguments, or a continuation or output file that belongs to another query or an earlier version',
    3: 'Aside is unavailable or returned an invalid response',
    4: 'Facebook login is required',
    5: 'requests are blocked for this account (checkpoint, rate limit or unreadable protection state)',
    6: 'a request failed before any record was read',
    7: 'Facebook explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read, then a request failed; or the budget ran out where reading must restart',
}
# Result kind (facebook.outcome.KINDS) → exit code.
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FacebookError(2, message, 'Run the command with --help.')


class EpilogFormatter(argparse.HelpFormatter):
    """Fill prose paragraphs as usual but keep an indented table's rows on their own lines."""
    def _fill_text(self, text, width, indent):
        return '\n\n'.join(paragraph if paragraph.startswith('  ') or '\n  ' in paragraph
                             else super(EpilogFormatter, self)._fill_text(paragraph, width, indent)
                             for paragraph in text.split('\n\n'))


def positive(value):
    try:
        result = int(value)
        if result > 0:
            return result
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('expected a positive integer')


def budget(value):
    result = positive(value)
    # 성진: 400회 상한은 실계정 보호용, 일회용 계정으로 바꾸면 올려도 됨
    if result > 400:
        raise argparse.ArgumentTypeError('at most 400 requests per invocation')
    return result


def day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('expected a date in YYYY-MM-DD format') from None


# Every option a command may declare: flags and argparse settings, with help a command can override.
OPTIONS = {
    'sort': (('--sort',), {'help': 'Server order'}),
    'limit': (('--limit',), {'type': positive, 'help': 'Records to show; omitted: until the request budget or the end'}),
    'since': (('--since',), {'type': day, 'help': 'Inclusive local start date YYYY-MM-DD'}),
    'until': (('--until',), {'type': day, 'help': 'Inclusive local end date YYYY-MM-DD'}),
    'include_sponsored': (('--include-sponsored',), {'action': 'store_true',
                                                     'help': 'Keep sponsored posts; by default they are skipped and counted'}),
    'replies': (('--replies',), {'action': 'store_true', 'help': 'Expand replies of the selected parents, one request each'}),
    'type': (('--type',), {'choices': ['top', 'posts', 'people', 'pages', 'groups'], 'default': 'top',
                           'help': 'Result category; top mixes posts with people, pages and groups'}),
    'section': (('--section',), {'help': 'Only this locale-independent section, e.g. directory_work'}),
    'chars': (('--chars',), {'type': positive, 'help': 'Characters of each text shown (default 180); JSON keeps full text'}),
    'after': (('--after',), {'type': positive, 'help': 'Continue from the numbered handle a more: line printed'}),
    'out': (('--out',), {'help': 'Collect into this NDJSON file, committed a whole page at a time; '
                                 'rerun the same command to resume. --limit counts everything saved'}),
    'json': (('--json',), {'action': 'store_true', 'help': 'Emit one complete JSON document'}),
    'max_requests': (('--max-requests',), {'type': budget,
                                           'help': 'Facebook requests this invocation may make, setup included '
                                                   '(default 25, at most 400)'}),
}
READ = ('limit', 'since', 'until', 'chars', 'after', 'out', 'json', 'max_requests')


@dataclass(frozen=True)
class Command:
    help: str
    options: tuple = ()
    target: str | None = None
    identity: tuple = ()          # options that make two invocations the same query
    continues_as: str | None = None
    epilog: str | None = None
    overrides: dict = field(default_factory=dict)


COMMANDS = {
    'feed': Command('Read the home feed.', ('sort', 'include_sponsored', *READ),
                    identity=('sort', 'window', 'include_sponsored'),
                    overrides={'sort': {'choices': ['top', 'recent'], 'default': 'top',
                                        'help': 'top is ranked; recent is newest first'}}),
    'profile': Command('Read a profile timeline; --since/--until are applied by Facebook.', READ,
                       target='Facebook profile URL, vanity name or numeric id', identity=('window',)),
    'group': Command('Read a group feed.', ('sort', *READ), target='Facebook group URL, vanity name or numeric id',
                     identity=('sort', 'window'),
                     overrides={'sort': {'choices': ['top', 'recent', 'activity'], 'default': 'top',
                                         'help': 'top and activity are ranked; recent is newest first'}}),
    'post': Command('Read one post in full and its first batch of parent comments.', ('limit', 'json', 'max_requests'),
                    target='Facebook post URL', continues_as='comments',
                    overrides={'limit': {'type': positive, 'help': 'Parent comments to show from the first batch'}}),
    'comments': Command('Read a post\'s parent comments, then replies of the selected parents.',
                        ('sort', 'replies', 'limit', 'chars', 'after', 'out', 'json', 'max_requests'),
                        target='Facebook post URL', identity=('sort', 'replies'),
                        overrides={'sort': {'choices': ['top', 'recent'], 'default': 'top', 'help': 'Comment order'},
                                   'limit': {'type': positive, 'help': 'Parent comments to show; replies are extra'}}),
    'search': Command('Search posts, people, pages or groups.', ('type', 'limit', 'chars', 'after', 'out', 'json',
                                                                'max_requests'),
                      target='Search text', identity=('type',)),
    'about': Command('Read a profile\'s visible About fields.', ('section', 'json', 'max_requests'),
                     target='Facebook profile URL, vanity name or numeric id', identity=('section',),
                     epilog='Reads the overview and every visible collection: 3 + collections requests '
                            '(2 + collections for a numeric id).'),
    'doctor': Command('Check Aside, login, block status and registry age; always JSON.', ('unblock',)),
    'refresh': Command('Replace stale query ids with verified ones from Facebook\'s own pages; always JSON.',
                       ('capture',), epilog='Up to 400 paced requests; this can take several minutes.'),
    'schema': Command('Describe results, output files and record fields; always JSON, no request.', ('object',)),
}
MAINTENANCE = {
    'unblock': (('--unblock',), {'action': 'store_true',
                                 'help': 'Clear a persisted block after checking Facebook in the browser yourself'}),
    'capture': (('--capture',), {'metavar': 'POST_URL', 'help': 'Also capture comment queries by opening this post in '
                                                                 'a browser tab, and feed flags from the home feed'}),
    'object': (('object',), {'nargs': '?', 'choices': ['result', 'out', 'post', 'comment', 'entity', 'about'],
                             'help': 'What to describe; omitted: the list of objects'}),
}
DESTS = sorted({*OPTIONS, *MAINTENANCE, 'target'})


def parser():
    table = '\n'.join(f'  {code}  {meaning}' for code, meaning in EXIT_CODES.items())
    root = Parser(description=__doc__, formatter_class=EpilogFormatter,
                  epilog='Read-only. All invocations share account pacing and block protection.'
                  + '\n\nexit codes:\n' + table)
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    commands = root.add_subparsers(dest='command', required=True)
    for name, command in COMMANDS.items():
        sub = commands.add_parser(name, help=command.help, description=command.help, epilog=command.epilog)
        if command.target:
            sub.add_argument('target', help=command.target)
        for option in command.options:
            flags, settings = OPTIONS.get(option) or MAINTENANCE[option]
            sub.add_argument(*flags, **{**settings, **command.overrides.get(option, {})})
        sub.set_defaults(**{dest: None for dest in DESTS if dest not in command.options and dest != 'target'})
        if not command.target:
            sub.set_defaults(target=None)
    return root


def validate(args):
    for name in ('target', 'section', 'out', 'capture'):
        value = getattr(args, name)
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise FacebookError(2, f'The {name} contains a line break or another control character.',
                                'Pass it on one line.')
    if args.since and args.until and args.since > args.until:
        raise FacebookError(2, '--since must not be later than --until.')
    if args.after and args.out:
        raise FacebookError(2, '--after and --out cannot be combined; --out resumes its own file.',
                            'Rerun the same command with the same --out path.')
    if args.command == 'search' and not args.target.strip():
        raise FacebookError(2, 'Search text must not be empty.')


def context_for(args, name=None):
    """A query's identity from its declaration; the account is filled in once the browser session is known."""
    command = name or args.command
    context = {'command': command, 'target': args.target}
    for key in COMMANDS[command].identity:
        context[key] = {'since': args.since, 'until': args.until} if key == 'window' else getattr(args, key)
    context['account_id'] = None
    return context


def continuation_args(args):
    """post continues as comments on the same post: top order, no replies, a fresh page size."""
    continued = argparse.Namespace(**vars(args))
    continued.command, continued.sort, continued.replies, continued.limit = 'comments', 'top', False, None
    return continued


def invocation():
    """This file's path as it was invoked (links kept), double-quoted the way allowed-tools spells it."""
    path = os.path.abspath(__file__)
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', path) + '"'


def query_words(args):
    """The command, its target, its identity options, then the controls the caller chose."""
    dashed = bool(args.target) and args.target.startswith('-')
    words = [args.command] + ([args.target] if args.target and not dashed else [])
    for key in COMMANDS[args.command].identity:
        if key == 'window':
            words += [w for flag in ('since', 'until') if getattr(args, flag) for w in ('--' + flag, getattr(args, flag))]
        elif getattr(args, key) is True:
            words.append('--' + key.replace('_', '-'))
        elif getattr(args, key) not in (None, False):
            words += ['--' + key.replace('_', '-'), str(getattr(args, key))]
    for key in ('limit', 'chars'):
        if getattr(args, key) is not None:
            words += ['--' + key, str(getattr(args, key))]
    if args.json:
        words.append('--json')
    if args.max_requests is not None:
        words += ['--max-requests', str(args.max_requests)]
    return words


def positional_tail(args):
    """A target that looks like an option goes last, after `--`."""
    return ['--', args.target] if args.target and args.target.startswith('-') else []


def next_command(args, number):
    """The same query from the numbered handle."""
    return invocation() + ' ' + shlex.join(query_words(args) + ['--after', str(number)] + positional_tail(args))


def resume_command(args):
    """The same --out invocation, which picks up where the file ends."""
    return invocation() + ' ' + shlex.join(query_words(args) + ['--out=' + args.out] + positional_tail(args))


def emit(kind, envelope, args):
    """One stdout document: JSON, a one-line --out summary, or the dense text page."""
    if args.json or args.command in ('doctor', 'refresh', 'schema') or (not envelope['results'] and not envelope['ok']
                                                                      and not args.out):
        print(json.dumps(envelope, ensure_ascii=False))
    elif args.out:
        parts = [args.command, f'{envelope.get("count", 0)} saved to {json.dumps(args.out, ensure_ascii=False)}']
        if 'sponsored_skipped' in envelope:
            parts.append(f'sponsored_skipped={envelope["sponsored_skipped"]}')
        parts += [f'stopped={envelope["stop_reason"]}',
                  f'requests={envelope["request_count"]}/{envelope["max_requests"]}']
        if envelope.get('already_complete'):
            parts.append('already complete')
        if envelope['stop_reason'] in ('budget', 'query_failure'):
            parts.append('resume: ' + resume_command(args))
        if envelope.get('error'):
            parts.append(f'error={envelope["error"]} fix={envelope["fix"]}')
        print(' · '.join(parts))
    else:
        print(render_page(envelope, chars=args.chars or (None if args.command == 'post' else 180)))
    return KIND_EXIT[kind]


def main(argv=None):
    args = None
    try:
        args = parser().parse_args(argv)
        validate(args)
        dispatch.prepare(args)
        context = continuation = None
        if args.command not in ('doctor', 'refresh', 'schema'):
            context = context_for(args)
            if COMMANDS[args.command].continues_as:
                continuation = context_for(continuation_args(args), COMMANDS[args.command].continues_as)
        identity = {key: getattr(args, key) for key in ('sort', 'type', 'section') if getattr(args, key) is not None}
        kind, envelope = dispatch.run(args, context=context, continuation=continuation, identity=identity)
        handle = envelope.pop('handle', None)
        if handle:
            continued = continuation_args(args) if handle['command'] != args.command else args
            envelope['next'] = next_command(continued, handle['number'])
        return emit(kind, envelope, args)
    except FacebookError as error:
        envelope = failure_envelope(error)
    except OSError:
        envelope = failure_envelope(FacebookError(6, 'Could not read or write local state.',
                                                  'Check the Facebook cache directory and the --out path.'))
    print(json.dumps(envelope, ensure_ascii=False))
    return KIND_EXIT[envelope['error']]


if __name__ == '__main__':
    sys.exit(main())
