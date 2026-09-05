from types import SimpleNamespace
from twitter_skill._render import _text, number, render
from twitter_skill._schema import schema
from twitter_skill._models import Tweet


def test_text_expands_links_removes_media_and_preserves_linebreaks():
    row = {
        "text": "One  https://t.co/link\nTwo https://t.co/photo",
        "entities": {
            "urls": [{"url": "https://t.co/link", "expanded_url": "https://example.com/article"}],
            "media": [{"url": "https://t.co/photo"}],
        },
    }
    assert _text(row, 100) == "One https://example.com/article ⏎ Two"
    assert number(1200000) == "1.2M"


def test_focal_full_text_quote_hop_and_partial_recovery():
    row = Tweet(id="1", text="A long focal body", quoted_tweet_id="2", limited_actions=["Reply"]).to_dict()
    row["role"] = "focal"
    text = render(
        {
            "results": [row],
            "operation": "TweetDetail",
            "stop_reason": "blocked",
            "error": "rate_limit",
            "fix": "Wait",
            "direct_shown": 0,
            "nested_shown": 0,
            "reported": 9,
            "hidden_branches": 2,
        },
        SimpleNamespace(command="post", sort="top", chars=3),
    )
    assert 'text[full]: "A long focal body"' in text
    assert "https://x.com/i/web/status/2 (open with post)" in text
    assert "[limited: replies]" in text and text.endswith("stopped: rate_limit · Wait")
    assert "0 direct shown of 9 reported" in text and "hidden branches 2" in text


def test_schema_matches_emitted_fields():
    model = schema()["results"][0]["Tweet"]
    assert set(model["properties"]) == set(Tweet().to_dict())
    assert "reposter" in model["properties"]["author"]["description"]


def test_schema_exposes_machine_readable_nullable_and_nested_types():
    doc = schema()
    definitions = doc['schema']['$defs']
    assert definitions['Tweet']['properties']['text']['type'] == 'string'
    assert definitions['Tweet']['properties']['author']['anyOf'] == [{'$ref': '#/$defs/User'}, {'type': 'null'}]
    assert definitions['Tweet']['properties']['media']['items'] == {'$ref': '#/$defs/Media'}
