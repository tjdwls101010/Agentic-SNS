"""Run one command: prepare its target, guard the account, then read through the transport and local stores.

The caller supplies each query's identity (its context, with `account_id` still unknown) and turns a returned
`handle` into a continuation command; this module fills in the account and saves cursors, nothing more.
"""
import copy

from facebook.account import check_blocked, unblock
from facebook.collect import OutFile
from facebook.cursors import CursorStore
from facebook.graphql.resolve import normalize_group, normalize_post, normalize_profile
from facebook.graphql.transport import Transport
from facebook.reading import maintenance
from facebook.reading.about import about
from facebook.reading.comments import comments
from facebook.reading.posts import run as posts
from facebook.reading.search import search


def prepare(args):
    """Normalize the target before any request; an unusable target is an argument error."""
    if args.command == 'refresh':
        if args.post:
            args.post = normalize_post(args.post)
        return
    if args.command in ('profile', 'about'):
        args.target = normalize_profile(args.target)
    elif args.command == 'group':
        args.target = normalize_group(args.target)
    elif args.command in ('post', 'comments'):
        args.target = normalize_post(args.target)


def run(args, *, context=None, continuation=None):
    if args.command == 'doctor' and args.unblock:
        unblock()
    check_blocked()
    if args.command == 'schema':
        return maintenance.schema()
    # 성진: 400회 상한은 실계정 보호용, 일회용 계정으로 바꾸면 올려도 됨
    budget = 400 if args.command == 'refresh' or any(
        getattr(args, key, None) for key in ('limit', 'since', 'out')) else 25
    transport = Transport(limit=budget)
    transport.verbose = args.verbose
    transport.start()
    if args.command in ('doctor', 'refresh'):
        return maintenance.run(args, transport)
    return read(args, transport, context, continuation)


def _with_account(context, transport):
    context = dict(context)
    context['account_id'] = transport.account_id
    return context


def read(args, transport, context, continuation):
    context = _with_account(context, transport)
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

        commit = commit_page if output else None
        if args.command in ('feed', 'profile', 'group', 'post'):
            result = posts(run_args, transport, state=state, commit=commit)
        elif args.command == 'comments':
            result = comments(run_args, transport, state=state, commit=commit)
        elif args.command == 'search':
            result = search(run_args, transport, state, commit)
        else:
            result = about(run_args, transport, state, commit)
        command = args.command
        if result.pop('continuation_command', None) == 'comments':
            command = 'comments'
            context = _with_account(continuation, transport)
        pending = result.get('pending')
        cursor = result.get('cursor')
        end = cursor.get('after') if isinstance(cursor, dict) and 'post_id' in cursor else cursor
        retry_replies = cursor.get('reply_retries') if isinstance(cursor, dict) else None
        if not output and (pending or retry_replies or cursor is not None and end != {'exhausted': True}):
            seen = set(state.get('seen') or [])
            seen.update(r['id'] for r in result['results'] if r.get('id') is not None)
            number = CursorStore().save(context, {'resume_cursor': cursor, 'seen': sorted(seen)}, pending=pending)
            result['handle'] = {'number': number, 'command': command}
        result.pop('pending', None)
        result.pop('cursor', None)
        if output:
            result.update(out=args.out, count=output.count)
        result['request_count'] = transport.request_count
        return result
    finally:
        if output:
            output.close()
