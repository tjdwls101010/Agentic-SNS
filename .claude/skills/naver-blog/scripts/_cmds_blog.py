"""blog, posts, buddies, home, topic, monthly — the commands that start from a blog or a shelf."""
from ._api import operation
from ._cmds_read import listing, request_budget
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
    return {'blog': read_blog, 'posts': read_posts, 'buddies': read_buddies,
            'home': read_home, 'topic': read_topic, 'monthly': read_monthly}[args.command](args, transport)


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
    context = {'command': 'posts', 'blog': blog_id, 'category': category,
               'since': args.since, 'until': args.until}
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




def read_buddies(args, transport):
    """Your own neighbour list is a different endpoint from anyone else's public one."""
    from . import _session
    if args.target is None:
        blog_id = _session.ensure(transport)
        op, values = 'my_buddies', {'blogId': blog_id}
        note = 'your own neighbours'
    else:
        blog_id = args.target.blog_id
        op, values = 'public_buddies', {'blogId': blog_id}
        note = 'public neighbours'
    context = {'command': 'buddies', 'blog': blog_id, 'kind': note}
    result = listing(args, transport, op=op, context=context, blog_id=blog_id,
                     build=build_buddy, page_values=values,
                     resume=f'buddies {blog_id}' if args.target else 'buddies',
                     label_prefix='b',
                     hops=['context: `blog <id>`', 'activity: `posts <id>`'])
    if op == 'public_buddies' and not result['results'] and result['code'] == 7:
        # Private is the default, so an empty public list says nothing about how many there are.
        result['warnings'] = ['this blog publishes no neighbour list; the card still carries a count']
    return result


def read_home(args, transport):
    """Naver serves one page of neighbour posts and ignores every paging parameter it accepts."""
    from ._listing import collect
    from ._walk import read_page
    spec = operation('buddy_feed')

    def fetch(page):
        payload = transport.get('buddy_feed')
        result = payload.get('result') or {}
        # Only an explicit false means "this account follows nobody"; a missing field does not.
        if result.get('hasBuddy') is False:
            raise NaverBlogError(7, 'This account has no neighbours yet.',
                                 'Follow a blog in Naver, or read one directly with posts <id>.',
                                 error='empty')
        raw = read_page(spec, payload, page=page)
        raw.items = [item.to_dict() for item in
                     (build_post(row) for row in raw.items) if item]
        return raw

    try:
        result = collect(spec, fetch, limit=args.limit, since=args.since, until=args.until,
                         # The feed is newest first, so a page below the window closes it.
                         monotonic=True)
    except NaverBlogError as error:
        if error.code != 7:
            raise
        result = {'ok': True, 'results': [], 'stop_reason': 'exhausted', 'code': 7,
                  'message': error.message, 'fix': error.fix}
    result['context'] = {'feed': 'neighbours'}
    result['label_prefix'] = 'p'
    result['budget'] = transport.budget.snapshot()
    result['fetched_bytes'] = transport.fetched_bytes
    result['next'] = None
    result['hops'] = ['open: `post <url>`', 'more from one: `posts <id>`',
                      'who they are: `buddies`']
    if result['stop_reason'] == 'server_capped':
        result['warnings'] = ['Naver reports more neighbour posts than it serves here; '
                              'read a neighbour directly with posts <id>']
    return result


def topic_number(transport, wanted):
    if str(wanted).isdigit():
        return str(wanted), None
    topics = build_topics(transport.get('directories').get('result'))
    matches = [topic for topic in topics if topic.name and str(wanted).lower() in topic.name.lower()]
    exact = [topic for topic in matches if topic.name.lower() == str(wanted).lower()]
    matches = exact or matches
    if not matches:
        names = ', '.join(topic.name for topic in topics[:8])
        raise NaverBlogError(9, f'No topic matches {wanted!r}.',
                             f'Run topic with no argument to list them; they start with {names}.',
                             error='not_exist_category')
    if len(matches) > 1:
        names = ', '.join(f'{topic.name} ({topic.seq})' for topic in matches[:5])
        raise NaverBlogError(2, f'{wanted!r} matches more than one topic.',
                             f'Pass the number instead: {names}.')
    return matches[0].seq, matches[0].name


