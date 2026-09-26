---
name: facebook
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: >-
  Read content on facebook.com through the user's logged-in Aside browser: Facebook post URLs, home feed, profiles, About fields, comments, search, and groups. Use whenever the request is to read or explore something on Facebook, including 페이스북에서, 내 페이스북 피드, 이 페북 글 댓글, 페북에서 누가 올렸어. Facebook URLs belong here even when the user only says “read this” or “summarize these comments.” Not for other social networks, general web pages, news about the Facebook company, or writing posts, comments, or reactions.
---

# Facebook through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` on one line. `--help` gives the commands and their arguments, `schema` what results, files and fields mean, and each error's `fix` how to recover.

## Every request is the person's real account

A checkpoint lands on the person's real account and only they can clear it, and every branch of a fan-out multiplies requests. Before following commenters, authors or group members, decide how many people or groups the question actually needs. Raise `--max-requests` only when the question needs more than one invocation reads.

## Order decides what a window can prove

Newest-first reads (feed and group with `--sort recent`) are chronological, so a date window closes at its lower bound; ranked reads are samples that can miss anything in the window; a profile window is filtered by Facebook itself. For a question about a period, choose an order that can close.

Even a closed window is what Facebook chose to show in that feed or group, not everything every friend posted there; describe the scope that way.

## Choosing whom to follow

Search returns several people with the same name. When who someone is changes the answer, confirm the identity (verified badge, About) before choosing. Open an unfamiliar author's About only when their context matters; each collection is a request.

## What a partial result can support

A truncated body says nothing about the rest of the post. When the rest could change your conclusion — a summary, a stance, a full quote — open the post; when you quote only what was received, say it is the beginning. If the opened post is still truncated, keep that qualification. Report `coverage:` lines as limits, never as "there are none".

## Collections and personal data

Collect into a file with `--out` when a result is too large to read in the conversation. Files and the cache hold other people's personal information: keep collections outside the repository and delete them when the task is done. Do not delete the account protection state that `doctor` lists; that removes block and pacing protection.
