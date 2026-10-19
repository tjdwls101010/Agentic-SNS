---
name: twitter
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: Read X (Twitter) through the user's logged-in Aside browser: the home feeds, a post with its parent chain and replies, profiles and their tabs, followers, following and similar accounts, reposts and quotes, search with X's operators (also across communities), trends, lists, communities, space cards, and the user's own bookmarks, likes, notifications and mentions. Use whenever the request is to read or explore X or Twitter — 트위터에서, 엑스에서, 이 트윗 답글, 리트윗, 트위터 타임라인, 트위터 검색, 트위터 트렌드, 엑스 알림 — including a bare x.com or twitter.com URL. Not for Threads, Facebook, Reddit, general web pages, news about X the company, direct messages, or posting, replying, liking, reposting, following and saving to bookmarks.
---

# X through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` as one plain command: a leading `cd`, a variable holding the path, or a second command joined with `;` or `&&` is not the invocation the permission rule allows. `--help` lists the commands, `<command> --help` says what a read costs and returns, and `schema` says what results and fields mean.

## Every request is the user's real account

A lock or challenge lands on the user's real account and only they can clear it. Reading a few pages within one command's default budget is ordinary; going past it — a raised `--max-requests`, a list or a date window read to its end, an `--out` collection, a read per replier or author — is a choice about that risk: say what it would cost in requests and get agreement first, unless the user's words already ask for all of it ("read all the replies", "every post from this week"). A question that names only a subject, a period or a number ("who does @name follow", "how is <topic> talked about this week", "how many") does not: read within the default, say what it covered, and offer the larger read with its cost. When no one can be asked, stay within the default and say what it covered.

## What a ranked surface can support

The For you and Following feeds, Top search and the replies X shows first are what X chose to show this account, and neither feed comes in date order. From them, say which kinds of posts were common among the N read, not what most people think. A share, "most" or "only N" holds only over a set read to its end, as the coverage line states it (a search with since:/until: that X had no more of, a list with nothing missing); a read cut by `--limit` or the budget, or a feed in no date order, supports only "of the N read".
