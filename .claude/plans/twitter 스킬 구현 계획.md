# `twitter` 스킬 구현 계획

계획 세션: 2026-09-05. 구현 세션은 이 파일만 읽고 시작할 수 있어야 한다. 아래 수치는 전부 이 세션에서 Aside `u0`로 실측한 값이다(GraphQL 약 70요청, 라우트·CDN GET 약 1,100회, 탭 8회). codex(gpt-6-astra, medium) 적대적 리뷰 결과는 맨 끝 절에 반영한다. 오퍼레이션 33종의 query id·변수 템플릿·봉투 루트·게이트 여부·레이트리밋 버킷·검증 방법과 feature 플래그 39개는 이 문서 끝의 **레지스트리 스냅샷** JSON 블록에 통합돼 있고 P0의 `registry.json` 초안은 그 블록을 그대로 읽어 만든다. 형제 계획 `threads 스킬 구현 계획.md`·`reddit 스킬 구현 계획.md`와 같은 구조이며, 이 세션은 `threads` 스킬 파일을 건드리지 않는다(다른 세션이 구현 중).

## Context

성진은 클로드가 X(트위터)를 **사람처럼** 쓰기를 원한다. 홈 피드를 훑다가 글을 열고, 답글과 인용을 읽고, 작성자의 프로필과 타임라인을 보고, 팔로워를 살피고, 검색하고, 트렌드와 리스트와 커뮤니티를 드나드는 흐름을 스크린샷·클릭 없이 밀도 높은 텍스트로 수행한다. 시각 UI 대신 X 웹 클라이언트가 실제로 쓰는 GraphQL 백엔드(`GET|POST https://x.com/i/api/graphql/<queryId>/<Operation>`)를 직접 부르고, 로그인은 이미 로그인된 **Aside 브라우저** 세션을 `aside repl`의 `fetch`로 빌린다.

이전 시도 `.tmp/Agentic X`(PyPI `agentic-twitter` v0.6.0, 6,874줄)는 기술적으로 동작했지만 **세션을 스스로 소유했다.** `auth.py` 479줄·`session.py` 287줄·`observe.py`·`config.py`·`cli.py`의 login/setup/status/catalog, stealth 브라우저 extra, PyPI 버전 비교와 그 SKILL.md의 3분의 1이 "로그인된 브라우저가 없다"는 전제 때문에 있었다. Aside 위에 올리면 그 층이 사라지고, **검증된 봉투 워커(`parse.py`)·모델(`model.py`의 트윗 부분)·txid 수학(`transaction.py`)·번들 채굴기(`queryids.py`)·페이지네이션 규칙(`retrieve.py`)**만 남는다. 2026-07-26의 query id 22종은 **이번 실측에서 전부 회전했다**(6주). 그러나 옛 채굴 방식은 그대로 통했고, 옛 txid 알고리즘은 **오늘도 통한다**(게이트 3종 전부 200).

facebook·reddit·threads와 같은 하네스 프레임을 코드에 닿게 적용한다. **principle over rail**: SKILL.md는 규칙 나열이 아니라 X의 사실과 그 결과를 쓴다. **interface over document**: 명령·플래그·종료 코드·복구 명령은 `--help`와 출력 자체가 가르치고 SKILL.md는 "언제·왜·무엇이 물었나"만 쓴다. **for user not developer**: 읽는 이는 사용 시점의 클로드다. 기본 출력은 밀도 높은 텍스트이고 전체 JSON은 요청할 때만 나온다. **dense information**: 트윗 하나는 3~4줄, 답글은 2~3줄이며 다음 홉의 핸들(`@handle`, URL)을 항상 싣는다.

X가 형제와 다른 점 넷이 설계를 결정한다. **회전하는 것 셋(query id·txid 재료·feature 플래그)이 전부 x.com HTML과 정적 CDN JS에 실려 온다.** Threads처럼 탭을 열어 SPA 클릭으로 캡처할 필요가 없고 `refresh`는 탭 없이 완결된다. **세 오퍼레이션(`SearchTimeline`·`Followers`·`UserTweetsAndReplies`)은 요청마다 새로 만드는 `x-client-transaction-id`를 요구한다.** 캡처·재생이 불가능한 단일 사용 서명이며 옛 `transaction.py`의 알고리즘으로 생성한다. **레이트리밋 헤더가 있다**(오퍼레이션별 15분 창 50·100·150·500). Reddit처럼 헤더로 예산을 세되, 버킷이 오퍼레이션마다 다르다. **탭이 필요한 것은 `ct0` 쿠키 하나뿐이다.** 응답 set-cookie로는 안 오고 `document.cookie`로만 읽히며, 세션 내내 값이 바뀌지 않았다.

## 확정된 결정 (성진, 2026-09-05)

| # | 결정 | 결과 |
|---|---|---|
| D1 | **실계정(Aside `u0`, X `@radamshi99`, id `1818125492823986176`) 로그인 세션 사용** | 홈 피드·북마크·좋아요가 열린다. 요청 간격 하한·오퍼레이션별 헤더 예산·차단 상태를 코드에 고정한다. X는 자동화 계정을 Meta보다 적극적으로 잠그므로 정지 시 잃는 것이 적은 계정이라고 가정한다. |
| D2 | **읽기 전용** | 게시·답글·좋아요·리포스트·팔로우·북마크 변경은 스펙에 `declined`. 번들에서 mutation id는 채굴하지 않는다(`operationType == "query"`만). |
| D3 | **개인 표면은 홈 피드(For you·Following)·북마크·좋아요 포함, 알림·DM 제외** | `home --feed foryou\|following`, `me bookmarks\|likes`. `NotificationsTimeline`·DM은 `declined`. |
| D4 | **관계·반응 표면 포함**: 팔로잉·팔로워(+인증·아는 사람)·리포스트한 사람·인용 | `graph <@name> following\|followers\|verified\|known`, `reposts <post>`, `quotes <post>`. 좋아요한 사람은 X가 빈 종료 타임라인만 주므로 명령을 두지 않는다. |
| D5 | **추가 표면 포함**: 프로필 탭 4종(답글·미디어·하이라이트·아티클), 리스트(글·멤버·정보), 트렌드(탐색 탭), 커뮤니티(글·미디어·정보·둘러보기·전체 커뮤니티 글 검색) | 전부 이 세션에서 실측 200. 특정 커뮤니티 안으로 좁히는 검색은 미실측이라 범위 밖. |
| D6 | **`ct0`는 `0600` 디스크 캐시 + 거부(403 code 353) 시 탭에서 재취득** | 호출당 탭 2초가 사라진다. `ct0`는 CSRF 토큰이라 브라우저 안의 HttpOnly `auth_token` 없이는 아무것도 인증하지 못한다는 것이 threads의 "토큰은 메모리에만" 관례와 갈리는 이유다. |
| D7 | **txid는 모든 오퍼레이션에 붙이고, 생성 실패 시 게이트 없는 오퍼레이션만 계속** | 실제 브라우저와 같은 모양. 404 빈 본문을 받은 오퍼레이션은 오버라이드 레지스트리에 `gated:true`로 학습한다. |
| D8 | **Claude 헤드리스 e2e 미실행** | codex가 SKILL.md·`--help`·실제 출력만으로 시나리오를 수행하는 사용성 검토와 `pytest -m live`(누적 30요청 가드)로 대체. |
| D9 | 본문·`--help`·주석은 영어, description 트리거에 한국어 표현 포함 | 스펙·커밋·PR은 한국어. |
| D10 | **스킬은 완결적** | facebook·reddit·threads 모듈을 import하지 않고 복사한다. `tests/twitter/` 아래에 스킬별 테스트. |
| D11 | 배포는 레포 `.claude/skills/twitter`가 원본, `~/.claude/skills/twitter` 심볼릭 링크 | 형제와 같은 관례. 스킬 이름은 `twitter`(성진 지정), 본문은 X로 부른다. |
| D12 | SKILL.md는 ultra-search처럼 **헤딩 위계가 있는 구조** | 골격은 아래 절. 길이는 완료 기준이 아니다. 옛 `.tmp/Agentic X/.claude/skills/x/SKILL.md`의 원리(리포스트 author·좋아요한 사람 부재·edge는 관측·Top은 순위) 중 Aside 전제와 무관한 것을 살린다. |

## 실측 사실 장부

아래는 이 세션에서 `aside --account u0 repl`로 직접 확인한 것이다. 구현 세션은 재실측 없이 이 값으로 시작한다. 단, query id·feature 플래그·txid 재료는 스냅샷이며 `refresh`가 갱신 수단이다.

### 접근·세션·계약

- **F1** Aside `u0`는 X에 `@radamshi99`(`rest_id 1818125492823986176`, 글 2개)로 로그인돼 있다. `Viewer` 오퍼레이션이 이 계정을 돌려주고, 홈 HTML 응답의 set-cookie `twid=u%3D<id>`에도 같은 id가 실린다.
- **F2 GraphQL 최소 계약.** `https://x.com/i/api/graphql/<queryId>/<Operation>`. GET은 쿼리 문자열 `variables=<JSON>&features=<JSON>[&fieldToggles=<JSON>]`, POST(`HomeTimeline`·`HomeLatestTimeline`)는 JSON 본문 `{variables, features, queryId[, fieldToggles]}`. 헤더는 `authorization: Bearer <공개 bearer>`(스냅샷에 있음, 계정 무관), `x-csrf-token: <ct0>`, `x-twitter-auth-type: OAuth2Session`, `x-twitter-active-user: yes`, `content-type: application/json`, `origin`·`referer: https://x.com`, 브라우저 `user-agent`. 쿠키는 Aside `fetch`가 항상 싣는다. **feature 플래그는 2026-07 캡처본 39개가 오늘도 통했고**, 그중 2개 값이 HTML의 현재 값과 달랐다(`responsive_web_profile_redirect_enabled` false→true, `responsive_web_grok_analyze_post_followups_enabled` true→false). 스냅샷은 HTML 값을 실었다(A1).
- **F3 `ct0`.** 홈 HTML을 `fetch`로 받아도 set-cookie에는 `guest_id*`·`twid`·`lang`·`__cf_bm`만 오고 `ct0`는 없다. `openTab` 뒤 `page.evaluate(() => document.cookie)`로만 읽힌다(`auth_token`은 HttpOnly라 안 보이고 안 보여야 한다). 탭은 `https://x.com/robots.txt`가 1.8초, `/manifest.json` 1.6초, `/home` 7.7초. 세션 내 3회 읽기(약 40분 간격)에서 값이 같았다. **잘못된 `x-csrf-token`은 403 `{"errors":[{"code":353,"message":"This request requires a matching csrf cookie and header."}]}`와 set-cookie `ct0=<새 값>`을 주지만, 브라우저의 쿠키는 바뀌지 않고 기존 `ct0`도 계속 200이다**(Aside `fetch`의 set-cookie는 브라우저 저장소에 쓰이지 않는다). 즉 캐시한 `ct0`는 안전하고, set-cookie로 `ct0`를 얻는 "탭 없는" 편법은 통하지 않는다.
- **F4 txid.** `SearchTimeline`(모든 product)·`Followers`·`UserTweetsAndReplies`는 헤더 없이 **404 본문 0바이트**, 옛 `transaction.py`가 만든 `x-client-transaction-id`로 **200**. 재료는 홈 HTML(295KB, 내비게이션 헤더로 GET)의 `<meta name="twitter-site-verification">`(base64 48바이트), `loading-x-anim-0..3` SVG 4개(각 path 2개), `,<n>:"ondemand.s"` 청크 번호와 `,<n>:"<hash>"` → `https://abs.twimg.com/responsive-web/client-web/ondemand.s.<hash>a.js`(18KB, 인덱스 4개 `[12, 4, 40, 27]`). 애니메이션 키는 재료가 같으면 같다(프로세스 간 캐시 가능). 게이트 없는 오퍼레이션(`UserTweets`)에 txid를 붙여도 응답이 같았다(D7의 근거). 옛 코드의 주석대로 **id는 요청마다 새로 만들고 재사용하지 않는다**(경로가 서명에 들어간다).
- **F5 query id 채굴은 탭 없이, 계정 예산 없이 된다.** `https://x.com/` HTML(익명 헤더로도 같은 296KB)에서 `main.<hash>.js` URL과 웹팩 청크 지도(`.u=e=>` 뒤 중괄호 두 덩이)를 읽고, main.js(67개) + 청크 **1,088개**를 Aside `fetch` 병렬 16으로 **20.7초**에 훑어 `queryId:"…",operationName:"…",operationType:"query"` 레코드 **194개**를 얻었다(실패 1). `Retweeters`·`Favoriters`·`HomeTimeline`·`Bookmarks`·`ListLatestTweetsTimeline`·`CommunityTweetsTimeline`은 main.js에 없고 지연 청크에 있다. 로컬 Python의 직접 HTTPS는 이 머신에서 인증서 오류(`CERTIFICATE_VERIFY_FAILED`)를 내므로 CDN도 Aside `fetch`로 받는다.
- **F6 feature 플래그는 HTML에 있다.** 홈 HTML에 `"<flag>":{"value":true|false}` 형태의 스위치가 **2,700개** 있고 스냅샷 39개 중 38개가 거기서 찾힌다(1개 `responsive_web_enhance_cards_enabled`는 없음, false 유지). `refresh`는 이 값으로 features 지도를 다시 만든다. X가 새 필수 플래그를 요구하면 400 `The following features cannot be null: a, b`로 이름을 알려준다(옛 코드 관측, 이번엔 미유발, A2).
- **F7 레이트리밋 헤더.** 모든 응답에 `x-rate-limit-limit`·`remaining`·`reset`(epoch 초)이 있고 창은 **15분**(`reset - now`가 415~895초로 관측). 버킷은 **query id 단위**다: 프로필 150, `Viewer` 100, `UserTweets`·`SearchTimeline`(product 무관 공유)·`Followers`·`UserRepliesTimeline`·`UserHighlightsTweets`·`UsersByScreenNames`·`CommunityAboutTimeline`·커뮤니티 검색 50, `TweetDetail` 150, 홈·팔로잉·리트위터·북마크·좋아요·미디어·리스트·커뮤니티·탐색 500. 게이트 404도 버킷을 1 깎는다. 429는 유발하지 않았다(A3).
- **F8 REPL 제약.** facebook F8·threads F6과 같다(120초, `console.log` 한 줄 12MB, `URL`·`URLSearchParams`·`require` 없음 → 쿼리 문자열은 `encodeURIComponent`로 직접 조립). `fetch`는 `credentials`를 무시하고 항상 쿠키를 싣는다. `r.headers.getSetCookie()`는 된다. 샌드박스 `fs`는 세션 디렉터리(`~/.aside/u/0/sessions/<id>/`)에만 쓸 수 있어 본문은 stdout 봉투로 받는다(최대 관측 970KB, 리스트 타임라인). `aside repl` 프로세스 스폰은 0.3초. 탭을 여는 호출은 한 번에 하나만(memory `aside-repl-capture-limits`).
- **F9 오류·부재 형태.** 없는 핸들 `UserByScreenName` → 200 `{"data":{}}`. `UsersByScreenNames`의 미해결 핸들 → `result` 없는 원소. 없는 트윗 `TweetDetail` → 200, focal 항목의 `tweet_results: {}`(957바이트). `UserByRestId` → Cloudflare **403 HTML**(핸들로만 조회). `ListByRestId` → 200 데이터와 함께 `errors[{code:214, DecodeException}]`가 실려도 `name`·`member_count` 등은 온다(오류 동반 데이터 수용). `GlobalCommunitiesLatestPostSearchTimeline`에 `searchQuery`를 주면 422 `GRAPHQL_VALIDATION_FAILED "must be defined" path ["variable","rawQuery"]`(변수 이름 오류의 표식). 로그아웃·정지·잠금 형태는 유발 못 했다(옛 `client.py`: 200 + `errors[].code == 32` "Could not authenticate you"가 로그아웃, 401도 있음; A4).

