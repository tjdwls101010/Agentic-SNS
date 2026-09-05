import json
import os
import time
import subprocess
import sys
from pathlib import Path
import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/twitter/scripts/twitter.py"


@pytest.mark.parametrize(
    "command",
    [
        "home",
        "user",
        "about",
        "post",
        "quotes",
        "reposts",
        "search",
        "graph",
        "me",
        "list",
        "trends",
        "community",
        "communities",
        "doctor",
        "refresh",
        "schema",
    ],
)
def test_help(command):
    p = subprocess.run([sys.executable, str(CLI), command, "--help"], capture_output=True, text=True)
    assert p.returncode == 0 and "usage:" in p.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["home", "--since", "2026-01-01"],
        ["user", "123"],
        ["about", "@example", "--after", "1"],
        ["search", "x", "--in", "communities", "--type", "users"],
        ["list", "1", "--tab", "about", "--after", "1"],
        ["post", "1", "2", "--after", "1"],
        ["community", "1", "--tab", "media", "--sort", "recent"],
        ["search", "x", "--limit", "0"],
        ["user", "@example", "--until", "nonsense"],
    ],
)
def test_invalid_before_network(args):
    p = subprocess.run([sys.executable, str(CLI), *args, "--json"], capture_output=True, text=True)
    assert p.returncode == 2


@pytest.fixture
def fake_env(tmp_path):
    home = tmp_path / "cache"
    home.mkdir()
    (home / "session.json").write_text(json.dumps({"ct0": "synthetic", "viewer_id": "100", "read_at": time.time()}))
    (home / "txid.json").write_text(
        json.dumps({"key_bytes": [1] * 48, "animation_key": "synthetic", "fetched_at": time.time()})
    )
    return {
        **os.environ,
        "TWITTER_HOME": str(home),
        "TWITTER_ASIDE_BIN": str(Path(__file__).parent / "fake_aside/aside"),
        "TWITTER_FAKE_LOG": str(tmp_path / "calls.ndjson"),
    }


def invoke(args, env):
    p = subprocess.run([sys.executable, str(CLI), *args, "--json"], capture_output=True, text=True, env=env)
    assert p.stdout, p.stderr
    return p.returncode, json.loads(p.stdout)


@pytest.mark.parametrize(
    "args,op,kind",
    [
        (["home"], "HomeTimeline", "tweet"),
        (["home", "--feed", "following"], "HomeLatestTimeline", "tweet"),
        *[
            (["user", "@example", "--tab", tab], op, "tweet")
            for tab, op in [
                ("posts", "UserTweets"),
                ("replies", "UserTweetsAndReplies"),
                ("replies-only", "UserRepliesTimeline"),
                ("media", "UserMedia"),
                ("highlights", "UserHighlightsTweets"),
                ("articles", "UserArticlesTweets"),
            ]
        ],
        (["about", "@example", "@second"], "UsersByScreenNames", "user"),
        (["post", "200"], "TweetDetail", "tweet"),
        (["post", "200", "201"], "TweetResultsByRestIds", "tweet"),
        (["quotes", "200"], "SearchTimeline", "tweet"),
        (["reposts", "200"], "Retweeters", "user"),
        (["search", "example"], "SearchTimeline", "tweet"),
        (["search", "example", "--type", "users"], "SearchTimeline", "user"),
        (["search", "example", "--type", "media"], "SearchTimeline", "tweet"),
        (["search", "example", "--in", "communities"], "GlobalCommunitiesLatestPostSearchTimeline", "tweet"),
        *[
            (["graph", "@example", relation], op, "user")
            for relation, op in [
                ("following", "Following"),
                ("followers", "Followers"),
                ("verified", "BlueVerifiedFollowers"),
                ("known", "FollowersYouKnow"),
            ]
        ],
        (["me", "likes"], "Likes", "tweet"),
        (["me", "bookmarks"], "Bookmarks", "tweet"),
        (["list", "1"], "ListLatestTweetsTimeline", "tweet"),
        (["list", "1", "--tab", "members"], "ListMembers", "user"),
        (["list", "1", "--tab", "about"], "ListByRestId", "list"),
        (["trends"], "ExplorePage", "trend"),
        (["trends", "--tab", "foryou"], "ExplorePage", "trend"),
        (["community", "1"], "CommunityTweetsTimeline", "tweet"),
        (["community", "1", "--tab", "media"], "CommunityMediaTimeline", "tweet"),
        (["community", "1", "--tab", "about"], "CommunityAboutTimeline", "user"),
        (["communities"], "CommunitiesExploreTimeline", "tweet"),
    ],
)
def test_all_surfaces(args, op, kind, fake_env):
    code, doc = invoke(
        args if args[0] == "about" or args[0] == "post" and len(args) > 2 else [*args, "--limit", "2"], fake_env
    )
    assert code == 0, doc
    assert doc["operation"] == op and doc["results"][0]["kind"] == kind
    if args[0] == "user":
        assert doc["card"]["followers_count"] == 1200


