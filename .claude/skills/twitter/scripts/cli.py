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
from twitter.browse.run import run as browse, valid_handle
from twitter.dates import timestamp
from twitter.errors import TwitterError
from twitter.output.doctor import summary
from twitter.output.render import plain, render
from twitter.output.schema import ABOUT as TOPICS, schema


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

    `target` is the kind its positional targets parse as; `fixes` maps an error class to this command's own fix (a function of the args, None to keep the general one); `operation(args)` gives the operation and variables; `prepare`, `fetch` and `finish` are browse/operations hooks (see browse.run); `rows` is the record kind listed; `continuable` issues more: handles; `sparse` stops an account list after three empty pages; `personal` rechecks the viewer cookie; `limit` is the display target when --limit is absent; `label` names in the text header what the request asked for (default: the command); `runner(args)` replaces all of this for doctor, refresh and schema. A field may be a function of the parsed args.
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
    fixes: dict = field(default_factory=dict)
    label: Callable | None = None


def value(field, args):
    return field(args) if callable(field) else field


EXITS = {
    0: 'success',
    2: 'arguments or local state: change what the fix names',
    3: 'Aside is unavailable or its reply was invalid',
    4: 'no usable X session in Aside',
    5: 'blocked, rate-limited, or the account window is full: wait or unblock as the fix says',
    6: 'X changed something or failed transiently: the error says which',
    7: 'empty: a valid response with no matching items',
    8: 'partial results, or this run spent its request budget: more: continues',
    9: 'unavailable: a deleted, protected or suspended target',
}
JSON = Arg(('--json',), dict(action='store_true', help='Print one JSON document instead of text, including partial results and the error fix.'))
OUT = Arg(('--out',), dict(metavar='FILE', help='Also save whole date-eligible pages to this private NDJSON file; run the same command again to resume. schema export describes the file.'))
PROFILE = Arg(('target',), dict(help='@handle or x.com profile URL; numeric user IDs are not accepted.'))
POST = Arg(('target',), dict(help='x.com post URL or numeric post ID.'))


def limit(noun, default, extra=''):
    return Arg(('--limit',), dict(type=int, help=f'{noun} to show, default {default}{extra}. Giving --limit lets this run make up to 40 requests instead of 10.'))


def chars(what, extra=''):
    return Arg(('--chars',), dict(type=int, help=f'Characters of {what} to show per item, default 280{extra}.'), 280)


def after(extra=''):
    return Arg(('--after',), dict(metavar='HANDLE', help='Continue from the handle in a more: line; its cached items come first, with no request. Handles expire 24 hours after they are issued.' + extra))


def dates(scope):
    return (Arg(('--since',), dict(help=f'Keep posts at or after this date (YYYY-MM-DD or ISO time); {scope} only.')),
            Arg(('--until',), dict(help=f'Keep posts before this date, exclusive (YYYY-MM-DD or ISO time); {scope} only.')))


def tab(*choices, help):
    return Arg(('--tab',), dict(choices=list(choices), help=help), choices[0])


def sort(*choices, default, help):
    return Arg(('--sort',), dict(choices=list(choices), help=help), default)


def dated(allowed, fix):
    return Rule(lambda a, g: (a.since or a.until) and not allowed(a), 'Date windows require a chronological timeline tab.', fix)


def signed(alternative):
    """A signature failure's fix for one surface: refresh first, then what else answers and how that answer differs."""
    return {error: alternative for error in ('transaction_rejected', 'transaction_unavailable')}


def batch(args):
    return len(args.target) > 1


NO_AFTER = Rule(lambda a, g: a.after and a.tab == 'about', 'This lookup does not support --after.',
                'Remove --after; --tab about returns the whole card in one request.')
