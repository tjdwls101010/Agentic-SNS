#!/usr/bin/env python3
"""Read Facebook through the logged-in Aside browser."""
import argparse
import copy
from datetime import date
import json
from pathlib import Path
import shlex
import sys

from _errors import FacebookError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FacebookError(2, message, 'Run the command with --help.')


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
    root = Parser(description=__doc__, epilog='Read-only. Default request budget: 25; explicit --limit, --since, or --out: up to 400. All requests share pacing and account block protection.')
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
    from _resolve import normalize_group, normalize_post, normalize_profile
    if args.command == 'refresh':
        if bool(args.capture) != bool(args.post):
            raise FacebookError(2, '--capture and --post must be used together.')
        if args.post:
            args.post = normalize_post(args.post)
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
    if args.command in ('profile', 'about'):
        args.target = normalize_profile(args.target)
    elif args.command == 'group':
        args.target = normalize_group(args.target)
    elif args.command in ('post', 'comments'):
        args.target = normalize_post(args.target)
    elif args.command == 'search' and not args.target.strip():
        raise FacebookError(2, 'Search text must not be empty.')


def context_for(args, transport):
    context = {'command': args.command, 'target': getattr(args, 'target', None),
               'sort': getattr(args, 'sort', None),
               'window': {'since': args.since, 'until': args.until},
               'account_id': transport.account_id}
    for key in ('type', 'section', 'replies'):
        if hasattr(args, key):
            context[key] = getattr(args, key)
    return context


def next_command(args, number, command=None):
    name = command or args.command
    words = ['python3', str(Path(__file__).resolve()), name]
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
    return shlex.join(words)


def read(args, transport):
    from _output import CursorStore, OutFile
    from _cmds_posts import run as posts
    from _cmds_people import run as people
    context = context_for(args, transport)
    state = CursorStore().load(args.after, context) if args.after else {}
    saved_cursor = state.get('cursor')
    if isinstance(saved_cursor, dict) and 'resume_cursor' in saved_cursor:
        state.update(cursor=saved_cursor['resume_cursor'], seen=saved_cursor.get('seen', []))
    output = OutFile(args.out, context) if args.out else None
    try:
        if output and output.complete:
            return {'ok': True, 'results': [], 'stop_reason': 'already_complete',
                    'out': args.out, 'count': output.count, 'already_complete': True}
        run_args = copy.copy(args)
        if output:
            state = {'cursor': output.cursor, 'pending': output.pending, 'seen': output.ids}
            saved_count = output.parent_count if args.command == 'comments' else output.count
            if args.limit is not None:
                if saved_count >= args.limit:
                    return {'ok': True, 'results': [], 'stop_reason': 'limit_reached',
                            'out': args.out, 'count': output.count, 'request_count': transport.request_count}
                run_args.limit = args.limit - saved_count
        def commit_page(records, cursor, reason):
            end = cursor.get('after') if isinstance(cursor, dict) and 'post_id' in cursor else cursor
            if end == {'exhausted': True} and reason in ('limit_reached', 'exhausted', None):
                reason = 'exhausted'
            output.commit(records, cursor, reason)

        handler = posts if args.command in ('feed', 'profile', 'group', 'post') else people
        result = handler(run_args, transport, state=state, commit=commit_page if output else None)
        continuation_args = args
        if result.pop('continuation_command', None) == 'comments':
            continuation_args = argparse.Namespace(**vars(args))
            continuation_args.command, continuation_args.sort = 'comments', 'top'
            continuation_args.replies = False
            continuation_args.since = continuation_args.until = None
            context = context_for(continuation_args, transport)
        pending = result.get('pending')
        cursor = result.get('cursor')
        end = cursor.get('after') if isinstance(cursor, dict) and 'post_id' in cursor else cursor
        retry_replies = cursor.get('reply_retries') if isinstance(cursor, dict) else None
        if not output and (pending or retry_replies or cursor is not None and end != {'exhausted': True}):
            seen = set(state.get('seen') or [])
            seen.update(r['id'] for r in result['results'] if r.get('id') is not None)
            number = CursorStore().save(context, {'resume_cursor': cursor, 'seen': sorted(seen)}, pending=pending)
            result['next'] = next_command(continuation_args, number)
        result.pop('pending', None)
        result.pop('cursor', None)
        if output:
            result.update(out=args.out, count=output.count)
        result['request_count'] = transport.request_count
        return result
    finally:
        if output:
            output.close()


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        validate(args)
        from _blocked import check_blocked
        if args.command == 'doctor' and args.unblock:
            from _blocked import unblock
            unblock()
        check_blocked()
        if args.command == 'schema':
            from _cmds_maint import schema
            result = schema()
        else:
            from _transport import Transport
            # 성진: 400회 상한은 실계정 보호용, 일회용 계정으로 바꾸면 올려도 됨
            budget = 400 if args.command == 'refresh' or any(
                getattr(args, key, None) for key in ('limit', 'since', 'out')) else 25
            transport = Transport(limit=budget)
            transport.verbose = args.verbose
            transport.start()
            if args.command in ('doctor', 'refresh'):
                from _cmds_maint import run
                result = run(args, transport)
            else:
                result = read(args, transport)
        from _output import emit
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
