"""wiki: a community's wiki — one page in full, or its page list. Wiki pages count in their own Reddit bucket, not the
one listings and threads share; a read is tied to no handle or file, so the Reddit account is not checked first."""
from sns import reading
from sns.errors import SnsError

from sns.reddit import web


def wiki(platform, invocation):
    options = invocation.options
    target = web.require(web.parse_target(options['target']), 'wiki')
    page = options.get('page') or target.page
    if page and options.get('pages'):
        raise SnsError('argument', '--pages lists the wiki; it takes no page name.',
                       'Drop the page name, or drop --pages.')
    if page is not None:
        page = web.parse_target(f'r/{target.sub}/wiki/{page}').page  # the same name rules as a wiki URL
    page = None if options.get('pages') else (page or 'index')
    name = f'r/{target.sub}/wiki' + (f'/{page}' if page else '')

    def read(connection, state, out):
        client = connection.client
        record = client.wiki_page(target.sub, page) if page else client.wiki_index(target.sub)
        return {'results': [record], 'stop_reason': 'exhausted'}

    return reading.run(platform, invocation, command='wiki', target=name, identity={}, reader=read, bound=False)
