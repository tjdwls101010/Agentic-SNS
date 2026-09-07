# `naver-blog` 스킬 구현 계획

계획 세션: 2026-09-07. 구현 세션은 이 파일만 읽고 시작할 수 있어야 한다. 아래 수치는 이 세션에서 Aside `u0`(네이버 `chunghun1`, blogNo `142227876`)로 직접 확인한 것이고, 출처가 다른 것은 **`[옛]`**(이전 시도 `.tmp/Agentic Blog`의 익명 정찰, 재확인 안 함)과 **`[가정]`**으로 표시한다. 표시 없는 문장은 이번 세션 실측이다. codex(gpt-6-astra, medium) 적대적 리뷰 1회(24건)를 반영했다(맨 끝 절). 형제 계획 `threads 스킬 구현 계획.md`·`twitter 스킬 구현 계획.md`와 같은 구조다.

**P0에서 이 파일을 `.claude/plans/naver-blog 스킬 구현 계획.md`로 옮기고 `.gitignore` 예외를 그 이름으로 추가한다.**

## Context

성진은 클로드가 네이버 블로그를 **사람처럼** 쓰기를 원한다. 검색으로 글을 찾고, 글 전문과 태그를 읽고, 그 블로그의 카테고리와 다른 글·인기글을 훑고, 댓글을 읽고, 댓글 작성자의 블로그로 건너가고, 비슷한 주제의 다른 블로그 글을 다시 찾는 흐름을 스크린샷·클릭 없이 밀도 높은 텍스트로 수행한다. 시각 UI 대신 네이버 블로그 웹 클라이언트가 실제로 쓰는 JSON API(`m.blog.naver.com/api`, `section.blog.naver.com/ajax`, `apis.naver.com/commentBox`)와 모바일 글 HTML을 직접 읽고, 로그인은 이미 로그인된 **Aside 브라우저** 세션을 `aside repl`의 `fetch`로 빌린다.

이전 시도 `.tmp/Agentic Blog`(PyPI `agentic-blog` v0.3.0, 약 4,100줄)은 기술적으로 실패하지 않았다. 익명 httpx로 공개 표면을 읽었고 엔드포인트 장부(`docs/plan/02-recon-findings.md`)가 충실하다. 실패한 것은 **하네스 모양**이다(성진 확인): 313줄 문서형 SKILL.md와 JSON 파일 출력(클로드가 결과를 다시 Read해야 함) 때문에 클로드가 스킬을 잘 쓰지 못했고, 별도 pip 패키지에 스킬이 의존해 설치·유지보수가 번거로웠다. 새 스킬은 그 장부를 상속하고, 형제 스킬처럼 **스킬 디렉터리 안 표준 라이브러리 CLI + 밀도 텍스트 + 다음 홉 핸들**로 모양을 바꾼다. 이전 코드에서 가져올 것은 엔드포인트 지식·본문 파서의 판정 규칙·정규화 규칙뿐이고, httpx·lxml·platformdirs 의존과 파일 출력 계약은 버린다.

facebook·reddit·threads·twitter와 같은 하네스 프레임을 코드에 닿게 적용한다. **principle over rail**: SKILL.md는 규칙 나열이 아니라 네이버 블로그의 사실과 그 결과를 쓴다. **interface over document**: 명령·플래그·종료 코드·복구는 `--help`와 출력 자체가 가르치고 SKILL.md는 "언제·왜·무엇이 물었나"만 쓴다. **for user not developer**: 읽는 이는 사용 시점의 클로드다. 기본 출력은 밀도 텍스트이고 전체 JSON은 요청할 때만 나온다. **dense information**: 글 하나는 3~4줄, 댓글은 1~2줄이며 다음 홉의 핸들(`blogId`, `blogId/logNo`, URL)을 항상 싣는다.

네이버 블로그가 형제와 다른 점 넷이 설계를 결정한다. **토큰이 없다**: doc_id·CSRF·서명·번들 채굴이 필요 없고 `referer` 헤더 하나면 된다. 그래서 형제의 `registry`·`refresh`·`capture`·서명 층이 통째로 사라진다. **글 본문만 HTML이다**: JSON 본문 엔드포인트가 없어 SmartEditor 컴포넌트 HTML을 파싱해야 하며, 이전 시도가 가장 자주 고친 곳이다. **서버가 자기 총수를 모른다**: 목록의 `totalCount`가 0으로 오거나(글 목록) 페이지마다 흔들리고(검색), **1,000건 경계 너머에서는 `totalCount`까지 0으로 바뀐다** — 종료 판정을 서버 숫자에 맡길 수 없다. **로그인이 여는 표면은 셋뿐이다**: 이웃새글, 내 이웃 목록, 댓글의 `mine`.

## 확정된 결정 (성진, 2026-09-07)

| # | 결정 | 결과 |
|---|---|---|
| D1 | **실계정(Aside `u0`, 네이버 `chunghun1`) 로그인 세션 사용** | 이웃새글·내 이웃 목록이 열린다. 모든 요청에 실계정 쿠키가 실리므로 요청 간격 하한·예산·차단 상태를 코드에 고정한다. |
| D2 | **읽기 전용** | 댓글·공감·이웃추가·스크랩은 스펙에 `declined`. 브라우저가 글을 열 때 보내는 조회·광고 로그(`jackpotlog`, `camp-report`, `web_naver_view_log_json`)도 보내지 않는다. |
| D3 | **개인 표면은 이웃새글·내 이웃 목록 포함, 내 블로그 통계·알림 제외** | `home`, `buddies`(인자 없음). 방문자·조회 수는 값이 오면 표시만 한다. |
| D4 | **공개 탐색은 검색(글·블로그·태그)·주제 디렉터리·이달의 블로그·같은 카테고리 추천까지** | 인기 키워드·핫토픽·모먼트·마켓·이미지 검색은 범위 밖. |
| D5 | **실패 진단은 하네스 모양 + 패키지 분리** | 스킬은 형제처럼 `scripts/` 안 표준 라이브러리 CLI로 완결한다. 이전 패키지를 import·설치하지 않는다. |
| D6 | **Claude 헤드리스 e2e 미실행** | codex 사용성 검토와 `pytest -m live`로 대체(형제 D5와 같음). |
| D7 | 본문·`--help`·주석은 영어, description 트리거에 한국어 포함 | 스펙·커밋·PR은 한국어. |
| D8 | **스킬은 완결적** | 형제 모듈을 import하지 않고 복사한다. `tests/naver_blog/` 아래에 스킬별 테스트. |
| D9 | 배포는 레포 `.claude/skills/naver-blog`가 원본, `~/.claude/skills/naver-blog` 심볼릭 링크 | 형제와 같은 관례. |
| D10 | SKILL.md는 ultra-search처럼 헤딩 위계, **명령 표 없음** | 골격은 아래 절. 길이는 완료 기준이 아니다. |
| D11 | **모든 단계가 `tdd` 스킬로 시작하고 `codex` 리뷰로 끝난다** | 아래 "게이트" 절이 무엇을 산출해야 통과인지 정한다. |
| D12 | **하네스 프레임 넷은 검사 가능한 형태로만 주장한다** | 아래 "프레임을 코드에 닿게 하는 방법" 절의 검사가 통과해야 P5가 끝난다. |

## 프레임을 코드에 닿게 하는 방법 (D12)

프레임은 서문에 적어 두면 지켜지지 않는다. 넷 다 **틀리면 실패하는 검사**를 가진다. 검사가 없는 프레임 주장은 계획에서 뺀다.

| 프레임 | 이 스킬에서의 구체적 의미 | 무엇으로 검사하나 (통과 조건) |
|---|---|---|
| **principle over rail** | SKILL.md는 "네이버 블로그가 이렇다 → 그래서 결과 해석이 이렇게 달라진다"만 쓴다. 규칙을 나열하면 열거 안 된 경우에서 부러진다. 예: "1,000건에서 끊긴다"가 아니라 "서버 총수는 답이 아니다 → 읽은 수로 말하고 넓히려면 창을 쪼갠다" | ① `tests/naver_blog/test_skill_doc.py`: SKILL.md 본문에 `--`로 시작하는 플래그 토큰, `exit <숫자>`, 명령/옵션 표(`|---|` 행 중 명령 열거)가 **0개**. ② 각 `##` 절의 모든 단정문이 사실 문장과 결과 문장을 함께 갖는지 codex가 절 단위로 판정하고, "왜"가 없는 문장을 지목하면 P5 미통과. ③ 본문에 없는 상황(예: 새 SE 컴포넌트 계열 등장)을 codex에게 주고 본문만으로 올바른 판단을 재유도할 수 있는지 한 번 확인 |
| **interface over document** | 문장을 코드 고치면 거짓이 되는 것은 전부 코드로 옮긴다. 명령·옵션·기본값·충돌·종료 코드·객체 필드·복구 절차는 `--help`·`schema`·`error.fix`가 소유한다 | ① `test_cli.py`: 12개 명령 각각의 `--help`가 전용 옵션·기본 `--limit`·허용/금지 조합을 **문자열로 포함**하고, 금지 조합은 요청 0회로 exit 2를 내며 그 메시지가 대안을 말한다. ② `test_schema.py`: `schema` 출력의 필드 집합이 각 dataclass `to_dict()`에서 **유도**됨(하드코딩된 필드 목록이 있으면 실패). ③ `test_errors.py`: 모든 `NaverBlogError`가 비어 있지 않은 `fix`를 갖고, 복구 가능한 코드(2·5·6·8)의 `fix`는 실행 가능한 명령 또는 구체적 조건을 담는다. ④ 닫힌 값 집합(`--type`, `--sort`)은 argparse `choices=`로 선언(자유 문자열 검증이면 실패). ⑤ SKILL.md와 `--help`의 중복 문장 검사: 같은 문장이 양쪽에 있으면 SKILL.md에서 뺀다 |
| **for user not developer** | 읽는 이는 사용 시점의 클로드다. 소스를 못 보고, 이전 대화를 모르고, 한 번에 한 명령만 실행한다 | **codex 사용성 검토를 구현 소스 접근 없이 수행한다**(형제의 방식: 합성 데이터와 SKILL.md·`--help`·실제 출력만 제공). V1–V5를 전부 수행하고, 각 시나리오에서 *다음에 무엇을 칠지*가 출력 안에 있었는지, 잘못된 명령을 고른 적이 있는지를 보고한다. 한 시나리오라도 소스를 봐야 진행됐다면 P6 미통과 |
| **dense information** | 클로드가 읽을 토큰이 곧 비용이다. 한 항목은 몇 줄, 빈 필드는 생략, 다음 홉은 항상 포함 | `test_render.py` 골든: 검색·목록 항목 **≤ 4줄**, 댓글 **≤ 3줄**, 헤더 **1줄**, 값이 없는 필드는 줄 자체가 없음(`likes=null` 같은 출력이 있으면 실패), 모든 목록 출력의 마지막 두 줄이 `more:`와 다음 홉 제안, 본문 외 텍스트에 `⏎`로 접힌 줄바꿈만 존재. `blog naverofficial`의 전체 출력이 **40줄 이하** |

## 게이트: tdd와 codex를 언제 어떻게 쓰나 (D11)

**모든 단계는 `Skill(tdd)` 호출로 시작한다.** 스킬을 열지 않고 테스트부터 쓰면 seam 합의 단계를 건너뛰고 내부 구현에 붙은 테스트를 만들게 된다. 각 단계의 tdd 산출물은 셋이다: ① 그 단계가 건드릴 **공개 seam 지명**(위 다섯 중 어느 것인지), ② 그 seam에서 **먼저 실패하는 테스트**(커밋에 실패 상태로 남기지 않되, 커밋 메시지나 계획서 기록에 "무엇이 어떻게 실패했다"를 적는다), ③ 통과. 버그가 나오면 재현 테스트를 먼저 쓰고 그것을 통과시키는 순서로만 고친다.

**모든 단계는 `Skill(codex)` diff 리뷰로 끝난다.** `gpt-6-astra`, effort `medium`, `--sandbox read-only`. 프롬프트는 그 단계의 diff와 이 계획서의 해당 절을 주고 "계획과 다른 점, 계획이 틀린 점, 테스트가 잡지 못하는 실패"를 요구한다. **P1 지적은 그 단계 안에서 재현 테스트와 함께 고친다.** 각 리뷰의 `run_id`와 반영 건수를 계획서의 "구현 진행 기록" 표에 적는다(형제와 같은 관례). 리뷰를 돌리지 않은 단계는 완료로 표시하지 않는다.

**codex를 쓰는 자리 셋을 구분한다.** ① 단계별 diff 리뷰(위). ② P6의 사용성 검토 V1–V5(소스 접근 없음, 위 표의 "for user not developer" 검사). ③ Graphify 커뮤니티 명명(P3·P6). 서브에이전트(`Agent`)로 대체하지 않는다 — 같은 검증을 더 약한 모델에 보내는 셈이 된다.

## 실측 사실 장부

엔드포인트별 URL·파라미터·리프·페이지 정책은 이 문서 끝의 **엔드포인트 스냅샷** JSON에 있고 P0의 `_api.py`는 그 블록을 그대로 코드로 옮긴다.

### 접근·계약

