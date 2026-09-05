# `reddit` 스킬 구현 계획

계획 세션: 2026-09-05. 구현 세션은 이 파일만 읽고 시작할 수 있어야 한다. 아래 수치는 전부 이 세션에서 Aside `u0`로 실측한 값이다(약 85요청). codex(gpt-6-astra, medium) 적대적 리뷰 1회(24건)를 반영했다(맨 끝 절).

## Context

성진은 클로드가 레딧을 **사람처럼** 쓰기를 원한다. 홈 피드를 훑다가 글을 열고, 댓글 트리를 읽고, 댓글 쓴 사람의 활동을 보고, 커뮤니티를 찾고, 특정 커뮤니티 안에서 검색하는 흐름을 스크린샷·클릭 없이 밀도 높은 텍스트로 수행한다. 시각 UI 대신 레딧 웹 클라이언트가 실제로 쓰는 JSON 백엔드(어떤 레딧 URL이든 `.json`을 붙이면 나오는 `Listing`/`thing` 응답)를 직접 부르고, 로그인은 이미 로그인된 **Aside 브라우저** 세션을 `aside repl`의 `fetch`로 빌린다.

이전 시도 `.tmp/Agentic Reddit`(PyPI `agentic-reddit` v0.3.0, 4,250줄)은 **익명 세션 전제**로 설계됐다. 그 전제 때문에 (1) 브라우저를 직접 소유하는 `session.py` 545줄과 scrapling 의존성이 생겼고, (2) 홈 피드·구독·저장 같은 개인 표면이 원천 불가능했으며, (3) `/api/morechildren`이 익명 세션에서 HTML 렌더 형태를 돌려주는 바람에 큰 스레드 확장이 "물리적으로 불가능"으로 결론났다. 이번 실측에서 로그인 세션은 이 셋을 전부 뒤집는다: 브라우저는 Aside가 갖고 있고, 개인 표면 4종이 읽히며, `morechildren`은 깨끗한 `t1` 객체를 100개 id당 1요청에 돌려준다. 남는 것은 검증된 식별자 파서(`identity.py`)·봉투 워커(`parse.py`)·모델(`model.py`)·헤더 기반 페이싱(`pacing.py`)과 댓글 앵커 검증(`retrieve._forest_contains`)이다.

facebook 스킬과 같은 하네스 프레임을 코드에 닿게 적용한다. **principle over rail**: SKILL.md는 규칙 나열이 아니라 레딧의 사실과 그 결과를 쓴다. **interface over document**: 명령·플래그·종료 코드·복구 명령은 `--help`와 출력 자체가 가르치고 SKILL.md는 "언제·왜·무엇이 물었나"만 쓴다. **for user not developer**: 읽는 이는 사용 시점의 클로드다. 기본 출력은 클로드가 읽을 밀도 높은 텍스트이고 전체 JSON은 요청할 때만 나온다. **dense information**: 게시물 하나는 3~4줄, 댓글 하나는 2~3줄이며 다음 홉의 핸들(`r/…`, `u/…`, URL)을 항상 싣는다.

페이스북과 다른 점 셋이 설계를 결정한다. **예산이 훨씬 빡빡하다**(10분에 100요청, 로그인해도 같음, 모든 CLI 호출이 공유). **응답은 한 번에 훨씬 많이 준다**(게시물 1요청에 댓글 491개, 목록 1요청에 100건). **토큰·doc_id·회전이 없다**(refresh 명령 불필요). 그래서 "적게 요청하고 한 번에 많이 받되, 클로드에게는 조금씩 보여주고 나머지는 핸들로 이어준다"가 구조의 축이고, 그 나머지를 담는 **스레드 상태 파일**이 이 스킬에서 가장 신경 써야 할 계약이다.

## 확정된 결정 (성진, 2026-09-05)

| # | 결정 | 결과 |
|---|---|---|
| D1 | **실계정(Aside `u0`) 로그인 세션 사용** | 홈 피드·구독·저장·추천 목록이 열린다. 요청 간격 하한·예산·차단 상태를 코드에 고정한다. |
| D2 | **읽기 전용** | 추천·댓글·저장·구독 등 모든 쓰기는 스펙에 `declined`. `modhash`가 응답에 실려 오지만 어떤 코드 경로도 이를 쓰지 않는다. |
| D3 | **개인 표면은 구독·저장·추천 포함, 메시지함 제외** | `me {subs,saved,upvoted}`. 받은 메시지함(`/message/inbox`)은 `declined`(사적 대화). |
| D4 | **Claude 헤드리스 e2e 미실행** | codex가 SKILL.md·`--help`·실제 출력만으로 시나리오를 수행하는 사용성 검토와 `pytest -m live`로 대체. 스펙에 미실행으로 기록. |
| D5 | 본문·`--help`·주석은 영어, description 트리거에 한국어 표현 포함 | facebook D5와 같다. 스펙·커밋·PR은 한국어. |
| D6 | **스킬은 완결적** | facebook 모듈을 import하지 않고 복사한다(레포 결정, facebook 계획 참조). `tests/reddit/` 아래에 스킬별 테스트. |
| D7 | 배포는 레포 `.claude/skills/reddit`이 원본, `~/.claude/skills/reddit` 심볼릭 링크 | facebook과 같은 관례. |
| D8 | SKILL.md는 ultra-search처럼 **헤딩 위계가 있는 구조** | 내용은 레딧 고유의 사실. 골격은 아래 절. 길이는 완료 기준이 아니다. |

## 실측 사실 장부

아래는 이 세션에서 `aside --account u0 repl`의 `fetch`로 직접 확인한 것이다. 구현 세션은 재실측 없이 이 값으로 시작한다.

### 접근과 세션

- **F1** Aside `u0`는 레딧에 `u/BadImpossible6596`으로 로그인돼 있다. 샌드박스 `fetch`는 `accept: application/json` 헤더 하나만으로 쿠키를 싣고 200을 받는다. 페이스북과 달리 `sec-fetch-*`·`user-agent`·토큰이 필요 없다.
- **F2** 로그인 판정: `/api/me.json`이 `kind: t2`와 `data.name`을 준다(`/api/v1/me.json`은 로그인 여부와 무관하게 `features`만 준다. 쓰지 않는다). `/user/me/…`는 실제 사용자명으로 리다이렉트된다. 목록 응답의 `data.modhash`는 로그인 시 비어 있지 않은 문자열이다(익명 시 빈 문자열이라는 것은 옛 정찰 기록이며 이번에 재확인하지 않았다. A1).
- **F3** **레이트리밋은 로그인해도 10분에 100요청이다.** 모든 `.json` 응답에 `x-ratelimit-used`·`x-ratelimit-remaining`(소수 문자열, 예 `62.0`)·`x-ratelimit-reset`(초 카운트다운)이 실리고 `used + remaining = 100`이다. 창은 **첫 요청 뒤 약 600초짜리 고정 창**이고 만료되면 다음 요청이 새 창을 연다(80회 쓴 뒤 창이 만료되자 `remaining 97, reset 547`). 이 창은 **모든 CLI 호출이 공유**한다. 429는 유발하지 않았다.
- **F4** **호스트 함정.** `np.reddit.com/comments/<id>.json`은 `www`로 리다이렉트된 뒤 190KB HTML 봇 차단 페이지(403)를 돌려준다. 같은 경로를 `www.reddit.com`으로 직접 부르면 200이다. `old.reddit.com`의 `.json`은 404를 줬다(차단이 아니라 다른 라우팅). 모든 요청은 `www.reddit.com` + 경로로만 나간다.
- **F5** REPL 제약은 facebook F8과 같다(120초, `console.log` 한 줄 12MB, `require`·`URL` 없음, 빈 코드 거부). `fetch`는 `redirect: "follow"`(최종 `response.url`)와 **`redirect: "manual"`(301과 `location` 헤더, 본문 0바이트)** 둘 다 지원한다. 리다이렉트를 홉마다 검증할 수 있다.

### 표면별 엔드포인트 (전부 200, 로그인 세션)

