"""feed (the logged-in account's neighbor feed), buddies (neighbor lists) and news (내소식).

All three read the account's own surfaces, so they ask who is logged in first (their address is that account's blog id); a
public neighbor list is a blog's and asks no one."""
from sns import reading
from sns.errors import SnsError

from sns.naver_blog import account, listing, web

FEED_DISPLAY, BUDDY_DISPLAY, NEWS_DISPLAY = 10, 20, 5


def feed(platform, invocation):
    options = invocation.options
    group = options.get('group')
    identity = {'group': group}
    words = ['--group', str(group)] if group else []

    def read(connection, state, out):
        ids = {'me': connection.viewer(), 'groupId': group or 0}
        result = listing.read_numbered(
            connection, state, out, op='feed', source=listing.pages_of(connection.client, 'feed', ids, web.post_record),
            command='feed', target=None, identity=identity, words=words, order='newest_first', show=FEED_DISPLAY,
            empty=(f'Naver reports no posts from neighbor group {group} (an unknown group answers the same way; '
                   'me groups lists them).' if group else
                   'Naver reports no neighbor posts for this account (it may follow no blog yet).'))
        result.setdefault('coverage', []).append('the neighbor feed holds only the blogs this account follows, newest '
                                                 'first')
        return result

    return reading.run(platform, invocation, command='feed', target=None, identity=identity, reader=read,
                       window=listing.window_of(options, 'newest_first'))


def check(options):
    """The argument rules of buddies, before any request."""
    if options.get('collection') == 'groups':
        if options.get('out') or options.get('after') or options.get('limit'):
            raise SnsError('argument', 'The neighbor groups are one page: no continuation, no file, no limit.',
                           'Drop --after/--out/--limit.')
        return
    if options.get('group') and (options.get('target') or options['relation'] != 'buddies'):
        raise SnsError('argument', '--group reads your own buddies.', 'Drop the blog or choose buddies without --group.')
    if options.get('target') and options['relation'] == 'followers':
        raise SnsError('argument', 'Followers are available only for your own blog.', 'Drop the blog.')


def buddies(platform, invocation):
    options = invocation.options
    target = web.parse_target(options['target'], 'blog') if options.get('target') else None
    if options.get('collection') == 'groups':
        return groups(platform, invocation)
    if options.get('collection') == 'news':
        return news(platform, invocation)
    kind = 'public' if target else 'followers' if options.get('relation') == 'followers' else 'mine'
    group = options.get('group')
    identity = {'blog': target and (target.blog_id or 'naver.me/' + target.short), 'kind': kind, 'group': group}
    words = [options['relation']] + (['--group', str(group)] if group else [])
    name = target.handle if target else None

    def read(connection, state, out):
        client = connection.client
        if kind == 'followers':
            op, ids = 'followers', {'me': connection.viewer()}
        elif target is None:
            op, ids = 'my_buddies', {'me': connection.viewer(), 'groupId': group}
        else:
            ids = {'blogId': listing.resumed(state, out).get('blog_id') or client.target(options['target'], 'blog').blog_id}
            op = 'public_buddies'
        result = listing.read_numbered(
            connection, state, out, op=op, source=listing.pages_of(client, op, ids, web.buddy_record),
            command='graph', target=name, identity=identity, words=words, order='finite', show=BUDDY_DISPLAY,
            blog=ids.get('blogId'),
            empty=('This blog shows no public neighbors. A public neighbor list is private by default, so an empty '
                   'one does not mean no neighbors: about <id> shows the card\'s neighbor count.') if target else None)
        return result

    return reading.run(platform, invocation, command='graph', target=name, identity=identity, reader=read,
                       bound=target is None or account.binds(options, BUDDY_DISPLAY))


def groups(platform, invocation):
    """Your neighbor groups: one page."""
    def read(connection, state, out):
        rows = connection.client.get('buddy_groups', me=connection.viewer())['result']
        found = [g.to_dict() for g in map(web.group_record, rows) if g]
        if not found:
            return {'results': [], 'failure': SnsError('empty', 'This account has no neighbor groups.',
                                                       listing.EMPTY_FIX)}
        return {'results': found, 'stop_reason': 'not_paginable'}

    return reading.run(platform, invocation, command='me', target=None, identity={'kind': 'groups'}, reader=read)


def news(platform, invocation):
    """Your 내소식 (replies to your comments, comments on your posts ...), newest first, a page at a time. Reading marks
    nothing read; the account check (bound) comes first."""
    def read(connection, state, out):
        return reading.read_list(connection, state, out, order='newest_first', command='me', target=None,
                                 fetch=lambda cursor: connection.client.after('news', cursor, web.news_record),
                                 identity={'kind': 'news'}, words=['news'], show=NEWS_DISPLAY)

    return reading.run(platform, invocation, command='me', target=None, identity={'kind': 'news'}, reader=read)