- **F1** Aside `u0`는 네이버에 `chunghun1`(blogNo `142227876`, 닉네임 `라담쉬`)으로 로그인돼 있다. Aside `fetch`는 쿠키를 항상 싣는다.
- **F2 헤더 계약은 `referer` 하나다.** `m.blog.naver.com/api/*`는 referer 없이 **403**(빈 JSON 102바이트), `https://m.blog.naver.com/`이면 200. 다른 호스트도 각 호스트 referer로 200. CSRF·토큰·서명은 없다. 댓글 API에 브라우저가 붙이는 `X-Cbox-Api-Sdk-Version`은 **없어도 같은 응답**이다.
- **F3 봉투 세 가지.** m.blog REST `{"isSuccess":true,"result":{…}}` / `{"isSuccess":false,"error":{"code","message","details"}}`; section ajax는 XSSI 접두 `)]}',\n` + `{"result":{…}}`; CBOX `{"success":true,"code":"1000","result":{…}}`. 접두를 벗긴 뒤 파싱한다.
- **F4 오류 서명(로그인 상태 실측).** 없는 블로그 → **404 `not_exist_blog`**(`[옛]` 익명 관측은 400 `blog_id_invalidate`였다. 둘 다 처리한다). 없는 글 → `comments-info` **404 `not_exist_post`**; 모바일 글 HTML **404** 113바이트 `location.href="/MobileErrorView.naver?errorType=noPost…"`. 남의 `my-buddies` → **403 `not_blog_owner`**. `post-list?itemCount=31` → 200 + `isSuccess:false` `param_is_invalidate`. referer 누락 → 403 + 빈 본문. 로그아웃 서명은 미관측(A1).
- **F5 레이트리밋 헤더가 없다.** `x-ratelimit-*`·`retry-after` 없음. 오늘 로그인 상태로 간격 0.6초 약 100요청에 이상 없음. `[옛]` 익명 0.5초 360요청(호스트당 120)도 전부 200. 로그인 상태 한도·차단 서명은 **미관측**이며 어느 쪽도 보장된 할당량이 아니다. 응답에 실리는 정책 신호는 `blockedByBifrostShield`/`isBlockedByBifrostShield`와 `queryControlInfo{isAdult,isForbidden}`(오늘 전부 false)이다.
- **F6 로그인·뷰어 원천.** 모바일 글 HTML에 `var userId = "chunghun1"`(뷰어)·`var blogOwner`·`var blogNo`(글 주인), PC HTML에 `var isLoggedIn = true`. `m.blog.naver.com/FeedList.naver`(22KB)에 `href="/BuddyList.naver?blogId=chunghun1"`·`buddyTotalCount 23`. `comments-user-info`(272B)는 뷰어 닉네임만.
- **F7 REPL 제약은 형제와 같다.** 브라우저 요청 캡처는 렌더된 탭에 훅을 심고 앱 안 클릭·스크롤로만 가능하다(오늘 댓글·피드 API를 이 방법으로 발견). **런타임에는 탭을 열지 않는다** — 회전하는 id가 없어 캡처가 필요 없다.

### 종료·페이지 판정을 바꾸는 사실

- **F13 검색은 1,000건에서 끊기고 그 너머에서 거짓 0을 준다.** `search/v1/post` `itemCount=30`: 33페이지 30건(=990), **34페이지 10건(=1000)**, **35페이지 0건이면서 `totalCount:0`·`totalPage:1`**. section `type=post` 34페이지도 10건이고 `totalCount`는 처음부터 1000이다. 태그 검색 34페이지는 0건이지만 `totalCount`는 151,093을 유지한다. 즉 **`totalCount`는 종료 판정에 절대 쓰지 않고**, 누적 위치가 1,000에 닿아 짧아진 페이지는 `exhausted`가 아니라 `server_capped`다.
- **F14 이웃새글은 페이지가 없다.** `BuddyPostList`는 `currentPage`·`countPerPage`·`groupId`를 **전부 무시**한다(1·2·4·9페이지, `countPerPage` 3·10·30이 모두 같은 10건·`buddyPostTotalCount:10`). 모바일 대안 `POST query.blog.naver.com/mweb/buddy-feed/ab/cards`(`{feedType:"TOTAL", pagingParam, exposedContentKeys}`, 텔레메트리 `campsParam` 없이도 200)는 `pagingParam`으로 페이지가 되지만 **2페이지부터는 이웃 글 0건에 추천 글만** 온다. 오늘 두 표면이 같은 10건에 합의했다. → `home`은 section GET 한 번, `stop_reason=not_paginable`, `buddyPostTotalCount`가 반환 수보다 크면 `server_capped`.
- **F15 글 목록의 서버 숫자는 거짓이다.** `post-list`는 `result.totalCount:0`·`result.page:1`을 항상 준다(요청은 정상 진행, 2페이지 중복 0). 종료는 **서버가 돌려준 원본 항목 수**가 요청한 `itemCount`보다 적을 때만이며, 표시 제한·날짜 필터·중복 제거 뒤의 수로 판정하지 않는다.
- **F16 신뢰할 수 있는 종료 표식이 있는 표면.** 댓글 `pageModel{totalPages, nextPage}`, 이웃 `totalPageCount`, 블로그 안 검색 `totalPage`(단 태그 검색의 `totalPage`는 `[옛]` 20건 기준으로 잘못 계산됨). 이들에서는 짧은 페이지보다 이 표식이 우선한다.
- **F17 페이지 크기.** 통합 검색·태그 검색·section 검색·글 목록 = **30 상한**(글 목록은 31에서 `param_is_invalidate`). 블로그 안 글 검색 = **20**. 블로그 안 태그 검색 = **30** `[옛]`. 댓글 = 100까지 확인. 이웃 = 20. 주제별 글 = 10 고정.

### 표면 카탈로그

| 사람의 동작 | 엔드포인트 | 페이지 | 주요 리프 | 비고 |
|---|---|---|---|---|
| 검색창(글) | `m.blog /api/search/v1/post?keyword&sortType=sim\|date&page&itemCount≤30[&startDate&endDate][&isBuyWithMyOwnMoney=true]` | page, 1,000 상한 | `result.list[]{blogId, blogNo, logNo, title, content, blogName, nickname, categoryName, addDate(ms), commentCount, sympathyCount, isBuyWithMyOwnMoney}` | 하이라이트 `<em class="highlight">`. 날짜 창은 서버 필터(9/1~9/7 → 521건) |
| 검색창(블로그) | `m.blog /api/search/v1/blog?keyword&page&itemCount≤30` | page | `result.list[]{blogId, blogNo, blogName, blogNameWithTag, nickname, blogDesc, buddyCount, officialBlog, powerBlog, isMarketBlog, profileImageURL}` | `[옛]` 장부에 `v2/blog`가 있었고 오늘 `v1`을 확인했다. 이웃 수가 있어 주 경로 |
| 검색창(태그) | `m.blog /api/tags/search/post?query&page&itemCount≤30` | page | `result.items[]{blogId, logNo, nickname, title, content, addDate, commentCount, sympathyCount}` | **blogNo·blogName·categoryName 없음**. 하이라이트 없음 |
| 검색(section, 대체) | `section /ajax/SearchList.naver?type=post\|blog\|id&keyword&orderBy&currentPage&countPerPage≤30` | page, 1,000 상한 | `result.searchList[]` | 하이라이트 `<strong class="search_keyword">`. `type=id`는 CLI에서 쓰지 않는다(블로그 검색이 대체) |
| 블로그 카드 | `m.blog /api/blogs/{blogId}` | single | `result{blogId, blogNo, blogName, nickName, subscriberCount, dayVisitorCount, totalVisitorCount, officialBlog, blogDirectoryName, neighbor, bothNeighbor, blogOwner, block}` | 2KB |
| 카테고리 | `m.blog /api/blogs/{blogId}/category-list` | single | `result.mylogCategoryList[]{categoryNo, categoryName, parentCategoryNo, postCnt, openYN, categoryType, divisionLine}`, `mylogPostCount` | 구분선 제외. **총 글 수를 믿을 수 있는 유일한 곳** |
| 글 목록 | `m.blog /api/blogs/{blogId}/post-list?categoryNo&itemCount≤30&page` | page(F15) | `result.items[]{logNo, titleWithInspectMessage, briefContents, addDate(ms), categoryNo, categoryName, commentCnt, sympathyCnt, shareCnt, readCount, smartEditorVersion, thumbnailList, allOpenPost, buddyOpen, notOpen, postBlocked}` | `readCount`는 내 블로그만 숫자 |
| 인기글 | `m.blog /api/blogs/{blogId}/popular-post-list` | single(10) | `result.popularPostList[]{…, viewCount}` | **`viewCount`가 오는 유일한 표면** |
| 공지 | `m.blog /api/blogs/{blogId}/notice-post-list` | single | `result.noticePostViewList[]{logNo, title, addDate, commentCount, postOpenType, categoryNo}` | 필드명이 다르다 |
| 블로그 안 검색 | `m.blog /api/blogs/{blogId}/search/post?query&sortType&page` | page(20), `totalPage` | `result.list[]{logNo, blogNo, title, contents, categoryName, addDate, commentCount, sympathyCount}` | `keyword=`는 500 |
| 블로그 안 태그 | `m.blog /api/blogs/{blogId}/search/tag?query&page` | page(30) | 같은 형태 | `sortType` 무시, `totalPage` 오계산 `[옛]` |
| 공개 이웃 | `m.blog /api/blogs/{blogId}/public-buddies?pageNo` | page, `totalPageCount` | `result{totalMyBuddyCount, totalPublicBuddyCount, totalPageCount, buddyList[]{blogId, blogName, nickName, blogNo, updateTime(null 가능)}}` | 비공개가 기본이라 빈 목록이 흔하다 |
| **내 이웃(로그인)** | `m.blog /api/blogs/{me}/my-buddies?pageNo&sortType=2` | page(20), `totalPageCount` | `result{totalMyBuddyCount, buddyGroupList[], buddyList[]{blogId, blogName, nickName, blogNo, groupId, bothNeighbor, officialBlog, recentlyUpdate}}` | 남의 id는 403 `not_blog_owner`(A3 확인) |
| **이웃새글(로그인)** | `section /ajax/BuddyPostList.naver?currentPage=1&groupId=0&countPerPage=30&categoryNo=0` | **없음(F14)** | `result{buddyPostList[]{blogId, nickName, blogName, logNo, postUrl, title, briefContents, addDate, sympathyCnt, commentCnt, readed, smartEditorVersion}, buddyPostTotalCount, hasBuddy, hasBuddyPost}` | 파라미터를 무시하지만 형태 유지를 위해 그대로 보낸다 |
| 글 본문 | `m.blog /PostView.naver?blogId&logNo` (HTML 66~132KB) | single | F8 | PC 프레임(`blog.naver.com/{id}/{logNo}`)은 쓰지 않는다 |
| 댓글 | `apis.naver.com/commentBox/cbox/web_naver_list_json.json?ticket=blog&templateId=default_simple&pool=blogid&objectId={blogNo}_201_{logNo}&groupId={blogNo}&listType=OBJECT&pageType=more&page&pageSize≤100&indexSize=10&replyPageSize=10&showReply=true&initialize=true&useAltSort=true&lang=ko` | page, `pageModel` | `result.commentList[]{commentNo, parentCommentNo, replyLevel, replyCount, contents, userName, maskedUserName, profileUserId, userProfileImage, regTime(ISO+0900), sympathyCount, antipathyCount, mine, best, status, deleted, blind, secret, hiddenByCleanbot, sticker, imageList}`, `count{comment,reply,total}`, `sort` | **답글은 `replyLevel:2`로 평탄하게 섞이고 `replyList`는 항상 null**(`[옛]` 중첩 주장 정정). **`sort=NEW\|FAVORITE\|OLD`를 줘도 응답 `sort`는 항상 `REVERSE_NEW`** → 정렬 옵션을 두지 않는다 |
| 댓글 수·blogNo | `m.blog /api/blogs/{blogId}/posts/{logNo}/comments-info` | single | `result{totalCount, postTitle, blogNo}` | 글 HTML을 읽었으면 불필요 |
| 같은 카테고리 추천 | `m.blog /api/blogs/{blogId}/v1/category-related-posts?blogId&categoryNo&countPerPage&logNo&isInitialPage=true&isFromSearchAddView=false` | single | `result{recommendationBlockTitle, recommendationPostList[]{blogId, blogNo, logNo, title, addDate(ISO), commentCount, sympathyCount, url}, hasNext}` | 목록 첫 항목이 그 글 자신이었다(1표본, A4) |
| 주제 디렉터리 | `section /ajax/DirectoryList.naver` | single | `result[]{name, seq, directoryList[]{name, seq}}` | 4그룹 32주제, 1.7KB |
| 주제별 글 | `section /ajax/DirectoryPostList.naver?directorySeq&pageNo` | page(10), 1,000 상한 | `result{totalCount, postList[]}` | |
| 주제 인기글 | `section /ajax/DirectoryTopPostList.naver?directorySeq` | single(9) | `result[]` | 수치 없음 |
| 이달의 블로그 | `section /ajax/ThisMonthDirectoryBlogList.naver?year&month` | single | `result{list[]{group, blogList[], count}, prevMonth, prevYear}` | 미래 달은 최신 호로 클램프 `[옛]` |
| 에디터 픽 | `section /ajax/EditorPickList.naver?year&month` | single | `result.list[]{…, introduce, subscriberCount, postViewList[]}` | |

