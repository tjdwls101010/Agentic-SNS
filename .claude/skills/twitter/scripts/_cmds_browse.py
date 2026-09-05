"""Resolve CLI browsing intent into immutable operation and variable choices."""
USER_TABS = {'posts': 'UserTweets', 'replies': 'UserTweetsAndReplies', 'replies-only': 'UserRepliesTimeline',
             'media': 'UserMedia', 'highlights': 'UserHighlightsTweets', 'articles': 'UserArticlesTweets'}
RELATIONS = dict(following='Following', followers='Followers', verified='BlueVerifiedFollowers', known='FollowersYouKnow')


def operation(args):
    command = args.command
    variables = {}
    target = args.targets[0] if hasattr(args, 'targets') else None
    if command == 'home':
        return ('HomeLatestTimeline' if args.feed == 'following' else 'HomeTimeline'), variables
    if command == 'user':
        return USER_TABS[args.tab], variables
    if command == 'graph':
        return RELATIONS[args.relation], variables
    if command == 'me':
        return ('Bookmarks' if args.collection == 'bookmarks' else 'Likes'), variables
    if command == 'search':
        variables['rawQuery'] = args.target
        if args.scope:
            return 'GlobalCommunitiesLatestPostSearchTimeline', variables
        variables['product'] = 'People' if args.type == 'users' else 'Media' if args.type == 'media' else args.sort.title()
        return 'SearchTimeline', variables
    if command == 'quotes':
        return 'SearchTimeline', dict(rawQuery='quoted_tweet_id:' + target.tweet_id, product='Latest')
    if command == 'reposts':
        return 'Retweeters', dict(tweetId=target.tweet_id)
    if command == 'post':
        if len(args.targets) > 1:
            return 'TweetResultsByRestIds', dict(tweetIds=[t.tweet_id for t in args.targets])
        return 'TweetDetail', dict(focalTweetId=target.tweet_id, rankingMode='Recency' if args.sort == 'recent' else 'Relevance')
    if command == 'about':
        if len(args.targets) > 1:
            return 'UsersByScreenNames', dict(screen_names=[t.handle for t in args.targets])
        return 'UserByScreenName', dict(screen_name=target.handle)
    if command == 'list':
        return {'posts': 'ListLatestTweetsTimeline', 'members': 'ListMembers', 'about': 'ListByRestId'}[args.tab], dict(listId=target.list_id)
    if command == 'community':
        variables = dict(communityId=target.community_id)
        if args.tab == 'posts':
            variables['rankingMode'] = 'Recency' if args.sort == 'recent' else 'Relevance'
        return {'posts': 'CommunityTweetsTimeline', 'media': 'CommunityMediaTimeline', 'about': 'CommunityAboutTimeline'}[args.tab], variables
    if command == 'communities':
        return 'CommunitiesExploreTimeline', variables
    return 'ExplorePage', variables