### 오퍼레이션 카탈로그 (2026-09-05 스냅샷, 회전함)

query id·변수 템플릿·봉투 루트·게이트·버킷은 끝의 JSON 블록이 진실이다. 아래는 사람의 동작과 응답 모양이다.

| 사람의 동작 | 오퍼레이션 | 결과 형태(실측) |
|---|---|---|
| 홈 For you | `HomeTimeline`(POST) | 60여 트윗 + `promoted-*` 7~9 + who-to-follow 모듈 1; Bottom 커서 |
| 홈 Following | `HomeLatestTimeline`(POST) | 61건, 2페이지 28건 중복 1 |
| 프로필 카드 | `UserByScreenName` | `data.user.result` 사용자 노드(F10) |
| 여러 카드 한 번에 | `UsersByScreenNames` | `data.users[].result`, 미해결은 빈 원소 |
| 프로필 글 | `UserTweets` | 20 + 고정글 1(`TimelinePinEntry`), 2페이지에서 고정글이 다시 온다(중복 1) |
| 프로필 답글 탭 | `UserTweetsAndReplies`(txid) | 글·답글 섞임 26건(답글 5); 대체: `UserRepliesTimeline`(답글만 40건, txid 불필요) |
| 미디어·하이라이트·아티클 탭 | `UserMedia`·`UserHighlightsTweets`·`UserArticlesTweets` | 11·20·0(커서만) |
| 글 열기 | `TweetDetail` | focal 1 + `conversationthread-*` 모듈 40(모듈당 1~n 트윗) + Bottom 커서; 2페이지 40 모듈 중복 1, focal 없음. `rankingMode: Recency` → 26건 최신순(관련순과 겹침 1). 답글을 focal로 열면 **부모 글이 먼저**(`tweet-<parent>`, `tweet-<focal>`, 이어서 그 답글의 답글) |
| 여러 글 한 번에 | `TweetResultsByRestIds` | `data.tweetResult[].result` 5/5 |
| 검색 | `SearchTimeline`(txid) product `Latest`·`Top`·`People`·`Media` | 20건, 2페이지 중복 0. `People`은 같은 루트에 `user-*` 항목. **검색 결과의 `quoted_status_result`는 `{}`** — 인용 원문은 `legacy.quoted_status_id_str`로만 안다 |
| 인용 목록 | `SearchTimeline` `rawQuery: quoted_tweet_id:<id>` | 20건, 전부 `legacy.quoted_status_id_str == <id>` |
| 팔로잉·팔로워 | `Following`·`Followers`(txid) | `count:20`에 70명, 2페이지 49명 중복 0 |
| 인증·아는 팔로워 | `BlueVerifiedFollowers`·`FollowersYouKnow` | 20·3명, txid 불필요 |
| 리포스트한 사람 | `Retweeters` | 20명 + 커서 |
| 좋아요한 사람 | `Favoriters` | `TimelineTerminateTimeline`만 → 명령 없음 |
| 내 북마크·좋아요 | `Bookmarks`·`Likes(userId=viewer)` | 북마크 0건(`instructions: []`, A5)·좋아요 4건 |
| 리스트 | `ListLatestTweetsTimeline`·`ListMembers`·`ListByRestId` | 81건 970KB·20명·정보(`name`, `description`, `member_count 37`, `subscriber_count`, `mode`) |
| 트렌드 | `ExplorePage` → `timelines[]{id: for_you\|trending\|news\|sports\|entertainment, timeline.id}` → `GenericTimelineById(timelineId)` | trending 62개 `TimelineTrend`(`name`, `trend_metadata.domain_context` "Trending in South Korea", `meta_description` "Promoted by …", `promoted_metadata`) |
| 커뮤니티 | `CommunityTweetsTimeline(Relevance\|Recency)`·`CommunityMediaTimeline`·`CommunityByRestId`·`CommunityAboutTimeline`·`CommunitiesExploreTimeline`·`GlobalCommunitiesLatestPostSearchTimeline(rawQuery)` | 19+고정·28·35·정보(`name`, `member_count`, `join_policy`, `is_nsfw`, `role`, `rules`)·moderators+members 모듈·탐색 20(`socialContext.landingUrl` `/i/communities/<id>`)·검색 33 |

- **F10 사용자 노드가 바뀌었다.** `legacy`가 **비었고** 값이 갈라졌다: `core{name, screen_name, created_at}`, `relationship_counts{followers, following}`, `tweet_counts{tweets, media_tweets}`, `action_counts{favorites_count}`, `profile_bio{description, entities}`, `website{url}`, `location{location}`, `privacy{protected}`, `verification{verified, verified_type}`, `is_blue_verified`, `avatar{image_url}`, `banner`, `relationship_perspectives{following, followed_by, blocking, muting}`, `pinned_items{tweet_ids_str}`, `affiliates_highlighted_label`, `professional`, `rest_id`, `follow_request_sent`. 옛 `build_user`(`legacy.followers_count`)는 None을 낸다 → `_entities.build_user`를 이 지도로 새로 쓴다.
- **F11 트윗 노드는 그대로다.** `rest_id`, `core.user_results.result`(사용자 노드), `legacy{full_text, created_at, conversation_id_str, in_reply_to_status_id_str, in_reply_to_screen_name, reply_count, retweet_count, quote_count, favorite_count, bookmark_count, lang, entities, extended_entities.media, quoted_status_id_str, retweeted_status_result, is_quote_status}`, `note_tweet.note_tweet_results.result.text`(장문, 홈 61건 중 28건), `quoted_status_result`(홈에서는 채워짐), `views{count, state}`, `source`, `__typename: TweetWithVisibilityResults`(홈 61건 중 8건; `tweet` 안에 본체, `limitedActionResults.limited_actions[].action == "Reply"` = 답글 제한). 옛 `model.build_tweet`의 규칙(리포스트 본문은 원글에서·note_tweet 우선·visibility 래퍼 재귀)이 그대로 유효하다. 미디어는 `photo`·`video`·`animated_gif`.
- **F12 봉투 규칙.** 타임라인은 `instructions[]`의 `TimelineAddEntries`·`TimelinePinEntry`(단수 `entry`)·`TimelineAddToModule`(`moduleItems`)·`TimelineClearCache`(무시)·`TimelineTerminateTimeline`(`terminated` 표식; `Favoriters`는 이것만 온다). 항목은 `content.itemContent.tweet_results.result`(item) 또는 `content.items[].item.itemContent`(module). **사용자도 모듈 안에 올 수 있다**: `CommunityAboutTimeline`은 `communityModerators-*`·`communityMembers-*` 모듈 안 `user_results`이고, 홈·탐색의 `who-to-follow-*`도 같은 형태다(옛 `walk_user_instructions`는 직접 `user-*` 항목만 읽어 이 응답을 빈 목록으로 본다 → `_walk`가 모듈 항목과 모듈 id를 함께 돌려주고 `_entities`가 역할을 붙인다). `promoted-*`·`promotedTweet-*` 접두어는 광고. 커서는 `content.cursorType == "Bottom"`(`Top`도 옴). **EOF는 커서 부재 또는 같은 커서**이고, 사용자 목록은 빈 페이지 3연속을 `empty_pages`로 끝낸다(옛 `retrieve.py`, `@X`의 팔로잉이 새 커서를 무한히 주던 관측). `TweetDetail` 모듈 안의 "답글 더 보기" 커서(`itemType: TimelineTimelineCursor`, `cursorType: ShowMore*`)는 이 표본에서 0개였다(A6). `_thread`가 부모 체인·focal·답글 모듈을 구분하려면 워커가 `entry_id`·모듈 경계·모듈 안 순서를 버리지 않아야 한다(옛 `walk_instructions`는 `(tweet, pinned)`로 평탄화했다).

## 설계

### 실행 모델

```
twitter.py <cmd> ──▶ Python(stdlib) ──spawn──▶ aside --account u0 repl <graphql.js | page.js | cookie.js> ──▶ Aside fetch / tab ──▶ x.com · abs.twimg.com
      ▲                                                                       │
      └── {status, url, body, ratelimit:{limit,remaining,reset}} ◀────────────┘
```

