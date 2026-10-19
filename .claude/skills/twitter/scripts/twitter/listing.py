"""feed, profile, graph, me, list and community posts: lists read by cursor in the server's order, with each
surface's date-window policy (twitter.window).
"""
import json

from twitter import connect
from twitter.errors import TwitterError
from twitter.x_web import parse_account, parse_community, parse_list, parse_post

# Both home feeds are X's choice of order: the following feed is not newest first (P2 R8), so neither closes a window.
FEEDS = {'foryou': ('foryou', 'unordered'), 'following': ('following', 'unordered')}


def feed(options):
    name = options.get('feed') or 'foryou'
    variant, order = FEEDS[name]
    identity = {'feed': name, 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        return connect.read_list(options, identity, state, out, order=order, command='feed', target=None,
                     fetch=lambda cursor: connection.client.feed(variant, cursor))

    return connect.run(options, command='feed', target=None, identity=identity, reader=read,
                       window=connect.window_of(options, order))


# tab → (operation, date order). posts is UserTweets: posts and reposts, newest first (X's own Posts tab now hides
# reposts, X14); media is UserMedia: photos, videos and GIFs (X's own Media tab now shows videos only).
TABS = {'posts': ('UserTweets', 'newest_first'), 'replies': ('UserRepliesTimeline', 'newest_first'),
        'media': ('UserMedia', 'finite'), 'highlights': ('UserHighlightsTweets', 'finite'),
        'articles': ('UserArticlesTweets', 'finite'), 'lists': ('CombinedLists', None),
        'memberships': ('ListMemberships', None)}


def profile(options):
    target = parse_account(options['target'])
    tab = options.get('tab')
    if tab and target.tab and tab != target.tab:
        raise TwitterError(2, f'The URL is the {target.tab} tab but --tab asks for {tab}.', 'Give one of them.')
    tab = tab or target.tab or 'posts'
    operation, order = TABS[tab]
    if order is None and (options.get('since') or options.get('until')):
        raise TwitterError(2, f'The {tab} tab holds lists, which are not dated.', 'Drop --since and --until.')
    identity = {'tab': tab, 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id, card = saved.get('user_id'), None
        if not user_id:
            card = client.user(target.handle)
            user_id = card['id']
        reading = connect.read_list(options, identity, state, out, order=order, command='profile', target=target.url,
                        extra={'user_id': user_id},
                        fetch=lambda cursor: client.timeline(operation, {'userId': user_id}, cursor))
        if card is not None and not reading['results'] and not reading.get('failure') and \
                not reading.get('continuation') and (out is None or not out.count):
            if card.get('private') and (card.get('relationship') or {}).get('following') is not True:
                reading['failure'] = TwitterError(9, f'@{target.handle} is protected and this account does not follow '
                                                     'it.', 'Tell the user; only approved followers can read it.',
                                                  reason='unavailable')
        return reading

    return connect.run(options, command='profile', target=target.url, identity=identity, reader=read,
                       window=connect.window_of(options, order))


RELATIONS = {'following': 'Following', 'followers': 'Followers', 'verified': 'BlueVerifiedFollowers',
             'known': 'FollowersYouKnow', 'similar': 'ConnectTabTimeline'}
# 성진: X의 계정 목록은 커서를 주면서 빈 쪽을 이어 보낼 때가 있다(현행 지식) — 새것 없는 쪽 3번 연속이면 멈춘다
ACCOUNT_IDLE_PAGES = 3


def graph(options):
    target = parse_account(options['target'])
    relation = options['relation']
    identity = {'relation': relation}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id = saved.get('user_id') or client.user(target.handle)['id']
        # the app asks for similar accounts with the profile as context (P2 R5), every other relation by user id
        variables = ({'context': json.dumps({'contextualUserId': user_id})} if relation == 'similar'
                     else {'userId': user_id})
        reading = connect.read_list(options, identity, state, out, order=None, command='graph', target=target.url,
                                    extra={'user_id': user_id}, words=[relation], idle_limit=ACCOUNT_IDLE_PAGES,
                                    fetch=lambda cursor: client.timeline(RELATIONS[relation], variables, cursor))
        if relation == 'similar':
            reading['coverage'] = ['X recommends these as similar to this account; they are not its relationships',
                                   *(reading.get('coverage') or [])]
        return reading

    return connect.run(options, command='graph', target=target.url, identity=identity, reader=read)


# list tab → (operation, what it holds). X serves a list's posts in its own order (not verified newest first).
LIST_TABS = {'posts': 'ListLatestTweetsTimeline', 'members': 'ListMembers'}


def lists(options):
    target = parse_list(options['target'])
    tab = options['tab']
    identity = {'tab': tab}

    def read(connection, state, out):
        client = connection.client
        if tab == 'about':
            return {'results': [client.x_list(target.list_id)], 'stop_reason': 'not_paginable'}
        return connect.read_list(options, identity, state, out, order='unordered' if tab == 'posts' else None,
                                 command='list', target=target.url, idle_limit=ACCOUNT_IDLE_PAGES,
                                 fetch=lambda cursor: client.timeline(LIST_TABS[tab], {'listId': target.list_id}, cursor))

    return connect.run(options, command='list', target=target.url, identity=identity, reader=read)


COMMUNITY_TABS = {'posts': 'CommunityTweetsTimeline', 'media': 'CommunityMediaTimeline'}


def community(options):
    """A community's posts, media or card; without a target, the communities X suggests to this account."""
    if not options.get('target'):
        return _discovery(options)
    target = parse_community(options['target'])
    tab, sort = options['tab'], options['sort']
    identity = {'tab': tab, 'sort': sort if tab == 'posts' else None}

    def read(connection, state, out):
        client = connection.client
        if tab == 'about':
            return {'results': [client.community(target.community_id)], 'stop_reason': 'not_paginable'}
        variables = {'communityId': target.community_id}
        if tab == 'posts':
            variables['rankingMode'] = 'Recency' if sort == 'recent' else 'Relevance'
        return connect.read_list(options, identity, state, out, order='unordered', command='community',
                                 target=target.url, words=['--tab', tab] + (['--sort', sort] if tab == 'posts' else []),
                                 fetch=lambda cursor: client.timeline(COMMUNITY_TABS[tab], variables, cursor))

    return connect.run(options, command='community', target=target.url, identity=identity, reader=read)


def _discovery(options):
    def read(connection, state, out):
        client = connection.client
        reading = connect.read_list(options, {}, state, out, order=None, command='community',
                                    target=None, fetch=lambda cursor: client.timeline('CommunityDiscoveryTimeline', {},
                                                                                     cursor))
        reading['coverage'] = ['communities X suggests to this account, not a ranking of all communities',
                               *(reading.get('coverage') or [])]
        return reading

    return connect.run(options, command='community', target=None, identity={}, reader=read)  # no target: the suggestions


def reposts(options):
    target = parse_post(options['target'])

    def read(connection, state, out):
        client = connection.client
        return connect.read_list(options, {}, state, out, order=None, command='reposts', target=target.url,
                                 idle_limit=ACCOUNT_IDLE_PAGES,
                                 fetch=lambda cursor: client.timeline('Retweeters', {'tweetId': target.post_id}, cursor))

    return connect.run(options, command='reposts', target=target.url, identity={}, reader=read)


def me(options):
    collection = options['collection']
    identity = {'collection': collection}

    def read(connection, state, out):
        client = connection.client
        if collection == 'likes':
            fetch = lambda cursor: client.timeline('Likes', {'userId': connection.account_id}, cursor)  # noqa: E731
        else:
            fetch = lambda cursor: client.timeline('Bookmarks', {}, cursor)  # noqa: E731
        return connect.read_list(options, identity, state, out, order='unordered', command='me', target=None, words=[collection],
                     fetch=fetch)

    return connect.run(options, command='me', target=None, identity=identity, reader=read)
