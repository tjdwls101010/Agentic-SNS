"""search: posts, communities or users, across Reddit or inside one community. The words go to Reddit as they are, so
its operators work; Reddit matches words loosely, so what comes back is Reddit's ranking of loose matches."""
from reddit import connect
from reddit.errors import RedditError
from reddit.reddit_web import SEARCH_SORTS, SEARCH_TYPES, parse_target, require, routes


def search(options):
    text = options['text']
    if not text.strip():
        raise RedditError(2, 'Search text must not be empty.', 'Pass the words to search for.')
    kind = options.get('type') or 'posts'
    sort = options.get('sort') or 'relevance'
    within = None
    if options.get('within'):
        if kind != 'posts':
            raise RedditError(2, '--in searches posts inside one community.', 'Drop --in, or search --type posts.')
        within = require(parse_target(options['within']), ('subreddit',), 'search --in').sub
    if kind != 'posts' and (options.get('since') or options.get('until') or options.get('time')):
        raise RedditError(2, '--since, --until and --time apply to posts.', 'Drop them, or search --type posts.')
    identity = {'type': kind, 'sort': sort, 'time': options.get('time'), 'within': f'r/{within}' if within else None,
                'nsfw': bool(options.get('nsfw')) or None, 'since': options.get('since'), 'until': options.get('until')}
    words = (['--in', f'r/{within}'] if within else []) + (['--nsfw'] if options.get('nsfw') else [])

    def read(connection, state, out):
        return connect.read_pages(connection, options, identity, state, out, command='search', target=text, words=words,
                          request=lambda after: routes.search(text, kind, sort, options.get('time'), within,
                                                              bool(options.get('nsfw')), after))

    return connect.run(options, command='search', target=text, identity=identity, reader=read)


__all__ = ['SEARCH_SORTS', 'SEARCH_TYPES', 'search']