- **한 `aside repl` 호출 = 한 요청.** facebook·reddit·threads와 같은 이유(스폰 0.3초, 페이싱은 Python이 소유). `# 성진: 요청당 스폰이 병목으로 측정되면 한 호출에 N요청 묶음` 주석을 같은 자리에 남긴다. 예외는 `refresh`의 번들 스윕 한 번(청크 1,088개를 한 호출 안에서 병렬 fetch, CDN이라 계정 예산 무관)과 `cookie.js`의 탭 1개다.
- **`graphql.js`**: `ARGS {op, query_id, method, variables, features, field_toggles?, ct0, txid?}` → F2 계약 요청 하나 → `{status, url, body, ratelimit}`. 헤더 세트는 JS가 고정하고 Python은 값만 준다. 12MB 조각 전송 경로를 facebook `graphql.js`에서 옮긴다. **`page.js`**: `ARGS {url}`(호스트 허용 목록 `x.com`·`abs.twimg.com`만) → 내비게이션 헤더 GET, `redirect: "manual"`. **`bundles.js`**: `ARGS {html_url}` → HTML + main.js + 청크 지도 → 병렬 16 스윕 → `{operations:{name: query_id}, features:{flag: bool}, txid_ingredients:{verification, frames, ondemand_url, ondemand_js}}` 한 봉투(20~30초, 120초 안). **`cookie.js`**: `ARGS {}` → `openTab('https://x.com/robots.txt')` → `document.cookie`의 `ct0`·`twid`만 → `closeTab`을 `finally`에서.
- **세션 상태 `~/.cache/twitter-skill/session.json`(0600)**: `{ct0, viewer_id, viewer_handle, read_at}`. `ct0`가 없거나 403 code 353이면 `cookie.js`로 한 번 재취득해 같은 요청을 한 번 재시도하고, 그래도 353이면 exit 4. `viewer_id`는 `cookie.js`가 `ct0`와 함께 읽는 `twid` 쿠키(`u%3D<id>`)에서, `viewer_handle`은 `doctor`의 `Viewer` 1요청에서 채운다. **계정 전환 방어**: `cookie.js`를 실행할 때마다 `twid`를 비교해 `viewer_id`가 바뀌면 커서 파일 전부를 지우고 헤더에 `viewer changed`를 적는다. 커서 파일과 `--out` 파일 헤더 레코드는 `viewer_id`를 담고, 이어읽기·이어받기는 현재 세션의 `viewer_id`와 다르면 exit 2(`fix`: 새로 시작). `me`·`home`은 `session.json`의 `read_at`이 24시간을 넘으면 요청 전에 `cookie.js`를 다시 실행한다(탭 1). `Likes`는 `viewer_id`를 쓴다.
- **txid `_txid.py`**: 옛 `transaction.py`의 수학을 **그대로**(라이선스 주석 포함) 이식하고 `httpx`·클래스 상태만 뺀다. 재료(`key_bytes`, `animation_key`, `indices`, `fetched_at`, `ondemand_url`)는 `~/.cache/twitter-skill/txid.json`에 캐시한다(비밀 아님). 없거나 24시간이 지났거나 게이트 오퍼레이션이 txid를 붙였는데도 404를 냈으면 `page.js` 2회(홈 HTML·ondemand.s)로 다시 만든다. `generate(method, path)`는 요청마다 호출한다. 재료 추출 실패는 `TwitterError(6, error="transaction_unavailable")`이고 메시지에 **어느 재료가 없는지**를 적는다.
- **판정은 Python 한 곳(`_transport.classify`)에서, 오퍼레이션별 기대 봉투를 가지고, 이 순서로.** 문구 검색은 정규화한 오류 객체(`errors[]`의 `code`·`message`) 안에서만 한다.
  1. **계정 차단(최우선, 무만료)**: 403인데 본문이 HTML(`<!DOCTYPE`·`cf-`) → `challenge`; 정규화 오류 코드 `64`(suspended)·`326`(locked) → `account_locked`. 둘 다 exit 5, 전역 차단 파일, `fix`: Aside에서 x.com을 열어 확인 뒤 `doctor --unblock`. 이후의 429·만료 처리가 이 상태를 덮지 못한다(threads `set_blocked`의 checkpoint 규칙 이식, P1 테스트).
  2. **요청 제한**: 429 → **그 query id의 버킷만** `reset`까지 잠근다(전역 차단 파일에 쓰지 않는다). 결과 없이 첫 요청에서 만나면 exit 5 `error=rate_limit`(`fix`에 reset 시각), 헤더가 없으면 15분.
  3. **세션**: 401, 또는 오류 코드 `32`(Could not authenticate) → exit 4. 코드 `353`(csrf) → `ct0` 재취득 1회 후 재시도, 재실패 시 4.
  4. **게이트**: 404 + 본문 0바이트. txid 없이 보냈으면 txid를 붙여 1회 재시도하고 성공 시 오버라이드에 `gated:true` 저장. txid를 붙였는데도 404면 재료를 재생성해 1회 더 시도, 그래도 404면 exit 6 `error=transaction_rejected`(`fix`: run refresh; 게이트 없는 대체 표면을 명령 도움말이 안내).
  5. **회전과 계약 이탈은 다르다.** 400에 `The following features cannot be null: a, b` → exit 6 `error=operation_rotated`, 누락 이름을 `~/.cache/twitter-skill/registry.json`의 `missing_features`에 적고 `fix`는 `refresh`(F6·A2, `refresh`가 그 이름을 HTML 스위치에서 찾아 넣는다). `errors[]`만 있고 `data`가 없는 200/404 JSON도 `operation_rotated`(query id 회전). 반면 422 `GRAPHQL_VALIDATION_FAILED`·`Variable … must be defined`·`… has coerced Null value`는 **변수 템플릿이 바뀐 것**이라 `refresh`로 못 고친다 → exit 6 `error=contract_drift`, `fix`: "X changed this operation's variables; update registry.json vars for <op> (code change)". 5xx·비JSON·잘린 JSON → exit 6 `error=transient`(차단 없음).
  6. **대상 없음·닫힘(exit 9)은 명시적 증거에만**: `UserByScreenName`의 `data:{}`; 사용자 노드 `__typename == "UserUnavailable"`; `TweetDetail` focal의 `tweet_results:{}` 또는 `__typename == "TweetTombstone"`; `privacy.protected == true`이고 `relationship_perspectives.following == false`인 계정의 타임라인이 빈 경우 `reason=protected`(A7).
  7. **봉투(exit 6 `envelope_drift`)**: 레지스트리의 `root` 경로에 `instructions[]`(또는 단일 노드)가 없음. `errors`가 데이터와 함께 오면(`ListByRestId` 214) 데이터를 쓰고 헤더에 `warnings=1`을 적는다.
  8. **정직한 0건(exit 7)**: 루트는 있는데 항목이 없고 커서도 없음(또는 `TimelineTerminateTimeline`만). 항목 0 + 새 커서는 진행(예산 안에서), 사용자 목록은 3연속에서 `empty_pages`(exit 8).
- **레지스트리는 데이터다.** `scripts/registry.json`에 스냅샷 33항목을 `{query_id, method, gated, rate, kind, root, vars, fieldToggles?, verified}`로, 공통 `features`와 `bearer`를 함께 싣는다. `refresh`는 `~/.cache/twitter-skill/registry.json`에 `{operations:{name:{query_id, gated?}}, features, refreshed_at}` 오버라이드를 쓰고, 로드 순서는 오버라이드 → 번들이다. 오버라이드는 **query id·features·gated만** 바꿀 수 있고 변수 템플릿·루트·kind는 번들이 소유한다(읽기 표면이 캐시로 늘어나지 않는다).
- **`refresh`는 탭 없이 한 호출이다.** `bundles.js` 1회(HTML → main.js → 청크 지도 → 1,088개 병렬 스윕, `operationType == "query"`만) → 33종 중 찾은 것의 id를 갱신하고 **못 찾은 것은 현재 유효 값(오버라이드가 있으면 오버라이드)을 유지**하며 이름을 `missing`으로 보고 → HTML 스위치 2,700개에서 features 39개 + `missing_features`에 적힌 이름을 다시 만들고(HTML에 없는 플래그는 현재 값 유지, `missing_features`의 이름이 HTML에도 없으면 `false`로 넣고 보고) → txid 재료를 같은 HTML에서 갱신 → **검증 재생 2회**(`UserByScreenName @X` 1 + `SearchTimeline "x" Latest count 1` 1: 게이트·txid·features를 한 번에 확인). 검증이 실패하면 아무것도 저장하지 않는다. 출력은 `verified [UserByScreenName, SearchTimeline] · discovered 31 (changed: op(old→new)…) · missing [..] · features +a -b · txid ok`로, 재생으로 확인한 것과 발견만 한 것을 구분한다. 청크 스윕은 계정 예산을 쓰지 않는다.

### 예산 계약 (`_budget.py`)

- **파일** `~/.cache/twitter-skill/budget.json`: `{buckets:{<query_id>:{limit, remaining, reset_at, observed_at}}, requests:[epoch…], block:{reason, expires_at|null}}`. 헤더가 오면 그 오퍼레이션 버킷을 갱신하고, 요청 전에는 `remaining -= 1`을 **예약**한다(reddit과 같은 순서: 파일 재읽기 → 차단 판정 → 버킷 판정 → 페이싱 → 예약 → 요청 → 헤더 반영). 버킷 `remaining ≤ 0`이고 `reset_at`이 남았으면 요청 없이 exit 5 `rate_limit`(`fix`에 reset 시각). `reset_at`이 지나면 폐기.
- **페이싱.** 요청 간 하한 1.0초(+0~0.5초 지터), 플래그로 못 낮춘다. 버킷 `remaining`이 `limit`의 20% 아래면 `(reset_at - now) / remaining`초로 늘린다. `# 성진: 1초 하한·20% 감속은 실계정 보호용 추정치, 잠금이 관측되면 낮춘다`.
- **호출당 상한과 표시 목표는 별개다.** 기본 10회, 명시적 `--limit`·`--since`·`--out`이 있으면 40회(exit 8 `budget`). 10분 창 합산 상한 200회(모든 CLI 호출 공유; 버킷 합이 더 크지만 계정 단위 보호; 초과는 exit 5 `error=window`, 창이 비는 시각을 `fix`에). `ct0` 탭·`refresh`의 CDN 스윕·`page.js` HTML GET은 X API 버킷을 깎지 않지만 창 합산에는 1로 센다.
- **책임 분리.** query id 제한은 `buckets`(오퍼레이션별, `reset_at` 자동 해제), 10분 창은 계정 전체(자동 해제), `block.reason ∈ {challenge, account_locked}`만 무만료 전역 차단이며 사람이 Aside에서 x.com을 열어 확인한 뒤 `doctor --unblock`. 요청 주기는 `account_lock`(fcntl) 안에서 돈다(threads `_blocked` 이식, `rate_limit` reason은 두지 않는다).
- 헤더에 `budget <op> 47 of 50 (resets in 8m) · window 23/200`처럼 **그 호출이 쓴 오퍼레이션의 버킷**을 적는다. 검색 버킷 50은 product 4종이 공유한다는 것을 SKILL.md가 말한다.

### 식별자 계약 (`_target.py`)

- identity는 트윗 `rest_id`(숫자)와 사용자 `rest_id`(숫자), 리스트 id, 커뮤니티 id. 표시 핸들은 `@screen_name`과 정식 URL `https://x.com/<handle>/status/<id>`.
- `Target(kind ∈ {user, post, list, community, query, me}, handle, user_id, tweet_id, list_id, community_id)`. 옛 `auth.py` 303~479행의 순수 함수(`normalize_identifier`·`normalize_tweet_identifier`·`normalize_list_identifier`·`_check_url_host`·`_normalize_url`, `_HANDLE_RE`·`_TWEET_ID_RE`)를 이식하고 형태를 추가한다: `@name`, `name`, `x.com/<name>`, `twitter.com/<name>`, `/<name>/status/<id>[/photo/n|/video/n|/analytics]`, `/i/web/status/<id>`, `/i/lists/<id>`, `/i/communities/<id>`, `mobile.`·`www.`·`m.` 호스트, 트레일링 슬래시·쿼리(`?s=20`)·프래그먼트. **숫자만 있는 대상은 명령이 정한다**: `post 123`은 트윗 id, `list 123`은 리스트 id, `user 123`은 거절(X에 id→프로필 경로가 없다, F9 `UserByRestId` 403)하고 `fix`에 "핸들을 쓰라"고 적는다. `/home`·`/i/…`(리스트·커뮤니티 제외)·`/messages`·`/notifications`·`/settings`는 exit 2.
- **핸들 → user id는 `UserByScreenName` 1요청**이고 `user`·`graph`가 먼저 쓴다(그 응답의 카드가 헤더 한 줄로 같이 나가므로 낭비가 아니다). 커서 파일에 `user_id`를 저장해 이어읽기는 재조회하지 않는다.

### 명령 표면 (`twitter.py --help`가 진실, 여기는 설계 의도)

사람이 X에서 하는 동작을 X의 명사로 만든다. 모든 읽기 명령은 같은 출력 옵션(`--json`, `--chars`, `--out`, `--limit`, `--after`)을 공유하되 적용 여부는 아래 기본값 표가 정한다. `--out FILE`은 형제와 같은 로컬 저장이다: **받은 페이지 전체를 저장**하고(표시 수 `shown`과 저장 수 `stored`를 헤더에 따로 적는다) 페이지 단위로 NDJSON을 커밋해 중단 뒤 같은 명령으로 이어받으며, 글은 글 한 줄 뒤 답글 평탄 레코드(`in_reply_to_id`·`depth`·`module` 포함). 파일의 완료 마커는 `exhausted`·`window_reached`·`not_paginable`·`terminated`가 완료, `limit_reached`·`budget`·`empty_pages`·`blocked`·`query_failure`가 미완료다.

| 명령 | 사람의 동작 | 받는 대상 | 요청 |
|---|---|---|---|
| `home [--feed foryou\|following]` | X를 연다 | 없음 | `HomeTimeline`/`HomeLatestTimeline` 페이지당 1(60건, 광고 제외) |
| `user <@name\|url> [--tab posts\|replies\|media\|highlights\|articles] [--since --until]` | 프로필의 탭을 본다 | user | `UserByScreenName` 1(카드 헤더 + id) + 탭 오퍼레이션 페이지당 1. `replies`는 X의 답글 탭(`UserTweetsAndReplies`, txid). txid를 못 만들면 자동 대체하지 않고 exit 6 `transaction_unavailable`의 `fix`가 `--tab replies-only`(`UserRepliesTimeline`, txid 불필요)를 가리킨다. 그 탭은 실측상 40건 중 답글 23건으로 글도 섞이므로 필터 없이 그대로 보여주고 헤더·JSON·커서에 `operation=UserRepliesTimeline`을 적는다 |
| `about <@name\|url> [<@name>…]` | 프로필 카드를 본다 | user(여럿) | 1개면 `UserByScreenName`, 2개 이상이면 `UsersByScreenNames` 1요청(미해결 핸들은 `unresolved:` 줄로) |
| `post <url\|id> [--sort top\|recent] [--after n]` | 글을 연다: 부모 체인 + 본문 + 답글 배치 | post | `TweetDetail` 1, `--after`로 Bottom 커서 계속. 여러 id를 주면 `TweetResultsByRestIds` 1(스레드 없이 글만) |
| `quotes <post>` / `reposts <post>` | 인용·리포스트한 사람 | post | `SearchTimeline quoted_tweet_id:`(txid) / `Retweeters` |
| `search <text> [--type posts\|users\|media] [--sort top\|latest] [--in communities]` | 검색창 | 자유 텍스트 | `SearchTimeline`(txid) / `--in communities`는 **모든 커뮤니티의 글을 대상으로 한 전역 검색**(`GlobalCommunitiesLatestPostSearchTimeline`, 특정 커뮤니티로 좁히는 변수는 미실측). X 검색 연산자(`from:`, `since:`, `min_faves:`…)는 그대로 통과 |
| `graph <@name\|url> following\|followers\|verified\|known` | 팔로워 수를 누른다 | user | `UserByScreenName` 1 + `Following`/`Followers`(txid)/`BlueVerifiedFollowers`/`FollowersYouKnow` 페이지당 1(70명) |
| `me bookmarks\|likes` | 내 북마크·좋아요 | 없음 | `Bookmarks`/`Likes(viewer_id)` 페이지당 1 |
| `list <url\|id> [--tab posts\|members\|about]` | 리스트를 연다 | list | `ListLatestTweetsTimeline`/`ListMembers`/`ListByRestId` |
| `trends [--tab trending\|foryou\|news\|sports\|entertainment]` | 탐색 탭 | 없음 | `ExplorePage` 1 → `foryou`는 `body.initialTimeline.timeline.timeline.instructions`에서 끝, 그 밖의 탭은 `body.timelines[].timeline.id`로 `GenericTimelineById` 1. 항목은 `TimelineTrend`(직접·모듈 안 모두)와 `TimelineEventSummary`(`[event]`)만 추출하고 트윗·who-to-follow 모듈은 센 뒤 `other items n`으로 헤더에 적는다(인식 항목 0이어도 봉투가 정상이면 exit 7이 아니라 0건 + `other items`) |
| `community <url\|id> [--tab posts\|media\|about] [--sort top\|recent]` / `communities` | 커뮤니티를 연다 / 둘러본다 | community | `CommunityByRestId`(헤더) + `CommunityTweetsTimeline`/`CommunityMediaTimeline`/`CommunityAboutTimeline` / `CommunitiesExploreTimeline` |
| `doctor [--unblock]` | 준비됐나 | — | `ct0` 없으면 탭 1 + `Viewer` 1: aside·로그인 핸들·차단·버킷·레지스트리 나이·txid 재료 나이 한 줄 |
| `refresh` | 깨졌을 때 고치기 | — | `bundles.js` 1 + 검증 2 |
| `schema` | 객체 필드 설명 | — | Tweet·User·Media·List·Community·Trend를 `to_dict()`에서 유도. 요청 0회 |

