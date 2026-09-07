"""Argument parsing and dispatch for the self-contained Naver Blog reader."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

if not __package__:
    directory = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('naver_blog_skill', directory / '__init__.py',
                                                  submodule_search_locations=[str(directory)])
    package = importlib.util.module_from_spec(spec)
    sys.modules['naver_blog_skill'] = package
    spec.loader.exec_module(package)
    __package__ = 'naver_blog_skill'

from ._errors import NaverBlogError
from ._target import parse_target


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise NaverBlogError(2, message)


def positive(value):
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Expected a positive integer.')


DESCRIPTIONS = {
    'search': 'Search all of Naver Blog for posts, blogs or tags.',
    'blog': "Read a blog's card, category tree, notices and popular posts (four requests).",
    'posts': 'List a blog\'s posts, one category, its notices or its popular posts.',
    'post': 'Read one post in full with its tags and same-category posts (two requests).',
    'comments': 'Read a post\'s comments and replies, newest first.',
    'find': 'Search inside one blog by text or by tag.',
    'buddies': 'Read your own neighbor list, or a blog\'s public one.',
    'home': 'Read your neighbors\' new posts (one page; Naver serves no more).',
    'topic': 'Browse the topic directory, or one topic\'s posts.',
    'monthly': 'Read the blogs of the month and the editors\' picks (two requests).',
    'doctor': 'Check Aside, the Naver login and local protection (one request).',
    'schema': 'Describe the output objects and stop reasons without making any request.',
}
READ_COMMANDS = ('search', 'blog', 'posts', 'post', 'comments', 'find', 'buddies', 'home', 'topic', 'monthly')
LISTING = ('search', 'posts', 'comments', 'find', 'buddies', 'home', 'topic')
# Only these can continue: the rest answer in one page or are a single card.
CONTINUABLE = ('search', 'posts', 'comments', 'find', 'buddies', 'topic')
COLLECTABLE = ('search', 'posts', 'post', 'comments', 'find', 'buddies', 'topic')
# Date windows need a listing whose items carry a date; home filters locally, search on the server.
WINDOWED = ('search', 'posts', 'find', 'home', 'topic')
DEFAULT_LIMIT = {'search': 10, 'posts': 10, 'comments': 20, 'find': 10, 'buddies': 20, 'home': 10, 'topic': 10}


def parser():
    root = Parser(
        prog='naver_blog.py',
        description='Read Naver Blog through the logged-in Aside account. '
                    'Naver publishes no rate limits, so every budget printed here is this tool\'s own count.',
        epilog='Exit: 0 success; 2 arguments; 3 Aside; 4 Naver login; 5 blocked; 6 transport or contract; '
               '7 an explicit empty result; 8 partial, budget or policy-restricted; '
               '9 target gone, private or owner-only. Every error carries its own fix.')
    subs = root.add_subparsers(dest='command', required=True, help='The Naver Blog surface to read')
    for command, description in DESCRIPTIONS.items():
        p = subs.add_parser(command, help=description, description=description)
        p.add_argument('--json', action='store_true',
                       help='Emit one JSON document with namespaced ids, stop_reason and the local budget')
        if command in READ_COMMANDS:
            p.add_argument('--chars', type=int, default=180,
                           help='Preview length per item; 0 means no clipping. A post body is never clipped')
        if command in LISTING:
            p.add_argument('--limit', type=positive, default=DEFAULT_LIMIT[command],
                           help=f'Maximum records to display (default {DEFAULT_LIMIT[command]}); '
                                'requests are capped separately')
        if command in CONTINUABLE:
            p.add_argument('--after', type=positive, default=None,
                           help='Continuation handle from the more: line. Naver resumes by page number, '
                                'so posts added since the first read can shift the boundary')
        if command in COLLECTABLE:
            p.add_argument('--out', default=None,
                           help='Private NDJSON file committed a page at a time; rerun the same command to resume')
        if command in WINDOWED:
            p.add_argument('--since', default=None, help='KST date YYYY-MM-DD, that day included')
            p.add_argument('--until', default=None, help='KST date YYYY-MM-DD, that whole day included')
        if command == 'search':
            p.add_argument('text', help='Search text')
            p.add_argument('--type', choices=['posts', 'blogs', 'tags'], default='posts',
                           help='What to search (default posts). Tag results carry no blog name')
            p.add_argument('--sort', choices=['sim', 'date'], default='sim',
                           help='Relevance or newest (default sim); posts and blogs only, not tags')
            p.add_argument('--own-money', action='store_true',
                           help='Only posts Naver marks as bought with the writer\'s own money; posts only')
        if command in ('blog', 'posts', 'find', 'buddies'):
            required = command != 'buddies'
            p.add_argument('target', nargs=None if required else '?', default=None,
                           help='Blog id or URL' + ('' if required else '; omit for your own neighbor list'))
        if command == 'blog':
            p.add_argument('--brief', action='store_true', help='Card and categories only (two requests)')
        if command == 'posts':
            p.add_argument('--category', default=None, help='Category number or name; a name costs one request')
            p.add_argument('--popular', action='store_true', help='The ten popular posts, the only surface with view counts')
            p.add_argument('--notices', action='store_true', help='Notice posts')
        if command in ('post', 'comments'):
            p.add_argument('target', help='Post URL or id/logNo')
        if command == 'post':
            p.add_argument('--comments', action='store_true', help='Also read the first page of comments')
        if command == 'find':
            p.add_argument('text', help='Text to search for inside this blog')
            p.add_argument('--tag', action='store_true', help='Search this blog\'s tags instead of its post text')
            p.add_argument('--sort', choices=['sim', 'date'], default='sim',
                           help='Relevance or newest (default sim); ignored by tag search, so --tag refuses it')
        if command == 'topic':
            p.add_argument('target', nargs='?', default=None,
                           help='Topic number or name; omit to list the topic directory')
            p.add_argument('--top', action='store_true', help='That topic\'s featured posts instead of its newest')
        if command == 'monthly':
            p.add_argument('--year', type=int, default=None, help='Year (default the current one)')
            p.add_argument('--month', type=int, default=None, help='Month 1-12 (default the current one)')
        if command == 'doctor':
            p.add_argument('--unblock', action='store_true',
                           help='Clear a local block, but only after one probe request succeeds; '
                                'the 10-minute window is kept either way')
    return root


def check(args):
    """Refuse an impossible combination before it costs a request."""
    if getattr(args, 'chars', 0) < 0:
        raise NaverBlogError(2, '--chars cannot be negative.')
    if args.command == 'search':
        if args.type == 'tags' and args.sort != 'sim':
            raise NaverBlogError(2, 'Tag search has no ordering.', 'Drop --sort, or search --type posts.')
        if args.type != 'posts' and args.own_money:
            raise NaverBlogError(2, '--own-money marks posts only.', 'Drop it, or search --type posts.')
        if args.type != 'posts' and (args.since or args.until):
            raise NaverBlogError(2, 'Date windows apply to post search only.',
                                 'Drop --since/--until, or search --type posts.')
    if args.command == 'posts':
        chosen = [name for name in ('category', 'popular', 'notices') if getattr(args, name)]
        if len(chosen) > 1:
            raise NaverBlogError(2, 'Choose one of --category, --popular and --notices.',
                                 'Run posts once per surface.')
        if args.target and args.target.category_no and args.category:
            raise NaverBlogError(2, 'That URL already names a category.',
                                 'Drop --category, or pass the blog id without the URL query.')
        if (args.popular or args.notices) and (args.since or args.until or args.after):
            raise NaverBlogError(2, 'Popular and notice lists are single pages with no date window.',
                                 'Drop --since/--until/--after.')
    if args.command == 'find' and args.tag and args.sort != 'sim':
        raise NaverBlogError(2, 'Tag search inside a blog ignores ordering.', 'Drop --sort, or drop --tag.')
    if args.command == 'topic' and args.top and (args.after or args.since or args.until):
        raise NaverBlogError(2, 'Featured posts are one page with no dates.', 'Drop --top, or drop the window.')
    if args.command == 'topic' and args.target is None and (args.after or args.top):
        raise NaverBlogError(2, 'The topic directory is one page.', 'Name a topic to read its posts.')
    if args.command == 'monthly' and args.month is not None and not 1 <= args.month <= 12:
        raise NaverBlogError(2, '--month is 1 to 12.')
    return args


def main(argv=None):
    try:
        args = check(parse_targets(parser().parse_args(argv)))
        if args.command in ('doctor', 'schema'):
            from ._cmds_meta import run
        elif args.command in ('search', 'post', 'comments', 'find'):
            from ._cmds_read import run
        else:
            from ._cmds_blog import run
        result = run(args)
        code = result.pop('code', 0)
        if args.command in ('doctor', 'schema'):
            print(json.dumps(result, ensure_ascii=False))
        elif args.json:
            from ._output import document
            print(json.dumps(document(args.command, result, budget=result.get('budget'),
                                      fetched_bytes=result.get('fetched_bytes', 0),
                                      next_command=result.get('next'),
                                      sections=result.get('sections')), ensure_ascii=False))
        else:
            from ._render import render
            print(render(result, args))
        return code
    except NaverBlogError as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False))
        return error.code
    except (OSError, ValueError) as error:
        print(json.dumps(NaverBlogError(6, f'Local operation failed ({type(error).__name__}).',
                                        'Check local storage and command arguments.').as_dict()))
        return 6


def parse_targets(args):
    kinds = {'blog': 'blog', 'posts': 'blog', 'find': 'blog', 'buddies': 'blog',
             'post': 'post', 'comments': 'post'}
    if args.command in kinds and getattr(args, 'target', None):
        args.target = parse_target(args.target, kinds[args.command])
    return args


if __name__ == '__main__':
    sys.exit(main())