def test_tail_zero_requests_and_out_full_pages(fake_env, tmp_path):
    code, first = invoke(["user", "@example", "--limit", "2"], fake_env)
    assert code == 0
    log = Path(fake_env["TWITTER_FAKE_LOG"])
    before = log.read_text()
    code, second = invoke(["user", "@example", "--limit", "2", "--after", str(first["next_handle"])], fake_env)
    assert code == 0 and log.read_text() == before
    assert {r["id"] for r in first["results"]}.isdisjoint(r["id"] for r in second["results"])
    out = tmp_path / "posts.ndjson"
    code, saved = invoke(["user", "@example", "--limit", "2", "--out", str(out)], fake_env)
    assert code == 0 and saved["shown"] == 2 and saved["stored"] == 5
    before = log.read_text().count("UserByScreenName")
    code, resumed = invoke(["user", "@example", "--limit", "2", "--out", str(out)], fake_env)
    assert code == 0 and resumed["stored"] == 7
    assert log.read_text().count("UserByScreenName") == before


def test_cli_partial_error_and_honest_empty(fake_env):
    code, doc = invoke(["home", "--limit", "10"], dict(fake_env, TWITTER_FAKE_SCENARIO="429"))
    assert code == 8 and len(doc["results"]) == 5 and doc["stop_reason"] == "blocked" and doc["next"] and doc["fix"]
    Path(fake_env["TWITTER_HOME"], "budget.json").unlink()
    code, doc = invoke(["home"], dict(fake_env, TWITTER_FAKE_SCENARIO="empty"))
    assert code == 7 and doc["results"] == []


@pytest.mark.parametrize(
    "args",
    [
        ["about", "@example", "@second", "--limit", "1"],
        ["post", "200", "201", "--limit", "1"],
        ["home", "--after", "0"],
    ],
)
def test_clipping_and_zero_after_rejected_before_network(args, fake_env):
    code, doc = invoke(args, fake_env)
    assert code == 2 and doc["error"] == "arguments"
    assert not Path(fake_env["TWITTER_FAKE_LOG"]).exists()


def test_batch_posts_default_never_clips_twenty(fake_env):
    ids = [str(200 + i) for i in range(25)]
    code, doc = invoke(["post", *ids], fake_env)
    assert code == 0 and [r["id"] for r in doc["results"]] == ids
    assert doc["next"] is None


def test_account_search_does_not_claim_a_chronological_sort(fake_env):
    p = subprocess.run([sys.executable, str(CLI), 'search', 'python', '--type', 'users', '--limit', '1'],
                       capture_output=True, text=True, env=fake_env)
    assert p.returncode == 0
    assert 'sort=latest' not in p.stdout
    assert 'rank=people' in p.stdout
    assert 'requests 1' in p.stdout
    p = subprocess.run([sys.executable, str(CLI), 'search', 'python', '--type', 'users', '--sort', 'latest', '--json'],
                       capture_output=True, text=True, env=fake_env)
    assert p.returncode == 2


def test_profile_card_respects_requested_text_length(fake_env):
    p = subprocess.run([sys.executable, str(CLI), 'about', '@example', '--chars', '3'],
                       capture_output=True, text=True, env=fake_env)
    assert p.returncode == 0
    assert 'bio: "Syn…"' in p.stdout
    assert 'Synthetic profile' not in p.stdout