- **F8 글 HTML.** 메타는 `<div id="_post_property" … commentCount blogName categoryNo addDate(ms) gdid browserTitle editorversion uri>` 속성 + 스크립트 변수 `var blogId`, `var blogNo`, `var postTitle`(유니코드 이스케이프), `var gsCategoryName`, **`var gsTagName = "태그1,태그2"`**(`[옛]` "태그는 별도 PC 호출" 정정: 3표본 모두 HTML에 있음. 없으면 `tags=unknown`이지 "태그 없음"이 아니다), `var openType`, `var userId`(뷰어), `<meta property="og:url|og:title|og:description">`. 본문 컨테이너는 `div.se-main-container`(SmartEditor ONE)와 legacy `div#viewTypeSelector.post_ct`이며 **한 문서에 둘 다 존재할 수 있다**(3표본 모두 `post_ct` 존재).
- **F9 SE 컴포넌트.** 오늘 3표본: `text`(29), `image`(12), `imageStrip`(4), `sectionTitle`(7), `horizontalLine`(10), `quotation`(1), `material`(2), `documentTitle`(3). `[옛]` 54표본 추가 계열: `sticker`, `imageGroup`, `video`, `table`, `oembed`, `oglink`, `placesMap`, `custom`, `wrappingParagraph`. 각 컴포넌트는 `<div class="se-component se-<family> …">` 하나에 계열 클래스 정확히 하나(`[옛]` 387/387). 텍스트는 `p.se-text-paragraph > span`, 이미지는 `img[data-lazy-src]`(진짜 URL, `src`는 흐린 플레이스홀더) 또는 `a.__se_image_link[data-linkdata].src`, 캡션은 `.se-caption`, `material`은 `a[data-linkdata]{type, title, link}`, **`video`와 `oembed`는 서로 다르다**: 둘 다 `script.__se_module_data[data-module]` JSON을 갖지만 `video`는 재생 URL이 없을 수 있고(`thumbnail`만), `oembed`는 영상·소셜 글·지도 어느 것이든 될 수 있다 `[옛] body.py:237-277`.
- **F10 식별자.** blogId는 영숫자·`_`·`-`이며 **숫자만인 id도 실재한다** `[옛]`. logNo는 **가변 길이 숫자**(`[옛] identifiers.py`; 오늘 표본은 12자리이나 길이를 강제하지 않는다). URL 형태: `blog.naver.com/<id>`, `/<id>/<logNo>`, `m.blog.naver.com/<id>[/<logNo>]`, `PostView.naver?blogId=&logNo=`, `PostList.naver?blogId=&categoryNo=`, `NBlogTop.naver?blogId=`, `<id>?Redirect=Log&logNo=`. **도메인 id는 302로 정식 blogId가 된다**(`blog.naver.com/naver_diary` → `NBlogTop.naver?blogId=naverofficial`).
- **F11 날짜 형식 셋.** 목록·글 HTML `addDate` = epoch ms, 댓글 `regTime`·추천 `addDate` = ISO `+0900`. 전부 `YYYY-MM-DDTHH:MM+09:00`으로 정규화한다. 이전 시도의 "HTML 날짜를 UTC로 오인" 결함은 HTML의 사람용 날짜를 쓰지 않는 것으로 피한다.
- **F12 크기·지연.** m.blog REST 2~40KB·40~200ms, section 검색 30건 51KB·300ms, 댓글 100건 26KB·200ms, 글 HTML 66~132KB·80~130ms, 이달의 블로그 115KB. 형제(글 0.8MB)보다 한 자릿수 작다.
- **F18 `[옛]` 확정 규칙(재확인 안 함).** `briefContents`가 이모지 서로게이트 절반에서 잘릴 수 있음(짝 없는 서로게이트를 **삭제**한다); `sympathy-users`는 목록이 비어 옴; 연재(시리즈) 엔드포인트 없음; `/api/search/v1/tag`는 태그 **그룹**이지 글이 아님.

## 설계

### 실행 모델

```
naver_blog.py <cmd> ──▶ Python(stdlib) ──spawn──▶ aside --account u0 repl <fetch.js> ──▶ Aside fetch ──▶ naver.com
      ▲                                                          │
      └── {status, url, body, location} ◀────────────────────────┘
```

- **한 `aside repl` 호출 = 한 요청.** 형제와 같은 이유. `# 성진` 주석 동일.
- **스니펫은 `fetch.js` 하나.** `ARGS {host, path, query, accept}` → GET. 호스트·경로 허용 목록을 스니펫과 파이썬 양쪽에 고정: `m.blog.naver.com`(`/api/*`, `/PostView.naver`, `/FeedList.naver`), `section.blog.naver.com`(`/ajax/*`), `apis.naver.com`(`/commentBox/cbox/web_naver_list_json.json`만), `blog.naver.com`(`/<id>`·`/NBlogTop.naver`만, 302 해석용). referer는 호스트별 고정값을 스니펫이 붙인다. `redirect:"manual"`로 3xx는 `location`으로 봉투에 싣는다. **GET만 지원한다**(F14의 모바일 피드 POST는 채택하지 않는다: 2페이지부터 추천 글뿐이고, 텔레메트리 형태의 본문을 보내게 된다).
- **세션.** `~/.cache/naver-blog-skill/session.json`에 `{viewer_id, read_at, account:"u0"}`. **TTL 12시간**, 만료·부재·로그인 판정 실패 시 `FeedList.naver` 1회로 갱신. 글 HTML을 읽는 명령은 `var userId`로 공짜 갱신한다. `viewer_id`가 바뀌면 `cursors/*`를 전부 지운다(형제 twitter `_session.ensure`와 같은 규칙).

### 응답 판정 (`_transport.classify`) — 순서가 계약이다

각 오퍼레이션은 `_api.py`에 **성공 플래그·리프 경로·리프 타입·대상 식별 필드**를 선언하고, classify는 그것을 인자로 받는다. 판정 순서:

1. **전송 실패**: 비 2xx/3xx 중 아래 규칙에 안 잡히는 것, 비JSON, 잘린 JSON → exit 6 `transient`. 재시도하지 않는다.
2. **명시적 차단(exit 5)**: HTTP **429**만. 30분 만료 차단 파일. `[옛]`도 오늘도 429를 관측한 적이 없으므로 **다른 어떤 신호도 차단으로 승격하지 않는다**. 캡차·인증 페이지 서명이 실제로 관측되면 그때 무만료 분기를 추가한다(A7).
3. **로그인(exit 4)**: 최종 URL 또는 `location`이 `nid.naver.com`·`/nidlogin`이면 **모든 명령에서** 4. 그 밖에는 로그인 전용 오퍼레이션(`my-buddies`, `BuddyPostList`, `FeedList`)에서 `notlogined`류 오류 코드일 때만 4. **FeedList HTML에 `BuddyList.naver?blogId=` 링크가 없는 것만으로는 4가 아니라 6 `envelope_drift`다**(HTML 개편·점검 페이지도 같은 모양이 된다).
4. **대상 없음·닫힘(exit 9)**: 404 + `not_exist_blog`/`not_exist_post`, 400 + `blog_id_invalidate`(`[옛]` 형태), 403 + `not_blog_owner`(`reason=owner_only`), 글 HTML 404 + `MobileErrorView.naver?errorType=noPost`. **`noPost` 이외의 `errorType`은 관측 전까지 6 `transient`이고 `reason`에 원값을 싣는다.** 목록 항목의 `notOpen`/`buddyOpen`/`postBlocked`는 항목 라벨일 뿐 명령을 9로 만들지 않는다.
5. **인자(exit 2)**: `param_is_invalidate`·`bad_request`. CLI가 요청 전에 막았어야 할 값이므로 버그 신호이며 `fix`가 그렇게 말한다.
6. **계약 오류(exit 6 `envelope_drift`)**: 그 밖의 403(빈 본문 = referer 결함); 성공 플래그가 false인데 위 코드가 아님; **CBOX `success:false`의 모든 코드(`3300` 포함)** — `3300`은 잘못된 `pool`·`ticket`에서도 나오므로 차단이 아니라 계약 오류다 `[옛] endpoints.py:26`; 기대 리프가 없거나 타입이 다름; 요청 대상과 응답 대상 불일치(예: 요청 `logNo`와 `objectId`의 logNo, 요청 `blogId`와 `result.blogId`).
7. **정책 제한(exit 8 `query_restricted`)**: `blockedByBifrostShield`/`isBlockedByBifrostShield` true, `queryControlInfo.isForbidden` true, `suicideWord` true. 받은 결과가 있으면 그대로 싣고 제한 사실을 헤더와 `fix`에 쓴다. **정책 제한을 "결과 없음"으로 보고하지 않는다.**
8. **정직한 0건(exit 7)**: 위 어디에도 안 걸리고, **명령이** 자기 주 결과 표면이 명시적 빈 배열이라고 판정했을 때. transport는 빈 배열을 오류로 만들지 않는다(9번 참조).

**부분 성공 계약.** transport는 판정과 데이터만 돌려주고 exit을 정하지 않는다. 복합 명령(`blog`, `post`)은 **절(section) 단위**로 결과를 모은다: 각 절은 `{name, ok, data|error{code,message}}`. 주 절(카드·본문)이 성공하면 명령은 0 또는 8이고, 보조 절 실패(공지·인기글·추천·댓글)는 결과에 남긴 채 **exit 8 `partial`**로 끝난다. 주 절이 실패하면 그 절의 코드를 그대로 쓴다. 여러 절이 실패하면 **우선순위 4 > 5 > 9 > 6 > 8**로 가장 높은 것을 exit으로 삼는다. 빈 공지·빈 인기글은 실패가 아니라 빈 절이고, `blog`은 카드가 있으면 절대 7이 아니다.

### 페이지 정책 (`_api.py`가 선언, `_walk`·`_listing`이 집행)

| 정책 | 대상 | 종료 규칙 |
|---|---|---|
| `page` | 검색 3종·section 검색·글 목록·주제별 글 | **서버가 돌려준 원본 항목 수 < 요청 페이지 크기**면 종료. 표시 제한·날짜 필터·중복 제거 뒤의 수를 쓰지 않는다 |
| `page_marked` | 댓글(`pageModel.totalPages`/`nextPage`), 이웃(`totalPageCount`), 블로그 안 글 검색(`totalPage`) | 표식이 우선하고 짧은 페이지는 보조 |
| `single` | 카드·카테고리·인기글·공지·추천·주제 목록·주제 인기글·이달·에디터픽 | `not_paginable` |
| `no_paging` | 이웃새글(F14) | 한 번만 요청. `buddyPostTotalCount > len(list)`면 `server_capped`, 아니면 `not_paginable` |

- **1,000건 상한(F13)**: `page` 정책 중 `cap:1000`인 오퍼레이션은 **누적 요청 위치**(`(page-1)*size + 반환 수`)를 센다. 판정은 "위치가 1000에 닿았나"가 아니라 **"한 페이지를 더 받으면 1000을 넘나"**(`position + page_size > cap`)다 — 글 검색은 위치 1,000에서, 태그 검색은 위치 990에서 짧아졌고 둘 다 상한이기 때문이다(P0 codex 지적으로 정정). 그렇게 짧아졌으면 `server_capped`(`reported_total`을 함께 싣되 "서버 보고치"라고 표시). 1000을 넘긴 페이지의 `totalCount:0`은 **진짜 0이 아니므로** 7로 만들지 않는다.
- **반복 페이지**: 이전 페이지와 항목 id 집합이 같으면 `exhausted`가 아니라 **`pagination_stalled`(exit 8)**로 멈춘다. 서버가 페이지 인자를 무시하는 상황과 실제 소진은 구별할 수 없다.
- 모든 `page` 진행은 안정 id(`logNo`·`blogId`·`commentNo`)로 중복 제거하며, 중복 제거된 수는 종료 판정에 쓰지 않고 표시에만 반영한다.

### 예산 계약 (`_budget.py`)

- 네이버는 남은 수를 알려주지 않으므로 **예산은 전적으로 로컬**이고 출력은 항상 `local budget`이라고 적는다.
- **예약 후 전송.** `account_lock` 안에서 차단 판정 → 창 합산 → **시각을 파일에 먼저 기록** → 페이싱 → 전송. 형제 `_budget.request()`와 같은 순서다. 요청이 서버에 닿은 뒤 프로세스가 죽어도 예산이 새지 않는다.
- **호출 간 합산 창.** `budget.json`에 최근 10분 요청 시각, 창 합계 **120회** 초과 시 요청 없이 exit 5. 요청 간 하한 **0.5초**(+0~0.3초 지터). `# 성진: 0.5초·120회/10분은 익명 360요청과 로그인 100요청 무사고에서 정한 로컬 추정치이지 서버가 준 할당량이 아니다. 429나 인증 페이지가 관측되면 낮춘다`.
- **호출당 상한** 기본 10, 명시적 `--limit`·`--since`·`--out`이 있으면 40, 절대 상한 60. `--limit`은 표시 목표이지 요청 상한이 아니다.
- **차단 상태** `blocked.json`은 `rate_limit`(30분)만. `doctor --unblock`은 **검증 요청 1회가 200으로 성공한 뒤에만** 차단 파일을 지우며, **로컬 창은 초기화하지 않는다**.
- 헤더에 `fetched 0.2MB`를 적는다.

