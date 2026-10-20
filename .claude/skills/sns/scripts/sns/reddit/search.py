"""search: posts, communities or users, across Reddit or inside one community. The words go to Reddit as they are, so
its operators work; Reddit matches words loosely, so what comes back is Reddit's ranking of loose matches."""
from sns import reading
from sns.errors import SnsError

from sns.reddit import web
from sns.reddit.listing import read_pages, resolve_sort, window_of


def search(platform, invocation):
    options = invocation.options
    text = options['text']
    if not text.strip():
        raise SnsError('argument', 'Search text must not be empty.', 'Pass the words to search for.')
    kind = options.get('type') or 'posts'
    within = None
    if options.get('within'):
        if kind != 'posts':
            raise SnsError('argument', '--in searches posts inside one community.',
                           'Drop --in, or search --type posts.')
        within = web.require(web.parse_target(options['within']), 'search --in').sub
    if kind != 'posts' and (options.get('since') or options.get('until') or options.get('time')):
        raise SnsError('argument', '--since, --until and --time apply to posts.', 'Drop them, or search --type posts.')
    shown, sort, sort_words = resolve_sort(options, 'relevance')
    identity = {'sort': shown, 'time': options.get('time'), 'type': kind,
                'within': f'r/{within}' if within else None, 'nsfw': True if options.get('nsfw') else None}
    words = ['--type', kind] + sort_words + (['--time', options['time']] if options.get('time') else []) \
        + (['--in', f'r/{within}'] if within else []) + (['--nsfw'] if options.get('nsfw') else [])
    order = 'newest_first' if sort == 'new' else 'ranked'

    def read(connection, state, out):
        return read_pages(connection, state, out, request=lambda after: web.routes.search(
            text, kind, sort, options.get('time'), within, bool(options.get('nsfw')), after), command='search',
            target=text, identity=identity, words=words, order=order)[0]

    return reading.run(platform, invocation, command='search', target=text, identity=identity, reader=read,
                       window=window_of(options, order))
