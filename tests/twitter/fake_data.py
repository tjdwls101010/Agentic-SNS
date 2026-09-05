"""Synthetic public response shapes; no captured user content or credentials."""


def user(identity="100", handle="example"):
    return {
        "__typename": "User",
        "rest_id": identity,
        "core": {"screen_name": handle, "name": "Example", "created_at": "Wed Jan 01 00:00:00 +0000 2020"},
        "relationship_counts": {"followers": 1200, "following": 40},
        "tweet_counts": {"tweets": 50, "media_tweets": 4},
        "profile_bio": {"description": "Synthetic profile"},
        "privacy": {"protected": False},
        "verification": {"verified_type": "Government"},
    }


def tweet(identity="200", parent=None):
    return {
        "__typename": "Tweet",
        "rest_id": identity,
        "core": {"user_results": {"result": user()}},
        "legacy": {
            "full_text": "Synthetic post https://t.co/example",
            "created_at": "Sat Sep 05 01:00:00 +0000 2026",
            "in_reply_to_status_id_str": parent,
            "favorite_count": 1200,
            "reply_count": 7,
            "entities": {"urls": [{"url": "https://t.co/example", "expanded_url": "https://example.com/story"}]},
        },
    }


def entry(node, kind="tweet"):
    return {"entryId": kind + "-" + node["rest_id"], "content": {"itemContent": {kind + "_results": {"result": node}}}}


def instructions(nodes, kind="tweet", cursor="next"):
    entries = [entry(n, kind) for n in nodes]
    if cursor:
        entries.append({"entryId": "cursor-bottom", "content": {"cursorType": "Bottom", "value": cursor}})
    return [{"type": "TimelineAddEntries", "entries": entries}]


ROOTS = {
    "HomeTimeline": "data.home.home_timeline_urt.instructions",
    "HomeLatestTimeline": "data.home.home_timeline_urt.instructions",
    "UserByScreenName": "data.user.result",
    "Viewer": "data.viewer.user_results.result",
    "SearchTimeline": "data.search_by_raw_query.search_timeline.timeline.instructions",
    "TweetDetail": "data.threaded_conversation_with_injections_v2.instructions",
    "Bookmarks": "data.bookmark_timeline_v2.timeline.instructions",
    "Retweeters": "data.retweeters_timeline.timeline.instructions",
    "ListByRestId": "data.list",
    "ListMembers": "data.list.members_timeline.timeline.instructions",
    "ListLatestTweetsTimeline": "data.list.tweets_timeline.timeline.instructions",
    "ExplorePage": "data.explore_page.body",
    "GenericTimelineById": "data.timeline.timeline.instructions",
    "CommunityByRestId": "data.communityResults.result",
    "CommunityTweetsTimeline": "data.communityResults.result.ranked_community_timeline.timeline.instructions",
    "CommunityMediaTimeline": "data.communityResults.result.community_media_timeline.timeline.instructions",
    "CommunityAboutTimeline": "data.communityResults.result.about_timeline.timeline.instructions",
    "CommunitiesExploreTimeline": "data.viewer.explore_communities_timeline.timeline.instructions",
    "GlobalCommunitiesLatestPostSearchTimeline": "data.search_by_raw_query.communities_latest_posts_search_page.timeline.instructions",
}


def response(op, v, scenario="normal"):
    cursor = v.get("cursor")
    if scenario == "429" and cursor:
        return 429, {"errors": [{"code": 88, "message": "Rate limit"}]}
    if op == "UsersByScreenNames":
        return 200, {
            "data": {
                "users": [{"result": user(str(100 + i), h)} for i, h in enumerate(v["screen_names"]) if h != "missing"]
            }
        }
    if op == "TweetResultsByRestIds":
        return 200, {"data": {"tweetResult": [{"result": tweet(i)} for i in v["tweetIds"]]}}
    if op in ("Viewer", "UserByScreenName"):
        root = user(handle=v.get("screen_name", "example"))
    elif op == "ListByRestId":
        root = {
            "id_str": v["listId"],
            "name": "Example list",
            "description": "Synthetic",
            "member_count": 3,
            "mode": "Public",
        }
    elif op == "CommunityByRestId":
        root = {
            "rest_id": v["communityId"],
            "name": "Example community",
            "member_count": 3,
            "join_policy": "Open",
            "rules": [{"name": "Be kind"}],
        }
    elif op == "ExplorePage":
        root = {
            "timelines": [
                {"id": k, "timeline": {"id": "trend-" + k}} for k in ["trending", "news", "sports", "entertainment"]
            ],
            "initialTimeline": {
                "timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "trend-1",
                                        "content": {
                                            "itemContent": {
                                                "itemType": "TimelineTrend",
                                                "name": "Example trend",
                                                "trend_metadata": {"domain_context": "Synthetic region"},
                                            }
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                }
            },
        }
    elif op == "GenericTimelineById":
        root = [
            {
                "type": "TimelineAddEntries",
                "entries": [
                    {
                        "entryId": "trend-1",
                        "content": {
                            "itemContent": {
                                "itemType": "TimelineTrend",
                                "name": "Example trend",
                                "trend_metadata": {"domain_context": "Synthetic region"},
                            }
                        },
                    }
                ],
            }
        ]
    elif op == "CommunityAboutTimeline":
        root = [
            {
                "type": "TimelineAddEntries",
                "entries": [
                    {
                        "entryId": "communityModerators-1",
                        "content": {
                            "items": [
                                {"entryId": "user-100", "item": {"itemContent": {"user_results": {"result": user()}}}}
                            ]
                        },
                    }
                ],
            }
        ]
    elif op == "TweetDetail":
        focal = v["focalTweetId"]
        root = instructions(
            [tweet("99"), tweet(focal), tweet("301", focal), tweet("302", "301")]
            if not cursor
            else [tweet("302", "301"), tweet("303", focal)],
            cursor=None if cursor else "next",
        )
    else:
        users = (
            op in ("Following", "Followers", "BlueVerifiedFollowers", "FollowersYouKnow", "Retweeters", "ListMembers")
            or v.get("product") == "People"
        )
        nodes = [
            user(str(100 + i), f"example{i}") if users else tweet(str(200 + i))
            for i in (range(4, 7) if cursor else range(5))
        ]
        if v.get("rawQuery", "").startswith("quoted_tweet_id:"):
            for n in nodes:
                n["legacy"]["quoted_status_id_str"] = v["rawQuery"].split(":")[1]
        root = instructions(nodes, "user" if users else "tweet", None if cursor else "next")
        if scenario == "empty":
            root = []
        if scenario == "empty_users":
            root = instructions([], cursor=(cursor or "") + "x")
    path = ROOTS.get(op, "data.user.result.timeline.timeline.instructions")
    body = root
    for key in reversed(path.split(".")):
        body = {key: body}
    return 200, body