**`post`의 동작.** `TweetDetail` 1회로 focal 앞의 항목은 `[parent]` 체인, focal은 `text[full]`, 뒤의 `conversationthread-*` 모듈은 답글(모듈 안 두 번째 이후 트윗은 그 답글의 답글로 들여쓰기; 관계는 `in_reply_to_status_id_str`로 판정하고, 부모가 표시 목록에 없으면 `reply-to=<id>`로 id만 적는다). `--sort recent`는 `rankingMode: Recency`. `--after`는 Bottom 커서(2페이지에 focal 없음, 중복 1은 pk로 제거). **완전성 수치는 서로 다른 수를 섞지 않는다**: `reported`(focal의 `reply_count`, 직접 답글 수), `direct_shown`(focal에 직접 단 답글 중 표시), `nested_shown`(그 아래 표시), `hidden_branches`(모듈 안 `ShowMore*` 커서 수, 이번 범위에서는 따라가지 않음, A6). 헤더는 `post · @elonmusk/2095364595326263447 · sort=top · replies: 36 direct shown of 5,261 reported · +0 nested · hidden branches 0 · fetched 0.26MB · budget TweetDetail 147 of 150`. `--json`·`--out`에도 같은 네 필드. `TweetWithVisibilityResults`는 `[limited: replies]` 라벨.

**`user`의 동작.** 카드 한 줄(`@elonmusk (Elon Musk ✓blue · affiliate @X) · followers 241.6M · following 1,403 · posts 108,163 · joined 2009-06 · bio: "…"`) 뒤 탭 항목. 고정글은 `[pinned]`로 첫 줄, 2페이지에서 다시 오면 pk로 제거. **리포스트 계약은 옛 `build_tweet`과 같다**: 바깥 `Tweet`의 `id`·`author`·`created_at`은 리포스트 행위(퍼간 사람·퍼간 시각)이고, 본문·미디어·통계·URL은 `retweeted_tweet`(원글)에서 표시한다. 텍스트 줄은 `[t2] @a · <시각> · repost of @b: "<원글 본문>" · likes=<원글> … · url: "<원글 URL>"`.

**인용 계약.** `Tweet`에 `quoted_tweet_id`(`legacy.quoted_status_id_str`)를 독립 필드로 둔다. `quoted_status_result`가 채워지면 `quoting @z: "…" (url)`, 비어 있으면(검색 결과, F11) `quoting <url> (open with post)`로 다음 홉 URL만 싣는다. `--json`에는 둘 다.

**날짜 창.** X 검색은 `since:`·`until:` 연산자가 서버 필터라 `search`는 그대로 통과시킨다. 타임라인의 `--since/--until`은 클라이언트 필터이고 최신순 표면(프로필 posts·replies·media, 리스트, 홈 Following)에서만 받는다. 종료 판단은 고정글 제외 `created_at`이며 단조성이 실측된 표면(프로필 posts)에서만 `window_reached`를 주장한다(A8).

**`--after <n>` 이어읽기.** facebook과 같은 번호 핸들(`~/.cache/twitter-skill/cursors/<n>.json`)에 커서·**실제 오퍼레이션**(대체 탭 포함)·`user_id`·`rankingMode`·날짜 창·마지막 페이지의 id 집합(중복 제거용)·`viewer_id`·아직 안 보인 꼬리 항목을 담는다. 이어읽기는 **꼬리를 먼저 0요청으로 소진**하고 표시 목표에 못 미칠 때만 다음 페이지를 요청한다(프로필 재조회 없음). 문맥(명령·대상·탭·정렬·계정)과 충돌하는 인자는 거절한다. `post`·`about`·`list --tab about`·`community --tab about`·`trends`처럼 페이지가 없는 조회는 `--after`를 받지 않는다(exit 2).

### 출력 계약

**기본(텍스트).** facebook·reddit·threads와 같은 규약(한 줄 본문, `⏎`, 따옴표 URL, 헤더 한 줄, 끝줄 `more:`). 본문 정규화(공백 접기·`t.co` 링크를 `entities.urls[].expanded_url`로 치환·미디어 `t.co` 제거·빈 필드 줄 생략)를 `_render._text`가 맡는다.

```
home · feed=following · 8 shown · stopped=limit · fetched 0.6MB · budget HomeLatestTimeline 496 of 500 (resets in 7m) · window 12/200
[t1] @karpathy (Andrej Karpathy ✓blue) · 2026-09-05T16:02+09:00 · likes=1431 reposts=143 replies=172 quotes=12 views=572K
     "…full text, note tweet preferred…"   link: https://example.com/post
     url: "https://x.com/karpathy/status/2096151011616882287"
[t2] @a · … · repost of @b: "…" (url: "…")
[t3] @c · … · [limited: replies] · quoting @d: "…" (url: "…")
     "…"   media: video(1)
more: python3 "/…/twitter.py" home --feed following --after 7
open: `post <url>` · person: `user @karpathy` / `about @karpathy` / `graph @karpathy followers` · who engaged: `reposts <url>` / `quotes <url>`
```

```
post · @elonmusk/2095364595326263447 · sort=top · replies: 36 shown of 5,261 reported · fetched 0.26MB · budget TweetDetail 147 of 150
[t1] @elonmusk (Elon Musk ✓blue) · 2026-09-04T22:10+09:00 · likes=58,748 reposts=5,043 replies=5,261 quotes=851 views=12.4M
     text[full]: "A Storm of Cybercabs"   media: video(1)
     url: "https://x.com/elonmusk/status/2095364595326263447"
[r1] @JAEGARCIA99 · 2026-09-04T22:40+09:00 · likes=88 replies=50
     "…"
     url: "…"
  [r2 reply-to=r1] @elonmusk ✓blue · … · likes=40
     "…"
more: python3 "/…/twitter.py" post 2095364595326263447 --after 12
newest first: `post <url> --sort recent` · who engaged: `reposts <url>` / `quotes <url>` · open a reply: `post <reply url>`
```

- 사용자 카드(`about`·`graph` 항목): `@handle (Name ✓blue|✓gov|✓business) · followers 1.2M · following 400 · posts 10K · private · bio: "…" · url`. 관계는 `follows you`·`you follow`를 `relationship_perspectives`에서.
- 트렌드: `[1] #tag · Trending in South Korea · 12K posts` / `[promoted] …`(광고 트렌드는 라벨하고 기본 표시에서 뺀다). 리스트·커뮤니티 카드: 이름·설명·멤버 수·모드/가입 정책·NSFW.
- **`--json`**: 항상 JSON 문서 하나(`{"ok","results","stop_reason","next","budget","fetched_bytes","warnings"}`). 결과가 하나도 없는 실패는 `{"ok":false,"error","message","fix"}`. **페이지를 받은 뒤의 실패는 부분 결과다**: exit 8, `stop_reason ∈ {blocked, query_failure}`, `results`·`next`(재개 가능하면)·`error`·`message`·`fix`를 함께 싣고 텍스트도 받은 항목을 먼저 출력한 뒤 마지막 줄에 `stopped: <error> · <fix>`를 적는다. exit 4·5·6은 첫 페이지 전에 실패했을 때만이다. `--out`은 성공한 마지막 페이지까지 커밋된 상태로 남는다.
- **명령별 기본값과 허용 옵션**은 `twitter.py`가 표 하나로 갖고 `--help`에 싣는다: `--limit` 기본 10(목록)·`post` 답글 20·`about`은 없음; `--chars` 기본 280(`post`의 focal은 전문); `--sort` 기본 `top`(`post`·`community`)·`latest`(`search`); `--since/--until`은 최신순 표면(`user --tab posts|replies|replies-only|media`, `list --tab posts`, `home --feed following`)만; `--after`는 페이지가 있는 명령만; `--in communities`는 `--type posts`와 `--sort latest`만. 의미 없는 조합은 조용히 무시하지 않고 exit 2.
- **`stop_reason`**: `limit_reached | exhausted | window_reached | budget | blocked | query_failure | empty_pages | not_paginable`(`about`·`ListByRestId`·`CommunityByRestId`·`TweetResultsByRestIds`) `| terminated`(`Favoriters`류 `TimelineTerminateTimeline`).
- **종료 코드**: 0 성공 · 2 잘못된 인자 · 3 aside 불가 · 4 X 로그인 필요·세션 거부(401, code 32, csrf 재취득 실패) · 5 차단(`error ∈ {challenge, account_locked, rate_limit, window}`; 챌린지·잠금은 `doctor --unblock`, 버킷·창 초과는 자동 해제, **재시도 금지**) · 6 `error ∈ {transient, envelope_drift, operation_rotated, contract_drift, transaction_rejected, transaction_unavailable}`로 `fix`가 갈린다 · 7 정직한 0건 · 8 부분 결과(예산·`empty_pages`·페이지 뒤의 차단·실패) · 9 대상 없음·비공개·삭제.

### 디렉터리 구조 (최종)

기능 단위 모듈, 책임 하나, 400줄 이하, 엔트리는 argparse와 디스패치만. 파서·모델·워커 모듈은 transport를 import하지 않는다.

```
Agentic SNS/
├── .claude/
│   ├── harness-spec.md                     # 인벤토리 행 B10(twitter 읽기)·B11(쓰기 declined)·B12(알림·DM declined) 추가
│   ├── plans/harness-creator-principle-curried-taco.md   # 이 파일 (.gitignore 예외 추가)
│   └── skills/twitter/
│       ├── SKILL.md
│       └── scripts/
│           ├── __init__.py
│           ├── twitter.py                  # argparse 배선·공통 옵션(default=None)·명령별 허용 Target·디스패치·종료 코드
│           ├── registry.json               # 스냅샷 33항목 + features 39 + bearer (데이터)
│           ├── _errors.py                  # TwitterError(code, message, fix, error), fix 문구, scrub(ct0·auth_token·cookie·bearer·pbs 서명) (threads 이식)
│           ├── _aside.py                   # aside 스폰, 봉투 검증(status·url·body·ratelimit?) (threads 이식)
│           ├── _blocked.py                 # 차단 파일·account_lock·write_state (threads 이식, reason 3종)
│           ├── _budget.py                  # 오퍼레이션 버킷·10분 창·페이싱·예약·헤더 반영
│           ├── _session.py                 # session.json(ct0·viewer) 읽기/쓰기(0600), cookie.js 호출, twid 파싱
│           ├── _txid.py                    # 옛 transaction.py 수학 이식(라이선스 주석), 재료 추출(HTML·ondemand.js), txid.json 캐시, generate()
│           ├── _registry.py                # registry.json 로드(오버라이드→번들), OpSpec, build_variables, gated 학습 저장
│           ├── _bundles.py                 # bundles.js 결과 → query id 지도·features 재구성·txid 재료; refresh 오케스트레이션과 검증 재생
│           ├── _transport.py               # graphql/page 요청 조립, ct0·txid 주입, classify 8단계, 353·404 재시도, Transport.query(op, vars, expect)
│           ├── _target.py                  # @name·URL·id → Target (옛 auth.py 순수 함수 이식 + 리스트·커뮤니티 URL)
│           ├── _walk.py                    # 순수 봉투 워커 (옛 parse.py 이식, 반환 계약 확장): Entry(node, entry_id, module_id|None, index_in_module, pinned, kind ∈ {tweet,user,trend,event,cursor}) 목록 + Page(bottom_cursor, module_cursors[], terminated, cleared). 광고 제외, 모듈 안 사용자(communityMembers·communityModerators·who-to-follow)와 역할(entry_id 접두어) 보존
│           ├── _listing.py                 # 반복 제어: 커서 EOF 규칙, empty_pages, 클라이언트 창, limit·예산, pending 꼬리, stop_reason (옛 retrieve 규칙, transport import 없음)
│           ├── _models.py                  # Tweet·Media dataclass + build_tweet(리포스트·인용·note·visibility 재귀) (옛 model.py 이식)
│           ├── _entities.py                # User(F10 새 지도)·List·Community·Trend dataclass + 빌더
│           ├── _schema.py                  # to_dict → 필드 설명·JSON Schema
│           ├── _thread.py                  # TweetDetail 항목 → 부모 체인·focal·답글 트리(in_reply_to 기반 들여쓰기)·완전성 수치·rankingMode
│           ├── _render.py                  # 객체 → 밀도 텍스트. 라벨·시간대·chars·본문 정규화(t.co 치환)는 여기만
│           ├── _output.py                  # --json 문서, --out 페이지 커밋·이어받기, CursorStore (facebook 이식)
│           ├── _cmds_browse.py             # home·user·search·me·graph·quotes·reposts (목록 모양)
│           ├── _cmds_post.py               # post·about (단일·스레드 모양)
│           ├── _cmds_places.py             # list·trends·community·communities
│           ├── _cmds_meta.py               # doctor·refresh·schema
│           └── browser/
│               ├── graphql.js              # ARGS {op, query_id, method, variables, features, field_toggles?, ct0, txid?} → 요청 하나 → 봉투(+ratelimit)
│               ├── page.js                 # ARGS {url} (x.com·abs.twimg.com만) → 내비게이션 헤더 GET, manual redirect → 봉투
│               ├── bundles.js              # ARGS {} → HTML·main.js·청크 스윕(병렬 16) → {operations, features, txid_ingredients}
│               └── cookie.js               # ARGS {} → robots.txt 탭 → document.cookie의 ct0·twid → 탭 닫기(finally)
├── tests/
│   └── twitter/
│       ├── __init__.py · conftest.py       # 네임스페이스 로드(threads 방식), TWITTER_ASIDE_BIN → fake_aside, TWITTER_HOME → tmp, live 마커·누적 30요청 가드
│       ├── fake_aside/aside                # 스니펫·오퍼레이션별 캔드 봉투
│       ├── js/test_graphql.js · test_page.js · test_bundles.js · test_cookie.js   # node가 실제 스니펫을 mock fetch/openTab로 실행: 헤더 세트·쿼리 문자열 조립·POST 본문·호스트 허용 목록·청크 지도 파서·탭 finally
│       ├── fixtures/*.ndjson               # 실캡처에서 구조만 유도한 합성 응답(PII 없음): 타임라인(고정·광고·visibility·리포스트·인용·note)·TweetDetail(부모·모듈·커서)·사용자 노드(F10)·검색 People·리스트·트렌드·커뮤니티·오류 봉투(353·404·32·422·214·HTML 403)
│       ├── tools/derive_fixture.py · check_fixtures_pii.py
│       ├── test_cli.py · test_transport.py · test_budget.py · test_session.py · test_txid.py · test_registry.py · test_bundles.py · test_target.py · test_walk.py · test_listing.py · test_models.py · test_entities.py · test_thread.py · test_render.py · test_output.py
│       └── live/test_live.py               # -m live. 실제 Aside. 모양·불변식만
├── .github/workflows/test.yml              # twitter 테스트·JS·ruff·PII 게이트 추가
├── README.md                               # 스킬 색인에 twitter 행
└── .gitignore                              # 이 계획·fixtures 예외
```