| 사람의 동작 | 경로 | 응답 형태 | 크기·지연 |
|---|---|---|---|
| 홈 피드 | `/best.json`, `/hot.json`, `/new.json`, `/top.json?t=day`, `/rising.json` | `Listing` of `t3`, 개인화됨(ClaudeCode·ClaudeAI 등 구독 커뮤니티) | 3건 15KB/0.4s |
| 커뮤니티 목록 | `/r/<name>/{hot,new,top,rising,controversial}.json?t=&limit=&after=&count=`, `r/popular`, `r/all`, `r/a+b` 결합 | `Listing` of `t3`, `limit` 상한 **100**(150 요청 시 100 반환, 259KB/0.9s) | 3건 18KB/1.1s |
| 커뮤니티 정보 | `/r/<name>/about.json`, `/r/<name>/about/rules.json`, `/r/<name>/wiki/index.json` | `t5` / `{rules:[…]}`(kind 없음) / `wikipage` | 21KB, 14KB |
| 글 열기 | `/r/<sub>/comments/<id>.json?limit=&depth=&sort=`, `/comments/<id>.json`(서브레딧 없이도 됨) | `[Listing(t3×1), Listing(t1…, more)]` | 아래 F6 |
| 댓글 하나 열기 | `/r/<sub>/comments/<pid>/_/<cid>.json?context=N&limit=&depth=` | 2요소 배열, `[1]`의 루트가 요청한 `t1`; `context=3`이면 루트가 부모 체인의 조상으로 올라감(depth 0) | 76KB |
| 접힌 댓글 펼치기 | `GET /api/morechildren.json?api_type=json&raw_json=1&link_id=t3_<pid>&children=<id,…≤100>&sort=` | `json.data.things`(kind 없음, `json.errors` 배열): **평탄한** `t1`·`more` 목록(각각 `parent_id`·`depth` 보유, `replies`는 `""`). 100 id → `t1` 100 + `more` 44, 203KB/0.9s | 1요청 |
| 사용자 프로필 | `/user/<name>/about.json` | `t2`(karma·created_utc·is_mod·verified 등) | 2KB |
| 사용자 활동 | `/user/<name>/{overview,submitted,comments}.json?sort=&t=&limit=&after=` | `Listing` of `t1`/`t3` 혼합 | 3건 7.6KB/0.8s |
| 검색 | `/search.json?q=&type=link\|sr\|user&sort=&t=&limit=&after=&include_over_18=on` | `t3`/`t5`/`t2` | 3건 0.2~35KB |
| 커뮤니티 안 검색 | `/r/<sub>/search.json?q=&restrict_sr=1&sort=&t=` | `t3` | 19KB/0.6s |
| 커뮤니티 찾기 | `/subreddits/search.json?q=`, `/api/subreddit_autocomplete_v2.json?query=&include_over_18=1&limit=` | `t5` / `t5`·`t2` 혼합 | 13KB |
| 내 것 | `/subreddits/mine/subscriber.json`, `/user/me/saved.json`, `/user/me/upvoted.json` | `t5` / `t3`·`t1` / `t3`·`t1` | 5건 51KB |
| 다른 커뮤니티의 같은 링크 | `/duplicates/<id>.json` | `[Listing(t3 원본), Listing(t3 중복들)]`, 두 번째가 비면 "다른 토론 없음" | — |
| id 일괄 조회 | `/api/info.json?id=t3_a,t1_b,t5_c` | `Listing` 혼합 | — |
| 짧은 링크 | `https://redd.it/<id>` | 301 → `https://www.reddit.com/comments/<id>` (`<id>`가 곧 글 id이므로 **네트워크 없이 로컬 변환**) | — |

- **F6 댓글 트리 크기(2,240댓글 스레드).** `limit=20&depth=2` → t1 20, 69KB/0.6s. `limit=100&depth=5` → t1 100, 245KB/0.9s. **`limit=500&depth=10` → t1 491(부모 42개 수준이 아니라 전체 노드 수), 최대 깊이 9, 998KB/2.7s, `more` 63개.** `sort=new`는 depth 0만 온다(답글이 트리로 안 온다). 최상위 `more`(parent `t3_…`)는 `count`(1,596~1,939)와 `children` id 수(1,588~1,895)가 **다르다**. `sort=best`와 `sort=confidence`는 같은 순서를 준다(`suggested_sort`는 null).
- **F7 `morechildren` 재구성.** 응답은 평탄하므로 `parent_id`로 트리를 다시 짜야 한다(옛 `parse.splice_subtree`는 서브트리 응답용이라 그대로 못 쓴다). 반환 `more` 노드들은 다음 배치의 입력이다. 요청한 id 중 일부(삭제·검열)는 돌아오지 않을 수 있다.
- **F8 없음·닫힘의 형태.** 없는 서브레딧·사용자·글은 **404** `{"message":"Not Found","error":404}`(익명 세션의 "빈 Listing"과 다르다). 프리미엄 전용은 403 `{"reason":"gold_only"}`, 격리는 403 `{"reason":"quarantined", …}`. 옛 정찰의 목록: `private`, `banned`, 정지 사용자 403. NSFW 커뮤니티(`over18: true`)는 200으로 그대로 읽힌다.
- **F9 게시물 유형.** 75건 표본에서 `image` 20, `rich:video` 24, `poll` 25(`poll_data`), `gallery` 4(`is_gallery`·`media_metadata`), `crosspost` 1(`crosspost_parent_list`), `link` 1. 판정 순서는 gallery → poll → crosspost → video → self → `post_hint` → `link:<domain>`.
- **F10 검색 흔들림.** 같은 `/search.json?q=python&type=link&limit=3`이 첫 호출에 0건(184바이트, `after: null`), 이후 세 번은 3건을 줬다. 검색 0건은 그 자체로 결론이 아니다.
- **F11** `raw_json=1`이 없으면 본문의 `&`·`<`·`>`가 HTML 엔티티로 온다(레딧 문서상 동작. 표본을 두 번 찾았으나 해당 문자가 없어 직접 보지 못했다. A2). 모든 요청에 `raw_json=1`을 붙인다.
- **F12** 미검증: 모바일 공유 링크 `/r/<sub>/s/<id>`(표본을 못 구함). 규칙은 "`www` 호스트로 바꿔 수동 리다이렉트를 홉마다 검증하며 추적"이며 P2 시작 전에 성진이 실제 공유 링크 하나를 준다(A3).

## 설계

### 실행 모델

```
reddit.py <cmd> ──▶ Python(stdlib) ──spawn──▶ aside --account u0 repl <fetch.js> ──▶ Aside fetch ──▶ www.reddit.com/…json
      ▲                                                       │
      └── {status, url, body, ratelimit:{used,remaining,reset}} ◀─┘
```

- **한 `aside repl` 호출 = 한 요청.** facebook과 같은 이유(120초 무관, 페이싱은 Python이 소유). `# 성진: 요청당 스폰이 병목으로 측정되면 한 호출에 N요청 묶음` 주석을 같은 자리에 남긴다.
- **`fetch.js`는 경로만 받는다.** `ARGS: {path, query}` → `https://www.reddit.com` + path + `?…&raw_json=1`, `redirect: "manual"`(3xx는 봉투에 `status`와 `location`으로 실려 오고 Python이 판정한다). URL 전체를 받지 않으므로 F4의 호스트 함정이 코드상 불가능하다. 봉투는 항상 `{status, url, body, location?, ratelimit}`이며 `_aside`가 그 형태를 검증한다. 12MB 초과 대비 조각 전송은 facebook `graphql.js`의 것을 그대로 옮긴다(실측 최대 1MB).
- **`resolve.js`는 공유 링크 전용이다.** 로컬에서 정규화할 수 있는 형태(호스트 변형 `www/old/np/sh/reddit.com` → `www`, `redd.it/<id>` → 글 id, `/comments/<id>`, `/gallery/<id>`, 댓글 permalink, 트레일링 슬래시·쿼리)는 `_target.py`가 **네트워크 없이** 처리한다. `/r/<sub>/s/<id>`만 `resolve.js`로 보내며, JS는 `https` + 정확한 호스트(`www.reddit.com`) + userinfo·포트 없음을 검사한 뒤 `redirect: "manual"`로 **최대 3홉**을 각 홉마다 같은 검사로 따라가고, 같은 봉투 형태로 최종 URL을 돌려준다. 이 해석도 요청 1회로 예산에 든다.
- **판정은 Python 한 곳(`_transport.classify`)에서, 엔드포인트별 기대 봉투를 가지고, 이 순서로.**
  1. 요청 제한: HTTP 429(JSON이든 HTML이든) → `reset` 헤더가 있으면 그 초, 없으면 600초 만료 차단.
  2. 봇 차단: HTTP 403 **이면서** 본문이 HTML **이면서** 확인된 표식(최종 URL 또는 본문의 `js_challenge`, 옛 정찰 기록의 190KB 챌린지 HTML 표식. P1에서 표식 문자열을 확정) → 만료 없는 차단. 표식이 없는 HTML 403은 6(봉투 이탈)이지 차단이 아니다.
  3. 일반 HTTP 실패: 5xx·빈 본문·비JSON → 6. **차단하지 않는다**(502 하나로 영구 차단되지 않도록).
  4. 대상 없음·닫힘: 형식이 검증된 대상에 대한 404, 또는 403 JSON의 `reason`이 알려진 값(`private`, `gold_only`, `quarantined`, `banned`, 정지 사용자) → 9. 모르는 `reason`은 6(메시지에 reason 포함).
  5. 로그인: **명시적 신호에만**. `doctor`·개인 표면 이어읽기의 `/api/me.json` 성공 봉투에 `name`이 없음, 또는 `home`·`me`의 성공 목록에서 `modhash == ""`(A1) → 4.
  6. 봉투: 엔드포인트별 기대(`listing`, `thing:t5`, `thing:t2`, `post_pair`, `rules`, `morechildren`(`json.errors`가 비어 있지 않으면 6), `duplicates`)에 맞지 않으면 6.
  7. 정직한 0건(7): **선택한 결과 표면**이 검증된 빈 결과일 때만. 댓글 없는 글은 글이 정상이므로 0이고, `duplicates`의 두 번째 Listing만 빈 것도 0이다.
