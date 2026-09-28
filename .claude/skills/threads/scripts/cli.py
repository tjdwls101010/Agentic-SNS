#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Threads through the account logged in to Aside (u0); read-only, cookies stay in the browser."""
import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from threads.errors import ThreadsError
from threads.output.render import render
from threads.output.schema import schema
from threads.reading import listing, maintenance, post, profile
from threads.reading.common import resolve_target
from threads.reading.window import MESSAGE as DATE_MESSAGE, moment

EXIT_CODES = {
    0: 'success, including a stop that more: resumes and an --out file already complete',
    2: 'invalid arguments, or a continuation or --out file that belongs to another query',
    3: 'Aside is unavailable or returned an invalid response',
    4: 'Threads login is required',
    5: 'requests are blocked for this account (checkpoint, rate limit, full local window)',
    6: 'a request failed before any record was read',
    7: 'Threads returned nothing for this target or window',
    8: 'partial: records were read, then a request failed or the request cap was reached',
    9: 'the post or profile is unavailable (deleted, private, or a post that redirected away)',
}
MAX_REQUESTS = 40


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ThreadsError(2, message)


class EpilogFormatter(argparse.HelpFormatter):
    """Fill prose paragraphs as usual but keep an indented table's rows on their own lines."""
    def _fill_text(self, text, width, indent):
        return '\n\n'.join(paragraph if '\n  ' in paragraph or paragraph.startswith('  ')
                           else super(EpilogFormatter, self)._fill_text(paragraph, width, indent)
                           for paragraph in text.split('\n\n'))


def positive(value):
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('expected a positive integer')


def chars(value):
    try:
        number = int(value)
        if number >= 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('expected 0 (full text) or a positive integer')


def requests(value):
    number = positive(value)
    # 성진: 40 per command protects the real account; the shared 10-minute window (120) still applies across commands.
    if number > MAX_REQUESTS:
        raise argparse.ArgumentTypeError(f'at most {MAX_REQUESTS} requests per command')
    return number


def when(value):
    try:
        moment(value)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(DATE_MESSAGE) from None
    return value


# Every option a command may declare: flags and argparse settings, with help a command can override.
OPTIONS = {
    'feed': (('--feed',), {'choices': ['foryou', 'following'], 'help': 'foryou (default) or following'}),
    'tab': (('--tab',), {'choices': ['threads', 'replies', 'reposts', 'media'],
                         'help': 'Profile tab (default: the tab in the URL, else threads)'}),
    'sort': (('--sort',), {'choices': ['top', 'recent'], 'help': 'Post ranking (default top)'}),
    'type': (('--type',), {'choices': ['posts', 'users'], 'help': 'posts (default) or users: one batch of account cards'}),
    'tag': (('--tag',), {'action': 'store_true', 'help': 'Search posts under this tag instead of by text'}),
    'since': (('--since',), {'type': when, 'help': 'Keep posts written at or after this ISO date/time (UTC unless an '
                                                    'offset is given). Filtered locally'}),
    'until': (('--until',), {'type': when, 'help': 'Keep posts written before this ISO date/time. Filtered locally'}),
    'limit': (('--limit',), {'type': positive, 'help': 'Records to show (default 10); the request cap stays '
                                                       '--max-requests'}),
    'chars': (('--chars',), {'type': chars, 'help': 'Text output only: preview length of each text (default 180, '
                                                    '0 = full). JSON always has full text'}),
    'out': (('--out',), {'help': 'Collect into this private NDJSON file, committed a page at a time; rerun the same '
                                 'command with the same file to resume'}),
    'after': (('--after',), {'type': positive, 'help': 'Continue from the numbered handle a more: line printed'}),
    'json': (('--json',), {'action': 'store_true', 'help': 'Emit one JSON document instead of text'}),
    'max_requests': (('--max-requests',), {'type': requests, 'help': 'Threads requests this command may make, its '
                                                                     'route page included (default 10, at most 40)'}),
    'unblock': (('--unblock',), {'action': 'store_true', 'help': 'After checking Threads in Aside yourself, make one '
                                                                'login probe; a checkpoint is cleared only if it succeeds'}),
    'capture': (('--capture',), {'action': 'store_true', 'help': 'Also open one Threads app tab to observe the queries '
                                                                'only the app loads (ask the user first); needs --post'}),
    'post': (('--post',), {'help': 'A public post URL: the page whose decoding is checked, and the tab --capture opens'}),
}
READ = ('limit', 'chars', 'out', 'after', 'json', 'max_requests')
# The order a query's identity is written in: continuation handles and --out headers compare it.
IDENTITY = ('target', 'feed', 'tab', 'sort', 'query', 'type', 'tag', 'relation', 'collection', 'since', 'until')