### SKILL.md 골격 (D12)

ultra-search처럼 `#` 제목 아래 `##` 절이 있고, 각 절은 "사실 + 결과"만 쓴다. 명령·플래그·종료 코드·스키마·복구 절차는 싣지 않는다(`--help`·`schema`·오류 JSON의 `fix`).

```
---
name: twitter
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/twitter.py" *)
description: Read X (Twitter, x.com) through the user's logged-in Aside browser: the home feed (for you / following), a post with its parent chain and replies, a profile's posts, replies, media, highlights and articles, followers and following, who reposted or quoted a post, search for posts or accounts, trends, lists, communities, and the user's own bookmarks and likes. Use whenever the request is to read or explore something on X or Twitter — 트위터에서, 엑스에서, 이 트윗 답글, 트위터 검색, 트렌드 — including a bare x.com or twitter.com URL with no mention of X. Not for Threads, Facebook, Reddit or other networks, general web pages, news about X the company, or posting, replying, liking, reposting, following, bookmarking.
---

# X through the user's own browser
  한 문단: 브라우저가 로그인된 계정을, CLI가 읽기 전용 질의와 밀도 텍스트를 준다. `$TW` 표기 규칙. `--help`·`schema`·오류의 `fix`가 나머지를 가르친다.

## Every request is the person's account, and X counts by operation
  헤더의 예산 줄은 X가 준 그 오퍼레이션의 15분 버킷이지 계정 전체가 아니다. 검색은 모든 종류가 한 버킷을 나눠 쓰고 프로필 글·팔로워도 작은 버킷이라 "검색을 여러 번"이 가장 비싼 동작이며, 홈·관계망은 넉넉하다(수치는 헤더가 말한다). X는 자동화 계정을 잠그므로 몇 명·몇 글을 볼지 먼저 정한다. 한 페이지가 20~70건이라 표시 수를 줄여도 요청 수는 줄지 않는다.

## Three surfaces run on a reverse-engineered signature
  검색·팔로워·답글 탭은 X 클라이언트가 요청마다 만드는 서명을 도구가 재현한다. 그것이 깨지면 그 셋만 죽고 나머지는 산다. 쿼리 id는 몇 주마다 전부 바뀐다. 두 경우 모두 오류의 `fix`가 복구와 게이트 없는 대체 표면을 가리키므로 본문을 외우지 않는다.

## A repost's author is the reposter, and other things the numbers hide
  리포스트 줄의 앞사람은 퍼간 사람이고 원글 작성자는 `of` 뒤다. 좋아요한 사람 목록은 X가 비워 보내므로 이 도구에 없다(리포스트·인용이 대신 보인다). 검색 결과의 인용은 원글 URL만 오고 본문은 열어야 보인다. `top`은 X의 순위이고 `latest`는 시간순이라 서로 다른 주장이다. 홈은 개인화된 피드이지 X의 표본이 아니다. 답글 제한 글은 라벨이 붙는다. 파란 체크는 유료 구독이고 정부·기업 체크만 X가 준 인증이다.

## @handles and URLs are the next command's arguments
  출력의 `@…`와 `url:`이 곧 인자. 팔로잉은 우정이 아니고 리포스트는 동의가 아니며 팔로워 목록은 그 사람과 무관한 사람들이다. 핸들은 바뀌지만 id는 남으므로 조인은 id로 한다. 숫자 id로 프로필을 열 수는 없다.

## What has actually bitten
  없는 글은 조용히 빈 응답이다. 답글 목록 2페이지에는 본문이 없다. 광고는 지워서 보이는 피드가 X가 보낸 페이지가 아니다. `since:`·`until:`은 검색 연산자로 넣고, 타임라인 날짜 창은 클라이언트 필터라 `window_reached`가 아닌 끝은 창을 다 봤다는 뜻이 아니다. 알림·DM은 열지 않는다.

## Large collections and what the cache holds
  `--out`은 클로드가 읽지 않을 만큼 클 때만. 파일·커서 캐시는 남의 개인정보 → 레포 밖·작업 뒤 삭제. 팔로워 수집은 그 사람과 무관한 사람들의 목록이다.
```

## 구현 단계와 완료 판정

각 단계는 `tdd` 스킬로 시작한다(seam 합의 → 실패 테스트 → 통과). 단계마다 `codex`로 diff 리뷰를 받고 P1 지적은 그 단계 안에서 고친다. `TaskCreate` 트래커에 아래 판정 기준을 그대로 적는다. **라이브 예산표**(X API 요청 기준; 탭·CDN·HTML GET은 따로 센다): P1 1 + txid 콜드 스타트 HTML 2(첫 게이트 요청 때) + P2 8 + P3 7 + P4 11 = 29요청. 재시도·353 재취득이 붙을 수 있으므로 **이 스킬의 라이브 가드는 40요청**이다(reddit·threads의 30에서 올림; 가드는 `conftest`의 누적 장부 하나가 센다). P5의 `refresh`는 별도 실행이다. 데이터 의존 수치 대신 구조·대상 일치를 단언하고, skip은 완료가 아니다. 라이브는 항상 `--limit 3`부터.

| 단계 | 내용 | 완료 판정 |
|---|---|---|
| P0 | 스캐폴드: `twitter/` 생성, `tests/twitter/`, `.gitignore`에 이 계획·fixtures 예외, `harness-spec.md` 인벤토리 행 **B10 `approved`(X 읽기), B11 `declined`(쓰기), B12 `declined`(알림·DM)**, 심볼릭 링크, `registry.json` 초안(**스냅샷 JSON을 그대로 변환**) | `audit_harness.py --path .`가 skill 4개·드리프트 0. `pytest tests/twitter`가 0개 수집 exit 5. `ls -l ~/.claude/skills/twitter`가 레포를 가리킴 |
| P1 | `_errors`·`_aside`·`_blocked`·`_budget`·`_session`·`_txid`·`_registry`·`_transport`·`_target` + `graphql.js`·`page.js`·`cookie.js` + `doctor` | fake aside 단위 테스트 통과. classify 픽스처(순서 포함): 403 HTML→5 무만료, code 64/326→5 무만료이며 **뒤따르는 429·만료 처리가 못 덮음**, 429→해당 버킷만 잠금(reset 존중, 전역 차단 없음, 다른 오퍼레이션은 진행), 401→4, code 32→4, code 353→ct0 재취득 1회 후 재시도(두 번째 353→4, 재취득은 탭 1회만), 404 빈 본문(txid 없음)→txid 재시도 후 gated 학습, 404(txid 있음)→재료 재생성 1회→6 `transaction_rejected`, 400 features null→6 `operation_rotated` + `missing_features` 기록, 422/`must be defined`→6 `contract_drift`, 502→6 차단 없음, `data:{}`→9, `UserUnavailable`→9, 루트 없음→6 `envelope_drift`, 데이터+errors 214→0 warnings=1, 빈 항목+커서 없음→7, 빈 항목+새 커서→진행, 2페이지 뒤 429→8 부분 결과(`results`·`next`·`fix`). `_budget`: 두 프로세스 동시 요청이 창에 2회, 버킷 0→요청 없이 5, 창 200→5 `window`, `--limit` 있어도 40회에서 8, 헤더 반영이 예약을 덮음. `_txid`: **고정 벡터 픽스처**(P1 시작 시 `page.js`로 홈 HTML·ondemand.js를 한 번 받아 `derive_fixture`로 verification 값·SVG path 4쌍·인덱스·기대 애니메이션 키를 저장, 개인정보 없음)에서 애니메이션 키가 기대값과 같고, `now`·`rng`를 주입한 `generate(method, path, now=, rng=)`가 결정적 기대값을 내며, fake transport가 요청마다 `generate`를 한 번씩 부른 것을 계수. `_session`: session.json 0600, `twid` 파싱, viewer 변경 시 커서 삭제. `_target`: 12형 URL·`@name`·숫자 규칙·`t.co` 거절. node: `graphql.js`가 헤더 8종과 GET 쿼리 문자열/POST 본문을 정확히 만들고 txid는 있을 때만, `page.js`가 허용 호스트 밖을 거절, `cookie.js`가 실패해도 탭을 닫음. 라이브(1 + 탭 1): `doctor` exit 0이 `@radamshi99`와 버킷을 출력 |
| P2 | `_walk`·`_listing`·`_models`·`_entities`·`_schema`·`_render`·`_output` + `home`·`user`·`about` | 합성 픽스처: 고정·광고·visibility·리포스트(바깥 author=퍼간 사람, 본문·통계=원글)·인용(`quoted_tweet_id` 단독 보존)·note·`TimelineAddToModule`·모듈 안 사용자(who-to-follow) 워커가 `entry_id`·모듈 경계를 보존, 사용자 노드 F10 지도(followers·following·verified_type·protected·affiliate), 커서 EOF·`empty_pages`, 꼬리 먼저 소진 후 요청, render 골든(t.co 치환·숫자 축약), `--out`이 페이지 전체를 저장하고 `shown`/`stored`를 구분. 라이브(≤ 8): `home --limit 3`(1) 구조 단언과 광고 0, `home --feed following --limit 3`(1) 뒤 출력된 `more:` 핸들을 그대로 실행(꼬리 소진은 0요청, 꼬리가 다 떨어질 때까지 `--limit`을 키워 실제 2페이지 1요청까지 진행)해 id 중복 0, `user @X --limit 3`(2)의 카드 followers>0(고정글은 있을 때만 라벨 단언), `user @X --tab media --limit 3`(2), `about @X @nasa`(1)가 2카드 |
| P3 | `_thread` + `post`·`quotes`·`reposts` + `graph` | 단위: 부모 체인·focal·모듈 들여쓰기·완전성 4필드(`reported`·`direct_shown`·`nested_shown`·`hidden_branches`)·Recency·Bottom `--after`, `TweetResultsByRestIds` 여러 id, 사용자 목록 페이지네이션·`empty_pages`·모듈 안 사용자(communityMembers 픽스처). 라이브(≤ 7): `post <X 글> --limit 5`(1)에서 focal id 일치, 표시된 모든 답글의 `in_reply_to`가 focal이거나 표시된 다른 답글, `post <답글 url>`(1)의 첫 항목이 부모, `post … --sort recent`(1), `reposts <글> --limit 3`(1), `quotes <글> --limit 3`(1, txid)의 `quoted_tweet_id == focal`, `graph @X following --limit 3`(2) |
| P4 | `search`·`me`·`list`·`trends`·`community`·`communities` + `--since/--until`·`--out` | 단위: product 4종 변수와 People 워커, `--in communities` 변수(`rawQuery`)와 루트, 트렌드 항목(직접·모듈)·`[event]`·`other items`·광고 트렌드 라벨, 리스트·커뮤니티 카드, `CommunityAboutTimeline` 모듈 역할, 창 테스트, `--out` 중단 후 재실행(같은 명령이 커밋된 페이지 다음부터). 라이브(≤ 11): `search "python" --limit 3`(1, txid), `search python --type users --limit 3`(1), `search --in communities python --limit 3`(1), `me likes --limit 3`(1), `me bookmarks`(성진이 글 하나 북마크한 뒤 1, A5; 미확보면 **미검증으로 기록하고 완료로 치지 않음**), `list <SpaceX 리스트> --limit 3`(1), `trends --limit 5`(2), `community <id> --limit 3`(2: 정보 + 글), `communities --limit 3`(1) |
| P5 | `_bundles` + `bundles.js` + `refresh` | 단위: 청크 지도 중괄호 파서(합성 HTML), `operationType == "query"`만, features 스위치 재구성(없는 플래그 유지), txid 재료 추출, 검증 실패 시 미저장·원자적 저장, `missing` 보고. 라이브(별도, CDN 스윕 1 + 검증 2): `refresh`가 33종 중 `changed 0 · unchanged 33`(같은 날)과 `features` 39개, `txid ok`를 출력하고 `doctor`가 레지스트리 나이 0일을 보인다 |
| P6 | `SKILL.md`, `harness-spec.md`, README, CI, `validate_harness.py` exit 0, description 대조(facebook·reddit·threads·ultra-search) | 검증 절 참조 |