### 식별자 계약 (`_target.py`)

- identity는 `blogId`(문자열)와 `logNo`(문자열, 가변 길이 숫자). 표시 핸들은 `blogId`와 `blogId/logNo`, 정식 URL `https://blog.naver.com/<id>/<logNo>`.
- `Target(kind ∈ {blog, post, category, query, me}, blog_id, log_no, category_no)`. F10의 URL 전부 + 트레일링 슬래시·쿼리·`m.` 변형. **URL이 `categoryNo`를 실어 오고 `--category`도 주어지면 exit 2**(충돌).
- **도메인 id 해석**: 정식 id 가정으로 먼저 요청하고, `not_exist_blog`/`blog_id_invalidate`가 오면 `blog.naver.com/<id>` 1홉 302로 `blogId=`를 읽어 재요청한다. 이 경로는 **3요청**(실패 1 + 리다이렉트 1 + 재요청 1)이며 헤더의 요청 수에 그대로 나타난다.
- `naver.me` 단축 링크는 A6 확인 전까지 exit 2. 범위 밖 라우트(알림·글쓰기·설정)도 2.

### 명령 표면 (`naver_blog.py --help`가 진실, 여기는 설계 의도)

**12개 명령.** 모든 읽기 명령은 `--json`·`--chars`·`--limit`을 공유한다. `--out`·`--after`·`--since/--until`은 아래 표가 허용하는 명령에만 있고, 허용되지 않는 조합은 **요청 전에** exit 2로 거절한다.

| 명령 | 인자 | 전용 옵션 | `--limit` 기본 | `--after` | `--since/--until` | `--out` | 기본 요청 수 | 조건부 추가 |
|---|---|---|---|---|---|---|---|---|
| `search <text>` | 자유 텍스트 | `--type posts\|blogs\|tags`(기본 posts), `--sort sim\|date`(posts·blogs만), `--own-money`(posts만) | 10 | ○ | 서버 필터(posts만) | ○ | 페이지당 1 | — |
| `blog <id\|url>` | blog | `--brief` | — | ✕ | ✕ | ✕ | 4(카드·카테고리·공지·인기글), `--brief`는 2 | 도메인 id면 +2 |
| `posts <id\|url>` | blog | `--category <no\|이름>`, `--popular`, `--notices`(셋은 상호 배타) | 10 | ○ | 클라이언트 | ○ | 페이지당 1 | 카테고리를 **이름**으로 주면 카테고리 목록 +1 |
| `post <url\|id/logNo>` | post | `--comments` | — | ✕ | ✕ | ○ | 2(HTML·추천) | `--comments` +1 |
| `comments <url\|id/logNo>` | post | — | 20 | ○ | ✕ | ○ | 1(`comments-info`) + 페이지당 1 | — |
| `find <id\|url> <text>` | blog+텍스트 | `--tag`, `--sort sim\|date`(태그 아닐 때만) | 10 | ○ | 클라이언트 | ○ | 페이지당 1 | — |
| `buddies [<id\|url>]` | blog·me | — | 20 | ○ | ✕ | ○ | 페이지당 1 | 인자 없고 세션 만료면 +1 |
| `home` | 없음 | — | 10 | ✕(F14) | 클라이언트 | ✕ | 1 | 세션 만료면 +1 |
| `topic [<seq\|이름>]` | 없음·seq | `--top` | 10 | ○(글 목록만) | 클라이언트 | ○ | 1 | 이름으로 주면 주제 목록 +1 |
| `monthly` | 없음 | `--year --month` | — | ✕ | ✕ | ✕ | 2 | — |
| `doctor` | 없음 | `--unblock` | — | ✕ | ✕ | ✕ | 1 | — |
| `schema` | 없음 | — | — | ✕ | ✕ | ✕ | 0 | — |

`post`의 동작. HTML 1회로 메타(F8)·태그·본문을 파싱하고, `category-related-posts`로 같은 카테고리 글과 이 글의 공감 수를 얻는다. **추천 목록의 첫 항목이 요청한 `logNo`면 그것으로 공감 수를 채우고 나머지(최대 4개)를 "같은 카테고리 글"로 보여준다. 아니면 `likes=unknown`이고 전부 보여준다.** 출력 순서: 헤더 → 글 카드(제목·작성자·날짜·카테고리·태그·공감·댓글 수) → 본문 → 같은 카테고리 글 → 끝줄 핸들. `--chars`는 본문에 적용하지 않는다. 추천 절이 실패해도 본문은 남고 exit 8이다.

`search`의 동작. 글은 `search/v1/post`(30건·공감·댓글 수·카테고리·내돈내산 필터), 블로그는 `search/v1/blog`(이웃 수·소개·공식 표식), 태그는 `tags/search/post`. 하이라이트 마크업 두 종류를 벗기고 원문 필드가 따로 있으면(`blogName` vs `blogNameWithTag`) 원문을 쓴다. `totalCount`는 헤더에 `reported≈27,295 (server figure, drifts)`로만 싣는다.

`blog`의 동작. 카드 한 줄(이름·닉네임·이웃 수·오늘/누적 방문·공식 표식·뷰어와의 이웃 관계) → 카테고리 트리(들여쓰기·`postCnt`·비공개는 `closed`) → 공지 제목 → 인기글 5줄(`views=`). 카테고리 줄마다 `posts <id> --category <no>`가 다음 홉이다.

**`related`는 두지 않는다.** 같은 카테고리 추천은 `post`가 이미 준다. 태그 기반 탐색은 검증된 `search --type tags <태그>`가 담당한다. 태그 추천 API(`end-recommend`)는 오늘 표본이 0건이라 스냅샷에 `verified:true, useful:unknown`으로만 남긴다(A5).

**날짜 창.** 입력은 **KST 날짜**(`YYYY-MM-DD`)이고 `--since`는 그날 00:00 포함, `--until`은 그날 **23:59:59 포함**이다. `search --type posts`에서만 서버 필터(`startDate`/`endDate`, 일 단위)로 내려가고 나머지는 클라이언트 필터다. 종료 판단은 항목 `addDate`로 하며, 최신순 표면(`post-list`, `sortType=date`, `home`)에서만 `window_reached`를 주장한다. 날짜가 없거나 단조성이 깨지면 필터만 적용하고 `exhausted`/`budget`으로 끝낸다.

**`--after <n>` 이어읽기.** 번호 핸들(`cursors/<n>.json`)에 다음 페이지 번호·문맥·`viewer_id`·아직 안 보인 꼬리를 담는다. 문맥(명령·대상·타입·정렬·계정)이 다르면 exit 2. **페이지 번호 재개는 서버 상태와 무관하지 않다** — 새 글이 앞에 끼면 경계가 밀린다. 안정 id로 중복은 제거하지만 누락 가능성은 `--help`와 `more:` 줄에 명시한다.

### 본문 파서 (`_body.py`)

표준 라이브러리 `html.parser`만 쓴다. 입력은 글 HTML, 출력은 `PostDoc(meta, tags, body)`이며 `body = Body(blocks[], images[], links[], attachments[], coverage)`.

- **컨테이너 선택은 구조로 한다.** `div.se-main-container`를 실제로 찾고 그 안에 `div.se-component`가 1개 이상이면 SE 경로. 없으면 `div#viewTypeSelector`(또는 `div.post_ct`)를 legacy 경로로 쓴다. 둘 다 없거나 둘 다 비었으면 **성공시키지 않고** exit 6 `envelope_drift`. `editorversion`은 참고값일 뿐 선택 기준이 아니다(오늘 4와 2 이하만 관측).
- **최상위 컴포넌트만 소유권을 갖는다.** 중첩된 `se-component`는 바깥 컴포넌트가 소비하며 두 번 추출하지 않는다(작은 태그 스택으로 범위를 추적).
- **계열 규칙**: `text`·`sectionTitle`(`## `)·`quotation`(`> `, 출처 포함)·`documentTitle`(제목과 같으면 생략) → 문단; `image`·`imageStrip`·`imageGroup` → 이미지마다 `[image: 캡션]`과 `images[]`에 `data-lazy-src` → 없으면 `data-linkdata.src` → 없으면 `src`; `oglink` → `link: 제목 (url)`; `material` → `[<type>: 제목 (url)]`(`type`은 module JSON의 값, 예 `book`); `table` → 행을 ` | `로; `sticker` → `[sticker]`; `horizontalLine` → `---`; `placesMap` → `[map: 장소명]`; **`video`** → `[video: 제목]` + `attachments[]`에 `{kind:"video", title, thumbnail_url, url: 있으면}`(재생 URL이 없으면 `url:null`이고 썸네일을 영상 URL로 쓰지 않는다); **`oembed`** → module JSON의 `inputUrl`·`description`·`thumbnailUrl`로 `[embed: 설명 (inputUrl)]`(영상이라고 단정하지 않는다).
- **일반 폴백**: 그 밖의 계열은 보이는 텍스트 + `img`(위 우선순위) + `a[href]`(내부 앵커·`#` 제외)를 살린다.
- **legacy 규칙**: 블록 경계(`p`,`div`,`br`,`li`,`h*`,`tr`)에서 줄을 나누고 `img`는 URL과 함께 `[image]`, `a[href]`는 `links[]`에 넣는다. 스크립트·스타일·주석은 버린다.
- **커버리지 회계.** 컴포넌트마다 `full`(전용 규칙) / `partial`(폴백으로 텍스트·이미지만) / `empty`(아무것도 못 건짐)를 센다. `coverage = {components, full, partial, empty, families:{name:count}, unhandled:[name…]}`. **텍스트 출력의 헤더와 본문 라벨이 이것을 반영한다**: 전부 `full`이면 `text[full]`, 하나라도 `partial`/`empty`면 `text[partial: 3 of 21 components reduced]`이고 헤더에 `unhandled: se-foo, se-bar`를 적는다.
- **정규화**: `&nbsp;`·제로폭·연속 공백 접기, 빈 줄 3개 이상 → 1개, **짝 없는 서로게이트 삭제**, 줄은 `⏎`로 잇는다.
- **경계 테스트 필수 입력**: void 태그(`<br>`,`<img>`), 닫는 태그 생략된 legacy `<p>`, 중첩 컴포넌트, 깨진 module JSON, 빈 `se-main-container`, `se-main-container`와 `post_ct` 공존, 태그 변수 부재.

### 출력 계약

기본은 텍스트다. 한 줄 본문, `⏎`, 따옴표 URL, 헤더 한 줄, 끝줄 `more:`와 다음 홉.

```
search · posts · "파이썬 크롤링" · sort=sim · 5 shown · stopped=limit_reached · reported≈27,295 (server figure) · fetched 7KB · local budget 1 of 10 (window 1/120)
[p1] akswodudwns/224391248663 · 김코딩 · 2026-08-22T20:14+09:00 · 코딩_초보를 위한_알쓸신잡 · likes=7 comments=0
     "[알쓸신잡] 매일 복붙하던 그 자료, 코드가 대신 긁어옵니다. - 크롤링 입문"
     "(기존 배운 파이썬 설치편을 참고하세요. (.venv) 켜고 하세요) pip …"
     url: "https://blog.naver.com/akswodudwns/224391248663"
more: python3 "/…/naver_blog.py" search "파이썬 크롤링" --after 3
open: `post <url>` · blog: `blog akswodudwns` · similar: `search --type tags <태그>`
```

```
post · naverofficial/224400531915 · body 2,140 chars · 21 components (21 full) · 9 images · 1 link · fetched 0.1MB · local budget 2 of 10
[p1] naverofficial (네이버 공식블로그, official) · 2026-09-04T09:30+09:00 · 이벤트/캠페인.zip · tags: AI탭, AI디깅클럽 · likes=99 comments=8
     "‘네이버 AI 디깅클럽’ 1기 발대식 후기 💙 ft. 100인의 크리에이터!"
     text[full]: "AI로 취향을 탐구하며 … ⏎ [image: 발대식 현장] ⏎ ## 100인의 크리에이터와 함께한 첫 만남 ⏎ …"
     url: "https://blog.naver.com/naverofficial/224400531915"
same category (이벤트/캠페인.zip): [s1] naverofficial/224342736839 "…" · likes=… · 2026-08-…  (×4)
comments: `comments naverofficial/224400531915` (8) · blog: `blog naverofficial` · tag: `search --type tags AI디깅클럽`
```

```
comments · naverofficial/223222167118 · 10 of 25 shown (24 comments + 1 reply, newest first) · fetched 30KB · local budget 2 of 10
[c1 #901140858609336335] gracegrace3 (blog: gracegrace3) · 2026-08-05T22:47+09:00 · likes=0
     "감사해요. 앞으로 잘 활용해 볼게요."
  [c2 reply-to=c1] 느릿 (blog: neurit) · 2026-08-06T09:02+09:00
     "…"
  [c3 reply-to=#804332662691987497 (parent not shown)] … 
[c4] [deleted]
more: python3 "/…/naver_blog.py" comments naverofficial/223222167118 --after 5
```

