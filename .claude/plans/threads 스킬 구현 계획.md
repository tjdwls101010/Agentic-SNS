# `threads` 스킬 구현 계획

계획 세션: 2026-09-05. 구현 세션은 이 파일만 읽고 시작할 수 있어야 한다. 아래 수치는 전부 이 세션에서 Aside `u0`로 실측한 값이다(라우트 GET 약 40회, GraphQL 약 60회, 탭 캡처 12세션). codex(gpt-6-astra, medium) 적대적 리뷰 1회(22건)를 반영했다(맨 끝 절). 오퍼레이션 16항목(읽기 경로 13종 + 대체·보조 3종)의 doc_id·플래그·변수 템플릿·리프·검증 방법은 이 문서 끝의 **레지스트리 스냅샷** JSON 블록에 통합돼 있고 P0의 `registry.json` 초안은 그 블록을 그대로 읽어 만든다. 형제 계획 `reddit 스킬 구현 계획.md`·`facebook 스킬 구현 계획.md`와 같은 구조이며, 이 세션은 `reddit` 스킬 파일을 건드리지 않는다(다른 세션이 구현 중).

## Context

성진은 클로드가 Threads를 **사람처럼** 쓰기를 원한다. 홈 피드를 훑다가 글을 열고, 답글과 인용을 읽고, 작성자의 프로필·스레드·답글·리포스트를 보고, 팔로워를 살피고, 검색하는 흐름을 스크린샷·클릭 없이 밀도 높은 텍스트로 수행한다. 시각 UI 대신 Threads 웹 클라이언트가 실제로 쓰는 Meta 지속 쿼리(`POST /graphql/query`, `doc_id`+`variables`)와 라우트 HTML에 서버가 미리 실어 보내는 Relay 페이로드를 직접 읽고, 로그인은 이미 로그인된 **Aside 브라우저** 세션을 `aside repl`의 `fetch`로 빌린다.

이전 시도 `.tmp/Agentic Threads`(PyPI `agentic-threads` v0.1.1, 6,132줄)는 기술적으로 동작했지만 세션을 스스로 소유했다. 코드의 약 40%(`session.py` 926줄·`auth.py` 655줄·`docids.py` 520줄·`config.py`·`cli.py`의 login/setup/status)가 "로그인된 브라우저가 없다"는 전제 때문에 있었고, 그 층이 scrapling과 쿠키 파일을 끌고 왔다. Aside 위에 올리면 그 층이 사라지고, 검증된 봉투 워커(`parse.py`)·모델(`model.py`)·오류 분류 표식(`client.py`)·페이지네이션 오케스트레이터(`retrieve.py`의 커서 규칙)만 남는다. 2026-07-23 정찰의 doc_id 12종은 **이번 실측에서 전부 `execution error`를 냈다**. 6주 사이에 회전했고, 게시물 화면의 오퍼레이션 계열 자체가 `PostColumnPage` → `PostPageStrongId{Target,Downward,Upward}`로 바뀌었다. 옛 코드의 doc_id 채굴기(`docids.py`)는 가져오지 않고, 이번에 실측한 **라우트 HTML preloader** 경로로 대체한다.

facebook·reddit과 같은 하네스 프레임을 코드에 닿게 적용한다. **principle over rail**: SKILL.md는 규칙 나열이 아니라 Threads의 사실과 그 결과를 쓴다. **interface over document**: 명령·플래그·종료 코드·복구 명령은 `--help`와 출력 자체가 가르치고 SKILL.md는 "언제·왜·무엇이 물었나"만 쓴다. **for user not developer**: 읽는 이는 사용 시점의 클로드다. 기본 출력은 밀도 높은 텍스트이고 전체 JSON은 요청할 때만 나온다. **dense information**: 게시물 하나는 3~4줄, 답글은 2~3줄이며 다음 홉의 핸들(`@handle`, URL)을 항상 싣는다.

Threads가 형제와 다른 점 셋이 설계를 결정한다. **게시물 화면은 HTML 한 번이 전부다**: 게시물·부모 체인·첫 답글 10개(각 답글의 하위 답글 포함)가 라우트 HTML의 SSR 페이로드로 오고, **그 다음 답글은 외부에서 받을 수 없다**(브라우저 자신의 요청을 같은 페이지 안에서 동일 재생해도 `null`). **레이트리밋 헤더가 없다**: 예산은 클라이언트가 스스로 세야 하고, Meta는 자동화에 체크포인트를 건다. **doc_id가 회전하고 Relay 플래그 세트가 오퍼레이션마다 다르다**(4~36개): 레지스트리와 `refresh`가 필요하다.

## 확정된 결정 (성진, 2026-09-05)

| # | 결정 | 결과 |
|---|---|---|
| D1 | **실계정(Aside `u0`, `@tjdwls101010`) 로그인 세션 사용** | 홈 피드 추천·팔로잉, 좋아요·저장 목록이 열린다. 요청 간격 하한·예산·차단 상태를 코드에 고정한다. |
| D2 | **읽기 전용** | 좋아요·답글·팔로우·저장·리포스트는 스펙에 `declined`. 브라우저가 활동 페이지를 열 때 보내는 "읽음 처리" mutation도 보내지 않는다. |
| D3 | **개인 표면은 홈 피드(추천/팔로잉)·좋아요한 글·저장한 글 포함, 활동(알림) 제외** | `me liked\|saved`. `/activity`는 `declined`(사적 성격, 열람이 곧 읽음 처리). |
| D4 | **팔로워·팔로잉 목록 포함** | `graph <@name> followers\|following`. 팔로잉 수는 이 경로에서만 나온다. |
| D5 | **Claude 헤드리스 e2e 미실행** | codex가 SKILL.md·`--help`·실제 출력만으로 시나리오를 수행하는 사용성 검토와 `pytest -m live`로 대체. |
| D6 | 본문·`--help`·주석은 영어, description 트리거에 한국어 표현 포함 | 스펙·커밋·PR은 한국어. |
| D7 | **스킬은 완결적** | facebook·reddit 모듈을 import하지 않고 복사한다. `tests/threads/` 아래에 스킬별 테스트. |
| D8 | 배포는 레포 `.claude/skills/threads`가 원본, `~/.claude/skills/threads` 심볼릭 링크 | facebook·reddit과 같은 관례. |
| D9 | SKILL.md는 ultra-search처럼 **헤딩 위계가 있는 구조** | 골격은 아래 절. 길이는 완료 기준이 아니다. |

## 실측 사실 장부

아래는 이 세션에서 `aside --account u0 repl`로 직접 확인한 것이다. 구현 세션은 재실측 없이 이 값으로 시작한다. 단, doc_id와 플래그 세트는 스냅샷이며 `refresh`가 갱신 수단이다.

### 접근·세션·계약

- **F1** Aside `u0`는 Threads에 `@tjdwls101010`(actor `17841463402945725`, userID `63485801431`)으로 로그인돼 있다. `threads.net`은 `threads.com`으로 301된다.
- **F2 라우트 HTML은 헤더 세트에 따라 두 가지가 온다.** `accept: text/html`만 주면 268KB 껍데기(preloader·`DTSGInitialData` 없음). facebook F2와 같은 내비게이션 세트(`user-agent`, `accept: text/html,…`, `accept-language`, `sec-fetch-dest: document`, `sec-fetch-mode: navigate`, `sec-fetch-site: none`, `upgrade-insecure-requests: 1`)를 주면 600~840KB 전체 문서가 온다. 전체 문서에 `"csrf_token":"…"`, `"DTSGInitialData",[],{"token":…}`, `"LSD",[],{"token":…}`, `"__spin_r"`, `"NON_FACEBOOK_USER_ID":"<actor>"`, `"username":"<viewer>"`가 있다.
- **F3 GraphQL 최소 계약이 성립한다.** `POST https://www.threads.com/graphql/query`, 폼 본문 `doc_id=…&variables=<JSON>` **둘뿐**, 헤더 `content-type: application/x-www-form-urlencoded`, `x-csrftoken`(HTML의 `csrf_token`), `x-ig-app-id: 238260118697367`, `x-fb-friendly-name: <오퍼레이션명>`, `origin`, `referer`. `fb_dtsg`·`jazoest`·`lsd`·`__spin_*`·`__dyn`류 Meta 봉투는 **필요 없다**(전체 봉투로 보내도 결과가 같다). 옛 정찰 Q-A/Q-B가 그대로 성립한다.
- **F4 레이트리밋 헤더가 없다.** `x-ratelimit-*`·`retry-after`·`x-ig-set-www-claim` 전부 null. 429·체크포인트는 이 세션에서 유발하지 않았다. 옛 `client.py`가 실측해 둔 표식: 요청 제한 오류 코드 `4, 17, 613, 80004`와 문구 `rate limit`/`too many request`/`try again later`, 체크포인트 오류 코드 `368, 459`와 문구 `challenge`/`checkpoint`/`consent_required`, 세션 만료 문구 `login_required`/`session expired`·`/accounts/login` 리다이렉트·HTML `checkpoint_required`/`challenge_required`/`"checkpoint_url"`.
- **F5** Aside `fetch`는 쿠키를 항상 싣는다(`credentials: "omit"`을 무시). 익명 응답 형태는 이번에 관측하지 못했다(A1).
- **F6** REPL 제약은 facebook F8과 같다. Aside `page`는 `cdp`·`on`이 있지만 **`Network.*`·`Page.addScriptToEvaluateOnNewDocument`가 허용 목록에 없고 `on("request")`는 이벤트를 내지 않는다**. 따라서 브라우저 요청 캡처는 "페이지가 렌더된 뒤 `window.fetch`/`XMLHttpRequest`를 감싸고, **앱 안 클릭(SPA)**으로 다음 화면을 열어 그 화면의 요청을 잡는" 방식뿐이다. `page.reload()`·`goto`·합성 앵커 클릭은 훅을 잃는다. **`/@name` 프로필을 `openTab`으로 직접 열면 127자 빈 껍데기만 렌더되고**(제목만 바뀜), 게시물 페이지는 직접 열어도 렌더된다. 탭 프로브를 두 프로세스가 동시에 돌리면 백그라운드 탭이 렌더를 멈춘다. 캡처 흐름은 **게시물 페이지에서 시작**해 작성자 링크 → 프로필 → 팔로워 모달(팔로워 탭 → 팔로잉 탭 → 모달 스크롤) → 검색창 입력 → 사이드바 좋아요·저장 순으로 SPA 이동한다. 이미 Relay 캐시에 있는 화면은 다시 열어도 요청이 없으므로 오퍼레이션마다 "관측 완료 조건·제한 시간·missing 사유"를 정한다.

### 오퍼레이션 카탈로그 (2026-09-05 스냅샷, 회전함)

