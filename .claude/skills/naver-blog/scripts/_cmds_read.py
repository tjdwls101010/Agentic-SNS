"""search, post, comments, find — the commands that start from text or from one post."""
from pathlib import Path

from ._api import operation
from ._errors import NaverBlogError
from ._listing import collect
from ._models import build_comment, build_post, link_replies
from ._output import CursorStore, OutFile, document
from ._transport import Transport
from ._walk import read_page

# A command asking for more than its default limit is collecting rather than reading.
BASE_REQUESTS, COLLECT_REQUESTS = 10, 40


def request_budget(args):
    explicit = (getattr(args, 'out', None) is not None or getattr(args, 'since', None) is not None
                or getattr(args, 'limit', None) not in (None, 10, 20))
    return COLLECT_REQUESTS if explicit else BASE_REQUESTS


ENTRY = f'python3 "{Path(__file__).resolve().parent / "naver_blog.py"}"'


def listing(args, transport, *, op, context, build, page_values, since=None, until=None,
            monotonic=False, blog_id=None, hops=None, label_prefix='p', resume=None):
    """The shared walk: one operation, page by page, with a handle and an optional file."""
    spec = operation(op)
    store = CursorStore()
    state = store.load(args.after, context) if getattr(args, 'after', None) else None

    def fetch(page):
        payload = transport.get(op, page=page, **page_values)
        raw = read_page(spec, payload, page=page)
        raw.items = [record.to_dict() for record in
                     (build(item) for item in raw.items) if record is not None]
        return raw

    out = OutFile(args.out, context) if getattr(args, 'out', None) else None
    try:
        if out and out.complete and state is None:
            state = out.state
        result = collect(spec, fetch, limit=args.limit, state=state, since=since, until=until,
                         monotonic=monotonic, commit=out.commit if out else None)
        if out:
            result['out'] = str(out.path)
            result['saved'] = out.count
            result['already_complete'] = out.complete
    finally:
        if out:
            out.close()
    next_command = None
    if result['stop_reason'] == 'limit_reached':
        handle = store.save(context, result['state'])
        # The handle is bound to this exact query, so the printed command must rebuild it.
        next_command = f'{ENTRY} {resume or context["command"]} --after {handle}'
    result['context'] = {key: value for key, value in context.items() if key not in ('command', 'account')}
    result['label_prefix'] = label_prefix
    result['hops'] = hops or []
    result['budget'] = transport.budget.snapshot()
    result['fetched_bytes'] = transport.fetched_bytes
    result['next'] = next_command
    result['blog_id'] = blog_id
    return result


def run(args):
    transport = Transport(request_budget(args))
    if args.command == 'search':
        return search(args, transport)
    if args.command == 'find':
        return find(args, transport)
    if args.command == 'comments':
        return comments(args, transport)
    return post(args, transport)


def search(args, transport):
    op = {'posts': 'search_posts', 'blogs': 'search_blogs', 'tags': 'search_tags'}[args.type]
    values = {'keyword': args.text} if args.type != 'tags' else {'query': args.text}
    if args.type == 'posts':
        values['sortType'] = args.sort
        if args.own_money:
            values['isBuyWithMyOwnMoney'] = 'true'
        # Only post search filters on the server, and only by whole KST days.
        if args.since:
            values['startDate'] = args.since
        if args.until:
            values['endDate'] = args.until
    from ._entities import build_blog
    build = build_blog if args.type == 'blogs' else build_post
    context = {'command': f'search {args.text!r}', 'type': args.type,
               'sort': args.sort if args.type != 'tags' else None}
    resume = f'search {args.text!r} --type {args.type}'
    if args.type != 'tags':
        resume += f' --sort {args.sort}'
    if args.own_money:
        resume += ' --own-money'
    for flag in ('since', 'until'):
        if getattr(args, flag):
            resume += f' --{flag} {getattr(args, flag)}'
    hops = ['open: `post <url>`', 'blog: `blog <id>`', 'similar: `search --type tags <tag>`']
    if args.type == 'blogs':
        hops = ['activity: `posts <id>`', 'context: `blog <id>`']
    return listing(args, transport, op=op, context={k: v for k, v in context.items() if v is not None},
                   build=build, page_values=values,
                   # The server already applied the window on post search; filtering again is free.
                   since=args.since if args.type == 'posts' else None,
                   until=args.until if args.type == 'posts' else None,
                   monotonic=args.type == 'posts' and args.sort == 'date', hops=hops, resume=resume)


