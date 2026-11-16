# What the skill reads, platform by platform

Every surface a logged-in person can read on each platform, taken from the sites' own menus, tabs and sort controls (swept 2026-11-16), and what the skill does with it. A surface the skill does not read says why.

Status values:

- **command** — the skill reads it; the command is given.
- **in recon (R#)** — being checked; R# is the item in the plan's appendix A (`.claude/plans/sns-skill-frame-audit.md`).
- **none — proven impossible** — tried; the platform does not serve it to a reader.
- **none — reading would write** — reading it marks something seen or read.
- **none — excluded (DM)** — private messages are out of scope by decision.
- **none — this account does not show it** — the platform hides it from this account; the condition to look again is given.
- **none — undetermined** — recon could not decide (no sample to look at); the condition to look again is given.

Writing, settings, ads, AI chat and games are not reading surfaces and are not listed.

## X

| Surface | Where on the site | Status |
|---|---|---|
| Home feed: For you, Following | Home tabs | command: `x feed --tab foryou\|following` |
| Profile: posts, replies, media, highlights, articles | Profile tabs | command: `x profile ACCOUNT --tab …` |
| Profile: reposts tab | Profile tab `/<account>/reposts` (new) | command: `x profile ACCOUNT --tab reposts` |
| Profile: lists, list memberships | Profile ⋯ menu | command: `x profile ACCOUNT --tab lists\|memberships` |
| Account card | Profile header | command: `x about ACCOUNT` |
| Following, followers, verified followers, followers you know, similar accounts | Profile counts and tabs | command: `x graph ACCOUNT following\|followers\|verified\|known\|similar` |
| Bookmarks, likes | History page `/i/history`, `/i/history/likes` (moved from the menu) | command: `x me bookmarks\|likes` |
| Bookmark folders | Bookmarks (Premium) | none — this account does not show it (a Premium feature; reopen with a Premium account; R17b) |
| Notifications, mentions | Notifications page tabs | command: `x me notifications\|mentions` |
| Notifications: Verified tab | Notifications page tab | command: `x me verified` |
| A post with its replies, hidden replies, a reply's branch | Post page | command: `x post POST`, `x replies HANDLE` |
| Reposts and quotes of a post | Post engagements | command: `x reposts POST`, `x quotes POST` |
| Search: posts (top, latest), accounts, media | Search tabs | command: `x search TEXT --type … --sort …` |
| Explore: trending, for you, news, sports, entertainment | Explore tabs | command: `x trends --tab …` |
| List: posts, members, card | List page | command: `x list LIST --tab posts\|members\|about` |
| List subscribers | List page | none — undetermined (reopen with the list subscribers page's request observed; R17d) |
| Community: posts (top, recent), media, card; suggested communities | Community page | command: `x community [COMMUNITY] --tab … --sort …` |
| Community members | Community page | command: `x community COMMUNITY --tab members` |
| Space card | Space page | command: `x about SPACE` |
| Post pictures (a video by its poster) | Post media | command: `x images POST` |
| Polls | Post | none — undetermined (reopen with a post with a poll; R16a) |
| Video captions | Post video | none — undetermined (reopen with a video with captions; R14a) |
| Your post analytics | Creator Studio `/i/jf/creators/studio` | none — undetermined (reopen with the account's analytics showing data; R17f) |
| Messages (Chat), calls | Chat | none — excluded (DM) |

## Threads

| Surface | Where on the site | Status |
|---|---|---|
| Home feed: For you, Following | Home tabs, `/following/` | command: `threads feed --tab foryou\|following` |
| Custom feeds | Feed menu | none — undetermined (reopen with the account having a custom feed; R18b) |
| Profile: threads, replies, reposts, media | Profile tabs | command: `threads profile ACCOUNT --tab …` |
| Profile card | Profile header | command: `threads about ACCOUNT` |
| Followers (first page) | Profile followers | command: `threads graph ACCOUNT followers` |
| Followers: next pages | Profile followers, scrolled | none — proven impossible: Threads serves one sample (the site stops at it too); the read ends `server_capped` (R4) |
| Following | Profile following | command: `threads graph ACCOUNT following` |
| Liked, saved | Menu `/liked/`, `/saved/` | command: `threads me liked\|saved` |
| Activity, first page (all, mentions, replies, quotes, reposts, follows, conversations, following, requests) | Activity `/activity` | command: `threads me activity --tab …` |
| Activity: next pages | Activity, scrolled | none — undetermined (this account's activity fits one page of 20; reopen with an account whose activity has more; R5) |
| A post with its replies, a reply's branch | Post page | command: `threads post POST`, `threads replies HANDLE` |
| Quotes and reposts of a post | Post activity | command: `threads quotes POST`, `threads reposts POST` |
| Search: posts (top, recent), tags, accounts | Search | command: `threads search TEXT --type …` |
| Trending | Search page | none — this account does not show it (reopen when the search screen shows trends; R12) |
| Post pictures | Post media | command: `threads images POST` |
| Polls | Post | none — undetermined (reopen with a post with a poll; R16b) |
| Video captions | Post video | none — undetermined (reopen with a video with captions; R14b) |
| Your insights | Menu `/insights/` | none — undetermined (reopen with the account's insights showing data; R17g) |
| Ghost posts | Menu `/ghost_posts/` | in recon (R17h) |
| Your archive | Menu `/archive/` | in recon (R17i) |
| Messages | `/messages/` | none — excluded (DM) |

## Reddit

| Surface | Where on the site | Status |
|---|---|---|
| Home feed: best, hot, new, top, rising | Home sort | command: `reddit feed --sort …` |
| Home feed: controversial | Home sort | command: `reddit feed --sort controversial` |
| Home feed: For You, Following tabs | Home tabs | none — undetermined (reopen with the home tabs' request observed; R17j) |
| Custom feeds | Left menu | command: `reddit sub m/NAME` (yours), `reddit sub u/USER/m/NAME` (another account's public feed) |
| A community's listing (hot, new, top, rising, controversial), r/a+b, r/popular, r/all | Community page | command: `reddit sub SUB --sort …` |
| Community card, rules, moderators, pinned posts; a user's card | Community sidebar, profile header | command: `reddit about SUB\|USER` |
| Community wiki | Community wiki | command: `reddit wiki SUB [PAGE]` |
| A user's overview, posts, comments | Profile tabs | command: `reddit profile USER --tab overview\|posts\|comments` |
| Your subscriptions, saved, upvoted | Profile tabs, Manage Communities | command: `reddit me subs\|saved\|upvoted` |
| Your downvoted, hidden | Profile tabs | command: `reddit me downvoted\|hidden` |
| Replies to your comments and posts, mentions | Inbox | command: `reddit me comment-replies\|post-replies\|mentions` |
| A post with its comments, a comment in full, the next batch | Post page | command: `reddit post POST`, `reddit comments POST` |
| Other discussions of the same link | Post "other discussions" | command: `reddit related POST` |
| Search: posts, communities, users | Search tabs | command: `reddit search TEXT --type posts\|subs\|users` |
| Search: comments | Search tab | in recon (R13) |
| Post pictures (gallery, image, a video's preview) | Post media | command: `reddit images POST` |
| Pictures in comments | Comment media | none — undetermined (reopen with a comment with a picture; R2a) |
| Video captions | Post video | none — undetermined (reopen with a video with captions; R14c) |
| Chat | `chat.reddit.com` | none — excluded (DM) |

## Facebook

| Surface | Where on the site | Status |
|---|---|---|
| Home feed (top, recent) | Home | command: `facebook feed --sort top\|recent` |
| Feeds filter (favorites, friends, groups, pages) | Menu "Feeds" `/?filter=…` | command: `facebook feed --tab favorites\|friends\|groups\|pages` |
| A profile's or page's timeline | Profile "All" tab | command: `facebook profile ACCOUNT` |
| A profile's or page's About; a group's card | About tab | command: `facebook about ACCOUNT\|GROUP` |
| A page's followers | Page "Followers" tab | command: `facebook graph ACCOUNT followers` (the first page the tab loads; a longer list ends `not_built`) |
| A page's live videos | Page "Live" tab | in recon (R17m — no capture of the tab's payload yet) |
| A profile's photos tab | Profile "Photos" tab | command: `facebook profile ACCOUNT --tab photos` (the first page the tab loads; a longer tab ends `not_built`) |
| A profile's videos tab | Profile "More" tabs | in recon (R17n — no capture of the videos tab's payload yet) |
| Your friends list | Friends `/friends/list` | command: `facebook graph friends` (the first page the screen loads) |
| Another account's friends | Profile "Friends" tab | in recon (R18c — only your own list was observed; another account's tab and its private answer were not) |
| A group's posts (top, recent, activity) | Group page | command: `facebook group GROUP --sort …` |
| Your groups | Menu "Groups" | command: `facebook me groups` (the first page the Your groups screen loads; a longer list ends `not_built`) |
| A group's members | Group members tab | command: `facebook group GROUP --tab members` (the tab's new members section only, its first page; a longer one ends `not_built`; the tab's other buckets are not read) |
| Events | Menu "Events" | in recon (R17q — the upcoming events list was empty, so no event's fields were seen) |
| Memories | Menu "Memories" `/onthisday/` | none — undetermined (reopen with a day with memories; R17r) |
| Saved | Menu "Saved" `/saved/` | command: `facebook me saved` (the first page the screen loads; the next-page request was not observed, so a longer list ends `not_built`) |
| Notifications (first page) | Notifications | command: `facebook me notifications` |
| Notifications: next pages | Notifications "see previous" | command: `facebook me notifications --limit N` (more: continues) |
| A post with its comments, a comment's replies | Post page | command: `facebook post POST`, `facebook comments POST`, `facebook replies HANDLE` |
| Replies under a reply: next batches | Post page, depth 2 | none — undetermined (reopen with a reply branch two levels deep that has more; R7) |
| Share, reel and watch links | Shared links | none — undetermined (reopen with a share, reel or watch link to try; R1) |
| Who reacted to a post | Post reactions | none — undetermined (reopen with the reactions dialog's request observed; R18d) |
| Reaction counts by kind | Post reactions | command: `facebook post` / `feed` (reactions field) |
| Search: top, posts, people, pages, groups | Search filters | command: `facebook search TEXT --type …` |
| Search: videos | Search filters | command: `facebook search TEXT --type videos` (the first page the videos search screen loads; more ends `not_built`) |
| Search: events | Search filters | in recon (R17s — event search was not observed) |
| Post pictures | Post media | command: `facebook images POST` |
| Pictures in comments | Comment media | none — undetermined (reopen with a comment with a picture; R2b) |
| A "sponsored" marker in posts | Feed | command: `facebook feed` (ads come as records with `promoted: true`) |
| Video captions | Post video | none — undetermined (reopen with a video with captions; R14d) |
| Messenger | Messenger | none — excluded (DM) |

## Naver Blog

| Surface | Where on the site | Status |
|---|---|---|
| Neighbor feed (이웃새글) | Blog home | command: `naver-blog feed` |
| Your neighbor list, a blog's public neighbor list, followers | 이웃 목록 | command: `naver-blog graph [BLOG] buddies\|followers` |
| Your neighbor groups | 이웃 목록 | command: `naver-blog me groups` |
| 내 소식 (news from your neighbors' blogs) | Blog home | in recon (R11) |
| 내 활동 (traces you left), who liked your posts | Blog home | none — undetermined (reopen with the request those screens send observed; R11) |
| A blog's card, category tree, notices, popular posts | Blog | command: `naver-blog about BLOG` |
| A blog's posts: all, one category, notices, popular | Blog | command: `naver-blog profile BLOG --tab … --category …` |
| A post in full; its comments | Post | command: `naver-blog post POST`, `naver-blog comments POST` |
| Post pictures | Post | command: `naver-blog images POST N…` |
| Pictures in comments | Comments | none — undetermined (reopen with a comment with a picture; R2c) |
| Guestbook (안부글) | Blog | none — undetermined (reopen with the framed page's requests observed; R17u) |
| A blog's clips | Blog clip tab | none — undetermined (reopen with the framed page's requests observed; R17v) |
| Search: posts, blogs, tags, clips (relevance, date); inside one blog | Search | command: `naver-blog search TEXT --type … --in BLOG` |
| Popular and related searches | Search, today's keywords | command: `naver-blog keywords [TEXT]` |
| Topic directory, a topic's newest and featured posts | 주제별 보기 | command: `naver-blog topic [TOPIC] --tab newest\|featured` |
| Blogs of the month | 이달의 블로그 | command: `naver-blog monthly` |
| Official blogs | 공식블로그 | none — undetermined (reopen with the framed page's requests observed; R17w) |
| Challenge program | 챌린지 프로그램 | none — undetermined (reopen with the framed page's requests observed; R17x) |
| naver.me short links | Anywhere | command: `naver-blog resolve LINK…` |
| Video captions | Post video | none — undetermined (reopen with a video with captions; R14e) |
