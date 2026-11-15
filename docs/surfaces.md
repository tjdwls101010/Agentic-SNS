# What the skill reads, platform by platform

Every surface a logged-in person can read on each platform, taken from the sites' own menus, tabs and sort controls (swept 2026-11-16), and what the skill does with it. A surface the skill does not read says why.

Status values:

- **command** — the skill reads it; the command is given.
- **in recon (R#)** — being checked; R# is the item in the plan's appendix A (`.claude/plans/sns-skill-frame-audit.md`).
- **none — proven impossible** — tried; the platform does not serve it to a reader.
- **none — reading would write** — reading it marks something seen or read.
- **none — excluded (DM)** — private messages are out of scope by decision.
- **none — this account does not show it** — the platform hides it from this account; the condition to look again is given.

Writing, settings, ads, AI chat and games are not reading surfaces and are not listed.

## X

| Surface | Where on the site | Status |
|---|---|---|
| Home feed: For you, Following | Home tabs | command: `x feed --tab foryou\|following` |
| Profile: posts, replies, media, highlights, articles | Profile tabs | command: `x profile ACCOUNT --tab …` |
| Profile: reposts tab | Profile tab `/<account>/reposts` (new) | in recon (R17a) |
| Profile: lists, list memberships | Profile ⋯ menu | command: `x profile ACCOUNT --tab lists\|memberships` |
| Account card | Profile header | command: `x about ACCOUNT` |
| Following, followers, verified followers, followers you know, similar accounts | Profile counts and tabs | command: `x graph ACCOUNT following\|followers\|verified\|known\|similar` |
| Bookmarks, likes | History page `/i/history`, `/i/history/likes` (moved from the menu) | command: `x me bookmarks\|likes` |
| Bookmark folders | Bookmarks (Premium) | in recon (R17b) |
| Notifications, mentions | Notifications page tabs | command: `x me notifications\|mentions` |
| Notifications: Verified tab | Notifications page tab | in recon (R17c) |
| A post with its replies, hidden replies, a reply's branch | Post page | command: `x post POST`, `x replies HANDLE` |
| Reposts and quotes of a post | Post engagements | command: `x reposts POST`, `x quotes POST` |
| Search: posts (top, latest), accounts, media | Search tabs | command: `x search TEXT --type … --sort …` |
| Explore: trending, for you, news, sports, entertainment | Explore tabs | command: `x trends --tab …` |
| List: posts, members, card | List page | command: `x list LIST --tab posts\|members\|about` |
| List subscribers | List page | in recon (R17d) |
| Community: posts (top, recent), media, card; suggested communities | Community page | command: `x community [COMMUNITY] --tab … --sort …` |
| Community members | Community page | in recon (R17e) |
| Space card | Space page | command: `x about SPACE` |
| Post pictures (a video by its poster) | Post media | command: `x images POST` |
| Polls | Post | in recon (R16a) |
| Video captions | Post video | in recon (R14a) |
| Your post analytics | Creator Studio `/i/jf/creators/studio` | in recon (R17f) |
| Messages (Chat), calls | Chat | none — excluded (DM) |

## Threads

| Surface | Where on the site | Status |
|---|---|---|
| Home feed: For you, Following | Home tabs, `/following/` | command: `threads feed --tab foryou\|following` |
| Custom feeds | Feed menu | in recon (R18b) |
| Profile: threads, replies, reposts, media | Profile tabs | command: `threads profile ACCOUNT --tab …` |
| Profile card | Profile header | command: `threads about ACCOUNT` |
| Followers (first page) | Profile followers | command: `threads graph ACCOUNT followers` |
| Followers: next pages | Profile followers, scrolled | in recon (R4) |
| Following | Profile following | command: `threads graph ACCOUNT following` |
| Liked, saved | Menu `/liked/`, `/saved/` | command: `threads me liked\|saved` |
| Activity, first page (all, mentions, replies, quotes, reposts, follows, conversations, following, requests) | Activity `/activity` | command: `threads me activity --tab …` |
| Activity: next pages | Activity, scrolled | in recon (R5) |
| A post with its replies, a reply's branch | Post page | command: `threads post POST`, `threads replies HANDLE` |
| Quotes and reposts of a post | Post activity | command: `threads quotes POST`, `threads reposts POST` |
| Search: posts (top, recent), tags, accounts | Search | command: `threads search TEXT --type …` |
| Trending | Search page | in recon (R12) |
| Post pictures | Post media | command: `threads images POST` |
| Polls | Post | in recon (R16b) |
| Video captions | Post video | in recon (R14b) |
| Your insights | Menu `/insights/` | in recon (R17g) |
| Ghost posts | Menu `/ghost_posts/` | in recon (R17h) |
| Your archive | Menu `/archive/` | in recon (R17i) |
| Messages | `/messages/` | none — excluded (DM) |

## Reddit

| Surface | Where on the site | Status |
|---|---|---|
| Home feed: best, hot, new, top, rising | Home sort | command: `reddit feed --sort …` |
| Home feed: controversial | Home sort | in recon (R10a) |
| Home feed: For You, Following tabs | Home tabs | in recon (R17j) |
| Custom feeds | Left menu | in recon (R18a) |
| A community's listing (hot, new, top, rising, controversial), r/a+b, r/popular, r/all | Community page | command: `reddit sub SUB --sort …` |
| Community card, rules, moderators, pinned posts; a user's card | Community sidebar, profile header | command: `reddit about SUB\|USER` |
| Community wiki | Community wiki | command: `reddit wiki SUB [PAGE]` |
| A user's overview, posts, comments | Profile tabs | command: `reddit profile USER --tab overview\|posts\|comments` |
| Your subscriptions, saved, upvoted | Profile tabs, Manage Communities | command: `reddit me subs\|saved\|upvoted` |
| Your downvoted, hidden | Profile tabs | in recon (R10b) |
| Replies to your comments and posts, mentions | Inbox | command: `reddit me comment-replies\|post-replies\|mentions` |
| A post with its comments, a comment in full, the next batch | Post page | command: `reddit post POST`, `reddit comments POST` |
| Other discussions of the same link | Post "other discussions" | command: `reddit related POST` |
| Search: posts, communities, users | Search tabs | command: `reddit search TEXT --type posts\|subs\|users` |
| Search: comments | Search tab | in recon (R13) |
| Post pictures (gallery, image, a video's preview) | Post media | command: `reddit images POST` |
| Pictures in comments | Comment media | in recon (R2a) |
| Video captions | Post video | in recon (R14c) |
| Chat | `chat.reddit.com` | none — excluded (DM) |

## Facebook

| Surface | Where on the site | Status |
|---|---|---|
| Home feed (top, recent) | Home | command: `facebook feed --sort top\|recent` |
| Feeds filter (favorites, friends, groups, pages) | Menu "Feeds" `/?filter=…` | in recon (R17k) |
| A profile's or page's timeline | Profile "All" tab | command: `facebook profile ACCOUNT` |
| A profile's or page's About; a group's card | About tab | command: `facebook about ACCOUNT\|GROUP` |
| A page's followers | Page "Followers" tab | in recon (R17l) |
| A page's live videos | Page "Live" tab | in recon (R17m) |
| A profile's photos and videos tabs | Profile "More" tabs | in recon (R17n) |
| Friends list | Friends | in recon (R18c) |
| A group's posts (top, recent, activity) | Group page | command: `facebook group GROUP --sort …` |
| Your groups | Menu "Groups" | in recon (R17o) |
| A group's members | Group members tab | in recon (R17p) |
| Events | Menu "Events" | in recon (R17q) |
| Memories | Menu "Memories" `/onthisday/` | in recon (R17r) |
| Saved | Menu "Saved" `/saved/` | in recon (R8) |
| Notifications (first page) | Notifications | command: `facebook me notifications` |
| Notifications: next pages | Notifications "see previous" | in recon (R6) |
| A post with its comments, a comment's replies | Post page | command: `facebook post POST`, `facebook comments POST`, `facebook replies HANDLE` |
| Replies under a reply: next batches | Post page, depth 2 | in recon (R7) |
| Share, reel and watch links | Shared links | in recon (R1) |
| Who reacted to a post | Post reactions | in recon (R18d) |
| Reaction counts by kind | Post reactions | in recon (R15) |
| Search: top, posts, people, pages, groups | Search filters | command: `facebook search TEXT --type …` |
| Search: videos, events | Search filters | in recon (R17s) |
| Post pictures | Post media | command: `facebook images POST` |
| Pictures in comments | Comment media | in recon (R2b) |
| A "sponsored" marker in posts | Feed | command: `facebook feed` (ads come as records with `promoted: true`) |
| Video captions | Post video | in recon (R14d) |
| Messenger | Messenger | none — excluded (DM) |

## Naver Blog

| Surface | Where on the site | Status |
|---|---|---|
| Neighbor feed (이웃새글) | Blog home | command: `naver-blog feed` |
| Your neighbor list, a blog's public neighbor list, followers | 이웃 목록 | command: `naver-blog graph [BLOG] buddies\|followers` |
| Your neighbor groups | 이웃 목록 | command: `naver-blog me groups` |
| 내 소식, 내 활동 (traces you left), who liked your posts | Blog home | in recon (R11) |
| A blog's card, category tree, notices, popular posts | Blog | command: `naver-blog about BLOG` |
| A blog's posts: all, one category, notices, popular | Blog | command: `naver-blog profile BLOG --tab … --category …` |
| A post in full; its comments | Post | command: `naver-blog post POST`, `naver-blog comments POST` |
| Post pictures | Post | command: `naver-blog images POST N…` |
| Pictures in comments | Comments | in recon (R2c) |
| Guestbook (안부글) | Blog | in recon (R17u) |
| A blog's clips | Blog clip tab | in recon (R17v) |
| Search: posts, blogs, tags, clips (relevance, date); inside one blog | Search | command: `naver-blog search TEXT --type … --in BLOG` |
| Popular and related searches | Search, today's keywords | command: `naver-blog keywords [TEXT]` |
| Topic directory, a topic's newest and featured posts | 주제별 보기 | command: `naver-blog topic [TOPIC] --tab newest\|featured` |
| Blogs of the month | 이달의 블로그 | command: `naver-blog monthly` |
| Official blogs | 공식블로그 | in recon (R17w) |
| Challenge program | 챌린지 프로그램 | in recon (R17x) |
| naver.me short links | Anywhere | command: `naver-blog resolve LINK…` |
| Video captions | Post video | in recon (R14e) |
