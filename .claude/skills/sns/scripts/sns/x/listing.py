"""feed, profile, graph, me, list and community: lists read by cursor in the server's order, with each surface's
date-window policy (sns.window). `surface` is the one place a timeline page becomes a reading page: what X mixes into
a surface (accounts it suggests among posts, dated by when they joined) is left out before the window weighs the
page's order, and counted."""
import json

from sns import reading
from sns.errors import SnsError
from sns.page import Page
from sns.window import Window
from sns.x import web

# What a page left out, in coverage's words
NOTES = {'promoted': 'promoted entries (ads)', 'other': 'other items X mixed in',
         'unreadable': 'entries this skill could not read (X may have changed its answer)'}
# 성진: X의 계정 목록은 커서를 주면서 빈 쪽을 이어 보낼 때가 있다(현행 지식) — 새것 없는 쪽 3번 연속이면 멈춘다
ACCOUNT_IDLE_PAGES = 3


def paged(listed, kinds):
    """The reading Page of one timeline page (web.list_page), keeping only `kinds` of record."""
    kept = [r for r in listed.records if r.get('kind') in kinds]
    foreign = sum(1 for kind in listed.unreadable_kinds if kind not in kinds)
    other = listed.other + len(listed.records) - len(kept) + foreign
    unreadable = listed.unreadable - foreign
    left_out = {label: count for label, count in (('promoted', listed.promoted), ('other', other),
                                                  ('unreadable', unreadable)) if count}
    return Page(kept, next=listed.cursor, end=not listed.has_next, left_out=left_out, unreadable=unreadable)


def surface(connection, state, out, *, kinds, fetch, order, command, target, identity, words=(), extra=None,
            idle_limit=2, end_covers_window=False):
    """Read a timeline surface (fetch(cursor) → a web.list_page result) as reading.read_list does."""
    return reading.read_list(connection, state, out, order=order, command=command, target=target, identity=identity,
                             words=words, extra=extra, idle_limit=idle_limit, end_covers_window=end_covers_window,
                             notes=NOTES, fetch=lambda cursor: paged(fetch(cursor), kinds))


def flags(identity, keys=('feed', 'tab', 'sort')):
    """The option words that rerun a command with this identity."""
    words = []
    for key in keys:
        if identity.get(key):
            words += ['--' + key, identity[key]]
    return words


def window_of(platform, options, order):
    """The date window a result names even when the read failed before it began (None: no --since/--until)."""
    if not (options.get('since') or options.get('until')):
        return None
    return Window(options.get('since'), options.get('until'), order=order, policy=platform.window).describe()


def feed(platform, invocation):
    options = invocation.options
    name = options.get('feed') or 'foryou'
    identity = {'feed': name}

    def read(connection, state, out):
        return surface(connection, state, out, order='ranked', command='feed', target=None, identity=identity,
                       kinds=('post',), words=flags(identity), fetch=lambda cursor: connection.client.feed(name, cursor))

    # both home feeds are X's choice of order (the following feed is not newest first, P2 R8): neither closes a window,
    # and neither ends by itself, so --out needs --limit
    return reading.run(platform, invocation, command='feed', target=None, identity=identity, reader=read, endless=True,
                       window=window_of(platform, options, 'ranked'))


# tab → (operation, date order). posts is UserTweets: posts and reposts, newest first (X's own Posts tab now hides
# reposts, X14); media is UserMedia: photos, videos and GIFs (X's own Media tab now shows videos only).
TABS = {'posts': ('UserTweets', 'newest_first'), 'replies': ('UserRepliesTimeline', 'newest_first'),
        'media': ('UserMedia', 'finite'), 'highlights': ('UserHighlightsTweets', 'finite'),
        'articles': ('UserArticlesTweets', 'finite'), 'lists': ('CombinedLists', 'finite'),
        'memberships': ('ListMemberships', 'finite')}
DATED_TABS = ('posts', 'replies', 'media', 'highlights', 'articles')


def profile(platform, invocation):
    options = invocation.options
    target = web.parse_account(options['target'])
    tab = options.get('tab')
    if tab and target.tab and tab != target.tab:
        raise SnsError('argument', f'The URL is the {target.tab} tab but --tab asks for {tab}.', 'Give one of them.')
    tab = tab or target.tab or 'posts'
    operation, order = TABS[tab]
    if tab not in DATED_TABS and (options.get('since') or options.get('until')):
        raise SnsError('argument', f'The {tab} tab holds lists, which are not dated.', 'Drop --since and --until.')
    identity = {'tab': tab}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id, card = saved.get('user_id'), None
        if not user_id:
            card = client.user(target.handle)
            user_id = card['id']
        result = surface(connection, state, out, order=order, command='profile', target=target.url, identity=identity,
                         kinds=('list',) if tab not in DATED_TABS else ('post',), words=flags(identity),
                         extra={'user_id': user_id}, end_covers_window=True,
                         fetch=lambda cursor: client.timeline(operation, {'userId': user_id}, cursor))
        if card is not None and not result['results'] and not result.get('failure') and \
                not result.get('continuation') and (out is None or not out.count):
            if card.get('private') and (card.get('relationship') or {}).get('following') is not True:
                result['failure'] = SnsError('unavailable', f'@{target.handle} is protected and this account does not '
                                                            'follow it.', 'Tell the user; only approved followers can '
                                                                          'read it.', reason='unavailable')
        return result

    return reading.run(platform, invocation, command='profile', target=target.url, identity=identity, reader=read,
                       window=window_of(platform, options, order))