## Git과 Graphify

- 브랜치 `feat/twitter-skill`(`main`에서; `threads` 브랜치가 먼저 머지되면 리베이스). 단계마다 논리 단위 커밋(`feat: twitter …`, 한국어 제목), P2 이후 단계 끝마다 푸시. PR 하나(`feat: X 읽기 전용 스킬 구현`), 템플릿이 없으므로 `## 무엇을 바꿨나`/`## 왜`/`## 영향`/`## 검증`, `## 검증`에 실제 수치. CI 통과 후 `gh pr merge --squash`.
- Graphify는 P3 뒤와 P6 뒤 두 번, facebook 계획의 방식(`graphify extract . --code-only --no-cluster` → codex 명명 → `graphify export html …`).

## 재사용 지도

| 출처 | 새 모듈 | 변경 |
|---|---|---|
| threads `_aside.py`·`_errors.py`·`_blocked.py`·`_session.py`(구조)·`_target.py`(구조)·`_registry.py`(구조) | 각 대응 모듈 | 복사 후 이름·마커·fix 문구·민감 키(`ct0`·`auth_token`·`cookie`·`authorization`·`x-csrf-token`, `pbs.twimg.com` 서명 쿼리) 변경. `_blocked`는 reason 3종. `_registry`는 오퍼레이션별 `gated` 학습 저장 추가 |
| reddit `_budget.py`(헤더 예약·만료·페이싱 거버너) | `_budget.py` | 단일 창 → **query id별 버킷** 사전 + 10분 창 합산 |
| facebook `_output.py`·`_schema.py`·`_render.py`·`_paginate.py`(구조)·`facebook.py`(배선) | `_output`·`_schema`·`_render`·`_listing`·`twitter.py` | 이름·라벨 변경, `_listing`의 transport import 제거 |
| facebook `browser/graphql.js`·`page.js` | `browser/graphql.js`·`page.js` | 헤더 세트를 X 계약으로, 12MB 조각 경로 유지, `URLSearchParams` 없이 조립 |
| 옛 `transaction.py`(수학 139~265행, `generate` 331~355행) | `_txid.py` | `httpx`·클래스 제거, 재료를 봉투에서 받음, 라이선스 주석 유지 |
| 옛 `queryids.py`(`_brace_span`·`_chunk_urls`·`_scrape_operations`·`changed_ids`) | `_bundles.py` + `bundles.js` | 스윕은 JS(Aside fetch), 파싱·병합·보고는 Python |
| 옛 `parse.py`(`ENVELOPE_ROOTS`·`_entry_tweets`·`walk_instructions`·`walk_user_instructions`·`walk_result_list`) | `_walk.py` | 루트를 레지스트리 데이터로, 커뮤니티·리스트·트렌드·탐색 루트 추가, `TimelineTrend` 항목 |
| 옛 `model.py`(`Tweet`·`Media`·`build_tweet`·`_extract_*`) | `_models.py` | `raw`·`captured_at`·JSON Schema 생성기 삭제, `limited_actions`·`community_results`·`in_reply_to_screen_name` 추가 |
| 옛 `model.py`의 `User`·`build_user` | `_entities.py` | **F10 지도로 재작성**, `List`·`Community`·`Trend` 신규 |
| 옛 `retrieve.py`(커서 EOF·`_EMPTY_USER_PAGE_LIMIT`·`_below_since`) | `_listing.py` | 규칙만 이식 |
| 옛 `client.py`(`_has_auth_error` code 32) | `_transport.py` | 표식 이식 + 353·404·422 규칙 |
| 옛 `auth.py` 303~479행 | `_target.py` | 순수 함수만 + 리스트·커뮤니티·`t.co` 형태(A9) |
| 옛 `.claude/skills/x/SKILL.md`의 원리 절 | `SKILL.md` | Aside 전제와 무관한 원리만(리포스트 author·edge는 관측·Top vs Latest·좋아요한 사람 부재·id 조인) |
| 옛 `session.py`·`observe.py`·`config.py`·`cli.py`·`redact.py`·`gql.py`의 변수 빌더 | — | 가져오지 않음(세션 소유·브라우저 폴백·설치·카탈로그 전제; 변수는 레지스트리 데이터로) |

## 검증

- 단위: `python3 -m pytest tests/ -q` (aside 없이, 형제와 함께). JS: `node --test tests/twitter/js/*.js`. 린트: `uvx ruff check --config pyproject.toml .claude/skills/twitter/scripts tests/twitter`. PII: `python3 tests/twitter/tools/check_fixtures_pii.py`.
- 라이브: `python3 -m pytest -m live tests/twitter/live/ -q`. 모양·불변식만. 누적 30요청 가드(탭·CDN 스윕은 요청 수에 넣되 X 버킷은 아님).
- 하네스: `validate_harness.py --path .` exit 0, `audit_harness.py` 드리프트 0.
- codex: 계획 리뷰(이 세션) → 단계별 diff 리뷰 → 최종 사용성 검토. 기준은 **"본문과 `--help`·도구 출력만으로 네 시나리오를 수행할 수 있나"**: V1 "내 트위터 피드 뭐 올라왔어" → `home`. V2 "이 트윗 답글 분위기 요약해줘(URL)" → `post`, 받은 수·정렬을 보고에 밝히고 필요하면 `--sort recent`·`quotes`. V3 "@karpathy 요즘 뭐 올려" → `user`, 낯선 계정이면 `about`. V4 "claude code 얘기하는 트위터 계정 찾아줘" → `search --type users` → `about` 여럿 한 번에, 검색 버킷 보고. 근접 오발 둘: "스레드에서 …", "이 레딧 글 …" → 미호출.
- Claude e2e: 미실행(D8).

## 위험과 처리

| 위험 | 처리 |
|---|---|
| 실계정 잠금·정지(X는 자동화에 공격적) | 하한 1.0s·지터·버킷 20% 감속, 호출당 10/40/60, 10분 200회 창, 잠금 코드 최우선 무만료 차단, SKILL.md의 "몇 명·몇 글" 원리, 라이브 예산표 |
| txid 알고리즘 변경(X 클라이언트 배포마다 가능) | 게이트 3종만 죽고 나머지는 산다(D7). 오류 `fix`가 대체 표면을 가리킨다. 재포팅은 코드 변경이며 `_txid.py`가 상류 구현과 diff 가능하도록 수학을 그대로 둔다 |
| query id·features 회전(6주에 전부) | `operation_rotated` → `refresh`(탭 없음, 30초, 검증 2요청) |
| 사용자 노드 형태 변경(이미 한 번 바뀜) | `_entities`가 지도 한 곳, 픽스처는 실측 형태, `about` 라이브가 followers>0을 단언 |
| `ct0` 회전 | 353 → 재취득 1회 → 재시도. 세션 내 불변 관측. 캐시 파일 0600 |
| 응답 크기(리스트 970KB·홈 600KB) | `fetched` 표시, 12MB 조각 경로, 기본 표시 수 작게 |
| 북마크 항목 형태 미확정(A5) | 구현 세션 P4 라이브에서 확정 |
| 수집 파일의 개인정보 | 레포 밖 권장, `.gitignore`, 본문의 삭제 원리 |

## 미룬 것 (스펙에 기록)

- 쓰기 동작 전부: `declined` (D2).
- 알림(`NotificationsTimeline`)·DM: `declined` (D3).
- 좋아요한 사람: X가 빈 종료 타임라인만 준다. 명령 없음, SKILL.md가 말한다.
- 숫자 id → 프로필: `UserByRestId`가 403. 명령 없음.
- 아티클 본문(`article` 노드의 rich text): 표본이 없었다. `--tab articles`는 목록만, 본문은 다음 패스.
- 미디어 다운로드: `--json`의 URL로 충분한지 먼저 본다.
- 프로세스 스폰 묶음: 병목이 측정될 때.

## 가정 (구현 세션이 확인)

- **A1** HTML 스위치 값으로 만든 features 지도(2개 값이 7월 캡처와 다름)로도 모든 오퍼레이션이 200이다. P1 라이브 `doctor`와 P2 첫 요청이 확인한다. 실패하면 7월 값으로 되돌리고 `refresh`의 features 재구성을 "필수 플래그 추가"로 좁힌다.
- **A2** 새 필수 플래그는 400 `The following features cannot be null: …`로 온다(옛 관측). `refresh`가 이 이름을 HTML 스위치에서 찾아 넣는다.
- **A3** 429의 본문·헤더 형태. 미유발. `reset` 헤더가 없으면 15분.
- **A4** 로그아웃은 401 또는 200+code 32, 정지 code 64, 잠금 code 326. 미유발. 로그인 판정은 이 신호에만.
- **A5** `Bookmarks`의 항목 형태는 홈과 같은 `tweet-*` 항목이다(성진이 글 하나 북마크한 뒤 P4에서 확인).
- **A6** `TweetDetail` 모듈 안의 `ShowMore*` 커서(답글 더 보기)의 존재와 변수. 표본에서 0개. **이번 범위에서는 따라가지 않고** `hidden_branches`로 세어 헤더에 적는다(완전 수집을 주장하지 않는다). 변수·저장·예산 규칙은 다음 패스.
- **A7** 비공개 계정은 `privacy.protected == true`이고 팔로우하지 않으면 타임라인 항목이 비고 커서만 온다.
- **A8** 프로필 posts 타임라인은 고정글을 제외하면 시간 단조다. 홈·리스트·하이라이트는 미확인이라 `window_reached`를 주장하지 않는다.
- **A9 (범위 밖으로 정리)** `t.co` 단축 URL은 이번 버전에서 받지 않는다(`page.js`가 `x.com`·`abs.twimg.com`만 허용). `_target`이 exit 2로 거절하고 `fix`에 "open the t.co link and pass the x.com URL"을 적는다. description에서도 `t.co`를 뺀다. 지원하려면 별도 해석 스니펫(HTTPS·정확한 호스트·리다이렉트 목적지 검사)이 필요하며 다음 패스.

## codex 리뷰 반영 (2026-09-05, run `20260905-174151-twitter-plan-review-207d`)

25건 중 25건 반영. P1(17건): (1) `UserRepliesTimeline`은 답글만이 아니므로 자동 대체를 없애고 `--tab replies-only`로 분리·출처 표기, (2) 리포스트 계약을 옛 `build_tweet`(바깥 author=퍼간 사람, 본문·통계=원글)로 통일, (3) `quoted_tweet_id` 독립 필드와 URL 홉, (4) `_walk` 반환 계약에 `entry_id`·모듈 경계·모듈 커서·`terminated` 보존, (5) 모듈 안 사용자(커뮤니티 about·who-to-follow) 추출, (6) 완전성 4필드(`reported`·`direct_shown`·`nested_shown`·`hidden_branches`)와 P3 부모 연결 검증, (7) A6 분기 커서는 미지원으로 표시, (8) `--after`는 꼬리 먼저 0요청·상태에 id 집합·창·실제 오퍼레이션, (9) `viewer_id` 대조·계정 전환 시 커서 삭제·개인 표면 24시간 재확인, (10) `t.co`를 범위 밖으로, (11) `missing_features` 기록 → `refresh`가 HTML에서 찾아 넣음, (12) 변수 검증 오류는 `contract_drift`로 분리, (13) `refresh`가 누락 항목의 현재 유효 값을 유지하고 검증/발견을 구분, (14) 잠금·정지 코드를 최우선·무만료로 올리고 덮어쓰기 금지 테스트, (15) 429는 버킷만·창은 계정·무만료는 전역으로 책임 분리, 60회 상한 삭제, (16) 부분 결과 JSON·exit 8 규칙, (17) `--out`은 페이지 전체 저장·`shown/stored` 구분·완료 마커 표. P2(8건): (18) 명령별 기본값·허용 옵션 표와 exit 2, (19) 커뮤니티 검색은 전역임을 명시, (20) `trends` 탭별 경로·항목 종류·`other items`, (21) 라이브 예산 재계산(29)과 가드 40, (22) 이어읽기 라이브 판정을 `more:` 핸들 실행으로·데이터 의존 단언 조건화, (23) `_txid` 고정 벡터 픽스처와 `now`·`rng` 주입, (24) SKILL.md 골격에서 명령 안내·수치 제거, (25) P0 인벤토리 B10 `approved`·B11/B12 `declined`. 리뷰 뒤 저장 응답에서 커뮤니티 둘러보기·커뮤니티 검색 루트 2종을 확정해 `verify in P4` 표기를 지웠다.

## 구현 진행 기록

2026-09-05: 사용자 구현 요청으로 D1–D12·P0–P6·테스트 경계 승인을 확인했다. 원본 작업 디렉터리는 `feat/threads-skill`의 미커밋 작업이 있으므로 건드리지 않고, `main`에서 만든 `feat/twitter-skill` worktree `/Users/seongjin/Coding/Agentic-SNS-twitter`에서 진행한다. 원본 Threads 계획은 이미 16종 레지스트리 JSON과 P0 통합·단독 파일 삭제 기록을 포함하므로 중복 편집하지 않았다. 별도 과정 파일은 만들지 않는다. 이 세션의 실제 도구 카탈로그에 TaskCreate·TaskUpdate·ToolSearch가 없어 이 표를 진행 표면으로 사용한다.

