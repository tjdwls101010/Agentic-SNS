"""topic (the topic directory, a topic's newest and featured posts) and monthly (the blogs of the month)."""
from sns import reading
from sns.errors import SnsError

from sns.naver_blog import account, listing, web

DISPLAY = 10
POSTS_PER_BLOG = 2


def topic_number(client, wanted):
    """A topic number costs nothing; a name costs one request: an exact match first, then a part of a name."""
    if str(wanted).isdigit():
        return str(wanted)
    found = web.topics(client.get('directories')['result'])
    lowered = str(wanted).lower()
    matches = [t for t in found if (t.name or '').lower() == lowered] or \
        [t for t in found if lowered in (t.name or '').lower()]
    if not matches:
        raise SnsError('unavailable', f'No topic matches {wanted!r}.', 'Run topic with no argument to list them.',
                       reason='not_exist_category')
    if len(matches) > 1:
        raise SnsError('argument', f'{wanted!r} matches more than one topic.', 'Pass the number instead: ' +
                       ', '.join(f'{t.name} ({t.seq})' for t in matches[:6]) + '.')
    return matches[0].seq


def check(options):
    """The argument rules of topic, before any request."""
    one_page = options.get('target') is None or options.get('top')
    if one_page and (options.get('since') or options.get('until') or options.get('after') or options.get('out')):
        if options.get('target') is None:
            raise SnsError('argument', 'The topic directory is one page of names.',
                           'Name a topic to read its posts.')
        raise SnsError('argument', 'Featured posts are one page: no window, no continuation, no file.',
                       'Drop --since/--until/--after/--out, or drop --top.')
    if options.get('target') is None and options.get('top'):
        raise SnsError('argument', 'The topic directory is one page of names.', 'Name a topic to read its posts.')


def topic(platform, invocation):
    options = invocation.options
    wanted = options.get('target')
    identity = {'topic': wanted, 'shelf': 'featured' if options.get('top') else None}
    words = ['--top'] if options.get('top') else []

    def read(connection, state, out):
        client = connection.client
        if wanted is None:
            return {'results': [t.to_dict() for t in web.topics(client.get('directories')['result'])],
                    'stop_reason': 'not_paginable'}
        seq = listing.resumed(state, out).get('seq') or topic_number(client, wanted)
        if options.get('top'):
            rows = client.get('directory_top', directorySeq=seq)['result']
            records = [r.to_dict() for r in map(web.post_record, rows) if r][:options.get('limit') or DISPLAY]
            if not records:
                return {'results': [], 'failure': SnsError('empty', f'Naver lists no featured posts for topic {seq}.',
                                                           listing.EMPTY_FIX)}
            return {'results': records, 'stop_reason': 'not_paginable'}
        result = listing.read_numbered(
            connection, state, out, op='directory_posts', source=listing.pages_of(
                client, 'directory_posts', {'directorySeq': seq}, web.post_record), command='topic', target=wanted,
            identity=identity, words=words, order='newest_first', show=DISPLAY, carry={'seq': seq})
        notes = ['a topic\'s list is Naver\'s choice of posts filed under it, newest first; it stops at 1,000']
        if not str(wanted).isdigit():
            notes.insert(0, f'topic {wanted} is number {seq}')
        result.setdefault('coverage', []).extend(notes)
        return result

    return reading.run(platform, invocation, command='topic', target=wanted, identity=identity, reader=read,
                       bound=wanted is not None and not options.get('top') and account.binds(options, DISPLAY),
                       window=listing.window_of(options, 'newest_first'))


def check_monthly(options):
    """The argument rules of monthly, before any request."""
    year, month = options.get('year'), options.get('month')
    if month is not None and not 1 <= month <= 12:
        raise SnsError('argument', '--month is 1 to 12.', 'Pass --year YYYY --month M.')
    if (year is None) != (month is None):
        raise SnsError('argument', 'Pass --year and --month together, or neither for the latest issue.',
                       'Add the missing one.')


def monthly(platform, invocation):
    """The blogs of the month for one issue: the published issues are listed, so the issue shown is never guessed."""
    options = invocation.options
    year, month = options.get('year'), options.get('month')

    def read(connection, state, out):
        client, sections = connection.client, []
        issues = [(int(y['year']), int(m)) for y in client.get('monthly_issues')['result']['yearList']
                  for m in y.get('monthList') or []]
        if not issues:
            raise SnsError('empty', 'Naver lists no blogs-of-the-month issue.', 'Nothing to read.')
        latest = max(issues)
        issue = (year, month) if year is not None else latest
        if issue not in issues:
            raise SnsError('unavailable', f'{year}-{month:02d} has no blogs-of-the-month issue.',
                           f'The latest is {latest[0]}-{latest[1]:02d}: run monthly --year {latest[0]} --month '
                           f'{latest[1]}.', reason='not_published')
        groups = client.get('monthly_blogs', year=issue[0], month=issue[1])['result']['directoryAndBlogIdList']
        ids = [blog for group in groups for blog in group.get('blogIdList') or []]
        cards, posts = {}, {}
        if ids:
            for raw in client.get('monthly_profiles', blogIdList=','.join(ids))['result']['blogProfileAndRelationView']:
                built = web.blog_record(raw)
                if built:
                    cards[built.blog_id] = built.to_dict()

            def popular():
                for entry in client.get('monthly_posts', blogIdList=','.join(ids))['result']['popularPostList']:
                    blog = entry.get('blogId')
                    posts[blog] = [r.to_dict() for r in (web.post_record(row, blog_id=blog) for row in
                                                           entry.get('postList') or []) if r][:POSTS_PER_BLOG]

            reading.section(sections, 'representative posts', popular)   # a failed one is shown beside the blogs
        for group in groups:
            data = []
            for blog in group.get('blogIdList') or []:
                data.append(cards.get(blog) or {'kind': 'blog', 'id': f'blog:{blog}', 'blog_id': blog,
                                                'url': f'https://blog.naver.com/{blog}'})
                data += posts.get(blog, [])
            sections.append({'name': (group.get('directory') or {}).get('name') or 'topic', 'ok': True, 'data': data})
        return {'sections': sections, 'stop_reason': 'not_paginable', 'details': {'issue': f'{issue[0]}-{issue[1]:02d}'},
                'coverage': [f'issue {issue[0]}-{issue[1]:02d}', f'each blog shows its first {POSTS_PER_BLOG} '
                             'representative posts; posts <id> --popular reads more']}

    return reading.run(platform, invocation, command='monthly', target=None, identity={}, reader=read, bound=False)
