"""post, comments and resolve: one post read in full, a post's comments, and where a short link leads.

A post is one page read (the body, pictures, links, Naver's flags), the live reaction count (the list surfaces' counts
can lag it), and the same-category posts — without the post itself, wherever it sits in that list.
"""
from dataclasses import replace

from sns import reading
from sns.cmdline import command_line, words
from sns.errors import SnsError

from sns.naver_blog import account, listing, web

COMMENTS_DISPLAY = 20   # rows (comments and their replies together) one screen shows
POST_COMMENTS = 10      # top-level comments post --comments reads, with their replies
RESUMABLE = ('time_limit', 'rate_limited')   # the stops that pass by themselves: the time limit and a hold


def post_url(blog, log_no):
    return f'https://blog.naver.com/{blog}/{log_no}'


def post(platform, invocation):
    options = invocation.options
    typed = web.parse_target(options['target'], 'post')
    name = typed.handle or options['target']

    def read(connection, state, out):
        client, sections = connection.client, []
        target = client.target(options['target'], 'post')

        def page():
            html = client.get('post_html', blogId=target.blog_id, logNo=target.log_no)
            return web.parse_post(html, blog_id=client.canonical.get(target.blog_id, target.blog_id),
                                  log_no=target.log_no)

        doc = reading.section(sections, 'post', page, primary=True)
        account.note_viewer(connection, doc)
        blog = doc.blog_id or target.blog_id
        record = doc.to_dict()
        sections[-1]['data'] = [record]

        def reactions():
            result = client.get('sympathy', blogId=blog, logNo=doc.log_no)['result']
            record['like_count'] = result.get('totalCount') if isinstance(result.get('totalCount'), int) else None
            record['reactions'] = {r.get('reactionType'): r.get('count') for r in result.get('reactionCounts') or []
                                   if isinstance(r, dict) and r.get('reactionType')}

        reading.section(sections, 'reactions', reactions)   # read for the post above: it draws nothing of its own
        if doc.category_no:
            def same_category():
                rows = client.get('related_category', blogId=blog, categoryNo=doc.category_no,
                                  logNo=doc.log_no)['result']['recommendationPostList']
                built = [web.post_record(row, blog_id=blog) for row in rows]
                return [r.to_dict() for r in built if r and r.log_no != str(doc.log_no)]
            reading.section(sections, 'same category', same_category)
        if options.get('comments'):
            def first_comments():
                blog_no = doc.blog_no or blog_no_of(client, blog, doc.log_no)[0]
                fetched, _ = client.page('comments', 1, lambda raw: raw, blogNo=blog_no, logNo=doc.log_no)
                return parents(threaded(fetched.items, post_url(blog, doc.log_no)), POST_COMMENTS)
            reading.section(sections, 'comments', first_comments)
        if out is not None and all(section['ok'] for section in sections):
            save(out, sections)   # a post with a section missing is not saved: the same command reads it all again
        return {'sections': sections, 'stop_reason': 'not_paginable'}

    return reading.run(platform, invocation, command='post', target=name, identity={'target': name}, reader=read,
                       bound=False)


def save(out, sections):
    """One post is one page of rows: the post, then what its other sections read."""
    out.commit([row for section in sections for row in section.get('data') or []], None, 'not_paginable')


def blog_no_of(client, blog, log_no):
    """The comment box is keyed by the blog's number: comments-info gives it (and Naver's total) for one request."""
    result = client.get('comments_info', blogId=blog, logNo=log_no)['result']
    if result.get('blogNo') is None:
        raise SnsError('failed', 'Naver did not supply the blog number the comment box needs.',
                       'Read the post first, then its comments.', reason='drift')
    total = result.get('totalCount')
    return str(result['blogNo']), total if isinstance(total, int) else None


def threaded(rows, url):
    """Records of one page in reading order (they arrive as dicts)."""
    built = [web.comment_record(row, post_url=url) for row in rows]
    return [c.to_dict() for c in web.thread_comments([c for c in built if c])]


def parents(records, count):
    """The first `count` top-level comments with the replies shown under them."""
    kept, tops = [], 0
    for record in records:
        if record['depth'] == 0:
            tops += 1
            if tops > count:
                break
        kept.append(record)
    return kept


def comments(platform, invocation):
    options = invocation.options
    typed = web.parse_target(options['target'], 'post')
    name = typed.handle or options['target']

    def read(connection, state, out):
        client = connection.client
        target = client.target(options['target'], 'post') if typed.short else typed
        blog_no = listing.resumed(state, out).get('blog_no') or blog_no_of(client, target.blog_id, target.log_no)[0]
        counts, url = {}, post_url(target.blog_id, target.log_no)

        def source(number):
            fetched, payload = client.page('comments', number, lambda raw: raw, blogNo=blog_no, logNo=target.log_no)
            counts.update(web.comment_counts(payload['result'].get('count')))
            return replace(fetched, items=threaded(fetched.items, url))

        result = listing.read_numbered(connection, state, out, op='comments', source=source, command='comments',
                                       target=name, identity={}, order='finite', show=COMMENTS_DISPLAY,
                                       carry={'blog_no': blog_no})
        notes = ['order: comments newest first; each comment\'s replies follow it, oldest first']
        if counts:
            notes.append(f'Naver\'s count: {counts["comments"]} comments · {counts["replies"]} replies · '
                         f'{counts["deleted"] or 0} deleted · {counts["blinded"] or 0} blinded · {counts["total"]} total')
        result.setdefault('coverage', []).extend(notes)
        return result

    return reading.run(platform, invocation, command='comments', target=name, identity={}, reader=read,
                       bound=account.binds(options, COMMENTS_DISPLAY))


def resolve(platform, invocation):
    """Where each naver.me link leads, read from its redirect without following it; a blog post destination is named
    as the target post takes it."""
    links = invocation.options['target']
    for text in links:   # refused here, after cli.py has named the command that reads another platform's link
        if 'naver.me' not in text.lower() or not web.parse_target(text, 'either').short:
            raise SnsError('argument', f'{text} is not a naver.me short link.',
                           'Pass naver.me/<code> links; other addresses are already where they go.')

    def read(connection, state, out):
        found, failure, remaining = [], None, []
        for index, text in enumerate(links):
            try:
                hop = connection.client.resolve(web.parse_target(text, 'either').short)
            except SnsError as error:
                failure, remaining = error, links[index:]
                break
            location = hop.get('location')
            record = web.Resolved(id=f'link:naver.me/{web.parse_target(text, "either").short}', url=text, link=text,
                                  status=hop['status'], destination=web.link_of(location) if location else None)
            if location:
                try:
                    landed = web.short_destination(location, 'post')
                    record.post = f'{landed.blog_id}/{landed.log_no}'
                except SnsError:
                    pass
            found.append(record.to_dict())
        result = {'results': found, 'stop_reason': 'exhausted', 'failure': failure, 'partial': bool(found)}
        if failure is not None and found and failure.reason in RESUMABLE:
            # The links not yet read are the whole of what goes on, so the command that reads them needs no handle (and
            # no account): a spent deadline or a standing hold cannot take it away.
            result['continuable'] = True
            result['next'] = command_line(invocation.cli_path, words(platform.key, 'resolve', remaining, [], invocation.options,
                                                                      limit=None))
        return result

    return reading.run(platform, invocation, command='resolve', target=links, identity={}, reader=read, bound=False)
