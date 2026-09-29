#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read X through Aside. This entry point only validates and dispatches."""
import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from typing import Callable

from twitter.browse import maintenance, operations
from twitter.browse.run import run as browse
from twitter.dates import timestamp
from twitter.errors import TwitterError
from twitter.output.doctor import summary
from twitter.output.render import plain, render
from twitter.output.schema import schema


@dataclass(frozen=True)
class Arg:
    """One argparse argument; `default` (a value, or a function of the parsed args) fills it when it was not given."""
    flags: tuple
    options: dict = field(default_factory=dict)
    default: object = None

    @property
    def dest(self):
        return self.options.get('dest') or self.flags[0].lstrip('-').replace('-', '_')


@dataclass(frozen=True)
class Rule:
    """A combination refused before any request. `when(args, given)` sees args with defaults filled and `given`, what was typed; an early rule runs before the shared limit and chars check."""
    when: Callable
    message: str
    fix: str | None = None
    early: bool = False


@dataclass(frozen=True)
class Surface:
    """Everything one command is: its arguments and refusals, what it asks X for, and how its result is shaped.

    `target` is the kind its positional targets parse as; `operation(args)` gives the operation and variables; `prepare`, `fetch` and `finish` are browse/operations hooks (see browse.run); `rows` is the record kind listed; `continuable` issues more: handles; `sparse` stops an account list after three empty pages; `personal` rechecks the viewer cookie; `limit` is the display target when --limit is absent; `runner(args)` replaces all of this for doctor, refresh and schema. A field may be a function of the parsed args.
    """
    help: str
    args: tuple = ()
    rules: tuple = ()
    target: str | None = None
    operation: Callable | None = None
    prepare: Callable | None = None
    fetch: Callable | None = None
    finish: Callable | None = None
    rows: str | Callable = 'tweet'
    continuable: bool | Callable = True
    sparse: bool | Callable = False
    personal: bool = False
    limit: int | Callable = 10
    runner: Callable | None = None


def value(field, args):
    return field(args) if callable(field) else field


JSON = Arg(('--json',), dict(action='store_true', help='Emit exactly one JSON document, including partial results and recovery.'))
LIMIT = Arg(('--limit',), dict(type=int, help='Display target: 10 items; single post 20 replies. Batch posts return all results without this option. Explicit limits allow 40 requests.'))
CHARS = Arg(('--chars',), dict(type=int, help='Text characters per item, default 280; the focal post is always full.'), 280)
OUT = Arg(('--out',), dict(metavar='FILE', help='Commit whole date-eligible pages as private NDJSON; repeat the same command to resume.'))
AFTER = Arg(('--after',), dict(type=int, metavar='N', help='Resume a numbered more: handle, consuming cached items before requesting another page.'))
DATES = tuple(Arg(('--' + flag,), dict(help=f'Client date filter ({flag} ISO date/time); chronological tabs only. until is exclusive.'))
              for flag in ('since', 'until'))
BROWSE = (LIMIT, CHARS, OUT, AFTER)
TARGET = Arg(('target',), dict(help='@handle/profile URL for profiles; X URL or numeric ID for other targets.'))
TARGETS = Arg(('target',), dict(nargs='+', help='@handle/profile URL for profiles; X URL or numeric ID for other targets.'))


def tab(*choices):
    return Arg(('--tab',), dict(choices=list(choices), help=f'Tab to read; default {choices[0]}.'), choices[0])


def sort(*choices, default):
    return Arg(('--sort',), dict(choices=list(choices), help='Post ranking; default latest for search, top otherwise. Account search uses People ranking and has no sort option.'), default)


def dated(allowed):
    return Rule(lambda a, g: (a.since or a.until) and not allowed(a), 'Date windows require a chronological timeline tab.')


def batch(args):
    return len(args.target) > 1