| 사람의 동작 | 오퍼레이션 | doc_id | 변수(플래그 제외) | 플래그 수 | 응답 리프 | 크기·지연 |
|---|---|---|---|---|---|---|
| 홈 피드(라우트 preloader, **A5 확인**) | `BarcelonaFeedDirectQuery` | `28427931060136602` | `{data:{pagination_source:"text_post_feed_threads"\|"text_post_feed_following", reason:"cold_start_fetch"\|"pagination"}, variant:"for_you"\|"following"}` (+`after`) | 31 | `feedData.edges[].node.text_post_app_thread.thread_items[].post`, `feedData.page_info` | 1페이지 4건 63KB, `after` 2페이지 7건 257KB 중복 0 |
| 홈 피드(브라우저 스크롤용, 대체 경로) | `BarcelonaFeedPaginationDirectQuery` | `28422906420733414` | `{after, before:null, first:10, last:null, sort_by:null, variant:"for_you"\|"following", data:{feed_view_info:"[]", pagination_source:"text_post_feed_threads"\|"text_post_feed_following", reason:"pagination"}}` | 31 | `feedData.edges[].node.text_post_app_thread.thread_items[].post`, `feedData.page_info` | 1페이지 4~7건, 55~273KB/1.2~2.3s. `first`는 무시된다(25를 줘도 4건) |
| 프로필 헤더 | `BarcelonaProfilePageDirectQuery` | `28459403360351848` | `{userID, canSeeFeedsTab:true, showLinkedIGStats:false}` | 11 | `user` | 5.6KB/0.6s |
| 프로필 스레드 탭 | `BarcelonaProfileThreadsTabDirectQuery` | `28581921448092834` | `{userID, first:4, allow_page_info_for_lox_user:false}` (+`after`) | 32 | `mediaData.edges[].node.thread_items[].post`, `mediaData.page_info` | first 4→91KB/1.1s, **first 25→15건 반환** 336KB/4.9s, `after`로 2페이지 15건 중복 0 |
| 답글 탭 (**A2 확인**) | `BarcelonaProfileRepliesTabDirectQuery` | `38355698004046040` | `{userID, first:4}` (+`after`) | 32 | 같음 | first 25→15건 514KB, `after` 2페이지 15건 중복 0 |
| 리포스트 탭 | `BarcelonaProfileRepostsTabDirectQuery` | `28800390459553524` | `{userID, first:4}` | 32 | 같음(`share_info.reposted_post`) | 49KB |
| 미디어 탭 | `BarcelonaProfileMediaTabDirectQuery` | `38191639027147618` | `{userID, first:4}` | 32 | 같음 | first 10→586KB/3.4s |
| 게시물 검색 | `BarcelonaSearchResultsQuery` | `28325705367048600` | `{query, search_surface:"default"\|null\|"tags", recent:0\|1, tagID:null, meta_place_id:null, power_search_info:null, trend_fbid:null}` (+`after`) | 36 | `searchResults.edges[].node.thread.thread_items[].post`, `searchResults.page_info` | 10건 250~590KB/1.9~3.3s, `after` 2페이지 10건 |
| 계정 검색 | `useBarcelonaAccountSearchGraphQLDataSourceQuery` | `27817458954582836` | `{query, first:10, should_fetch_friendship_status:false, should_fetch_fediverse_profiles:true, should_fetch_ig_inactive_on_text_app:null, should_fetch_tag_and_mention_restrictions:false, hide_unconnected_private:false, is_internal_user:false}` | 3 | `xdt_api__v1__users__search_connection.edges[].node` (page_info 없음) | 14건 13.5KB/0.7s, `errors`에 `field_exception`이 실려도 데이터는 온다 |
| 팔로워 | `BarcelonaFriendshipsFollowersTabQuery` | `28335060419422716` | `{userID, first:20}` | 4 | `user.followers.edges[].node`, `counts` | 20건 48KB/1.1s. **5.7M 계정도 `has_next_page:false`**(서버가 20명까지만 준다) |
| 팔로잉 | `BarcelonaFriendshipsFollowingTabQuery` | `28280885978174653` | `{userID, first:20}` | 4 | `user.following.edges[].node`, `counts{followers, following, mutuals}` | 20건 22KB/0.8s, `end_cursor:"20"` |
| 팔로잉 이어읽기 | `BarcelonaFriendshipsFollowingTabRefetchableQuery` | `27339952475679383` | `{id:userID, first:10, after:"20"}` | 3 | `fetch__XDTUserDict.following.edges[].node` | 10건 10KB/0.7s, 커서는 **숫자 오프셋 문자열** |
| 좋아요한 글 | `BarcelonaLikedPageViewerQuery` | `38611212625136673` | `{}` | 31 | `xdt_text_app_viewer.liked_media.edges[].node.thread_items[].post`, `.page_info` | 251KB/1.9s |
| 저장한 글 | `BarcelonaSavedPageViewerQuery` | `28336699875962760` | `{}` | (캡처됨) | `xdt_text_app_viewer.…` | 391바이트(계정에 저장 글 없음, 형태 미확인 A3) |

- **F7 게시물 화면은 SSR 페이로드다.** `GET /@<user>/post/<code>`(내비게이션 헤더) → 840KB/1.3s. `<script type="application/json">` 블록들 안의 `__bbox.result.data` 5개: `viewer`, **Target**(`media`: 게시물 본체, `text_post_app_info.direct_reply_count` 등), **Upward**(`media.text_post_app_info.containing_thread.posts.edges[]`: 부모 체인, 루트 글이면 0), **Downward**(`media.text_post_app_info.direct_replies.edges[].node.posts.edges[].node`: 답글 10개, 각 답글 노드에 1~2개 post(답글과 그 하위 답글), `page_info{end_cursor, has_next_page}`, 노드마다 `fetch_token`), 그리고 뷰 카운트. 같은 URL에 `?sort_order=recent`를 붙이면 Downward가 최신순 8개로 바뀐다. **preloader에 `"postID":"<숫자>"`가 있어 shortcode→postID 변환이 정규식 하나다**(옛 4후보 디코딩 불필요). 답글 하나의 자기 페이지(`/@<replier>/post/<code>`, 758KB)도 같은 구조로 그 답글의 하위 답글 2개와 부모 1개를 준다.
- **F8 답글 11번째 이후는 외부에서 받을 수 없다.** 브라우저는 스크롤 시 `BarcelonaPostPageStrongIdDirectRepliesRefetchQuery`(`28456164537310692`, `{postID, after}`, 32플래그)를 14회 보내 20~59KB씩 받는다. 그 요청을 **같은 페이지 안에서 폼·헤더까지 동일하게 재생하면 289바이트 `direct_replies: null`**이다(2회 확인). SSR 커서를 그대로 보내도, 커서(base64 JSON `{t:"downward_other_replies", ts, ex:[본 id들], sc:10, nr:10}`)의 `ts`를 현재로 바꾸거나 `ex`를 SSR의 id로 채워 위조해도, `after:null`로 보내도 전부 `null`이다. `BarcelonaPostPageStrongIdDownwardQuery`(`28855004007435047`)를 GraphQL로 직접 부르는 것도 브라우저 자신의 요청까지 `null`을 받는다(SSR로만 답을 준다). 즉 **현재 재생 방식으로는 SSR 밖의 직접 답글을 이어 읽을 수 없다**(브라우저가 받은 추가 응답을 읽는 다른 방법이 없다는 증명은 아니다. 다음 패스의 질문). 도구가 줄 수 있는 것은 HTML 1회(인기순 10개, 하위 답글 포함) + HTML 1회(최신순 8개, 인기순과 **겹칠 수 있다**) + 답글별 자기 페이지(그 답글 **아래**만 보이고 형제 누락은 줄지 않는다)이며, 수치는 아래 출력 계약의 완전성 필드로 구분해 표시한다.
- **F9 라우트 HTML preloader가 refresh 수단이다.** 전체 문서에 `"preloaderID":"adp_<Op>RelayPreloader_<hash>","queryID":"<doc_id>"…"variables":{…}` 항목이 있고 프로필·검색 라우트의 값이 브라우저 요청과 일치했다. 라우트별 발견: `/` → `FeedDirectQuery`(`28427931060136602`, 초기 피드, `{data:{pagination_source, reason:"cold_start_fetch"}, variant}`)·`HomeContentQuery`; `/@zuck` → `ProfilePageDirectQuery`·`ProfileThreadsTabDirectQuery`; `/@zuck/{replies,reposts,media}` → 각 탭 Direct; `/@u/post/<code>` → `StrongId{Downward,Target,Upward}`·`PostViewCountQuery`; `/search?q=…&serp_type=default|recent|tags` → `SearchResultsQuery`; `/liked` → `LikedPagePrivateLikesQuery`(빈 stub, 목록은 `LikedPageViewerQuery`가 지연 로딩); `/saved`·`/activity`·`/search?from_author=` → preloader 없음(지연). `__d("<Op>_facebookRelayOperation")` 번들 채굴은 **Threads에서 0건**(27스크립트 20MB). `AccountSearch`·`Friendships*` 3종·`LikedPageViewer`·`SavedPageViewer`는 preloader에 없어 **탭 캡처(F6 흐름)로만 갱신**된다(`FeedPagination`도 없지만 A5로 `FeedDirect`가 대신한다).
- **F10 식별자.** `username → userID`는 프로필 HTML의 **`ProfilePageDirectQuery` preloader 항목의 `variables.userID`**에서 읽는다(전역 첫 `"userID"` 매치는 viewer·인용·추천 대상과 섞여 다른 사람을 줄 수 있다. zuck → `63055343223`, `"pk"`와 같다). `code → postID`도 게시물 HTML의 `StrongIdTargetQuery` preloader `variables.postID`에서 읽고, SSR 결과의 `media.pk`·`media.code`가 요청과 같은지 검증한다. 없는 사용자 `/nonexistent_user_zz_12345` → 200이지만 268KB 껍데기, preloader 없음. 없는 게시물 `/@zuck/post/NOPE12345` → 200이지만 최종 URL이 `/@zuck`(프로필로 리다이렉트). `ProfilePageDirectQuery`에 없는 userID → `{"errors":[{"message":"execution error","path":["user"]}],"data":{"user":null}}`. 짧은 링크 `/t/<code>`·`threads.net`·`threads.com`(www 없음)은 301로 정식 URL을 준다(로컬 규칙으로 변환 가능).
- **F11 객체 필드.** 게시물(`post`): `pk`, `id`(`<pk>_<userpk>`), `code`, `user{pk, id, username, full_name, is_verified, profile_pic_url, friendship_status{following, followed_by}, text_post_app_is_private}`, `caption{text}`, `taken_at`(초), `like_count`, `has_liked`, `media_type`(1 이미지·2 동영상·8 캐러셀·19 텍스트), `image_versions2`, `video_versions`, `carousel_media`, `canonical_url`, `text_post_app_info{direct_reply_count, repost_count, quote_count, reshare_count, is_reply, reply_to_author, share_info{quoted_post, reposted_post, is_reposted_by_viewer}, link_preview_attachment, pinned_post_info, reply_control, self_thread_count}`, `like_and_view_counts_disabled`. 프로필(`user`): `username`, `full_name`, `biography`, `follower_count`(**`following_count` 없음** → 팔로워 대화상자의 `counts`에서), `is_verified`, `text_post_app_is_private`, `bio_links[]`, `profile_pic_url`, `hd_profile_pic_versions`. 계정 검색 노드: `username, pk, full_name, is_verified, follower_count, text_post_app_is_private`.
- **F11b 답글 관계.** Downward의 `direct_replies.edges[].node.posts.edges[]`는 "답글 스레드"이며 첫 post가 직접 답글이고 뒤는 그 답글자의 이어쓰기 또는 하위 답글이다. 관계는 배열 순서가 아니라 각 post의 `text_post_app_info.reply_to_id`·`is_reply`·`reply_to_author`(옛 `build_post`가 쓰던 필드)로 판정한다(A8: 이번 표본에서 `reply_to_id`의 존재를 직접 확인하지 않았다. 없으면 `thread continuation`으로 표시하고 `reply-to`를 만들지 않는다).
- **F12** 옛 파서 `parse.py`의 `ENVELOPE_ROOTS`/`_POST_THREAD_ITEM_PATHS`는 오퍼레이션별 리프 경로 지도이며 위 표의 경로로 갱신하면 그대로 쓸 수 있다. `model.py`의 `build_post`(인용·리포스트 재귀, `reply_to_id`, 미디어 판정)·`build_user`는 필드가 그대로다.

