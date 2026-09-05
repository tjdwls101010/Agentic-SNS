# `facebook` 스킬 구현 계획

계획 세션: 2026-09-05. 구현 세션은 이 파일만 읽고 시작할 수 있어야 한다. 아래의 모든 수치는 이 세션에서 실측한 값이다. codex(gpt-6-astra, medium) 적대적 리뷰 1회를 반영했다(맨 끝 절).

## Context

성진은 클로드가 페이스북을 **사람처럼** 돌아다니는 역량을 원한다. 피드를 훑다가 글을 열고, 댓글을 읽고, 댓글 쓴 사람의 프로필과 글을 보고, 거기서 다시 이어가는 흐름을 스크린샷·클릭 없이 구조화된 텍스트로 수행한다. 시각 UI 대신 페이스북 웹 클라이언트가 실제로 쓰는 GraphQL 백엔드(`POST /api/graphql/`)를 직접 부르고, 로그인은 이미 로그인된 **Aside 브라우저** 세션을 `aside repl`의 `fetch`로 빌린다.

이전 시도 `.tmp/Agentic Facebook`(PyPI `agentic-facebook` v0.6.0, 5,853줄)은 기술적으로 동작했지만 무거웠다. 코드의 약 40%(session·scroll·tokens·chrome·profiles·login/status/setup/doctor)가 "로그인된 브라우저가 없다"는 전제 때문에 존재했고, 그 층이 scrapling(Playwright 고정 핀)을 끌고 왔으며, 스킬 본문의 3분의 1이 설치·버전 확인 의식이 됐다. 또 출력이 3건에 1MB짜리 JSON 파일이라 스킬이 "파일을 Read하라"를 가장 큰 함정으로 가르쳐야 했다. Aside 위에 올리면 그 40%가 사라지고, 검증된 파서(`parse.py`·`model.py`·`comments.py`·`search.py`·`about.py`)와 쿼리 레지스트리(`queries.py`)만 남는다.

하네스 프레임 네 가지를 코드에 닿게 적용한다. **principle over rail**: SKILL.md는 규칙 나열이 아니라 도메인 사실과 그 결과를 쓴다. **interface over document**: 명령·플래그·종료 코드·복구 명령은 `--help`와 출력 자체가 가르치고 SKILL.md는 "언제·왜·무엇이 물었나"만 쓴다. **for user not developer**: 읽는 이는 사용 시점의 클로드다. 기본 출력은 클로드가 읽을 밀도 높은 텍스트이고, 전체 JSON은 요청할 때만 나온다. **dense information**: 한 게시물은 3~4줄이며, 다음 홉의 핸들(URL)을 항상 싣는다.

## 확정된 결정 (성진, 2026-09-05)

이 레포는 앞으로 `reddit`·`twitter`·`naver-blog` 스킬도 `.claude/skills/` 아래에 담는다(성진, 2026-09-05). 그래서 **스킬은 각자 완결적**이다: 스킬 간 공유 모듈을 만들지 않고(나중의 `twitter`가 같은 aside 브리지를 써도 복사한다), SKILL.md는 다른 스킬을 이름으로 언급하지 않으며, 테스트·픽스처 도구는 `tests/<skill>/` 아래에 스킬별로 둔다. `harness-spec.md`는 레포에 하나이고 스킬마다 인벤토리 행이 는다. 형제 스킬이 생기는 패스마다 description을 서로 대조한다.

| # | 결정 | 결과 |
|---|---|---|
| D1 | **실계정(Aside `u0`) 사용** | 요청 간 최소 간격·페이지 상한·요청 예산을 코드에 고정(플래그로 못 낮춤). 체크포인트·429 뒤에는 계정 단위 차단 상태. 팬아웃은 스킬 원리로 다룬다. 친구 관계에 묶인 정보가 보이는 이점. |
| D2 | **읽기 전용** | 좋아요·댓글·게시는 스펙에 `declined`. 반응한 사람 목록도 v1 제외(`declined`, 친구 아닌 사람은 숫자만 보임). |
| D3 | **기본 출력은 읽기용 밀도 텍스트** | `--json`으로 전체 객체, `--chars N`으로 본문 길이. `post`는 전문과 첫 댓글 배치를 함께 낸다. |
| D4 | **대규모 수집은 같은 명령에 `--out FILE`** | `profile`/`feed`/`group`이 `--since --until --limit --out`을 받아 NDJSON을 페이지 단위로 커밋하고 이어받는다. 별도 `crawl`/`collect` 없음. |
| D5 | **본문·`--help`·주석은 영어**, 트리거에 한국어 표현 포함 | 하네스 스펙·커밋·PR은 한국어(성진 규칙). |
| D6 | 스킬 디렉터리는 `facebook`(소문자) | 디렉터리 이름이 곧 `/facebook` 명령. 현재 빈 `.claude/skills/Facebook`은 추적되지 않으므로 삭제 후 생성. |
| D7 | 배포는 레포 `.claude/skills/facebook`이 원본, `~/.claude/skills/facebook` 심볼릭 링크 | codex·harness-creator·interview와 같은 관례. 플러그인 패키징 없음. |

## 실측 사실 장부

아래는 이 세션에서 `aside repl`로 직접 확인한 것이다. 구현 세션은 재실측 없이 이 값으로 시작한다. 단, F4·F5의 doc_id는 스냅샷이며 `refresh`가 갱신 수단이다.

