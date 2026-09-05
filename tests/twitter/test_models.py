from twitter_skill._models import build_tweet
from twitter_skill._entities import build_user
from twitter_skill._walk import walk


def user(id="100", handle="example"):
    return {
        "rest_id": id,
        "core": {"screen_name": handle, "name": "Example"},
        "relationship_counts": {"followers": 1200, "following": 3},
        "privacy": {"protected": True},
        "verification": {"verified_type": "Government"},
        "tweet_counts": {"tweets": 42},
    }


def tweet(id="200", text="short", **legacy):
    return {
        "rest_id": id,
        "core": {"user_results": {"result": user()}},
        "legacy": {"full_text": text, "favorite_count": 12, **legacy},
    }


def test_new_user_map():
    card = build_user(user()).to_dict()
    assert (
        card["followers_count"],
        card["following_count"],
        card["tweet_count"],
        card["verified_type"],
        card["is_protected"],
    ) == (1200, 3, 42, "Government", True)


def test_repost_note_quote_visibility():
    original = tweet("201")
    original["note_tweet"] = {"note_tweet_results": {"result": {"text": "long text"}}}
    outer = tweet("202", retweeted_status_result={"result": original}, quoted_status_id_str="299")
    outer["core"]["user_results"]["result"] = user("101", "reposter")
    built = build_tweet(
        {
            "__typename": "TweetWithVisibilityResults",
            "tweet": outer,
            "limitedActionResults": {"limited_actions": [{"action": "Reply"}]},
        }
    ).to_dict()
    assert built["author"]["screen_name"] == "reposter" and built["id"] == "202"
    assert built["text"] == "long text" and built["url"].endswith("/201") and built["like_count"] == 12
    assert built["quoted_tweet_id"] == "299" and "Reply" in built["limited_actions"]


def test_walk_pin_modules_cursor_and_ads():
    content = {"itemContent": {"tweet_results": {"result": tweet()}}}
    page = walk(
        [
            {"type": "TimelinePinEntry", "entry": {"entryId": "tweet-200", "content": content}},
            {
                "type": "TimelineAddEntries",
                "entries": [
                    {"entryId": "promoted-200", "content": content},
                    {
                        "entryId": "communityModerators-1",
                        "content": {
                            "items": [
                                {"entryId": "user-100", "item": {"itemContent": {"user_results": {"result": user()}}}}
                            ]
                        },
                    },
                    {"entryId": "bottom", "content": {"cursorType": "Bottom", "value": "next"}},
                ],
            },
            {
                "type": "TimelineAddToModule",
                "moduleEntryId": "conversationthread-1",
                "moduleItems": [
                    {
                        "entryId": "more",
                        "item": {
                            "itemContent": {
                                "itemType": "TimelineTimelineCursor",
                                "cursorType": "ShowMoreThreads",
                                "value": "hidden",
                            }
                        },
                    }
                ],
            },
        ]
    )
    assert page.entries[0].pinned and len(page.entries) == 3
    assert page.entries[1].module_id == "communityModerators-1" and page.entries[1].kind == "user"
    assert page.bottom_cursor == "next" and len(page.module_cursors) == 1
