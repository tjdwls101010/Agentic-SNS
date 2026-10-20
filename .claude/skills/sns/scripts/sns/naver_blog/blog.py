"""blog (a blog's card, counts, category tree, notices, popular posts) and posts (one blog's lists)."""
from sns import reading
from sns.errors import SnsError

from sns.naver_blog import account, listing, web

DISPLAY = 10
SHELVES = {'popular': 'popular_posts', 'notices': 'notice_posts'}
_LEAF = {'popular_posts': 'result.popularPostList', 'notice_posts': 'result.noticePostViewList'}


def blog(platform, invocation):
    options = invocation.options
    typed = web.parse_target(options['target'], 'blog')
    identity = {'blog': typed.blog_id or 'naver.me/' + typed.short}

    def read(connection, state, out):
        client, sections = connection.client, []
        target = client.target(options['target'], 'blog')

        def card():
            built = web.blog_record(client.get('blog_card', blogId=target.blog_id)['result'])
            if built is None:
                raise SnsError('failed', 'The blog card named no blog.', 'Run doctor; the response shape changed.',
                               reason='drift')
            return [built.to_dict()]

        record = reading.section(sections, 'blog', card, primary=True)[0]
        blog_id = record['blog_id']

        def counts():
            result = client.get('contents_count', blogId=blog_id)['result']
            record['post_count'] = result.get('postCount') if isinstance(result.get('postCount'), int) else \
                record['post_count']
            record['clip_count'] = result.get('momentCount') if isinstance(result.get('momentCount'), int) else None

        reading.section(sections, 'counts', counts)   # read for the card above: it draws nothing of its own
        reading.section(sections, 'categories', lambda: [c.to_dict() for c in web.categories(
            client.get('categories', blogId=blog_id)['result']['mylogCategoryList'], blog_id)])
        if not options.get('brief'):
            for name in ('notices', 'popular'):
                reading.section(sections, name, lambda op=SHELVES[name]: shelf(client, op, blog_id))
        return {'sections': sections, 'stop_reason': 'not_paginable',
                'coverage': ['a public neighbor list is private by default: the card\'s neighbor count is the figure, '
                             'buddies <id> may show none']}

    return reading.run(platform, invocation, command='blog', target=typed.handle, identity=identity, reader=read,
                       bound=False)


def shelf(client, op, blog_id):
    """A blog's notice or popular posts: one page, no total."""
    rows = web.at(client.get(op, blogId=blog_id), _LEAF[op])
    return [r.to_dict() for r in (web.post_record(row, blog_id=blog_id) for row in rows) if r]


def category_number(client, blog_id, wanted):
    """A category number costs nothing; a name costs one request: an exact match first, then a part of a name."""
    if str(wanted).isdigit():
        return str(wanted), None
    rows = web.categories(client.get('categories', blogId=blog_id)['result']['mylogCategoryList'], blog_id)
    lowered = str(wanted).lower()
    exact = [c for c in rows if (c.name or '').lower() == lowered]
    matches = exact or [c for c in rows if lowered in (c.name or '').lower()]
    if not matches:
        raise SnsError('unavailable', f'This blog has no category matching {wanted!r}.',
                       f'Run blog {blog_id} to see its categories.', reason='not_exist_category')
    if len(matches) > 1:
        raise SnsError('argument', f'{wanted!r} matches more than one category.', 'Pass --category with a number: ' +
                       ', '.join(f'{c.name} ({c.category_no})' for c in matches[:6]) + '.')
    return matches[0].category_no, matches[0].name


def check(options):
    """The argument rules of posts, before any request."""
    target = web.parse_target(options['target'], 'blog')
    chosen = [flag for flag in ('category', 'popular', 'notices') if options.get(flag)]
    if len(chosen) > 1:
        raise SnsError('argument', 'Choose one of --category, --popular and --notices.', 'Run posts once per list.')
    if target.category_no and options.get('category'):
        raise SnsError('argument', 'That URL already names a category.',
                       'Drop --category, or pass the blog id alone.')
    if (options.get('popular') or options.get('notices')) and (options.get('since') or options.get('until')
                                                               or options.get('after') or options.get('out')):
        raise SnsError('argument', 'Popular and notice posts are one page: no date window, no continuation, no file.',
                       'Drop --since/--until/--after/--out.')


def posts(platform, invocation):
    options = invocation.options
    target = web.parse_target(options['target'], 'blog')
    shelf_name = 'popular' if options.get('popular') else 'notices' if options.get('notices') else None
    wanted = target.category_no or options.get('category')
    identity = {'blog': target.blog_id or 'naver.me/' + target.short, 'category': wanted, 'shelf': shelf_name}
    words = ['--category', str(wanted)] if wanted else []

    def read(connection, state, out):
        client = connection.client
        saved = listing.resumed(state, out)
        blog_id = saved.get('blog_id') or client.target(options['target'], 'blog').blog_id
        if shelf_name:
            records = shelf(client, SHELVES[shelf_name], blog_id)[:options.get('limit') or DISPLAY]
            if not records:
                return {'results': [], 'failure': SnsError('empty', f'This blog shows no {shelf_name} posts.',
                                                           listing.EMPTY_FIX)}
            return {'results': records, 'stop_reason': 'not_paginable'}
        number = saved.get('category_no')
        if wanted and number is None:
            number, _ = category_number(client, blog_id, wanted)
        ids = {'blogId': blog_id, 'categoryNo': number or 0}
        result = listing.read_numbered(
            connection, state, out, op='post_list', source=listing.pages_of(
                client, 'post_list', ids, lambda raw: web.post_record(raw, blog_id=blog_id)), command='posts',
            target=target.handle or options['target'], identity=identity, words=words, order='newest_first',
            show=DISPLAY, blog=blog_id, carry={'category_no': number})
        if wanted and not str(wanted).isdigit():
            result.setdefault('coverage', []).append(f'category {wanted} is number {number}')
        return result

    return reading.run(platform, invocation, command='posts', target=target.handle or options['target'],
                       identity=identity, reader=read, bound=not shelf_name and account.binds(options, DISPLAY),
                       window=None if shelf_name else listing.window_of(options, 'newest_first'))
