---
name: reddit
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/reddit.py" *)
description: Read Reddit through the user's logged-in Aside browser: the home feed, subreddit listings, a post and its comment thread, a linked comment, a redditor's history and profile, search across or inside communities, and the user's own subscriptions, saved and upvoted posts. Use whenever the request is to read or explore something on Reddit — 레딧에서, 서브레딧, 이 스레드 댓글 읽어줘, 레디터들은 뭐라고 해, 내 레딧 피드 — including a bare reddit.com or redd.it URL with no mention of Reddit. Not for other social networks, general web pages, news about Reddit the company, or posting, voting, commenting, saving.
---

# Reddit through the user's own browser

The bundled CLI reads Reddit through the account already logged in to Aside u0. Cookies stay in the browser; the interface exposes read-only queries and dense text with navigation handles. Below, `$RD` means `python3 "${CLAUDE_SKILL_DIR}/scripts/reddit.py"`: expand it to the literal absolute path, quoted and on one shell line. Start with `$RD --help`; `schema` describes fields, and errors carry their own `fix`.

## The budget is shared and the tool counts it

Reddit's observed allowance is 100 requests per ten minutes, shared across CLI calls even while logged in. Each response reports the remaining budget and actual request count. Opening a new target spends requests; continuing a cached thread often spends none. Choosing the communities and people relevant to the question before opening them makes that budget go further. At zero the tool stops and reports expiry; waiting for a new window is the person's decision.

## Where a person starts

The home feed is personalized; subscriptions are the person's own communities. `popular` and `all` cover a broader Reddit audience. One subreddit is one community, so its response should be attributed to that community rather than to Reddit as a whole.

## A thread is a tree read in batches

Opening a post retrieves hundreds of comments in one request and displays a batch. The `more:` handle continues the same state, keeping hidden replies and folded branches separate. Cached and newly expanded comments have different observation times, reported in the header; the ordering is a snapshot within each batch, not a global ordering across batches. Expansion may bring both requested comments and their descendants.

Best and top surface rewarded positions; new and controversial answer different questions. New does not return replies as a nested tree. Name the ordering when reporting a discussion. Reddit's comment total includes deleted comments and can exceed the parsed count. Client date windows do not extend Reddit's finite listings: reaching the window and exhausting the server listing are different outcomes.

## r/ and u/ are the next command's arguments

Community handles, user handles and comment permalinks in the output are reusable targets. Community information provides rules, scale and access labels; user information gives profile context before interpreting activity. A display number such as `[c1]` belongs only to its batch, so the comment URL is the durable branch handle. A pseudonymous public history describes that account's observed activity; it does not establish the person's offline identity.

## What has actually bitten

Reddit host variants can route to bot challenges or missing pages, so the tool normalizes them to www. Missing or closed targets are different from an empty result and do not improve by repeating the same read. NSFW is labeled, not silently filtered. Search sometimes returns an empty page transiently; even two empty searches do not prove absence. Shared links need redirect resolution, and each actual hop consumes budget.

## Large collections and what the cache holds

File collection is useful when the requested corpus is larger than the text needed for the answer. It commits progress so interruption can be resumed without replaying completed records. Output files and the thread cache under `~/.cache/reddit-skill` contain other people's activity; aggregating pseudonymous history can enable identification. Keep collections outside the repository and remove task data after use. The tool expires cached threads and cursors after 24 hours and bounds their combined size.