- 댓글 라벨은 표시 번호와 **원본 `commentNo`를 함께** 싣고, 부모가 이 페이지에 없으면 `parent not shown`으로 표시한다. `--json`과 `--out`에는 `commentNo`·`parentCommentNo`가 원값으로 남는다. **답글 완전성은 "반환된 것만"이라고 헤더가 말한다** — `replyPageSize=10`이므로 부모 하나에 답글이 10개를 넘을 때의 동작은 미확인이다(A11).
- 댓글 상태 라벨은 **확인된 불리언에만** 붙인다: `deleted`→`[deleted]`, `blind`/`hiddenByCleanbot`→`[blinded]`, `secret`→`[secret]`. `status`가 0이 아니면서 이 불리언이 전부 false면 본문을 숨기지 않고 `[status=<값>]`을 덧붙인다.
- 댓글 작성자의 `profileUserId`가 있으면 `(blog: id)`로 다음 홉을 만든다(확인: `daddy-challenge`). 없으면 `userName`만 싣는다.
- 목록 항목의 공개 범위: `allOpenPost:false`면 `[buddy-only]`·`[private]`, `postBlocked`면 `[blocked]`.
- **`--json`**: 항상 JSON 문서 하나. `{"ok", "command", "results"|"sections", "stop_reason", "next", "budget", "fetched_bytes", "warnings"}`. 복합 명령은 `sections:[{name, ok, data|error}]`. 모든 레코드에 **네임스페이스 id**를 붙인다: `post:<blogId>/<logNo>`, `blog:<blogId>`, `comment:<commentNo>`, `category:<blogId>/<no>`, `buddy:<blogId>`. `--out`의 중복 제거와 재개는 이 id로 한다. 값이 없어서 비운 필드는 `null`이고, **확인할 수 없어서 비운 필드는 `"unknown"`**이다(태그 변수 부재, 공감 수 미확인).
- **`stop_reason`**: `limit_reached | exhausted | window_reached | budget | blocked | query_failure | query_restricted | not_paginable | server_capped | pagination_stalled`.
- **종료 코드**: 0 성공 · 2 인자 · 3 aside · 4 네이버 로그인 필요 · 5 차단(429·로컬 창) · 6 `transient`\|`envelope_drift` · 7 정직한 0건 · 8 부분 결과·예산·정책 제한 · 9 대상 없음·삭제·비공개·소유자 전용.

### 디렉터리 구조 (최종)

기능 단위 모듈, 책임 하나, 400줄 이하. `_body`·`_models`·`_walk`는 transport를 import하지 않는다. **Python 20파일(엔트리 1 + `_*` 19) + JS 1.**

```
Agentic SNS/
├── .claude/
│   ├── harness-spec.md                     # 인벤토리 B13(naver-blog)·B14(쓰기 declined)·B15(통계·알림 declined)
│   ├── plans/naver-blog 스킬 구현 계획.md   # 이 파일을 옮긴 것 (.gitignore 예외)
│   └── skills/naver-blog/
│       ├── SKILL.md
│       └── scripts/
│           ├── naver_blog.py               # argparse·명령별 허용 옵션 표·충돌 거절·디스패치·종료 코드
│           ├── _errors.py                  # NaverBlogError(code, message, fix), fix 표, scrub(NID 쿠키·userKey·baUserKey·pstatic 서명)
│           ├── _aside.py                   # aside 스폰, 봉투 검증 (threads 이식)
│           ├── _budget.py                  # 예약 후 전송·페이싱·차단 파일·account_lock
│           ├── _session.py                 # session.json(viewer_id, read_at, account), TTL 12h, FeedList 판정, 뷰어 변경 시 커서 무효화
│           ├── _api.py                     # 오퍼레이션 카탈로그: 호스트·경로·쿼리 빌더·성공 플래그·리프·리프 타입·대상 식별 필드·페이지 정책·cap
│           ├── _transport.py               # fetch 조립·XSSI 제거·classify 8단계·대상 대조·Transport.get(op, **params)
│           ├── _target.py                  # id·URL → Target, 도메인 id 302, 명령별 허용 종류, 옵션 충돌
│           ├── _walk.py                    # 순수 봉투 워커: 리프 추출·원본 항목 수·페이지 표식
│           ├── _listing.py                 # 페이지 진행·cap 위치·반복 감지·클라이언트 창·limit·예산·pending 꼬리·stop_reason
│           ├── _models.py                  # Post(6종 카드 통합)·Comment + build_* (하이라이트 제거·날짜 3형·서로게이트)
│           ├── _entities.py                # Blog·Category·Buddy·Topic·MonthlyPick + build_*
│           ├── _body.py                    # 글 HTML → PostDoc(meta·tags·Body·coverage)
│           ├── _schema.py                  # to_dict → 필드 설명·JSON Schema
│           ├── _render.py                  # 객체 → 밀도 텍스트(정규화·chars·라벨은 여기만)
│           ├── _output.py                  # --json 문서·sections·네임스페이스 id·--out 커밋/재개·CursorStore
│           ├── _sections.py                # 복합 명령의 절 수집·부분 성공·exit 우선순위
│           ├── _cmds_read.py               # search·post·comments·find
│           ├── _cmds_blog.py               # blog·posts·buddies·home·topic·monthly
│           ├── _cmds_meta.py               # doctor·schema
│           └── browser/
│               └── fetch.js                # ARGS {host, path, query, accept} → GET (호스트·경로 허용 목록·고정 referer·manual redirect)
├── tests/naver_blog/
│   ├── conftest.py                         # NAVER_BLOG_ASIDE_BIN·NAVER_BLOG_HOME, live 마커, 누적 30요청 가드
│   ├── fake_aside/aside                    # 정규화된 전체 ARGS(host+path+query)로 픽스처 선택, 호출 순서를 로그에 기록
│   ├── js/test_fetch.js                    # 실제 스니펫 + mock fetch: 호스트·경로 거부, referer 고정, GET만, 3xx 봉투
│   ├── fixtures/*.ndjson, fixtures/*.html  # 합성: REST 14종·section 7종·CBOX 2종·글 HTML 5종(SE 풍부/legacy/공존/빈 컨테이너/깨진 JSON)
│   ├── tools/derive_fixture.py, check_fixtures_pii.py
│   ├── test_skill_doc.py                   # 프레임 검사: SKILL.md에 플래그·exit·명령 표 없음, --help와 중복 문장 없음
│   ├── test_cli.py, test_render.py, test_schema.py, test_errors.py   # 인터페이스 소유권 + 밀도 골든
│   └── test_transport.py, test_budget.py, test_session.py, test_target.py, test_api.py, test_walk.py, test_listing.py, test_models.py, test_entities.py, test_body.py, test_output.py, test_sections.py, live/test_live.py
├── .github/workflows/test.yml              # naver_blog 추가
└── README.md                               # 스킬 색인
```

**공개 seam(tdd에서 먼저 합의할 것).** ① CLI를 subprocess로 실행하고 stdout/exit을 검사(fake aside). ② `_body.parse(html) → PostDoc` 순수 함수. ③ `node --test`로 실제 `fetch.js` + mock fetch. ④ 두 프로세스가 같은 `NAVER_BLOG_HOME`에서 예산을 합산. ⑤ `_transport.classify(op_spec, envelope)` 순수 함수. 나머지 내부 모듈은 이 다섯 seam을 통해 검증하고, 모듈마다 테스트 파일을 강제하지 않는다.

### SKILL.md 골격 (D10)

```
---
name: naver-blog
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/naver_blog.py" *)
description: Read Naver Blog (blog.naver.com) through the user's logged-in Aside browser: search posts, blogs and tags across Naver, open a post in full with its tags and same-category posts, read a blog's card, category tree, post lists, notices and popular posts, read comments and replies, search inside one blog, browse topic directories and blogs of the month, and read the user's own neighbor feed and neighbor list. Use whenever the request is to read or explore something on Naver Blog — 네이버 블로그에서, 블로그 글 읽어줘, 이 블로그 카테고리, 댓글 봐줘, 이웃새글, 블로그 검색, 후기·리뷰·내돈내산 찾아줘 — including a bare blog.naver.com or m.blog.naver.com URL. Not for Naver Cafe, Naver News, Naver 지식iN, Naver Shopping, other Naver services, Tistory or Brunch, general web pages, or writing posts, comments, likes and neighbor requests.
---

# Naver Blog through the user's own browser
  한 문단: 브라우저가 로그인된 계정을, CLI가 읽기 전용 질의와 밀도 텍스트를 준다. `$NB` 표기 규칙. `--help`·`schema`·오류의 `fix`가 나머지를 가르친다.

## Naver's own counts are not answers
  목록의 총수는 0으로 오고 검색의 총수는 페이지마다 흔들린다. 검색은 어떤 정렬로도 1,000건에서 끊기며, 그 너머 페이지는 총수까지 0으로 바꿔 "결과 없음"처럼 보인다 — 도구는 이것을 `server_capped`로 구분한다. 그래서 "몇 건이나 있나"에 답할 때는 서버 숫자가 아니라 읽은 수를 말하고, 더 넓게 보려면 페이지를 더 넘기는 대신 날짜 창이나 검색어를 쪼갠다. 이웃새글은 페이지가 아예 없어 지금 있는 것만 준다.

## A post is one page, and the body is the only thing that can drift
  본문은 JSON이 아니라 편집기 HTML이다. 헤더의 `components`가 전부 `full`이면 본문은 그대로이고, `partial`이 있으면 그 컴포넌트는 텍스트와 이미지만 남았다는 뜻이며 `unhandled`에 계열 이름이 나온다. 축약된 본문을 요약하면서 완전한 것처럼 말하지 않는다. 태그가 `unknown`인 것은 태그가 없다는 뜻이 아니다.

## Reviews are an economy, not a sample
  네이버 블로그의 후기 코퍼스는 협찬·체험단·대가성 글이 많고 `is_ad` 같은 필드는 없다(`schema`에 없다). 판단 수단은 본문 첫 문단의 고지("소정의 원고료를 받고…"), `[buy-with-own-money]` 표식, 같은 블로그 글 목록의 밀도뿐이다. 무엇을 걸렀는지 보고에 쓴다. `sim` 정렬은 관련도이지 품질이 아니다.

## Handles and URLs are the next command's arguments
  출력의 `id/logNo`·`blogId`·`url:`이 곧 인자. 낯선 블로그는 `blog`으로 맥락을 먼저, 활동은 `posts`, 사람은 `buddies`, 댓글 작성자의 블로그 id가 있으면 그것이 다음 홉이다. 이웃 수는 카드에 있지만 공개 이웃 목록은 대개 비어 있다(비공개가 기본).

## What has actually bitten
  숫자만인 블로그 id가 실재하고 도메인 주소는 302로 다른 id가 된다. 답글은 댓글 목록에 평탄하게 섞여 오고 정렬은 최신순으로 고정돼 있다. 조회수는 인기글에만 있다. 태그 검색 결과에는 블로그 이름이 없다. 요약문은 글자 중간에서 잘려 이모지가 깨질 수 있다. 이어읽기는 페이지 번호라서 새 글이 앞에 끼면 경계가 밀린다.

## Large collections and what the cache holds
  `--out`은 클로드가 읽지 않을 만큼 클 때만. 파일과 캐시(`~/.cache/naver-blog-skill`)는 남의 개인정보이고, 실명·얼굴·동네가 흔한 매체다. 이웃 목록 + 글 목록 + 댓글 작성자를 합치면 한 사람의 관계망이 되므로 질문에 필요한 만큼만 모으고 작업 뒤 지운다.
```

## 구현 단계와 완료 판정

각 단계는 **`Skill(tdd)`로 열고 `Skill(codex)` diff 리뷰로 닫는다**(위 "게이트" 절의 산출물 셋과 `run_id` 기록이 없으면 그 단계는 완료가 아니다). `TaskCreate` 트래커에 아래 기준을 그대로 적는다. **라이브 예산표**: P1 4 + P2 8 + P3 8 + P4 8 = 28요청이 상한 30 안에 든다. **라이브는 고정 개수를 단언하지 않는다** — 타입·대상 일치·내부 정합(예: `shown ≤ pageModel.totalRows`)만 검사하고, 개수 단언은 합성 테스트에 둔다.