- **F1** Aside 계정 `u0`(구글 로그인)의 브라우저가 페이스북에 로그인돼 있다. 샌드박스 `fetch`는 그 쿠키를 싣는다.
- **F2** 페이스북은 내비게이션형 헤더가 없으면 홈 GET에 400을 준다. 필요한 세트: `user-agent`, `accept: text/html,…`, `accept-language`, `sec-fetch-dest: document`, `sec-fetch-mode: navigate`, `sec-fetch-site: none`, `upgrade-insecure-requests: 1`. `sec-fetch-*`만 보내면 200에 빈 본문. GraphQL POST는 `user-agent`, `accept: */*`, `sec-fetch-site: same-origin`, `sec-fetch-mode: cors`, `sec-fetch-dest: empty`, `origin`, `referer`, `x-fb-friendly-name`, `x-fb-lsd`, `content-type: application/x-www-form-urlencoded`가 없으면 오류 1357054("요청이 처리되지 않았습니다").
- **F3** 세션 토큰은 홈 HTML에서 정규식으로 뽑는다: `"USER_ID":"(\d+)"`, `"DTSGInitialData",\[\],\{"token":"([^"]+)"`, `"LSD",\[\],\{"token":"([^"]+)"`, `"__spin_r":(\d+)`. `jazoest`는 `"2" + sum(ord(c) for c in fb_dtsg)`. 폼 필드: `av, __user, __a=1, __comet_req=15, fb_dtsg, jazoest, lsd, __spin_r, __rev, server_timestamps=true, fb_api_caller_class=RelayModern, fb_api_req_friendly_name, variables(JSON), doc_id`.
- **F4** **2026-07-20/26 스냅샷 doc_id 9종 전부가 오늘 데이터를 돌려준다** (newsfeed, timeline, about, search, group, post dialog, comments root, comments page, replies). 단, `queries.py`의 45개 `__relay_internal__pv__*` 플래그 유니언이 이제 **필수**다. 빼면 `missing_required_variable_value` CRITICAL 오류에 data 없음(7월엔 경고만).
- **F5** 현재 클라이언트가 쓰는 doc_id는 9종 모두 7월과 다르다(예: newsfeed `27790894430578947` → `28716439607948928`). 즉 회전은 일어나지만 **옛 id는 서버에서 최소 6.5주 이상 유효**하다.
- **F6** 번들 채굴로 탭 없이 doc_id를 복구할 수 있다. 라우트 HTML의 `https://static.xx.fbcdn.net/rsrc.php/…js` 목록을 `fetch`하고 `__d("<QueryName>_facebookRelayOperation",[],(function(t,n,r,o,a,i){a.exports="<doc_id>"}),null)`를 찾는다. 라우트별로 발견: `/`→newsfeed·post dialog, `/zuck`→timeline, `/zuck/about`→about, `/search/top/?q=…`→search, `/groups/<id>/`→group. 7라우트·94스크립트·약 80MB, 약 20초. **댓글 3종(root·page·replies)은 지연 로딩이라 번들에 없다.**
- **F7** Aside의 `page`는 축소된 Playwright다. `route`·`addInitScript`·`on('request')`·`context()`가 없다. 로드 후 `page.evaluate`로 `window.fetch`/`XMLHttpRequest.prototype.send`를 감싸고 스크롤하면 클라이언트의 GraphQL 요청(이름·doc_id·variables)을 캡처할 수 있다(피드에서 3건 캡처). 댓글 3종의 `refresh`는 이 경로인데, **스크롤만으로 댓글 쿼리가 발생한다는 증거는 없다**(댓글 열기·더 보기·답글 펼치기 동작이 필요).
- **F8** REPL 제약: 하드 타임아웃 120초. `console.log` 한 줄 12MB가 stdout으로 온전히 온다. `pwd`는 `~/.aside/u/0/sessions/<id>`이고 그 아래와 프로젝트 루트 아래만 쓸 수 있다(`/tmp` 거부). 코드 문자열이 비면 대화형 REPL로 빠져 무한 대기한다. 소스에 `require`라는 토큰이 있으면 정적 검사가 거부한다(`page.evaluate` 안이라도). `URL`·`URLSearchParams`는 샌드박스에 없다(폼 인코딩은 `encodeURIComponent`로 직접).
- **F9** 크기·지연: 피드 3건 1.0MB/1.8s, 타임라인 3건 1.3~2.1MB/1.4~1.9s, 검색 3건 0.3~0.66MB/1.5s, About 245KB/0.6s, 댓글 루트 527KB/1.0~1.7s(20노드), 댓글 페이지 506KB/0.9s, 답글 514KB/1.9s, 그룹 3건 886KB/1.8s.
- **F10** 타임라인 페이지 크기는 **3건 고정**(`count` 10·25도 3건). 커서 페이지네이션은 동작하고, `afterTime`/`beforeTime`(unix초)은 서버에서 적용된다(6~7월 창 → 그 기간 글만). **서버 날짜 필터가 입증된 표면은 타임라인뿐이다.** 1,000건 ≈ 330회 요청 ≈ 9분(1.5초 간격) ≈ 500MB 전송.
- **F11** 옛 파서는 Aside로 받은 응답을 수정 없이 파싱한다. 피드 3/3, 타임라인 3/3, 댓글 10/10 정상(작성자·시간·본문·반응/댓글 수·`page_info`). 미디어·링크·공유 게시물 경로와 path 기반 deferred 패치는 이 실측으로 검증되지 않았다.
- **F12** 피드 페이로드에 스폰서 마커가 있다: `sponsored_data` 23회, `is_sponsored` 2회, `ad_id` 5회(광고 1건 포함 3건 기준). 옛 파서는 이를 무시해 광고가 날짜 `None`·반응 0인 `link` 게시물로 나온다.
- **F13** 댓글 루트 응답은 `end_cursor`, 각 댓글의 `expansion_token`, 댓글 자체의 `feedback.id`를 싣는다. 답글은 댓글의 feedback id + expansion_token으로 1회 요청/댓글.
- **F14** 검색 `--type groups` 응답에서 `"__typename":"Group"` 노드에 그룹 숫자 id가 있고, 그 id로 그룹 피드 쿼리가 동작한다(`1084901568224581`로 3건).
- **F15** `ultra-search`가 `aside repl`을 다루는 방식(스니펫을 `.js` 파일로 두고 `const ARGS = …` 접두, NDJSON stdout 회수, 120초 kill의 "daemon is not reachable" 오해 번역)은 그대로 가져올 수 있다. 위치: `~/Coding/Ultra-Search/.claude/skills/ultra-search/scripts/_repl.py`. 단, 그 `_repl.py:81`은 실패 시 stdout/stderr 앞 400자를 오류에 싣는다. 여기서는 토큰이 ARGS로 오가므로 그대로 복사하면 진단으로 샌다.
- **F16** 환경: `python3` 3.12.8, `pytest` 8.4.2(0개 수집 시 exit 5), `node` v22(시스템)·v26(`~/.aside/runtime/bin`). 레포 `.gitignore`가 `.claude/` 전체를 무시한다(`git check-ignore`로 확인) — 스킬이 커밋되지 않으므로 P0에서 고친다.

## 설계

### 실행 모델

```
facebook.py <cmd> ──▶ Python(stdlib) ──spawn──▶ aside repl <js> ──▶ Aside 브라우저 fetch ──▶ facebook.com
      ▲                                                  │
      └── NDJSON(stdout) ◀────────────────────────────────┘
```