NO_AFTER = Rule(lambda a, g: a.after and a.tab == 'about', 'This lookup does not support --after.')
SURFACES = {
    'home': Surface('Read your personalized For you or chronological Following feed.',
                    (*BROWSE, *DATES, Arg(('--feed',), dict(choices=['foryou', 'following'], help='Feed to read, default foryou.'), 'foryou')),
                    (dated(lambda a: a.feed == 'following'),), operation=operations.home, personal=True),
    'user': Surface('Read a profile tab. replies-only is an ungated, mixed posts/replies alternative.',
                    (*BROWSE, *DATES, tab('posts', 'replies', 'replies-only', 'media', 'highlights', 'articles'), TARGET),
                    (dated(lambda a: a.tab in ('posts', 'replies', 'replies-only', 'media')),), 'user',
                    operations.user, operations.profile_id),
    'about': Surface('Read one or several profile cards in one request.', (CHARS, OUT, TARGETS), (), 'user',
                     operations.about, finish=operations.unresolved_handles, rows='user', continuable=False,
                     limit=lambda a: len(a.target)),
    'post': Surface('Open a post with parents and replies; several IDs fetch posts without threads.',
                    (*BROWSE, sort('top', 'recent', default='top'), TARGETS),
                    (Rule(lambda a, g: batch(a) and g['limit'] is not None, 'Batch post lookup returns every requested post and has no --limit.',
                          'Remove --limit, or open one post for replies.', early=True),
                     Rule(lambda a, g: batch(a) and (g['sort'] is not None or g['after'] is not None), 'Batch post lookup has no replies or continuation.')),
                    'post', operations.post, finish=operations.thread_completeness, continuable=lambda a: not batch(a),
                    limit=lambda a: len(a.target) if batch(a) else 20),
    'quotes': Surface('Find posts quoting a post; uses the shared search bucket.', (*BROWSE, TARGET), (), 'post', operations.quotes),
    'reposts': Surface('Read the accounts that reposted a post.', (*BROWSE, TARGET), (), 'post', operations.reposts,
                       rows='user', sparse=True),
    'search': Surface('Search posts, accounts or media. X search operators pass through unchanged.',
                      (*BROWSE, sort('top', 'latest', default=lambda a: 'latest' if a.type != 'users' else None),
                       Arg(('target',), dict(help='Search text, including X from:, since:, until: or engagement operators.')),
                       Arg(('--type',), dict(choices=['posts', 'users', 'media'], help='Search product, default posts; all share one operation bucket.'), 'posts'),
                       Arg(('--in',), dict(dest='scope', choices=['communities'], help='Search posts across ALL communities; only posts/latest supported.'))),
                      (Rule(lambda a, g: a.type == 'users' and g['sort'] is not None, 'Account search uses X People ranking, not top/latest post sorting.',
                            'Omit --sort for --type users.'),
                       Rule(lambda a, g: a.scope and (a.type != 'posts' or a.sort != 'latest'), 'Community search only supports posts/latest.')),
                      operation=operations.search, rows=lambda a: 'user' if a.type == 'users' else 'tweet',
                      sparse=lambda a: a.type == 'users'),
    'graph': Surface('Read following, followers, verified followers or followers you know.',
                     (*BROWSE, Arg(('target',), dict(help='@handle or profile URL; numeric user IDs are unavailable.')),
                      Arg(('relation',), dict(choices=['following', 'followers', 'verified', 'known'], help='Relationship list to read.'))),
                     (), 'user', operations.graph, operations.profile_id, rows='user', sparse=True),
    'me': Surface('Read your bookmarks or liked posts.',
                  (*BROWSE, Arg(('collection',), dict(choices=['bookmarks', 'likes'], help='Your private collection to read.'))),
                  operation=operations.collection, prepare=operations.viewer_likes, personal=True),
    'list': Surface('Read list posts, members or its information card.', (*BROWSE, *DATES, tab('posts', 'members', 'about'), TARGET),
                    (NO_AFTER, dated(lambda a: a.tab == 'posts')), 'list', operations.listing,
                    rows=lambda a: {'posts': 'tweet', 'members': 'user', 'about': 'place'}[a.tab]),
    'trends': Surface('Read trends and events from an Explore tab; other item types are counted.',
                      (LIMIT, CHARS, OUT, tab('trending', 'foryou', 'news', 'sports', 'entertainment')),
                      operation=operations.trends, fetch=operations.explore, rows='trend', continuable=False),
    'community': Surface('Read community posts, media or information and member roles.',
                         (*BROWSE, tab('posts', 'media', 'about'), sort('top', 'recent', default='top'), TARGET),
                         (Rule(lambda a, g: a.tab != 'posts' and g['sort'] is not None, 'Sorting only applies to community posts.'), NO_AFTER),
                         'community', operations.community, operations.community_card,
                         rows=lambda a: 'user' if a.tab == 'about' else 'tweet', continuable=lambda a: a.tab != 'about'),
    'communities': Surface('Browse community posts with links to their communities.', BROWSE, operation=operations.communities),
    'doctor': Surface('Check Aside, your viewer, protection state and cache ages.',
                      (Arg(('--unblock',), dict(action='store_true', help='Clear a challenge/lock after checking X in Aside; rate limits still apply.')),),
                      runner=lambda args: summary(maintenance.doctor(args))),
    'refresh': Surface('Mine current read-query IDs and signatures, then verify two operations before saving.',
                       runner=lambda args: summary(maintenance.refresh(args))),
    'schema': Surface('Describe the normalized output fields without making requests.', runner=lambda args: schema()),
}
UNSET = ('limit', 'after', 'since', 'until', 'tab', 'sort', 'feed', 'type', 'scope', 'relation', 'collection', 'target')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TwitterError(2, message, 'Read the command --help for valid options.')


