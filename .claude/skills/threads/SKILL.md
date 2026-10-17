---
name: threads
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: Read Threads through the user's logged-in Aside browser: home feeds, a post with its parent chain and replies, the replies under one reply, the posts quoting a post and the accounts reposting it, profiles and their tabs, followers and following, post, tag and account search with date and author filters, and the user's liked and saved posts. Use whenever the request is to read or explore Threads — 스레드에서, 쓰레드 피드, 이 스레드 글 답글, 스레드 인용, 스레드 검색 — including a bare threads.com or threads.net URL. Not for Instagram, Facebook, X/Twitter, Reddit, programming threads, general web pages, news about Threads or Meta as companies, or posting, replying, liking, reposting, saving and following.
---

# Threads through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` as one plain command: a leading `cd`, a variable holding the path, or a second command joined with `;` or `&&` is not the invocation the permission rule allows. `--help` lists the commands, `<command> --help` says what a read costs and returns, and `schema` says what results and fields mean.

## Every request is the user's real account

A checkpoint or rate limit lands on the user's real account and only they can clear it. Reading a few pages within one command's default budget is ordinary; going past it — a raised `--max-requests`, a list or a date window read to its end, an `--out` collection, a read per replier or author — is a choice about that risk: say what it would cost in requests and get agreement first, unless the user's words already ask for all of it ("read all the replies", "every post from this week"). A question that names only a subject, a period or a number ("who does X follow", "how is Y talked about this week", "how many") does not: read within the default, say what it covered, and offer the larger read with its cost. When no one can be asked, stay within the default and say what it covered.

## What a ranked surface can support

Top search results, the For you feed and the replies Threads shows first are what Threads chose to show this account, not a sample of opinion. From them, say which kinds of posts were common among those read and how many were read; do not turn that into what most people think. A share or "most" holds only over a set read to its end, as the coverage line states it (a dated search or a following feed that Threads had no more of, a reply list with nothing missing); a read cut by `--limit` or the budget, or a list Threads capped, supports only "of the N read".