def find(args, transport):
    blog_id = args.target.blog_id
    op = 'blog_tag_search' if args.tag else 'blog_search'
    values = {'blogId': blog_id, 'query': args.text}
    if not args.tag:
        values['sortType'] = args.sort
    context = {'command': f'find {blog_id} {args.text!r}', 'blog': blog_id,
               'kind': 'tag' if args.tag else 'text'}
    if not args.tag:
        context['sort'] = args.sort
    resume = f'find {blog_id} {args.text!r}' + (' --tag' if args.tag else f' --sort {args.sort}')
    for flag in ('since', 'until'):
        if getattr(args, flag):
            resume += f' --{flag} {getattr(args, flag)}'
    return listing(args, transport, op=op, context=context, blog_id=blog_id,
                   build=lambda raw: build_post(raw, blog_id=blog_id), page_values=values,
                   since=args.since, until=args.until,
                   monotonic=not args.tag and args.sort == 'date', resume=resume,
                   hops=[f'open: `post {blog_id}/<logNo>`', f'all posts: `posts {blog_id}`'])


def comments(args, transport):
    blog_id, log_no = args.target.blog_id, args.target.log_no
    # comments-info is the cheapest source of the numeric blog id the comment box is keyed by.
    blog_no, info = blog_no_of(transport, blog_id, log_no)
    context = {'command': f'comments {blog_id}/{log_no}', 'post': f'{blog_id}/{log_no}'}
    store = CursorStore()
    state = store.load(args.after, context) if args.after else None
    out = OutFile(args.out, context) if args.out else None
    try:
        if out and out.complete and state is None:
            state = out.state
        result = comments_of(transport, blog_id, log_no, blog_no, args.limit,
                             state=state, commit=out.commit if out else None)
        if out:
            result['out'] = str(out.path)
            result['saved'] = out.count
            result['already_complete'] = out.complete
    finally:
        if out:
            out.close()
    total = info.get('totalCount')
    result['shown_of'] = total if isinstance(total, int) else result.get('reported_total')
    result['context'] = {'post': f'{blog_id}/{log_no}', 'order': 'newest first'}
    result['label_prefix'] = 'c'
    # replyPageSize is 10, so a parent with more replies than that may not show all of them.
    result['warnings'] = ['replies: only the ones Naver returned; a parent with many replies may be partial']
    result['hops'] = [f'post: `post {blog_id}/{log_no}`', f'blog: `blog {blog_id}`',
                      'commenter: `blog <the blog: id on a comment>`']
    result['next'] = None
    if result['stop_reason'] == 'limit_reached':
        handle = store.save(context, result['state'])
        result['next'] = f'{ENTRY} comments {blog_id}/{log_no} --after {handle}'
    result['budget'] = transport.budget.snapshot()
    result['fetched_bytes'] = transport.fetched_bytes
    return result


def post(args, transport):
    from ._cmds_post import read_post
    return read_post(args, transport)


def comments_of(transport, blog_id, log_no, blog_no, limit, *, state=None, commit=None):
    """The comment box is keyed by the blog's numeric id, which is not the blog id."""
    spec = operation('comments')

    def fetch(page):
        payload = transport.get('comments', page=page, blogNo=blog_no, logNo=log_no)
        raw = read_page(spec, payload, page=page)
        built = link_replies([c for c in (build_comment(item) for item in raw.items) if c is not None])
        raw.items = [comment.to_dict() for comment in built]
        return raw
    return collect(spec, fetch, limit=limit, state=state, commit=commit)


def blog_no_of(transport, blog_id, log_no):
    payload = transport.get('comments_info', blogId=blog_id, logNo=log_no)
    blog_no = (payload.get('result') or {}).get('blogNo')
    if blog_no is None:
        raise NaverBlogError(6, 'Naver did not supply the numeric blog id the comment box needs.',
                             'Read the post itself first; its HTML carries the same number.',
                             error='envelope_drift')
    return str(blog_no), payload.get('result') or {}


def documents(command, result, *, sections=None):
    return document(command, result, budget=result.get('budget'),
                    fetched_bytes=result.get('fetched_bytes', 0),
                    next_command=result.get('next'), sections=sections)