def read_topic(args, transport):
    if args.target is None:
        payload = transport.get('directories')
        topics = [topic.to_dict() for topic in build_topics(payload.get('result'))]
        return {'ok': True, 'code': 0 if topics else 7, 'results': topics,
                'stop_reason': 'not_paginable', 'context': {'directory': 'topics'},
                'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes,
                'next': None, 'label_prefix': 't',
                'hops': ['newest in one: `topic <seq>`', 'featured: `topic <seq> --top`']}

    seq, name = topic_number(transport, args.target)
    if args.top:
        payload = transport.get('directory_top', directorySeq=seq)
        rows = payload.get('result') or []
        records = [post.to_dict() for post in (build_post(row) for row in rows) if post][:args.limit]
        return {'ok': True, 'code': 0 if records else 7, 'results': records,
                'stop_reason': 'not_paginable', 'context': {'topic': name or seq, 'shelf': 'featured'},
                'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes,
                'next': None, 'label_prefix': 'p',
                'hops': ['open: `post <url>`', f'newest instead: `topic {seq}`']}

    context = {'command': 'topic', 'topic': seq, 'since': args.since, 'until': args.until}
    return listing(args, transport, op='directory_posts', context=context,
                   build=build_post, page_values={'directorySeq': seq},
                   since=args.since, until=args.until, monotonic=True,
                   resume=f'topic {seq}' + ''.join(
                       f' --{flag} {getattr(args, flag)}' for flag in ('since', 'until')
                       if getattr(args, flag)),
                   hops=['open: `post <url>`', 'blog: `blog <id>`', f'featured: `topic {seq} --top`'])


def next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def read_monthly(args, transport):
    """Naver clamps a future month to its latest issue, so the answer says which one it is."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9)))
    year, month = args.year or today.year, args.month or today.month
    sections = Sections()

    def blogs():
        payload = transport.get('monthly_blogs', year=year, month=month)
        result = payload.get('result') or {}
        rows = []
        for group in result.get('list') or []:
            for raw in (group.get('blogList') or []):
                built = build_blog(raw)
                if built:
                    rows.append(built.to_dict())
        sections.previous = (result.get('prevYear'), result.get('prevMonth'))
        # Naver clamps a month it has not published yet to its latest issue, and answers
        # without saying so. The issue before this one is the only evidence of which it is.
        if all(sections.previous):
            sections.actual = next_month(*sections.previous)
        return rows

    def picks():
        payload = transport.get('editor_picks', year=year, month=month)
        rows = []
        for raw in (payload.get('result') or {}).get('list') or []:
            built = build_blog(raw)
            if built:
                rows.append(built.to_dict())
        return rows

    sections.previous = None
    sections.actual = None
    sections.add('blogs of the month', blogs, primary=True, prefix='m')
    sections.add('editor picks', picks, prefix='e')
    previous = getattr(sections, 'previous', None)
    actual = getattr(sections, 'actual', None) or (year, month)
    hops = ['context: `blog <id>`', 'activity: `posts <id>`']
    if previous and all(previous):
        hops.append(f'earlier issue: `monthly --year {previous[0]} --month {previous[1]}`')
    warnings = []
    if (actual[0], actual[1]) != (year, month):
        warnings.append(f'{year}-{month:02d} has not been published; '
                        f'this is the {actual[0]}-{actual[1]:02d} issue')
    return {'ok': sections.exit_code() == 0, 'code': sections.exit_code(),
            'sections': sections.as_list(), 'results': [], 'stop_reason': 'not_paginable',
            'warnings': warnings, 'context': {'issue': f'{actual[0]}-{actual[1]:02d}'},
            'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes,
            'next': None, 'hops': hops}
