---
name: naver-blog
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/naver_blog.py" *)
description: >-
  Read Naver Blog (blog.naver.com) through the user's logged-in Aside browser: search Naver Blog for posts, blogs and tags, open a post in full with its tags and same-category posts, read a blog's card, category tree, post lists, notices and popular posts, read comments and replies, search inside one blog, browse topic directories and blogs of the month, and read the user's own neighbor feed and neighbor list. Use whenever the request names Naver Blog or points at it — 네이버 블로그에서, 네이버 블로그 글 읽어줘, 이 블로그 카테고리, 이 블로그 글 댓글, 이웃새글, 서로이웃 새 글, 내 이웃 목록, 네이버 블로그 검색, 이달의 블로그, 네이버 블로그 후기·내돈내산 찾아줘 — including a bare blog.naver.com or m.blog.naver.com URL. Pick it by where the content lives, not by the topic: a review or a blog post is only this skill's when the platform or the link says Naver Blog. Not for Naver Cafe, Naver News, Naver 지식iN, Naver Shopping, other Naver services, Tistory, Brunch or Velog, general web pages, or writing posts, comments, likes and neighbor requests.
---

# Naver Blog through the user's own browser

The browser supplies the account, already logged in as the person you are working for; the bundled CLI supplies read-only queries and dense text. Below, `$NB` means `python3 "${CLAUDE_SKILL_DIR}/scripts/naver_blog.py"` — expand it to the quoted absolute path on one shell line. Start from `$NB --help`; `schema` describes what comes back, and every error carries the `fix` for its own case.

## Naver's own counts are not answers

A blog's post list reports a total of zero no matter how many posts it holds, and a search total shifts between pages of the same query. Search itself stops at a thousand results in every ordering, and the pages past that report a total of zero as well — which looks exactly like "nothing found" unless something tells them apart, so the tool reports that stop separately from an honest empty result. The consequence is that "how many are there" is answered with what was actually read and what stopped the reading, never with the server's figure; reaching further means narrowing the question — a date window, a tighter keyword, one blog's own search — rather than turning more pages. The neighbour feed is not a listing at all: Naver hands over the posts it has staged and accepts no request for more, so what comes back is neither every neighbour's posts nor everything from any stretch of time.

## A post is one page, and its body is the part extraction can fall short of

The body is editor HTML rather than a field, so extraction from it can fall short, and the body line reports how far it got. `text[full]` means every block was read by a rule written for it. `text[partial: 3 of 21 components reduced]` means three blocks gave up only their text and pictures — what those blocks additionally held is unknown, so a summary drawn from a reduced body says it was reduced, and the ratio is a count of blocks rather than a proportion of meaning. Tags read `unknown` when the page carried no tag field at all, which is a different thing from a post with no tags: the first forbids saying "untagged", the second permits it.

## Reviews are an economy, not a sample

Naver Blog is where Korean product and place reviews live, and a large share of them are paid, sponsored or comped. There is no field that says so, which means sponsorship is inferred rather than read: from the disclosure sentence Korean sponsored posts carry near the top or bottom ("소정의 원고료를 받고…", "체험단"), from the `buy-with-own-money` label Naver puts on posts the writer marked as bought themselves, and from the shape of the blog's own post list, where a run of posts about unrelated brands is a reason to look for a disclosure rather than a verdict on its own. Because it is inference, the answer says which signals were used and what was set aside, and treats every unexamined post as unclassified. Relevance ordering ranks by match, not by honesty.

## Handles and URLs are the next command's arguments

Every line carries what the next command needs: `blogId/logNo` for a post, `blogId` for a blog, a full URL to paste back. Which surface to open next follows from the question — who is writing this needs the blog's card, how they organise their work needs the category tree, what they publish needs a post list, and a commenter's blog id is a hop to a person rather than to another post. Continuing a listing works by page number rather than a server cursor, so a post published between two reads shifts every later boundary; duplicates that reappear are removed, but a record pushed across a boundary is simply never seen, and a continued listing therefore cannot be called exhaustive.

## What has actually bitten

A blog id can be nothing but digits, and a blog's own domain address redirects to a different id than the one in its address — so neither the shape of an identifier nor a difference between two address strings settles which blog is which; only the id the tool resolved does. Replies arrive mixed flat into the comment list, newest first, with no other order available, which makes adjacency in the output meaningless: a reply belongs to the parent its own line names, and the sequence is not the order the conversation happened in. View counts exist only on the popular-posts shelf, and the read count everywhere else is a constant zero rather than a measurement, so an ordinary post has no readership figure and the popular shelf's numbers describe only that shelf. Tag search returns no blog name at all — an absent name there is a gap in that surface, not an unnamed blog. Naver's excerpts are cut at a character count, so an excerpt's ending is where the string stopped rather than where the writer did, and nothing about the post's conclusion can be read from it. Neighbour lists are private by default, so an empty one is not evidence of having no neighbours; the card's own count usually says otherwise.

## Large collections and what the cache holds

A collected file fixes what was read to one moment, so rereading it answers further questions about that material without spending the account again — and answers a question about what has changed since only as the older half of a comparison, never on its own. Both those files and the cache under `~/.cache/naver-blog-skill` hold other people's material, and this is a real-name medium where faces, workplaces and neighbourhoods are ordinary post content. A neighbour list plus their post lists plus the people who comment is a map of someone's social circle assembled from pieces that were each posted alone, so the amount gathered is decided by the question and deleted when the question is answered.
