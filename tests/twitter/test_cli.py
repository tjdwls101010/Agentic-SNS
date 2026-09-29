import re
import subprocess
import sys
from pathlib import Path
import pytest

from .helpers import CLI, invoke


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


def test_more_command_starts_with_the_allowed_tools_invocation(fake_env):
    skill = CLI.parents[1]
    allowed = re.search(r'(?m)^allowed-tools: Bash\((.+) \*\)$', (skill / 'SKILL.md').read_text())[1]
    code, doc = invoke(["user", "@example", "--limit", "2"], fake_env)
    assert doc["next"].startswith(allowed.replace("${CLAUDE_SKILL_DIR}", str(skill)) + " ")


GENERIC_FIXES = {'Run doctor, then follow its recovery advice.', 'Read the command --help for valid options.'}


@pytest.mark.parametrize("args,names", [
    (["home", "--since", "2026-01-01"], ["--feed following", "--since"]),
    (["user", "@example", "--tab", "highlights", "--since", "2026-01-01"], ["--tab", "--since"]),
    (["list", "1", "--tab", "members", "--until", "2026-01-01"], ["--tab posts", "--until"]),
    (["list", "1", "--tab", "about", "--after", "1"], ["--after"]),
    (["community", "1", "--tab", "media", "--sort", "recent"], ["--sort", "--tab posts"]),
    (["post", "1", "2", "--sort", "top"], ["--sort"]),
    (["post", "1", "2", "--after", "1"], ["--after"]),
    (["post", "1", "2", "--limit", "1"], ["--limit"]),
    (["search", "x", "--type", "users", "--sort", "latest"], ["--sort"]),
    (["search", "x", "--in", "communities", "--type", "users"], ["--type", "--in"]),
    (["search", "x", "--in", "communities", "--sort", "top"], ["--sort", "--in"]),
    (["search", "x", "--limit", "0"], ["--limit"]),
    (["home", "--chars", "0"], ["--chars"]),
    (["user", "@example", "--until", "nonsense"], ["--until"]),
    (["user", "@example", "--since", "2026-02-01", "--until", "2026-01-01"], ["--since", "--until"]),
    (["home", "--after", "0"], ["--after"]),
    (["user", "@example", "--out", "{tmp}/x.ndjson", "--after", "1"], ["--out", "--after"]),
    (["home", "--tab", "posts"], ["--tab"]),
    (["user", "@example", "--tab", "bogus"], ["--tab"]),
    (["home", "--limit", "many"], ["--limit"]),
    (["graph", "@example"], ["relation"]),
    (["search"], ["target"]),
    (["user", "123"], ["@handle"]),
    (["post", "https://x.com/example"], ["post URL"]),
    (["list", "abc"], ["list"]),
])
def test_every_argument_error_names_what_to_change(args, names, fake_env, tmp_path):
    code, doc = invoke([a.replace("{tmp}", str(tmp_path)) for a in args], fake_env)
    assert (code, doc["error"]) == (2, "arguments"), doc
    assert doc["fix"] not in GENERIC_FIXES and all(name in doc["fix"] for name in names), doc["fix"]
    assert not Path(fake_env["TWITTER_FAKE_LOG"]).exists()


def test_media_search_refuses_a_sort_it_would_ignore(fake_env):
    code, doc = invoke(["search", "x", "--type", "media", "--sort", "top"], fake_env)
    assert (code, doc["error"]) == (2, "arguments") and "Remove --sort" in doc["fix"]
    assert not Path(fake_env["TWITTER_FAKE_LOG"]).exists()


def help_text(*command):
    done = subprocess.run([sys.executable, str(CLI), *command, "--help"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def option(output, flag):
    """The help of one option or positional: its line, and the next when a long invocation pushed the help there."""
    lines = output.splitlines()
    index = next(i for i, line in enumerate(lines) if re.match(r"\s+" + re.escape(flag) + r"\b", line))
    following = lines[index + 1] if index + 1 < len(lines) else ""
    return lines[index] + (" " + following.strip() if re.match(r"\s{20,}\S", following) else "")


COMMANDS = ["home", "user", "about", "post", "quotes", "reposts", "search", "graph", "me", "list", "trends",
            "community", "communities", "doctor", "refresh", "schema"]


@pytest.mark.parametrize("command", ["", *COMMANDS])
def test_help_never_folds_a_sentence(command):
    output = help_text(*([command] if command else []))
    folded = [line for line in output.splitlines() if re.match(r"\s{20,}[a-z]", line)]
    assert folded == [] and all(len(line) < 400 or " " in line for line in output.splitlines())


@pytest.mark.parametrize("command", ["home", "user", "about", "quotes", "reposts", "search", "graph", "me", "list",
                                     "trends", "community", "communities"])
def test_only_post_help_talks_about_batches_and_the_focal_post(command):
    output = help_text(command).lower()
    assert "batch" not in output and "focal" not in output


def test_help_states_each_command_s_own_units_and_limits():
    assert "--feed following" in option(help_text("home"), "--since")
    user = help_text("user")
    assert "numeric" in option(user, "target") and "not accepted" in option(user, "target")
    assert all(tab in option(user, "--since") for tab in ("posts", "replies", "replies-only", "media"))
    assert "not expanded" in option(user, "--tab")
    assert "bio" in option(help_text("about"), "--chars")
    post = help_text("post")
    assert all(flag in option(post, "target") for flag in ("--limit", "--sort", "--after"))
    assert "latest" not in option(post, "--sort") and "account" not in option(post, "--sort").lower()
    for command in ("reposts", "graph"):
        assert "accounts" in option(help_text(command), "--limit").lower() and "bio" in option(help_text(command), "--chars")
    search = help_text("search")
    assert "--type users" in option(search, "--sort") and "media" in option(search, "--sort")
    listing = help_text("list")
    assert "--tab about" in option(listing, "--after") and "--tab posts" in option(listing, "--since")
    trends = help_text("trends")
    assert "--after" in trends and "description" in option(trends, "--chars")
    community = help_text("community")
    assert "--tab posts" in option(community, "--sort") and "--tab about" in option(community, "--after")
    root = help_text()
    assert all(f"{code} " in root for code in (0, 2, 3, 4, 5, 6, 7, 8, 9))