- **예산 관측과 응답 성공 판정은 분리한다.** 유효한 응답은 `remaining`이 0이 되어도 출력·커밋하고, 차단은 **다음 네트워크 요청**부터다. 캐시만 읽는 이어읽기·`schema`·`doctor`의 로컬 부분은 예산 0에서도 동작한다.

### 예산 계약 (`_budget.py`)

- **파일** `~/.cache/reddit-skill/budget.json`: `{observed_at(벽시계 epoch), expires_at(= observed_at + reset), remaining, used, next_allowed_at, block:{reason, expires_at|null}}`. `reset` 카운트다운은 저장하지 않고 만료 시각으로 바꿔 저장한다. 프로세스 안의 대기는 monotonic 시계로 계산한다.
- **잠금 범위.** facebook `_transport`처럼 **요청 한 번의 전체 주기**가 `account_lock` 안에서 돈다: 파일 재읽기 → 차단·만료 판정 → 페이싱 대기 → **요청 전에 `remaining -= 1`과 `next_allowed_at`을 파일에 예약** → 요청 → 헤더로 파일 갱신(응답을 못 받아도 예약분은 남는다). 두 CLI 호출이 같은 1회를 쓰는 경쟁, 늦게 끝난 응답이 오래된 헤더로 덮는 문제, 죽은 프로세스의 미기록을 이 순서가 막는다.
- **만료 뒤.** `expires_at`이 지났으면 오래된 0을 폐기하고 요청을 허용한다(첫 응답이 새 창을 관측한다). 헤더가 없거나 일부만 있거나 비정상 값이면 마지막 관측을 유지하되 로컬 예약분만 차감한다(보수적). 시계가 뒤로 가면(observed_at > now) 파일을 무시하고 재관측한다.
- **페이싱.** 요청 간 하한 1.0초(+0~0.5초 지터), 플래그로 못 낮춘다. `remaining ≤ used`가 되면 `(expires_at - now)/remaining`초로 늘린다(옛 `pacing.py` 거버너 이식, `wait_on_limit`는 삭제. 기다림은 사람의 결정).
- **호출당 예산.** 기본 8회. 명시적 `--limit`·`--since`·`--out`이 있으면 목표까지, 절대 상한 60회/호출. "명시적"은 argparse `default=None`으로 판정한다. `# 성진: 60회는 한 호출이 10분 창 100회 중 40회를 다른 호출에 남기는 값, 창이 커지면 올린다`.
- **차단.** `block.reason ∈ {challenge, rate_limit}`. `rate_limit`는 `expires_at`에 자동 해제, `challenge`는 사람이 Aside에서 레딧을 열어 클리어한 뒤 `doctor --unblock`. 차단 중 모든 네트워크 요청은 요청 없이 exit 5이고 오류 JSON의 `fix`에 남은 초를 적는다.

### 식별자 계약 (`_target.py`)

- **identity는 항상 fullname**(`t3_abc`, `t1_abc`, `t5_…`, `t2_…`)이다. 페이지네이션 중복 제거·커서·`--out` 커밋·복구·스레드 상태 전부. 옛 모델의 접두어 없는 `id`를 identity로 쓰면 혼합 목록에서 `t3_abc`와 `t1_abc`가 충돌한다.
- `Target(kind ∈ {subreddit, subreddits, user, post, comment, share, me}, sub, post_id, comment_id, user, name)`. 옛 `identity.py`의 정규식·검증을 이식하고 URL 형태를 추가한다: `/comments/<id>`, `/gallery/<id>`, `/r/<sub>/comments/<pid>/<slug>/<cid>`, `/r/<sub>/comments/<pid>/comment/<cid>`, `redd.it/<id>`, `/r/<sub>/s/<id>`(share), 호스트 변형, 트레일링 슬래시·`?utm_*`. 위키·모드 페이지 등은 exit 2 + fix.
- **명령별 허용 Target 종류**를 `reddit.py`가 표로 갖고 `--help`의 positional 설명에 싣는다. `about`은 명시적 `r/`·`u/` 또는 분류 가능한 URL만 받고, 접두어 없는 단어(`about python`)는 exit 2 + fix("prefix r/ or u/"). `r/a+b`는 `sub`에서만.
- CLI 값 → 서버 값 매핑은 `_transport`의 경로 빌더 한 곳: `best → confidence`, `--type posts → submitted`, `--nsfw → include_over_18=on`.

### 명령 표면 (`reddit.py --help`가 진실, 여기는 설계 의도)

사람이 레딧에서 하는 동작을 레딧의 명사로 만든다. 모든 읽기 명령은 같은 출력 옵션(`--json`, `--chars`, `--out`, `--limit`, `--after`)을 공유한다. **`--out FILE`은 facebook과 같은 로컬 저장이다**(성진 요청): `home`·`sub`·`user`·`me`·`search`는 페이지 단위로 NDJSON을 커밋하고 중단 뒤 같은 명령으로 이어받으며, `post`·`comments`는 글 한 줄 뒤에 댓글을 평탄 레코드로 저장해 스레드 전체(수천 댓글)를 클로드가 읽지 않고 파일로 모을 수 있다. 화면에는 요약 한 줄과 예산만 나온다.

| 명령 | 사람의 동작 | 받는 대상 | 요청 |
|---|---|---|---|
| `home [--sort best\|hot\|new\|top\|rising] [--time]` | 레딧을 연다 | 없음 | `/{sort}.json` |
| `sub <r/name[+name]> [--sort hot\|new\|top\|rising\|controversial] [--time] [--since --until]` | 커뮤니티에 들어간다 (`popular`·`all` 포함) | subreddit(s) | `/r/<name>/<sort>.json` |
| `post <target> [--sort best\|top\|new\|controversial\|old\|qa] [--depth]` | 글을 연다: 전문 + 첫 댓글 배치 | post, share | `/comments/<id>.json?limit=500&depth=10&sort=` **1회** → 스레드 상태 생성 |
| `comments <target> [--sort] [--depth] [--context N] [--after N]` | 댓글을 더 본다 / 링크된 댓글 하나를 연다 | post(상태가 있으면 이어읽기, 없으면 `post`와 같은 1회 조회 뒤 댓글만 표시), comment(서브트리) | 저장분 먼저(0회), 그 뒤 `morechildren` 100개 묶음; 댓글은 `/_/<cid>.json?context=` |
| `user <u/name> [--type overview\|posts\|comments] [--sort] [--time] [--since --until]` | 작성자를 눌러 활동을 본다 | user | `/user/<name>/{overview,submitted,comments}.json` |
| `about <r/name \| u/name \| url>` | 커뮤니티 사이드바 / 프로필 카드를 본다 | subreddit(단일), user | `t5`+rules(2요청) / `t2`(1요청) |
| `search <text> [--in r/name] [--type posts\|subs\|users] [--sort] [--time] [--nsfw]` | 검색창 | 자유 텍스트 | `/search.json` 또는 `/r/<name>/search.json` |
| `me subs\|saved\|upvoted` | 내 커뮤니티·저장·추천 | 없음 | `/subreddits/mine/subscriber.json` 등 |
| `related <target>` | "다른 커뮤니티의 같은 링크" | post | `/duplicates/<id>.json` |
| `doctor [--unblock]` | 준비됐나 | — | aside·로그인(`/api/me.json` 1회)·예산 파일·차단 상태·스레드 캐시 크기 한 줄 |
| `schema` | 객체 필드 설명 | — | Post·Comment·Subreddit·User를 `to_dict()`에서 유도. 요청 0회 |

