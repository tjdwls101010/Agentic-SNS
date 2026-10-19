---
name: reddit
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: Read Reddit through the user's logged-in Aside browser: the home feed, subreddit listings, a post and its comment thread, a linked comment, a redditor's history and profile, search across or inside communities, and the user's own subscriptions, saved and upvoted posts. Use whenever the request is to read or explore something on Reddit — 레딧에서, 서브레딧, 이 스레드 댓글 읽어줘, 레디터들은 뭐라고 해, 내 레딧 피드 — including a bare reddit.com or redd.it URL with no mention of Reddit. Not for other social networks, general web pages, news about Reddit the company, or posting, voting, commenting, saving.
---

# Reddit through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` as one plain command: a leading `cd`, a variable holding the path, or a second command joined with `;` or `&&` is not the invocation the permission rule allows. `--help` lists the commands, `<command> --help` says what a read costs and returns, and `schema` says what results and fields mean.
