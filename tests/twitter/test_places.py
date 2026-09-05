from types import SimpleNamespace
from twitter_skill._browse import normalize_page
from twitter_skill._entities import build_place
from twitter_skill._walk import walk


def test_trends_modules_events_promoted_and_other_items():
    rows = [
        {"entryId": "trend-a", "content": {"itemContent": {"itemType": "TimelineTrend", "name": "A"}}},
        {
            "entryId": "trends",
            "content": {
                "items": [
                    {"entryId": "event-b", "item": {"itemContent": {"itemType": "TimelineEventSummary", "title": "B"}}},
                    {
                        "entryId": "trend-ad",
                        "item": {
                            "itemContent": {
                                "itemType": "TimelineTrend",
                                "name": "Advertisement",
                                "promoted_metadata": {"advertiser": "example"},
                            }
                        },
                    },
                ]
            },
        },
        {"entryId": "unknown", "content": {"itemContent": {"itemType": "NewThing"}}},
    ]
    items, cursor, meta = normalize_page(
        [{"type": "TimelineAddEntries", "entries": rows}], "GenericTimelineById", SimpleNamespace(command="trends")
    )
    assert [r["kind"] for r in items] == ["trend", "event"] and meta["promoted"] == 1 and meta["other_items"] == 1
    assert meta["not_paginable"] and cursor is None


def test_community_roles_and_cards():
    root = [
        {
            "type": "TimelineAddEntries",
            "entries": [
                {
                    "entryId": "communityMembers-1",
                    "content": {
                        "items": [
                            {
                                "entryId": "user-1",
                                "item": {
                                    "itemContent": {
                                        "user_results": {"result": {"rest_id": "1", "core": {"screen_name": "example"}}}
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        }
    ]
    rows, _, _ = normalize_page(root, "CommunityAboutTimeline", SimpleNamespace(command="community"))
    assert rows[0]["role"] == "member"
    card = build_place(
        {"rest_id": "1", "name": "Example", "rules": [{"name": "Kindness"}], "is_nsfw": True}, "community"
    ).to_dict()
    assert (
        card["rules"] == [{"name": "Kindness"}] and card["url"] == "https://x.com/i/communities/1" and card["is_nsfw"]
    )


def test_top_termination_does_not_end_bottom_pagination():
    page = walk([{"type": "TimelineTerminateTimeline", "direction": "Top"}])
    assert not page.terminated


def test_community_landing_url_is_a_string_next_hop():
    node = {
        "entryId": "tweet-1",
        "content": {
            "itemContent": {
                "tweet_results": {"result": {"rest_id": "1", "legacy": {"full_text": "Synthetic"}}},
                "socialContext": {
                    "landingUrl": {"url": "https://twitter.com/i/communities/123", "urlType": "ExternalUrl"}
                },
            }
        },
    }
    rows, _, _ = normalize_page(
        [{"type": "TimelineAddEntries", "entries": [node]}],
        "CommunitiesExploreTimeline",
        SimpleNamespace(command="communities"),
    )
    assert rows[0]["community_url"] == "https://twitter.com/i/communities/123"