@dataclass(frozen=True)
class Command:
    help: str
    run: object                 # the feature function: run(args, ctx) -> result
    options: tuple = ()
    positionals: tuple = ()     # (dest, argparse settings) in order
    identity: tuple = ()        # what makes two invocations the same query
    defaults: dict = field(default_factory=dict)
    epilog: str | None = None
    overrides: dict = field(default_factory=dict)


def read_listing(args, ctx):
    return listing.run(args, ctx)


def read_post(args, ctx):
    return post.run(args.target, sort=args.sort, limit=args.limit, max_requests=args.max_requests)


def read_profile(args, ctx):
    return profile.run(args.target, max_requests=args.max_requests)


TARGET = ('target', {'help': 'Threads @handle or profile URL (a tab URL such as /@name/replies reads that tab)'})
COMMANDS = {
    'home': Command('Read the for-you or following home feed.', read_listing,
                    ('feed', 'since', 'until', *READ), identity=('feed', 'since', 'until'),
                    defaults={'feed': 'foryou'}, epilog='--since/--until need --feed following.'),
    'user': Command('Read a profile tab: threads, replies, reposts or media.', read_listing,
                    ('tab', 'since', 'until', *READ), (TARGET,), identity=('target', 'tab', 'since', 'until'),
                    defaults={'tab': 'threads'},
                    epilog='A date window is kept locally. Only the newest-first tabs (threads, replies) can prove '
                           'that the window\'s start was passed; the result says whether the window was read whole.'),
    'about': Command('Read a profile card: name, bio, links, privacy, follower count (one request). Threads '
                     'publishes no following or mutual count; graph following lists the accounts.', read_profile, ('json', 'max_requests'), (TARGET,), identity=('target',)),
    'post': Command('Read one post in full with its parent chain and first batch of replies (one page; replies do not '
                    'page further).', read_post, ('sort', 'limit', 'chars', 'json', 'max_requests'),
                    (('target', {'help': 'Post URL or shortcode (a shortcode costs a redirect request)'}),),
                    identity=('target', 'sort'), defaults={'sort': 'top'},
                    overrides={'sort': {'help': 'Reply order (default top); recent may repeat top replies'},
                               'limit': {'help': 'Direct replies shown (default 10), each with its received '
                                                 'sub-replies; parents and the post are always shown'}}),
    'graph': Command('Read followers or following.', read_listing, READ[:1] + READ[2:],
                     (TARGET, ('relation', {'choices': ['followers', 'following'],
                                            'help': 'followers: one server-chosen sample (the reported total is '
                                                    'larger); following: pages on'})),
                     identity=('target', 'relation')),
    'search': Command('Search posts, tags or accounts.', read_listing, ('type', 'sort', 'tag', *READ),
                      (('query', {'help': 'Search text'}),), identity=('sort', 'query', 'type', 'tag'),
                      defaults={'sort': 'top', 'type': 'posts'},
                      epilog='--sort, --tag and --chars apply to post search only.'),
    'me': Command('Read your liked or saved posts (first batch only).', read_listing, READ,
                  (('collection', {'choices': ['liked', 'saved'], 'help': 'liked or saved'}),),
                  identity=('collection',)),
    'doctor': Command('Check Aside, login, account protection and registry age (one request; always JSON).',
                      lambda args, ctx: maintenance.doctor(args.unblock), ('unblock',)),
    'refresh': Command('Find rotated queries on Threads\' own pages, verify them by replay, and save an override '
                       '(always JSON).', lambda args, ctx: maintenance.refresh(args.capture, args.post),
                       ('capture', 'post'), epilog='Up to 40 paced requests; --capture up to 60.'),
    'schema': Command('Describe results, records, errors and --out files (no request; always JSON).',
                      lambda args, ctx: schema(EXIT_CODES)),
}
DESTS = sorted({*OPTIONS, 'target', 'query', 'relation', 'collection'})