| 단계 | 내용 | 완료 판정 |
|---|---|---|
| P0 | 스캐폴드: `naver-blog/` 생성, `tests/naver_blog/`, 계획 파일 이동·`.gitignore` 예외, `harness-spec.md` 행 3개, 심볼릭 링크, `_api.py` 초안(**스냅샷의 오퍼레이션 전체**를 변환, 누락·중복 0으로 판정) | `audit_harness.py --path .` skill 5개·드리프트 0. `pytest tests/naver_blog` 0개 수집 exit 5. `ls -l ~/.claude/skills/naver-blog`가 레포를 가리킴. `_api` 로드 시 스냅샷과 op 집합이 정확히 일치 |
| P1 | `_errors`·`_aside`·`_budget`·`_session`·`_transport`·`_api`·`_target` + `fetch.js` + `doctor` | classify 픽스처 전부 통과: 429→5, **CBOX 3300→6 `envelope_drift`(차단 아님)**, `location: nid.naver.com`→4(모든 명령), FeedList에 링크 없음→6, 404 `not_exist_blog`→9, 400 `blog_id_invalidate`→9, 403 `not_blog_owner`→9 `owner_only`, 빈 403→6, `errorType=noPost`→9 / 다른 `errorType`→6 with reason, `param_is_invalidate`→2, `blockedByBifrostShield`→8 `query_restricted`, 대상 불일치(응답 logNo≠요청)→6, 정상 본문에 "제한되었습니다" 문구가 있어도 0. `_budget`: **전송 전 예약**(전송 중 프로세스 사망 시뮬레이션 후에도 창에 1회), 두 프로세스 합산, 창 초과→요청 없이 5, 40회에서 8, `--unblock`은 검증 성공 후에만 해제하고 창은 유지. `_target`: 8형 URL·숫자 id·가변 길이 logNo·`--category` 충돌 거절. node: 허용 밖 호스트/경로·POST 거부, 호스트별 referer, 3xx 봉투. **라이브(4요청)**: `doctor` exit 0(뷰어 `chunghun1`), **A1**을 위해 로그아웃 형태를 대신할 판정 근거 확인(FeedList 200 + 링크 존재), **A2**를 위해 `BuddyPostList`를 `countPerPage` 3과 30으로 각 1회 호출해 항목 집합이 동일함을 재확인(F14 회귀 감시) |
| P2 | `_walk`·`_listing`·`_models`·`_entities`·`_schema`·`_render`·`_output`·`_sections` + `search`·`blog`·`posts`·`find` | 합성: 6종 카드가 같은 `Post`로 정규화, 하이라이트 2종 제거, 날짜 3형, 서로게이트, 카테고리 트리(구분선 제외·부모 연결·비공개), **cap 위치 계산**(33페이지 30건 → 34페이지 10건 → `server_capped`; 35페이지 `totalCount:0`을 7로 만들지 않음), 짧은 페이지는 원본 수 기준, 반복 페이지 → `pagination_stalled`, 표식 우선(댓글·이웃·블로그 안 검색), 절 부분 성공(공지 실패해도 카드 유지, exit 8; 공지 0건은 실패 아님), 네임스페이스 id 중복 제거, render 골든. **라이브(≤8)**: `search 파이썬 --limit 3`, `--type blogs --limit 3`, `--type tags --limit 3`(각 1), `blog naverofficial`(4: 네 절 모두 ok, 카드의 blogId가 요청과 일치), `posts naverofficial --category 108 --limit 3`(1) |
| P3 | `_body` + `post`·`comments` | 단위: 계열 12종 + 미지 계열 + 중첩 + 빈 컨테이너 + 공존 + 깨진 module JSON + legacy(닫는 태그 생략) 픽스처에서 `coverage`가 `full/partial/empty`를 정확히 세고, `video`와 `oembed`가 분리되며, video의 `url`이 없으면 null이고 썸네일을 쓰지 않음, `text[partial: …]` 라벨, 태그 부재 → `unknown`; 댓글 평탄 목록의 `replyLevel:2` 들여쓰기·부모 부재 표시·원본 `commentNo` 보존·상태 라벨은 불리언에만·미지 status는 값 노출; A4 실패 시 `likes=unknown`. **라이브(≤8)**: `post naverofficial/224400531915`(2: 태그 존재, `blogNo`가 HTML과 추천 응답에서 일치, coverage 합이 컴포넌트 수와 같음), `post eijin1130/224403503427`(2: `sectionTitle`·`imageStrip`·`material`이 `full`), `comments naverofficial/223222167118 --limit 5`(2: `shown ≤ count.total`, 답글이 있으면 `reply-to` 표기), `post peopleteria/220108382928`(2: legacy 본문 길이 > 0) |
| P4 | `buddies`·`home`·`topic`·`monthly` + 날짜 창·`--out` | 단위: 내/공개 이웃 분기와 403 `owner_only`, `hasBuddy:false`→7, `home`의 `not_paginable`/`server_capped`, 주제 이름 해석(부분 일치·중복→2), 이달의 `prevMonth` 안내, 창 경계(KST·`--until` 당일 포함·서버 일 단위 변환·단조성 없으면 `window_reached` 미주장), `--out` 절 구조·네임스페이스 id·재개·완료 마커. **라이브(≤8)**: `buddies --limit 5`(1~2), `home --limit 5`(1: `stop_reason=not_paginable`), `topic`(1), `topic 문학·책 --limit 3`(1), `monthly`(2), `search 파이썬 --since <7일 전> --limit 3 --out <레포 밖>`(1) |
| P5 | `SKILL.md`·`harness-spec.md`·README·CI | **프레임 검사 통과**: `test_skill_doc.py`(플래그·exit·명령 표 0개), `--help`/`schema`/`fix` 소유권 테스트 4종, `test_render.py` 밀도 골든, SKILL–`--help` 중복 문장 0. `validate_harness.py --path .` exit 0, `audit_harness.py` 드리프트 0. description을 형제 4종·ultra-search와 나란히 읽어 트리거 절도·근접 오발 확인. codex가 SKILL.md 절 단위로 "왜가 없는 문장"을 0건 지목 |
| P6 | codex 사용성 검토 V1–V5·Graphify·PR | **소스 접근 없이** V1–V5 전부 수행, 각 시나리오에서 다음 명령이 출력 안에 있었는지 보고, 오발 셋 미호출. 지적은 재현 테스트로 수정. Graphify 갱신·명명, PR 스쿼시 머지 |

## Git과 Graphify

- 브랜치 `feat/naver-blog-skill`. 단계마다 논리 단위 커밋(`feat: naver-blog …`, 한국어 제목), P2 이후 푸시. PR 하나(`feat: Naver Blog 읽기 전용 스킬 구현`). 레포에 `.github/pull_request_template.md`가 없으므로 `## 무엇을 바꿨나` / `## 왜` / `## 영향` / `## 검증` 순서, `## 검증`에 실제 수치. CI 통과 후 `gh pr merge --squash`.
- Graphify는 P3 뒤·P6 뒤 두 번, 형제 방식(`graphify extract . --code-only --no-cluster` → codex 명명 → HTML 내보내기).

## 재사용 지도

| 출처 | 새 모듈 | 변경 |
|---|---|---|
| threads `_aside.py`·`_errors.py`·`_budget.py`+`_blocked.py`·`_output.py`·`_schema.py`·`_listing.py`·`_render.py`·`threads.py` | 각 대응 모듈 | 이름·마커·fix·민감 키(`NID_AUT`·`NID_SES`·`userKey`·`baUserKey`·pstatic 서명) 변경. `_budget`은 checkpoint 분기 제거·하한 0.5초. `_listing`은 커서 대신 페이지 번호 + cap 위치 + 반복 감지 |
| threads `browser/page.js` | `browser/fetch.js` | 호스트·경로 허용 목록, 호스트별 referer, `accept` 인자, GET만 |
| threads `tests/threads/{conftest, fake_aside, tools, js}` | `tests/naver_blog/…` | 이식 + 30요청 가드. fake_aside는 **query 포함 전체 ARGS**로 매칭·순서 기록 |
| 옛 `endpoints.py` | `_api.py` | URL·파라미터·상한·오류 코드 지식. 스냅샷 JSON이 원본 |
| 옛 `identifiers.py` | `_target.py` | URL 형태 + 숫자 id + 가변 길이 logNo. 도메인 id 302는 신규 |
| 옛 `body.py` | `_body.py` | 컨테이너 판정·계열 지식·video/oembed 구분·정규화만 이식, lxml → `html.parser`로 새로 씀. 커버리지 회계·일반 폴백은 신규 |
| 옛 `model.py`의 정규화 규칙 | `_models.py`·`_entities.py` | 하이라이트·날짜·id 문자열화·구분선·서로게이트만. `raw`·스키마 생성기는 버림 |
| 옛 `parse.py`의 리프 경로 | `_walk.py`·`_api.py` | 스냅샷의 `leaf`로 |
| 옛 `client.py`·`retrieve.py`·`cli.py`·`config.py`·`redact.py` | — | 가져오지 않음 |
| ultra-search `to_markdown.mjs` | — | 쓰지 않음: 흐린 플레이스홀더 이미지를 집고 헤더 잡음이 섞이며 node 런타임 의존이 생긴다 |

## 검증

- 단위: `python3 -m pytest tests/ -q`. JS: `node --test tests/naver_blog/js/*.js`. 린트: `uvx ruff check --config pyproject.toml .claude/skills/naver-blog/scripts tests/naver_blog`. PII: `python3 tests/naver_blog/tools/check_fixtures_pii.py`(실명·닉네임·blogId·logNo·userKey·프로필 URL 게이트).
- 라이브: `python3 -m pytest -m live tests/naver_blog/live/ -q`. 타입·대상 일치·내부 정합만. 누적 30요청 가드.
- 하네스: `validate_harness.py --path .` exit 0, `audit_harness.py` 드리프트 0.
- 프레임 검사(D12): `python3 -m pytest tests/naver_blog/test_skill_doc.py tests/naver_blog/test_render.py tests/naver_blog/test_schema.py tests/naver_blog/test_errors.py tests/naver_blog/test_cli.py`.
- codex: 계획 리뷰(이 세션, 완료) → **단계별 diff 리뷰 7회**(P0–P6, `run_id` 기록) → 최종 사용성 검토. 기준은 **"본문과 `--help`·출력만으로, 구현 소스를 보지 않고 다섯 시나리오를 수행하나"**: V1 글 요약(URL) → `post`, coverage와 태그까지 보고. V2 댓글 분위기 → `comments`, 총수·정렬·답글 관계 명시. V3 이 블로그 어떤 곳인가 → `blog` → `posts --category`. V4 내돈내산 후기 찾기 → `search --own-money` → `post` 2~3개, 협찬 판단 근거 보고. V5 이웃 새글 → `home` → `post`. 근접 오발 셋: 네이버 카페 / 티스토리 / 네이버 뉴스 → 미호출.
- Claude e2e: 미실행(D6).

## 위험과 처리

| 위험 | 처리 |
|---|---|
| 실계정 쿠키(로그인 한도 미관측) | 하한 0.5초·지터, 10분 120회, 호출당 10/40/60, **예약 후 전송**, 429만 차단, SKILL.md의 요청 수 원리, 라이브 예산표 |
| 본문 HTML 드리프트 | 구조 기반 컨테이너 선택, 일반 폴백, **커버리지가 텍스트 출력에 나타남**, `envelope_drift`는 컨테이너 부재·빈 추출에만, 픽스처 5종 + 라이브 3표본 |
| 서버 숫자 불신(총수 0·상한 1,000·거짓 0) | 원본 항목 수 기준 종료, cap 위치 추적, `server_capped`, `reported≈ (server figure)` 표기 |
| 서버가 페이지 인자를 무시(F14 회귀) | `pagination_stalled`, `home`은 `not_paginable`, P1 라이브가 F14를 회귀 감시 |
| 복합 명령의 절 실패 | `_sections`의 부분 성공 계약과 exit 우선순위, 주 절 보존 |
| 답글 완전성 미확인(A11) | 헤더가 "반환된 것만"이라고 말하고 부모 부재를 표시 |
| 수집 파일·캐시의 개인정보 | 레포 밖 권장, `.gitignore`, PII 게이트, SKILL.md의 관계망 원리 |
| 이전 시도 재발(문서형·파일 출력) | D5·D10, codex V1–V5, SKILL.md는 형제 수준 길이 |

## 미룬 것 (스펙에 기록)

- 쓰기 전부(댓글·공감·이웃추가·스크랩·신고): `declined`. 내 통계·알림·내소식·안부글: `declined`. 인기 키워드·핫토픽·모먼트·마켓·이미지 검색: 범위 밖.
- `related` 명령: 두지 않는다(같은 카테고리는 `post`가, 태그는 `search --type tags`가 담당). 태그 추천 API는 스냅샷에만 남긴다(A5).
- section `type=id`(아이디 검색): 블로그 검색이 대체하므로 **의도적 제외**.
- 모바일 이웃새글 POST 피드: 2페이지부터 추천 글뿐이라 채택하지 않는다(F14). 이웃 글을 더 보려면 `buddies` → `posts`가 정확하다.
- 이웃공개 글 본문: 목록 라벨만. 이웃인 블로그의 이웃공개 글 HTML 형태는 미관측.
- `naver.me` 단축 링크(A6): exit 2. 미디어 다운로드: `--json`의 URL로 충분한지 먼저 본다.

## 가정 (구현 세션이 확인)

