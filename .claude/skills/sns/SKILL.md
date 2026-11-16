---
name: sns
description: >-
  Read social networks through the user's logged-in Aside browser: X (Twitter), Threads, Reddit, Facebook and Naver Blog. Feeds, a post with its replies or comment tree, quotes and reposts, profiles, followers and following, search, subreddits and wikis, Facebook groups and pages, X lists, communities and trends, Naver blogs, categories and neighbors, the pictures in a post, and the user's own saved, liked and notification items. Use whenever the request is to read or explore one of these platforms or to follow a lead across them — 트위터에서, 엑스에서, 스레드에서, 레딧에서, 서브레딧, 페이스북에서, 페북 그룹, 네이버 블로그에서, 이웃새글, SNS 반응, SNS 후기 — including a bare x.com, twitter.com, threads.com, threads.net, reddit.com, redd.it, facebook.com, blog.naver.com, m.blog.naver.com or naver.me link with no platform named. Pick it by where the content lives, not by the topic. Not for Instagram, YouTube, Naver Cafe, News or 지식iN, Tistory, other websites, news about these companies, direct messages, or posting, replying, reacting, following and saving.
allowed-tools:
  - Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
  - Read(~/.local/state/agentic-sns/**)
---

# Social networks through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <platform> <command> …` as its own call with the literal script path: the permission rule matches the whole command line, so a `cd`, a variable, a loop, a pipe or a second command around it stops for approval, and several reads are several calls. `--help` maps every platform's commands, and `<platform> <command> --help` says what a read costs and returns.

Every request goes out as the user's own logged-in account. A checkpoint, challenge or lock a platform puts on it lands on that account, and only the user can clear it, in their own browser. A read that grows with what it covers (every reply, months of posts, an `--out` collection) spends that account's requests; each command's `--help` says how many before the call.
