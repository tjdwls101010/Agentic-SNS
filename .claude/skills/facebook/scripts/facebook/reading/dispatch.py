"""Run one command: prepare its target, guard the account, read through the transport and local stores, finish.

The caller supplies each query's identity (its context, with `account_id` still unknown) and turns a returned
`handle` into a continuation command; this module fills in the account, saves cursors and hands the reading to
outcome.finish, nothing more.
"""
import copy

from facebook.account import check_blocked, unblock
from facebook.collect import OutFile
from facebook.cursors import CursorStore
from facebook.graphql.resolve import normalize_group, normalize_post, normalize_profile
from facebook.graphql.transport import Transport
from facebook.errors import FacebookError
from facebook.outcome import FIXES, SETUP_BUDGET, finish
from facebook.reading import maintenance
from facebook.reading.about import about
from facebook.reading.comments import comments
from facebook.reading.posts import run as posts
from facebook.reading.search import search


def prepare(args):
    """Normalize the target before any request; an unusable target is an argument error."""
    if args.command == 'refresh':
        if args.capture:
            args.capture = normalize_post(args.capture)
        return
    if args.command in ('profile', 'about'):
        args.target = normalize_profile(args.target)
    elif args.command == 'group':
        args.target = normalize_group(args.target)
    elif args.command in ('post', 'comments'):
        args.target = normalize_post(args.target)


def run(args, *, context=None, continuation=None, identity=None):
    """(kind, envelope) of one command; failures before any reading raise FacebookError."""
    if args.command == 'schema':
        return finish(maintenance.schema(args.object), command='schema', requests=0, budget=0)
    if args.command == 'doctor' and args.unblock:
        unblock()
    check_blocked()
    # 성진: refresh의 400회는 실계정 보호 상한, 일회용 계정으로 바꾸면 올려도 됨
    budget = {'refresh': 400, 'doctor': 2}.get(args.command) or args.max_requests or 25
    transport = Transport(limit=budget)
    transport.verbose = args.verbose
    try:
        transport.start()
        if args.command in ('doctor', 'refresh'):
            reading = maintenance.run(args, transport)
        else:
            reading = read(args, transport, context, continuation)
    except FacebookError as error:
        # A budget stop outside paging has no cursor to continue from: home, target id, permalink, About overview.
        if error.code == 8 and args.command not in ('doctor', 'refresh'):
            raise FacebookError(8, SETUP_BUDGET, FIXES['budget_restart']) from None
        raise
    resumable = bool(reading.get('handle')) or args.out is not None
    kind, envelope = finish(reading, command=args.command, identity=identity, requests=transport.request_count,
                            budget=budget, out=args.out, resumable=resumable)
    if reading.get('handle'):
        envelope['handle'] = reading['handle']
    return kind, envelope


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
            return {'results': [], 'stop_reason': 'exhausted', 'count': output.count, 'already_complete': True}
        run_args = copy.copy(args)
        if output:
            state = {'cursor': output.cursor, 'pending': output.pending, 'seen': output.ids}
            saved_count = output.parent_count if args.command == 'comments' else output.count
            if args.limit is not None:
                if saved_count >= args.limit:
                    return {'results': [], 'stop_reason': 'limit_reached', 'count': output.count}
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
            result['count'] = output.count
        return result
    finally:
        if output:
            output.close()