**날짜 창.** 레딧 목록에는 서버 날짜 필터가 없다. `--since/--until`은 **클라이언트 필터**이며 항상 `--sort new`와 짝이고(다른 정렬과 함께 주면 exit 2), 고정글·날짜 없는 항목은 종료 판정에서 제외하고 `pinned`/`undated`로 표시하며, 고정글이 아닌 날짜 있는 항목이 `since`보다 오래되면 멈춘다. `stop_reason`은 `window_reached`(창을 다 봤다)와 `exhausted`(서버 목록이 끝났다. 레딧 목록은 최대 약 1,000건이므로 창을 다 못 봤을 수 있다)를 구분해 출력한다. `top`·`controversial`의 `--time hour|day|week|month|year|all`은 서버 필터이고 별개다.

**검색 0건(F10).** 예산이 있으면 1회 재시도하고(예산에 포함), 그래도 0건이면 exit 7. 재시도할 예산이 없으면 exit 8(부분)이며 "0건은 미확인"이라고 적는다. SKILL.md는 두 번의 0건도 "레딧에 없다"의 증명은 아니라고 쓴다.

### 스레드 상태 계약 (`_thread.py`) — 이 스킬의 핵심

`post`가 1요청으로 받은 500노드짜리 트리를 화면에는 조금만 보여주고 나머지를 요청 없이 이어 읽게 하려면, 커서가 "안 보인 댓글 + more id"보다 훨씬 많은 것을 기억해야 한다.

- **파일** `~/.cache/reddit-skill/threads/<post fullname>-<sort>.json` 하나에 스레드 전체 상태를 두고, 번호 커서(`cursors/<n>.json`)는 그 파일과 위치·표시 옵션을 가리킨다. 스레드 파일은 이어읽기마다 **제자리 갱신**(임시 파일 + `os.replace`)하며 커서마다 트리를 복사하지 않는다.
- **내용**: `nodes{fullname → {data(모델 dict), parent(fullname), children[정렬된 fullname 목록], shown(bool), first_seen_at}}`, `root_children[...]`, `pending_more[{parent, ids[], count, from_pointer_key}]`, `requested_ids{…}`, `received_ids{…}`, `orphans{parent → [node…]}`, `post(모델)`, `fetched_at`, `expanded_at[]`, `account(레딧 사용자명)`, `context{target, sort}`. 포인터 식별 키는 `(parent, tuple(children))`이며 옛 `_more_identity`처럼 `(parent, count, depth)`만 쓰지 않는다.
- **표시 순서와 배치.** 표시는 항상 트리 DFS 순서다. 한 배치는 "아직 `shown`이 아닌 노드 중 표시 깊이 이하"를 DFS로 `--limit`개까지 보여준다. 이미 보인 부모 아래의 새 노드를 보여줄 때는 부모를 **한 줄 문맥**(`[c7 shown earlier] u/x: "…"`)으로 재표시해 관계를 잃지 않는다. 배치 안에서 정렬된 스냅샷을 보장할 뿐, 배치 간 전역 정렬은 주장하지 않는다(헤더에 `fetched 13:00, expanded 13:20`).
- **고정 문맥 vs 표시 옵션.** 대상·정렬은 고정 문맥이며 바꾸면 새 조회(새 스레드 파일). `--limit`·`--depth`·`--chars`·`--json`은 표시 옵션이며 `--after`와 함께 자유롭게 바꿀 수 있다(깊은 답글은 `--depth`를 올려 연다).
- **요청 순서.** `comments --after`는 (1) 안 보인 노드가 표시 깊이 안에 있으면 요청 0회, (2) 없으면 `pending_more`를 DFS 순서로 100개 묶어 `morechildren` 1회, 응답을 병합 후 다시 (1). 병합 규칙: `parent_id`로 `nodes`에 붙이고, 그 포인터가 있던 형제 위치에 삽입하며, 부모가 아직 없으면 `orphans`에 보관했다가 부모가 도착하면 재연결한다. 병합 뒤에도 남은 `orphans`는 배치 끝에 `orphan reply-to=<fullname>`로 표시하고 버리지 않는다.
- **진행 불가.** 요청 id는 `requested_ids`에, 돌아온 것은 `received_ids`에 넣고, 요청했으나 안 돌아온 id는 `missing`으로 센다. 한 배치가 새 노드도 새 포인터도 만들지 않으면 `stop_reason=stalled`로 끝낸다(무한 재요청 금지). `children`이 빈 포인터(`count>0`)는 부모 permalink 서브트리 1요청으로 대신 펼치고, 부모가 글이면 `unresolved`로 표시한다.
- **완료.** `pending_more`·`orphans`·`missing`이 모두 비어야 `complete`다. `hidden=0`만으로 판정하지 않는다. 헤더 수치는 부모 수·전체 파싱 수·이번 표시 수·미표시 수·대기 포인터의 id 합·최소 필요 요청 수(`ceil(ids/100)`, "at least")를 구분한다.
- **댓글 permalink 앵커.** `comments <댓글 URL>`은 응답 트리에 요청한 `post_id`와 `comment_id`가 실제로 있는지 검증한다(옛 `_forest_contains` 이식. 없는 댓글 id는 서버가 404 대신 일반 목록을 주는 실측이 있다). `--context`로 조상부터 시작해도 요청한 댓글은 표시 깊이와 무관하게 강조해 보여준다.
- **수명.** 스레드 파일·커서는 24시간 뒤 다음 쓰기 때 정리하고, 캐시 총량 상한 200MB를 넘으면 오래된 것부터 지운다. `doctor`가 캐시 크기를 보고한다. 개인 활동 캐시도 여기 있으므로 SKILL.md의 삭제 원리는 `--out` 파일과 캐시 둘 다를 가리킨다.
- **계정.** 스레드·커서 문맥에 레딧 사용자명을 저장한다. `me`·`home` 커서를 **네트워크로** 이어받기 전에는 `/api/me.json` 1회(예산 포함)로 같은 계정인지 확인하고, 캐시만 출력할 때는 "원래 계정·조회 시각"을 헤더에 적고 로그인 확인을 주장하지 않는다.

### 출력 계약

**기본(텍스트).** facebook과 같은 규약: 데이터와 명령을 구분하고, 본문은 한 줄로(개행은 `⏎`), URL은 따옴표. 헤더 한 줄에 표면·정렬·건수·중단 사유·**남은 예산**, 끝줄에 `more:`.

```
home · sort=best · 5 shown · stopped=limit · budget 62 left, resets in 4m
[p1] r/ClaudeCode · u/someone · 2026-09-05T10:12+09:00 · self · score=516 (93%) · comments=28 · flair="Discussion"
     title: "Did we just get a reset?"
     text[180/412 chars]: "Since some people keep asking about the differences, …"
     url: "https://www.reddit.com/r/ClaudeCode/comments/1orl7xk/…"
[p2] r/pics · u/photog · 2026-09-05T08:00+09:00 · gallery(4) · score=12k (97%) · comments=340 · nsfw
     title: "…"   captions: "…" ⏎ "…"
     url: "…"   link: "https://www.reddit.com/gallery/…"
more: python3 "/…/reddit.py" home --sort best --after 12
open: `post <url>` · community: `sub r/ClaudeCode` / `about r/ClaudeCode` · person: `user u/someone` / `about u/someone`
```

```
post · r/AskReddit · sort=best · fetched 2026-09-05T13:00+09:00 · parents 42 · parsed 491 · shown 25 · unshown 466 · pending 1,588 ids (≥16 requests) · budget 61 left
[p1] r/AskReddit · u/asker · … · self · score=… · comments=2240 (Reddit's count includes deleted)
     title: "…"
     text[full]: "…"
[c1] u/alice · 2026-09-05T02:11+09:00 · score=812 · replies 14 shown-later · +9 pending
     "…"
     url: "https://www.reddit.com/r/AskReddit/comments/1w7icu8/_/p7v5y8k/"
  [c2 reply-to=c1] u/bob · … · score=201
     "…"
     url: "…"
[c3] [deleted] · … · score=hidden
more: python3 "/…/reddit.py" comments "https://www.reddit.com/comments/1w7icu8" --after 13     (next batch needs 0 requests)
branch: `comments <comment url> --context 2`
```

