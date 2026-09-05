from twitter_skill._thread import thread_records, completeness
from twitter_skill._walk import walk


def node(identity, parent=None):
    return {
        "entryId": "tweet-" + identity,
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "rest_id": identity,
                        "legacy": {"full_text": "example", "in_reply_to_status_id_str": parent, "reply_count": 9},
                    }
                }
            }
        },
    }


def test_parent_focal_nested_and_completeness():
    parent, focal, direct, nested = node("1"), node("2", "1"), node("3", "2"), node("4", "3")
    page = walk(
        [
            {
                "type": "TimelineAddEntries",
                "entries": [
                    parent,
                    focal,
                    {
                        "entryId": "conversationthread-3",
                        "content": {
                            "items": [
                                {"entryId": x["entryId"], "item": {"itemContent": x["content"]["itemContent"]}}
                                for x in [direct, nested]
                            ]
                        },
                    },
                ],
            }
        ]
    )
    rows, meta = thread_records(page, "2")
    assert [r["role"] for r in rows] == ["parent", "focal", "reply", "reply"]
    assert rows[-1]["depth"] == 1 and rows[-1]["module"] == "conversationthread-3"
    assert completeness(rows, "2", meta) == dict(reported=9, direct_shown=1, nested_shown=1, hidden_branches=0)


def test_related_posts_are_not_replies():
    page = walk(
        [
            {
                "type": "TimelineAddEntries",
                "entries": [
                    node("2"),
                    {
                        "entryId": "tweetdetailrelatedtweets-9",
                        "content": {
                            "items": [
                                {"entryId": "tweet-9", "item": {"itemContent": node("9")["content"]["itemContent"]}}
                            ]
                        },
                    },
                ],
            }
        ]
    )
    rows, meta = thread_records(page, "2")
    assert [r["id"] for r in rows] == ["2"]
    assert completeness(rows, "2", meta)["direct_shown"] == 0
