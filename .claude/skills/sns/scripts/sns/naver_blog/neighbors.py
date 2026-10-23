"""feed (the logged-in account's neighbor feed) and buddies (neighbor lists).

Both read the account's own surfaces, so they ask who is logged in first (their address is that account's blog id); a
public neighbor list is a blog's and asks no one."""
from sns import reading
from sns.errors import SnsError

from sns.naver_blog import account, listing, web

FEED_DISPLAY, BUDDY_DISPLAY = 10, 20


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
                   'buddies --groups lists them).' if group else
                   'Naver reports no neighbor posts for this account (it may follow no blog yet).'))
        result.setdefault('coverage', []).append('the neighbor feed holds only the blogs this account follows, newest '
                                                 'first')
        return result

    return reading.run(platform, invocation, command='feed', target=None, identity=identity, reader=read,
                       window=listing.window_of(options, 'newest_first'))


def check(options):
    """The argument rules of buddies, before any request."""
    kinds = [flag for flag in ('followers', 'groups') if options.get(flag)] + (['group'] if options.get('group') else [])
    if len(kinds) > 1:
        raise SnsError('argument', 'Choose one of --followers, --group and --groups.', 'Run buddies once per list.')
    if options.get('groups') and (options.get('out') or options.get('after')):
        raise SnsError('argument', 'The neighbor groups are one page: no continuation, no file.',
                       'Drop --after/--out.')
    if options.get('target') and kinds:
        raise SnsError('argument', f'--{kinds[0]} reads your own neighbors; another blog shows only its public list.',
                       'Drop the blog, or drop the option.')


def buddies(platform, invocation):
    options = invocation.options
    target = web.parse_target(options['target'], 'blog') if options.get('target') else None
    if options.get('groups'):
        return groups(platform, invocation)
    kind = 'public' if target else 'followers' if options.get('followers') else 'mine'
    group = options.get('group')
    identity = {'blog': target and (target.blog_id or 'naver.me/' + target.short), 'kind': kind, 'group': group}
    words = (['--followers'] if kind == 'followers' else []) + (['--group', str(group)] if group else [])
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
            command='buddies', target=name, identity=identity, words=words, order='finite', show=BUDDY_DISPLAY,
            blog=ids.get('blogId'),
            empty=('This blog shows no public neighbors. A public neighbor list is private by default, so an empty '
                   'one does not mean no neighbors: blog <id> shows the card\'s neighbor count.') if target else None)
        return result

    return reading.run(platform, invocation, command='buddies', target=name, identity=identity, reader=read,
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

    return reading.run(platform, invocation, command='buddies', target=None, identity={'kind': 'groups'}, reader=read)
