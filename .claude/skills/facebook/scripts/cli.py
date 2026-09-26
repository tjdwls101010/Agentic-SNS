#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Facebook through the logged-in Aside browser."""
import argparse
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


def day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('expected a date in YYYY-MM-DD format') from None


def parser():
    table = '\n'.join(f'  {code}  {meaning}' for code, meaning in EXIT_CODES.items())
    root = Parser(description=__doc__, formatter_class=EpilogFormatter,
                  epilog='Read-only. Default request budget: 25; explicit --limit, --since, or --out: up to 400. All requests share pacing and account block protection.'
                  + '\n\nexit codes:\n' + table)
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    commands = root.add_subparsers(dest='command', required=True)
    descriptions = {
        'feed': 'Read the home feed in ranked or recent order.',
        'profile': 'Read a profile timeline; dates use local time and server filtering.',
        'group': 'Read a group feed; dates are client filters, not a completeness guarantee.',
        'post': 'Read one full post and its first batch of parent comments.',
        'comments': 'Read parent comments; limit counts parents before expanding replies.',
        'search': 'Search posts or people, pages, and groups.',
        'about': 'Read visible profile About fields and their collections.',
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description, description=description)
        if name != 'feed':
            command.add_argument('target', help='Search text' if name == 'search' else
                                 'Facebook post URL' if name in ('post', 'comments') else
                                 'Facebook URL, vanity name, or numeric id')
        command.add_argument('--verbose', action='store_true', default=argparse.SUPPRESS,
                             help='Write scrubbed request metadata to stderr; never raw captures')
        command.add_argument('--json', action='store_true', help='Emit one complete JSON document')
        command.add_argument('--chars', type=positive, default=180, help='Text preview length (post always shows full text)')
        command.add_argument('--limit', type=positive, help='Maximum records (parent comments for comments; omitted: request budget)')
        command.add_argument('--since', type=day, help='Inclusive local start date YYYY-MM-DD; unavailable for undated entities/About')
        command.add_argument('--until', type=day, help='Inclusive local end date YYYY-MM-DD; unavailable for undated entities/About')
        command.add_argument('--out', help='Write/resume context-checked NDJSON; commit whole pages, possibly exceeding --limit')
        command.add_argument('--after', type=positive, help='Resume the numbered cursor from more: with identical query context')
        if name in ('feed', 'group', 'comments', 'profile'):
            choices = ['recent'] if name == 'profile' else ['top', 'recent']
            if name == 'group':
                choices.append('activity')
            command.add_argument('--sort', choices=choices, default='recent' if name == 'profile' else 'top',
                                 help='Server order (profile supports recent only)')
        if name == 'comments':
            command.add_argument('--replies', action='store_true', help='Expand replies only for selected, deduplicated parents')
        if name == 'search':
            command.add_argument('--type', choices=['top', 'posts', 'people', 'pages', 'groups'], default='top',
                                 help='Result category (default: top, mixed posts and entities)')
        if name == 'about':
            command.add_argument('--section', help='Exact locale-independent section, e.g. directory_work')
    doctor = commands.add_parser('doctor', help='Check Aside, login, block status, and registry age')
    doctor.add_argument('--unblock', action='store_true', help='Clear persisted block after checking the browser manually')
    doctor.add_argument('--json', action='store_true', help='Emit one JSON document')
    refresh = commands.add_parser('refresh', help='Refresh query ids from Facebook client bundles',
                                  description='Mine and replay read queries. Up to 400 paced requests; this can take several minutes.')
    refresh.add_argument('--capture', action='store_true', help='Capture current feed flags and comment queries in browser tabs, then replay candidates')
    refresh.add_argument('--post', help='Facebook post URL used for comment capture')
    refresh.add_argument('--json', action='store_true', help='Emit one JSON document')
    schema = commands.add_parser('schema', help='Describe Post, Comment, Entity, and ProfileField from their public schemas')
    schema.add_argument('--json', action='store_true', help='Emit one JSON document')
    for command in (doctor, refresh, schema):
        command.add_argument('--verbose', action='store_true', default=argparse.SUPPRESS,
                             help='Write scrubbed request metadata to stderr')
    return root


def validate(args):
    if args.command in ('doctor', 'schema'):
        return
    if args.command == 'refresh':
        if bool(args.capture) != bool(args.post):
            raise FacebookError(2, '--capture and --post must be used together.')
        return
    if args.since and args.until and args.since > args.until:
        raise FacebookError(2, '--since must not be later than --until.')
    if args.after and args.out:
        raise FacebookError(2, '--after and --out cannot be combined; --out resumes its own file.')
    if args.command in ('about', 'post') and args.after:
        raise FacebookError(2, '--after is supported by feed, profile, group, comments, and search.')
    if (args.since or args.until) and (args.command == 'about' or
            args.command == 'search' and args.type != 'posts'):
        raise FacebookError(2, 'Date filters require dated results; use search --type posts or profile.')
    if args.command == 'search' and not args.target.strip():
        raise FacebookError(2, 'Search text must not be empty.')


def context_for(args):
    """A query's identity; the account is filled in once the browser session is known."""
    context = {'command': args.command, 'target': getattr(args, 'target', None),
               'sort': getattr(args, 'sort', None),
               'window': {'since': args.since, 'until': args.until},
               'account_id': None}
    for key in ('type', 'section', 'replies'):
        if hasattr(args, key):
            context[key] = getattr(args, key)
    return context


def continuation_args(args):
    """post continues as comments on the same post, in top order without replies or a window."""
    continued = argparse.Namespace(**vars(args))
    continued.command, continued.sort = 'comments', 'top'
    continued.replies = False
    continued.since = continued.until = None
    return continued


def invocation():
    """This file's path as it was invoked (links kept), double-quoted the way allowed-tools spells it."""
    path = os.path.abspath(__file__)
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', path) + '"'


def next_command(args, number, command=None):
    name = command or args.command
    words = [name]
    if getattr(args, 'target', None):
        words.append(args.target)
    if name == 'comments' and args.command == 'post':
        words += ['--sort', 'top']
    else:
        for key in ('sort', 'type', 'section', 'since', 'until', 'limit', 'chars'):
            if getattr(args, key, None) is not None:
                words += ['--' + key, str(getattr(args, key))]
        if getattr(args, 'replies', False):
            words.append('--replies')
    if getattr(args, 'json', False):
        words.append('--json')
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
            if args.command == 'post':
                continuation = context_for(continuation_args(args))
        result = dispatch.run(args, context=context, continuation=continuation)
        handle = result.get('handle')
        if handle:
            continued = continuation_args(args) if handle['command'] != args.command else args
            result = {('next' if key == 'handle' else key): (next_command(continued, handle['number'])
                                                            if key == 'handle' else value)
                      for key, value in result.items()}
        return emit(result, json_mode=args.json, chars=None if args.command == 'post' else getattr(args, 'chars', 180),
                    command=args.command, sort=getattr(args, 'sort', None))
    except FacebookError as error:
        print(json.dumps({'ok': False, 'error': error.code, 'message': error.message, 'fix': error.fix,
                          'results': []}, ensure_ascii=False))
        return error.code
    except OSError:
        print(json.dumps({'ok': False, 'error': 6, 'message': 'Could not read or write local state.', 'results': []}))
        return 6


if __name__ == '__main__':
    sys.exit(main())