- **본문 정규화(`_render._text`, 성진 요청).** 클로드가 읽을 텍스트는 정보만 남긴다: 연속 공백·개행은 하나로 접고(단락 경계만 `⏎`), 제로폭·방향 제어·변형 선택자 등 보이지 않는 문자와 마크다운 서식 기호(`**`, `*`, `~~`, `^`, `>` 인용 접두, 표 구분선)는 벗기고, 마크다운 링크 `[text](url)`는 `text (url)`로, 같은 URL의 반복은 한 번만, HTML 엔티티가 남아 있으면 풀며(A2 보강), `[removed]`·`[deleted]` 본문은 그 라벨 하나로 줄인다. 값이 없는 필드(`flair` 없음, `edited` false, 캡션 없음, `?`인 수치 중 항상 없는 `downs`류)는 **줄 자체를 생략**한다. `text[shown/received chars]`의 `received`는 정규화 **뒤** 길이이고, 원문 그대로가 필요하면 `--json`이다. 골든 테스트가 이 규칙을 고정한다.
- 댓글마다 `url:`(permalink)을 싣는다. `[cN]` 번호는 배치 안에서만 유효하고 다른 배치의 같은 번호가 같은 댓글이라는 보장이 없다는 것이 이유다.
- 게시물 유형별 기본 텍스트: `self`는 본문, `link`는 도메인+URL, `image/video`는 미디어 URL, `gallery(n)`는 캡션들, `poll`은 선택지와 표(`poll_data.options`, 투표 수는 `?` 가능), `crosspost`는 원본의 `r/·u/·title·url` 한 줄.
- 수치 nullable은 `?`, 삭제된 작성자는 `[deleted]`, `score_hidden`이면 `score=hidden`. 스티키·잠금·스포일러·NSFW·편집됨은 라벨로. 엔티티: `[s1] r/python · 1.5M subscribers · public · nsfw=no · "…"`, `[u1] u/spez · karma post=… comment=… · since 2005-06 · admin`. `about r/…`는 t5 필드 뒤에 `rule 1: …` 줄들.
- **`--json`**: 항상 JSON 문서 하나(`{"ok":…,"results":[…],"stop_reason":…,"next":…,"budget":{…},"thread":{…}}`). 실패는 `{"ok":false,"error":<code>,"message":…,"fix":…}`. argparse 오류도 같은 객체.
- **`stop_reason`**: `limit_reached | exhausted | window_reached | budget | rate_limited | blocked | stalled | query_failure`.
- **`--out FILE`**: 목록은 facebook `OutFile`(헤더 대조·페이지 커밋·이어받기)을 fullname 기준으로 이식. **댓글은 다르다**: 레코드는 `parent`·`depth` 필드를 가진 **평탄한 댓글 한 줄씩**이고, 페이지 마커에 `pending_more`·`requested_ids`·`orphans`를 함께 커밋해 마커에서 스레드 진행 상태를 복구할 수 있게 한다. 중첩 `replies`를 기록하지 않는다.
- **종료 코드**: 0 성공 · 2 잘못된 인자 · 3 aside 불가 · 4 레딧 로그인 필요 · 5 차단(봇 차단은 `doctor --unblock`, 요청 제한은 만료 뒤 자동 해제, **재시도 금지**) · 6 봉투 이탈·일시 장애 · 7 정직한 0건 · 8 부분 결과(예산·창 미달·정체) · **9 대상 없음·닫힘**. 7과 9를 나누는 이유: 7은 다른 창·정렬로 다시 물을 가치가 있고 9는 없다.

### 디렉터리 구조 (최종)

기능 단위 모듈, 책임 하나, 400줄 이하, 엔트리는 argparse와 디스패치만. 파서·모델·스레드 모듈은 transport를 import하지 않는다. 소유권: `_thread`가 상태를 만들고 `_output`은 저장·복구만 한다.

```
Agentic SNS/
├── .claude/
│   ├── harness-spec.md                     # 인벤토리 행 B4(reddit)·B5(쓰기 declined)·B6(메시지함 declined) 추가
│   ├── plans/…                             # 이 파일 (.gitignore 예외 추가)
│   └── skills/reddit/
│       ├── SKILL.md                        # 아래 골격
│       └── scripts/
│           ├── reddit.py                   # argparse 배선·공통 옵션(default=None)·명령별 허용 Target·디스패치·종료 코드
│           ├── _errors.py                  # RedditError(code, message, fix), 코드별 fix 문구, 진단 scrub (facebook 이식)
│           ├── _aside.py                   # aside 스폰, 빈 코드 거부, 120s 번역, 봉투 검증(status·url·body·location?·ratelimit) (facebook 이식)
│           ├── _budget.py                  # 예산 파일(만료 시각·예약), account_lock 안의 요청 주기, 하한+거버너, 차단 상태 (facebook _blocked + 옛 pacing)
│           ├── _transport.py               # 경로 빌더(www 고정·raw_json·CLI→서버 값 매핑), 엔드포인트별 기대 봉투, classify 7단계, Transport.get(path, expect)
│           ├── _target.py                  # URL·r/·u/·id36 → Target, 로컬 정규화, share 링크만 resolve (옛 identity 이식)
│           ├── _listing.py                 # Listing 워커(kind 보존), fullname 커서 페이지네이션, 클라이언트 창(고정글 제외), limit·예산 → stop_reason
│           ├── _models.py                  # Post·Comment dataclass + build_* + 유형 판정(F9)·poll·gallery·crosspost (옛 model 이식)
│           ├── _entities.py                # Subreddit·User·Rule dataclass + build_* (옛 model 이식)
│           ├── _schema.py                  # to_dict → 필드 설명·JSON Schema(nullable number 지원) (facebook 방식 확장)
│           ├── _tree.py                    # 글 응답·서브트리·morechildren 파싱, more 수집, 평탄→트리 병합·고아 재연결, 앵커 검증 (옛 parse + retrieve 이식)
│           ├── _thread.py                  # 스레드 상태 파일, 배치 선택(DFS·shown·표시 깊이), 포인터 큐, 정체·완료 판정, 수명·용량
│           ├── _render.py                  # 객체 → 밀도 텍스트. 라벨·시간대·chars·한 줄 규칙·문맥 줄은 여기만
│           ├── _output.py                  # --json 문서, --out(목록 페이지 커밋 / 댓글 평탄 레코드+진행 마커), CursorStore(번호→스레드 파일 참조)
│           ├── _cmds_browse.py             # home·sub·user·me·search·related (목록 모양)
│           ├── _cmds_thread.py             # post·comments (트리 모양)
│           ├── _cmds_meta.py               # about·doctor·schema
│           └── browser/
│               ├── fetch.js                # ARGS {path, query} → GET www.reddit.com (manual redirect) → {status,url,body,location?,ratelimit}
│               └── resolve.js              # ARGS {url} → https·호스트·userinfo·포트 검사 → 최대 3홉 수동 추적(홉마다 검사) → 같은 봉투
├── tests/
│   └── reddit/
│       ├── conftest.py                     # REDDIT_ASIDE_BIN → fake_aside, REDDIT_HOME → tmp, live 마커, 라이브 누적 30요청 가드(요청 직전 검사)
│       ├── fake_aside/aside                # 스니펫·경로별 캔드 봉투를 돌려주는 가짜 바이너리
│       ├── js/test_fetch.js · test_resolve.js   # node가 실제 스니펫을 mock fetch로 실행: URL 거부·raw_json·헤더 추출·manual redirect·홉 검사
│       ├── fixtures/*.ndjson               # 실캡처에서 구조만 유도한 합성 응답 (PII 없음): 목록·글 500·morechildren·서브트리·403 reason·404·rules·duplicates
│       ├── tools/derive_fixture.py · check_fixtures_pii.py   # facebook 것 이식
│       ├── test_cli.py · test_transport.py · test_budget.py · test_target.py · test_listing.py · test_models.py · test_entities.py · test_tree.py · test_thread.py · test_render.py · test_output.py
│       └── live/test_live.py               # -m live. 실제 Aside. 모양·불변식만
├── .github/workflows/test.yml              # reddit 테스트·JS·ruff·PII 게이트 추가
├── README.md                               # 스킬 색인에 reddit 행
└── pyproject.toml                          # live 마커 설명을 "the real logged-in account"로 일반화
```

### SKILL.md 골격 (D8)

ultra-search처럼 `#` 제목 아래 `##` 절이 있고, 각 절은 "사실 + 결과"만 쓴다. 명령·플래그·종료 코드·스키마·복구 절차는 싣지 않는다(`--help`·`schema`·오류 JSON의 `fix`가 인터페이스). 길이는 기준이 아니다. codex 지적대로 "깊게 먼저"류의 탐색 순서 강제는 쓰지 않고 비용 사실만 쓴다.