POSTS = (limit('Posts', 10), chars('post text'), OUT, after())
ACCOUNTS = (limit('Accounts', 10), chars('bio'), OUT, after())
SURFACES = {
    'home': Surface('Read your home feed: For you (personalized ranking) or Following (chronological).',
                    (*POSTS, *dates('with --feed following'),
                     Arg(('--feed',), dict(choices=['foryou', 'following'], help='Feed: foryou (personalized ranking, default) or following (chronological).'), 'foryou')),
                    (dated(lambda a: a.feed == 'following', 'Add --feed following (the chronological feed), or remove --since/--until.'),),
                    operation=operations.home, personal=True, label=lambda a: f'home {a.feed}'),
    'user': Surface('Read one profile tab of an account.',
                    (*POSTS, *dates('tabs posts, replies, replies-only and media'),
                     tab('posts', 'replies', 'replies-only', 'media', 'highlights', 'articles',
                         help='Tab, default posts. replies needs a signed request; replies-only is unsigned but mixes in some non-reply posts; articles lists articles, their bodies not expanded.'),
                     PROFILE),
                    (dated(lambda a: a.tab in ('posts', 'replies', 'replies-only', 'media'),
                           'Use --tab posts, replies, replies-only or media, or remove --since/--until.'),), 'user',
                    operations.user, operations.profile_id, label=lambda a: f'user {a.tab}',
                    fixes=signed(lambda a: 'Run refresh, then retry; or use --tab replies-only, which is unsigned but mixes in some non-reply posts.'
                                 if a.tab == 'replies' else None)),
    'about': Surface('Read one or several profile cards in one request.',
                     (chars('bio'), OUT, Arg(('target',), dict(nargs='+', help='One or more @handles or x.com profile URLs, read together in one request; numeric user IDs are not accepted.'))),
                     (), 'user', operations.about, finish=operations.unresolved_handles, rows='user', continuable=False,
                     limit=lambda a: len(a.target)),
    'post': Surface('Open a post with its parents and replies, or fetch several posts by ID without threads.',
                    (limit('Replies', 20, '; the post and its parents are always shown'),
                     chars('parent and reply text', '; the opened post is always shown in full'), OUT, after(),
                     sort('top', 'recent', default='top', help='Reply order, default top (X ranking); recent is newest first.'),
                     Arg(('target',), dict(nargs='+', help='x.com post URL or numeric post ID. Several IDs fetch just those posts, without replies, and refuse --limit, --sort and --after.'))),
                    (Rule(lambda a, g: batch(a) and g['limit'] is not None, 'Batch post lookup returns every requested post and has no --limit.',
                          'Remove --limit, or open one post for replies.', early=True),
                     Rule(lambda a, g: batch(a) and (g['sort'] is not None or g['after'] is not None), 'Batch post lookup has no replies or continuation.',
                          'Remove --sort and --after, or open one post for its replies.')),
                    'post', operations.post, finish=operations.thread_completeness, continuable=lambda a: not batch(a),
                    label=lambda a: 'post' if batch(a) else f'post {a.sort}',
                    limit=lambda a: len(a.target) if batch(a) else 20),
    'quotes': Surface('Find posts quoting a post; spends the search bucket.',
                      (limit('Quoting posts', 10), chars('post text'), OUT, after(), POST), (), 'post', operations.quotes),
    'reposts': Surface('Read the accounts that reposted a post.', (*ACCOUNTS, POST), (), 'post', operations.reposts,
                       rows='user', sparse=True),
    'search': Surface('Search posts, accounts or media; X search operators pass through unchanged.',
                      (limit('Posts or accounts', 10), chars('post text or bio'), OUT, after(),
                       sort('top', 'latest', default=lambda a: 'latest' if a.type != 'users' else None,
                            help='Post order, default latest (newest first); top is X ranking. Not with --type users or media, which have one ranking each.'),
                       Arg(('target',), dict(help='Search text; X operators such as from:, since:, until: and min_faves: pass through unchanged.')),
                       Arg(('--type',), dict(choices=['posts', 'users', 'media'], help='Product: posts (default), users (accounts, People ranking) or media. All three spend the one search bucket.'), 'posts'),
                       Arg(('--in',), dict(dest='scope', choices=['communities'], help='Search posts across all communities, newest first; not with --type or --sort.'))),
                      (Rule(lambda a, g: a.type == 'media' and g['sort'] is not None, 'Media search has one ranking; --sort would not change it.',
                            'Remove --sort for --type media.'),
                       Rule(lambda a, g: a.type == 'users' and g['sort'] is not None, 'Account search uses X People ranking, not top/latest post sorting.',
                            'Omit --sort for --type users.'),
                       Rule(lambda a, g: a.scope and (a.type != 'posts' or a.sort != 'latest'), 'Community search only supports posts/latest.',
                            'Community search reads posts newest first: remove --type and --sort, or drop --in communities.')),
                      operation=operations.search, rows=lambda a: 'user' if a.type == 'users' else 'tweet',
                      sparse=lambda a: a.type == 'users',
                      label=lambda a: 'search ' + ('in=communities' if a.scope else {'users': 'rank=people', 'media': 'product=media'}.get(a.type, a.sort))),
    'graph': Surface("Read an account's following, followers, verified followers, or followers you know.",
                     (*ACCOUNTS, PROFILE,
                      Arg(('relation',), dict(choices=['following', 'followers', 'verified', 'known'],
                                              help='Which list: following, followers (signed request), verified (their verified followers) or known (their followers whom you follow).'))),
                     (), 'user', operations.graph, operations.profile_id, rows='user', sparse=True, label=lambda a: f'graph {a.relation}',
                     fixes=signed(lambda a: 'Run refresh, then retry. graph <handle> following is no substitute: whom they follow is a different question from who follows them.'
                                  if a.relation == 'followers' else None)),
    'me': Surface('Read your own bookmarks or liked posts.',
                  (*POSTS, Arg(('collection',), dict(choices=['bookmarks', 'likes'], help='Which of your collections: bookmarks or likes.'))),
                  operation=operations.collection, prepare=operations.viewer_likes, personal=True, label=lambda a: f'me {a.collection}'),
    'list': Surface("Read a list's posts, members or information card.",
                    (limit('Posts or members', 10), chars('post text, bio or list description'), OUT, after(' Not with --tab about.'),
                     *dates('--tab posts'),
                     tab('posts', 'members', 'about', help='Tab, default posts: members lists accounts; about is the list card, read in one request.'),
                     Arg(('target',), dict(help='x.com/i/lists URL or numeric list ID.'))),
                    (NO_AFTER, dated(lambda a: a.tab == 'posts', 'Use --tab posts, or remove --since/--until.')), 'list', operations.listing,
                    rows=lambda a: {'posts': 'tweet', 'members': 'user', 'about': 'place'}[a.tab], label=lambda a: f'list {a.tab}'),
    'trends': Surface('Read trends and events from an Explore tab; other item types are counted.',
                      (limit('Trends', 10), chars('trend description'), OUT, after(),
                       tab('trending', 'foryou', 'news', 'sports', 'entertainment', help='Explore tab, default trending.')),
                      operation=operations.trends, fetch=operations.explore, rows='trend', label=lambda a: f'trends {a.tab}'),
    'community': Surface("Read a community's posts, media, or information card with member roles.",
                         (limit('Posts or members', 10), chars('post text, bio or community description'), OUT, after(' Not with --tab about.'),
                          tab('posts', 'media', 'about', help='Tab, default posts: media, or about for the card and member roles.'),
                          sort('top', 'recent', default='top', help='Post order for --tab posts, default top (X ranking); recent is newest first.'),
                          Arg(('target',), dict(help='x.com/i/communities URL or numeric community ID.'))),
                         (Rule(lambda a, g: a.tab != 'posts' and g['sort'] is not None, 'Sorting only applies to community posts.',
                               'Remove --sort, or use --tab posts.'), NO_AFTER),
                         'community', operations.community, operations.community_card,
                         rows=lambda a: 'user' if a.tab == 'about' else 'tweet', continuable=lambda a: a.tab != 'about',
                         label=lambda a: f'community {a.tab}' + (f' {a.sort}' if a.tab == 'posts' else '')),
    'communities': Surface('Browse posts from communities, each with a link to its community.', POSTS, operation=operations.communities),
    'doctor': Surface('Report a block without any request; otherwise re-read the login cookie against the cached viewer, then show cache ages, the Viewer bucket, the account window and the cache location.',
                      (Arg(('--unblock',), dict(action='store_true', help='After resolving a challenge or lock in Aside, clear it, then diagnose; rate limits still apply.')),),
                      runner=lambda args: summary(maintenance.doctor(args))),
    'refresh': Surface('Mine current read-query IDs and signatures, then verify two operations before saving.',
                       runner=lambda args: summary(maintenance.refresh(args))),
    'schema': Surface('Describe the output without any request: the topic list, or one topic.',
                      (Arg(('topic',), dict(nargs='?', choices=list(TOPICS), help='Record fields for tweet, user, media, list, community or trend; envelope: result fields, stop reasons, exit codes and error classes; export: the --out file. Without a topic: the topic list.')),),
                      runner=lambda args: schema(args.topic, EXITS, text=not args.json)),
}
UNSET = ('limit', 'after', 'since', 'until', 'tab', 'sort', 'feed', 'type', 'scope', 'relation', 'collection', 'target')


