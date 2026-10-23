---
name: sns
description: >-
  Read social networks through the user's logged-in Aside browser: X (Twitter), Threads, Reddit, Facebook and Naver Blog. Feeds, a post with its replies or comment tree, quotes and reposts, profiles, followers and following, search, subreddits and wikis, Facebook groups and pages, X lists, communities and trends, Naver blogs, categories and neighbors, the pictures in a post, and the user's own saved, liked and notification items. Use whenever the request is to read or explore one of these platforms or to follow a lead across them — 트위터에서, 엑스에서, 스레드에서, 레딧에서, 서브레딧, 페이스북에서, 페북 그룹, 네이버 블로그에서, 이웃새글, SNS 반응, SNS 후기 — including a bare x.com, twitter.com, threads.com, threads.net, reddit.com, redd.it, facebook.com, blog.naver.com, m.blog.naver.com or naver.me link with no platform named. Pick it by where the content lives, not by the topic. Not for Instagram, YouTube, Naver Cafe, News or 지식iN, Tistory, other websites, news about these companies, direct messages, or posting, replying, reacting, following and saving.
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
---

# Social networks through the user's own browser

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <platform> <command> …` as its own call with the literal script path: the permission rule matches the whole command line, so a `cd`, a variable, a loop, a pipe or a second command around it stops for approval, and several reads are several calls. `--help` maps every platform's commands, `<platform> <command> --help` says what a read costs and returns, and `<platform> schema` says what results and fields mean.

## What a read supports

Feeds, top or relevance search and the replies a platform shows first are what it chose to show this account, and a thread speaks for the people who answered there; neither stands for the platform or its users. Counts, shares, rankings and words like "most", "none" or "all" are stated over the items actually read, as the output's coverage line counts them (shown, deeper than `--depth`, not expanded), not the platform's own total.

Claims stay inside what was read. A field the output marks unknown is unknown, not false, and what was not opened — a reply body, a branch, a post behind a notification — was not seen. When something unread could change the answer — a body cut at `--chars` or by the platform, comments that could not be opened, branches not expanded, pictures not looked at — name that gap in one line; nobody can vouch that unread content would not change it. A gap that cannot touch the answer needs no mention.

A post's text names its pictures but not what is in them: a menu's prices, a disclosure drawn into a photo, a product's defect. When the answer could sit in a picture, look at it with `<platform> images` and Read the saved file.

## How much to read

Stop when what was read supports the answer at the detail asked for. A request for the end ("끝까지", every reply, the whole category) runs through that scope until it is exhausted or a stop says otherwise, and reports what remains; when the answer sits in something the output points to (the branch the question is about, the pictures that hold the prices), open it rather than offering to. A search that finds little has not shown there is little: before saying so, try the words the platform's own users would write (another language, a product's short name) or another surface (a group, a community, a tag). Reuse what earlier calls returned; read again only for what they lacked. Ask first only when a read would cost far more than the request reasonably covers — hundreds of requests, an `--out` collection the user did not ask for — and say what it would cost; an explicit request for the whole thing already covers it.

## An account is not a person

What someone posts is that account's observed activity. Report what was said and by whom; do not infer the writer's politics, region or nationality, health, or relationships from their posts, names, language or who they follow, and do not sort commenters into such groups. What a person states about themselves can be quoted as their own words, as far as the question needs: asked who a private commenter is, say what their public activity shows about the matter at hand, and do not gather their school, work, family or places into a portrait. Group reactions by what they say, not by who the speakers seem to be.

## Every request is the user's real account

A checkpoint, challenge or lock lands on the user's account and only a person can clear it in their browser: stop, tell the user what the output said, and run `doctor --unblock` only after they say they have. A rate or scope limit names when it lifts: say so; wait only when that is short against the task, otherwise whether to wait is the user's call. When a read wrote an `--out` file, say where it is and that it holds the posts read, other people's words among them.

## Naver Blog

No field says a post is sponsored; when commercial influence matters to the answer, keep what a post states apart from what its links and pictures suggest:

- Korea's FTC guideline puts a disclosure in the title or the opening (for a photo post, in the photo), so one only at the bottom or behind a link is a badly placed disclosure, not a missing one, and no disclosure does not show a post is unsponsored. '체험단', '체험 후기' or '선물' describing what the writer received is wording the guideline calls inadequate, and the post is still a sponsored one.
- A seller's marketing link (`mkt.shopping.naver.com/link/<id>`) is one link the seller hands to many channels, so the same id across bloggers shows that link handed around, not that the bloggers act together; a creator's shopping-connect link (`brandconnect.naver.com`, often behind naver.me) is unique to that blogger, pays them commission and calls for a sentence saying so.
- A picture served from a review-campaign platform (a 체험단 site such as reviewplace or reviewnote) is a lead to that campaign; its host alone does not show what the picture says. A purchase-verification card names the item bought, which may not be the item the post reviews.
