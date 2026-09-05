"""Authorized read-only CLI scenarios under the persistent forty-API guard."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
import pytest

pytestmark = pytest.mark.live
CLI = Path(__file__).resolve().parents[3] / ".claude/skills/twitter/scripts/twitter.py"
GUARD = Path(__file__).with_name("guard_aside.py")


def run(args):
    env = dict(os.environ, TWITTER_ASIDE_BIN=str(GUARD))
    p = subprocess.run(
        [sys.executable, str(CLI), *args, "--json"], capture_output=True, text=True, env=env, timeout=150
    )
    body = json.loads(p.stdout)
    print(
        json.dumps(
            dict(
                command=args,
                exit=p.returncode,
                shown=len(body.get("results", [])),
                stop=body.get("stop_reason"),
                error=body.get("error"),
                requests=body.get("budget", {}).get("requests"),
            ),
            ensure_ascii=False,
        ),
        flush=True,
    )
    assert p.returncode in (0, 7), body
    return body


def test_live_feeds_profiles_and_continuations():
    home = run(["home", "--limit", "3"])
    assert home["results"] and all(r["kind"] == "tweet" for r in home["results"])
    following = run(["home", "--feed", "following", "--limit", "3"])
    continuation = shlex.split(following["next"])[2:]
    tail = run(continuation)
    assert tail["budget"]["requests"] == 0
    assert {r["id"] for r in following["results"]}.isdisjoint(r["id"] for r in tail["results"])
    # Consume a full cached tail plus some of the next server page in one invocation.
    larger = shlex.split(tail["next"])[2:]
    larger[larger.index("--limit") + 1] = "65"
    page2 = run(larger)
    assert page2["budget"]["requests"] >= 1
    assert len({r["id"] for r in page2["results"]}) == len(page2["results"])
    profile = run(["user", "@X", "--limit", "3"])
    assert profile["card"]["followers_count"] > 0
    run(["user", "@X", "--tab", "media", "--limit", "3"])
    cards = run(["about", "@X", "@nasa"])
    assert len(cards["results"]) == 2


def test_live_threads_and_relationships():
    focal = os.environ.get("TWITTER_LIVE_POST", "2089465307844825263")
    post = run(["post", focal, "--limit", "5"])
    assert any(r["id"] == focal and r["role"] == "focal" for r in post["results"])
    replies = [r for r in post["results"] if r.get("role") == "reply"]
    if replies:
        reply = run(["post", replies[0]["id"], "--limit", "3"])
        assert reply["results"][0]["role"] == "parent"
    run(["post", focal, "--sort", "recent", "--limit", "3"])
    run(["reposts", focal, "--limit", "3"])
    quotes = run(["quotes", focal, "--limit", "3"])
    assert all(r["quoted_tweet_id"] == focal for r in quotes["results"])
    run(["graph", "@X", "following", "--limit", "3"])


def test_live_search_collections_and_places():
    run(["search", "python", "--limit", "3"])
    people = run(["search", "python", "--type", "users", "--limit", "3"])
    assert all(r["kind"] == "user" for r in people["results"])
    run(["search", "python", "--in", "communities", "--limit", "3"])
    run(["me", "likes", "--limit", "3"])
    bookmarks = run(["me", "bookmarks", "--limit", "3"])
    if not bookmarks["results"]:
        print(
            "LIMITATION: bookmark item shape remains unverified; the account returned a valid empty timeline.",
            flush=True,
        )
    run(["list", os.environ.get("TWITTER_LIVE_LIST", "1418075522672771076"), "--limit", "3"])
    trends = run(["trends", "--limit", "5"])
    assert "other_items" in trends
    communities = run(["communities", "--limit", "3"])
    links = [r.get("community_url") for r in communities["results"] if r.get("community_url")]
    if links:
        community = run(["community", links[0], "--limit", "3"])
        assert community["card"]["member_count"] >= 0
    else:
        pytest.fail("Community landing URL was not returned; community read remains unverified.")