- Python이 페이지네이션·페이싱·요청 예산·파싱·렌더링을 전부 맡는다. JS 스니펫은 "토큰 뽑기", "GraphQL POST **한 번**", "HTML GET 한 번"만 한다(`graphql.js`는 요청 하나만 받는다. 페이싱은 Python이 소유하므로 JS에 `gapMs`를 두지 않는다).
- **한 `aside repl` 호출 = 한 요청.** 프로세스 오버헤드는 실측 수백 ms로 요청 지연(1~2s)보다 작고, 120초 한계와 무관해지며, 페이싱을 Python `time.sleep`이 확실히 잡는다. 성진: 요청당 프로세스 스폰이 대량 수집에서 병목으로 측정되면 한 호출에 N페이지(≤ 60초)로 묶는다.
- **JS는 항상 `{status, url(최종), body}`를 돌려준다.** 판정은 Python 한 곳(`_transport.classify`)에서 이 순서로 한다: 체크포인트(`"checkpoint_url"`/`"challenge_url"` 키, 또는 최종 URL이 `/checkpoint/`) → 로그인 필요(홈에 `USER_ID` 없음·`"0"`, GraphQL `"error":1357001`·`caa_login_form_data`) → 요청 제한(HTTP 429, 오류 1357004/1357054 반복) → HTTP/GraphQL 실패(비200, JSON 청크 0개, `errors` 있고 `data` 없음, 어느 청크든 CRITICAL) → 기대 구조(요청한 connection 키가 응답 어딘가에 있는가). 기대 구조가 없으면 "정직한 0건"이 아니라 실패다. 0건(exit 7)은 connection이 명시적으로 비었을 때만, 소진은 `has_next_page:false`가 명시됐을 때만이다.
- **세션 토큰은 CLI 호출마다 새로 뽑고 디스크에 저장하지 않는다.** 홈 GET 한 번(2MB, 0.3~0.5s)이 비용의 전부이고, `fb_dtsg`는 세션 안에서도 회전하므로 신선한 쪽이 안전하다. 크리덴셜 파일이 없다는 것이 보안상 가장 단순한 상태다.
- **차단 상태.** 체크포인트나 요청 제한을 한 번이라도 보면 `~/.cache/facebook-skill/blocked.json`에 사유·시각·만료(체크포인트는 만료 없음, 429는 30분)를 쓰고, 이후 **모든** 명령(`refresh` 포함)이 요청 없이 exit 5로 거절한다. 사람이 브라우저에서 확인한 뒤 `doctor --unblock`으로만 푼다. 요청 간격과 페이지 상한은 "천천히"를 보장할 뿐 "멈춤"을 보장하지 못하고, 다음 CLI 호출은 이전 호출이 뭘 봤는지 모른다는 것이 이 파일이 존재하는 이유다.
- **레지스트리는 데이터다.** `scripts/registry.json`에 doc_id 9종과 relay 플래그 45개, 캡처 날짜를 싣고(코드가 아니라 JSON), `refresh`는 `~/.cache/facebook-skill/registry.json`에 **쿼리별 병합**으로 오버라이드를 쓴다(임시 파일 후 `os.replace`). 로드 순서: 오버라이드 → 번들. 오버라이드에는 크리덴셜이 없으므로 저장해도 된다.
- **페이싱과 예산은 코드에.** 요청 간 1.0~2.0초 지터, 플래그로 낮출 수 없다(올리기만 가능). id 해석용 HTML GET도 같은 간격을 거친다. 한 CLI 호출의 요청 예산은 페이지·댓글 페이지·답글 확장·About 컬렉션·id 해석을 **하나로 합산**하며 기본 25회, `--limit`/`--since`/`--out`이 있으면 목표까지, 절대 상한 400회/호출. `# 성진: 400회 상한은 실계정 보호용, 일회용 계정으로 바꾸면 올려도 됨` 주석을 남긴다.

### 명령 표면 (`facebook.py --help`가 진실, 여기는 설계 의도)

사람이 페이스북에서 하는 동작을 그대로 동사로 만든다. 모든 읽기 명령은 같은 출력 옵션(`--json`, `--chars`, `--out`, `--limit`, `--after`)을 공유한다.

| 명령 | 사람의 동작 | 핸들 | 쿼리 |
|---|---|---|---|
| `feed [--sort top\|recent]` | 홈 피드 훑기 | 없음 | `CometNewsFeedPaginationQuery` |
| `profile <who> [--since --until --sort]` | 누군가의 담벼락 보기 | URL·vanity·숫자 id | `ProfileCometTimelineFeedRefetchQuery` (`afterTime`/`beforeTime` 서버 필터) |
| `about <who> [--section …]` | 소개 탭 읽기 | 같음 | `ProfileCometAboutAppSectionQuery` (개요 1회 + 컬렉션별 1회) |
| `post <url>` | 글 하나 열기 | 게시물 URL | `CometSinglePostDialogContentQuery` → 전문 + 첫 댓글 배치 |
| `comments <url> [--sort top\|recent] [--replies]` | 댓글 더 읽기 | 게시물 URL | `CommentListComponentsRootQuery` → `CommentsListComponentsPaginationQuery` → `Depth1CommentsListPaginationQuery` |
| `search <text> --type top\|posts\|people\|pages\|groups` | 검색 | 자유 텍스트 | `SearchCometResultsPaginatedResultsQuery` (`args.experience.type`) |
| `group <id-or-url> [--sort top\|recent\|activity]` | 그룹 들어가 보기 | 그룹 id·URL | `GroupsCometFeedRegularStoriesPaginationQuery` |
| `doctor [--unblock]` | 준비됐나 | — | aside 바이너리·계정·로그인·차단 상태·레지스트리 나이 한 줄, 실패 시 비영 종료 |
| `refresh [--capture --post URL]` | 깨졌을 때 고치기 | — | 번들 채굴(6종) + `--capture`로 탭 내 캡처(댓글 3종) |
| `schema` | 객체 필드 설명 | — | Post·Comment·Entity·ProfileField를 `to_dict()`에서 유도 |

**`--after <n>` 이어읽기.** 모든 페이지네이션 명령(feed·profile·group·comments·search)에 있다. 번호 `n`은 `~/.cache/facebook-skill/cursors/<n>.json`을 가리키고, 그 파일에는 커서뿐 아니라 **원래 조회 문맥 전체**(명령·대상·정렬·창·계정 id·시각)가 들어 있다. `--after`와 함께 문맥과 충돌하는 인자를 주면 거절한다. 번호는 단조 증가하고 재사용하지 않는다. 출력 끝줄은 실행 가능한 전체 명령이다: `more: python3 "/…/facebook.py" comments "https://…" --sort recent --after 17`. 커서 문자열은 수백 자라 클로드가 옮겨 적으면 틀린다는 것이 번호를 쓰는 이유다. `post`가 보여준 첫 댓글 배치와 `comments`의 커서가 호환되는지는 P3에서 실측하고, 호환되지 않으면 `comments`는 "처음부터 읽는다"고 출력에 명시한다.

**댓글 확장 순서.** 부모 댓글을 id로 중복 제거하고 `--limit`을 적용한 **뒤에** 남은 부모만 `--replies`로 확장한다(옛 `retrieve.py`는 받은 20노드를 전부 확장한 뒤 limit을 적용했다). 일부 답글·About 컬렉션이 실패하면 삼키지 않고 결과에 `replies_incomplete`/`failed_sections`로 남긴다.

**날짜 창의 의미.** `profile`은 서버 필터(`afterTime`/`beforeTime`)이고 창의 완전성을 보장한다. `feed`·`group`은 서버 필터가 없으므로 **클라이언트 필터**이며, 랭킹 정렬에서는 오래된 글 하나를 만났다고 탐색을 끝내지 않고 요청 예산까지 간다. 그래서 창을 쓰는 질문은 `--sort recent`와 짝이다. 요청한 정렬 순서를 보존한다(옛 `_apply_window`의 재정렬 삭제). 경계와 출력은 **같은 시간대**(로컬)를 쓰고 내부에서 UTC 초로 바꾼다. 고정글·날짜 없는 글은 창과 무관하게 남기되 `pinned`/`undated`로 표시한다.

### 출력 계약

