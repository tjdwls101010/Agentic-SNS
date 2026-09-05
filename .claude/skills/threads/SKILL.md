---
name: threads
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/threads.py" *)
description: Read Threads through the user's logged-in Aside browser: the home feed (for you / following), a post with its parent chain and replies, profile threads, replies, reposts and media, followers and following, post or account search, and the user's liked and saved posts. Use whenever the request is to read or explore Threads — 스레드에서, 쓰레드 피드, 이 스레드 글 답글, 스레드 검색 — including a bare threads.com or threads.net URL. Not for Instagram, Facebook, X/Twitter, Reddit, programming threads, general web pages, or posting, replying, liking, saving and following.
---

# Threads through the user's own browser

The bundled CLI reads through the account already logged in to Aside u0; cookies stay in the browser. It exposes read-only queries and dense text with reusable handles. Below, `$TH` means `python3 "${CLAUDE_SKILL_DIR}/scripts/threads.py"`: expand it to the quoted absolute path on one shell line. Start with `$TH --help`; `schema` describes objects and errors carry their own `fix`.

## Every request is the person's account, and Threads does not say how many are left

Threads supplies no rate-limit headers, so `local budget` is the tool's own accounting, not a server allowance. Meta checkpoints affect the real account. A post page is roughly 0.8 MB and a feed page may contain only a handful of posts: choosing relevant people and posts before opening them saves both requests and bytes. Date windows filter received records locally; a stop other than `window_reached` does not establish that the whole date window was read.

## A post page shows one reply batch

Opening a post reads its full body, parent chain and first reply batch together. The current replay method cannot paginate further direct replies. The header separates received direct replies, displayed descendants, unavailable records and estimated `unfetched` replies. Opening a reply shows what is underneath it; it does not fill missing siblings. Newest-first may overlap top replies, and file collection has the same coverage limit. Top replies are rewarded positions rather than a representative opinion sample: report the sort, received count and estimate when summarizing a discussion.

## Handles and URLs are the next command's arguments

An output `@handle` or `url:` is a reusable target. A profile card supplies context before interpreting someone's activity; profile tabs separate posts, replies, reposts and media. Relationship lists distinguish the server-capped follower sample from paginated following. An embedded quote or repost retains the original post's handle, while a deleted nested post does not erase its outer post. The full `more:` command preserves both the server cursor and received records not yet displayed.

## What has actually bitten

Threads rotated every query ID in an earlier six-week interval; the error's `fix` names the recovery surface. A nonexistent post may silently redirect to a profile, so a successful page load is not proof of post identity. A profile header sometimes arrives as null and needs a separate query. Following counts are absent from profile cards and may also be omitted by the relationship query; unknown is not zero. Account search can return useful data alongside optional-field errors and has no next server page. Notifications change read state when opened, so they are outside this reader.

## Large collections and what the cache holds

File collection is useful when the requested corpus exceeds what is needed in the answer. It commits complete pages and retains unshown tails, so interruption does not require replaying committed records. The output files and `~/.cache/threads-skill` cursors contain other people's activity; keep task collections outside the repository and remove them after use. Recovery capture observes one normal app tab: bootstrap traffic and the app's own view/seen mutations are outside the CLI's read-only guarantee, and observed request counts do not measure all browser traffic.
