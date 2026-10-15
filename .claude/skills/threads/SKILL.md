---
name: threads
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: Read Threads through the user's logged-in Aside browser: home feeds, a post with its parent chain and replies, profiles and their tabs, followers and following, post or account search, and the user's liked and saved posts. Use whenever the request is to read or explore Threads — 스레드에서, 쓰레드 피드, 이 스레드 글 답글, 스레드 검색 — including a bare threads.com or threads.net URL. Not for Instagram, Facebook, X/Twitter, Reddit, programming threads, general web pages, or posting, replying, liking, saving and following.
---

# Threads through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` written out on one line; a command kept in a shell variable is not split into words by zsh and fails. `--help` lists the commands and their arguments, `schema` says what results and fields mean, and each error's `fix` says how to recover.

## Every request spends the person's account

Threads sends no rate-limit headers and a checkpoint lands on the person's real account, so choose before opening: pick the posts and people worth reading from what a listing already shows — handles, previews, counts — and open only those. Once the evidence answers the question, stop even if more could be read, and say what was left unread. Recovery (refresh, capture) is the same account's activity: run it only when the answer needs the surface that failed.

## What a read can support

What Threads shows first — top search results, the replies under a post — is ranked, not a sample of opinion: when summarizing reactions, say which order and how much of it was read, and don't claim what most people think.

A quote or repost carries its original author's words: attribute a claim to that author, and don't count one post seen through several sorts or searches as separate voices.

Dates are when a post was written. A repost carries the original's date, so it shows neither when the person reposted it nor what they did in a period.

When who someone is — bio, verification, privacy — could change how their posts read, look at their `about` card before interpreting them.

## Collections hold other people's activity

Use `--out` when the corpus needed is larger than what the answer shows. The file and the continuation handles in the cache's `cursors/` folder (`$THREADS_HOME`, default `~/.cache/threads-skill`) hold other people's posts: keep the file outside the repository and delete both when the task is done. `budget.json` and `blocked.json` beside them protect the account; leave them.
