---
name: twitter
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/twitter.py" *)
description: >-
  Read X (Twitter, x.com) through the user's logged-in Aside browser: the home feed, a post with parents and replies, profile posts/replies/media/highlights/articles, followers and following, reposts and quotes, search, trends, lists, communities, and the user's own bookmarks and likes. Use whenever the request is to read or explore X or Twitter — 트위터에서, 엑스에서, 이 트윗 답글, 트위터 검색, 트렌드 — including a bare x.com or twitter.com URL. Not for Threads, Facebook, Reddit, general web pages, news about X the company, posting, replying, liking, reposting, following, or bookmarking.
---

# X through the user's own browser

Aside supplies the logged-in person's session; the bundled CLI supplies read-only queries and dense text. Let `$TW` mean the absolute path `${CLAUDE_SKILL_DIR}/scripts/twitter.py`, invoked as `python3 "$TW"`. Start with its `--help`; command help, `schema`, and an error's `fix` carry the interface details. The script is self-contained and can run from any directory.

## Every request is the person's account, and X counts by operation

The budget line reports the operation's server bucket, not an account-wide allowance. Every search product shares one bucket; searching for posts and then accounts spends the same reserve. Profile posts and followers also have smaller buckets than home and following. X can lock accounts for automation, so decide how many people or posts answer the question before collecting. A server page contains many more items than the default display target: asking for fewer displayed items does not make that first request cheaper, while a cached continuation can require no request at all.

## Three surfaces run on a reverse-engineered signature

Search, followers, and the profile replies tab depend on a signature reproduced from X's web client. Every request needs a fresh signature, and a client deployment can break these surfaces while other reads continue working. Query IDs also rotate. Error recovery distinguishes a signature problem, a rotated operation, and a changed variable contract; their fixes are different. The explicit replies-only alternative is a different operation and still contains some non-reply posts.

## A repost's author is the reposter, and other things the numbers hide

The person at the front of a repost row is the reposter; the person after “repost of” wrote the original. The row ID and timestamp describe the repost action, while its body, URL, and engagement counts describe the original. Search may supply only an ID for an embedded quote; the next-hop URL opens the missing original. X no longer returns a useful list of people who liked a post, so that surface is absent.

Top is X's ranking, not a chronological sample, and the home feed is personalized rather than a sample of all X. A blue check denotes a paid subscription; government and business badges carry different meanings. Reply limitations are labeled. Reply totals distinguish direct replies reported by X, direct replies shown, nested replies shown, and hidden branches; related-post recommendations are not replies. These are observations, not a completeness guarantee.

## @handles and URLs are the next command's arguments

Printed handles and URLs are directly usable as targets. Handles can change but IDs remain stable, so join records by ID. X's usable profile lookup needs a handle rather than a numeric user ID. Following is not friendship, and reposting is not necessarily agreement; a relationship list contains people who may have no other connection to the subject.

## What has actually bitten

An unavailable post can arrive as an empty focal node in an otherwise successful response. The second page of replies usually has no focal post. Advertisements are removed, so the displayed feed differs from the complete server response. “More replies” branches are counted but not followed. Article tabs expose their listing; article rich-text bodies are not expanded.

Search date operators are server filters. Timeline date windows are client filters, and a stop other than `window_reached` does not establish that the requested time window was fully covered. Only the profile posts surface has enough evidence of chronological ordering to make that early-stop claim. Notifications and DMs are outside this skill.

## Large collections and what the cache holds

Use local exports when the collection is too large to read in the conversation. Exports commit whole eligible pages within the requested date window, so stored and shown counts can differ. Interrupted exports resume from the last complete page; continuation handles consume their cached unseen tail first. Both are bound to query context and the cached viewer, and a detected account change invalidates continuations.

The cache holds the CSRF token, viewer identity, and potentially other people's posts and profiles; the browser retains the actual login credential. Exports and continuation files are personal data: keep them outside the repository and remove them after the task. A long-lived cached session is not continuous proof that the person has stayed logged in as the same account; personal surfaces periodically recheck the viewer cookie.
