"""Argument parsing and dispatch for the self-contained Threads reader."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

if not __package__:
    directory = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('threads_skill', directory / '__init__.py',
                                                submodule_search_locations=[str(directory)])
    package = importlib.util.module_from_spec(spec)
    sys.modules['threads_skill'] = package
    spec.loader.exec_module(package)
    __package__ = 'threads_skill'

from ._errors import ThreadsError
from ._target import parse_target


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ThreadsError(2, message)


def positive(value):
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Expected a positive integer.')


def parser():
    root = Parser(description="Read Threads through the logged-in Aside account; local budgets are not server allowances.",
        epilog='Exit: 0 success; 2 arguments; 3 Aside; 4 login; 5 blocked; 6 query/transport; 7 empty; 8 partial; 9 unavailable. Each error includes its fix.')
    subs = root.add_subparsers(dest='command', required=True, help='The Threads surface to read')
    descriptions = {
        'home': 'Read the for-you or following home feed.', 'user': 'Read a profile activity tab.',
        'about': 'Read a profile and relationship counts (two requests).',
        'post': 'Read the full post, parent chain and first reply batch (one page; no further sibling pagination).',
        'graph': 'Read followers (server sample) or following (paginated).',
        'search': 'Search posts, tags or accounts.', 'me': 'Read the first batch of your liked or saved posts.',
        'doctor': 'Check Aside, login, local protection and registry age (one request).',
        'refresh': 'Discover and verify rotated queries before saving an override.',
        'schema': 'Describe the output objects without making any requests.'}
    for command, description in descriptions.items():
        p = subs.add_parser(command, help=description, description=description)
        p.add_argument('--json', action='store_true', help='Emit one JSON document including completeness and local budget')
        if command in ('user', 'about', 'post', 'graph'):
            p.add_argument('target', help='Threads @handle or URL' if command != 'post' else 'Post URL or shortcode (shortcode resolution costs an extra request)')
        if command not in ('doctor', 'refresh', 'schema'):
            p.add_argument('--limit', type=positive, default=None, help='Maximum displayed records; explicit collection allows up to 40 local requests')
            p.add_argument('--chars', type=int, default=180, help='Text preview length; 0 means full text, post body is always full')
            p.add_argument('--out', default=None, help='Private NDJSON file with page commits; repeat the same command and file to resume')
            if command not in ('post', 'about'):
                p.add_argument('--after', type=positive, default=None, help='Opaque local handle from the complete more: command; retains undisplayed records')
        if command == 'home':
            p.add_argument('--feed', choices=['foryou', 'following'], default=None, help='Home algorithm; default foryou')
        if command == 'user':
            p.add_argument('--tab', choices=['threads', 'replies', 'reposts', 'media'], default=None, help='Profile activity tab; default threads')
        if command in ('home', 'user'):
            p.add_argument('--since', default=None, help='Inclusive ISO date/time lower bound, filtered locally; chronological surfaces only')
            p.add_argument('--until', default=None, help='Exclusive ISO date/time upper bound, filtered locally; no server-side filtering')
        if command in ('post', 'search'):
            p.add_argument('--sort', choices=['top', 'recent'], default=None, help='Default top; recent post replies may overlap with top replies')
        if command == 'graph':
            p.add_argument('relation', choices=['followers', 'following'], help='Followers is capped at 20 by the server; following can continue')
        if command == 'search':
            p.add_argument('query', help='Search text')
            p.add_argument('--type', choices=['posts', 'users'], default=None, help='Result kind; default posts; users has one batch only')
            p.add_argument('--tag', action='store_true', help='Search tagged posts instead of the default surface')
        if command == 'me':
            p.add_argument('collection', choices=['liked', 'saved'], help='Personal collection; only the first batch can be requested')
        if command == 'doctor':
            p.add_argument('--unblock', action='store_true', help='After checking Threads in Aside, make one login probe; clear a checkpoint only if it succeeds')
        if command == 'refresh':
            p.add_argument('--capture', action='store_true', help='Observe one app tab for six lazy queries; bootstrap requests and app mutations are outside CLI control')
            p.add_argument('--post', default=None, help='Public post URL to seed SSR verification and SPA capture when your own profile has no posts')
    return root


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if getattr(args, 'chars', 0) < 0:
            raise ThreadsError(2, '--chars cannot be negative.')
        if hasattr(args, 'target'):
            args.target = parse_target(args.target, 'post' if args.command == 'post' else 'user')
        if args.command in ('doctor', 'refresh', 'schema'):
            from ._cmds_meta import run
        elif args.command in ('post', 'about'):
            from ._cmds_post import run
        else:
            from ._cmds_browse import run
        result = run(args)
        code = result.pop('code', 0)
        if args.json or args.command in ('doctor', 'refresh', 'schema'):
            print(json.dumps(result, ensure_ascii=False))
        else:
            from ._render import render
            print(render(result, args))
        return code
    except ThreadsError as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False))
        return error.code
    except (OSError, ValueError) as error:
        print(json.dumps(ThreadsError(6, f'Local operation failed ({type(error).__name__}).',
                                    'Check local storage and command arguments.').as_dict()))
        return 6


if __name__ == '__main__':
    sys.exit(main())