## 설계

### 실행 모델

```
threads.py <cmd> ──▶ Python(stdlib) ──spawn──▶ aside --account u0 repl <page.js | graphql.js> ──▶ Aside fetch ──▶ www.threads.com
      ▲                                                                │
      └── {status, url, body} ◀─────────────────────────────────────────┘
```

- **한 `aside repl` 호출 = 한 요청.** facebook·reddit과 같은 이유. `# 성진` 주석 동일.
- **`page.js`**: `ARGS {path}` → `GET https://www.threads.com<path>`, 내비게이션 헤더 세트(F2), `redirect: "manual"`(3xx는 `status`·`location`으로). 호스트는 코드가 `www.threads.com`으로 고정한다. **`graphql.js`**: `ARGS {name, doc_id, variables, csrf, referer}` → 최소 계약(F3) POST 하나. 두 스니펫 다 12MB 조각 전송 경로를 facebook `graphql.js`에서 옮긴다(실측 최대 840KB).
- **세션 토큰은 `csrf_token` 하나이고 호출마다 대상 라우트 HTML에서 뽑는다.** `post`·`about`·`user`는 어차피 라우트 HTML을 먼저 읽으므로 추가 비용이 없고, `home`·`search`·`me`·`graph`는 홈 HTML 1회(700KB, 0.5~3s)가 선행한다. 디스크에 저장하지 않는다.
- **판정은 Python 한 곳(`_transport.classify`)에서, 엔드포인트별 기대 봉투를 가지고, 이 순서로.** 문구 검색은 **정규화한 오류 객체 안에서만**(GraphQL: `errors[]`·`error`·`error_code`·subcode를 하나의 목록으로 정규화) 하고, HTML은 최종 URL과 확인된 구조(로그인 폼·challenge 라우트)로만 판정한다. 게시물 본문·번들 문자열에 `challenge`·`try again later`가 들어 있어도 차단되지 않아야 하며 P1 픽스처가 그 반례를 갖는다.
  1. **체크포인트(최우선)**: 최종 URL이 `/challenge`·`/checkpoint`, 정규화 오류 코드 `368|459`, 오류 객체 문구 `checkpoint`/`challenge`/`consent_required`, HTML의 `checkpoint_required`/`challenge_required`/`"checkpoint_url"` → **만료 없는 차단**(exit 5). 429와 함께 와도 체크포인트가 이긴다. 기존 `checkpoint` 차단은 `rate_limit`으로 덮어쓰지 못한다.
  2. 요청 제한: HTTP 429(체크포인트 표식 없음), 정규화 오류 코드 `4|17|613|80004`, 오류 객체 문구 `rate limit`/`too many request`/`try again later` → 30분 만료 차단(exit 5).
  3. 로그인: 최종 URL이 `/accounts/login`·`/login`, 전체 문서인데 `csrf_token`·`NON_FACEBOOK_USER_ID`·`"username"`이 없음, 정규화 오류에 `login_required`/`session expired`/CSRF 거부 → exit 4(`fix`: Aside에서 Threads 로그인 후 doctor). 껍데기 HTML(268KB, DTSG 없음)은 요청 헤더 문제·없는 대상·로그아웃이 겹치므로 **단독으로는 판정하지 않는다**.
  4. 일반 HTTP 실패·5xx·비JSON·잘린 JSON → exit 6 `error=transient`, 차단하지 않는다.
  5. 대상 없음·닫힘(exit 9)은 **명시적 증거에만**: 게시물 URL이 프로필로 리다이렉트됨(최종 URL에 `/post/` 없음); 내비게이션 헤더로 받은 프로필 라우트 응답에 viewer `username`은 있는데 `ProfilePageDirectQuery` preloader가 없음(없는 사용자의 실측 형태); 프로필 SSR `user.text_post_app_is_private:true`이고 `friendship_status.following:false`이며 탭 edges가 빔(`reason=private`, A4). `data.user:null`은 라우트 판정이 이미 "없음"일 때만 9이고, 그 외의 null은 6이다.
  6. 봉투(exit 6, `fix`가 갈린다): `errors[].severity=="CRITICAL"`이면서 `data`가 비었으면 `error=operation_rotated`(fix: run refresh); 전체 문서에 preloader·`__bbox` 구조가 없으면 `error=envelope_drift`(fix: refresh, 그래도 안 되면 문의); 기대 리프가 없으면 `envelope_drift`. 페이지네이션 표면에서 `page_info` 누락은 6이지 소진이 아니다.
  7. 정직한 0건(exit 7): 선택한 결과 표면의 `edges`가 명시적으로 빈 배열이고 `page_info.has_next_page`가 false일 때만. `edges:[]`인데 `has_next_page:true`면 커서를 진행한다(예산 안에서).
- **오퍼레이션별 페이지네이션 정책**을 레지스트리가 선언한다: `relay`(커서), `offset`(팔로잉 숫자 문자열), `single_batch`(계정 검색·프로필 헤더), `capped`(팔로워 20명), `ssr_only`(Downward). `exhausted`는 `has_next_page:false`가 명시된 `relay`·`offset`에서만 쓰고, `capped`는 `server_capped`, `single_batch`는 `not_paginable`로 끝난다.
- **레지스트리는 데이터다.** `scripts/registry.json`에 스냅샷의 16항목을 `{doc_id, flags:{…}, variables_template, leaf, pagination, verified, captured_at}`로 싣고, `refresh`는 `~/.cache/threads-skill/registry.json`에 오퍼레이션별 병합으로 오버라이드를 쓴다(facebook `_registry`·`_refresh` 구조). 로드 순서: 오버라이드 → 번들.
- **`refresh`는 두 단계이고 항목마다 발견 경로·검증 방법이 스냅샷 JSON에 일대일로 적혀 있다.** 기본(탭 없음): 라우트 HTML 7개(`/`, `/@<viewer>`, `/@<viewer>/{replies,reposts,media}`, `/search?q=a&serp_type=default`, viewer의 첫 글 `/post/<code>` 또는 `--post URL`)에서 preloader의 `(op, doc_id, variables)`를 읽어 **10종**(FeedDirect·ProfilePage·탭 4종·SearchResults·StrongId 3종)을 얻고, POST 재생이 가능한 7종은 재생으로, SSR 전용 3종(StrongId)은 SSR 파싱으로 검증한 것만 저장한다. viewer에게 글이 없으면 `--post URL`이 필요하다고 정직하게 말한다. `--capture`(탭 1개): 게시물 페이지를 열어 훅을 심고 SPA로 작성자 → 프로필 → 팔로워 모달(팔로워 탭 → 팔로잉 탭 → 스크롤) → 검색창 입력 → 사이드바 `/liked/`·`/saved/`를 수행해 **6종**(AccountSearch·Followers·Following·FollowingRefetchable·LikedViewer·SavedViewer)을 캡처한다. 캡처 뒤 각 항목은 POST 재생으로 검증하고, 캡처한 variables의 **플래그만** 오퍼레이션별로 병합한다(facebook의 공통 유니언이 아니라 오퍼레이션별 세트).
- **캡처의 보장 범위(D2를 좁힌다).** 캡처는 도구가 요청을 보내는 것이 아니라 브라우저 탭이 정상 방문처럼 움직이는 것을 관측한다. 훅 설치 전 bootstrap 요청은 셀 수 없고, 앱은 스스로 조회수·seen류 mutation을 보낼 수 있다. 그래서 CLI가 보내는 요청에는 mutation이 없다는 것만 보장하고, 캡처 중 앱이 보낸 요청은 "관측된 요청 수"로 별도 보고한다. 차단 신호(체크포인트·429)를 관측하면 즉시 SPA 흐름을 멈추고 차단 파일을 쓴다. 탭 닫기는 `finally`에서 하고, Python이 죽어도 다음 `doctor`가 열린 캡처 탭을 보고한다.

### 예산 계약 (`_budget.py`)

- Threads는 남은 수를 알려주지 않으므로 **예산은 전적으로 로컬**이고 출력은 항상 `local budget`이라고 적어 서버 잔여량으로 오해되지 않게 한다.
- **호출 간 합산 창.** `~/.cache/threads-skill/budget.json`에 최근 10분의 요청 시각 목록을 두고(잠금 안에서 갱신), 창 안 합계가 **120회**를 넘으면 요청 없이 exit 5(`rate_limit`, 창이 비는 시각을 `fix`에). `--limit 3`이든 반복 `more:`든 이 창을 벗어날 수 없다. `# 성진: 120회/10분·1초 하한은 헤더 없는 실계정 보호용 추정치, 체크포인트가 관측되면 낮춘다`.
- **호출당 상한과 표시 목표는 별개다.** 요청 간 하한 1.0초(+0~0.5초 지터), 플래그로 못 낮춘다. 호출당 요청 상한은 기본 10회, 명시적 `--limit`·`--since`·`--out`이 있으면 40회, 절대 상한 60회. `--limit`은 표시·수집 목표이지 요청 상한이 아니므로 날짜 필터가 대부분을 버리는 조회도 40회에서 멈춘다(exit 8, `budget`).
- **차단 상태** `~/.cache/threads-skill/blocked.json`은 facebook `_blocked`를 그대로 쓴다(`checkpoint` 무만료, `rate_limit` 30분). 요청 주기는 `account_lock` 안에서 돈다(파일 재읽기 → 차단 판정 → 창 합산 → 페이싱 → 요청 → 판정 결과·시각 저장).
- **응답이 크다는 것이 진짜 비용이다.** 게시물 HTML 840KB, 검색 1페이지 500KB, 미디어 탭 586KB. 헤더에 `fetched 2.1MB`를 적는다.