| 단계 | 상태 | 완료 근거·남은 검증 |
|---|---|---|
| P0 | 완료 | 33종 레지스트리·독립 스킬·사용자 링크 생성. 격리 worktree audit는 main에 Threads가 아직 없어 skill 3개·드리프트 0, validator 오류 0·경고 0. 원본 Threads 작업은 보존했다. 초기 0개 테스트 수집은 별도 실행하지 않았으며 대신 실제 경계 테스트를 검증했다. |
| P1 | 완료 | 중간 검증: `python3 -m pytest tests/twitter/test_target.py tests/twitter/test_transport.py -q` 26 passed, `node --test tests/twitter/js/*.js` 4 passed. 실제 HTML·서명 청크·Viewer 1요청 성공. 독립 P1 리뷰와 동시성·복구 테스트 보강 대기. |
| P2 | 완료 | 새 사용자 필드·리포스트·장문·인용·모듈·출력·꼬리 우선 이어읽기 검증. 실계정 홈/Following/프로필/미디어/배치 카드, 캐시 0요청과 실제 다음 페이지·중복 제거 확인. |
| P3 | 완료 | 부모·focal·직접/중첩 답글·관련 글 제외·분기 누적·관계망 구현 및 회귀 검증. 실계정 스레드/관계 검증 통과. P3 그래프 1,224노드·2,895간선·92커뮤니티를 Codex가 명명하고 HTML 검증. |
| P4 | 구현 완료·A5 미검증 | 검색/개인 목록/리스트/트렌드/커뮤니티/날짜 창/파일 재개 구현·통합 테스트 통과. 실계정 커뮤니티 URL 객체를 문자열로 보정하고 새 응답→카드/글 3건 재검증. 북마크 빈 응답은 확인했으나 실제 항목 형태는 미검증. |
| P5 | 완료 | 실제 번들의 shared~·i18n/ 이름을 빠뜨리던 필터를 재현 테스트 후 수정. 수정본 refresh: discovered 33·changed 0·unchanged 33·missing []·features 39·txid ok. 2개 검증 요청 통과. |
| P6 | 완료 | SKILL.md·README·CI·사용성 검토 완료. 전체 로컬 595 passed, Twitter 160 passed·JS 9 passed, 하네스 오류/경고 0·드리프트 0. 최초 CI 수집 오류 수정 후 Linux push CI 통과. PR #3의 checks·merge 상태가 배포 확인 표면이다. |

구현 실행: Codex `20260905-175118-twitter-implementation-f3e1` (`gpt-6-astra`, medium, priority). 소유 범위는 `.claude/skills/twitter/`와 `tests/twitter/`이며, 상위 세션이 계획·하네스·CI·Git 통합과 결과 검증을 담당한다. Threads 구현과 원본 브랜치 변경은 금지했다. 라이브 가드는 계획 최종 정정의 40회이며 refresh는 별도다.

P1 독립 리뷰 `20260905-175554-twitter-p1-review-acdb`: URL 포트/IPv6 파싱 예외, 특수문자 검색어 템플릿 오인, 누락 feature 덮어쓰기 3건을 확인했다. 각 실패 테스트를 먼저 실행해 재현하고 공통 경계에서 수정했다. 상위 세션이 P1 모듈과 테스트 소유권을 받아 동시 프로세스·오퍼레이션 버킷 격리·창/호출 상한·영구 차단·CSRF 재취득·계정 전환·서명 재생성과 gated 학습·Aside subprocess/조각 봉투를 보강했다. `python3 -m pytest tests/twitter/test_target.py tests/twitter/test_registry.py tests/twitter/test_budget.py tests/twitter/test_session_transport.py tests/twitter/test_transport.py tests/twitter/test_txid.py tests/twitter/test_aside.py -q`: 59 passed. `node --test tests/twitter/js/test_graphql.js`: 5 passed. 같은 P1 파일 대상 `uvx ruff check --config pyproject.toml …`: All checks passed. 서명 fixture의 animation key·완성 txid는 기존 `.tmp/Agentic X`의 `ClientTransaction`으로 독립 재계산해 일치했고, 고정 시각·noise·검증 출처를 fixture에 기록했다. 재검토 `20260905-180234-twitter-p1-review-3841`가 세 결함 수정을 확인했고, 남은 챌린지 영구 차단·502 비차단·URL 형식·fieldToggles 테스트를 추가했다. 같은 Python 명령은 최종 67 passed, JS는 7 passed다. 리뷰어의 읽기 전용 환경은 임시 디렉터리를 만들 수 없어 일부 테스트 실행이 제한됐지만 상위 세션에서 모두 실제 통과했다. 전체 CLI·부분 결과·doctor 라이브 경계는 후속 통합 검증에서 판정한다.



P2–P5 독립 리뷰 `20260905-180332-twitter-browse-review-e2f1`가 8건을 확인했다. 상위 세션은 CSRF 복구 중 viewer 변경 시 재시도를 중단하고, 사용자/타임라인 루트가 존재해도 최소 형태가 틀리면 envelope_drift로 구분하도록 재현 테스트 후 수정했다. 구현 실행은 날짜 창 내 전체 페이지 저장, about/batch 비페이지 조회의 잘림 방지, 파일의 답글 완전성 기록, 숨은 분기 누적, 양수 continuation 번호를 보강한다. 여기서 “페이지 전체 저장”은 표시 수에는 잘리지 않되 사용자가 지정한 날짜 창 안의 전체 페이지라는 뜻으로 명확히 한다. 사용자 스코프 링크는 다른 세션을 방해하지 않도록 현재 격리 worktree의 스킬을 가리킨다.

## 최종 검증 기록

- `python3 -m pytest tests/twitter -q`: 최종 160 passed, 3 live deselected (30.85s). `python3 -m pytest tests/facebook tests/reddit -q`: 435 passed, 12 live deselected (155.01s). 작업 중인 원본 Threads 코드·테스트는 가져오거나 수정하지 않았다.
- `node --test tests/twitter/js/*.js`: 9 passed. `uvx ruff check --config pyproject.toml .claude/skills/twitter/scripts tests/twitter`: All checks passed. `python3 tests/twitter/tools/check_fixtures_pii.py`: passed. `git diff --check`: 통과.
- `validate_harness.py --path .`: 오류 0·경고 0. `audit_harness.py --path .`: 격리 main 기반에서 skill 3개·드리프트 0. Threads가 main에 머지되면 skill 4개가 되는 구성이다.
- 라이브는 `TWITTER_ASIDE_BIN=…/tests/twitter/live/guard_aside.py`를 통해 실행했다. 최초 합쳐진 시나리오는 관련 글을 답글로 세는 단언 실패를 발견했고, 재현 테스트 후 관련 모듈을 제외했다. 분리한 `test_live_threads_and_relationships`는 통과했다. 검색·개인 목록·리스트·트렌드·커뮤니티 탐색 뒤 커뮤니티 URL 객체가 subprocess 인자로 전달되는 실패를 발견했다(`1 failed, 1 passed, 1 deselected`). URL 정규화 재현 테스트 후 새 `communities --limit 3 --json`(1요청)에서 문자열 링크를 받아 `community <반환 URL> --limit 3 --json`(2요청)을 실행해 exit 0·글 3건·멤버 수를 확인했다. 이미 통과한 표면은 불필요하게 재실행하지 않았고 전체 live suite 통과로 표기하지 않는다.
- 첫 `refresh --json`은 검증 2회 성공·28종 발견·5종 미발견이었다. 실제 HTML 확인으로 `shared~…`와 `i18n/…` 번들 이름이 검증 필터에서 제외된 원인을 찾았다. 허용 호스트와 `.`/`..` 경로 요소 거부를 유지하면서 정상 이름을 허용한 뒤 JavaScript 실패 테스트가 통과했다. 수정본 `refresh --json`은 전체 33종 발견·변경 0·누락 0·플래그 39·txid 정상. 첫 refresh 2회는 별도 장부이며 수정 후 검증 2회는 일반 40회 장부의 남은 범위에서 차감했다. 장부를 초기화하거나 상한을 높이지 않았다.
- `doctor`: Aside u0 로그인 핸들·Viewer 버킷·레지스트리/서명 나이 정상. A5 북마크는 유효한 빈 타임라인으로 항목 형태 미검증이다. 사용자가 직접 하나 추가하면 남은 가드 범위에서 해당 항목만 확인할 수 있다. 쓰기 요청은 수행하지 않았다.
- P2–P5 리뷰 재검증 `20260905-180828-twitter-browse-review-3e87`: 기존 8건 모두 해결. 별도 Claude headless e2e는 D8에 따라 실행하지 않았다.

사용성 검토 `20260905-181246-twitter-usability-6cf7`는 구현/테스트 소스 없이 SKILL.md·도움말·실제 CLI 출력만으로 V1 홈 캐시, V2 실제 글/답글, V3 `@X` 프로필 캐시(계획의 `@karpathy`와 같은 명령 경계), V4 계정 검색 캐시→반환 핸들 2개 일괄 조회를 수행해 모두 exit 0이었다. 새 API 요청은 2회였다. 계정 검색의 latest 오해를 없애 `rank=people`로 표시하고 명시적 post sort를 거절했다. 요청 수와 account window를 분리해 표시하고 For you 개인화 라벨을 추가했다. about/trends에 불가능한 continuation 옵션은 도움말에서 제거했고 프로필 카드 `--chars`도 실제 적용하도록 실패 테스트 후 수정했다. 강제 예산을 더 낮추는 별도 플래그와 캐시 시각 확장은 승인 범위에 추가하지 않았다. 24시간 세션 재확인과 캐시가 현재 시점 전체 최신 목록이 아니라는 원리는 본문에 유지했다. 사용성 실행과 동시에 doctor 1회를 상위 세션이 실행했으므로 리뷰어의 추정 장부 값 대신 실제 장부를 최종 근거로 쓴다.

CI 최초 실행에서 `tests/twitter/live/test_live.py`와 Facebook live 모듈의 이름 충돌을 발견했다. 전체 `python3 -m pytest tests/ --collect-only -q`로 같은 오류를 재현하고, Twitter live 디렉터리에 `__init__.py`를 추가해 독립 네임스페이스로 수집되도록 수정했다. 스킬별 테스트만 통과했다는 이유로 CI 실패를 넘기지 않았다.

최종 전체 실행 `python3 -m pytest tests/ -q`: **595 passed, 15 deselected (178.92s)**. P6 그래프는 사용성 보정 후 다시 갱신해 **1,262노드·2,910간선·93커뮤니티**이며 Codex `20260905-181713-twitter-graph-labels-7969`가 현재 멤버 기준 모든 이름과 HTML 반영을 검증했다. 그래프는 격리 worktree의 로컬 제외 파일로 유지했다. 사용자 링크로 `/tmp`에서 `twitter.py --help`와 `schema --json`도 실행해 작업 디렉터리 독립성을 확인했다.

