---
name: reddit
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: Read Reddit through the user's logged-in Aside browser — the home feed, subreddit listings (r/popular and r/all included), posts and their comment trees, a linked comment, a redditor's activity and card, a community's rules, moderators, pinned posts and wiki, search for posts, communities or users, the other discussions of a link, and the user's own subscriptions, saved and upvoted items. Use whenever the request is to read or explore Reddit — 레딧에서, 서브레딧, 이 스레드 댓글 읽어줘, 레디터들은 뭐라고 해, 레딧 후기, 레딧 위키, 내 레딧 피드 — including a bare reddit.com or redd.it URL with no mention of Reddit. Not for other social networks, general web pages or web coverage of Reddit the company, or posting, voting, commenting, saving and private messages.
---

# Reddit through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` as a plain command with the literal script path: a leading `cd`, a path held in a variable, or another program chained to it is not what the permission rule allows. `--help` lists the commands, `<command> --help` says what a read costs and returns, and `schema <object>` says what results and fields mean.

## Every request is the user's real account

Reads go out as the user's real Reddit account: a rate limit interrupts its reading until Reddit's reset, and a browser challenge stops everything until the user clears it. Searching and opening the posts and threads a question needs is ordinary reading. Before a planned read would use a large share of the request window — judged across all the calls it takes, such as reading a thread of hundreds of comments to the end or opening each commenter's history — say what it would cost and get agreement, unless the user already asked for that scope. When going on means waiting for a reset, whether to wait is the user's call.

## What a ranked or partial read supports

Hot, top, best and search results are what Reddit chose to show this account, and a thread speaks for the people who answered in that community, not for Reddit or for the community's members. Tie each frequency or share claim to the comments whose text you actually read, and name the order: "among the 150 comments read in best order, most named their mid-30s" holds; "most people there felt it in their mid-30s" does not follow even from the whole thread, since commenters are self-selected and the order chose what was seen. Comments received but not shown, and gaps not expanded, are not in that count.

## An account is not a person

A public history is that account's observed activity. Summarize the topics and communities it shows; do not infer the person's location, politics, health or other personal attributes from flair, place names or asides, or assemble such clues into a personal profile — combined, they can make the person identifiable.
