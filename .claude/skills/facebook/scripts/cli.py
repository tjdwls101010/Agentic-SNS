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
from facebook.render import render_results

EXIT_CODES = {
    0: 'success',
    2: 'invalid arguments, or a continuation or output file from a different query',
    3: 'Aside is unavailable or returned an invalid response',
    4: 'Facebook login is required',
    5: 'requests are blocked for this account (checkpoint, rate limit or unreadable protection state)',
    6: 'the query failed before any record was read',
    7: 'the query explicitly returned no results',
    8: 'partial result: records plus a failure, or the request budget ran out',
}


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
    'feed': Command('Read the home feed.', ('sort', 'include_sponsored', *READ), identity=('sort', 'window'),
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


def next_command(args, number):
    """The same query from the numbered handle: identity options, then the controls the caller chose."""
    words = [args.command] + ([args.target] if args.target else [])
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
    words += ['--after', str(number)]
    return invocation() + ' ' + shlex.join(words)


def emit(result, json_mode=False, chars=180, command='', sort=None):
    """One stdout document on JSON/error paths; never mix diagnostics with data."""
    result = dict(result)
    records = result.setdefault('results', [])
    code = result.pop('code', 0)
    result.setdefault('ok', True)
    result.setdefault('stop_reason', 'exhausted')
    result['stop_reason'] = {'already_complete': 'exhausted', 'reply_batch_limit': 'query_failure'}.get(
        result['stop_reason'], result['stop_reason'])
    if not result['ok']:
        code = code or (5 if result['stop_reason'] == 'blocked' else 8 if records else 6)
        if records and code not in (4, 5):
            code = 8
        result.setdefault('error', 'partial' if records else 'query_failure')
        result.setdefault('message', 'The request did not complete.')
        result.setdefault('fix', 'Read stop_reason before continuing.')
    elif not records and command not in ('schema', 'doctor', 'refresh') and not result.get('out'):
        result.update(ok=False, error='empty', message='This query explicitly returned no results.',
                      fix='Try a different target or date window; this is not a stale-query failure.')
        code = 7
    if json_mode or not result['ok']:
        print(json.dumps(result, ensure_ascii=False))
    elif result.get('out'):
        print(f'{command} · {result.get("count", len(records))} saved · stopped={result["stop_reason"]} · '
              + json.dumps(str(result['out']), ensure_ascii=False)
              + (' · already complete' if result.get('already_complete') else ''))
    elif command in ('schema', 'doctor', 'refresh'):
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(render_results(records, command=command, sort=sort, stop_reason=result['stop_reason'],
                             more=result.get('next'), chars=chars))
        if result.get('note'):
            print(str(result['note']).replace('\n', ' '))
    return code


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        validate(args)
        dispatch.prepare(args)
        context = continuation = None
        if args.command not in ('doctor', 'refresh', 'schema'):
            context = context_for(args)
            if COMMANDS[args.command].continues_as:
                continuation = context_for(continuation_args(args), COMMANDS[args.command].continues_as)
        result = dispatch.run(args, context=context, continuation=continuation)
        handle = result.get('handle')
        if handle:
            continued = continuation_args(args) if handle['command'] != args.command else args
            result = {('next' if key == 'handle' else key): (next_command(continued, handle['number'])
                                                            if key == 'handle' else value)
                      for key, value in result.items()}
        return emit(result, json_mode=bool(args.json), chars=args.chars or (None if args.command == 'post' else 180),
                    command=args.command, sort=args.sort)
    except FacebookError as error:
        print(json.dumps({'ok': False, 'error': error.code, 'message': error.message, 'fix': error.fix,
                          'results': []}, ensure_ascii=False))
        return error.code
    except OSError:
        print(json.dumps({'ok': False, 'error': 6, 'message': 'Could not read or write local state.', 'results': []}))
        return 6


if __name__ == '__main__':
    sys.exit(main())
