#!/usr/bin/env python3
"""Read X through Aside. This entry point only validates and dispatches."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

if not __package__:
    root = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('twitter_skill', root / '__init__.py', submodule_search_locations=[str(root)])
    package = importlib.util.module_from_spec(spec)
    sys.modules['twitter_skill'] = package
    spec.loader.exec_module(package)
    __package__ = 'twitter_skill'

from ._errors import TwitterError
from ._entities import timestamp
from ._target import parse

DESCRIPTIONS = {
    'home': 'Read your personalized For you or chronological Following feed.',
    'user': 'Read a profile tab. replies-only is an ungated, mixed posts/replies alternative.',
    'about': 'Read one or several profile cards in one request.',
    'post': 'Open a post with parents and replies; several IDs fetch posts without threads.',
    'quotes': 'Find posts quoting a post; uses the shared search bucket.',
    'reposts': 'Read the accounts that reposted a post.',
    'search': 'Search posts, accounts or media. X search operators pass through unchanged.',
    'graph': 'Read following, followers, verified followers or followers you know.',
    'me': 'Read your bookmarks or liked posts.',
    'list': 'Read list posts, members or its information card.',
    'trends': 'Read trends and events from an Explore tab; other item types are counted.',
    'community': 'Read community posts, media or information and member roles.',
    'communities': 'Browse community posts with links to their communities.',
    'doctor': 'Check Aside, your viewer, protection state and cache ages.',
    'refresh': 'Mine current read-query IDs and signatures, then verify two operations before saving.',
    'schema': 'Describe the normalized output fields without making requests.'}
TABS = {'user': ['posts', 'replies', 'replies-only', 'media', 'highlights', 'articles'],
        'list': ['posts', 'members', 'about'], 'community': ['posts', 'media', 'about'],
        'trends': ['trending', 'foryou', 'news', 'sports', 'entertainment']}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TwitterError(2, message, 'Read the command --help for valid options.')


def parser():
    p = Parser(description='Read-only X (Twitter) via the logged-in Aside u0 browser.',
               epilog='Exit: 0 success; 2 arguments; 3 Aside; 4 session; 5 blocked/rate/window; '
                      '6 API drift; 7 empty; 8 partial/budget; 9 unavailable. Errors include a recovery fix.')
    subs = p.add_subparsers(dest='command', required=True)
    for name, description in DESCRIPTIONS.items():
        sub = subs.add_parser(name, help=description, description=description)
        sub.add_argument('--json', action='store_true', help='Emit exactly one JSON document, including partial results and recovery.')
        if name in ('doctor', 'refresh', 'schema'):
            if name == 'doctor':
                sub.add_argument('--unblock', action='store_true', help='Clear a challenge/lock after checking X in Aside; rate limits still apply.')
            continue
        sub.add_argument('--limit', type=int, default=None, help='Display target: 10 items; single post 20 replies. Unavailable for about/batch post (all results). Explicit limits allow 40 requests.')
        sub.add_argument('--chars', type=int, default=None, help='Text characters per item, default 280; the focal post is always full.')
        sub.add_argument('--out', default=None, metavar='FILE', help='Commit whole date-eligible pages as private NDJSON; repeat the same command to resume.')
        sub.add_argument('--after', type=int, default=None, metavar='N', help='Resume a numbered more: handle, consuming cached items before requesting another page.')
        if name in ('user', 'home', 'list'):
            for flag in ('since', 'until'):
                sub.add_argument('--' + flag, default=None, help=f'Client date filter ({flag} ISO date/time); chronological tabs only. until is exclusive.')
        if name in TABS:
            sub.add_argument('--tab', choices=TABS[name], default=None, help=f'Tab to read; default {TABS[name][0]}.')
        if name == 'home':
            sub.add_argument('--feed', choices=['foryou', 'following'], default=None, help='Feed to read, default foryou.')
        if name in ('post', 'search', 'community'):
            choices = ['top', 'latest'] if name == 'search' else ['top', 'recent']
            sub.add_argument('--sort', choices=choices, default=None, help='Server ranking; default latest for search, top otherwise.')
        if name == 'search':
            sub.add_argument('target', help='Search text, including X from:, since:, until: or engagement operators.')
            sub.add_argument('--type', choices=['posts', 'users', 'media'], default=None, help='Search product, default posts; all share one operation bucket.')
            sub.add_argument('--in', dest='scope', choices=['communities'], default=None, help='Search posts across ALL communities; only posts/latest supported.')
        elif name == 'graph':
            sub.add_argument('target', help='@handle or profile URL; numeric user IDs are unavailable.')
            sub.add_argument('relation', choices=['following', 'followers', 'verified', 'known'], help='Relationship list to read.')
        elif name == 'me':
            sub.add_argument('collection', choices=['bookmarks', 'likes'], help='Your private collection to read.')
        elif name not in ('home', 'trends', 'communities'):
            sub.add_argument('target', nargs='+' if name in ('about', 'post') else None, help='@handle/profile URL for profiles; X URL or numeric ID for other targets.')
    return p


def validate(args):
    if args.command in ('doctor', 'refresh', 'schema'):
        return args
    args.explicit_limit = args.limit is not None
    if args.after is not None and args.after < 1:
        raise TwitterError(2, 'Continuation handles must be positive.', 'Copy the complete more: command.')
    if args.command == 'about' and args.limit is not None:
        raise TwitterError(2, 'about returns every requested profile and has no --limit.', 'Remove --limit.')
    if args.command == 'post' and len(args.target) > 1 and args.limit is not None:
        raise TwitterError(2, 'Batch post lookup returns every requested post and has no --limit.', 'Remove --limit, or open one post for replies.')
    if args.limit is not None and args.limit < 1 or args.chars is not None and args.chars < 1:
        raise TwitterError(2, 'limit and chars must be positive.', 'Choose a positive display target.')
    for key in ('since', 'until', 'tab', 'sort', 'feed', 'type', 'scope', 'relation', 'collection', 'target'):
        if not hasattr(args, key):
            setattr(args, key, None)
    args.tab = args.tab or TABS.get(args.command, [None])[0]
    args.feed = args.feed or ('foryou' if args.command == 'home' else None)
    if args.command == 'community' and args.tab != 'posts' and args.sort is not None:
        raise TwitterError(2, 'Sorting only applies to community posts.')
    if args.command == 'post' and len(args.target) > 1 and (args.sort is not None or args.after is not None):
        raise TwitterError(2, 'Batch post lookup has no replies or continuation.')
    args.sort = args.sort or ('latest' if args.command == 'search' else 'top' if args.command in ('post', 'community') else None)
    args.type = args.type or ('posts' if args.command == 'search' else None)
    if args.scope and (args.type != 'posts' or args.sort != 'latest'):
        raise TwitterError(2, 'Community search only supports posts/latest.')
    if args.after and (args.command in ('about', 'trends') or args.command in ('list', 'community') and args.tab == 'about'):
        raise TwitterError(2, 'This lookup does not support --after.')
    allowed_dates = args.command == 'user' and args.tab in ('posts', 'replies', 'replies-only', 'media') or args.command == 'list' and args.tab == 'posts' or args.command == 'home' and args.feed == 'following'
    if (args.since or args.until) and not allowed_dates:
        raise TwitterError(2, 'Date windows require a chronological timeline tab.')
    for key in ('since', 'until'):
        if getattr(args, key):
            normalized = timestamp(getattr(args, key) + 'T00:00:00+00:00' if len(getattr(args, key)) == 10 else getattr(args, key))
            if not normalized:
                raise TwitterError(2, f'Invalid {key} date.', 'Use YYYY-MM-DD or an ISO timestamp.')
            setattr(args, key, normalized)
    if args.since and args.until and args.since >= args.until:
        raise TwitterError(2, 'since must precede until.')
    kinds = {'user': 'user', 'about': 'user', 'graph': 'user', 'post': 'post', 'quotes': 'post', 'reposts': 'post', 'list': 'list', 'community': 'community'}
    if args.command in kinds:
        values = args.target if isinstance(args.target, list) else [args.target]
        args.targets = [parse(v, kinds[args.command]) for v in values]
    args.limit = args.limit or (len(args.target) if args.command == 'about' or args.command == 'post' and len(args.target) > 1 else 20 if args.command == 'post' else 10)
    args.chars = args.chars or 280
    return args


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = validate(parser().parse_args(argv))
        from ._output import emit
        if args.command in ('doctor', 'refresh', 'schema'):
            from ._cmds_meta import run
        else:
            from ._browse import run
        return emit(run(args), args)
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