```
---
name: reddit
allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/reddit.py" *)
description: Read Reddit through the user's logged-in Aside browser: the home feed, subreddit listings, a post and its comment thread, a linked comment, a redditor's history and profile, search across or inside communities, and the user's own subscriptions, saved and upvoted posts. Use whenever the request is to read or explore something on Reddit — 레딧에서, 서브레딧, 이 스레드 댓글 읽어줘, 레디터들은 뭐라고 해, 내 레딧 피드 — including a bare reddit.com or redd.it URL with no mention of Reddit. Not for other social networks, general web pages, news about Reddit the company, or posting, voting, commenting, saving.
---

# Reddit through the user's own browser
  한 문단: 브라우저가 로그인된 계정을, CLI가 읽기 전용 질의와 밀도 텍스트를 준다. `$RD` 표기 규칙(한 줄, 따옴표, 절대 경로). `--help`·`schema`·오류의 `fix`가 나머지를 가르친다.

## The budget is shared and the tool counts it
  10분에 100요청, 로그인해도 같고 **모든 호출이 공유**. 매 출력 헤더의 `budget`이 진실. 새 대상을 열면 요청이 늘고, 이미 받은 스레드를 이어 읽는 것은 대부분 0회. 몇 개 커뮤니티·몇 명을 볼지는 시작 전에 정하는 편이 싸다. 예산이 0이면 도구가 멈추고 만료를 알려주니 기다림은 사람의 결정.

## Where a person starts
  `home`은 개인화 피드, `me subs`는 내 커뮤니티, `popular`·`all`은 레딧 전체. 한 서브레딧은 한 커뮤니티이지 레딧이 아니다.

## A thread is a tree read in batches
  `post`는 한 요청으로 수백 댓글을 받아 첫 배치만 보여주고 나머지는 `more:`로 이어진다. 이어 읽은 배치는 처음 조회 시점과 펼친 시점이 다르며(헤더에 둘 다), 배치 간 전역 정렬을 보장하지 않는다. `best/top`은 보상받은 자리, `new`·`controversial`은 다른 질문의 답이고 `new`는 답글을 트리로 주지 않는다. 보고할 때 정렬을 밝힌다. `comments=`는 삭제 포함이라 파싱 합보다 크다. 날짜 창은 클라이언트 필터라 `window_reached`와 `exhausted`가 다르다.

## r/ and u/ are the next command's arguments
  출력의 `r/…`·`u/…`·URL이 곧 인자. 낯선 커뮤니티는 `about r/`(규칙·규모·nsfw), 낯선 사람은 `about u/`(카르마·나이). 검색의 같은 이름은 `about`으로 확인. 댓글의 `url:`이 가지를 여는 핸들.

## What has actually bitten
  `np`·`sh` 등 다른 호스트는 봇 차단이나 404를 부르므로 도구가 www로 고정한다. 닫힌 커뮤니티는 다시 묻지 않는다(exit 9). NSFW는 표시되지 필터되지 않는다. 검색 0건은 흔들릴 수 있어 두 번 봐도 부재의 증명이 아니다. 공유 링크는 해석에 요청 1회가 든다.

## Large collections and what the cache holds
  `--out`은 클로드가 읽지 않을 만큼 클 때만. 파일과 `~/.cache/reddit-skill`의 스레드 캐시는 남의 개인정보(가명 계정의 활동 집계는 탈익명화 도구)이므로 레포 밖·작업 뒤 삭제.
```

## 구현 단계와 완료 판정

각 단계는 `tdd` 스킬로 시작한다(seam 합의 → 실패 테스트 → 통과). 단계마다 `codex`로 diff 리뷰를 받고 P1 지적은 그 단계 안에서 고친다. `TaskCreate` 트래커에 아래 판정 기준을 그대로 적는다. 라이브 검사는 `conftest`의 **누적 30요청 가드**(요청 직전 검사, 초과 시 테스트 skip) 아래에서 돌고, 데이터 의존 수치(≥50, ≥3) 대신 불변식을 단언한다.

| 단계 | 내용 | 완료 판정 |
|---|---|---|
| P0 | 스캐폴드: `reddit/` 생성, `tests/reddit/`, `.gitignore`에 이 계획 파일 예외, `harness-spec.md` 인벤토리 `approved` 행, 심볼릭 링크 | `audit_harness.py --path .`가 skill 2개·드리프트 0. `pytest tests/reddit`이 0개 수집 exit 5. `ls -l ~/.claude/skills/reddit`이 레포를 가리킴 |
| P1 | `_errors`·`_aside`·`_budget`·`_transport`·`_target` + `fetch.js`·`resolve.js` + `doctor` | fake aside 단위 테스트 통과. classify 픽스처: 429→5+만료 차단, HTML 403+표식→5+무만료, HTML 403 무표식→6, 502→6(차단 파일 없음), `remaining==0`인 200→정상 출력 후 파일 차단, 다음 호출 요청 없이 5, 404→9, `gold_only`/`quarantined`→9, 모르는 reason→6, `morechildren.json.errors` 비어있지 않음→6, 빈 children→7. `_budget`: 두 프로세스 동시 예약이 합쳐 1회만 차감, 만료 뒤 0 폐기, 시계 역행 무시, 헤더 없음 시 로컬 차감. `_target`: URL 14형을 Target으로, share만 resolve 경로. node: `fetch.js`가 URL을 받지 못하고 `raw_json=1`을 붙이며 3xx를 봉투로 돌려주고, `resolve.js`가 잘못된 호스트·4홉째를 거부. 라이브: `doctor` exit 0, 예산 파일에 `expires_at` |
| P2 | `_models`·`_entities`·`_schema`·`_listing`·`_render`·`_output(목록)` + `home`·`sub`·`user`·`me` | 합성 픽스처로 유형 6종(F9) 빌드·render 골든(본문 정규화: 공백 접기·제로폭 제거·마크다운 벗기기·링크 축약·빈 필드 줄 생략), 혼합 목록에서 `t3_x`·`t1_x` 공존. 라이브: `home --limit 3`, `sub r/python --sort new --limit 3` → `more:` 실행이 캐시 소진 후 **실제 `after` 요청**을 내고 fullname 중복 0, `user u/spez --type overview --limit 3`, `me subs --limit 3`, `--json` 단일 문서, 성진이 준 공유 링크 1건 해석(A3) |
| P3 | `_tree`·`_thread` + `post`·`comments`·`related` | 단위(합성 500노드 트리): 표시 25/깊이 2 분리, 보인 부모 아래 새 노드의 문맥 줄, `--depth` 상향으로 깊은 답글 열기, morechildren 평탄 응답 병합(형제 위치·고아 재연결·요청 미반환 id `missing`), 새 노드·포인터 없는 배치→`stalled`, 빈 children 포인터→서브트리 경로, 포인터 키에 children 포함, 앵커 검증(없는 댓글 id→9), 24h 정리·200MB 상한. 라이브: 2,000+댓글 스레드에서 `post` 요청 1회, `comments --after` 첫 회 요청 0, 저장분 소진 뒤 `morechildren` 1회의 **반환 id가 모두 요청 id의 부분집합이고 부모 연결이 `nodes`에 존재**, `comments <댓글 permalink> --context 2`가 조상부터 렌더하고 요청 댓글을 강조 |
| P4 | `search`·`about` + `--since/--until`·`--out` | 단위: 창 테스트가 포함·제외·고정글 제외·`window_reached`/`exhausted` 구분을 단언, 검색 0건 재시도(예산 있음→재시도, 없음→8), `about`의 r/·u/ 분기와 접두어 없는 단어 거절, 댓글 `--out` 평탄 레코드+진행 마커 복구. 라이브: `search "type hints" --in r/python --limit 3`, `search seoul --type subs --limit 3`→첫 결과로 `sub`, `about r/python`(t5 + rules 배열, 개수 미단언), `about u/spez`, `sub r/python --sort new --since <2일 전> --limit 20 --out <레포 밖>` 재실행 "already complete" |
| P5 | `SKILL.md`, `harness-spec.md`, README, CI, `validate_harness.py` exit 0, description 대조(facebook·ultra-search와 나란히) | 검증 절 참조 |

## Git과 Graphify (성진 요청)