최종 실계정 누적 장부는 일반 GraphQL **37/40**, 별도 최초 refresh 검증 **2회**, 탭/HTML/CDN 묶음 **6회**다(전체 X API 합계 39회). 사용자 승인 없는 쓰기·북마크 추가는 수행하지 않았다. A5의 실제 북마크 항목 형태는 데이터 부재로 미검증을 유지하며 P4 전체 라이브 완료로 표기하지 않는다. [PR #3](https://github.com/tjdwls101010/Agentic-SNS/pull/3)에 한국어 변경 이유·영향·실행 결과를 남겼고, CI와 스쿼시 머지의 최종 상태는 해당 PR에서 확인한다. 원본 Threads 브랜치·코드·계획서·캐시는 수정하지 않았다.

## 레지스트리 스냅샷

구현의 갱신 가능한 레지스트리는 스킬 안의 `scripts/registry.json`이고, 이 블록은 2026-09-05 조사 근거로 보존한다. `vars`의 `<…>`와 `a|b`는 템플릿 표기이며 `cursor: null`은 첫 페이지다. 모든 `root`는 실측 응답에서 `instructions[]`(또는 단일 노드)를 찾은 경로다.

```json
{
 "captured_at": "2026-09-05",
 "account": "Aside u0 = @radamshi99 (1818125492823986176)",
 "bearer": "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
 "operations": {
  "UserByScreenName": {"query_id": "Gb-d6r0vxPOADdG62OEBpQ", "method": "GET", "gated": false, "rate": 150, "kind": "user_single", "root": "data.user.result", "vars": {"screen_name": "<handle>", "withSafetyModeUserFields": true}, "verified": "200; missing handle -> {\"data\":{}}"},
  "UsersByScreenNames": {"query_id": "BQEP-w59kdVKv7CSLsSSiw", "method": "GET", "gated": false, "rate": 50, "kind": "user_list", "root": "data.users[].result", "vars": {"screen_names": ["<handle>", "…"], "withSafetyModeUserFields": true}, "verified": "200; unresolved handle -> element without result"},
  "Viewer": {"query_id": "5XShkXk2oO2J7SYmTu6pvw", "method": "GET", "gated": false, "rate": 100, "kind": "user_single", "root": "data.viewer.user_results.result", "vars": {"withCommunitiesMemberships": true}, "verified": "200 (@radamshi99)"},
  "UserTweets": {"query_id": "eviprbEPLvNG88V3smUngQ", "method": "GET", "gated": false, "rate": 50, "kind": "tweets", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": true, "withQuickPromoteEligibilityTweetFields": true, "withVoice": true, "cursor": null}, "verified": "200; 21 tweets incl. 1 pinned; page 2 overlap 1 (the pin repeats)"},
  "UserTweetsAndReplies": {"query_id": "3NGdaaeHbLRmVlbbJ-eBgg", "method": "GET", "gated": true, "rate": 500, "kind": "tweets", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": true, "withCommunity": true, "withVoice": true, "cursor": null}, "fieldToggles": {"withArticlePlainText": false}, "verified": "404 without txid, 200 with (26 tweets)"},
  "UserRepliesTimeline": {"query_id": "dRUXRSlEIPlVmPgOQ8Z43g", "method": "GET", "gated": false, "rate": 50, "kind": "tweets", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "withClientEventToken": false, "withBirdwatchNotes": false, "withVoice": true, "cursor": null}, "verified": "200; 40 tweets, 23 replies"},
  "UserMedia": {"query_id": "VyudDWQnr9vJNw7GasFz2g", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "withClientEventToken": false, "withBirdwatchNotes": false, "withVoice": true, "cursor": null}, "verified": "200; 11 tweets"},
  "UserHighlightsTweets": {"query_id": "p1UTbncXKApPssa4EpqKvw", "method": "GET", "gated": false, "rate": 50, "kind": "tweets", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "withVoice": true, "cursor": null}, "verified": "200; 20 tweets"},
  "UserArticlesTweets": {"query_id": "ZmMjUyrTpwYfTGAdylEyMw", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "withClientEventToken": false, "withBirdwatchNotes": false, "withVoice": true, "cursor": null}, "verified": "200; empty (cursors only) on a user without articles"},
  "Likes": {"query_id": "xA8fDIbrJfy4ojjjXmSR-A", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<viewer id>", "count": 20, "includePromotedContent": false, "withClientEventToken": false, "withBirdwatchNotes": false, "withVoice": true, "cursor": null}, "verified": "200; 4 tweets (viewer only)"},
  "Bookmarks": {"query_id": "iblrFnKr6PZUR-dWpfXG6g", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.bookmark_timeline_v2.timeline.instructions", "vars": {"count": 20, "includePromotedContent": false, "cursor": null}, "verified": "200; instructions [] on an account with no bookmarks (A5)"},
  "HomeTimeline": {"query_id": "wp06oo3fRGU4P1sK8rECqQ", "method": "POST", "gated": false, "rate": 500, "kind": "tweets", "root": "data.home.home_timeline_urt.instructions", "vars": {"count": 20, "includePromotedContent": true, "latestControlAvailable": true, "requestContext": "launch", "withCommunity": true, "cursor": null}, "verified": "200; ~60 tweets + 7-9 promoted"},
  "HomeLatestTimeline": {"query_id": "BLQWpfVqtgBqAqwRRJcJjA", "method": "POST", "gated": false, "rate": 500, "kind": "tweets", "root": "data.home.home_timeline_urt.instructions", "vars": {"count": 20, "includePromotedContent": true, "latestControlAvailable": true, "requestContext": "launch", "withCommunity": true, "cursor": null}, "verified": "200; 61 tweets, page 2 28 tweets overlap 1"},
  "TweetDetail": {"query_id": "XMOz5h24KAZ86qKffKTLdQ", "method": "GET", "gated": false, "rate": 150, "kind": "thread", "root": "data.threaded_conversation_with_injections_v2.instructions", "vars": {"focalTweetId": "<id>", "with_rux_injections": false, "rankingMode": "Relevance|Recency", "includePromotedContent": true, "withCommunity": true, "withQuickPromoteEligibilityTweetFields": true, "withBirdwatchNotes": true, "withVoice": true, "cursor": null}, "fieldToggles": {"withArticleRichContentState": true, "withArticlePlainText": false, "withArticleSummaryText": true, "withArticleVoiceOver": true, "withGrokAnalyze": false, "withDisallowedReplyControls": false}, "verified": "200; focal + 40 conversationthread modules + Bottom cursor; page 2 40 modules overlap 1; reply as focal -> parent first; Recency 26 newest-first; unknown id -> tweet_results {}"},
  "TweetResultsByRestIds": {"query_id": "Pho4sg8jLcrVlMeclMayrg", "method": "GET", "gated": false, "rate": 500, "kind": "tweet_list", "root": "data.tweetResult[].result", "vars": {"tweetIds": ["<id>", "…"], "includePromotedContent": false, "withCommunity": false, "withVoice": false}, "verified": "200; 5/5"},
  "SearchTimeline": {"query_id": "hyPfJYJ_XAtDYoslQc-Rgg", "method": "GET", "gated": true, "rate": 50, "kind": "tweets|users (product=People)", "root": "data.search_by_raw_query.search_timeline.timeline.instructions", "vars": {"rawQuery": "<query>", "count": 20, "querySource": "typed_query", "product": "Latest|Top|People|Media", "withGrokTranslatedBio": true, "withQuickPromoteEligibilityTweetFields": false, "cursor": null}, "verified": "404 without txid; 200 with: Latest 20, Top 20, People 20 users, quoted_tweet_id:<id> 20, page 2 overlap 0; one 50/15min bucket shared by all products"},
  "Following": {"query_id": "qGZZDF3mp91q7X22s3HxpA", "method": "GET", "gated": false, "rate": 500, "kind": "users", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "cursor": null}, "verified": "200; 70 users"},
  "Followers": {"query_id": "JNyQdTISpzCkj_1fqxDvFg", "method": "GET", "gated": true, "rate": 50, "kind": "users", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "cursor": null}, "verified": "404 without txid; 200 with: 70 users, page 2 49 overlap 0"},
  "BlueVerifiedFollowers": {"query_id": "u3PkPbg--arppBcwNbF1ig", "method": "GET", "gated": false, "rate": 500, "kind": "users", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "cursor": null}, "verified": "200; 20 users"},
  "FollowersYouKnow": {"query_id": "VFqixXkwK2VqJ9PedvCNqg", "method": "GET", "gated": false, "rate": 500, "kind": "users", "root": "data.user.result.timeline.timeline.instructions", "vars": {"userId": "<id>", "count": 20, "includePromotedContent": false, "cursor": null}, "verified": "200; 3 users"},
  "Retweeters": {"query_id": "ROjiuYueotTnWoI8m2YaiQ", "method": "GET", "gated": false, "rate": 500, "kind": "users", "root": "data.retweeters_timeline.timeline.instructions", "vars": {"tweetId": "<id>", "count": 20, "includePromotedContent": true, "cursor": null}, "verified": "200; 20 users"},
  "Favoriters": {"query_id": "yObihOW0q78g0PONS3QWVw", "method": "GET", "gated": false, "rate": 500, "kind": "users", "root": "data.favoriters_timeline.timeline.instructions", "vars": {"tweetId": "<id>", "count": 20, "includePromotedContent": true}, "verified": "200 but only TimelineTerminateTimeline: not offered as a command"},
  "ListLatestTweetsTimeline": {"query_id": "1LE3u14FJjPZUHKFGzos2g", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.list.tweets_timeline.timeline.instructions", "vars": {"listId": "<id>", "count": 20, "cursor": null}, "verified": "200; 81 tweets, 970KB"},
  "ListByRestId": {"query_id": "niz0TtOxL2zIcbq6_NQiNw", "method": "GET", "gated": false, "rate": 500, "kind": "list_single", "root": "data.list", "vars": {"listId": "<id>"}, "verified": "200 with a harmless errors[214] alongside data: name, description, member_count, subscriber_count, mode"},
  "ListMembers": {"query_id": "8rYmkvWQe9jRRZdy_-vkGA", "method": "GET", "gated": false, "rate": 500, "kind": "users", "root": "data.list.members_timeline.timeline.instructions", "vars": {"listId": "<id>", "count": 20, "cursor": null}, "verified": "200; 20 users"},
  "ExplorePage": {"query_id": "jo4rJIWiO5pQlMk6FYphZQ", "method": "GET", "gated": false, "rate": 500, "kind": "explore", "root": "data.explore_page.body", "vars": {"withCommunitiesMemberships": true}, "verified": "200; initialTimeline (for_you) + timelines[] ids for_you/trending/news/sports/entertainment with timeline.id for GenericTimelineById"},
  "GenericTimelineById": {"query_id": "ee4dBLWL8a8qg6n19m1htQ", "method": "GET", "gated": false, "rate": 500, "kind": "trends", "root": "data.timeline.timeline.instructions", "vars": {"timelineId": "<from ExplorePage timelines[].timeline.id>", "count": 20, "withCommunity": true}, "verified": "200; trending: 62 TimelineTrend items"},
  "CommunitiesExploreTimeline": {"query_id": "ydRsG-hZZ7p8ylwe1BdtSw", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.viewer.explore_communities_timeline.timeline.instructions", "vars": {"count": 20, "cursor": null}, "verified": "200; 20 community tweets, ids in socialContext.landingUrl /i/communities/<id>"},
  "CommunityTweetsTimeline": {"query_id": "EwftYyqQemkckQ0wzGM6uw", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.communityResults.result.ranked_community_timeline.timeline.instructions", "vars": {"communityId": "<id>", "count": 20, "displayLocation": "Community", "rankingMode": "Relevance|Recency", "withCommunity": true, "cursor": null}, "verified": "200; 19 tweets + pin; Recency 28"},
  "CommunityMediaTimeline": {"query_id": "ESJtwnI_apuGesbJncpc0Q", "method": "GET", "gated": false, "rate": 500, "kind": "tweets", "root": "data.communityResults.result.community_media_timeline.timeline.instructions", "vars": {"communityId": "<id>", "count": 20, "withCommunity": true, "cursor": null}, "verified": "200; 35 tweets"},
  "CommunityByRestId": {"query_id": "KW2CcDlT6D26JLajPjL5KA", "method": "GET", "gated": false, "rate": 500, "kind": "community_single", "root": "data.communityResults.result", "vars": {"communityId": "<id>"}, "verified": "200; name, description, member_count, moderator_count, join_policy, is_nsfw, role, rules"},
  "CommunityAboutTimeline": {"query_id": "H-QOvucTlztqr3leGYpg7g", "method": "GET", "gated": false, "rate": 50, "kind": "users", "root": "data.communityResults.result.about_timeline.timeline.instructions", "vars": {"communityId": "<id>", "count": 20, "withCommunity": true}, "verified": "200; communityModerators + communityMembers modules"},
  "GlobalCommunitiesLatestPostSearchTimeline": {"query_id": "OLcWToLopIqEtIQLgMeH9g", "method": "GET", "gated": false, "rate": 50, "kind": "tweets", "root": "data.search_by_raw_query.communities_latest_posts_search_page.timeline.instructions", "vars": {"rawQuery": "<query>", "count": 20, "withCommunity": true, "cursor": null}, "verified": "200; 33 tweets. `searchQuery` -> 422 must be defined"}
 },
 "features": {
  "rweb_video_screen_enabled": false, "rweb_cashtags_enabled": true, "profile_label_improvements_pcf_label_in_post_enabled": true, "responsive_web_profile_redirect_enabled": true, "rweb_tipjar_consumption_enabled": false, "verified_phone_label_enabled": false, "creator_subscriptions_tweet_preview_api_enabled": true, "responsive_web_graphql_timeline_navigation_enabled": true, "responsive_web_graphql_skip_user_profile_image_extensions_enabled": false, "premium_content_api_read_enabled": false, "communities_web_enable_tweet_community_results_fetch": true, "c9s_tweet_anatomy_moderator_badge_enabled": true, "responsive_web_grok_analyze_button_fetch_trends_enabled": false, "responsive_web_grok_analyze_post_followups_enabled": false, "rweb_cashtags_composer_attachment_enabled": true, "responsive_web_jetfuel_frame": true, "responsive_web_grok_share_attachment_enabled": true, "responsive_web_grok_annotations_enabled": true, "articles_preview_enabled": true, "responsive_web_edit_tweet_api_enabled": true, "rweb_conversational_replies_downvote_enabled": false, "graphql_is_translatable_rweb_tweet_is_translatable_enabled": true, "view_counts_everywhere_api_enabled": true, "longform_notetweets_consumption_enabled": true, "responsive_web_twitter_article_tweet_consumption_enabled": true, "content_disclosure_indicator_enabled": true, "content_disclosure_ai_generated_indicator_enabled": true, "responsive_web_grok_show_grok_translated_post": true, "responsive_web_grok_analysis_button_from_backend": true, "post_ctas_fetch_enabled": false, "freedom_of_speech_not_reach_fetch_enabled": true, "standardized_nudges_misinfo": true, "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": true, "longform_notetweets_rich_text_read_enabled": true, "longform_notetweets_inline_media_enabled": false, "responsive_web_grok_image_annotation_enabled": true, "responsive_web_grok_imagine_annotation_enabled": true, "responsive_web_grok_community_note_auto_translation_is_enabled": true, "responsive_web_enhance_cards_enabled": false
 },
 "txid_ingredients_2026_09_05": {"key_bytes_len": 48, "frames": {"0": 2, "1": 2, "2": 2, "3": 2}, "indices": [12, 4, 40, 27], "ondemand": "https://abs.twimg.com/responsive-web/client-web/ondemand.s.298568e61a87195ea.js", "main_js": "https://abs.twimg.com/responsive-web/client-web/main.1a27b43fa7bf61a8a.js", "animation_key": "6c0ff0e666666666666806e147ae147ae1406e147ae147ae140e666666666666800"}
}
```

## 원래 작업 디렉터리 통합

2026-09-05: PR #3의 원격 main 머지는 완료됐으나 원래 작업 디렉터리는 Threads 브랜치에 남아 있어 Twitter 파일이 보이지 않았다. 사용자 지적에 따라 깨끗한 `feat/threads-skill` 작업 트리에 `origin/main`을 병합했다. Threads 소스·테스트는 그대로 보존하고 README·하네스 스펙·CI·ignore의 병행 추가를 모두 유지해 충돌을 해결했다. 사용자 스코프 Twitter 링크도 `/Users/seongjin/Coding/Agentic SNS/.claude/skills/twitter`로 옮긴다.