### 식별자 계약 (`_target.py`)

- identity는 게시물 `pk`(숫자)와 사용자 `pk`(숫자). 표시 핸들은 `@username`과 정식 URL `https://www.threads.com/@<user>/post/<code>`.
- `Target(kind ∈ {user, post, me, query}, username, user_id, code, post_id)`. 옛 **`auth.py`의 순수 식별자 함수**(`normalize_user_identifier`, `normalize_post_identifier`, `_threads_url_identifier`, 정규식 `_USERNAME_RE`·`_SHORTCODE_RE`)만 이식하고 URL 형태를 추가한다: `@name`, `name`, `/@name`, `/@name/{replies,reposts,media}`, `/@name/post/<code>`, `/t/<code>`, `threads.net`·`threads.com`·`www` 변형, 트레일링 슬래시·쿼리. 숫자만 있는 대상은 username으로 본다(숫자 ID로 라우트를 만들 수 없으므로 `--by id`는 두지 않는다). `/activity`·`/settings`·커뮤니티 등 범위 밖 라우트는 exit 2. 옛 `shortcode_to_post_id_candidates`는 가져오지 않는다(F7).
- **`username → userID`는 프로필 HTML 정규식**(F10), **`code → postID`는 게시물 HTML preloader 정규식**(F7). 둘 다 그 화면을 읽는 GET에서 함께 나오므로 해석 전용 요청은 없다. `/t/<code>`는 `page.js`의 `redirect: "manual"` 1회로 `location`을 얻고(호스트 `www.threads.com`·경로 `/@<user>/post/<code>` 형태·홉 ≤ 3 검증) 정식 페이지 GET이 이어지므로 **2요청**이다(예산 포함).

### 명령 표면 (`threads.py --help`가 진실, 여기는 설계 의도)

사람이 Threads에서 하는 동작을 Threads의 명사로 만든다. 모든 읽기 명령은 같은 출력 옵션(`--json`, `--chars`, `--out`, `--limit`, `--after`)을 공유한다. `--out FILE`은 facebook·reddit과 같은 로컬 저장이다(페이지 단위 NDJSON 커밋·이어받기, 게시물은 글 한 줄 뒤 답글 평탄 레코드).

| 명령 | 사람의 동작 | 받는 대상 | 요청 |
|---|---|---|---|
| `home [--feed foryou\|following]` | Threads를 연다 | 없음 | 홈 HTML 1(csrf; SSR 첫 4건은 `for_you`일 때 재사용) + `FeedDirect` 페이지당 1(4~7건) |
| `user <@name\|url> [--tab threads\|replies\|reposts\|media] [--since --until]` | 프로필의 탭을 본다 | user | 프로필 HTML 1(userID·csrf; 스레드 탭이면 SSR 첫 4건 재사용) + 탭 Direct 페이지당 1(`first:25`, ≤15건). 다른 탭의 라우트 HTML은 받지 않는다 |
| `about <@name\|url>` | 프로필 카드를 본다 | user | 프로필 HTML 1(SSR `user`) + `FollowingTab` 1(`counts`). 두 절은 독립이다: counts 실패는 `following=unknown`으로 남기고 exit 8, 팔로잉 0명은 counts가 정상이면 7이 아니다 |
| `post <url\|code> [--sort top\|recent]` | 글을 연다: 본문 + 부모 체인 + 첫 답글 배치 | post | 게시물 HTML **1회** |
| `graph <@name\|url> followers\|following` | 팔로워 수를 누른다 | user | 프로필 HTML 1 + `Friendships*Tab` 1 + 팔로잉은 `Refetchable` 페이지당 1 (`following --limit 25` = 3요청). 팔로워는 서버가 20명에서 끊는다(`server_capped`) |
| `search <text> [--type posts\|users] [--sort top\|recent] [--tag]` | 검색창 | 자유 텍스트 | 홈 HTML 1 + `SearchResults`(10건, 250~590KB) 또는 `AccountSearch` 1 |
| `me liked\|saved` | 내 좋아요·저장 | 없음 | 홈 HTML 1 + `*PageViewerQuery` 1. **첫 배치만 지원**(2페이지 오퍼레이션·변수 미캡처, A7) |
| `doctor [--unblock]` | 준비됐나 | — | 홈 HTML 1: aside·로그인(`username`)·차단 상태·레지스트리 나이 한 줄 |
| `refresh [--capture]` | 깨졌을 때 고치기 | — | 라우트 6~7 GET + 재생 검증 POST; `--capture`는 탭 1개 |
| `schema` | 객체 필드 설명 | — | Post·User·Media·Counts를 `to_dict()`에서 유도. 요청 0회 |

**`post`의 동작.** HTML 1회로 SSR 5개 페이로드를 파싱한다. 출력 순서: 부모 체인(Upward, 있으면 `[parent]` 라벨) → 게시물 전문 → 답글 10개(각 답글 아래 하위 답글은 들여쓰기). `--sort recent`는 `?sort_order=recent`로 같은 GET을 다시 한다. 완전성은 서로 다른 수를 섞지 않는다: `reported_direct`(Threads가 말한 직접 답글 수), `received_direct`(SSR로 받은 직접 답글), `shown_direct`, `shown_descendants`(하위 답글), `unshown_received`(`--limit`으로 안 보인 것), `unavailable`(톰스톤), `unfetched≈max(reported−received−unavailable, 0)`(**추정치**, 서버 집계가 흔들리면 `unknown`). 헤더는 `replies: 10 of ~172 direct received (unfetched ≈162, estimate) · +2 descendants`처럼 쓰고, 끝줄은 `more:`가 아니라 **`open a reply: post <reply url>` (shows what is under it; missing siblings stay missing) · newest first: --sort recent (may overlap)`**이다(F8). `stop_reason=not_paginable`은 기능 한계이지 완료가 아니며 `--json`·`--out`에도 같은 필드가 실린다.

**`user`의 동작.** 프로필 HTML의 SSR 첫 4건(스레드 탭일 때)을 먼저 쓰고, `--limit`이 그보다 크면 SSR `page_info.end_cursor`로 Direct 쿼리를 잇는다. **SSR 커서가 Direct에서 통하는지는 미검증**(A6, SSR은 `allow_page_info_for_lox_user:false`로 왔다)이므로 P2 라이브가 먼저 확인하고, 통하지 않으면 Direct 1페이지부터 시작해 SSR 4건과 pk로 중복 제거한다. 답글·리포스트·미디어 탭은 처음부터 Direct 쿼리다(라우트 GET 700KB보다 싸다).

**날짜 창.** 서버 필터가 없다. `--since/--until`은 클라이언트 필터이고 최신순 표면(프로필 탭·팔로잉 피드)에서만 받는다. 종료 판단은 평탄화된 post가 아니라 **정렬 단위인 edge의 활동 시각**(edge 안 `thread_items`의 최대 `taken_at`; 리포스트 탭은 리포스트 시각이 없으므로 필터만)으로 하고, 고정글은 제외한다. 시간 단조성이 실측된 표면(프로필 스레드·답글 탭)에서만 `window_reached`를 주장하고, 그 외는 필터만 적용한 `exhausted`/`budget`으로 끝낸다(A9: 팔로잉 피드의 단조성 미확인).

**`--after <n>` 이어읽기.** facebook과 같은 번호 핸들(`~/.cache/threads-skill/cursors/<n>.json`)이며 커서·`userID`·csrf 재취득용 라우트·**아직 안 보인 꼬리 항목**을 담는다. 이어읽기는 홈 HTML 1회(csrf)만 다시 받고 대상 HTML은 다시 받지 않는다. 문맥(명령·대상·탭·정렬·계정)과 충돌하는 인자는 거절하고 `--limit`·`--chars`·`--json`은 자유롭게 바꾼다. 게시물에는 `--after`가 없다(F8).

### 출력 계약

**기본(텍스트).** facebook·reddit과 같은 규약(한 줄 본문, `⏎`, 따옴표 URL, 헤더 한 줄, 끝줄 `more:`). 본문 정규화(공백 접기·제로폭 제거·마크다운 벗기기·링크 축약·빈 필드 줄 생략, reddit 계획과 같은 규칙)를 `_render._text`가 맡는다.

```
home · feed=foryou · 5 shown · stopped=limit · fetched 0.3MB · local budget 8 of 10 (window 112/120)
[p1] @zuck (Mark Zuckerberg ✓) · 2026-09-04T09:13+09:00 · image · likes=1431 replies=172 reposts=143 quotes=12
     "Muse Spark 1.3 is rolling out today with frontier performance almost too cheap to meter. …"
     url: "https://www.threads.com/@zuck/post/Dcy_A8pGo-m"
