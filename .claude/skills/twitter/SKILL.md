---
name: twitter
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: >-
  Read X (Twitter, x.com) through the user's logged-in Aside browser: the home feed, a post with parents and replies, profile posts/replies/media/highlights/articles, followers and following, reposts and quotes, search, trends, lists, communities, and the user's own bookmarks and likes. Use whenever the request is to read or explore X or Twitter — 트위터에서, 엑스에서, 이 트윗 답글, 트위터 검색, 트렌드 — including a bare x.com or twitter.com URL. Not for Threads, Facebook, Reddit, general web pages, news about X the company, notifications or direct messages, posting, replying, liking, reposting, following, or bookmarking.
---

# X through the person's own browser

Aside supplies the logged-in person's session; the bundled CLI reads X with it, read-only, and prints dense text. Let `$TW` mean `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`, written out on one shell line. `$TW --help` and `$TW <command> --help` give each command's arguments, `$TW schema` what the output means, and every error its own `fix`.

## Every request spends the person's account

X can lock an account for automated use, and it counts requests per operation rather than per account: every search product, quotes included, draws on one bucket, so a people search after a post search spends the same reserve. Decide how many people or posts answer the question before collecting. A server page holds far more items than the default display target, so asking to show fewer does not make the first request cheaper, while following a `more:` line serves the rest of an already fetched page with no request.

## Some surfaces break while others keep working

Some reads need a request signature reproduced from X's web client, and an X deployment can break them while every other read keeps working. A nearby surface may still answer, but it answers a different question — replies-only mixes in posts that are not replies, and following is not followers — so when you substitute one, say so in the answer.

## What a row shows is not what it seems

A repost row records the reposter's act: its author, ID and time are the repost's, while its text, link and counts belong to the original post and its writer. Top search and the For you feed are X's ranking and personalization, not a sample of what was posted; ask for latest or following when recency or coverage matters. A thread's reported reply count is X's claim, not what you read: count only the replies shown, and treat hidden branches as unread. X does not list who liked a post, so that question cannot be answered here.

## Joining records and following links

Handles change and IDs do not, so join records from different collections by ID. A follow is not a friendship and a repost is not an endorsement; a follower list holds accounts that may have no other tie to the subject.

## Date windows: server filter vs client filter

Search operators such as since: and until: filter on X's side. A timeline's --since and --until only filter what was fetched, so a run that stopped for any reason other than window_reached has not shown that the window was covered; only profile posts are ordered reliably enough to reach that stop.

## Large collections are personal data

Collect anything too large to read in the conversation with --out. Exports and the cache hold other people's posts and profiles: keep export files outside the repository and delete them when the task is done. A cached session is not proof that the same person is still logged in.