def parser():
    table = '\n'.join(f'  {code}  {meaning}' for code, meaning in EXIT_CODES.items())
    root = Parser(description=__doc__, formatter_class=EpilogFormatter,
                  epilog='Each error carries its fix. Every command shares account pacing and block protection.'
                         '\n\nexit codes:\n' + table)
    commands = root.add_subparsers(dest='command', required=True, help='The Threads surface to read')
    for name, command in COMMANDS.items():
        sub = commands.add_parser(name, help=command.help, description=command.help, epilog=command.epilog)
        for dest, settings in command.positionals:
            sub.add_argument(dest, **settings)
        for option in command.options:
            flags, settings = OPTIONS[option]
            sub.add_argument(*flags, **{**settings, **command.overrides.get(option, {})})
        taken = {dest for dest, _ in command.positionals} | set(command.options)
        sub.set_defaults(**{dest: None for dest in DESTS if dest not in taken})
    return root


def validate(args):
    """Combinations the parser cannot express, refused before any request."""
    if args.command == 'search' and args.type == 'users':
        for flag, value in (('--sort', args.sort), ('--tag', args.tag), ('--chars', args.chars)):
            if value not in (None, False):
                raise ThreadsError(2, f'{flag} applies to post search; account search returns one batch of cards.')
    if args.target is not None:
        args.target = resolve_target(args.target, 'post' if args.command == 'post' else 'user')
        if args.command == 'user' and args.target.tab:
            if args.tab and args.tab != args.target.tab:
                raise ThreadsError(2, f'The URL is the {args.target.tab} tab but --tab asks for {args.tab}.',
                                   'Give one of them.')
            args.tab = args.target.tab
    if (args.since or args.until) and args.command == 'home' and args.feed != 'following':
        raise ThreadsError(2, 'Date windows apply only to the following feed and profile tabs.',
                           'Add --feed following, or read a profile with user.')
    if args.since and args.until and moment(args.since) >= moment(args.until):
        raise ThreadsError(2, '--since must be earlier than --until.')


def context(args):
    """The query's identity: what a continuation handle or --out file must match to resume it."""
    command = COMMANDS[args.command]
    result = {'command': args.command, 'account': 'u0'}
    for key in IDENTITY:
        if key in command.identity:
            value = getattr(args, key)
            result[key] = value.path if key == 'target' else command.defaults.get(key) if value is None else value
    if args.command == 'search' and result.get('type') == 'users':
        result.pop('sort', None)
    return result


def invocation():
    """This file's path as it was invoked (links kept), double-quoted the way allowed-tools spells it."""
    path = os.path.abspath(__file__)
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', path) + '"'


def more_command(args, ctx, handle):
    """The same query from the numbered handle, keeping what the caller chose to see and to spend."""
    command = COMMANDS[args.command]
    positionals = []
    for dest, _ in command.positionals:
        positionals.append('@' + args.target.username if dest == 'target' else ctx[dest])
    words = [args.command]
    for key in IDENTITY:
        if key in ctx and key not in dict(command.positionals):
            if ctx[key] is True:
                words.append('--' + key)
            elif ctx[key] not in (None, False):
                words += ['--' + key, str(ctx[key])]
    words += ['--after', str(handle)]
    if args.out is not None:
        words += ['--out', str(Path(args.out).expanduser().resolve())]
    for key in ('limit', 'chars', 'max_requests'):
        if getattr(args, key) is not None:
            words += ['--' + key.replace('_', '-'), str(getattr(args, key))]
    if args.json:
        words.append('--json')
    if any(str(word).startswith('-') for word in positionals):
        words.append('--')
    return invocation() + ' ' + shlex.join(words + positionals)


def main(argv=None):
    args = None
    try:
        args = parser().parse_args(argv)
        validate(args)
        ctx = context(args)
        result = COMMANDS[args.command].run(args, ctx)
        if result.get('next_handle') is not None:
            result['next'] = more_command(args, ctx, result['next_handle'])
        code = result.pop('code', 0)
        if result.get('fix'):
            result['fix'] = result['fix'].replace('{command}', args.command)
        if args.json or args.command in ('doctor', 'refresh', 'schema'):
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(render(result, args))
        return code
    except ThreadsError as error:
        if args is not None:
            error.fix = error.fix.replace('{command}', args.command)
        print(json.dumps(error.as_dict(), ensure_ascii=False))
        return error.code
    except (OSError, ValueError) as error:
        print(json.dumps(ThreadsError(6, f'Local operation failed ({type(error).__name__}).',
                                      'Check local storage and command arguments.').as_dict()))
        return 6


if __name__ == '__main__':
    sys.exit(main())