- **브랜치** `feat/reddit-skill`을 `main`에서 판다. P0~P5 각 단계가 끝날 때마다 논리 단위로 커밋한다(`feat: reddit 스킬 …`, `test: …` 형식, 한국어 제목). P2 이후 단계 끝마다 푸시한다.
- **PR**은 P5 완료 후 하나로 연다. 제목 `feat: Reddit 읽기 전용 스킬 구현`, 본문은 `.github/pull_request_template.md`가 있으면 그 섹션대로, 없으면 `## 무엇을 바꿨나 / ## 왜 / ## 영향 / ## 검증`. `## 검증`에는 실제 실행한 명령과 수치를 적는다. CI(오프라인 pytest·node·ruff·PII)가 통과하면 `gh pr merge --squash`로 머지한다.
- **Graphify**는 두 번 갱신한다: P3 뒤(스레드 상태 계약이 코드로 굳은 시점)와 P5 뒤(최종). facebook 계획에 기록된 방식대로 Claude 호출을 피한다: `graphify extract . --code-only --no-cluster` → codex가 커뮤니티 이름을 부여 → `graphify export html --graph graphify-out/graph.json --labels graphify-out/.graphify_labels.json`. 결과는 로컬 산출물로 두고 `graphify-out/`은 커밋 대상이 아니면 그대로 둔다(현재 `.gitignore` 상태를 P0에서 확인).
- `harness-spec.md`의 Change history와 Validation은 P5에서 이 계획의 검증 수치로 채운다.

## 재사용 지도

| 출처 | 새 모듈 | 변경 |
|---|---|---|
| facebook `_aside.py`·`_errors.py`·`_blocked.py`·`_output.py` | `_aside`·`_errors`·`_budget`·`_output` | 복사 후 이름·마커·fix 문구 변경, 봉투에 `location`·`ratelimit`, 예산 파일과 요청 주기 잠금, identity를 fullname으로, 댓글 평탄 레코드 |
| facebook `_transport._request` 잠금 구조·`_paginate.py`·`_render.py`·`facebook.py`·`_schema.py` | `_budget`·`_listing`·`_render`·`reddit.py`·`_schema` | 구조만 따르고 내용은 레딧 봉투·필드로 재작성 |
| facebook `tests/facebook/{conftest,fake_aside,tools,js}` | `tests/reddit/…` | 이식 + 라이브 30요청 가드 |
| 옛 `identity.py` (179) | `_target.py` | 그대로 + 공유 링크·`/comments/<id>`·`/gallery/<id>`·댓글 permalink 2형·`redd.it` 로컬 변환 |
| 옛 `parse.py` (276) | `_tree.py`·`_listing.py` | `walk_listing_nodes`(kind 보존)·`collect_more`·`splice_subtree` 이식, morechildren 평탄→트리 병합 신규 |
| 옛 `retrieve.py`의 `_forest_contains`·`fetch_comment` 앵커 검증 | `_tree.py` | 이식 |
| 옛 `model.py` (1024) | `_models.py` + `_entities.py` (각 ≤ 400) | `raw`·`captured_at`·JSON Schema 생성기 삭제, 유형 판정·poll·gallery·crosspost 추가, schema는 `_schema`로 |
| 옛 `pacing.py` (130) | `_budget.py` | 거버너 이식, `wait_on_limit` 삭제, 만료 시각 저장·monotonic 대기 |
| 옛 `endpoints.py` (238) | `_transport.py` | 경로 빌더 축약, `www` 고정, CLI→서버 값 매핑 |
| 옛 `retrieve.py` 나머지·`cli.py`·`session.py`·`config.py`·`redact.py` | — | 가져오지 않음 (transport 전제·파일 출력 전제·scrapling) |

## 검증

- 단위: `python3 -m pytest tests/ -q` (aside 없이, facebook 228개와 함께). JS: `node --test tests/reddit/js/*.js`. 린트: `uvx ruff check --config pyproject.toml .claude/skills/reddit/scripts tests/reddit`. PII: `python3 tests/reddit/tools/check_fixtures_pii.py`.
- 라이브: `python3 -m pytest -m live tests/reddit/live/ -q`. 모양·불변식만 단언. 누적 30요청 가드.
- 하네스: `validate_harness.py --path .` exit 0, `audit_harness.py` 드리프트 0.
- codex: 계획 리뷰(완료) → 단계별 diff 리뷰 → 최종 사용성 검토. 기준은 **"본문과 `--help`·도구 출력만으로, 소스나 개발 문서 없이 네 시나리오를 수행할 수 있나"**: V1 "내 레딧 피드 뭐 올라왔어" → `home`. V2 "이 스레드 요약해줘(URL)" → `post` → 필요 시 `comments --after`, 정렬·시점·미표시 수를 보고에 밝힘. V3 "r/python에서 uv 얘기 어때" → `search --in` → `post` 2~3개, 예산 보고. V4 "이 댓글 단 사람 평소 뭐 하는 사람이야" → `about u/` → `user`. 근접 오발 둘: "이 페북 글 댓글", "이 레포 테스트 돌려" → 미호출.
- Claude e2e: 미실행(D4). 스펙에 그렇게 기록.

## 위험과 처리

| 위험 | 처리 |
|---|---|
| 10분 100요청 창을 여러 CLI 호출·세션이 공유 | 잠금 안의 요청 주기와 사전 예약, 만료 시각 저장, 호출당 기본 8·상한 60, 거버너, 0이면 요청 없이 exit 5 + 만료 표시 |
| 봇 차단이 로그인 세션에서도 발생 | 확인된 표식에만 무만료 차단, 일반 장애는 6. 호스트는 코드가 www로 고정 |
| 스레드 상태 병합 오류(순서·고아·무한 재요청) | 포인터 키에 children, 요청·수신 id 집합, `stalled`, 고아 보관·재연결·표시, 라이브 불변식 |
| 검색 흔들림(F10) | 예산 있으면 1회 재시도, 없으면 8, 두 번 0건도 증명 아님 |
| 공유 링크 미검증(F12) | P2 전에 표본 확보, 실패 시 exit 2 + fix |
| 캐시·수집 파일의 개인정보 | 24h 정리·용량 상한, 레포 밖 권장, `.gitignore`, 본문의 삭제 원리 |
| 응답 12MB 초과 | 실측 최대 1MB. 조각 전송 경로 유지 |

## 미룬 것 (스펙에 기록)

- 쓰기 동작 전부: `declined` (D2).
- 받은 메시지함·알림: `declined` (D3).
- 멀티레딧(`/api/multi/mine`은 빈 배열), 위키 본문, 모더레이터 목록(인증 필요): 범위 밖. 다음 패스가 묻는다.
- 미디어 다운로드: `--json`의 미디어 URL로 충분한지 먼저 본다.
- 요청당 프로세스 스폰 최적화: 병목이 측정될 때.

## 가정 (구현 세션이 확인)

- **A1** 익명 세션의 목록 `modhash`가 빈 문자열이라는 로그인 판정. 대안은 `/api/me.json` 1요청.
- **A2** `raw_json=1`이 HTML 엔티티를 없앤다. P2 라이브에서 `&`가 든 제목·본문 표본으로 확인.
- **A3** `/r/<sub>/s/<id>` 공유 링크가 `www` 호스트 수동 리다이렉트로 정식 URL이 된다.
- **A4** `morechildren`이 `sort=new|top|controversial`에서도 같은 평탄 구조를 준다(실측은 `confidence`만). P3 라이브에서 1회 확인.
- **A5** 봇 차단 HTML의 표식 문자열(옛 정찰의 `?js_challenge=1` URL). P1에서 픽스처로 고정하고, 표식이 없으면 6으로 떨어진다는 것이 안전한 기본이다.

## codex 리뷰 반영 (2026-09-05, run `20260905-140635-plan-review-79c4`)

24건 중 24건 반영. P1(13건): (1)(2)(3) 스레드 상태 계약을 fullname 노드 맵·형제 위치·shown·요청/수신 id·고아·정체 판정으로 다시 정의, (4) identity를 fullname으로 통일, (5) 댓글 `--out`은 평탄 레코드+진행 마커, (6) 봇 차단은 확인된 표식에만·일반 장애는 6, (7) 예산 관측과 응답 성공 분리·다음 요청부터 차단, (8) 잠금 안의 요청 주기와 사전 예약, (9) 만료 시각 저장·monotonic·시계 이상 규칙, (10) 커서에 레딧 사용자명·개인 표면 이어받기 전 확인, (11) 엔드포인트별 기대 봉투·7/9 조건 좁힘, (12) 댓글 앵커 검증 이식, (13) 로컬 정규화 우선·수동 리다이렉트 홉 검증·resolve도 같은 봉투. P2(10건): (14) 헤더 수치 구분, (15) 스레드 파일 제자리 갱신·수명·용량, (16) 고정 문맥 vs 표시 옵션·`best→confidence` 한 곳, (17) `--type posts→submitted`·커서 없는 `comments`·`--expand` 삭제·`default=None`·60회 주석 수정, (18) `about`의 명시적 접두어·명령별 허용 Target·`redd.it` 로컬 변환, (19) 댓글 permalink 핸들·유형별 기본 텍스트, (20) 창의 고정글 제외·`window_reached`/`exhausted` 구분·검색 재시도 예산, (21) 모델 분할·`walk_listing_nodes`·schema nullable·소유권, (22) 30요청 가드·불변식 단언·실제 after 요청 확인·표본 사전 확보, (23) SKILL 골격에서 탐색 순서 강제·인터페이스 중복 제거, 시점 차이·`new` 특성·창 불완전성 추가, `old` 404로 정정. (24) 미검증 주장은 A1~A5로 정리했고 `best≡confidence`·수동 리다이렉트 지원·창 만료 동작은 이 세션에서 추가 실측했다.