- **A1** 로그아웃 세션에서 `FeedList.naver`는 `nid.naver.com`으로 302하거나 로그인 폼을 준다. **미관측이므로 링크 부재만으로 exit 4를 내지 않는다**(설계에 반영). P1에서 로그인 상태의 양성 형태만 확인한다.
- **A2 (해소)** `BuddyPostList`는 페이지 인자를 무시한다(F14 실측). P1 라이브가 회귀만 감시한다.
- **A3 (확인됨)** `my-buddies`는 소유자만 200, 남은 403 `not_blog_owner`.
- **A4** `category-related-posts`의 첫 항목이 요청한 글 자신이다(1표본). 아니면 `likes=unknown`.
- **A5** 태그 추천이 다른 블로그 글을 준다. 오늘 0건이라 명령을 만들지 않았다.
- **A6** `naver.me/<code>`는 302로 정식 글 URL을 준다.
- **A7** 로그인 상태의 차단 서명(캡차·인증 페이지)은 미관측. 관측되면 무만료 분기를 추가한다.
- **A8 (해소)** `search/v1/blog`가 존재하며 `buddyCount`·`blogDesc`·`officialBlog`를 준다. `[옛]`의 `v2/blog` 지식은 대체 경로로 스냅샷에 남긴다.
- **A9 (확인됨)** 댓글 작성자 blogId는 `profileUserId`(`daddy-challenge`). `userIdNo`는 빈 문자열이라 쓰지 않는다.
- **A10** 이웃공개 글(`buddyOpen`)의 HTML은 이웃이 아니면 `MobileErrorView`로 간다. `errorType` 원값을 `reason`에 싣는다.
- **A11** 부모 하나의 답글이 10개(`replyPageSize`)를 넘을 때의 반환 범위. 미확인이므로 "반환된 답글만"으로 표기한다.

## 구현 진행 기록

| 단계 | 커밋 | codex 리뷰 run | 지적/반영 | 먼저 실패한 것 |
|---|---|---|---|---|
| P0 | `bbdf4e3` + 후속 | `20260907-214127-nb-p0-7108` | 12건 중 12건 반영 | 경로 플레이스홀더 이름 비교, `comments`의 page_size가 `params.pageSize`에만 있음, `buddy_feed`가 `countPerPage`를 보내면서도 페이지 없음(F14) |
| P1 | `8a4c1e0` + 후속 | `20260907-215253-nb-p1-94f4` | 21건 중 21건 반영 | 로그인 302가 실제 전송 경로에서 6이 됨, `--unblock`이 검증 실패에도 해제, 허용 목록 접두 일치가 `/PostView.naver.evil`을 통과, 비객체 JSON에서 AttributeError |
| P2 | `5be8780` + 후속 | `20260907-220853-nb-p2-f59b` | P1 6건 전부 반영 | 상한·단일 페이지에서 미표시 꼬리 소실, 재개 문맥에 날짜·내돈내산 누락, 미완료 `--out`이 1페이지부터 재시작, `more:`가 `--out` 누락, `repr` 인용의 셸 확장, 파일 중간 손상을 꼬리로 오인 |
| P3 | `51fa41e` + `25c3015` | `20260907-221750-nb-p3-08ca` | P1 8건 전부 반영("승인하기 어렵다" 판정) | 본문 순서가 `앞<b>중간</b>뒤`→`앞뒤중간`, 닫히지 않은 `<p>`의 RecursionError, `data-module`이 `{type,data}`인데 최상위에서 읽음, 중첩 소유권이 이미지 손실을 숨김, `post --comments`가 차단을 빈 댓글로, logNo 미대조, tidy가 서로게이트를 남김, `post --out` 미저장 |
| P4 | `eeff4da` + 후속 | `20260907-223002-nb-p4-176f` | P1 6건 전부 반영("승인 보류" 판정) | 인라인 태그 아래의 `<p>`는 여전히 RecursionError, 중첩 판정이 이미지 수만 봄(빈 결과를 full로 승격하는 회귀 포함), `siblings_after` 가드가 정상 페이지의 위젯을 본문에 섞음, `post --out`이 실패 절을 지우고 완료로 기록, `topic --out`이 저장 없이 성공, 주제 목록의 `domainIdOrBlogId`를 버림 |
| P5 문서 | `67fea03` + 후속 | `20260907-223953-nb-p5-doc-257b` → `…-6ba5` | "왜 없는 문장" 6건 + 별도 4건 반영, 재심사에서 6/6 해소 확인 | "What has actually bitten" 절의 다섯 문장이 사실만 말하고 결과 해석이 없었음, 절 제목의 "본문만 변할 수 있다"가 과한 단정, "브랜드마다 다른 글이면 광고 채널"이 정황을 확정으로, description의 주제어 트리거가 형제를 훔칠 여지 |
| P6 사용성 | 아래 | `20260907-224153-nb-p6-usability-beae` | V1–V5 전부 소스 없이 수행, 오발 셋 미호출 | 댓글이 전부 자기 자신을 부모로 표시(네이버가 최상위 댓글을 그렇게 표시함), `schema`에 본문·커버리지·`sections` 구조가 없음, 다중 단어 검색어가 인자 오류, 헤더의 `own_money`가 `True`로 표시, 제목에 " : 네이버 블로그" 접미사 |

**P0에서 계획을 정정한 것.** ① 1,000건 상한 판정: "위치가 1000에 닿음"은 태그 검색(위치 990에서 짧아짐)을 놓치므로 `position + page_size > cap`으로 바꿨다(위 "페이지 정책" 절 반영). ② P0 완료 판정의 "pytest 0개 수집 exit 5"는 같은 행의 "`_api` 집합 일치" 요구와 모순이므로 후자를 기준으로 삼았다. ③ SKILL.md는 P5 산출물이므로 P0의 감사 기준은 스펙 행 `planned` + 드리프트 0이다. ④ 스냅샷 행의 `verified:true`는 "엔드포인트가 존재한다"이지 "페이지 계약을 로그인 상태에서 재확인했다"가 아니므로, `_api.py`에 `source='measured'|'legacy'` 필드를 두고 블로그 안 태그 검색을 `legacy`로 표시했다(그 `totalPage`는 쓰지 않는다).

**P0에서 설계를 강화한 것.** `_api.build()`가 쿼리 조립을 소유한다 — 호출자는 식별자만 넘기고, 댓글의 `objectId`(`{blogNo}_201_{logNo}`)·`groupId`처럼 파생되는 값은 장부 안에서만 만들어진다. 조용히 틀릴 수 있는 값을 호출자 손에 두지 않기 위해서다. 장부 행은 `frozen`이고 `build`는 `params`를 복사해 쓰므로 호출 간 값이 새지 않는다.

**P1에서 계획을 정정한 것.** ① classify 1단계의 "비JSON"은 429·리다이렉트보다 먼저 걸려 빈 본문 429를 6으로 만든다. HTTP·리다이렉트 신호를 먼저 보고 JSON 파싱은 그 뒤로 옮겼다. ② `--unblock`의 해제 조건은 "200"이 아니라 "뷰어 식별 성공"이다 — 같은 계획이 200 점검 페이지를 `envelope_drift`로 구별하기 때문이다. 동시에 다른 프로세스가 새로 기록한 429는 지우지 않도록 `blocked_at`을 대조한다. ③ 예약과 페이싱의 순서는 계획의 "예약 → 페이싱"이 아니라 "페이싱 → 예약"으로 둔다. 예약 시각이 실제 전송 시각과 멀어지면 창이 먼저 만료되기 때문이고, 전송 전 예약이라는 성질은 그대로다. ④ F14 라이브 판정은 순서가 아니라 집합 일치다 — 두 요청 사이에 이웃이 글을 올리면 순서가 바뀐다. ⑤ A1(로그아웃 서명)은 계속 미확인이다. 로그인 상태의 양성 표본은 F6 회귀 감시일 뿐 로그아웃 형태를 입증하지 않는다.

**P1에서 강화한 것.** 허용 목록을 접두 일치에서 전체 일치 정규식으로 바꾸고, `tests/naver_blog/fixtures/paths.json` 한 표를 파이썬과 `fetch.js`가 같이 읽는다 — 한쪽에만 규칙을 더하면 다른 쪽이 실패한다. 대상 대조는 장부의 `identity`에서 자동으로 나오므로 호출자가 잊을 수 없고, `result.commentList[].objectId` 같은 목록 경로도 항목마다 대조한다. 정책 제한 오류는 도착한 결과를 `error.payload`에 싣는다. 예산 경합은 두 프로세스를 같은 시각에 출발시키는 테스트가 잡는다(락을 지우면 실제로 실패함을 확인했다).

**P2–P4에서 계획을 정정한 것.** ① `--limit`·`--sort`의 기본값을 파싱 뒤에 채워 "사용자가 명시했나"를 구분한다 — 값으로 판단하면 `search --limit 10`이 기본값과 같아 예산 40을 못 받는다. ② 블로그·태그 검색에는 정렬 파라미터가 스냅샷에 없으므로 `--sort`를 거절한다(계획 표의 "blogs만" 기재를 정정). ③ 인기글·공지·주제 디렉터리·주제 인기글은 단일 페이지이므로 `--out`·`--after`·날짜를 요청 전에 거절한다 — 옵션을 받고 무시하면 파일이 조용히 비어 있다. ④ 절 exit는 계획대로 4>5>9>6>8이되 4·5·9는 그 코드 그대로, 6·8만 "부분"으로 낸다. ⑤ `no_paging` 표면에서는 `window_reached`를 주장하지 않는다 — 다음 페이지가 없으므로 "창 때문에 멈췄다"가 서버가 덜 준 사실을 덮는다. ⑥ 미래 달은 응답의 `prevMonth`+1로 실제 회차를 계산해 경고한다. ⑦ 주제 목록의 블로그 식별자는 `domainIdOrBlogId`다.

**본문 파서에서 확인한 것.** `data-module`은 `{type, data:{…}}`이고 영상 제목은 `data.mediaMeta.title`이다(이전 구현 `body.py:142`와 픽스처로 확인). HTMLParser가 속성 엔티티를 이미 풀므로 다시 풀면 안 된다. 컨테이너 밖으로 밀려난 컴포넌트를 본문에 끌어오는 가드는 정상 페이지의 위젯을 섞으므로 두지 않는다 — 브라우저도 그 경계에서 끊는다.

**최종 검증 (2026-09-07).** 오프라인 335개·JS 9개, 전체 레포 1,005 passed·39 deselected. Ruff·PII(6파일 0건)·`validate_harness.py`(0/0)·`audit_harness.py`(skill 5개·드리프트 0) 통과. 라이브 15개가 누적 30요청 가드 안에서 통과했다 — `doctor`가 `chunghun1`을 보고했고, `BuddyPostList`가 `countPerPage` 3과 30에 같은 집합을 돌려줬으며(F14 회귀 없음), 실제 SE 리치 글이 33컴포넌트 전부 `full`로 읽혔다. Graphify는 2,290노드·5,282간선·150커뮤니티로 갱신하고 codex가 새 커뮤니티를 명명했다. PR #5.

**라이브 미확인으로 남긴 것.** A1(로그아웃 `FeedList` 형태), A6(`naver.me`), A7(로그인 상태 차단 서명), A11(답글 10개 초과 부모의 반환 범위). 코드는 미관측을 근거로 판정을 승격하지 않는다 — 링크 부재는 로그아웃이 아니라 `envelope_drift`이고, 차단은 HTTP 429만이며, 관측 안 된 `errorType`은 원값을 `reason`에 실은 채 6이다.

**P5·P6에서 정정한 것.** ① SKILL.md의 사실 문장은 전부 결과 해석과 함께 쓴다 — 재심사에서 6건 모두 해소를 확인했다. ② description은 소재지로 고르고 주제어로 고르지 않는다고 명시한다("리뷰·후기"만으로 이 스킬을 택하면 형제의 요청을 가져간다). ③ **네이버는 최상위 댓글의 `parentCommentNo`를 자기 자신으로 채운다** — 그대로 쓰면 모든 댓글이 자기 답글로 보인다(실측으로 확인). ④ `schema`는 `Post.body`와 `Section`을 정의한다. `--json`으로 바꿨을 때 본문 완전성을 어디서 보는지 알 수 없었다. ⑤ 검색어는 여러 낱말을 하나의 질의로 받는다 — 한국어 검색은 대개 여러 낱말이고, 따옴표를 강제하면 자연스러운 형태가 인자 오류가 된다. ⑥ 글 제목의 " : 네이버 블로그" 접미사를 벗긴다.

## codex 리뷰 반영 (2026-09-07, run `20260907-211739-naver-blog-plan-review-bf87`)

