---
name: naver-blog
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/naver_blog.py" *)
description: >-
  Read Naver Blog (blog.naver.com) through the user's logged-in Aside browser: search posts, blogs and tags across Naver, open a post in full with its tags and same-category posts, read a blog's card, category tree, post lists, notices and popular posts, read comments and replies, search inside one blog, browse topic directories and blogs of the month, and read the user's own neighbor feed and neighbor list. Use whenever the request is to read or explore something on Naver Blog — 네이버 블로그에서, 이 블로그 글 읽어줘, 이 블로그 카테고리, 이 블로그 글 댓글, 이웃새글, 네이버 블로그 검색, 블로그 후기·리뷰·내돈내산 찾아줘 — including a bare blog.naver.com or m.blog.naver.com URL. Not for Naver Cafe, Naver News, Naver 지식iN, Naver Shopping, other Naver services, Tistory or Brunch, general web pages, or writing posts, comments, likes and neighbor requests.
---

# Naver Blog through the user's own browser

The browser supplies the account, already logged in as the person you are working for; the bundled CLI supplies read-only queries and dense text. Below, `$NB` means `python3 "${CLAUDE_SKILL_DIR}/scripts/naver_blog.py"` — expand it to the quoted absolute path on one shell line. Start from `$NB --help`; `schema` describes what comes back, and every error carries the `fix` for its own case.

## Naver's own counts are not answers

A blog's post list reports a total of zero no matter how many posts it holds, and a search total shifts between pages of the same query. Search itself stops at a thousand results in every ordering, and the pages past that report a total of zero as well — which looks exactly like "nothing found" unless something tells them apart, so the tool reports that stop separately from an honest empty result. The consequence is that "how many are there" is answered with the number actually read, and reaching further means narrowing the question — a date window, a tighter keyword, one blog's own search — rather than turning more pages. The neighbour feed has no pages at all: it hands over what it has and nothing asks it for more.

## A post is one page, and the body is the only thing that can drift

Everything else arrives as JSON with a stable shape; a post body is editor HTML. So the body line says how much of it survived. `text[full]` means every block was read by a rule written for it. `text[partial: 3 of 21 components reduced]` means three blocks gave up only their text and pictures, and the header names which kinds they were. Summarise a reduced body as a reduced body, and never as the whole post. Tags read `unknown` when the page carried no tag field at all, which is a different thing from a post with no tags — the first forbids saying "untagged", the second permits it.

## Reviews are an economy, not a sample

Naver Blog is where Korean product and place reviews live, and a large share of them are paid, sponsored or comped. There is no field that says so — look in `schema` and you will not find one. What you have is the disclosure sentence Korean sponsored posts carry near the top or bottom ("소정의 원고료를 받고…", "체험단"), the `buy-with-own-money` label Naver puts on posts the writer marked as bought themselves, and the shape of the blog's own post list: a blog whose every recent post is a different brand is an advertising channel. Say which of these you used and what you set aside. Relevance ordering ranks by match, not by honesty.

## Handles and URLs are the next command's arguments

Every line carries what the next command needs: `blogId/logNo` for a post, `blogId` for a blog, a full URL to paste back. For an unfamiliar blog the card comes first — it tells you who they are, how many neighbours they have and whether the account already follows them — and then their categories, which are how a Naver blog is actually organised. A commenter's blog id, when Naver supplies one, is a next hop to the person rather than the post. Continuing a listing works by page number rather than a server cursor, so a post published between two reads shifts the boundary; the tool removes duplicates it can see but cannot restore something pushed past.

## What has actually bitten

Blog ids made only of digits exist, and a blog's own domain address redirects to a different id than the one in the address bar. Replies come back mixed flat into the comment list rather than nested under their parents, newest first, with no way to ask for another order. View counts exist only on the popular-posts shelf; the read count on everyone else's post list is a constant zero. Tag search results carry no blog name at all. Naver's excerpts are cut by character count, so they can end mid-emoji. Neighbour lists are private by default, so an empty one is not evidence of having no neighbours — the card's count usually disagrees with it.

## Large collections and what the cache holds

Collect to a file when the corpus is larger than the answer needs; read it back in place of asking again. Both those files and the cache under `~/.cache/naver-blog-skill` hold other people's material, and this is a real-name medium where faces, workplaces and neighbourhoods are ordinary post content. A neighbour list plus their post lists plus the people who comment is a map of someone's social circle assembled from pieces that were each posted alone — gather what the question needs and delete it when the question is answered. Every request rides the person's own logged-in account, so a search worth running twice is worth reading once.
