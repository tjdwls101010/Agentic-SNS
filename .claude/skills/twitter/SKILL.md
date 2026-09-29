---
name: twitter
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: >-
  Read X (Twitter, x.com) through the user's logged-in Aside browser: the home feed, a post with parents and replies, profile posts/replies/media/highlights/articles, followers and following, reposts and quotes, search, trends, lists, communities, and the user's own bookmarks and likes. Use whenever the request is to read or explore X or Twitter — 트위터에서, 엑스에서, 이 트윗 답글, 트위터 검색, 트렌드 — including a bare x.com or twitter.com URL. Not for Threads, Facebook, Reddit, general web pages, news about X the company, notifications or direct messages, posting, replying, liking, reposting, following, or bookmarking.
---

# X through the person's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` to read X through the person's logged-in Aside browser, read-only. `--help` lists the commands, `<command> --help` gives a command's arguments, `schema` lists the output topics and `schema <topic>` explains one; every error carries a recovery `fix`.

## Every request spends the person's account

Automated reads can get the person's logged-in account locked, so choose the smallest collection that answers the question and stop once it is answered; the CLI's request limits are safeguards, not a budget to spend.

## Follows and reposts are actions, not relationships

A follow or a repost records what an account did, not friendship or agreement; describe the action itself, and if you answer a question about friends with mutual follows, call them a proxy.

## Large collections are personal data

Use `--out` for collections too large to read in the conversation. Exports and cached records hold other people's posts and profiles: keep exports outside the repository, and tell the person to keep them private and delete them once the analysis they are for is done.

When the browser may have switched accounts, run `doctor` before reading account-specific data or resuming a collection, because the cached viewer can outlive the login it describes.
