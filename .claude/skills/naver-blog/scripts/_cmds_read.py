"""search, post, comments, find — the commands that start from text or from one post."""
import shlex
from pathlib import Path

from ._api import operation
from ._errors import NaverBlogError
from ._listing import collect
from ._models import UNKNOWN, build_comment, build_post, link_replies
from ._output import CursorStore, OutFile, document
from ._transport import Transport
from ._walk import read_page

# A command asking for more than its default limit is collecting rather than reading.
BASE_REQUESTS, COLLECT_REQUESTS = 10, 40


def request_budget(args):
    """Collecting is asking for it: a named --limit, a date window, or a file to fill."""
    explicit = (getattr(args, 'out', None) is not None or getattr(args, 'since', None) is not None
                or getattr(args, 'until', None) is not None or getattr(args, 'explicit_limit', False))
    return COLLECT_REQUESTS if explicit else BASE_REQUESTS


ENTRY = f'python3 "{Path(__file__).resolve().parent / "naver_blog.py"}"'


def listing(args, transport, *, op, context, build, page_values, since=None, until=None,
            monotonic=False, blog_id=None, hops=None, label_prefix='p', resume=None):
    """The shared walk: one operation, page by page, with a handle and an optional file."""
    spec = operation(op)
    store = CursorStore()
    state = store.load(args.after, context) if getattr(args, 'after', None) else None

    def fetch(page):
        try:
            payload = transport.get(op, page=page, **page_values)
        except NaverBlogError as error:
            # A restricted answer still carries whatever arrived; reporting the restriction
            # while dropping those results would look exactly like an empty result.
            if error.error == 'query_restricted' and error.payload is not None:
                salvaged = read_page(spec, error.payload, page=page)
                error.records = [record.to_dict() for record in
                                 (build(item) for item in salvaged.items) if record is not None]
            raise
        raw = read_page(spec, payload, page=page)
        raw.items = [record.to_dict() for record in
                     (build(item) for item in raw.items) if record is not None]
        return raw

    out = OutFile(args.out, context) if getattr(args, 'out', None) else None
    try:
        # A file that already knows where it stopped is the resume point, finished or not;
        # starting over would re-display the same head and add nothing to the file.
        if out and state is None and out.state:
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
    # A handle is offered whenever anything is left: more pages to ask for, or records
    # already read that the display limit did not reach.
    if result['stop_reason'] == 'limit_reached' or result.get('pending'):
        handle = store.save(context, result['state'])
        # The handle is bound to this exact query, so the printed command must rebuild it.
        following = resume or context['command']
        if getattr(args, 'out', None):
            following += f' --out {shlex.quote(str(args.out))}'
        next_command = f'{ENTRY} {following} --after {handle}'
    result['context'] = {key: value for key, value in context.items()
                         if key != 'command' and value not in (None, False)}
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
    context = {'command': 'search', 'text': args.text, 'type': args.type,
               'sort': args.sort if args.type == 'posts' else None,
               'own_money': bool(args.own_money), 'since': args.since, 'until': args.until}
    resume = f'search {shlex.quote(args.text)} --type {args.type}'
    if args.type == 'posts':
        resume += f' --sort {args.sort}'
        if args.own_money:
            resume += ' --own-money'
    for flag in ('since', 'until'):
        if getattr(args, flag):
            resume += f' --{flag} {getattr(args, flag)}'
    hops = ['open: `post <url>`', 'blog: `blog <id>`', 'similar: `search --type tags <tag>`']
    if args.type == 'blogs':
        hops = ['activity: `posts <id>`', 'context: `blog <id>`']
    return listing(args, transport, op=op, context=context, build=build, page_values=values,
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
    context = {'command': 'find', 'blog': blog_id, 'text': args.text,
               'kind': 'tag' if args.tag else 'text',
               'sort': None if args.tag else args.sort, 'since': args.since, 'until': args.until}
    resume = f'find {blog_id} {shlex.quote(args.text)}' + (' --tag' if args.tag else f' --sort {args.sort}')
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
    context = {'command': 'comments', 'post': f'{blog_id}/{log_no}'}
    # The handle is checked before any request: a mismatched one must not cost a lookup.
    store = CursorStore()
    state = store.load(args.after, context) if args.after else None
    # comments-info is the cheapest source of the numeric blog id the comment box is keyed by,
    # and a resumed walk already carries that number, so it is asked for only once.
    blog_no, info = (state.get('blog_no'), {'totalCount': state.get('total')}) if state and state.get('blog_no') \
        else blog_no_of(transport, blog_id, log_no)
    out = OutFile(args.out, context) if args.out else None
    try:
        if out and state is None and out.state:
            state = out.state
        result = comments_of(transport, blog_id, log_no, blog_no, args.limit,
                             state=state, commit=out.commit if out else None)
        # Carry the numeric id and the total forward so continuing costs one request less.
        result['state']['blog_no'] = blog_no
        result['state']['total'] = info.get('totalCount')
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
    if result['stop_reason'] == 'limit_reached' or result.get('pending'):
        handle = store.save(context, result['state'])
        following = f'comments {blog_id}/{log_no}'
        if args.out:
            following += f' --out {shlex.quote(str(args.out))}'
        result['next'] = f'{ENTRY} {following} --after {handle}'
    result['budget'] = transport.budget.snapshot()
    result['fetched_bytes'] = transport.fetched_bytes
    return result


def post(args, transport):
    """One HTML read gives metadata, tags and body; one recommendation read gives the rest."""
    from ._body import parse
    from . import _session
    from ._sections import Sections

    blog_id, log_no = args.target.blog_id, args.target.log_no
    sections = Sections()

    def read():
        return transport.get('post_html', blogId=blog_id, logNo=log_no)

    from ._cmds_blog import resolve
    html, resolved = resolve(transport, blog_id, lambda name: transport.get('post_html',
                                                                            blogId=name, logNo=log_no))
    blog_id = resolved
    doc = parse(html)
    if doc.blog_id and doc.blog_id != blog_id:
        raise NaverBlogError(6, f'That page belongs to {doc.blog_id}, not {blog_id}.',
                             'Open the URL in Aside and pass the id it lands on.', error='envelope_drift')
    if doc.log_no and str(doc.log_no) != str(log_no):
        # Mixing another post's body with this post's recommendations and counts is worse
        # than refusing, and nothing downstream could tell the two apart.
        raise NaverBlogError(6, f'That page is post {doc.log_no}, not {log_no}.',
                             'Open the URL in Aside and pass the post number it lands on.',
                             error='envelope_drift')
    # The post page already names the viewer, so the session refreshes without a request.
    _session.note_viewer(html)
    record = {'id': f'post:{blog_id}/{log_no}', 'blog_id': blog_id, 'log_no': log_no,
              'url': f'https://blog.naver.com/{blog_id}/{log_no}', 'title': doc.title,
              'created_at': doc.created_at, 'category_no': doc.category_no,
              'category_name': doc.category_name, 'tags': doc.tags,
              'comment_count': doc.comment_count, 'like_count': UNKNOWN,
              'body': doc.body.to_dict()}
    sections.entries.append({'name': 'post', 'ok': True, 'primary': True, 'prefix': 'p',
                             'data': [record]})

    related = []
    if doc.category_no is not None:
        def recommendations():
            payload = transport.get('related_category', blogId=blog_id, categoryNo=doc.category_no,
                                    logNo=log_no)
            rows = (payload.get('result') or {}).get('recommendationPostList') or []
            built = [item for item in (build_post(row, blog_id=blog_id) for row in rows) if item]
            # The first recommendation has been the post itself, and that copy carries the
            # sympathy count the page does not. When it is not, the count stays unknown.
            if built and built[0].log_no == log_no:
                record['like_count'] = built[0].like_count
                del built[0]
                # One of the five slots held this post; the other four are the recommendations.
                built = built[:4]
            return [item.to_dict() for item in built]

        related = sections.add('same category', recommendations, prefix='s') or []

    if args.comments:
        def first_comments():
            blog_no = doc.blog_no
            if not blog_no:
                blog_no, _ = blog_no_of(transport, blog_id, log_no)
            outcome = comments_of(transport, blog_id, log_no, blog_no, 10)
            if not outcome['ok']:
                # collect reports a failure in its return value; swallowing that here would
                # turn a block or a login wall into a post that simply has no comments.
                raise NaverBlogError(outcome.get('error_code', 6),
                                     outcome.get('message') or 'The comment box could not be read.',
                                     outcome.get('fix'), error=outcome.get('error') or 'transient')
            return outcome['results']

        sections.add('comments', first_comments, prefix='c')

    if args.out:
        # One post is one page of records; the file is written whole rather than page by page.
        # A section that failed is written too, because a file that shows only what worked
        # reads later as a post that simply had no comments.
        out = OutFile(args.out, {'command': 'post', 'post': f'{blog_id}/{log_no}',
                                 'comments': bool(args.comments)})
        try:
            rows = []
            for entry in sections.as_list():
                if entry.get('ok'):
                    rows.extend(entry.get('data') or [])
                else:
                    rows.append({'id': f'section:{entry["name"]}', 'section': entry['name'],
                                 'ok': False, 'error': entry['error']})
            complete = sections.exit_code() == 0
            out.commit(rows, {'page': 1, 'pending': [], 'seen': []},
                       'not_paginable' if complete else 'query_failure')
        finally:
            out.close()

    tags = doc.tags if isinstance(doc.tags, list) else []
    hops = [f'comments: `comments {blog_id}/{log_no}`', f'blog: `blog {blog_id}`']
    if tags:
        hops.append(f'tag: `search --type tags {tags[0]}`')
    return {'ok': sections.exit_code() == 0, 'code': sections.exit_code(),
            'sections': sections.as_list(), 'results': [], 'stop_reason': 'not_paginable',
            'context': {'post': f'{blog_id}/{log_no}', 'body': doc.body.coverage.label()},
            'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes,
            'next': None, 'hops': hops, 'coverage': doc.body.coverage.__dict__,
            'related_count': len(related),
            **({'out': str(Path(args.out).expanduser())} if args.out else {})}


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
