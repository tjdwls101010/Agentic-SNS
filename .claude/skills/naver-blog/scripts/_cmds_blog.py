"""blog, posts, buddies, home, topic, monthly — the commands that start from a blog or a shelf."""
from ._api import operation
from ._cmds_read import ENTRY, listing, request_budget
from ._entities import build_blog, build_buddy, build_categories, build_topics
from ._errors import NaverBlogError
from ._models import build_post
from ._sections import Sections
from ._transport import Transport


def resolve(transport, blog_id, produce):
    """Try the id as given; a domain address only reveals its real id through one redirect."""
    try:
        return produce(blog_id), blog_id
    except NaverBlogError as error:
        if error.error not in ('not_exist_blog', 'blog_id_invalidate'):
            raise
        canonical = transport.redirect_of('domain_redirect', blogId=blog_id)
        return produce(canonical), canonical


def run(args):
    transport = Transport(request_budget(args) if args.command != 'blog' else 6)
    return {'blog': read_blog, 'posts': read_posts}[args.command](args, transport)


def read_blog(args, transport):
    blog_id = args.target.blog_id
    sections = Sections()

    def card(identifier):
        return transport.get('blog_card', blogId=identifier)

    payload, blog_id = resolve(transport, blog_id, card)
    entry = build_blog(payload.get('result'))
    if entry is None:
        raise NaverBlogError(6, 'The blog card did not identify a blog.', error='envelope_drift')
    sections.entries.append({'name': 'blog', 'ok': True, 'primary': True, 'prefix': 'b',
                             'data': [entry.to_dict()]})

    def categories():
        payload = transport.get('categories', blogId=blog_id)
        rows = build_categories((payload.get('result') or {}).get('mylogCategoryList'), blog_id)
        return [row.to_dict() for row in rows]

    sections.add('categories', categories, prefix='c')
    if not args.brief:
        def notices():
            payload = transport.get('notice_posts', blogId=blog_id)
            rows = (payload.get('result') or {}).get('noticePostViewList') or []
            return [post.to_dict() for post in
                    (build_post(row, blog_id=blog_id) for row in rows) if post]

        def popular():
            payload = transport.get('popular_posts', blogId=blog_id)
            rows = (payload.get('result') or {}).get('popularPostList') or []
            return [post.to_dict() for post in
                    (build_post(row, blog_id=blog_id) for row in rows) if post]

        sections.add('notices', notices, prefix='n')
        sections.add('popular', popular, prefix='v')
    return {'ok': sections.exit_code() == 0, 'code': sections.exit_code(),
            'sections': sections.as_list(), 'results': [], 'stop_reason': 'not_paginable',
            'context': {'blog': blog_id}, 'budget': transport.budget.snapshot(),
            'fetched_bytes': transport.fetched_bytes, 'next': None,
            'hops': [f'posts: `posts {blog_id} --category <no>`', f'search inside: `find {blog_id} <text>`',
                     f'neighbours: `buddies {blog_id}`']}


def category_number(transport, blog_id, wanted):
    """A category name costs one request; the number in the blog output costs none."""
    if str(wanted).isdigit():
        return str(wanted)
    payload = transport.get('categories', blogId=blog_id)
    rows = build_categories((payload.get('result') or {}).get('mylogCategoryList'), blog_id)
    matches = [row for row in rows if row.name and str(wanted).lower() in row.name.lower()]
    exact = [row for row in matches if row.name.lower() == str(wanted).lower()]
    matches = exact or matches
    if not matches:
        raise NaverBlogError(9, f'This blog has no category matching {wanted!r}.',
                             f'Run `blog {blog_id}` to see the category tree.', error='not_exist_category')
    if len(matches) > 1:
        names = ', '.join(f'{row.name} ({row.category_no})' for row in matches[:5])
        raise NaverBlogError(2, f'{wanted!r} matches more than one category.',
                             f'Pass --category with a number: {names}.')
    return matches[0].category_no


def read_posts(args, transport):
    blog_id = args.target.blog_id

    if args.popular or args.notices:
        op = 'popular_posts' if args.popular else 'notice_posts'
        payload, blog_id = resolve(transport, blog_id, lambda name: transport.get(op, blogId=name))
        rows = read_single(operation(op), payload)
        records = [post.to_dict() for post in
                   (build_post(row, blog_id=blog_id) for row in rows) if post][:args.limit]
        return {'ok': True, 'code': 0 if records else 7, 'results': records,
                'stop_reason': 'not_paginable',
                'context': {'blog': blog_id, 'shelf': 'popular' if args.popular else 'notices'},
                'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes,
                'next': None, 'label_prefix': 'p',
                'hops': [f'open: `post {blog_id}/<logNo>`', f'all posts: `posts {blog_id}`']}

    category = args.target.category_no or args.category
    if category is not None:
        category = category_number(transport, blog_id, category)
    values = {'blogId': blog_id, 'categoryNo': category or 0}
    context = {'command': f'posts {blog_id}', 'blog': blog_id}
    if category:
        context['category'] = category
    resume = f'posts {blog_id}' + (f' --category {category}' if category else '')
    for flag in ('since', 'until'):
        if getattr(args, flag):
            resume += f' --{flag} {getattr(args, flag)}'
    return listing(args, transport, op='post_list', context=context, blog_id=blog_id, resume=resume,
                   build=lambda raw: build_post(raw, blog_id=blog_id), page_values=values,
                   since=args.since, until=args.until,
                   # A blog's own post list is newest first, so a page below the window ends it.
                   monotonic=True,
                   hops=[f'open: `post {blog_id}/<logNo>`', f'blog: `blog {blog_id}`',
                         f'search inside: `find {blog_id} <text>`'])


def read_single(spec, payload):
    from ._transport import at
    rows = at(payload, spec.leaf)
    return rows if isinstance(rows, list) else []


__all__ = ['run', 'read_blog', 'read_posts', 'category_number', 'resolve', 'build_buddy',
           'build_topics', 'ENTRY']