**기본(텍스트).** 데이터와 명령을 구분하고, 본문은 한 줄로(개행은 `⏎`로 치환), URL은 따옴표로 감싼다. 헤더 한 줄에 표면·정렬·건수·중단 사유, 끝줄에 `more:`. 시간은 로컬 시간대에 오프셋 포함 ISO.

```
feed · sort=top · 3 shown · stopped=limit
[p1] 윤지호 · 2026-09-03T21:07+09:00 · photo · reactions=516 comments=28 shares=3
     text[180/412 chars, complete]: "예전부터 쓰고 싶었던 스타일의 글, 다른 지면의 기고를 멈추고 글쓰기를…"
     url: "https://www.facebook.com/jiho.yoon.7547/posts/pfbid0…"   author: "https://www.facebook.com/jiho.yoon.7547"
[p2] Brainy One · sponsored · link · reactions=0 comments=0 shares=?
     text[180/388 chars, complete]: "AI 쓸수록 머리가 나빠지는 것 같으신가요? 2025년 MIT 연구…"
     url: "https://www.facebook.com/permalink.php?story_fbid=…"   author: unavailable
[p3] 김철수 · 2026-09-04T21:30+09:00 · shared · reactions=124 comments=1 shares=0
     text[42/42 chars, complete]: "이 글 꼭 읽어보세요"
     shared-from: 홍길동 · 2026-09-01T10:00+09:00 · url: "https://…" · text[120/900 chars, truncated]: "…"
     url: "…"   author: "…"
more: python3 "/…/facebook.py" feed --sort top --after 12
open a post: `post <url>` · read a person: `profile <url>` / `about <url>`
```

- `text[shown/received chars, complete|truncated]`: `received`는 서버가 보낸 길이이고, `truncated`는 서버가 잘랐다는 뜻이다(옛 `text_truncated`). 잘린 글은 `post <url>`이 전문을 가져오며, 그래도 잘려 있으면 `truncated`가 남고 다시 조회하지 않는다.
- 댓글은 `[c1]`, 답글은 `[c2 reply-to=c1]`로 들여쓰기. 엔티티는 `[e1] group id=1084901568224581 · name · verified · url: "…"`. About은 `section: text (url)`.
- nullable 수치는 `?`, 없는 핸들은 `unavailable`(막다른 길이지 오류가 아니다).
- **`--json`**: 항상 **JSON 문서 하나**. 성공은 `{"ok":true,"results":[…],"stop_reason":…,"next":…}`, 실패·부분은 `{"ok":false,"error":…,"message":…,"fix":…,"results":[…],"stop_reason":…}`. 옛 객체 스키마를 유지하되 `sponsored: bool`·`pinned`·`undated` 추가, `source` 유지, 시각은 ISO UTC. argparse 오류도 같은 객체로 변환한다(`parse_args`를 `try` 안에).
- **`stop_reason`**은 `limit_reached | exhausted | window_reached | budget | query_failure | blocked` 중 하나다. `exhausted`로 끝난 소량 결과를 재시도할 실패처럼 안내하지 않는다.
- **`--out FILE`**: NDJSON. 첫 줄은 `{"kind":"header", command, target, sort, window, account_id, started_at}`이고, 다른 문맥으로 같은 파일을 열면 거절한다. **페이지가 커밋 단위**다: 그 페이지의 레코드 줄들 뒤에 `{"kind":"page", cursor, ids:[…], n}`를 쓰고 flush한다. 이어받기는 마지막 완전한 `page` 줄까지만 신뢰하고, 그 뒤의 불완전한 꼬리를 잘라낸 뒤 `page.cursor`에서 재개하며, 이미 쓴 id로 중복을 제거한다. `--limit`은 `--out`에서 페이지 단위로 적용된다(최대 2건 초과 가능, 헤더에 명시). 화면에는 요약 한 줄. 옛 "`--output`을 무조건 비우기"는 이식하지 않되, 그 보장(이전 결과를 이번 결과로 오인하지 않는다)은 헤더 대조가 대신한다.
- **오류는 JSON 한 줄을 stdout에**(`ok:false, error, message, fix`). ultra-search와 같은 규약. `message`에 REPL의 원시 stdout/stderr·소스·ARGS를 넣지 않는다. 진단이 필요할 때만 옛 `redact.py`의 scrub(토큰 키·쿠키·서명 URL)을 거친 뒤 `--verbose`로 낸다.
- **종료 코드**: 0 성공 · 2 잘못된 인자 · 3 aside 불가 · 4 페이스북 로그인 필요 · 5 차단(체크포인트·요청 제한, **중단·재시도 금지**) · 6 쿼리 실패(doc_id/필수 변수 → `refresh`) · 7 정직한 0건 · 8 부분 결과(예산·창 미달). 각 코드의 복구 문구는 오류 JSON의 `fix`에 실린다.

### 디렉터리 구조

책임 하나·400줄 이하·엔트리는 argparse와 디스패치만(ultra-search 규칙). 옛 코드에서 옮기는 모듈은 **transport 의존을 제거**한 뒤 가져온다. 파서 모듈에는 숨은 transport/session import가 없음을 codex가 확인했다(공용 스키마 유틸 의존만 있어 `_schema.py`로 뺀다).

