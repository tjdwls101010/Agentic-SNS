"""wiki: a community's wiki — one page in full, or its page list. Wiki pages count in their own Reddit bucket, not the
one listings and threads share; a read is tied to no handle or file, so the Reddit account is not checked first."""
from reddit import connect
from reddit.errors import RedditError
from reddit.reddit_web import parse_target, require


def wiki(options):
    target = require(parse_target(options['target']), ('subreddit', 'wiki'), 'wiki')
    page = options.get('page') or target.page
    if page and options.get('pages'):
        raise RedditError(2, '--pages lists the wiki; it takes no page name.', 'Drop the page name, or drop --pages.')
    if page is not None:
        page = parse_target(f'r/{target.sub}/wiki/{page}').page  # the same name rules as a wiki URL
    page = None if options.get('pages') else (page or 'index')
    name = f'r/{target.sub}/wiki' + (f'/{page}' if page else '')

    def read(connection, state, out):
        client = connection.network()
        record = client.wiki_page(target.sub, page) if page else client.wiki_index(target.sub)
        return {'results': [record], 'stop_reason': 'exhausted'}

    return connect.run(options, command='wiki', target=name, identity={}, reader=read, bound=False)
