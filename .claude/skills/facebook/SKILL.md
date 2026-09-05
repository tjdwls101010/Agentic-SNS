---
name: facebook
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/facebook.py" *)
description: >-
  Read content on facebook.com through the user's logged-in Aside browser: Facebook post URLs, home feed, profiles, About fields, comments, search, and groups. Use whenever the request is to read or explore something on Facebook, including 페이스북에서, 내 페이스북 피드, 이 페북 글 댓글, 페북에서 누가 올렸어. Facebook URLs belong here even when the user only says “read this” or “summarize these comments.” Not for other social networks, general web pages, news about the Facebook company, or writing posts, comments, or reactions.
---

# Facebook

The browser supplies the already logged-in account; the bundled CLI supplies read-only Facebook queries and dense text. Start with `python3 "<base directory>/scripts/facebook.py" --help`. Below, `$FB` means that literal command with the absolute skill directory substituted. Write it as one line, with the path quoted; the directory may contain spaces. Each command's help describes its options, `schema` describes the returned objects, and errors carry their own recovery instruction in `fix`.

Every request uses the person's real account. A typical timeline page contains three posts, so reading 100 posts costs about 34 page requests plus setup. Decide how many people or groups to follow before branching: following every commenter multiplies those requests and a checkpoint affects the real account. The CLI enforces pacing, a request budget and a persistent account block; a block needs the person to inspect Facebook before clearing it.

Ranked results and chronological results answer different questions. Pair a date window with recent order. Profile windows are filtered by the server; feed and group windows are filtered from the pages actually visited, so they cannot establish that every post in that period was found. Read `stop_reason` and any completeness fields before describing coverage. Reaching a limit is a sample, not proof of completeness.

The output's `url` and `author` handles are the next command's arguments. A post gives the full received text and its first comment batch together; request more comments only when the question needs them. An unfamiliar author is a reason to read their About fields before choosing whose timeline to follow. Search can return several people with the same name; inspect their identities before selecting one. A `more:` line is a complete continuation command: copy it rather than reconstructing its query context.

Sponsored posts can have no date, an `unavailable` handle is a dead end, and `?` means an unknown count. Text previews show how many characters were displayed versus received. `truncated` means Facebook itself shortened the text; open the post before quoting it. If the opened post is still truncated, keep that qualification rather than repeatedly fetching it. Some secondary sections or replies may be incomplete; report that limitation instead of presenting them as empty.

Use `--out` when the results are too large to read in the conversation. It commits complete pages and resumes the same query after an interruption; the terminal reports a summary. The file contains other people's personal information, so prefer a path outside the repository and remove the collection when the task is finished. Use ordinary text output for exploration, and `--json` only when the full structured objects are useful.