class Wide(argparse.HelpFormatter):
    """Help that never folds a sentence and keeps the line breaks it was written with."""

    def __init__(self, prog):
        super().__init__(prog, max_help_position=30, width=10_000)

    def _fill_text(self, text, width, indent):
        return ''.join(indent + line for line in text.splitlines(keepends=True))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TwitterError(2, message, parse_fix(message))


def parse_fix(message):
    """A fix naming the argument argparse refused."""
    if match := re.match(r"argument (\S+): invalid choice: \S+ \(choose from (.+)\)", message):
        return f'Pass {match[1]} one of: ' + match[2].replace("'", '') + '.'
    if match := re.match(r'argument (\S+): invalid int value', message):
        return f'Pass {match[1]} a whole number.'
    if match := re.match(r'argument (\S+): expected one argument', message):
        return f'Give {match[1]} a value.'
    if match := re.match(r'unrecognized arguments: (.+)', message):
        return f'Remove {match[1]}; the command\'s --help lists the options it takes.'
    if match := re.match(r'the following arguments are required: (.+)', message):
        return f'Add {match[1]}; the command\'s --help shows the order.'
    return 'Read the command --help for valid options.'


def parser():
    p = Parser(description='Read-only X (Twitter) via the logged-in Aside u0 browser.', formatter_class=Wide,
               epilog='Exit codes; every error also carries a recovery fix:\n' + ''.join(f'  {code}  {meaning}\n' for code, meaning in EXITS.items()))
    subs = p.add_subparsers(dest='command', required=True)
    for name, surface in SURFACES.items():
        sub = subs.add_parser(name, help=surface.help, description=surface.help, formatter_class=Wide)
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
    given = args.given = dict(vars(args))
    args.explicit_limit = args.limit is not None
    if args.out and args.after is not None:
        raise TwitterError(2, '--out resumes from its own page commits.', 'Repeat the same --out command without --after.')
    if args.after is not None and not valid_handle(args.after):
        raise TwitterError(2, 'Continuation handles are six lowercase letters or digits.',
                           'Copy --after from the latest more: line; a numbered handle from an older version no longer works, so rerun without --after.')
    refuse([rule for rule in surface.rules if rule.early], args, given)
    for key in ('limit', 'chars'):
        if getattr(args, key) is not None and getattr(args, key) < 1:
            raise TwitterError(2, f'{key} must be positive.', f'Pass --{key} 1 or more.')
    for arg in sorted(surface.args, key=lambda arg: callable(arg.default)):
        if arg.default is not None and getattr(args, arg.dest) is None:
            setattr(args, arg.dest, value(arg.default, args))
    refuse([rule for rule in surface.rules if not rule.early], args, given)
    for key in ('since', 'until'):
        if getattr(args, key):
            normalized = timestamp(getattr(args, key) + 'T00:00:00+00:00' if len(getattr(args, key)) == 10 else getattr(args, key))
            if not normalized:
                raise TwitterError(2, f'Invalid {key} date.', f'Pass --{key} as YYYY-MM-DD or an ISO timestamp.')
            setattr(args, key, normalized)
    if args.since and args.until and args.since >= args.until:
        raise TwitterError(2, 'since must precede until.', 'Pass a --since earlier than --until; --until is exclusive.')
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