```
Agentic SNS/
├── .claude/
│   ├── harness-spec.md                     # 하네스의 단일 출처 (audit_harness.py가 읽음)
│   ├── plans/…                             # 이 파일
│   └── skills/facebook/
│       ├── SKILL.md                        # 언제·왜·무엇이 물었나. 명령 표는 없음
│       └── scripts/
│           ├── facebook.py                 # argparse 배선·디스패치·종료 코드. 이 파일이 인터페이스
│           ├── registry.json               # doc_id 9종 + relay 플래그 45개 + 캡처 날짜 (데이터)
│           ├── _errors.py                  # 오류 클래스=종료 코드=JSON 한 줄. fix 문구. 진단 scrub
│           ├── _aside.py                   # aside 바이너리 찾기, repl 스폰, 빈 코드 거부, 120s 번역, NDJSON 회수
│           ├── _session.py                 # 홈 GET → 토큰 5종 추출, jazoest
│           ├── _transport.py               # 폼 본문·헤더 조립, 페이싱 하한, 요청 예산, classify(체크포인트→로그인→제한→실패→구조), 청크 분할
│           ├── _blocked.py                 # 차단 상태 파일 읽기·쓰기·만료
│           ├── _registry.py                # registry.json 로드(오버라이드→번들), QuerySpec, build_variables
│           ├── _refresh.py                 # 번들 채굴(정규식) + 캡처 병합 + 재생 검증 → 쿼리별 원자적 저장
│           ├── _paginate.py                # 커서 루프, page_info 탐색(인라인/deferred), limit·창·예산, stop_reason
│           ├── _resolve.py                 # who/url → 숫자 id·storyID·feedback id (HTML 정규식), URL 정규화·검증
│           ├── _schema.py                  # _iso, build_schema_fields, build_json_schema (모든 모델이 공유)
│           ├── _parse.py                   # bytes → 병합된 story dict (옛 parse.py 이식)
│           ├── _post.py                    # Post·Media·Link + build_post + sponsored/pinned/undated (옛 model.py 이식)
│           ├── _comment.py                 # Comment + build_comments + 부모 중복 제거·정렬 (옛 comments.py 이식)
│           ├── _entity.py                  # Entity + 결과 노드에서만 추출, 명시적 Page는 page (옛 search.py 수정 이식)
│           ├── _about.py                   # ProfileField + 컬렉션 **발견·파싱**만 (옛 about.py 이식)
│           ├── _render.py                  # 객체 → 밀도 텍스트. 레이블·시간대·chars·한 줄 규칙은 여기만
│           ├── _output.py                  # --json 문서, --out 헤더·페이지 커밋·이어받기, 커서 핸들 저장
│           ├── _cmds_posts.py              # feed/profile/group/post 핸들러 (게시물 조회)
│           ├── _cmds_people.py             # comments/search/about 핸들러 (사람·엔티티 조회, About 컬렉션 요청)
│           ├── _cmds_maint.py              # doctor/refresh/schema
│           └── browser/
│               ├── tokens.js               # ARGS 없음. 홈 GET → {status,url,body}
│               ├── graphql.js              # ARGS: {tokens, name, doc_id, variables, referer} → 요청 **하나**의 {status,url,body}
│               ├── page.js                 # ARGS: {url} → {status,url,body} (id 해석용)
│               ├── mine.js                 # ARGS: {routes, names} → 발견한 doc_id JSON
│               └── capture.js              # ARGS: {url, targets, actions} → 탭 열고 fetch/XHR 감싸고 댓글 열기·더 보기·답글 펼치기 수행, 캡처 반환, 탭 닫기
├── tests/
│   └── facebook/                           # 스킬별 디렉터리. 나중에 reddit/·twitter/·naver-blog/가 형제로 온다
│       ├── conftest.py                     # FACEBOOK_ASIDE_BIN → fake_aside/aside, FACEBOOK_HOME → tmp, live 마커
│       ├── fake_aside/aside                # 스니펫 이름별 캔드 {status,url,body}를 돌려주는 가짜 바이너리 (프로세스·출력 계약 검사용)
│       ├── js/                             # 실제 browser/*.js를 node에서 mock fetch/page로 실행해 URL·헤더·폼 인코딩을 검사
│       ├── fixtures/                       # 실캡처에서 **구조만** 유도한 합성 NDJSON (PII 없음)
│       ├── tools/derive_fixture.py         # 실캡처 → 합성 픽스처 (키·중첩·타입 보존, 값 합성)
│       ├── tools/check_fixtures_pii.py     # 옛 스크립트 이식. CI 게이트
│       ├── test_cli.py · test_transport.py · test_blocked.py · test_paginate.py · test_parse.py · test_post.py · test_comment.py · test_entity.py · test_about.py · test_render.py · test_output.py · test_registry.py · test_refresh.py · test_resolve.py
│       └── live/test_live.py               # -m live. 실제 Aside 필요. 모양·불변식만 단언
├── README.md (스킬 목록 색인) · .gitignore · pyproject.toml (pytest·ruff 설정만, 의존성 없음; testpaths=tests)
```

`.gitignore`는 지금 `.claude/` 전체를 무시하고 있어 스킬이 커밋되지 않는다. Ultra-Search처럼 `.claude/histories`만 무시하도록 바꾸고, `.tmp/`, `*.ndjson`(tests/fixtures 제외), `.codex-runs/`, `__pycache__/`를 넣는다. 수집 결과·캡처는 절대 커밋하지 않는다.

### SKILL.md의 내용 (본문에 들어갈 것과 들어가지 않을 것)

들어가는 것(모두 "사실 + 결과" 형태):
- 라우팅: 이 스킬은 **facebook.com에 있는 것**을 읽을 때 쓴다. description이 facebook.com URL과 페이스북 문맥("페이스북에서", "내 피드", "이 페북 글 댓글", "페북에서 누가 올렸어")을 명시적으로 가져가고, 다른 소셜 네트워크·일반 웹·페이스북 회사 뉴스는 **이름 없이** 근접 오발로 배제한다. 본문과 description 어디에도 다른 스킬(ultra-search 등)을 언급하지 않는다. 다만 구현 세션에서 저는 사용자 스코프에 있는 ultra-search의 description("read this URL"을 포괄)과 나란히 읽어 facebook.com URL이 이 스킬로 오도록 문구를 다듬는다. 그것은 검토 작업이지 스킬 내용이 아니다.
- `$FB`는 `python3 "<base directory>/scripts/facebook.py"`를 한 줄로 쓴다. 변수 경로·줄바꿈은 사전 승인 패턴에 안 맞는다(ultra-search와 같은 이유).
- **비용의 실체**: 요청 하나가 실계정의 요청이고 간격 하한·예산이 있다. 페이지당 3건이라 100건은 34회다. "몇 명을 볼지 먼저 정하고 시작"이 팬아웃 원리이고, 그 이유는 체크포인트가 실계정에 온다는 것. 차단 상태는 사람이 풀어야 한다.
- **랭킹과 시간순은 다른 질문의 답**이다. 창을 쓰는 질문은 `recent`와 짝이고, 완전성은 프로필에서만 보장된다.
- 핸들이 이어지는 방식: 출력의 `url`/`author`가 다음 명령의 인자다. `about`은 낯선 사람을 만났을 때, `post`는 전문과 댓글 첫 배치를 함께 주므로 `comments`는 더 필요할 때만. `more:` 줄은 그대로 실행한다.
- 무엇이 물었나: 스폰서 게시물은 날짜가 없다. `unavailable` 핸들은 막다른 길이다. `truncated`면 인용 전에 `post`. 0건과 낡음은 같아 보이고 도구가 구분해서 말해 주니 `stop_reason`을 읽는다. 검색의 같은 이름은 `about`으로 확인한 뒤 고른다.
- `--out`의 의미: 클로드가 읽지 않을 만큼 클 때만. 그 파일은 남의 개인정보이므로 레포 밖·작업 끝나면 삭제.

들어가지 않는 것: 명령·플래그 표(`--help`), 종료 코드 표와 복구 명령(오류 JSON의 `fix`), 스키마(`schema`), 설치 절차(없음), 버전 확인(없음).

## 구현 단계와 완료 판정

각 단계는 `tdd` 스킬로 시작한다(seam 합의 → 실패 테스트 → 통과). 단계마다 `codex`로 diff 리뷰를 받고 P1 지적은 그 단계 안에서 고친다. 트래커(`TaskCreate`)에 아래 판정 기준을 그대로 적는다. 라이브 확인은 항상 `--limit 3`부터.