def parser():
    p = Parser(description='Read-only X (Twitter) via the logged-in Aside u0 browser.',
               epilog='Exit: 0 success; 2 arguments; 3 Aside; 4 session; 5 blocked/rate/window; '
                      '6 API drift; 7 empty; 8 partial/budget; 9 unavailable. Errors include a recovery fix.')
    subs = p.add_subparsers(dest='command', required=True)
    for name, surface in SURFACES.items():
        sub = subs.add_parser(name, help=surface.help, description=surface.help)
        for arg in (JSON, *surface.args):
            sub.add_argument(*arg.flags, **arg.options)
    return p


def validate(args):
    surface = SURFACES[args.command]
    if surface.runner:
        return args
    for key in UNSET:
        if not hasattr(args, key):
            setattr(args, key, None)
    given = dict(vars(args))
    args.explicit_limit = args.limit is not None
    if args.after is not None and args.after < 1:
        raise TwitterError(2, 'Continuation handles must be positive.', 'Copy the complete more: command.')
    refuse([rule for rule in surface.rules if rule.early], args, given)
    if args.limit is not None and args.limit < 1 or args.chars is not None and args.chars < 1:
        raise TwitterError(2, 'limit and chars must be positive.', 'Choose a positive display target.')
    for arg in sorted(surface.args, key=lambda arg: callable(arg.default)):
        if arg.default is not None and getattr(args, arg.dest) is None:
            setattr(args, arg.dest, value(arg.default, args))
    refuse([rule for rule in surface.rules if not rule.early], args, given)
    for key in ('since', 'until'):
        if getattr(args, key):
            normalized = timestamp(getattr(args, key) + 'T00:00:00+00:00' if len(getattr(args, key)) == 10 else getattr(args, key))
            if not normalized:
                raise TwitterError(2, f'Invalid {key} date.', 'Use YYYY-MM-DD or an ISO timestamp.')
            setattr(args, key, normalized)
    if args.since and args.until and args.since >= args.until:
        raise TwitterError(2, 'since must precede until.')
    if surface.target:
        args.targets = operations.resolve(args.target if isinstance(args.target, list) else [args.target], surface.target)
    args.limit = args.limit or value(surface.limit, args)
    return args


def refuse(rules, args, given):
    for rule in rules:
        if rule.when(args, given):
            raise TwitterError(2, rule.message, *([rule.fix] if rule.fix else []))


def invocation():
    """This CLI as its allowed-tools pattern runs it: the path as called, double-quoted, never resolved."""
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', os.path.abspath(__file__)) + '"'


def context_for(args, op):
    """A query's identity for continuations and exports; the run attaches the viewer."""
    targets = [t.handle.lower() if t.handle else t.tweet_id or t.list_id or t.community_id for t in args.targets] if hasattr(args, 'targets') else args.target
    return dict(command=args.command, target=targets, operation=op, viewer_id=None,
                **{key: getattr(args, key) for key in ('tab', 'sort', 'feed', 'type', 'scope', 'relation', 'collection', 'since', 'until')})


def more_command(args, number):
    parts = [args.command]
    if args.target:
        parts.extend(args.target if isinstance(args.target, list) else [args.target])
    if args.relation:
        parts.append(args.relation)
    if args.collection:
        parts.append(args.collection)
    for key in ('tab', 'sort', 'feed', 'type', 'scope', 'since', 'until'):
        value = getattr(args, key)
        if value is not None:
            parts.extend(['--in' if key == 'scope' else '--' + key, value])
    parts.extend(['--limit', str(args.limit), '--after', str(number)])
    return invocation() + ' ' + shlex.join(parts)


def emit(result, args):
    code = result.pop('code', 0)
    result.pop('state', None)
    result.setdefault('next', None)
    result.setdefault('warnings', [])
    result.setdefault('fetched_bytes', 0)
    result.setdefault('budget', {})
    surface = SURFACES[args.command]
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(plain(result) if surface.runner else render(result, args, value(surface.rows, args)))
    return code


def dispatch(args):
    surface = SURFACES[args.command]
    if surface.runner:
        return surface.runner(args)
    op, variables = surface.operation(args)
    result = browse(args, context_for(args, op), op, variables, rows=value(surface.rows, args), personal=surface.personal,
                    prepare=surface.prepare, fetch=surface.fetch, finish=surface.finish,
                    continuable=value(surface.continuable, args), sparse=value(surface.sparse, args))
    if result.get('next_handle'):
        result['next'] = more_command(args, result['next_handle'])
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = validate(parser().parse_args(argv))
        return emit(dispatch(args), args)
    except TwitterError as error:
        if '--json' in argv:
            print(json.dumps(error.to_dict(), ensure_ascii=False))
        else:
            print(f'{error.error}: {error.message}\nfix: {error.fix}')
        return error.code
    except (OSError, BrokenPipeError):
        error = TwitterError(8, 'Local output or cache I/O failed.', 'Check disk space and permissions; resume committed output.')
        print(json.dumps(error.to_dict()))
        return error.code


if __name__ == '__main__':
    sys.exit(main())