def more_command(args, handle):
    """The next call: positionals, the options that were typed, --limit always (the next display target), then --after."""
    parts = [args.command]
    for arg in SURFACES[args.command].args:
        typed = args.given.get(arg.dest)
        if not arg.flags[0].startswith('-'):
            parts.extend(typed if isinstance(typed, list) else [typed])
        elif typed is not None and arg.dest not in ('limit', 'chars', 'after', 'out'):
            parts.extend([arg.flags[0], str(typed)])
    parts += ['--limit', str(args.limit)]
    if args.given.get('chars') is not None:
        parts += ['--chars', str(args.chars)]
    parts += ['--after', handle] + (['--json'] if args.json else [])
    return invocation() + ' ' + shlex.join(parts)


def emit(result, args):
    code = result.pop('code', 0)
    result.pop('state', None)
    surface = SURFACES[args.command]
    if not surface.runner:
        result.setdefault('next', None)
        result.setdefault('warnings', [])
        result.setdefault('fetched_bytes', 0)
        result.setdefault('budget', {})
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(plain(result) if surface.runner else render(result, args, value(surface.rows, args), value(surface.label, args) or args.command))
    return code


def dispatch(args):
    surface = SURFACES[args.command]
    if surface.runner:
        return surface.runner(args)
    op, variables = surface.operation(args)
    try:
        result = browse(args, context_for(args, op), op, variables, rows=value(surface.rows, args), personal=surface.personal,
                        prepare=surface.prepare, fetch=surface.fetch, finish=surface.finish,
                        continuable=value(surface.continuable, args), sparse=value(surface.sparse, args))
    except TwitterError as error:
        error.fix = own_fix(surface, args, error.error) or error.fix
        raise
    if result.get('error'):
        result['fix'] = own_fix(surface, args, result['error']) or result['fix']
    if result.get('next_handle'):
        result['next'] = more_command(args, result['next_handle'])
    return result


def own_fix(surface, args, error):
    return value(surface.fixes.get(error), args)


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