| 단계 | 내용 | 완료 판정 |
|---|---|---|
| P0 | 스캐폴드: `.claude/skills/Facebook` 삭제 → `facebook/` 생성, `.gitignore` 수정, `tests/`, `pyproject.toml`, `harness-spec.md` 초안(인벤토리 `approved`), 심볼릭 링크 | `audit_harness.py --path .`가 skill 1개·드리프트 0. `git check-ignore .claude/skills/facebook/SKILL.md`가 아무것도 출력하지 않음. `pytest`는 0개 수집 exit 5(정상) |
| P1 | `_aside`·`_session`·`_transport`·`_blocked`·`_registry`·`_errors` + `tokens.js`·`graphql.js` + `doctor` | fake aside로 단위 테스트, node로 JS 스니펫 테스트(헤더 세트·폼 인코딩에 `&`·`+`·한글) 통과. classify 픽스처: 체크포인트→5, 로그아웃→4, 429→5+차단 파일, `errors`만→6, JSON 0개→6, connection 없음→6, 빈 connection→7. 라이브: `doctor` exit 0 |
| P2 | `_schema`·`_parse`·`_post`·`_paginate`·`_render`·`_resolve`·`_output(--json)` + `feed`·`profile` | 합성 픽스처로 build_post·render 골든. 라이브: `feed --limit 3` 텍스트, `profile zuck --limit 6` 2페이지·`more:` 실행 가능, `--json` 단일 문서, 스폰서 표시, photo·link·shared 게시물 각 1건 확인 후 픽스처 추가 |
| P3 | `_comment`·`_entity`·`_about` + `post`·`comments`·`search`·`group`·`about` | 픽스처 테스트(limit 후 확장, 부모 중복 제거, Page→page). 라이브: `post <zuck 글>` 전문+댓글, `comments --replies --limit 5`가 답글 들여쓰기·요청 수 ≤ 1+5, `search seoul --type groups` → 첫 id로 `group` 3건, `about zuck` 섹션 ≥3, `post`→`comments` 커서 호환 여부 기록 |
| P4 | `_output(--out)`: 헤더·페이지 커밋·이어받기, `--since/--until`, `--after` 문맥 | 단위: 페이지 중간 중단 후 재실행이 누락·중복 없음, 다른 문맥 파일 거절, 창 테스트는 포함·제외 대상을 모두 단언. 라이브: `profile zuck --since 2026-06-01 --until 2026-07-15 --out /tmp/z.ndjson` 창 안 글만, 재실행 "already complete" |
| P5 | `_refresh` + `mine.js`·`capture.js` | 단위: 번들 텍스트 픽스처에서 정규식이 6종 추출, 쿼리별 병합·원자적 저장. 라이브: `refresh`가 6종 갱신 보고, `refresh --capture --post <url>`이 댓글 3종을 캡처하고 **재생 검증**한 것만 저장, 못 한 이름을 정직하게 출력 |
| P6 | `SKILL.md`, `harness-spec.md` 완성, `validate_harness.py` exit 0, README 색인, 사용자 스코프 스킬들과 description 겹침 검토(스킬 안에는 언급 없음) | 검증 절 참조 |

## 재사용 지도 (옛 코드 → 새 모듈)

| 옛 파일 (`.tmp/Agentic Facebook/src/agentic_facebook/`) | 새 모듈 | 변경 |
|---|---|---|
| `parse.py` (333줄) | `_parse.py` | 그대로. path 기반 deferred 패치 미지원은 `incomplete` 표시로 드러낸다(P2 라이브에서 발생 여부 확인) |
| `model.py` (429줄) | `_post.py` + `_schema.py` | 스키마 유틸 분리, `truncation.has_truncation_marker` 인라인, `sponsored`·`pinned`·`undated` 추가 |
| `truncation.py`의 `resolve_truncated_text` | `_cmds_posts.py` | `post`가 전문을 가져오는 경로. 주입형이라 그대로 |
| `comments.py` (250줄) | `_comment.py` | 부모 id 중복 제거 추가 |
| `search.py` (167줄) | `_entity.py` | 결과 노드에서만 추출, 명시적 `Page`는 page |
| `about.py` (193줄) | `_about.py` | 파싱만. 컬렉션 요청 루프는 `_cmds_people.py` |
| `queries.py` (366줄) | `registry.json` + `_registry.py` | 데이터는 JSON으로, `QuerySpec`·`build_variables`만 코드 |
| `graphql.py` 판정 함수·`find_page_info`·`iter_chunks` | `_transport.py`·`_paginate.py` | `FetcherSession` 제거, 판정 순서 재정의(위) |
| `retrieve.py`의 `_resolve_*`·`_fetch_post_story`·댓글 흐름 | `_resolve.py`·`_cmds_*.py` | 프로필 디렉터리·모드 분기 삭제, 창 재정렬 삭제, limit 후 확장 |
| `redact.py`의 scrub | `_errors.py` | 진단 경로에만 |
| `tokens.py`의 정규식·jazoest | `_session.py` | 캐시 파일 삭제 |
| `exits.py`·`catalog.py` | `_errors.py`·`--help`·`schema` | 카탈로그 명령은 만들지 않음(`--help`가 그 역할) |
| `tests/fixtures/*.ndjson`·`test_parse.py`·`test_comments.py`·`test_truncation.py` | `tests/` | 그대로 이식 |
| `scripts/check_fixtures_pii.py` | `scripts/` | 그대로 |
| `session.py`·`scroll.py`·`chrome.py`·`profiles.py`(로그인 부분)·`config.py`·`cli.py` | — | **가져오지 않음** |
| ultra-search `_repl.py`·`_errors.py`·`_exec.aside_bin`·`tests/fake_aside` | `_aside.py`·`_errors.py`·`tests/facebook/fake_aside` | **복사**해서 스킬 안에 둔다(import 없음, 스킬 완결성). 이름·마커 변경, 오류 메시지의 원시 출력 삽입 제거 |

## 검증

- 단위: `pytest tests/` (aside 없이). seam: CLI(fake aside 서브프로세스, 종료 코드·JSON 문서), transport classify, blocked, paginate(중간 페이지 limit·예산), 각 build_*, render 골든, output(중단 각 경계·문맥 불일치·잘린 stdout), registry 로드 순서, refresh 정규식·병합. JS: `tests/js/`에서 node가 실제 스니펫을 mock `fetch`/`page`로 실행해 URL·헤더·폼을 독립 검사(fake aside가 돌려주도록 정한 값을 다시 받는 검사는 transport 검증이 아니다).
- 라이브: `pytest -m live` (Aside 실행 중, 실계정). 모양·불변식만 단언, 실제 게시물 내용은 단언하지 않는다.
- 하네스: `validate_harness.py --path .` exit 0, `audit_harness.py` 드리프트 0.
- codex: 계획 리뷰(완료) → 단계별 diff 리뷰 → 최종 SKILL.md 리뷰. 기준은 **"본문과 `--help`·도구 출력만으로, 소스나 개발 문서 없이 세 시나리오를 수행할 수 있나"**(본문에 명령 정보를 복제하라는 압력이 되지 않게).
- e2e(성진 동의 후, 시나리오당 약 $0.5~2): V1 "내 피드 최근 글 5개 요약" → `feed --sort recent --limit 5` 텍스트를 읽고 파일 Read 없이 답. V2 "이 글 댓글 단 사람들은 평소 뭘 올리나" → `post` → `comments` → 작성자 2~3명만 `profile --limit 3`, 몇 명을 봤는지 보고. V3 "'seoul' 그룹 찾아줘" → `search --type groups` → `group` 2~3개 확인. V4 근접 오발 둘: "이 레포 테스트 돌려", "이 스레드 글 댓글 읽어줘(threads.net)" → 스킬 미호출. V5 "이 사람 글 전부 모아줘" → `--out` 사용, 비용(요청 수) 먼저 말함.