[p2] @someone · … · text · likes=12 replies=3 · quoting @other: "…" (url: "…")
     "…"   link: "Title of preview" (https://example.com)
     url: "…"
more: python3 "/…/threads.py" home --feed foryou --after 7
open: `post <url>` · person: `user @zuck` / `about @zuck` / `graph @zuck followers`
```

```
post · @zuck/Dcy_A8pGo-m · sort=top · replies: 10 of ~172 direct received (unfetched ≈162, estimate) · +2 descendants · fetched 0.8MB · local budget 9 of 10
[p1] @zuck (Mark Zuckerberg ✓) · 2026-09-04T09:13+09:00 · image(1) · likes=1431 replies=172 reposts=143 quotes=12
     text[full]: "…"
     url: "https://www.threads.com/@zuck/post/Dcy_A8pGo-m"
[r1] @ashbridge30 · 2026-09-04T09:20+09:00 · likes=88 replies=2
     "…"
     url: "https://www.threads.com/@ashbridge30/post/Dcy_9M-ihsR"
  [r2 reply-to=r1] @zuck ✓ · … · likes=40
     "…"
     url: "…"
[r3] [unavailable] · replies hidden by author
open a reply: `post <reply url>` (what is under it; missing siblings stay missing) · newest first: `post <url> --sort recent` (may overlap)
```

- 답글의 `[unavailable]`은 `attachment_tombstone_info`/`is_post_unavailable`. 인용은 `quoting @x: "…" (url)`, 리포스트는 `repost of @y` 뒤에 원글 한 줄. 미디어는 `image(n)`·`video`·`carousel(n)`에 `--json`에서만 URL. 링크 미리보기는 `link: title (url)`. 비공개 계정은 `private`, 인증은 `✓`.
- 사용자 카드(`about`): `@zuck (Mark Zuckerberg ✓) · followers 5.73M · following 464 · mutual 23 · bio: "…" · links: … · url`.
- **`--json`**: 항상 JSON 문서 하나(`{"ok","results","stop_reason","next","budget","fetched_bytes"}`). 실패는 `{"ok":false,"error","message","fix"}`.
- **`stop_reason`**: `limit_reached | exhausted | window_reached | budget | blocked | query_failure | not_paginable`(게시물 답글·계정 검색) `| server_capped`(팔로워 20명, `reported_total` 동반). `--out` 파일의 완료 마커는 `ssr_complete`(게시물)와 `exhausted`를 구분하고 `not_paginable`을 완료로 보지 않는다.
- **종료 코드**: 0 성공 · 2 잘못된 인자 · 3 aside 불가 · 4 Threads 로그인 필요·세션 거부(로그인 URL 리다이렉트 포함) · 5 차단(체크포인트는 `doctor --unblock`, 요청 제한·로컬 창 초과는 만료 뒤 자동 해제, **재시도 금지**) · 6 `error ∈ {transient, envelope_drift, operation_rotated}`로 `fix`가 갈린다(일시 장애는 잠시 뒤 재시도, 회전은 refresh) · 7 정직한 0건 · 8 부분 결과 · 9 대상 없음·비공개·삭제.

### 디렉터리 구조 (최종)

기능 단위 모듈, 책임 하나, 400줄 이하, 엔트리는 argparse와 디스패치만. 파서·모델·SSR 모듈은 transport를 import하지 않는다.

```
Agentic SNS/
├── .claude/
│   ├── harness-spec.md                     # 인벤토리 행 B7(threads)·B8(쓰기 declined)·B9(활동 declined) 추가
│   ├── plans/threads 스킬 구현 계획.md      # 이 파일 (.gitignore 예외 추가)
│   └── skills/threads/
│       ├── SKILL.md
│       └── scripts/
│           ├── threads.py                  # argparse 배선·공통 옵션(default=None)·명령별 허용 Target·디스패치·종료 코드
│           ├── registry.json               # 스냅샷 16항목: doc_id·오퍼레이션별 플래그·변수 템플릿·리프·페이지네이션 정책·검증 여부·캡처 날짜 (데이터)
│           ├── _errors.py                  # ThreadsError(code, message, fix), fix 문구, scrub(csrf·dtsg·lsd·sessionid·cdninstagram 서명) (facebook 이식)
│           ├── _aside.py                   # aside 스폰, 봉투 검증(status·url·body·location?) (facebook 이식)
│           ├── _budget.py                  # 로컬 예산·페이싱·차단 파일·account_lock (facebook _blocked + 요청 주기)
│           ├── _session.py                 # 라우트 HTML → csrf·actor·viewer username·로그인 여부·preloader 목록
│           ├── _transport.py               # page GET·graphql POST 조립, 헤더 세트, classify 7단계, Transport.page()/query(op, vars, expect)
│           ├── _registry.py                # registry.json 로드(오버라이드→번들), OpSpec(doc_id, flags, template, leaf), build_variables
│           ├── _refresh.py                 # 라우트 preloader 채굴 → 재생 검증 → 병합 저장; --capture 병합
│           ├── _target.py                  # @name·URL·code → Target, 로컬 정규화, 명령별 허용 종류 (옛 identity 이식)
│           ├── _ssr.py                     # 라우트 HTML → application/json 블록 → __bbox.result.data 목록 → 오퍼레이션별 식별(리프로)
│           ├── _walk.py                    # 순수 봉투 워커: 오퍼레이션별 리프 경로 지도, page_info 정책(relay/offset/single_batch/capped/ssr_only) (옛 parse 이식)
│           ├── _listing.py                 # 반복 제어: 커서 진행, 클라이언트 창(edge 활동 시각), limit·예산, pending 꼬리, stop_reason (facebook _paginate 구조, transport import 없음)
│           ├── _models.py                  # Post·Media dataclass + build_post(인용·리포스트 재귀, 미디어 판정, 톰스톤; **중첩 인용이 톰스톤이어도 바깥 글은 살린다**) (옛 model 이식)
│           ├── _entities.py                # User(**private·bio_links·friendship_status 추가**)·Counts dataclass + build_user·build_counts
│           ├── _schema.py                  # to_dict → 필드 설명·JSON Schema (facebook 방식)
│           ├── _thread.py                  # SSR Target/Upward/Downward → 게시물·부모 체인·답글 트리(reply_to_id 기반 들여쓰기)·완전성 필드 6종·정렬 라우트
│           ├── _render.py                  # 객체 → 밀도 텍스트. 라벨·시간대·chars·본문 정규화는 여기만
│           ├── _output.py                  # --json 문서, --out 페이지 커밋·이어받기, CursorStore (facebook 이식)
│           ├── _cmds_browse.py             # home·user·search·me·graph (목록 모양)
│           ├── _cmds_post.py               # post·about (SSR 모양)
│           ├── _cmds_meta.py               # doctor·refresh·schema
│           └── browser/
│               ├── page.js                 # ARGS {path, query} → GET www.threads.com (내비게이션 헤더, manual redirect) → 봉투
│               ├── graphql.js              # ARGS {name, doc_id, variables, csrf, referer} → 최소 계약 POST 하나 → 봉투
│               └── capture.js              # ARGS {post_url, targets, budget} → 게시물 탭 열기·훅·SPA 흐름(홈 스크롤/작성자/팔로워 모달/검색 입력/사이드바)·캡처 반환·탭 닫기
├── tests/
│   └── threads/
│       ├── conftest.py                     # THREADS_ASIDE_BIN → fake_aside, THREADS_HOME → tmp, live 마커, 라이브 누적 30요청 가드
│       ├── fake_aside/aside                # 스니펫·경로별 캔드 봉투
│       ├── js/test_page.js · test_graphql.js · test_capture_guard.js   # node가 실제 스니펫을 mock fetch로 실행: 헤더 세트·최소 폼·manual redirect·캡처 예산
│       ├── fixtures/*.ndjson               # 실캡처에서 구조만 유도한 합성 응답 (PII 없음): 라우트 HTML 조각(preloader·bbox), 피드·탭·검색·팔로워·좋아요 응답, 오류 봉투
│       ├── tools/derive_fixture.py · check_fixtures_pii.py
│       ├── test_cli.py · test_transport.py · test_budget.py · test_session.py · test_target.py · test_registry.py · test_refresh.py · test_ssr.py · test_listing.py · test_models.py · test_entities.py · test_thread.py · test_render.py · test_output.py
│       └── live/test_live.py               # -m live. 실제 Aside. 모양·불변식만
├── .github/workflows/test.yml              # threads 테스트·JS·ruff·PII 게이트 추가
├── README.md                               # 스킬 색인에 threads 행
└── pyproject.toml                          # live 마커 설명 일반화
```

### SKILL.md 골격 (D9)

ultra-search처럼 `#` 제목 아래 `##` 절이 있고, 각 절은 "사실 + 결과"만 쓴다. 명령·플래그·종료 코드·스키마·복구 절차는 싣지 않는다(`--help`·`schema`·오류 JSON의 `fix`).

```
---
name: threads
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/threads.py" *)
description: Read Threads (threads.com) through the user's logged-in Aside browser: the home feed (for you / following), a post with its parent chain and replies, a profile's threads, replies, reposts and media, followers and following, search for posts or accounts, and the user's own liked and saved posts. Use whenever the request is to read or explore something on Threads — 스레드에서, 쓰레드 피드, 이 스레드 글 답글, 스레드 검색 — including a bare threads.com or threads.net URL with no mention of Threads. Not for Instagram, Facebook, X/Twitter, Reddit or other networks, general web pages, or posting, replying, liking, following.
---

# Threads through the user's own browser
  한 문단: 브라우저가 로그인된 계정을, CLI가 읽기 전용 질의와 밀도 텍스트를 준다. `$TH` 표기 규칙. `--help`·`schema`·오류의 `fix`가 나머지를 가르친다.

## Every request is the person's account, and Threads does not say how many are left
  레이트리밋 헤더가 없어 헤더의 `local budget`은 도구가 스스로 센 수이지 서버의 잔여량이 아니다. Meta는 자동화에 체크포인트를 걸고 그것은 실계정에 남는다. 응답이 크다(글 하나 0.8MB) → 몇 명·몇 글을 볼지 먼저 정한다. 피드 한 페이지는 4~7건뿐이라 "최근 100개"는 20요청이다. 날짜 창은 클라이언트 필터라 `window_reached`가 아닌 끝은 창을 다 봤다는 뜻이 아니다.

## A post page is one request and shows what it shows
  `post`는 본문·부모 체인·답글 첫 배치(하위 답글 포함)를 한 번에 준다. 그 밖의 직접 답글은 현재 방식으로 이어 읽을 수 없다: 헤더의 `unfetched`는 **추정치**이고, 답글 하나를 열면 그 아래는 보이지만 형제 누락은 줄지 않으며, 최신순은 인기순과 겹칠 수 있다. `--out`으로도 이 한계는 같다. 인기순은 보상받은 자리이지 여론 표본이 아니다. 보고할 때 정렬과 받은 수·추정치를 밝힌다.

## @handles and URLs are the next command's arguments
  출력의 `@…`와 `url:`이 곧 인자. 낯선 사람은 `about`(소개·팔로워·팔로잉·함께 아는), 활동은 `user`의 탭, 관계는 `graph`. 팔로워 목록은 서버가 20명에서 끊으므로 표본이지 관계망이 아니고, 팔로잉은 끝까지 온다. 인용·리포스트는 글 안에 원글 한 줄로 온다.

## What has actually bitten
  Threads는 6주 만에 쿼리 id를 전부 바꿨다; 오류 JSON의 `fix`가 복구를 가리키니 본문을 외우지 않는다. 없는 게시물 URL은 프로필로 조용히 리다이렉트되므로 "열렸다"가 곧 "그 글이다"가 아니다(도구가 잡는다). `following`은 프로필에 없어 `about`이 요청 1회를 더 쓴다. 계정 검색은 오류를 실어도 결과가 있고 페이지가 없다. 활동(알림)은 열면 읽음 처리가 되므로 이 도구는 읽지 않는다.

## Large collections and what the cache holds
  `--out`은 클로드가 읽지 않을 만큼 클 때만. 파일과 커서 캐시는 남의 개인정보 → 레포 밖·작업 뒤 삭제.
```

## 구현 단계와 완료 판정

각 단계는 `tdd` 스킬로 시작한다(seam 합의 → 실패 테스트 → 통과). 단계마다 `codex`로 diff 리뷰를 받고 P1 지적은 그 단계 안에서 고친다. `TaskCreate` 트래커에 아래 판정 기준을 그대로 적는다. **라이브 예산표**: P1 1 + P2 9 + P3 6 + P4 7 = 23요청이 `pytest -m live` 한 번의 상한(30) 안에 들고, P5의 refresh(약 14)는 별도 실행이다. 데이터 의존 수치 대신 구조·대상 일치를 단언하고, skip은 완료가 아니다. 라이브는 항상 `--limit 3`부터.

| 단계 | 내용 | 완료 판정 |
|---|---|---|
| P0 | 스캐폴드: `threads/` 생성, `tests/threads/`, `.gitignore`에 이 계획·스냅샷 파일 예외, `harness-spec.md` 인벤토리 `approved` 행, 심볼릭 링크, `registry.json` 초안(**스냅샷 JSON 16항목을 그대로 변환**, 미검증 항목은 `verified:false`) | `audit_harness.py --path .`가 skill 3개·드리프트 0. `pytest tests/threads`가 0개 수집 exit 5. `ls -l ~/.claude/skills/threads`가 레포를 가리킴 |
| P1 | `_errors`·`_aside`·`_budget`·`_session`·`_transport`·`_registry`·`_target` + `page.js`·`graphql.js` + `doctor` | fake aside 단위 테스트 통과. classify 픽스처: 429+체크포인트 표식→5 무만료(429 단독→30분, 기존 checkpoint를 rate_limit이 못 덮음), 오류 코드 368→5 무만료, `/accounts/login` 리다이렉트→4, 전체 문서인데 csrf·username 없음→4, 껍데기 HTML 단독→판정 불가(6 `transient`), 502→6(차단 없음), 본문에 `challenge`·`try again later`가 든 정상 게시물→0, viewer 있는 프로필 라우트에 preloader 없음→9, 프로필로 리다이렉트된 게시물→9, `data.user:null`(라우트 판정 없음)→6, CRITICAL+data 없음→6 `operation_rotated`, 빈 edges+has_next false→7, 빈 edges+has_next true→커서 진행, page_info 누락→6. `_budget`: 두 프로세스 동시 요청이 창에 2회로 합산, 창 120 초과→요청 없이 5, `--limit`이 있어도 40회에서 8. `_session`: 전체 문서에서 csrf·actor·username·preloader 13종 추출, 껍데기에서 "로그인 판정 불가" 구분. `_target`: 10형 URL·`@name`·code. node: `page.js`가 내비게이션 헤더 7종을 붙이고 3xx를 봉투로, `graphql.js` 폼이 `doc_id`·`variables` 두 필드뿐. 라이브: `doctor` exit 0(홈 1요청) |
| P2 | `_ssr`·`_walk`·`_listing`·`_models`·`_entities`·`_schema`·`_render`·`_output` + `home`·`user`·`about` | 합성 픽스처: preloader 항목과 bbox 결과를 `queryName`·variables·리프로 짝지어 식별하고 요청 대상(`postID`·`userID`)과 대조, 피드·탭 리프 워커와 정책 5종, 인용·리포스트·톰스톤(중첩 톰스톤이 바깥 글을 살림)·캐러셀·링크 미리보기 빌드, render 골든(본문 정규화), pending 꼬리 보존. 라이브(요청 ≤ 9): `home --limit 3`(2요청) 구조 단언, `home --feed following --limit 3`(2)의 응답 `variant`·`pagination_source` 대조, `user @zuck --limit 6`(2~3)에서 **SSR 커서 → Direct 연결 성공 여부를 기록**(A6; 실패 시 대체 경로로 pk 중복 0), `about @zuck`(2)에 followers·following·mutual 필드 존재, `--json` 단일 문서 |
| P3 | `_thread` + `post` + `graph` | 단위: SSR 픽스처에서 부모 체인·본문·답글 배치·하위 답글 관계(`reply_to_id` 기반, 없으면 continuation)·완전성 필드 6종·`--sort recent` 라우트, 팔로잉 오프셋 커서 이어읽기, 팔로워 `server_capped`. 라이브(요청 ≤ 6): `post <zuck 글>` 요청 1회이고 `media.pk == 요청 postID`, 완전성 필드가 합산 규칙을 만족, `post <답글 url>`(1)의 부모 체인에 원글 pk 포함, `graph @zuck followers`(2)가 `server_capped`+`reported_total`, `graph @zuck following --limit 25`(3)가 3요청·pk 중복 0 |
| P4 | `search`·`me` + `--since/--until`·`--out` | 단위: 검색 표면 3종 변수, 계정 검색의 `errors` 동반 데이터 수용·`not_paginable`, 창 테스트(edge 활동 시각·고정글 제외·`window_reached`/`exhausted`·단조성 미확인 표면은 필터만), 게시물 `--out`의 `ssr_complete` 마커. 라이브(요청 ≤ 7): `search "python" --limit 3`(2), `search python --type users --limit 5`(2), `me liked --limit 3`(2, 첫 배치), `me saved`(성진이 글 하나 저장한 뒤 1회, A3; 미확보면 **미검증으로 기록**), `user @zuck --since <2일 전> --limit 5 --out <레포 밖>`(2)의 창 안 항목만 기록. "already complete" 재실행은 `window_reached`로 끝난 파일에만 요구 |
| P5 | `_refresh` + `capture.js` | 단위: 중괄호 균형 파서가 라우트 픽스처 7개에서 10종 추출, 오퍼레이션별 플래그 병합·재생/SSR 검증·원자적 저장, 캡처 관측 요청 계수·차단 시 중단·`finally` 탭 닫기. 라이브(별도 실행, 요청 ≈ 7 GET + 7 POST): `refresh`가 10종 갱신 보고(failed 0), `refresh --capture`가 6종 중 캡처·검증된 것만 저장하고 못 한 것을 사유와 함께 missing으로 출력(프로필 직접 열기 없음) |
| P6 | `SKILL.md`, `harness-spec.md`, README, CI, `validate_harness.py` exit 0, description 대조(facebook·reddit·ultra-search) | 검증 절 참조 |

## Git과 Graphify

- 브랜치 `feat/threads-skill`. 단계마다 논리 단위 커밋(`feat: threads …`, 한국어 제목), P2 이후 단계 끝마다 푸시. PR 하나(`feat: Threads 읽기 전용 스킬 구현`), 템플릿 섹션대로, `## 검증`에 실제 수치. CI 통과 후 `gh pr merge --squash`.
- Graphify는 P3 뒤와 P6 뒤 두 번, facebook 계획의 방식(`graphify extract . --code-only --no-cluster` → codex 명명 → `graphify export html …`). `reddit` 브랜치가 먼저 머지되면 그 뒤에 `main`을 리베이스한다.

## 재사용 지도

| 출처 | 새 모듈 | 변경 |
|---|---|---|
| facebook `_aside.py`·`_errors.py`·`_blocked.py`·`_output.py`·`_registry.py`·`_refresh.py`·`_schema.py`·`_paginate.py`·`_render.py`·`facebook.py` | 각 대응 모듈 | 복사 후 이름·마커·fix 문구·민감 키(csrf·sessionid·cdninstagram) 변경. 명시적 차이: `_registry`는 공통 플래그 유니언 대신 **오퍼레이션별 플래그**; `_output.OutFile`은 `ssr_complete`·`server_capped`·`not_paginable`을 완료/미완료로 구분; `_paginate`의 transport import 제거; `_refresh`는 번들 채굴 대신 preloader 채굴 |
| facebook `browser/{page.js, graphql.js, capture.js}` | `browser/*` | `page.js` 그대로(호스트만), `graphql.js`는 최소 폼으로 축약, `capture.js`는 SPA 흐름으로 재작성 |
| facebook `tests/facebook/{conftest,fake_aside,tools,js}` | `tests/threads/…` | 이식 + 30요청 가드 |
| 옛 `auth.py`의 식별자 함수(531~640행) | `_target.py` | 순수 함수만 이식 + `/t/<code>`·탭 URL·호스트 변형. 쿠키·세션 코드는 제외 |
| 옛 `parse.py` (235) | `_walk.py`·`_ssr.py` | `ENVELOPE_ROOTS`·리프 경로를 스냅샷 JSON으로 갱신, `_page_state`의 "누락→(None,False)"는 버리고 정책 선언으로 대체, SSR bbox 식별 신규 |
| 옛 `model.py` (731) | `_models.py`·`_entities.py` (각 ≤ 400) | `raw`·`captured_at`·JSON Schema 생성기 삭제, 톰스톤·캐러셀·링크 미리보기 유지 |
| 옛 `client.py`의 분류 표식·`_reset_at` | `_transport.py` | 표식 이식, 헤더 없는 경우의 30분 기본 |
| 옛 `retrieve.py`의 커서 EOF 규칙·`_PostState` | `_listing.py` | 규칙만 이식 |
| 옛 `gql.py`의 플래그 사전 | `registry.json` | 데이터로. 값은 이번 캡처로 갱신 |
| 옛 `session.py`·`auth.py`·`docids.py`·`config.py`·`cli.py`·`redact.py` | — | 가져오지 않음 (세션 소유·쿠키 파일·번들 채굴·파일 출력 전제) |

## 검증

- 단위: `python3 -m pytest tests/ -q` (aside 없이, facebook·reddit과 함께). JS: `node --test tests/threads/js/*.js`. 린트: `uvx ruff check --config pyproject.toml .claude/skills/threads/scripts tests/threads`. PII: `python3 tests/threads/tools/check_fixtures_pii.py`.
- 라이브: `python3 -m pytest -m live tests/threads/live/ -q`. 모양·불변식만. 누적 30요청 가드.
- 하네스: `validate_harness.py --path .` exit 0, `audit_harness.py` 드리프트 0.
- codex: 계획 리뷰(이 세션) → 단계별 diff 리뷰 → 최종 사용성 검토. 기준은 **"본문과 `--help`·도구 출력만으로 네 시나리오를 수행할 수 있나"**: V1 "내 스레드 피드 뭐 올라왔어" → `home`. V2 "이 글 답글 요약해줘(URL)" → `post`, 받은 수·추정치·정렬을 보고에 밝힘, 필요하면 `post <reply url>`. V3 "@zuck 요즘 뭐 올려" → `user @zuck`, 낯선 계정이면 `about`. V4 "python 얘기하는 스레드 계정 찾아줘" → `search --type users` → `about` 2~3명, 예산 보고. 근접 오발 둘: "인스타그램에서 …", "이 레딧 글 …" → 미호출.
- Claude e2e: 미실행(D5).

## 위험과 처리

| 위험 | 처리 |
|---|---|
| 실계정 체크포인트(헤더 없음) | 하한 1.0s·지터, 호출 간 10분 120회 창 + 호출당 10/40/60, 체크포인트 최우선 판정·무만료 차단, 캡처 중 차단 관측 시 즉시 중단, SKILL.md의 팬아웃 원리, 라이브 예산표 |
| doc_id·플래그 회전(6주에 12종 전부) | `execution error`+data 없음 → 6 `operation_rotated` → `refresh`(preloader 10종) / `refresh --capture`(6종). 검증된 id만 저장 |
| SSR 밖 직접 답글 불가(F8) | `not_paginable`(완료 아님), 완전성 필드 6종과 추정치 표기, 답글별 자기 페이지(형제 누락은 그대로), `--sort recent`(겹칠 수 있음) |
| 탭 캡처 취약(F6: 직접 연 프로필 빈 껍데기·동시 탭·훅 유실) | 게시물 페이지에서 시작하는 SPA 흐름, 탭 1개, 렌더 폴링, 실패 시 missing 보고 |
| 응답 크기(글 0.8MB·검색 0.5MB) | `fetched` 바이트 표시, 12MB 조각 경로, 기본 표시 수 작게 |
| 저장 목록 형태 미확인(A3) | 구현 세션에서 성진이 글 하나 저장 후 라이브로 확정 |
| 수집 파일의 개인정보 | 레포 밖 권장, `.gitignore`, 본문의 삭제 원리 |

## 미룬 것 (스펙에 기록)

- 쓰기 동작 전부: `declined` (D2).
- 활동(알림): `declined` (D3).
- `from_author` 검색(프로필의 "이 계정에서 검색"): 라우트 preloader가 없어 변수 형태 미확인. 다음 패스가 캡처한다.
- 커뮤니티·태그 페이지·인사이트·메시지: 범위 밖.
- 미디어 다운로드: `--json`의 URL로 충분한지 먼저 본다.

## 가정 (구현 세션이 확인)

- **A1** 로그아웃 세션의 라우트 HTML에는 `csrf_token`·`NON_FACEBOOK_USER_ID`가 없거나 로그인 폼이 있다(이번에 관측 불가). 로그인 판정은 이 부재 + `username` 부재로 한다.
- **A2 (확인됨)** 답글 탭 Direct는 `first:25`→15건, `after`→15건 중복 0. 리포스트·미디어 탭은 같은 형태라고 가정하고 P2에서 `after` 1회로 확인한다.
- **A3** 저장 목록(`SavedPageViewerQuery`)의 리프는 좋아요 목록과 같은 `xdt_text_app_viewer.<saved_media>.edges[].node.thread_items[].post`다.
- **A4** 비공개 계정은 프로필 SSR `user.text_post_app_is_private:true`이고 탭 쿼리가 빈 edges를 준다.
- **A5 (확인됨)** `/`의 `FeedDirectQuery`가 `after`(+`reason:"pagination"`)로 2페이지 7건 중복 0을 줬다. 피드는 refresh 기본 경로에 있고 `FeedPagination`은 대체 경로로만 스냅샷에 남긴다.
- **A6** 프로필 SSR의 `mediaData.page_info.end_cursor`가 Direct 쿼리의 `after`로 통한다. 실패 시 Direct 1페이지 + pk 중복 제거.
- **A7** 좋아요·저장 목록의 2페이지 오퍼레이션·변수. 미캡처이므로 첫 배치만 지원하고 다음 패스가 캡처한다.
- **A8** 답글 post에 `text_post_app_info.reply_to_id`가 있다. 없으면 관계를 만들지 않는다.
- **A9** 팔로잉 피드·리포스트 탭의 시간 단조성. 미확인이므로 `window_reached`를 주장하지 않는다.

## codex 리뷰 반영 (2026-09-05, run `20260905-161036-threads-plan-review-fc02`)

22건 중 22건 반영. P1(14건): (1) 체크포인트 최우선·rate_limit이 checkpoint를 못 덮음, (2) 로그인 URL은 4, 오류 봉투 정규화, exit 6의 `error` 3종과 `fix` 분리, (3) 문구 검색은 정규화 오류 객체 안에서만·HTML은 구조로·반례 픽스처, (4) 9는 명시적 증거에만·껍데기 단독 판정 금지·`user:null`은 라우트 판정과 결합, (5) refresh 카탈로그를 preloader 10종(+SSR 전용 3종 파싱 검증)·캡처 6종으로 정정·항목별 발견/검증 일대일, (6) 스냅샷 JSON(플래그 전체·변수 템플릿·리프·검증 방법) 동반 파일, (7) 호출 간 10분 120회 창·표시 목표와 요청 상한 분리·`local budget` 표기, (8) 캡처의 보장 범위 축소·관측 요청 계수·차단 시 중단·finally 정리, (9) 완전성 필드 6종·추정치 표기·JSON/`--out` 보존, (10) F8 표현을 "현재 방식의 한계"로·정렬 중복·가지 열기의 한계 명시, (11) 팔로워 `server_capped`+총수·계정 검색 `not_paginable`, (12) 창 종료는 edge 활동 시각·단조성 미확인 표면은 필터만, (13) 페이지네이션 정책 5종 선언·page_info 누락은 6·빈 중간 페이지는 진행, (14) userID·postID는 preloader variables에서·SSR 결과와 대상 대조. P2(8건): (15) SSR→Direct 커서 연결을 A6로 분리·대체 경로, (16) 캡처 흐름에 팔로잉 탭·스크롤·완료 조건·`--post URL`, (17) 명령별 준비 라우트 통일·`graph following` 3요청·`--after`는 홈 1회, (18) `about` 부분 성공·`me` 첫 배치만, (19) 출처를 `auth.py`로·`--by id` 삭제·`/t/` 2요청·리다이렉트 검증·범위 밖 라우트 거절, (20) 모델·저장·레지스트리 포팅 차이를 명시·`_walk`/`_listing` 분리, (21) 라이브 예산표·데이터 의존 단언 제거·skip≠완료·A3 미확보 시 미검증, (22) SKILL 골격에서 종료 코드·refresh 명령 제거·로컬 예산 vs 서버·창 불완전성·`--out` 한계 추가. 미검증 주장은 A1~A9로 정리했고 A2·A5는 리뷰 직후 실측으로 확인했다.

## 구현 진행 기록

2026-09-05: 사용자 구현 요청으로 D1–D9·P0–P6와 테스트 seam을 승인 상태로 적용한다. 현재 도구 카탈로그에는 Skill·TaskCreate·TaskUpdate가 없어 전달된 스킬 본문을 적용하고 이 표를 영속 트래커로 쓴다. 각 단계의 완료 판정은 위 P0–P6 표를 그대로 따른다. audit 초기 결과는 skill 2개·드리프트 0·검증 오류 0·경고 0. 작업 브랜치는 `feat/threads-skill`이다. 라이브 P3 표의 요청 합계는 1+1+2+3=7이며 전체 선택 실행은 30회 가드로 관리한다.

| 단계 | 상태 | 증거·남은 작업 |
|---|---|---|
| P0 | 완료 | audit skill 3개·드리프트 0, 초기 pytest 0개 수집(exit 5), 사용자 스코프 링크 확인. 스냅샷 16종 전체를 아래 JSON 블록으로 통합하고 단독 파일 제거. |
| P1 | 완료 | Python 경계 테스트 43개(P2 선행 7개 포함 전체 50), JS 4개 통과. 실계정 doctor: 1요청·661,226바이트·로그인 확인. Codex P1 리뷰 5건을 재현하여 오류 코드 키 보존·path 숫자 제외·잠금 내 unblock·Relay 구조 검사·오퍼레이션 리프 검증으로 수정. 빈 페이지의 exit 7은 목록 출력 경계에서 판정한다. |
| P2 | 진행 중 | 순수 모델·SSR·리프 워커 완료, 목록·출력·브라우징 수직 구현 중. |
| P3 | 대기 | 위 P3 완료 판정 |
| P4 | 대기 | 위 P4 완료 판정 |
| P5 | 대기 | 위 P5 완료 판정 |
| P6 | 대기 | 위 P6 완료 판정·CI·PR 머지 |

P0 리뷰 `20260905-170532-threads-p0-review-7a38`: 16항목 보존·필드 차이 0 확인, 빈 tests 디렉터리 Git 미포함 지적은 P1 테스트 파일 추가로 해소. P1 리뷰 `20260905-171312-threads-p1-review-f536`: 위 5건 수정. 테스트 실패 후 통과를 단계별 기록으로 남긴다.

## 레지스트리 스냅샷

기존 JSON의 전체 내용을 손실 없이 통합했다. 구현의 갱신 가능한 레지스트리는 스킬 안의 `scripts/registry.json`이고, 이 블록은 2026-09-05 조사 근거로 보존한다.

```json
{
 "captured_at": "2026-09-05",
 "account_note": "captured through Aside u0 (@tjdwls101010); userIDs in variables are the sample targets (zuck=63055343223, viewer=63485801431) and must be templated",
 "contract": {
  "url": "https://www.threads.com/graphql/query",
  "form": [
   "doc_id",
   "variables"
  ],
  "headers": [
   "content-type: application/x-www-form-urlencoded",
   "x-csrftoken: <csrf_token from route HTML>",
   "x-ig-app-id: 238260118697367",
   "x-fb-friendly-name: <operation>",
   "origin: https://www.threads.com",
   "referer: https://www.threads.com/<route>"
  ]
 },
 "operations": [
  {
   "operation": "BarcelonaFeedDirectQuery",
   "doc_id": "28427931060136602",
   "source": "route:/",
   "discovery": "preloader on /",
   "verification": "POST replay: page1 + after (4/7 edges, 0 overlap)",
   "leaf": "feedData.edges[].node.text_post_app_thread.thread_items[].post; feedData.page_info",
   "pagination": "relay",
   "variables_template": {
    "data": {
     "pagination_source": "text_post_feed_threads|text_post_feed_following",
     "reason": "cold_start_fetch|pagination"
    },
    "variant": "for_you|following",
    "after": null
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 31,
   "captured_at": "2026-09-05",
   "notes": "A5 verified. `first` is ignored (4-7 posts per page)."
  },
  {
   "operation": "BarcelonaProfilePageDirectQuery",
   "doc_id": "28459403360351848",
   "source": "route:/@<user>",
   "discovery": "preloader on profile route",
   "verification": "POST replay (data.user)",
   "leaf": "user",
   "pagination": "single_batch",
   "variables_template": {
    "userID": "<pk>",
    "canSeeFeedsTab": true,
    "showLinkedIGStats": false
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsLoggedOutrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasInsightsProfileM2relayprovider": false,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesOrLoggedOutrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM1Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Productionrelayprovider": false
   },
   "flag_count": 11,
   "captured_at": "2026-09-05",
   "notes": "SSR on profile route already carries data.user; POST only needed for refresh verification."
  },
  {
   "operation": "BarcelonaProfileThreadsTabDirectQuery",
   "doc_id": "28581921448092834",
   "source": "route:/@<user>",
   "discovery": "preloader on profile route",
   "verification": "POST replay first=25 (15 edges) + after (0 overlap)",
   "leaf": "mediaData.edges[].node.thread_items[].post; mediaData.page_info",
   "pagination": "relay",
   "variables_template": {
    "userID": "<pk>",
    "first": 25,
    "allow_page_info_for_lox_user": false,
    "after": null
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasProfileSelfReplyContextrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 32,
   "captured_at": "2026-09-05",
   "notes": ""
  },
  {
   "operation": "BarcelonaProfileRepliesTabDirectQuery",
   "doc_id": "38355698004046040",
   "source": "route:/@<user>/replies",
   "discovery": "preloader on replies route",
   "verification": "POST replay first=25 (15 edges) + after (0 overlap)",
   "leaf": "mediaData.edges[].node.thread_items[].post; mediaData.page_info",
   "pagination": "relay",
   "variables_template": {
    "userID": "<pk>",
    "first": 25,
    "after": null
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasProfileSelfReplyContextrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 32,
   "captured_at": "2026-09-05",
   "notes": "A2 verified."
  },
  {
   "operation": "BarcelonaProfileRepostsTabDirectQuery",
   "doc_id": "28800390459553524",
   "source": "route:/@<user>/reposts",
   "discovery": "preloader on reposts route",
   "verification": "POST replay first=10 (1 edge, has_next false on zuck)",
   "leaf": "mediaData.edges[].node.thread_items[].post (share_info.reposted_post)",
   "pagination": "relay",
   "variables_template": {
    "userID": "<pk>",
    "first": 25,
    "after": null
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasProfileSelfReplyContextrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 32,
   "captured_at": "2026-09-05",
   "notes": "after not exercised (only 1 repost on sample)."
  },
  {
   "operation": "BarcelonaProfileMediaTabDirectQuery",
   "doc_id": "38191639027147618",
   "source": "route:/@<user>/media",
   "discovery": "preloader on media route",
   "verification": "POST replay first=10 (10 edges)",
   "leaf": "mediaData.edges[].node.thread_items[].post",
   "pagination": "relay",
   "variables_template": {
    "userID": "<pk>",
    "first": 25,
    "after": null
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasProfileSelfReplyContextrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 32,
   "captured_at": "2026-09-05",
   "notes": "after not exercised."
  },
  {
   "operation": "BarcelonaSearchResultsQuery",
   "doc_id": "28325705367048600",
   "source": "route:/search?q=<q>&serp_type=default",
   "discovery": "preloader on search route",
   "verification": "POST replay default/recent/tags + after (10/10 edges)",
   "leaf": "searchResults.edges[].node.thread.thread_items[].post; searchResults.page_info",
   "pagination": "relay",
   "variables_template": {
    "query": "<text>",
    "search_surface": "default|null|tags",
    "recent": "0|1",
    "tagID": null,
    "meta_place_id": null,
    "power_search_info": null,
    "trend_fbid": null,
    "after": null
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaHasSERPHeaderrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesOrLoggedOutrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityGreenDotrelayprovider": false,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityBobbleheadsrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityTrendingBadgingrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 36,
   "captured_at": "2026-09-05",
   "notes": "recent => search_surface null + recent 1. 250-590KB per page."
  },
  {
   "operation": "BarcelonaPostPageStrongIdTargetQuery",
   "doc_id": "28157348907240195",
   "source": "route:/@<user>/post/<code>",
   "discovery": "preloader + SSR __bbox on post route",
   "verification": "SSR parse only (POST replay also returns media)",
   "leaf": "media (post object)",
   "pagination": "single_batch",
   "variables_template": {
    "postID": "<numeric>"
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaHasCommunityPermalinkPivotsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Productionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasInsightsPermalinkUFIrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM1Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 35,
   "captured_at": "2026-09-05",
   "notes": "Read from SSR; no POST needed in normal reads."
  },
  {
   "operation": "BarcelonaPostPageStrongIdDownwardQuery",
   "doc_id": "28855004007435047",
   "source": "route:/@<user>/post/<code>[?sort_order=recent]",
   "discovery": "preloader + SSR __bbox on post route",
   "verification": "SSR parse only. POST replay returns direct_replies:null even from the browser itself (F8)",
   "leaf": "media.text_post_app_info.direct_replies.edges[].node.posts.edges[].node; .page_info; node.fetch_token",
   "pagination": "ssr_only",
   "variables_template": {
    "postID": "<numeric>",
    "sortOrder": "TOP"
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPermalinkIndentationrelayprovider": true
   },
   "flag_count": 32,
   "captured_at": "2026-09-05",
   "notes": "Never POST. Replies beyond the SSR batch are not retrievable."
  },
  {
   "operation": "BarcelonaPostPageStrongIdUpwardQuery",
   "doc_id": "38155848637363153",
   "source": "route:/@<user>/post/<code>",
   "discovery": "preloader + SSR __bbox on post route",
   "verification": "SSR parse only",
   "leaf": "media.text_post_app_info.containing_thread.posts.edges[].node",
   "pagination": "single_batch",
   "variables_template": {
    "postID": "<numeric>"
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaHasPostAuthorNotifControlsrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasInsightsPermalinkCTArelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityNoteWriteEntrypointrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPermalinkIndentationrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsLoggedOutrelayprovider": false
   },
   "flag_count": 36,
   "captured_at": "2026-09-05",
   "notes": "Parent chain; 0 edges on a root post."
  },
  {
   "operation": "useBarcelonaAccountSearchGraphQLDataSourceQuery",
   "doc_id": "27817458954582836",
   "source": "capture:search box",
   "discovery": "SPA: search nav -> type query -> Enter",
   "verification": "POST replay (14 edges; errors[] with field_exception but data present)",
   "leaf": "xdt_api__v1__users__search_connection.edges[].node",
   "pagination": "single_batch",
   "variables_template": {
    "query": "<text>",
    "first": 10,
    "should_fetch_friendship_status": false,
    "should_fetch_fediverse_profiles": true,
    "should_fetch_ig_inactive_on_text_app": null,
    "should_fetch_tag_and_mention_restrictions": false,
    "hide_unconnected_private": false,
    "is_internal_user": false
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false
   },
   "flag_count": 3,
   "captured_at": "2026-09-05",
   "notes": "No page_info."
  },
  {
   "operation": "BarcelonaFriendshipsFollowersTabQuery",
   "doc_id": "28335060419422716",
   "source": "capture:followers dialog",
   "discovery": "SPA: rendered profile -> click role=button '팔로워 N' element",
   "verification": "POST replay (20 edges, has_next false even at 5.7M followers)",
   "leaf": "user.followers.edges[].node; counts{followers,following,mutuals}",
   "pagination": "capped",
   "variables_template": {
    "userID": "<pk>",
    "first": 20
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseListsrelayprovider": true
   },
   "flag_count": 4,
   "captured_at": "2026-09-05",
   "notes": "Server caps at 20; report server_capped."
  },
  {
   "operation": "BarcelonaFriendshipsFollowingTabQuery",
   "doc_id": "28280885978174653",
   "source": "capture:followers dialog -> 팔로잉 tab",
   "discovery": "SPA: dialog tab click",
   "verification": "POST replay (20 edges, end_cursor '20')",
   "leaf": "user.following.edges[].node; user.following.page_info; counts",
   "pagination": "offset",
   "variables_template": {
    "userID": "<pk>",
    "first": 20
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseListsrelayprovider": true
   },
   "flag_count": 4,
   "captured_at": "2026-09-05",
   "notes": ""
  },
  {
   "operation": "BarcelonaFriendshipsFollowingTabRefetchableQuery",
   "doc_id": "27339952475679383",
   "source": "capture:followers dialog -> 팔로잉 tab -> scroll",
   "discovery": "SPA: dialog scroll to bottom",
   "verification": "POST replay (10 edges, end_cursor '30')",
   "leaf": "fetch__XDTUserDict.following.edges[].node; .page_info",
   "pagination": "offset",
   "variables_template": {
    "id": "<pk>",
    "first": 10,
    "after": "<offset string>"
   },
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false
   },
   "flag_count": 3,
   "captured_at": "2026-09-05",
   "notes": ""
  },
  {
   "operation": "BarcelonaLikedPageViewerQuery",
   "doc_id": "38611212625136673",
   "source": "capture:sidebar /liked/",
   "discovery": "SPA: click a[href='/liked/']",
   "verification": "POST replay (251KB, page_info with end_cursor)",
   "leaf": "xdt_text_app_viewer.liked_media.edges[].node.thread_items[].post; .page_info",
   "pagination": "relay",
   "variables_template": {},
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 31,
   "captured_at": "2026-09-05",
   "notes": "Pagination op/variables for page 2 not captured (A7)."
  },
  {
   "operation": "BarcelonaSavedPageViewerQuery",
   "doc_id": "28336699875962760",
   "source": "capture:sidebar /saved/",
   "discovery": "SPA: click a[href='/saved/']",
   "verification": "POST replay 391 bytes on an account with no saved posts; leaf unverified (A3)",
   "leaf": "xdt_text_app_viewer.<saved_media>.edges[].node.thread_items[].post (assumed)",
   "pagination": "relay",
   "variables_template": {},
   "relay_flags": {
    "__relay_internal__pv__BarcelonaIsLoggedInrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPrivateRepliesDeprecationrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMetaAiContentAttachmentsrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasEventBadgerelayprovider": false,
    "__relay_internal__pv__BarcelonaGenAIRepliesEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsSearchDiscoveryEnabledrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunitiesrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGameScoreSharerelayprovider": true,
    "__relay_internal__pv__BarcelonaMessagesHasLiveChatMessagingrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasPublicViewCountCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasCommunityEmojiUpdateCardrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityEntityCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasScorecardCommunityrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasSportTeamAllegianceCardrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasMusicrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasNewspaperLinkStylerelayprovider": false,
    "__relay_internal__pv__BarcelonaHasMessagingrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastV2Consumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasPodcastTranscriptConsumptionrelayprovider": true,
    "__relay_internal__pv__BarcelonaShouldFulfillLightboxQueryrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasViewerRepliedrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasGhostPostEmojiActivationrelayprovider": false,
    "__relay_internal__pv__BarcelonaOptionalCookiesEnabledrelayprovider": true,
    "__relay_internal__pv__BarcelonaHasDearAlgoWebProductionrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasWebFaviconsrelayprovider": false,
    "__relay_internal__pv__BarcelonaIsCrawlerrelayprovider": false,
    "__relay_internal__pv__BarcelonaHasCommunityTopContributorsrelayprovider": false,
    "__relay_internal__pv__BarcelonaCanSeeSponsoredContentrelayprovider": false,
    "__relay_internal__pv__BarcelonaShouldShowFediverseM075Featuresrelayprovider": true,
    "__relay_internal__pv__BarcelonaIsInternalUserrelayprovider": false
   },
   "flag_count": 31,
   "captured_at": "2026-09-05",
   "notes": "Verify after saving one post."
  }
 ]
}
```
