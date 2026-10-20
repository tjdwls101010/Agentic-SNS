"""search (posts, blogs, tags, clips; one blog's own search) and keywords.

What each kind of search honours was measured, and a combination a surface would silently ignore is refused before it
costs a request: post search takes an order, dates and the own-money flag; blog search only an order; tag search comes
newest first and ignores any order, so a date window is applied locally and closes on it; one blog's post search takes
an order and dates, its tag search neither; clip search takes an order and dates.
"""
from sns import reading
from sns.errors import SnsError

from sns.naver_blog import account, listing, web

DISPLAY = 10
# kind → (operation, the query key, takes --sort, takes dates, takes --own-money, server applies dates)
SURFACES = {
    ('posts', False): ('search_posts', 'keyword', True, True, True, True),
    ('blogs', False): ('search_blogs', 'keyword', True, False, False, False),
    ('tags', False): ('search_tags', 'query', False, True, False, False),
    ('clips', False): ('search_clips', 'keyword', True, True, False, True),
    ('posts', True): ('blog_search', 'query', True, True, False, True),
    ('tags', True): ('blog_tag_search', 'query', False, False, False, False),
}
_KINDS = {'posts': 'post search', 'blogs': 'blog search', 'tags': 'tag search', 'clips': 'clip search'}
_BUILD = {'blogs': web.blog_record, 'clips': web.clip_record}


def check(options):
    """The argument rules of search, before any request."""
    inside = bool(options.get('blog'))
    kind = options.get('type') or 'posts'
    if (kind, inside) not in SURFACES:
        raise SnsError('argument', f'One blog\'s own search finds posts or tags, not {kind}.',
                       'Drop --blog, or use --type posts or tags.')
    _, _, sorts, dates, own_money, _ = SURFACES[(kind, inside)]
    where = _KINDS[kind] + (' inside one blog' if inside else '')
    if options.get('sort') and not sorts:
        raise SnsError('argument', f'{where.capitalize()} has no order (Naver ignores one).', 'Drop --sort.')
    if (options.get('since') or options.get('until')) and not dates:
        raise SnsError('argument', f'{where.capitalize()} cannot be limited to dates.', 'Drop --since/--until.')
    if options.get('own_money') and not own_money:
        raise SnsError('argument', '--own-money (posts carrying Naver\'s 내돈내산 인증 card) filters Naver-wide post '
                                   'search only.', 'Drop --own-money.')
    if not ' '.join(options.get('text') or []).strip():
        raise SnsError('argument', 'Search text must not be empty.', 'Pass the words to search for.')


def search(platform, invocation):
    options = invocation.options
    text = ' '.join(options['text']).strip()
    kind = options.get('type') or 'posts'
    blog_text = options.get('blog')
    op, key, sorts, dates, _, server_dates = SURFACES[(kind, bool(blog_text))]
    sort = (options.get('sort') or 'sim') if sorts else None
    local = web.parse_target(blog_text, 'blog') if blog_text else None
    identity = {'type': kind, 'sort': sort, 'blog': local and (local.blog_id or 'naver.me/' + local.short),
                'own_money': True if options.get('own_money') else None}
    words = ['--type', kind] + (['--sort', sort] if options.get('sort') else []) + \
        (['--blog', blog_text] if blog_text else []) + (['--own-money'] if options.get('own_money') else [])
    # A surface Naver filters by date ends by itself; tags and --sort date come newest first, so a window closes on them.
    order = 'server' if server_dates else 'newest_first' if kind == 'tags' or sort == 'date' else 'ranked'

    def read(connection, state, out):
        client = connection.client
        ids = {key: text}
        if sort:
            ids['sortType'] = sort
        if blog_text:
            ids['blogId'] = listing.resumed(state, out).get('blog_id') or client.target(blog_text, 'blog').blog_id
        if server_dates:
            ids.update(startDate=options.get('since'), endDate=options.get('until'))
        if options.get('own_money'):
            ids['isBuyWithMyOwnMoney'] = 'true'
        result = listing.read_numbered(connection, state, out, op=op, source=listing.pages_of(
            client, op, ids, _BUILD.get(kind, web.post_record)), command='search', target=text, identity=identity,
            words=words, order=order, show=DISPLAY, blog=ids.get('blogId'))
        if kind == 'tags' and not blog_text:
            result.setdefault('coverage', []).append('tag search sends no blog name: an empty name is that surface\'s '
                                                     'gap, not an unnamed blog')
        return result

    return reading.run(platform, invocation, command='search', target=text, identity=identity, reader=read,
                       bound=account.binds(options, DISPLAY), window=listing.window_of(options, order))


def keywords(platform, invocation):
    """Naver Blog's popular searches of the day, or the searches related to one keyword."""
    text = ' '.join(invocation.options.get('text') or []).strip()
    identity = {'kind': 'related' if text else 'popular', 'target': text or None}

    def read(connection, state, out):
        client = connection.client
        if text:
            result = client.get('related_keywords', keyword=text)['result']
            found = [k.to_dict() for k in web.keyword_records(result.get('keywords'))]
            if not found:
                return {'results': [], 'failure': SnsError('empty', f'Naver lists no searches related to {text!r}.',
                                                           listing.EMPTY_FIX)}
            return {'results': found, 'stop_reason': 'not_paginable'}
        result = client.get('popular_keywords')['result']
        found = [k.to_dict() for k in web.keyword_records(result.get('keywords'))]
        return {'results': found, 'stop_reason': 'not_paginable',
                'coverage': [f'Naver\'s popular blog searches as of {result.get("keywordDate") or "an undated day"}, in '
                             'its own order: a ranking, not a share of searches']}

    return reading.run(platform, invocation, command='keywords', target=None, identity=identity, reader=read,
                       bound=False)