RELATIONS = {'following': 'Following', 'followers': 'Followers', 'verified': 'BlueVerifiedFollowers',
             'known': 'FollowersYouKnow', 'similar': 'ConnectTabTimeline'}


def graph(platform, invocation):
    options = invocation.options
    target = web.parse_account(options['target'])
    relation = options['relation']
    identity = {'relation': relation}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id = saved.get('user_id') or client.user(target.handle)['id']
        # the app asks for similar accounts with the profile as context (P2 R5), every other relation by user id
        variables = ({'context': json.dumps({'contextualUserId': user_id})} if relation == 'similar'
                     else {'userId': user_id})
        result = surface(connection, state, out, order='finite', command='graph', target=target.url,
                         identity=identity, kinds=('account',), extra={'user_id': user_id}, words=[relation],
                         idle_limit=ACCOUNT_IDLE_PAGES,
                         fetch=lambda cursor: client.timeline(RELATIONS[relation], variables, cursor))
        if relation == 'similar':
            result['coverage'] = ['X recommends these as similar to this account; they are not its relationships',
                                  *(result.get('coverage') or [])]
        return result

    return reading.run(platform, invocation, command='graph', target=target.url, identity=identity, reader=read)


# list tab → operation. X serves a list's posts in its own order (not verified newest first).
LIST_TABS = {'posts': 'ListLatestTweetsTimeline', 'members': 'ListMembers'}


def lists(platform, invocation):
    options = invocation.options
    target = web.parse_list(options['target'])
    tab = options['tab']
    identity = {'tab': tab}

    def read(connection, state, out):
        client = connection.client
        if tab == 'about':
            return {'results': [client.x_list(target.list_id)], 'stop_reason': 'not_paginable'}
        return surface(connection, state, out, order='ranked' if tab == 'posts' else 'finite',
                       kinds=('post',) if tab == 'posts' else ('account',), command='list', target=target.url,
                       identity=identity, words=flags(identity), idle_limit=ACCOUNT_IDLE_PAGES,
                       fetch=lambda cursor: client.timeline(LIST_TABS[tab], {'listId': target.list_id}, cursor))

    return reading.run(platform, invocation, command='list', target=target.url, identity=identity, reader=read)


COMMUNITY_TABS = {'posts': 'CommunityTweetsTimeline', 'media': 'CommunityMediaTimeline'}


def community(platform, invocation):
    """A community's posts, media or card; without a target, the communities X suggests to this account."""
    options = invocation.options
    if not options.get('target'):
        return _discovery(platform, invocation)
    target = web.parse_community(options['target'])
    tab, sort = options['tab'] or 'posts', options['sort'] or 'top'
    identity = {'tab': tab, 'sort': sort if tab == 'posts' else None}

    def read(connection, state, out):
        client = connection.client
        if tab == 'about':
            return {'results': [client.community(target.community_id)], 'stop_reason': 'not_paginable'}
        variables = {'communityId': target.community_id}
        if tab == 'posts':
            variables['rankingMode'] = 'Recency' if sort == 'recent' else 'Relevance'
        return surface(connection, state, out, order='ranked', command='community', kinds=('post',),
                       target=target.url, identity=identity, words=flags(identity),
                       fetch=lambda cursor: client.timeline(COMMUNITY_TABS[tab], variables, cursor))

    return reading.run(platform, invocation, command='community', target=target.url, identity=identity, reader=read)


def _discovery(platform, invocation):
    def read(connection, state, out):
        result = surface(connection, state, out, order='finite', command='community', kinds=('community',),
                         target=None, identity={},
                         fetch=lambda cursor: connection.client.timeline('CommunityDiscoveryTimeline', {}, cursor))
        result['coverage'] = ['communities X suggests to this account, not a ranking of all communities',
                              *(result.get('coverage') or [])]
        return result

    return reading.run(platform, invocation, command='community', target=None, identity={}, reader=read)


def reposts(platform, invocation):
    target = web.parse_post(invocation.options['target'])

    def read(connection, state, out):
        return surface(connection, state, out, order='finite', command='reposts', target=target.url, identity={},
                       kinds=('account',), idle_limit=ACCOUNT_IDLE_PAGES,
                       fetch=lambda cursor: connection.client.timeline('Retweeters', {'tweetId': target.post_id},
                                                                       cursor))

    return reading.run(platform, invocation, command='reposts', target=target.url, identity={}, reader=read)


def me(platform, invocation):
    collection = invocation.options['collection']
    identity = {'collection': collection}

    def read(connection, state, out):
        client = connection.client
        if collection == 'likes':
            def fetch(cursor):
                return client.timeline('Likes', {'userId': connection.viewer()}, cursor)
        elif collection in ('notifications', 'mentions'):
            # only the read: X's notifications screen is never opened (opening it marks them read, P2 R5)
            kind = 'Mentions' if collection == 'mentions' else 'All'

            def fetch(cursor):
                return client.timeline('NotificationsTimeline', {'timeline_type': kind}, cursor)
        else:
            def fetch(cursor):
                return client.timeline('Bookmarks', {}, cursor)
        return surface(connection, state, out, order='ranked', command='me', target=None, identity=identity,
                       words=[collection], fetch=fetch,
                       kinds=('notification', 'post') if collection in ('notifications', 'mentions') else ('post',))

    return reading.run(platform, invocation, command='me', target=None, identity=identity, reader=read)
