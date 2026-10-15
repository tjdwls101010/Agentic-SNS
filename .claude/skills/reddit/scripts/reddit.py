"""Argument parsing and dispatch for the self-contained read-only Reddit skill."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

if not __package__:
    directory = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('reddit_skill', directory / '__init__.py', submodule_search_locations=[str(directory)])
    package = importlib.util.module_from_spec(spec)
    sys.modules['reddit_skill'] = package
    spec.loader.exec_module(package)
    __package__ = 'reddit_skill'

from ._errors import RedditError
from ._target import parse_target

TARGETS = {'sub': {'subreddit', 'subreddits'}, 'post': {'post', 'share'},
           'comments': {'post', 'comment', 'share'}, 'user': {'user'},
           'about': {'subreddit', 'user'}, 'related': {'post'}}
SORTS = {'home': ['best', 'hot', 'new', 'top', 'rising'],
         'sub': ['hot', 'new', 'top', 'rising', 'controversial'],
         'post': ['best', 'top', 'new', 'controversial', 'old', 'qa'],
         'comments': ['best', 'top', 'new', 'controversial', 'old', 'qa'],
         'user': ['new', 'hot', 'top', 'controversial'],
         'search': ['relevance', 'hot', 'top', 'new', 'comments']}
TIMES = ['hour', 'day', 'week', 'month', 'year', 'all']


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RedditError(2, message)


def positive(value):
    try:
        result = int(value)
        if result > 0:
            return result
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('must be a positive integer')


def nonnegative(value):
    if value == '0':
        return 0
    return positive(value)


def parser():
    root = Parser(description='Read Reddit through the logged-in Aside u0 browser. GET only; cookies stay in Aside.',
                  epilog='Exit codes: 0 success; 2 arguments; 3 Aside; 4 login; 5 blocked (do not retry); 6 response drift/service; 7 empty; 8 partial; 9 missing/closed. Use schema for fields. Cursors and files retain private activity; remove them after use.')
    commands = root.add_subparsers(dest='command', required=True)
    descriptions = {'home': 'Read your personalized home feed.', 'sub': 'Read a community or r/a+b combined listing.',
                    'post': 'Open a post: full body and the first comment batch; one request caches up to 500 comments.',
                    'comments': 'Read cached comments first, then expand missing branches; a comment URL opens that branch.',
                    'user': 'Read a redditor\'s public activity.', 'me': 'Read your subscriptions, saved or upvoted items.',
                    'about': 'Read a community sidebar and rules, or a user profile.',
                    'search': 'Search posts, communities or users. Empty search is retried once within budget.',
                    'related': 'Read other discussions of the same link.',
                    'doctor': 'Check Aside login, request budget, block and cache. Unblock only after clearing a browser challenge.',
                    'schema': 'Describe normalized object fields; no network request.'}
    for name, description in descriptions.items():
        cmd = commands.add_parser(name, help=description, description=description)
        cmd.add_argument('--json', action='store_true', help='Print exactly one JSON document, preserving received text.')
        if name in TARGETS:
            cmd.add_argument('target', help='Accepted targets: ' + ', '.join(sorted(TARGETS[name])) + '; use explicit r/name or u/name for about.')
        if name == 'me':
            cmd.add_argument('surface', choices=['subs', 'saved', 'upvoted'], help='Your own read-only collection.')
        if name == 'search':
            cmd.add_argument('query', help='Search text, quoted as one argument.')
            cmd.add_argument('--in', dest='within', help='Restrict post search to one r/name community.')
            cmd.add_argument('--type', choices=['posts', 'subs', 'users'], default='posts', help='Result kind (default: posts).')
            cmd.add_argument('--nsfw', action='store_true', help='Include over-18 search results.')
        if name == 'user':
            cmd.add_argument('--type', choices=['overview', 'posts', 'comments'], default='overview', help='Activity kind (default: overview).')
        if name in SORTS:
            cmd.add_argument('--sort', choices=SORTS[name], default=None, help='Server ordering (default: ' + SORTS[name][0] + '); continuation retains its ordering.')
            if name not in ('post', 'comments'):
                cmd.add_argument('--time', choices=TIMES, default=None, help='Server time range, separate from the client date window.')
        if name not in ('doctor', 'schema'):
            cmd.add_argument('--limit', type=positive, default=None, help='New items to show (default: 5 listing / 25 comments); explicit goals allow up to 60 requests.')
            cmd.add_argument('--chars', type=nonnegative, default=180, help='Normalized text characters per item (default: 180); post body is shown in full.')
            cmd.add_argument('--out', help='Commit full records to private NDJSON; rerun identical query/file to resume. Screen shows a summary.')
            cmd.add_argument('--after', type=positive, help='Local numbered continuation handle from more:, never a Reddit fullname.')
        if name in ('sub', 'user', 'search', 'home'):
            cmd.add_argument('--since', help='Inclusive ISO date/time start, client filter; requires --sort new. Listings may end before the window.')
            cmd.add_argument('--until', help='Inclusive ISO date/time end, client filter; requires --sort new.')
        if name in ('post', 'comments'):
            cmd.add_argument('--depth', type=nonnegative, default=2, help='Display depth, root=0 (default: 2); raise on continuation to reveal cached deep replies.')
            cmd.add_argument('--context', type=nonnegative, default=0, help='Ancestors requested for a linked comment; exact comment is highlighted regardless of display depth.')
        if name == 'doctor':
            cmd.add_argument('--unblock', action='store_true', help='Clear a challenge block after solving it in Aside; rate limits expire automatically.')
    return root


def validate(args):
    if args.command in TARGETS:
        if args.command == 'about' and not any(s in args.target for s in ('/', '://')):
            raise RedditError(2, 'about requires an explicit community or user.', 'Prefix r/ or u/, for example about r/python.')
        args.parsed_target = parse_target(args.target)
        if args.parsed_target.kind not in TARGETS[args.command]:
            raise RedditError(2, 'Target kind is not accepted by this command.', 'Use one of: ' + ', '.join(TARGETS[args.command]))
    if getattr(args, 'within', None):
        if parse_target(args.within).kind != 'subreddit' or args.type != 'posts':
            raise RedditError(2, '--in requires one r/name community and --type posts.')
    if getattr(args, 'since', None) or getattr(args, 'until', None):
        if args.sort not in (None, 'new'):
            raise RedditError(2, 'Date windows require --sort new.')
        args.sort = 'new'
        from ._listing import parse_date
        start, end = parse_date(args.since), parse_date(args.until)
        if start is not None and end is not None and start > end:
            raise RedditError(2, 'Use an ISO date/time window with since <= until.')


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        validate(args)
        if args.command in ('doctor', 'schema', 'about'):
            from ._cmds_meta import run
        elif args.command in ('post', 'comments'):
            from ._cmds_thread import run
        else:
            from ._cmds_browse import run
        from ._cmds_common import emit
        return emit(run(args), args)
    except RedditError as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False))
        return error.code
    except (OSError, UnicodeError):
        error = RedditError(8, 'Local reading state could not be read or saved.', 'Check cache/output permissions and available disk space, then resume the committed file or reopen the target.')
        print(json.dumps(error.as_dict()))
        return error.code
    except KeyboardInterrupt:
        error = RedditError(8, 'Read interrupted. Committed pages remain available.')
        print(json.dumps(error.as_dict()))
        return error.code


if __name__ == '__main__':
    sys.exit(main())
