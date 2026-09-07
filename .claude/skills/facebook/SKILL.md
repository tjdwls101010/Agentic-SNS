---
name: facebook
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/facebook.py" *)
description: >-
  Read content on facebook.com through the user's logged-in Aside browser: Facebook post URLs, home feed, profiles, About fields, comments, search, and groups. Use whenever the request is to read or explore something on Facebook, including 페이스북에서, 내 페이스북 피드, 이 페북 글 댓글, 페북에서 누가 올렸어. Facebook URLs belong here even when the user only says “read this” or “summarize these comments.” Not for other social networks, general web pages, news about the Facebook company, or writing posts, comments, or reactions.
---

# Facebook through the user's own browser

The browser supplies the already logged-in account; the bundled CLI supplies read-only Facebook queries and dense text. Start with `python3 "<base directory>/scripts/facebook.py" --help`. Below, `$FB` means that literal command with the absolute skill directory substituted. Write it as one line, with the path quoted; the directory may contain spaces. Each command's help describes its options, `schema` describes the returned objects, and errors carry their own recovery instruction in `fix`.

## Every request is the person's real account

A typical timeline page contains three posts, so reading 100 posts costs about 34 page requests plus setup. Decide how many people or groups to follow before branching: following every commenter multiplies those requests and a checkpoint affects the real account. A post gives the full received text and its first comment batch together; request more comments only when the question needs them.

## Ranked order and recent order

Ranked results and chronological results answer different questions. Pair a date window with recent order.

## Reaching a limit is a sample, not proof

Profile windows are filtered by the server; feed and group windows are filtered from the pages actually visited, so they cannot establish that every post in that period was found. Read `stop_reason` and any completeness fields before describing coverage.

## Handles and URLs are the next command's arguments

The output's `url` and `author` handles are the next command's arguments. An unfamiliar author is a reason to read their About fields before choosing whose timeline to follow. Search can return several people with the same name; inspect their identities before selecting one. A `more:` line is a complete continuation command: copy it rather than reconstructing its query context.

## What has actually bitten

Sponsored posts can have no date, an `unavailable` handle is a dead end, and `?` means an unknown count. Text previews show how many characters were displayed versus received. `truncated` means Facebook itself shortened the text; open the post before quoting it. If the opened post is still truncated, keep that qualification rather than repeatedly fetching it. Some secondary sections or replies may be incomplete; report that limitation instead of presenting them as empty.

## Large collections and what the cache holds

Use `--out` when the results are too large to read in the conversation. It commits complete pages and resumes the same query after an interruption; the terminal reports a summary. Use ordinary text output for exploration, and `--json` only when the full structured objects are useful. `~/.cache/facebook-skill` holds continuation cursors, the query registry, and the account protection state. Both that cache and an `--out` file contain other people's personal information, so prefer a collection path outside the repository and remove it when the task is finished.
