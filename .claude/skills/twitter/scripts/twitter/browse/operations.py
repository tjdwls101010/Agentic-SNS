"""What each command asks X for: its operation and variables, requests it needs first, and result finishing.

cli.py's declarations name these functions; nothing here branches on the command.
"""
from ..errors import TwitterError
from ..graphql.protocol.transport import root_at
from ..graphql.responses.records import build_place, build_user
from ..graphql.responses.targets import parse
from ..graphql.responses.thread import completeness

USER_TABS = {'posts': 'UserTweets', 'replies': 'UserTweetsAndReplies', 'replies-only': 'UserRepliesTimeline',
             'media': 'UserMedia', 'highlights': 'UserHighlightsTweets', 'articles': 'UserArticlesTweets'}
RELATIONS = dict(following='Following', followers='Followers', verified='BlueVerifiedFollowers', known='FollowersYouKnow')


def resolve(values, kind):
    """Parse targets before any request; an invalid one is an argument error."""
    return [parse(value, kind) for value in values]


# Operations: args -> (operation, variables).

def home(args):
    return ('HomeLatestTimeline' if args.feed == 'following' else 'HomeTimeline'), {}


def user(args):
    return USER_TABS[args.tab], {}


def graph(args):
    return RELATIONS[args.relation], {}


def collection(args):
    return ('Bookmarks' if args.collection == 'bookmarks' else 'Likes'), {}


def search(args):
    variables = {'rawQuery': args.target}
    if args.scope:
        return 'GlobalCommunitiesLatestPostSearchTimeline', variables
    variables['product'] = 'People' if args.type == 'users' else 'Media' if args.type == 'media' else args.sort.title()
    return 'SearchTimeline', variables


def quotes(args):
    return 'SearchTimeline', dict(rawQuery='quoted_tweet_id:' + args.targets[0].tweet_id, product='Latest')


def reposts(args):
    return 'Retweeters', dict(tweetId=args.targets[0].tweet_id)


def post(args):
    if len(args.targets) > 1:
        return 'TweetResultsByRestIds', dict(tweetIds=[t.tweet_id for t in args.targets])
    return 'TweetDetail', dict(focalTweetId=args.targets[0].tweet_id, rankingMode='Recency' if args.sort == 'recent' else 'Relevance')


def about(args):
    if len(args.targets) > 1:
        return 'UsersByScreenNames', dict(screen_names=[t.handle for t in args.targets])
    return 'UserByScreenName', dict(screen_name=args.targets[0].handle)


def listing(args):
    return {'posts': 'ListLatestTweetsTimeline', 'members': 'ListMembers', 'about': 'ListByRestId'}[args.tab], dict(listId=args.targets[0].list_id)


def community(args):
    variables = dict(communityId=args.targets[0].community_id)
    if args.tab == 'posts':
        variables['rankingMode'] = 'Recency' if args.sort == 'recent' else 'Relevance'
    return {'posts': 'CommunityTweetsTimeline', 'media': 'CommunityMediaTimeline', 'about': 'CommunityAboutTimeline'}[args.tab], variables


def communities(args):
    return 'CommunitiesExploreTimeline', {}


def trends(args):
    return 'ExplorePage', {}


# Prepares: requests made before the first page; they return the card to show and may fill variables.

def profile_id(transport, args, session, state, variables, card):
    """Profile timelines need the numeric user ID, resolved once per query and kept in its state."""
    if not state.get('user_id'):
        card = build_user(transport.query('UserByScreenName', {'screen_name': args.targets[0].handle})).to_dict()
        state['user_id'] = card['id']
    variables['userId'] = state['user_id']
    return card


def viewer_likes(transport, args, session, state, variables, card):
    if args.collection == 'likes':
        variables['userId'] = session['viewer_id']
    return card


def community_card(transport, args, session, state, variables, card):
    return card or build_place(transport.query('CommunityByRestId', {'communityId': args.targets[0].community_id}), 'community').to_dict()


# Fetches: a first page that takes more than one request.

def explore(transport, args):
    """An Explore tab: the landing page names each tab's timeline, which is a second request except For you."""
    body = transport.query('ExplorePage')
    if args.tab == 'foryou':
        return root_at(body, 'initialTimeline.timeline.timeline.instructions')
    tab = next((t for t in body.get('timelines', []) if t.get('id') == args.tab), None)
    timeline_id = tab.get('timeline', {}).get('id') if tab else None
    if not timeline_id:
        raise TwitterError(6, 'Explore tab ID is missing.', 'Update the Explore parser.', 'envelope_drift')
    return transport.query('GenericTimelineById', {'timelineId': timeline_id})


# Finishes: what a collected result adds before it is shown.

def thread_completeness(result, args):
    if len(args.targets) == 1:
        result.update(completeness(result['results'], args.targets[0].tweet_id, result))


def unresolved_handles(result, args):
    resolved = {row['screen_name'].lower() for row in result['results']}
    result['unresolved'] = [t.handle for t in args.targets if t.handle.lower() not in resolved]