24건 중 24건 반영. P1(12건): (1) CBOX `3300`을 차단에서 계약 오류(6)로 내리고 429만 차단으로 남김, (2) 오퍼레이션별 성공 플래그·리프 타입·대상 대조를 classify 입력으로 승격하고 정책 제한을 `query_restricted`(8)로 분리, (3) `_sections.py`와 절 단위 부분 성공·exit 우선순위 신설, (4) 로그인은 명시적 `nid.naver.com`으로만 모든 명령에서 판정하고 링크 부재는 6, 미관측 `errorType`은 6, (5) 1,000건 cap을 누적 위치로 추적하고 그 너머의 `totalCount:0`을 7로 만들지 않음(실측 F13 추가), (6) 반복 페이지를 `pagination_stalled`로 분리하고 A2를 실측으로 해소(F14), (7) 커버리지 회계를 텍스트 출력의 `text[partial: …]`·`unhandled`로 노출, (8) 컨테이너 선택을 구조 기반으로 바꾸고 최상위 소유권·빈 추출 실패를 규정, (9) `video`와 `oembed` 분리·썸네일을 영상 URL로 쓰지 않음, (10) 댓글의 원본 번호 보존·부모 부재 표시·답글 완전성 한계(A11), (11) 상태 라벨을 확인된 불리언에만, (12) 예산을 전송 전 예약으로·`--unblock`은 검증 후·창 유지. P2(11건): (13) 명령별 허용 옵션·기본값·충돌 표, (14) 요청 수를 기본+조건부로 분리하고 이름 해석·도메인 id·추천 자기 자신을 반영, (15) 세션 TTL 12시간·뷰어 변경 시 커서 무효화·페이지 재개의 누락 가능성 명시, (16) 태그 검색 30건 등 페이지 크기 표(F17)와 표식 우선 규칙(F16), (17) 날짜 창의 KST·`--until` 포함·서버 일 단위, (18) 폴백의 링크·이미지·첨부 보존 규칙과 파서 경계 테스트 목록, (19) fake aside를 전체 ARGS 매칭으로 바꾸고 공개 seam 다섯을 명시, (20) 네임스페이스 id·절 구조·`unknown` vs `null`, (21) 라이브에서 고정 개수 단언 제거·A1/A2를 P1로, (22) `related` 삭제와 `type=id` 의도적 제외 기록, (23) 출처 표기 `[옛]`·`[가정]` 도입, `v2/blog` 지식 보존, logNo 가변 길이. P3(1건): (24) 파일 수·오퍼레이션 수를 실제와 맞추고 완료 판정을 집합 일치로 변경.

## 엔드포인트 스냅샷

`_api.py`는 이 블록을 그대로 옮긴다. `verified`는 2026-09-07 로그인 세션 실측 여부이고 `[옛]` 표시는 이전 익명 정찰 출처다.

```json
{
 "captured_at": "2026-09-07",
 "account_note": "Aside u0 (naver chunghun1, blogNo 142227876); samples naverofficial/42609743, eijin1130/53706702, peopleteria(legacy)",
 "contract": {
  "referer": {"m.blog.naver.com": "https://m.blog.naver.com/", "section.blog.naver.com": "https://section.blog.naver.com/", "apis.naver.com": "https://m.blog.naver.com/", "blog.naver.com": "https://blog.naver.com/"},
  "envelopes": {"mblog": "{isSuccess, result} | {isSuccess:false, error{code,message,details}}", "section": ")]}',\\n{result}", "cbox": "{success, code, message, result}"},
  "method": "GET only",
  "search_ceiling": 1000,
  "ceiling_note": "past the ceiling totalCount itself becomes 0 on search/v1/post; never treat that as an honest zero"
 },
 "operations": [
  {"op": "search_posts", "host": "m.blog.naver.com", "path": "/api/search/v1/post", "params": {"keyword": "<text>", "sortType": "sim|date", "page": 1, "itemCount": 30, "startDate": "YYYY-MM-DD?", "endDate": "YYYY-MM-DD?", "isBuyWithMyOwnMoney": "true?"}, "success": "isSuccess", "leaf": "result.list", "leaf_type": "list", "identity": null, "pagination": "page", "page_size": 30, "cap": 1000, "verified": true, "notes": "highlight <em class=\"highlight\">; totalCount/totalPage unreliable; p33=30 p34=10 p35=0 with totalCount 0"},
  {"op": "search_blogs", "host": "m.blog.naver.com", "path": "/api/search/v1/blog", "params": {"keyword": "<text>", "page": 1, "itemCount": 30}, "success": "isSuccess", "leaf": "result.list", "leaf_type": "list", "pagination": "page", "page_size": 30, "cap": 1000, "verified": true, "notes": "blogName plain, blogNameWithTag highlighted; buddyCount present"},
  {"op": "search_tags", "host": "m.blog.naver.com", "path": "/api/tags/search/post", "params": {"query": "<text>", "page": 1, "itemCount": 30}, "success": "isSuccess", "leaf": "result.items", "leaf_type": "list", "pagination": "page", "page_size": 30, "cap": 1000, "verified": true, "notes": "no blogNo/blogName/categoryName; p34 empty while totalCount stays"},
  {"op": "search_posts_section", "host": "section.blog.naver.com", "path": "/ajax/SearchList.naver", "params": {"type": "post", "keyword": "<text>", "orderBy": "sim|date", "currentPage": 1, "countPerPage": 30}, "success": null, "leaf": "result.searchList", "leaf_type": "list", "pagination": "page", "page_size": 30, "cap": 1000, "verified": true, "role": "fallback", "notes": "used only if search_posts drifts; totalCount is the 1000 cap itself"},
  {"op": "search_blogs_section", "host": "section.blog.naver.com", "path": "/ajax/SearchList.naver", "params": {"type": "blog", "keyword": "<text>", "orderBy": "sim|date", "currentPage": 1, "countPerPage": 30}, "success": null, "leaf": "result.searchList", "leaf_type": "list", "pagination": "page", "page_size": 30, "cap": 1000, "verified": true, "role": "fallback"},
  {"op": "blog_card", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}", "success": "isSuccess", "leaf": "result", "leaf_type": "dict", "identity": "result.blogId", "pagination": "single", "verified": true, "notes": "404 not_exist_blog today; [옛] 400 blog_id_invalidate"},
  {"op": "categories", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/category-list", "success": "isSuccess", "leaf": "result.mylogCategoryList", "leaf_type": "list", "pagination": "single", "verified": true, "notes": "drop divisionLine/categoryType S; mylogPostCount is the trustworthy total"},
  {"op": "post_list", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/post-list", "params": {"categoryNo": 0, "itemCount": 30, "page": 1}, "success": "isSuccess", "leaf": "result.items", "leaf_type": "list", "pagination": "page", "page_size": 30, "verified": true, "notes": "itemCount>30 -> param_is_invalidate; result.totalCount always 0 and result.page always 1; stop on raw short page"},
  {"op": "popular_posts", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/popular-post-list", "success": "isSuccess", "leaf": "result.popularPostList", "leaf_type": "list", "pagination": "single", "verified": true, "notes": "only surface with viewCount"},
  {"op": "notice_posts", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/notice-post-list", "success": "isSuccess", "leaf": "result.noticePostViewList", "leaf_type": "list", "pagination": "single", "verified": true, "notes": "commentCount and postOpenType, not commentCnt"},
  {"op": "blog_search", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/search/post", "params": {"query": "<text>", "sortType": "sim|date", "page": 1}, "success": "isSuccess", "leaf": "result.list", "leaf_type": "list", "pagination": "page_marked", "page_size": 20, "marker": "result.totalPage", "verified": true, "notes": "keyword= returns 500"},
  {"op": "blog_tag_search", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/search/tag", "params": {"query": "<tag>", "page": 1}, "success": "isSuccess", "leaf": "result.list", "leaf_type": "list", "pagination": "page", "page_size": 30, "verified": true, "notes": "[옛] 30 per page, sortType ignored, totalPage miscomputed against 20 -> do not use the marker"},
  {"op": "public_buddies", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/public-buddies", "params": {"pageNo": 1}, "success": "isSuccess", "leaf": "result.buddyList", "leaf_type": "list", "pagination": "page_marked", "page_size": 20, "marker": "result.totalPageCount", "verified": true, "notes": "updateTime may be null; empty list is normal"},
  {"op": "my_buddies", "host": "m.blog.naver.com", "path": "/api/blogs/{me}/my-buddies", "params": {"pageNo": 1, "sortType": 2}, "success": "isSuccess", "leaf": "result.buddyList", "leaf_type": "list", "pagination": "page_marked", "page_size": 20, "marker": "result.totalPageCount", "login": true, "verified": true, "notes": "403 not_blog_owner for anyone else (A3 confirmed)"},
  {"op": "buddy_feed", "host": "section.blog.naver.com", "path": "/ajax/BuddyPostList.naver", "params": {"currentPage": 1, "groupId": 0, "countPerPage": 30, "categoryNo": 0}, "success": null, "leaf": "result.buddyPostList", "leaf_type": "list", "pagination": "no_paging", "total_field": "result.buddyPostTotalCount", "login": true, "verified": true, "notes": "F14: currentPage/countPerPage/groupId all ignored; identical set on pages 1,2,4,9 and sizes 3,10,30"},
  {"op": "post_html", "host": "m.blog.naver.com", "path": "/PostView.naver", "params": {"blogId": "<id>", "logNo": "<logNo>"}, "accept": "text/html", "leaf": "#_post_property attrs; var blogNo/blogId/postTitle/gsCategoryName/gsTagName/userId/openType; div.se-main-container | div#viewTypeSelector", "pagination": "single", "identity": "var blogNo + uri", "verified": true, "notes": "404 + MobileErrorView errorType=noPost; 66-132KB"},
  {"op": "comments", "host": "apis.naver.com", "path": "/commentBox/cbox/web_naver_list_json.json", "params": {"ticket": "blog", "templateId": "default_simple", "pool": "blogid", "objectId": "{blogNo}_201_{logNo}", "groupId": "{blogNo}", "listType": "OBJECT", "pageType": "more", "page": 1, "pageSize": 100, "indexSize": 10, "replyPageSize": 10, "showReply": "true", "initialize": "true", "useAltSort": "true", "lang": "ko"}, "success": "success", "leaf": "result.commentList", "leaf_type": "list", "identity": "result.commentList[].objectId", "pagination": "page_marked", "marker": "result.pageModel.totalPages", "verified": true, "notes": "replies inline at replyLevel 2, replyList always null; sort param ignored (always REVERSE_NEW); X-Cbox-Api-Sdk-Version not required; code 3300 also comes from a wrong pool -> contract error, not a block"},
  {"op": "comments_info", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/posts/{logNo}/comments-info", "success": "isSuccess", "leaf": "result", "leaf_type": "dict", "pagination": "single", "verified": true, "notes": "404 not_exist_post; source of blogNo when no HTML was read"},
  {"op": "related_category", "host": "m.blog.naver.com", "path": "/api/blogs/{blogId}/v1/category-related-posts", "params": {"blogId": "<id>", "categoryNo": "<no>", "countPerPage": 5, "logNo": "<logNo>", "isInitialPage": "true", "isFromSearchAddView": "false"}, "success": "isSuccess", "leaf": "result.recommendationPostList", "leaf_type": "list", "pagination": "single", "verified": true, "notes": "first item was the post itself on the one sample (A4); addDate ISO +0900"},
  {"op": "related_tag", "host": "m.blog.naver.com", "path": "/api/end-recommend/search/tag-posts", "params": {"blogId": "<id>", "logNo": "<logNo>", "countPerPage": 6, "recommendationType": "FIRST_TAG_POST", "recommendationCategory": "ETC", "searchKeyword": "<first tag>"}, "success": "isSuccess", "leaf": "result.recommendationPostList", "leaf_type": "list", "pagination": "single", "verified": true, "useful": "unknown", "notes": "0 items on the sample (A5); no command uses it yet"},
  {"op": "directories", "host": "section.blog.naver.com", "path": "/ajax/DirectoryList.naver", "success": null, "leaf": "result", "leaf_type": "list", "pagination": "single", "verified": true, "notes": "4 groups, 32 topics, 1.7KB"},
  {"op": "directory_posts", "host": "section.blog.naver.com", "path": "/ajax/DirectoryPostList.naver", "params": {"directorySeq": "<seq>", "pageNo": 1}, "success": null, "leaf": "result.postList", "leaf_type": "list", "pagination": "page", "page_size": 10, "cap": 1000, "verified": true},
  {"op": "directory_top", "host": "section.blog.naver.com", "path": "/ajax/DirectoryTopPostList.naver", "params": {"directorySeq": "<seq>"}, "success": null, "leaf": "result", "leaf_type": "list", "pagination": "single", "verified": true, "notes": "9 items, no counts"},
  {"op": "monthly_blogs", "host": "section.blog.naver.com", "path": "/ajax/ThisMonthDirectoryBlogList.naver", "params": {"year": 2026, "month": 8}, "success": null, "leaf": "result.list", "leaf_type": "list", "pagination": "single", "verified": true, "notes": "115KB; prevMonth/prevYear for navigation; [옛] future month clamps"},
  {"op": "editor_picks", "host": "section.blog.naver.com", "path": "/ajax/EditorPickList.naver", "params": {"year": 2026, "month": 8}, "success": null, "leaf": "result.list", "leaf_type": "list", "pagination": "single", "verified": true},
  {"op": "feed_html", "host": "m.blog.naver.com", "path": "/FeedList.naver", "accept": "text/html", "leaf": "href=\"/BuddyList.naver?blogId=<me>\"", "pagination": "single", "login": true, "verified": true, "notes": "22KB; doctor and viewer-id source; logged-out shape unverified (A1) so absence alone is envelope_drift, not a login error"},
  {"op": "domain_redirect", "host": "blog.naver.com", "path": "/{maybeDomainId}", "accept": "text/html", "leaf": "location header -> NBlogTop.naver?blogId=<canonical>", "pagination": "single", "verified": true, "notes": "only after a not_exist_blog; one hop, host and path validated"}
 ]
}
```