## 위험과 처리

| 위험 | 처리 |
|---|---|
| 실계정 체크포인트·요청 제한 | 코드 하한 1.0s·지터, 요청 예산, exit 5에서 즉시 중단, **차단 파일로 다음 호출도 중단**, 스킬의 팬아웃 원리, 라이브는 `--limit 3`부터 |
| doc_id 회전 | 옛 id 유효기간 실측 ≥6.5주. exit 6 → `refresh`. 댓글 3종은 `--capture --post` |
| 플래그 유니언에 새 필수 플래그 | 증상은 200에 data 없음(exit 6). `refresh --capture`가 캡처한 variables에서 **relay 플래그만** 병합 |
| REPL 120초 | 요청당 1호출이라 무관. `refresh --capture`만 60초 예산 |
| 응답 12MB 초과 | 실측 최대 3.6MB. stdout 12MB 확인. 초과 시 세션 디렉터리에 파일로 쓰고 경로를 돌려주는 `toFile` 경로를 `graphql.js`에 준비 |
| 옛 파서의 미확인 경로(미디어·링크·공유·deferred 패치) | P2 라이브에서 확인, 픽스처 추가, 미지원은 `incomplete` 표시 |
| 수집 파일의 개인정보 | 레포 밖 경로 권장, `.gitignore`, 스킬 본문의 삭제 원리 |
| 진단으로 토큰 유출 | 오류 메시지에 원시 stdout/stderr·ARGS 금지, `--verbose`만 scrub 후 출력 |

## 미룬 것 (스펙에 기록)

- 쓰기 동작·반응한 사람 목록: `declined` (D2).
- 릴스·스토리·알림·메신저: 범위 밖. 다음 패스가 묻는다.
- 요청당 프로세스 스폰 최적화: 대량 수집 병목이 측정될 때.
- 미디어 다운로드: 요청 시. `--json`의 미디어 URL로 충분한지 먼저 본다.

## codex 리뷰 반영 (2026-09-05, run `20260905-104133-plan-review-a36a`)

14건 중 14건 반영. 요지: (1) `--out` 이어받기를 페이지 커밋 단위·헤더 대조·id 중복 제거로, (2) 응답 판정을 체크포인트→로그인→제한→실패→구조 순서로 하고 exit 7은 명시적 빈 connection에만, (3) 429·체크포인트 뒤 계정 단위 차단 파일, (4) 댓글은 limit 뒤 확장·요청 예산 합산, (5) 날짜 창은 프로필만 서버 필터, (6) `--after`에 조회 문맥·전체 실행 명령, (7) 텍스트 형식에 연도·잘림·공유·`?`·`unavailable`·한 줄 본문, (8) `refresh --capture`는 동작 수행·재생 검증·쿼리별 병합, (9) 진단 scrub, (10) 검색 엔티티 추출 수정, (11) `--json` 단일 문서·argparse 오류 변환·`stop_reason`, (12) JS 스니펫 node 테스트, (13) `_schema.py` 분리·`_about` 파싱만·`graphql.js` 단일 요청·명령 모듈 둘로, (14) 최종 리뷰 기준 수정·description 대조·pytest exit 5. 타당하다고 확인된 것: 요청당 REPL 1회, 토큰 무캐시, JSON 레지스트리, 번호 커서, 밀도 텍스트 기본.

## 구현 진행 기록

TaskCreate/ToolSearch가 이 세션에 제공되지 않아 이 계획서에서 위 P0–P6 완료 기준과 상태를 함께 관리한다.

- P0 완료: 스킬 1개·audit 드리프트 0, git check-ignore 출력 없음, pytest 0개 수집(exit 5). 사용자 스코프 facebook 링크 연결. 성진 추가 요청으로 `.codex` → `.claude` 상대 심볼릭 링크 생성.
- P1 완료: transport·계정 차단·JS 요청 계약·라이브 doctor·검토 수정 검증 완료.
- P2–P3 완료: 파서·모든 읽기 명령 연결, 소량 라이브와 검토 수정 검증 완료.
- P4 완료: 페이지 커밋·중단 복구·문맥 검증·실제 날짜 창 수집 및 완료 파일 재실행 검증.
- P5 완료: eager 번들·JSON prefetch 플래그·안전한 캡처·검증 후 원자적 병합. 기본 6종 갱신 성공, 캡처 2종 미관측 제한은 아래에 명시.
- P6 완료: CI·스킬·문서·전체 검사·단계별 검토 수정 완료. Git 반영은 저장소의 PR/스쿼시 흐름으로 진행한다.

- 중간 검증: `_paginate`·`_output` 12개 테스트 통과. 페이지 중간 limit의 남은 항목·마지막 페이지 소진·랭킹 날짜 창·부분 실패·파일 중단 복구·문맥 불일치·번호 커서를 검증했다. P0/P4 독립 codex 검토 시작.
- Graphify 1차 갱신: 코드 전용 AST 44개 파일, 332노드·603간선·21커뮤니티. 사용자 요청에 따라 주요 구현 경계에서 재갱신한다. 그래프는 로컬 산출물로 유지한다.

- P0 추가 점검: histories가 디렉터리 아닌 심볼릭 링크여서 ignore 끝 `/`를 제거했다. 전역 Git ignore가 plans를 숨기므로 이 계획서만 명시적으로 추적 예외를 추가했다(스펙의 참조 대상도 배포에 포함).
- P4 검토 3건: 빈 connection의 has_next_page=true를 소진으로 오인하는 경로는 P1에서 수정 중. 마지막 페이지 limit 완료 상태와 anti-JSON 접두사의 페이지 정보 누락은 회귀 테스트로 수정 완료. 추가로 Page 엔티티의 kind=page가 파일 커밋 마커와 충돌하는 문제를 수정했다.