## 구현 진행상황

이 절을 지속 트래커로 사용한다. 위 P0–P5 표의 완료 판정 기준으로 상태를 갱신한다. TaskCreate·TaskUpdate·ToolSearch는 현재 도구 목록에 없어 계획서에 직접 기록한다.

| 단계 | 상태 | 실행 결과·남은 검증 |
|---|---|---|
| P0 | 완료 | audit skill 2개·drift 0, pytest tests/reddit 0개 exit 5, 사용자 스코프 심볼릭 링크 확인. ab671b1. 독립 리뷰는 P1 작업과 함께 진행 중. |
| P1 | 완료 | Python 114개·JS 6개·ruff 통과. 실제 doctor 1요청 통과. 독립 리뷰 3건(공유 링크 홉별 예산·중첩 replies 검증·인코딩 slug)을 재현·수정했다. |
| P2 | 완료 (A3 표본 제외) | 모델·렌더·schema·CLI 연결 완료. 실제 home·sub r/python(+after)·user u/spez·me subs·r/ClaudeAI 통과. 공유 링크 /s/ 표본 미확보. t2 사용자명/fullname 차이 재현·수정. 모델·렌더·목록·출력 33개 테스트 통과. |
| P3 | 완료 | 순수 코어 26개 통과, 독립 리뷰 6건 재현·수정. 실제 대형 글 1요청→캐시 0요청→morechildren 1요청·부모 연결·댓글 앵커 통과. Graphify 950노드·2,373간선·59커뮤니티 추출, Codex 명명 진행. |
| P4 | 완료 | 검색 재시도·파일 재실행·캐시 소실 복구·계정 문맥·시간대 비교·창 미달 빈 결과를 CLI로 검증. 실계정 검색→커뮤니티·소개·2일 창 수집→0요청 재실행 통과. 리뷰 4건 재현·수정. |
| P5 | 구현·검증 완료 | 본문·README·CI 연결. Python 435개·JS 36개 통과, ruff·PII·하네스 오류/경고 0, drift 0. 실제 출력 V1–V4 수행(활동 빈 결과 exit 7 포함). Git 마무리는 아래 PR 기록에서 추적한다. |

### 실행 결정·보정

- 2026-09-05: 사용자 요청에 따라 진행상황을 이 계획서에 통합하고 별도 진행 파일을 삭제했다. 이후 Codex는 gpt-6-astra/medium, fast 없이 사용한다.
- 공유 링크의 논리적 해석 한 번과 실제 HTTP 홉 수는 다르다. 남은 예산 0에서 추가 요청을 막는 상위 계약을 지키기 위해 각 실제 홉을 개별 예약·관측하도록 보정한다.

- P3 라이브에서 morechildren 요청 ID 1개에 t1 3개(요청 댓글+자손)가 반환됐다. 계획의 “반환 id ⊆ 요청 id” 조건은 실제 서버 계약과 달라 폐기한다. 요청 ID 수신 여부와 모든 반환 노드의 부모 연결을 검증하고, 실제 삭제·검열로 미수신한 요청은 missing으로 보존한다. 자손을 버리지 않는 현재 병합 방식은 유지한다.

- 첫 전체 오프라인 실행: `python3 -m pytest tests/ -q` → 363 passed, 8 deselected, 143.54초. 이후 리뷰 회귀 테스트를 추가 중이므로 최종 수치는 다시 기록한다.

- A4: 기존 대형 스레드 포인터로 `morechildren sort=top`을 1회 호출하여 평탄한 t1/more·parent_id 형태를 확인했다.
- 사용성 검토는 가드 포함 누적 총 30요청에서 종료했다. CLI의 Reddit 잔여 예산과 테스트의 30요청 상한은 별개다. 새 댓글 수와 문맥 행을 헤더에서 분리했고 수집 시각을 ISO로 통일했다.

### 최종 검증 기록

- 라이브 검증은 `python3 -m pytest -m live tests/reddit/live/test_live.py::<각 시나리오> -q`로 P1–P4 진행 중 나누어 실행했다. doctor, 목록/서버 after, 대형 스레드/앵커, 검색/소개/파일 창, top 정렬 morechildren의 5개 시나리오가 최종 통과했다. 대형 스레드 첫 시도는 서버가 자손을 함께 반환해 잘못된 계획 단언이 실패했고, 관측 계약으로 보정 후 통과했다. top 정렬 첫 선택은 빈 포인터만 골라 1회 skip됐고, ID가 있는 포인터 표본으로 바꿔 통과했다.
- Codex 사용성 검토 V1은 이전 홈 캐시를 0요청으로 읽었다. V2 글·댓글, V3 커뮤니티 검색 후 글 2개, V4 프로필·활동을 수행했다. 마지막 활동은 검증된 빈 Listing으로 exit 7이며 재시도하지 않았다. 본문·help·실제 출력만 사용했고 구현 소스는 열지 않았다. 자동 description 트리거 자체의 실행 검증은 하지 않고 Facebook·ultra-search 설명과 근접 오발을 대조했다.
- 실계정 검증·실제 출력 사용성 검토 합계는 30요청이다. 저장된 일별 가드가 요청 직전 검사하며, 사용성 검토의 별도 CLI에도 동일 가드를 사용했다. 요청 31은 fake Aside 경계 테스트로 차단을 확인했다.
- A1 익명 modhash와 A3 실제 /s/ 공유 링크는 이번에 실측하지 못했다. 현재 계정에서 로그아웃하지 않았고, 받은 URL은 r/ClaudeAI 커뮤니티 주소였다. 공유 링크는 합성 JS/Python 리다이렉트·예산·URL 경계 테스트로 검증했다. A2 raw_json 전달/잔여 HTML 엔티티 처리는 JS·렌더 테스트로 검증했고, 동일 표본의 옵션 유무 비교는 미실행이다. A4 top 정렬 평탄 응답은 실측했다. A5는 js_challenge 표식이 있을 때만 영구 차단하며 미표식 HTML 403은 오류 6이다.
- Claude headless e2e는 D4에 따라 미실행이다. 런타임은 표준 라이브러리와 Aside만 사용한다. 각 런타임 Python 모듈은 400줄 미만이며 스킬 밖 코드를 import하지 않는다.

- 최종 `python3 -m pytest tests/ -q`: 435 passed, 12 deselected in 157.79s. `node --test tests/facebook/js/*.js tests/reddit/js/*.js`: 36 passed. `uvx ruff check --config pyproject.toml .claude/skills/reddit/scripts tests/reddit`: All checks passed. `python3 tests/reddit/tools/check_fixtures_pii.py`: 5파일 통과. `validate_harness.py --path .`: 오류 0·경고 0. `audit_harness.py --path .`: skill 2·drift 0.

실제로 개별 실행한 라이브 명령(각 최종 1 passed):

- `python3 -m pytest -m live tests/reddit/live/test_live.py::test_doctor -q`
- `python3 -m pytest -m live tests/reddit/live/test_live.py::test_browse_real_listings_and_server_continuation -q`
- `python3 -m pytest -m live tests/reddit/live/test_live.py::test_large_thread_cache_expansion_and_comment_anchor -q`
- `python3 -m pytest -m live tests/reddit/live/test_live.py::test_search_about_and_file_window -q`
- `python3 -m pytest -m live tests/reddit/live/test_live.py::test_morechildren_top_sort_keeps_the_flat_envelope -q`

- P5 Graphify 최종: 960노드·2,358간선·63커뮤니티. `graphify extract . --code-only --no-cluster` → `graphify cluster-only . --no-label --no-viz` → Codex 명명 → `graphify export html --graph graphify-out/graph.json --labels graphify-out/.graphify_labels.json`. 전체 이름·HTML 반영을 확인했고 로컬 산출물로 유지했다.

### Git 마무리

P0–P5를 `feat/reddit-skill`에서 단계별 커밋했고 P2 이후 단계마다 푸시했다. 구현·로컬 검증은 완료됐으며 [PR #2 — feat: Reddit 읽기 전용 스킬 구현](https://github.com/tjdwls101010/Agentic-SNS/pull/2)에서 원격 CI와 스쿼시 머지 상태를 확인할 수 있다.