- P1 라이브 doctor exit 0(홈 1요청). Aside의 await 없는 IIFE 및 ANSI `[ok | …ms]` footer 처리 문제를 실측·회귀 테스트로 수정했다. 9쿼리·45플래그 레거시 일치를 확인했다.
- P2 라이브 feed 3건(광고 1건, shared/link 포함), profile zuck 6건/2페이지(홈·id 해석 포함 4요청), 출력 more 명령 재실행 6건·이전 페이지와 id 중복 0. photo도 확인했다.
- P2/P3 파서 검토 P2 4건(공유글 최상위 순서·중간 식별자 없는 공유·중첩 공유 렌더·링크 썸네일 분류)을 수정, 모델 59테스트·합성 fixture 11개 PII 게이트 통과.
- P3 라이브 post 전문+댓글 10개 성공(4요청). 댓글 목록과 total_count 전용 preview를 혼동하는 응답 판정은 실응답 구조 기반 합성 테스트로 수정했다. comments --replies --limit 5는 부모 5·답글 30, 요청 9회(준비 3+부모 1+답글 5); 더 있는 답글 배치 2개를 replies_incomplete로 정직하게 표시(exit 8).
- 명령 통합 독립 검토 P2 4건(수집 파일 누적 limit·post deferred 정보 보존·실패 답글 재개·혼합 검색 nodes 순서) 수정 중.
- P5 캡처 보호 검토 P1 1건: 캡처를 요청 1회로 계산하지 않고 실제 GraphQL 요청의 예산·직렬 페이싱·첫 차단 뒤 중단을 구현 중. 이 보호가 완성되기 전 라이브 capture는 실행하지 않는다.

- P3 추가 라이브: 댓글 root 커서→comments_page 10건 재생 성공, 앞선 10건과 중복 0(로그인 포함 2요청). 검색의 실제 Group은 edge.node 내부가 아니라 edge.rendering_strategy.view_model.profile에 있음을 확인하고 합성 회귀 테스트로 확장했다. search seoul --type groups 3건 → 첫 id의 group 3건 모두 exit 0.

- P3 about zuck 라이브: 14필드·12섹션, 홈·id 해석·컬렉션 포함 9요청, exit 0.

- Graphify 2차 갱신: 526노드·1,181간선·26커뮤니티.
- P6 검증 구성: fixture PII 검사를 실제 CI 게이트로 연결하고, GitHub Actions에서 오프라인 pytest·실제 JS mock 테스트·ruff를 함께 실행한다. Python의 datetime.UTC 사용에 맞춰 런타임 최소 버전은 3.11로 명시했다(검증 환경은 계획대로 3.12).

- P4 라이브 창 수집: 2026-06-01~2026-07-15 프로필 6건, 날짜 있는 비고정 글 모두 창 안, 4요청 후 exhausted·window_complete=true. 같은 파일 재실행은 이미 완료된 6건을 유지했다.
- 오프라인 전체 중간 검사: 223 passed, 7 deselected. 추가 변경 이후 최종 재검사 예정.
- P5 최초 라이브는 400요청·710초 후 예산 중단. 원인: HTML의 지연 Bootloader 자산 약 700개를 모두 훑음. 실제 eager script src는 중복 제거 시 30개임을 실측, eager만 탐색하고 라우트 목표 쿼리 발견 시 다음 라우트로 이동하도록 수정했다. 이 실패에서는 검증되지 않은 override를 저장하지 않았다.
- 대형 응답 설계 수정: Aside fs.writeFile의 mode 옵션이 무시되고(0644), 세션은 0755이며 현재 cwd도 Aside 쓰기 경계 밖이었다. 파일 전달 대신 512Ki 문자 조각을 stdout으로 보내 Python에서 순서·개수를 검증해 합친다. 실제 Aside에서 합성 9MB를 손실 없이 회수, 개인 응답 파일은 쓰지 않는다. 계획의 toFile 준비를 이 안전한 전달 방식으로 대체했다.

- P5 eager 탐색 수정 후 37요청으로 6종 doc_id를 발견했으나 새 쿼리 재생은 missing_required_variable_value로 실패했다. 현재 브라우저 피드 요청을 캡처해 `StoriesShouldEnablePhotosensitiveContentWarningrelayprovider=false`라는 새 플래그를 실측했고, 이 값만 추가한 새 newsfeed 쿼리 재생이 성공했다(2요청). 기본 relay 유니언을 검증된 46개로 갱신했다.
- P5 복구 캡처는 이제 피드 스크롤로 공통 플래그도 얻고, 게시물에서 댓글 정렬 전환·더 보기·답글을 수행한다. 계정 보호는 초기 탐색 및 가로챈 GraphQL 요청을 개별 계산·직렬 전송하며 자산 요청은 계산 범위 밖이다.
- Aside 탭 동작은 stdout에 상태 줄을 추가하므로 JSON 봉투·조각만 파싱하고 상태 줄은 무시한다. 잘린 JSON과 중복 봉투는 계속 오류로 처리한다. 실제 답글 쿼리 캡처 1종은 성공했으며 root/page는 추가 정렬 동작을 붙여 재검증 중이다.

- P6 최종 스킬 사용성 검토: 본문+도움말+스키마만으로 세 시나리오와 오발 제외·링크 배포 확인. P2 1건(스키마의 옛 fetch 안내)을 profile/about으로 수정하고 schema 출력에서 잔존 0건 확인.
- P5 캡처 포함 실제 실행: 53요청, group/newsfeed/post/replies/search/timeline 새 ID 검증·저장. About은 새 필수 변수 때문에 검증 실패, comments/comments_page는 클라이언트 요청을 관찰하지 못했다고 명시(exit 8). 검증되지 않은 ID는 저장하지 않았다.

- P5 기본 refresh 최종 라이브: eager 번들+각 라우트의 JSON prefetch 플래그를 함께 수집하여 39요청으로 about/group/newsfeed/post/search/timeline 6종 검증·저장, failed 0, exit 0. 댓글 3종은 기본 모드에서 missing으로 명시한다. 추가로 피드·소개 UI를 켜지 않고도 새 필수 플래그를 회복한다.

## 최종 구현 검증

- 오프라인 Python: `python3 -m pytest tests/ -q` → 228 passed, 7 deselected.
- 실제 브라우저: `python3 -m pytest -m live tests/facebook/live/ -q` → 7 passed. 새 레지스트리로 실행했다.
- 실제 JS mock: `node --test tests/facebook/js/*.js` → 30 passed.
- 린트: `uvx ruff check --config pyproject.toml .claude/skills/facebook/scripts tests/facebook` → All checks passed.
- fixture: `python3 tests/facebook/tools/check_fixtures_pii.py` → 13개 통과.
- 하네스: validate 오류 0·경고 0, audit skill 1개·드리프트 0. 사용자 스코프 링크는 같은 소스다.
- 모든 런타임 모듈은 400줄 미만이다. 런타임은 Python 3.11+ 표준 라이브러리와 Aside만 사용한다.
- 최종 새 레지스트리의 댓글 답글: 부모 3개·답글 23개, 더 남은 배치 2개는 부분 결과로 명시. 피드 텍스트는 3건/11줄이다.
- 캡처에서 root/page 새 ID 2종은 이번 실계정 UI에서 관찰하지 못했다. 검증되지 않은 ID를 저장하지 않고 기존 유효 ID와 missing 보고를 유지한다. 새 답글 ID의 캡처·재생 및 기존 root/page의 읽기·커서 호환은 확인했다.
- 추가 모델 e2e는 비용 동의 답변을 받지 않아 실행하지 않았다. 본문+도움말+출력에 대한 독립 검토는 수행했다.
- Graphify 마지막 AST: 558노드·1,315간선. 커뮤니티 자동 명명은 Claude 세션 한도로 실패했으며 기본 이름을 사용한다.
