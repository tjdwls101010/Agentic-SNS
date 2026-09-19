# finviz 스킬 4프레임 재점검과 보완 계획

> 구현 세션은 시작 시 이 파일을 형제 기록과 같은 이름 `.claude/plans/finviz 스킬 4프레임 점검.md`로 옮긴다.

## Context

성진이 코덱스에 준 원 프롬프트(`.claude/plans/user-inputs/260913_finviz 스킬 구현.md`)의 의도는 Finviz의 Screener·Groups·Insider·Calendar·티커별 Overview/Short Interest/Financials/Options 등 **무료 화면 전부를 클로드가 사람처럼 자유자재로 탐색하는 역량**을 harness-creator의 네 프레임(principle over rail, interface over document, for user not developer, dense information)에 맞게 주는 것이었다. 클로드가 브라우저를 클릭할 수도 있지만 LLM은 언어로 일하므로, 그 역량은 **CLI 인터페이스의 형태로** 주어져야 한다.

`.claude/skills/finviz`는 이미 한 번 이 잣대로 점검받았다. v1(PR #10, `91dee47`)은 본문은 통과했으나 모델이 받는 출력이 미달이어서(기본 출력이 헤더에 예산을 쓰고 깊이 5 이하를 생략해 `stock A`가 지표 84개 중 5개만 보였고, `catalog screen`이 304KB인데 검색 인자가 없었다) 성진은 전면 재작성을 택했다. v2(PR #13, `4637f9a`)는 목적별 `GROUP LEAF` 42리프 + 파서에서 파생하는 `schema`, "자르지 않고 선택 인자로 좁힌다"는 출력 계약으로 다시 쓰였고 코덱스 4단계 리뷰를 받았다.

이 세션은 **v2가 같은 잣대를 다시 통과하는지** 점검했다. SKILL.md·CLI 소스 1,648줄을 읽고, 격리 저장소에서 `--help` 3계층과 `schema` 35개, 42리프 중 40개를 **기본 옵션으로** 실행하고, 오류 10종과 각 리프가 낸 `too_large` 회복 문장을 **그대로 실행해** 따라갔다. 무료 기능 커버리지는 익명 요청으로 finviz.com의 내비게이션·스크리너 뷰·종목 탭을 열거해 대조했다. `sec` v1 점검(`.claude/plans/sec 스킬 4프레임 점검.md`)과 같은 잣대다.

v2 재작성의 코덱스 4단계 리뷰와 라이브 테스트 40건은 **정확성만** 판정했다. 합격 기준에 "기본 옵션으로 호출했을 때 답이 나오는가"가 없었다. `tests/finviz/test_live.py`는 큰 표면 대부분을 **미리 좁혀서** 호출하고 `status == "ok"`만 확인하므로, 기본 예산에서의 실패가 구조적으로 보이지 않는다. 결함은 거기서 나왔다.

**이 점검 자체도 독립 검증을 받았다.** 내 프레임이 낸 판정을 내 프레임으로 감사할 수 없으므로 코덱스 레인(`gpt-6-astra` high, read-only 격리, 실행 ID `20260919-011356-finviz-reaudit-ed69`)에 실측 장부와 프레임 판정을 주고 네 가지를 물었다: 내가 결함이라 부른 것 중 실제로는 이전 계획이 정당화한 설계 결정인 것, 내가 통과로 둔 것 중 실제 결함인 것, 층 진단이 맞는지, 성진이 고른 레버로 덮이지 않는 것. **내 판정 7건이 철회·축소됐고, 내가 통과로 둔 곳에서 결함 8건이 나왔으며, 내가 그은 층 경계가 너무 좁다는 지적을 받았다.** 아래 판정은 그 반영 후의 것이고, 무엇이 왜 철회됐는지는 "철회·축소한 판정"에 남긴다.

이 파일은 점검 세션의 유일한 산출물이다. 구현 파일은 바꾸지 않았다.

## 점검 결과 요약

| 프레임 | 본문(SKILL.md) | 인터페이스·출력 | 근거 |
|---|---|---|---|
| Principle over rail | 통과 | **결함 1건(C1)** | 본문 6개 절 전부 판단 이유가 있고 고정 순서가 없다. 기본 예산 20,000자에 이유와 상한이 없다. "큰 결과를 오류로 알리고 모델이 범위를 고른다"는 계약 자체는 이전 계획이 명시적으로 택한 것이고 정당하다 — 결함은 그 계약이 **약속한 선택이 듣지 않는 곳**에 있다. |
| Interface over document | **결함 2건(A2, A4)** | **결함 7건(A1, A6, G3, G4, G6, G7, G8)** | 본문이 라이브 카디널리티를 산문에 박아 3일 만에 어긋났고, argparse가 JSON 계약을 깨는 것을 본문이 대신 안내한다. 실패 메시지가 듣지 않는 좁히기를 이름 붙이고 듣는 것을 빠뜨린다. 입력 오류가 `too_large`에 가려진다. `--raw`는 슬라이스가 안 되고, 발견할 수 없는 인자값이 있고, `--fields`가 리프에 따라 다른 뜻이며, 중간 리디렉션 응답이 저장 약속을 어긴다. |
| For user not developer | 통과 | **결함 2건(F1, G9)** | 본문에 개발 이력이 없다. 개발자용 센티널 `"[]"`·`"{}"`가 리프 17개의 도움말 출력 키로 새어 나온다. 다중 목표의 `fix`가 목표 하나의 관측 id를 가리킨다. |
| Dense information | **결함 1건(G12)** | **결함 4건(D2, G2, G5, G11)** | 38줄이고 봉투는 0.2~1.5%로 이미 얇다(v1 결함 해소). 본문에 모든 경로가 읽는 분기별 회복 절차가 섞여 있다. 한 질문에 3회가 낭비되고, `read`가 `partial`을 잃고 해석 문맥을 잃으며, `data` **안쪽**에 중복이 있다. |
| **근거의 정직성** (네 프레임의 교차) | 통과 | **결함 1건(G1)** | 본문 L26이 "행을 받았다는 것이 선택자 적용을 증명하지 않는다"를 가르치는데, 달력 구현이 정확히 그 추론으로 `confirmed`를 준다. 본문이 금지한 것을 구현이 한다. |
| **잉여** (성진 추가 트랙) | 통과 | **결함 4건(S1~S4)** | 13그룹 42리프라는 개수와 `open`·`groups options`·`screen views`·`search`·`doctor`·`read`는 정당하다. 잉여는 항상 거절되는 인자 3개, 공유 옵션의 27%를 차지하는 전송 손잡이, 같은 페이지의 4회 중복 요청, `inspect`가 다시 세는 봉투 포인터다. |

**의도 정합성과 커버리지**: 달성됐다. 원 프롬프트가 이름 붙인 화면은 전부 명령으로 있고, 익명 finviz.com과 대조해도 **데이터 층에서 빠진 무료 화면이 없다**(아래 "커버리지 대조"). `conditions` 근거 기계·파서 파생 `schema`·3계층 도움말·자르지 않는 계약·얇은 봉투·전송 허용목록은 v2가 옳게 정한 것이다.

**미달은 한 곳이 아니다.** 첫 진단에서 나는 "선택·예산 층 한 곳"이라고 썼고 코덱스가 그 경계를 반박했다. 예산을 줄여도 남는 것이 셋 있다: **근거**(달력의 거짓 `confirmed`), **재생**(`read`가 `partial`과 해석 문맥을 잃고 `--raw`를 못 읽는다), **발견**(`market bubbles`의 네 축은 `help`가 "X field"이고 `choices`도 발견 명령도 없어 모델이 값을 만들어 낼 수밖에 없다). 그래서 보완 범위는 **선택 + 발견 + 근거 + 재생 계약**이다.

## 실측 사실 장부 (2026-09-18~19, 격리 저장소, 익명, 기본 옵션)

| 항목 | 실측 |
|---|---|
| 번들 | SKILL.md 38줄 / 5,824자, `scripts/` 8모듈 1,648줄, `references/` 없음, 테스트는 레포 `tests/finviz/`(78함수) |
| `validate_harness.py --path .` | **errors 0 / warnings 0** (v1의 4E/1W 해소) |
| `--help` 3계층 | 루트 3,180자에 그룹 13개 + 공유 옵션 8개 전부 설명·기본값. 그룹 도움말이 리프를 열거. 리프 42개 전부 description, 모든 플래그에 `help`·`default`, 닫힌 선택지에 `choices` |
| stderr | `-q --frozen`으로 **모든 호출에서 0바이트** (v1의 설치 로그 해소) |
| `schema` | 무인자 8,120자(sec는 20,249), 그룹 736~1,836자, 리프 35개 1,967~4,196자. 파서에서 파생 |
| `schema` 리프 구성 | `stock snapshot` 2,216자 중 리프 고유는 390자(18%). 공유 옵션 1,180자 + `statuses`·`exit_codes` 389자가 35개 리프에 동일하게 반복 |
| 봉투 대 데이터 | 큰 응답 10건에서 봉투 353~922자 = **0.2~1.5%**. 데이터가 98.5~99.8% |
| **기본 옵션 실패** | 42리프 중 **11개 `too_large`**: `screen filters`(208,728자) `stock news`(23,737) `stock options`(24,101) `stock flows`(49,644) `market quotes`(140,472) `market map`(44,836) `market bubbles`(73,240) `calendar economic`(29,756) `calendar season`(33,520) `news headlines`(44,387) `insiders trades`(95,193) |
| 한도 1.5% 이내 | `stock short-interest` 19,742 / `stock filings` 19,916 |
| 직접 좁히기 구제 | 11개 중 **9개는 리프 자신의 인자로 구제된다**: `stock news --limit 20`(5,389) `stock options --limit 20`(7,952) `stock flows --limit 20`(1,639) `market bubbles --limit 20`(3,827) `calendar economic --limit 20`(7,698) `calendar season --limit 20`(8,561) `news headlines --limit 40`(10,676) `insiders trades --limit 20`(9,700) `market map --performance-only`(7,063) |
| **회복 문장 사망** | 각 리프의 `fix`를 **그대로 실행**했을 때 `too_large`가 다시 나오는 것은 **3개**: `screen filters`(`/data`, 다섯 오프셋 전부) `market quotes futures`(`/data`) `market map`(`/data`) |
| 사망 원인 | `--limit`은 레코드 수를 세는데 이 셋의 크기 축은 다르다. `screen filters`는 옵션 목록(`etf_tags` 한 레코드가 28,193자, 옵션 537개)이고, `market quotes`는 레코드당 `sparkline`(20종목 × 약 2,380자 = 47,600자)이며, `market map`은 키 4개짜리 dict(`nodes`·`subtype`·`version`·`hash`)라 `--limit 20`이 no-op이다 |
| 정정 기록 | 첫 측정에서 사망을 5개로 적었다. `calendar economic`·`season`의 `fix`는 `/data/items`를 가리키는데 내가 `/data`를 넣어 실행한 것이 원인이었다. 코덱스 지적으로 재측정해 정정했다 |
| 듣지만 광고되지 않는 경로 | `screen filters --fields id,label` = **4,247자 1회로 88개 전부**, `--fields id,label,definition` = 14,408자. 그런데 `screen filters`의 `narrowing`은 `['--filter','--limit']`뿐이라 `fix`가 `--fields`를 이름 붙일 수 없다 |
| 큰 옵션 목록 도달성 | `read ID --pointer /data/86/options --limit 100` = 5,156자로 **도달 가능**(무한정은 아님). `--limit` 없이는 `too_large`. 번거롭지만 막혀 있지는 않다 |
| `--fields` 오류 마스킹 | `stock options A --fields bogus` → `invalid_fields`가 아니라 `too_large`(24,355자). `--max-chars 40000`을 주면 사용 가능한 21개 필드명을 열거하는 정확한 진단이 나온다. `finalize()`가 오류 결과에도 `data`를 남겨 문서가 예산을 넘고, `emit()`이 입력 오류를 `too_large`로 덮으며 그 `fix`가 방금 잘못 쓴 `--fields`를 다시 권한다 |
| `--fields`의 두 가지 뜻 | `market quotes futures --fields label,last,change` → **`too_large`**. `records=None`이고 데이터가 티커→시세 dict라 `--fields`가 *어느 종목*을 고르며, 도움말은 "record fields to keep"이라고 쓴다. 같은 리프에서 `--limit 5`(12,627)·`--filter AUD`(2,978)는 듣는다 |
| `sparkline` | `market quotes`가 악기마다 300점 배열 + `sparklineDateChanges`를 싣는다. futures 139,965자 중 **126,394자(90.3%)**, forex 91%, crypto 90%. 빼면 futures는 13,571자 |
| **`read --raw` 사망** | 139,970바이트 원자료에 `--raw`, `--raw --start 0 --limit 20`, `--raw --limit 5` **전부 `too_large`**. `--start`/`--limit`은 컨테이너만 자르고 `--raw`는 문자열 하나다. 예산을 넘는 원자료를 읽을 경로가 없다 |
| 다중 목표 | `stock snapshot` 티커 1개 8,382자 / **3개 25,194자로 오류** / 6개·10개도 오류. `stock forecast`도 3개에서 오류. 나머지 stock 리프는 3개에서 통과(`profile` 4,703, `ratings` 8,890, `dividends` 14,448, `statement` 12,053, `prices` 11,680). `fix`가 이름 붙인 `--limit 20`(6,870)·`--filter P/E`(2,001)는 실제로 듣는다. 다만 `fix`의 `read` 문장이 세 관측 중 **하나의 id**를 가리켜 비교가 아니라 한 종목만 준다 |
| 달력 근거 | `feeds.py:59`가 `confirmed if dates[0][:10] >= args.date`로 판정한다. `--date 2026-09-19`(오늘) → `confirmed`, 근거 `{"earliest_item":"2026-09-19T16:30:00"}`. 미래 날짜는 `unverified`. **응답의 `date_from` 에코가 이미 출력에 있는데 근거로 쓰이지 않는다.** `tests/finviz/test_feeds.py:115`가 이 추론을 고정한다 |
| `read`의 상태 | `read` 리프가 `result["status"] = "ok"`를 하드코딩하고 `saved["status"] == "error"`만 경고로 특수 처리한다. `partial`·`empty`는 읽어올 때 `ok`가 되고 종료 코드도 0이 된다. `output`의 계약은 "status of the original observation are repeated"라고 쓴다 |
| 발견 불가한 인자값 | `market bubbles`의 `--x`·`--y`·`--size`·`--color`는 `help`가 각각 "X field"·"Y field"·"Size field"·"Color field"이고 `choices`도, 값을 알려 주는 발견 명령도 없다. `screen run --sort`·`insiders trades --sort`는 "column header links"의 키를 요구하는데 정상 출력에 그 키가 없다 |
| 개발자 센티널 노출 | 리프 17개의 `--help` epilog가 `Output keys: [].`를 낸다(`search` `screen filters` `screen signals` `screen views` `stock ratings/news/flows/short-interest` `groups performance` `market bubbles` `insiders trades` `news headlines` `inspect` 등). `screen run`은 `Output keys: id, [], conditions, coverage, continuation.`, `market quotes`는 `"{}"`. 레코드 모양은 `schema`에 있으나 도움말에서 사라진다 |
| 기본 범위 | `default_limit`은 `stock earnings`(40) 하나. 다만 다른 방식의 기본 범위는 있다 — `stock options`는 만기 1개, `stock prices`는 30봉, `screen run`은 1페이지 |
| `--max-chars` | 기본 20,000, **상한 없음**, 이유가 코드·도움말·schema·본문 어디에도 없다 |
| 에코된 `--max-chars` 재실행 | 정확히 성공(`23737` → 23,737바이트). 자리수 변화까지 수렴한다. **결함 아님** |
| `conditions`(스크리너) | `--filters cap_bogus` → `not_applied`, `coverage.source_total 11655`. 실제 필터 → `confirmed` + 페이지 컨트롤 근거. `--columns 1,6,7` → `confirmed` + `['ticker','marketCap','PE']`. **정확하다** |
| 오류 계약 | 10종 중 9종이 `code/message/fix`와 등급 종료 코드(404→`http_error` 6, 외부 URL→`unsupported_url` 2, 미지원 경로→`unsupported_route`, 없는 id→`unknown_id`, `schema nosuchgroup`→`invalid_scope`, `calendar economic --page 3`→`invalid_argument`). 정직하고 복구 가능 |
| argparse 오류 | `stock nosuchleaf`·`--dataset nope`는 stdout이 비고 stderr에 usage, exit 2. 모듈 docstring의 "one JSON document on stdout"과 어긋난다. `sec`(`sec.py:10-12`)·`yfinance`(`yfinance_cli.py:39-45`)는 봉투로 보낸다 |
| `stock snapshot A` | 84지표 전부(`shown=84`), `EPS next Y`가 정의 둘과 함께 두 번. 8,382자. **v1 결함 해소** |
| 본문 대비 라이브 | SKILL.md:18 "the filter list alone is 87 controls" vs 실측 **88**(`coverage.received`) |
| zsh 함정 | 명령을 변수 하나에 담으면 zsh가 분할하지 않아 실행 안 됨(이 세션에서 두 번 재현). `sec`·`yfinance` SKILL.md에는 이 문장이 있고 **finviz에는 없다** |
| description | 845자. 한국어 트리거와 근접 거절(yfinance·sec·코드 작성)을 갖췄다 |
| `docs/usage.md:140-146` | 존재하지 않는 `collect` 명령을 설명하고, 재작성이 버린 `--isolated` 호출형을 예시로 들고, "terminal output is a preview"라고 쓴다(프리뷰는 없다). 같은 줄이 "The CLI owns the current command and data catalog"라고 주장한다 |
| 번들 잔여물 | 소스 없는 `scripts/__pycache__/html.cpython-313.pyc`(재작성이 지운 모듈), 빈 `tests/finviz/fixtures/`와 살아 있는 접근자 `conftest.py:37-40` |

## 커버리지 대조 (익명 요청, 2026-09-19)

원 프롬프트의 "무료 기능은 모두"를 실제 사이트와 대조했다. **데이터 층에서 빠진 화면은 없다.**

| 표면 | 사이트가 제공 | CLI가 덮는 것 | 판정 |
|---|---|---|---|
| 상단 내비게이션 | screener, map, news, groups, insidertrading, futures, forex, crypto, calendar, portfolio, elite | 앞의 9개 + bubbles + stock/quote. `portfolio`는 로그인, `elite`·`api-and-exports`는 유료 | **완전**. 제외된 둘은 선언된 범위 밖이다 |
| 스크리너 뷰 | 17개(`v=` 110·111·121·131·141·151·161·171·181·191·211·311·321·341·351·411·711) | 표 뷰 9개(overview·valuation·ownership·performance·financial·technical·etf·etf-performance·custom) | **실질 완전**. 211 Charts·311 Basic·341 Snapshot·351 TA는 차트 이미지 10개씩 실측돼 "시각 렌더링 제외" 결정에 맞고, 711 Maps는 `market map`이, 411 Tickers는 `screen run --fields ticker`(20행 1,125자)가 덮는다. **321 News만 유일한 논쟁거리** — 스크린된 집합의 뉴스이고 텍스트 표를 갖지만 차트 이미지도 10개 있다 |
| 종목 탭 | 7개(`ty=` c·dv·ea·fc·lf·oc·si) + `rv` | 16리프가 8개 탭 전부 | **완전** |
| 그룹 뷰 | 표 5개 + 차트 4개 | 표 5개 | **완전** |
| 맵·버블·시장·일정·뉴스·내부자 | — | `market map`(15종)·`bubbles`·`quotes`/`performance` 3종·`calendar` 4종·`news` 3종(`headlines` 5종)·`insiders trades` | **완전** |

`screen` `v=321`(스크린 집합의 뉴스)을 덮을지는 보완 작업 8번의 선택 항목으로 남긴다. 나머지는 성진의 목표가 달성돼 있다.

## 잉여 점검 — 불필요한 것이 필요한 것을 희석하는가

성진의 지적으로 추가한 트랙이다. 앞의 결함들은 "필요한 것이 닿는가"를 물었고, 이 절은 반대 방향 — **인터페이스에 모델이 쓸 이유가 없는 것이 있어서 쓸 것을 고르기 어려워지는가** — 를 묻는다. `dense information`과 `for user not developer`가 데이터가 아니라 인터페이스 자체에 적용되는 질문이다.

**먼저 잉여가 아닌 것.** 13그룹 42리프라는 **개수 자체는 정당하다.** "무료 기능 모두"가 명시된 목표이고, 모델은 42개를 한 번에 보지 않는다 — 루트 `--help`가 그룹 13개를 목적 한 줄씩 주고 각 그룹 도움말이 자기 리프만 열거하는 2계층이라, 한 결정에 놓이는 선택지는 13개 또는 한 그룹의 1~16개다. 개수에 맞는 구조가 있다. `open`도 잉여가 아니다 — `open https://finviz.com/stock?t=A&ty=c`는 오류이므로 타입 명령과 겹치지 않고, 붙여 준 URL이라는 고유한 진입점을 맡는다. `groups options`(3,203자)도 잉여가 아니다: `groups table --group`의 `choices`가 `None`이므로 그룹 식별자를 주는 유일한 경로다. `screen views`(1,288자)는 `--view`의 `choices`가 이미 이름 9개를 주므로 이름은 중복이지만 뷰마다 어느 열이 오는지를 더하고, 그 설명이 뷰 선택의 실제 근거다 — 유지한다. `search`·`doctor`·`read`는 각자 하나뿐인 역할이 있다.

**잉여로 확정한 것 넷.**

### S1. 항상 거절되는 인자를 도움말이 광고한다 — `scripts/feeds.py:16,27-30`

`CALENDAR_ARGS` 하나를 달력 4리프가 공유해서, `calendar season --help`가 `--date`·`--page`·`--sort`를 광고하고 **셋 다 `invalid_argument`로 항상 실패한다.** `calendar economic --page`도 마찬가지다(`--sort`는 듣는다). 도움말 문장이 그 거절을 스스로 설명한다 — "Not accepted by season", "rejected by economic and season". 모델이 읽는 자리에 **구현의 편의(한 `calendar()` 함수, `CALENDAR_PATHS` 루프)가 그대로 노출돼** 있고, 그 대가로 리프 하나에 쓸 수 없는 선택지 3개가 붙는다. 각 리프가 자기가 받는 인자만 갖게 하면 도움말의 거절 설명도 함께 사라진다.

### S2. 전송 조율 플래그가 모든 리프의 계약에 실린다 — `scripts/finviz.py:31-40`

공유 옵션 8개 1,192자 중 `--connect-timeout`(108자)·`--timeout`(101자)·`--max-bytes`(109자) **318자(27%)는 운영자 손잡이**다. 모델이 Finviz 질문에 답하려고 연결 타임아웃을 바꿀 이유는 없다. 이 셋이 루트 `--help` 최상단과 **리프 35개의 `schema`에 매번** 실려(1,192자 × 35 ≈ 41,700자) 선택 층(`--max-chars`·`--filter`·`--fields`·`--limit`, 693자)과 같은 무게로 보인다. 환경 변수나 `doctor`가 보고하는 값으로 내리고 도움말에서는 이름만 남기거나 빼면, 모델이 보는 공유 옵션은 "출력을 어떻게 좁히는가" 넷과 `--store`가 된다.

### S3. 같은 페이지를 여러 번 받는다 — `scripts/stock.py:37-107`

`snapshot`·`profile`·`ratings`·`news`·`insiders`·`ownership` 여섯 리프의 `source.url`이 전부 `https://finviz.com/stock?t=A&ty=c`로 **동일하다.** "이 회사 좀 봐줘"에 개요·뉴스·내부자·등급을 보면 같은 페이지를 네 번 받는다. 리프를 절별로 나눈 것 자체는 밀도 이득이다(물어본 표만 온다) — 잉여는 명령이 아니라 **요청**이다. 저장소가 이미 그 페이지를 갖고 있으므로, 추출기를 저장된 관측에 대해 돌릴 수 있게 하면(G3의 `--raw` 범위 읽기와 같은 뿌리) 네 번이 한 번 + 세 번의 지역 추출이 된다. 사람은 페이지를 한 번 열고 표 네 개를 읽는다.

### S4. `inspect` 출력의 대부분이 모델이 이미 아는 포인터다 — `scripts/finviz.py:156`

`inspect`는 2,903자를 쓰는데 앞쪽이 `/id`·`/observed_at`·`/source/url`·`/source/http_status`·`/source/redirects`·`/status` 같은 **봉투 포인터**다. 이것은 `schema`의 `envelope`가 이미 소유한 지식이다. `inspect`의 고유 가치는 `/data/...` 아래의 동적 구조(`route-init-data` 계열은 리프마다 모양이 다르다)이고, 그것만 내면 명령이 하는 일이 분명해진다. 제거 후보가 아니라 범위 후보다.

## 확정 결함

### A1. 실패 메시지가 구현과 어긋난다 — `scripts/output.py:143-148`, 리프별 `narrow=`

`too_large_fix()`가 리프의 손으로 적은 `narrow` 목록을 그대로 읽는다. `screen filters`에서 그 목록은 `--filter, --limit`인데 `--limit 20`은 실패하고(하한이 `--limit 5`), 목록에 없는 `--fields id,label`이 1회 4,247자로 88개 전부를 준다. 같은 함수가 붙이는 `read ID --pointer … --start 0 --limit 20`은 `screen filters`·`market quotes`·`market map`에서 같은 `too_large`를 낸다. "Help text and failure messages must agree with the implementation"의 정면 위반이고, yfinance가 `f3ded99`에서 이미 고친 결함("too_large가 들을 수 없는 좁히기를 권했다")이 여기 남아 있다.

### A2. 본문이 라이브 카디널리티를 산문에 박았다 — `SKILL.md:18`

"the filter list alone is 87 controls"는 실측 88이다. 3일 만에 어긋났고, 같은 수치를 `screen filters`의 `coverage.received`가 매번 정확히 보고한다.

### A4. 본문이 인터페이스의 불일치를 대신 안내한다 — `SKILL.md:14`

"JSON errors carry a `fix`; argument-parser errors instead print usage on stderr and exit 2." 모듈 docstring은 "one JSON document on stdout"을 약속한다. argparse 실패를 봉투로 보내면 이 문장이 필요 없어진다(`sec`·`yfinance` 선례).

### A6. 입력 오류가 `too_large`에 가려진다 — `scripts/output.py:139`, `:156-160`

`finalize()`의 마지막 줄이 `ordered` 열거로 `data`를 되살려, 오류 상태의 결과가 만들지 못했다고 말한 페이로드를 그대로 싣는다. 그 문서가 예산을 넘으면 `emit()`이 진짜 오류(`invalid_fields`)를 `too_large`로 덮고, 그 `fix`가 방금 잘못 쓴 `--fields`를 다시 권한다. 진단은 있는데 기본 예산에서 닿을 수 없다.

### C1. 기본 예산 20,000자에 이유가 없다 — `scripts/finviz.py:32`

왜 20,000인지, 어떤 조건에서 다른 값이 맞는지가 없고 상한도 없다. "Numbers need a reason and the conditions under which another value is right." 성진 결정으로 **값은 20,000 그대로 두고 이유 문장만 `schema.shared_options`에 남긴다.** 리프별 기본 범위가 출력 크기를 결정하게 되면 예산은 구속 조건이 아니라 안전 경계가 되고, 그것이 그 문장의 내용이다. 호스트 잘림 지점에서 계산한 상한은 이번 범위에 넣지 않는다.

### D2. 한 질문의 호출 수 — 실측

"핀비즈에서 시가총액 큰 기술주" 경로: `screen filters`(실패) → `fix`대로 `--limit 20`(실패) → `fix`대로 `read … --limit 20`(실패, 다섯 오프셋 전부) → 광고되지 않은 `--fields id,label`을 스스로 찾아야 1회. **3회 낭비 후에도 인터페이스는 다음 제안을 갖고 있지 않다.** 사람은 스크리너 페이지를 한 번 보고 라벨 88개를 읽는다.

### F1. 개발자 센티널이 모델 도움말로 새어 나온다 — `scripts/finviz.py:223-224` + 리프 17곳의 `output={"[]": …}`

`epilog()`가 `", ".join(item.output)`로 키 이름만 잇는다. `"[]"`는 "데이터가 dict가 아니라 리스트"라는 구현 표식인데 출력에서는 `Output keys: [].`가 되어 아무것도 알려주지 않는다.

### G1. 근거가 근거가 아니다 — `scripts/feeds.py:59`, `tests/finviz/test_feeds.py:115`

달력이 "반환된 첫 항목 날짜 ≥ 요청일"이라는 **추론**으로 `date`를 `confirmed`로 만든다. 원천이 `dateFrom`을 무시하고 늘 오늘 이후를 돌려줘도 이 술어는 참이므로, 적용과 무시를 구별하지 못한다. SKILL.md:26은 "행을 받았다는 것이 선택자 적용을 증명하지 않는다"를 가르치고 스크리너 구현은 페이지 자체 컨트롤의 에코를 읽는다. **본문이 금지한 추론을 한 구현이 하고 있고, 테스트가 그것을 고정한다.** 정직한 근거는 이미 출력에 있는 원천의 `date_from` 에코다.

### G2. `read`가 원본 상태를 잃는다 — `scripts/finviz.py`(read 리프)

`result["status"] = "ok"`가 하드코딩돼 있고 `saved["status"] == "error"`만 경고로 특수 처리한다. `partial`(사용 가능한 데이터에 기록된 공백이 있음)·`empty`가 읽어올 때 `ok`가 되고 종료 코드도 8·7 대신 0이 된다. 같은 리프의 `output` 계약은 "status of the original observation are repeated"라고 쓴다. `read`는 11개 실패 리프의 **광고된 회복 경로**이므로, 회복이 인식론적 공백을 세탁한다.

### G3. 저장된 원자료를 읽을 방법이 없다 — `scripts/finviz.py`(read 리프의 `--raw`)

`--raw`는 문자열 하나를 돌려주고 `--start`/`--limit`은 컨테이너만 자른다. 139,970바이트 원자료에 어떤 조합을 줘도 `too_large`다. 예산을 넘는 원자료 — 즉 `--raw`가 필요한 유일한 경우 — 를 읽을 경로가 없다. 이것이 "명령 출력에서 빼도 저장소가 보존하므로 손실이 아니다"의 전제를 무너뜨린다.

### G4. 발견할 수 없는 인자값 — `scripts/markets.py:164`, `scripts/screener.py:89`, `scripts/feeds.py:160`

`market bubbles`의 `--x`·`--y`·`--size`·`--color`는 `help`가 "X field"·"Y field"·"Size field"·"Color field"이고 `choices`도, 값을 알려 주는 발견 명령도 없다. 기본값(`sector`·`lastChange`·`marketCap`·`sp500`) 외의 축을 쓰려면 모델이 이름을 만들어 내야 한다. `screen run --sort`·`insiders trades --sort`는 "column header links"의 키를 요구하는데 정상 출력에 그 키가 없다. **리프 42개가 이름을 갖는 것이 모델이 유효한 요청을 조립할 수 있다는 뜻은 아니다.** 닫힌 선택지에 `choices`를 붙인 다른 인자들과 대비된다.

### G5. 슬라이스가 해석 문맥을 잃는다 — `scripts/finviz.py`(read 리프), `scripts/stock.py:212`

`read --pointer /data/items`류가 형제 필드를 남기지 않는다. 재무제표에서 항목만 떼면 기간 목록과 통화가 사라지고, 특례는 부모의 literal `unit` 하나뿐이다. 값은 "7,372.00" 같은 원천 문자열이므로 기간과 통화 없이는 해석할 수 없다.

### G6. 같은 플래그가 리프에 따라 다른 뜻이다 — `scripts/output.py:86-119`, `scripts/markets.py:72`

`--fields`의 도움말은 "Comma-separated record fields to keep"인데, `records=None`이고 데이터가 dict인 리프(`market quotes`)에서는 **최상위 키(어느 종목)**를 고른다. 그래서 `market quotes futures --fields label,last,change`가 `too_large`다. `narrow` 목록이 `--fields`를 이름 붙이고 있어 모델이 이 경로로 유도된다.

### G7. 저장 약속을 어기는 응답이 있다 — `scripts/transport.py:153`, `scripts/output.py:19`

봉투 계약은 모든 수신 응답이 저장된다고 쓰지만, 리디렉션 체인의 성공한 중간 응답은 버려진다. 거절된 리디렉션은 저장된다.

### G8. 대체 오류 문서가 예산 검사를 받지 않는다 — `scripts/output.py:156-160`

`emit()`이 `too_large` 오류 문서를 만들어 바로 출력한다. 목표가 많고 id·fix가 길면 그 문서 자체가 예산을 넘을 수 있고, 그때는 아무 경계도 남지 않는다.

### G9. 다중 목표의 회복 문장이 목표 하나를 가리킨다 — `scripts/output.py:145`

`too_large_fix`가 `ids[0]`만 쓴다. `stock snapshot AAPL MSFT NVDA`가 실패하면 `read <AAPL의 id>`를 권하므로, 따라간 모델은 비교가 아니라 한 종목을 얻는다.

### G11. 밀도는 `data` 안쪽에도 있다 — `scripts/markup.py:108`, `scripts/feeds.py:220`

기사 읽기가 단락 목록과 전문을 함께 싣고, 일반 `open`이 같은 본문을 links·tables·초기 데이터에 다시 실을 수 있다. 봉투가 0.2%라도 `data`의 절반이 같은 텍스트면 밀도는 낮다. 이 항목은 코덱스가 소스에서 지적한 것이고 내가 실측하지 않았다.

### G12. 본문이 분기별 절차를 모든 경로에 싣는다 — `SKILL.md:14,18,38`

`read --pointer/--start/--limit`의 조작법, `/data/records`가 중첩 목록을 자르지 않는다는 사실, `--pages/--out` 수집 기전, argparse 예외는 **특정 경로에서만 필요한 운영 계약**인데 38줄 본문에 있어 모든 호출이 읽는다. 본문의 의미 구분(라벨 모호성, 조건 적용의 인식론, `observed_at`과 시장 시각의 차이, 스킬 경계)은 판단이고 남아야 한다.

## 경미한 항목 (권고안에 포함)

- E1. zsh 함정 한 문장이 없다. `sec`·`yfinance` 문구를 그대로 넣는다. 이 세션에서 두 번 재현했다.
- E2. `schema` 리프 응답의 82%가 35개 리프에 동일한 공유 옵션·`statuses`·`exit_codes`다. 리프 고유는 390자다.
- E3. `docs/usage.md:140-146`이 없는 `collect`, 버린 `--isolated` 호출형, 없는 "preview"를 설명한다. 모델이 읽는 표면은 아니지만 인터페이스의 산문 사본이 드리프트한다는 증거다.
- E4. 번들 잔여물: 소스 없는 `scripts/__pycache__/html.cpython-313.pyc`, 빈 `tests/finviz/fixtures/`와 살아 있는 접근자 `conftest.py:37-40`.
- E5. positional metavar이 섞여 있다(`search`는 `query`, `stock snapshot`은 `TICKER`).

## 철회·축소한 판정 (코덱스 `20260919-011356-finviz-reaudit-ed69`)

내 첫 판정 중 다음은 프레임 오적용이거나 이전 계획이 정당화한 결정이었다. 다음 세션이 이것을 다시 결함으로 읽지 않도록 이유를 남긴다.

- **C2 "리프 42개 중 1개만 기본 범위를 갖는다" — 철회.** 이전 계획이 "프리뷰를 버리고 `too_large` + 모델이 고른 범위"를 명시적으로 택했고 합격 기준에 큰 스크리닝·revisions 결과를 의도적으로 넣었다. `default_limit`의 부재가 기본 범위의 부재가 아니다 — `stock options`는 만기 1개, `stock prices`는 30봉, `screen run`은 1페이지다. 리프별 기본 범위는 **성진이 이번에 새로 택한 설계 변경**이고, 프레임이 이전에 요구한 것이 아니다.
- **C3 "중첩 dict라 `--limit`이 안 듣는다" — 축소.** 달력은 `records="items"`, 옵션은 `records="contracts"`로 이미 지정돼 있어 `--limit`이 듣는다. 실제로 축이 안 맞는 것은 `screen filters`의 옵션 목록, `market quotes`의 레코드별 `sparkline`, `market map`의 키 4개 dict 셋이다. 내가 `fix`의 포인터 대신 `/data`를 넣어 실행한 것이 오진의 원인이었다.
- **A3 "본문이 파서가 소유한 인자를 다시 적는다" — 대폭 축소, G12로 대체.** "본문에 플래그 이름을 적지 않는다"는 내가 발명한 레일이다. harness-creator 문서는 유용한 예시와 필요한 예외를 명시적으로 보호하고, yfinance SKILL.md도 `--limit`을 적는다. 남는 것은 **절차의 사본**(G12)이고, `observed_at` 대 시장 시각, 추정 대 확정 실적일 같은 판단을 담은 언급은 남아야 한다.
- **A5 "`schema`의 출력 계약이 실제와 어긋난다" — 철회.** "as published, including extra source fields"는 구현을 정확히 기술한다. 거짓이 아니라 정보가 부족한 계약이고, 원천 값 보존은 이전 계획의 명시적 결정이었다.
- **F2 "모델이 읽을 수 없는 렌더링 데이터" — 근거 철회, 조치 유지.** 300점 수치 이력은 렌더링 없이도 분석에 쓸 수 있으므로 "모델이 못 읽는다"는 근거가 틀렸다. `sparkline`을 기본 출력에서 빼는 것은 **새 표현 결정**이고 정당하지만, 보존을 위반했다는 증명은 아니다. 그리고 그 결정은 G3(원자료를 읽을 경로)이 함께 고쳐질 때만 무손실이다.
- **F3 "`narrow` 목록이 손으로 유지된다" — 구조적 지적 철회.** 파서는 어떤 플래그가 존재하는지 알지만 어떤 플래그가 *이 페이로드*를 줄이는지는 모른다. 의미 선언은 정당하고, 잘못된 선언은 A1이다. `stock options --fields`는 `contracts`에 실제로 듣고 `bid`/`ask`는 정말 없는 이름이며 올바르게 검출된다 — 문제는 A6의 마스킹뿐이다.
- **D1 "오류 결과가 데이터를 싣는다" — 축소.** 이전 계획이 `array_alignment` 오류에서 원본 배열을 진단용으로 남기기로 했다. 모든 오류에서 데이터를 없애면 그 결정을 뒤집는다. 남는 것은 **선택되지 않은·무관한 페이로드의 누출**이고 A6이 그 사례다.

## 네 프레임이 이 보완에서 결정하는 것

첫 초안을 같은 프레임으로 다시 점검했다. 아래 원칙이 각 항목의 형태를 결정하고, 숫자는 원칙에서 계산한 결과만 쓴다.

- **principle over rail → "기본값은 사람이 한 번 보는 것, 전수는 옵트인."** 출력 크기는 모델이 고른 범위의 결과여야 한다. 그런데 "모델이 고른 범위"가 성립하려면 **고를 수 있는 것이 무엇인지 아는 첫 호출**이 성공해야 한다. 그래서 리프마다 기본값을 "그 화면을 한 번 본 사람이 아는 것"으로 정하고, 전수는 인자로 요청한다. 예산은 그 결과를 검사하는 안전 경계로 물러나며 값을 바꾸지 않는다. 기본값이 **잘라낸 것이라는 사실은 `coverage`가 매번 말한다**(`received` 대 `shown`) — 침묵하는 절단은 여전히 금지다.
- **interface over document → "도구가 소유하는 지식은 도구가 말하고, 실패 메시지는 실제로 듣는 것만 이름 붙인다."** `narrow` 선언은 유지하되 **그 선언이 실제로 예산 안에 들어오게 하는지를 테스트가 고정한다.** 닫힌 선택지에는 `choices`를, 열린 식별자 집합에는 발견 명령을 준다. 같은 플래그 이름이 리프마다 다른 뜻이면 이름을 나눈다. 산문에서 빠지는 것은 절차의 사본이고, 판단은 남는다.
- **for user not developer → "모델이 읽는 자리에 구현 표식도, 쓸 수 없는 선택지도 두지 않는다."** `"[]"`·`"{}"` 같은 센티널은 모양을 말하는 문장으로 바꾼다. 다중 목표의 회복 문장은 목표 전체를 가리킨다. 오류 `code`와 `warnings` 값은 모델이 그대로 읽고 판단할 짧은 이름이어야 한다. **그리고 어느 리프의 도움말에도 그 리프가 거절할 인자를 싣지 않는다** — 인자 목록을 리프끼리 공유하는 것은 구현의 편의이고, 그 편의를 모델의 선택지로 청구하지 않는다(S1).
- **dense information → "같은 것을 두 번 싣지 않고, 뗀 것의 문맥은 함께 간다."** 슬라이스는 해석에 필요한 형제 필드를 데리고 가고, 기사 본문은 한 번만 실린다. 그리고 **잘라낸 데이터의 상태는 잘라내도 살아 있어야 한다** — `read`가 `partial`을 `ok`로 만들지 않는다. 같은 원칙이 인터페이스에도 적용된다: 같은 페이지를 네 번 받지 않고(S3), 모델이 이미 아는 포인터를 다시 세지 않고(S4), 운영자 손잡이를 선택 인자와 같은 무게로 놓지 않는다(S2). **명령을 줄이는 것이 목표가 아니다** — 42리프는 목표가 요구하는 커버리지이고, 잉여는 개수가 아니라 쓸 수 없는 선택지와 중복된 비용이다.

## 보완 작업 (성진 결정: 선택 + 발견 + 근거 + 재생 계약. 전면 재작성은 하지 않는다)

바꾸는 파일은 `scripts/output.py`(선택·오류·예산), `scripts/finviz.py`(read 계약·epilog·예산 문장), `scripts/feeds.py`(달력 근거·뉴스 기본 범위·기사 중복), `scripts/markets.py`(quotes 필드·bubbles 발견·map 기본 범위), `scripts/screener.py`(filters 기본 범위·sort 발견), `scripts/stock.py`(다중 목표 기본값·statement 문맥), `scripts/transport.py`(리디렉션 저장), `SKILL.md`, 그리고 `tests/finviz/`다. `scripts/markup.py`는 G11에서만 닿는다. **디렉터리 구조와 명령 구조(13그룹 42리프), `@leaf` 레지스트리, 파서 파생 `schema`, 3계층 도움말, 전송 허용목록, 관측 저장소는 그대로다.**

각 항목은 `tdd` 스킬로 공개 CLI seam(`tests/finviz/test_cli.py`·`test_screen.py`·`test_stock.py`·`test_feeds.py`·`test_schema.py`, 픽스처 빌더 `tests/finviz/pages.py`)에 재현 테스트를 먼저 쓰고 통과시킨다. 트래커는 `TaskCreate`로 열고 아래 완료 판정을 그대로 적는다.

1. **근거를 근거로 (G1)** — 가장 먼저. 달력의 `date` 조건을 원천의 `date_from` 에코와 요청값의 비교로 판정한다: 같으면 `confirmed`(근거 `{"source_date_from": …}`), 다르면 `not_applied`, 에코가 없으면 `unverified`. 반환된 항목 날짜로 추론하지 않는다. `tests/finviz/test_feeds.py:115`의 기존 테스트는 이 추론을 고정하고 있으므로 새 계약으로 고쳐 쓴다. **완료 판정**: `dateFrom`을 무시하고 오늘 이후를 돌려주는 픽스처에 대해 `not_applied`가 나오는 재현 테스트가 통과하고, 스크리너·그룹·옵션·맵의 기존 `conditions` 경로는 변경 없이 통과한다.

2. **재생이 상태와 문맥을 보존한다 (G2, G5, G3)** — `read`가 `saved["status"]`를 그대로 싣고 종료 코드도 그것을 따른다(`partial`→8, `empty`→7). `error`는 현재의 경고를 유지한다. `/data/...` 하위를 가리킨 슬라이스는 해석에 필요한 형제 스칼라(재무제표의 `currency`·기간 목록, 기존 `unit` 특례를 일반화)를 `selection.context`로 함께 낸다. `--raw`에 문자 범위 인자를 단다(`--raw --chars A-B`, sec의 `--rows`·`--position/--end`와 같은 계열). **완료 판정**: `partial` 관측을 `read`하면 `partial`과 exit 8이 나오고, `market quotes futures`의 139,970바이트 원자료가 기본 예산에서 문자 범위로 완독 가능하며(139,970 ÷ 20,000 → 7회 이상), 재무제표 항목 슬라이스가 통화와 기간을 갖는다.

3. **리프별 기본 범위 (C2를 설계 변경으로, D2)** — 기본값을 "그 화면을 한 번 본 사람이 아는 것"으로 정하고 전수는 인자로 요청한다. `screen filters`는 옵션 없는 `{id, label, definition}` 목록(실측 14,408자)이 기본이고 `--options`로 옵션을 붙이거나 `--filter`로 한 필터를 받는다. `insiders trades` 20행, `news headlines` 40건(단, 페이지의 섹션·출처 구분을 보존해 앞에서 자르지 않는다), `market bubbles`는 `--index`의 대표 집합을 명시적 의미로 자른다, `market map`은 성과 요약이 기본이고 분류 트리는 `--classification`으로 옵트인하며 하위 트리를 포인터로 고른다, `calendar season`은 `items`와 함께 `totals_per_day`도 범위 안에 든다, `stock flows`는 **최신** 창이 기본이다(현재 접두 자르기는 가장 오래된 것을 준다). `coverage`가 매번 `received` 대 `shown`으로 잘라낸 사실을 말한다. **완료 판정**: 실패 11개 리프 전부가 기본 옵션에서 `ok`이고, 각 기본 응답이 실측 20,000자 이내이며, 각 리프의 전수 옵트인 경로가 `too_large` 없이 또는 듣는 좁히기와 함께 도달 가능하다. `screen filters` 기본 1회로 88개 id·label·definition 전부.

4. **단일은 전수, 다중은 목록 (성진 결정, G9)** — `stock` 리프의 목표가 1개면 현재 동작 그대로(지표 84개 전부, v1 수정 보존). 2개 이상이면 기본이 헤더 + 지표 라벨·값 목록이 되고 `--fields`·`--filter`로 좁힌다. 다중 목표의 `too_large` `fix`는 `ids[0]`이 아니라 목표 전체의 id를 열거하고, 목표 수를 줄이는 제안을 포함한다. **완료 판정**: `stock snapshot AAPL MSFT NVDA`가 기본 옵션에서 `ok`이고, 티커 1개는 여전히 `shown=84`이며, 10개 목표의 `fix`가 열 id를 모두 담고도 예산 안이다(G8과 함께).

5. **실패 메시지가 듣는 것만 이름 붙인다 (A1, A6, G8, G6)** — `screen filters`의 `narrow`에 `--fields`를 넣는다. `finalize()`가 오류 결과에서 선택되지 않은 `data`를 떨어뜨려 `invalid_fields`가 `too_large`에 가려지지 않게 한다(`array_alignment`의 진단용 배열 보존은 유지). `emit()`이 대체 오류 문서에도 예산 검사를 적용하고, 넘으면 id 목록을 줄인 최소 문서를 낸다. dict 리프의 키 선택은 `--fields`가 아닌 별 이름(`--keys`)으로 나누고 `market quotes`의 `narrow`를 그에 맞춘다. **완료 판정**: 11개 리프 각자의 `fix` 문장을 **그대로 실행**하면 전부 `ok`가 되는 재현 테스트, `stock options --fields bogus`가 기본 예산에서 `invalid_fields`와 21개 필드명을 내는 재현 테스트.

6. **발견 명령과 `choices` (G4)** — `market bubbles`의 네 축에 원천이 제공하는 값 목록을 주는 발견 경로를 붙인다(`market bubbles --list-fields`, yfinance의 `--list-fields` 선례). `screen run --sort`·`insiders trades --sort`의 정렬 키를 정상 출력이 노출하게 한다(열 헤더 레코드에 `sort_key`). **완료 판정**: SKILL.md와 CLI만 받은 모델이 비기본 버블 축과 예시에 없는 정렬 키로 유효한 요청을 만들 때까지의 실패 호출 수가 0인 시나리오 통과.

7. **모델이 읽는 자리의 표식과 계약 정합 (F1, A4, G7, E1~E5)** — `output` 선언의 `"[]"`·`"{}"`를 모양을 말하는 문장으로 바꾸고 `epilog()`가 그것을 낸다. argparse 실패를 봉투로 보내 `invalid_argument`와 exit 2로 만든다(`sec.py:10-12`·`yfinance_cli.py:39-45` 선례). 리디렉션 체인의 성공한 중간 응답을 저장한다. `schema.shared_options`에 `--max-chars`의 이유 문장을 넣는다(C1). zsh 문장 1개, positional metavar 통일, `docs/usage.md` finviz 절 정정, 번들 잔여물 삭제. **완료 판정**: 42리프의 epilog에 `[]`·`{}`가 없고, `stock nosuchleaf`가 JSON 봉투와 exit 2를 내며, `validate_harness.py --path .`가 errors 0 / warnings 0.

8. **본문을 판단만 남기고 줄인다 (G12, A2) + 선택 항목** — `SKILL.md`에서 절차의 사본(`read` 조작법, `/data/records` 주의, `--pages/--out` 기전, argparse 예외, "87 controls")을 빼고, 판단(라벨 모호성, 조건 적용의 인식론, 시각 구분, 스킬 경계, 큰 결과의 의미)은 남긴다. 빠진 절차는 6·7번에서 도움말·`schema`·`fix`가 소유하게 된 것들이다. 커버리지의 유일한 논쟁거리인 스크리너 `v=321`(스크린 집합의 뉴스)을 덮을지는 이 단계에서 결정한다. **완료 판정**: 본문의 모든 문장이 "이 문장이 없으면 모델이 무엇을 잘못하는가"에 답하고, CLI가 이미 내는 사실을 반복하는 문장이 없으며, description은 845자 그대로 두고 트리거를 건드리지 않는다.

9. **잉여를 걷어낸다 (S1~S4)** — 달력 4리프가 각자 받는 인자만 갖게 하고(`earnings`·`dividends`는 셋 다, `economic`은 `--date`·`--sort`, `season`은 없음) 도움말의 거절 설명 문장을 없앤다. `--connect-timeout`·`--timeout`·`--max-bytes`를 모델이 보는 공유 옵션에서 내리고 환경 변수로 받으며 `doctor`가 실효값을 보고한다. 개요 페이지에서 나오는 여섯 리프가 저장된 관측을 재사용할 수 있게 한다(2번의 `read` 문맥 보존과 같은 뿌리). `inspect`를 `/data` 아래로 한정한다. **완료 판정**: `calendar season --help`에 인자가 `-h`뿐이고 세 인자를 주면 argparse 수준에서 거절되며, 리프 `schema`의 공유 옵션이 693자 + `--store`로 줄고(현재 1,192자), 개요 4절을 보는 데 HTTP 요청이 1회이며(현재 4회), `inspect`가 봉투 포인터를 내지 않는다. 명령·그룹 개수는 바꾸지 않는다.

10. **검증·리뷰·전달** — `uv run -q --frozen --python 3.11 --group dev --project .claude/skills/finviz python -m pytest tests/finviz -q`와 같은 project의 ruff. **`tests/finviz/test_live.py`를 고친다**: 지금은 큰 표면을 미리 좁혀 호출하므로 기본 옵션 실패가 보이지 않는다. 42리프 각자를 **기본 옵션으로** 호출해 `ok`를 요구하는 케이스를 추가하고, 각 리프의 `fix` 문장을 그대로 실행해 `ok`가 되는지 검사하는 케이스를 추가한다. 이 세션의 실측 체인 전체를 새 격리 저장소에서 재실행해 위 완료 판정 수치를 기록한다. 코덱스(`gpt-6-astra`, high, read-only) 독립 리뷰 1회. 모델 시나리오는 `tests/finviz/model-scenarios.json`의 5개에 세 개를 더한다: 조건 발견에서 시작하는 스크리닝 1건(`screen filters` → `run`까지의 호출 수를 합격 기준에 넣는다), 3종목 비교 1건, 그리고 한 회사의 개요·뉴스·내부자를 함께 보는 1건(HTTP 요청 수를 합격 기준에 넣는다). **샌드박스는 `danger-full-access`** — `workspace-write`·`read-only`에서는 CLI의 curl이 나가지 못해 코덱스가 픽스처 값을 답으로 낸다. 브랜치 `feat/finviz-selection-evidence`, 커밋 단위는 위 1~9, PR 제목 `feat: finviz 선택·발견·근거·재생 계약 재설계`, `gh pr merge --squash`.

## 최종 스킬 디렉터리 구조

구조는 바뀌지 않는다. `references/`를 만들지 않는 것이 이 보완의 결정이고 이유가 있다.

```
.claude/skills/finviz/
├── SKILL.md              판단만. 절차·인자·출력 계약은 CLI가 소유
├── pyproject.toml        beautifulsoup4 4.15.0, json5 0.15.0 / dev: pytest, ruff
├── uv.lock
└── scripts/
    ├── finviz.py         @leaf 레지스트리, 파서 구축, schema·doctor·search·read·inspect
    ├── output.py         봉투·선택·예산·오류·종료 코드
    ├── transport.py      curl, URL 허용목록, 리디렉션, Store
    ├── markup.py         공용 HTML·표 추출
    ├── screener.py       screen filters|signals|columns|views|run
    ├── stock.py          stock 16리프
    ├── markets.py        groups 3 + market 4
    └── feeds.py          calendar 4 + news 3 + insiders 1 + open
```

`references/`가 없어야 하는 이유: 참고 파일이 맡을 내용 — 필터 88개, 시그널 34개, 열 128개, 뷰 9개, 맵 15종 — 은 **라이브 카탈로그**다. 산문 사본은 A2가 3일 만에 증명한 대로 드리프트하고, 발견 명령(`screen filters|signals|columns|views`)과 argparse `choices`가 같은 정보를 정확하게 낸다. 그리고 진행적 공개가 값을 하려면 모델이 실제로 **분기**해야 하는데, 이 스킬에서 분기는 명령 선택이고 그것은 `--help`·`schema`가 이미 계층으로 준다. 이 저장소의 어느 스킬도 `references/`를 갖지 않는다.

## 최종 SKILL.md 섹션 구조

38줄을 유지하거나 줄인다. 프론트매터는 `name`·`description`(845자, 손대지 않는다)뿐이다.

| 섹션 | 남는 내용 | 빠지는 내용 |
|---|---|---|
| `# Finviz through one CLI` | 호출 한 줄, `CLAUDE_SKILL_DIR`이 치환되지 않을 때의 대안, `--help`→`GROUP LEAF --help`→`schema GROUP LEAF`의 계층, **zsh 함정 한 문장(E1)** | `read --pointer/--start/--limit` 조작법, `/data/records` 주의, argparse 예외 — 전부 도움말·`schema`·`fix`가 소유 |
| `## Which surface the question needs` | 질문 모양 → 명령 경로의 판단(조건에서 시작하면 `screen`, 한 기업이면 `stock`, 집계면 `groups`·`market`, 붙여 준 URL이면 `open`) | "87 controls"(A2), `--pages/--out` 수집 기전, 플래그별 좁히기 지시 |
| `## Meaning comes from the source` | 그대로. 라벨이 측도를 특정하지 않는다(`EPS next Y` 두 번, `EPS Q/Q`가 YoY, ETF `Tags` 반복), 정의·단위·값을 함께 읽고 원천 문자열을 벗기지 않는다 | — |
| `## Scope travels with the observation` | 그대로. 행을 받았다는 것이 선택자 적용을 증명하지 않는다, `conditions`의 세 상태와 `coverage`의 의미, 필드 부재가 확인이 아니다, `--pages` 실행은 인구조사가 아니다 | — (이 절이 G1의 판정 근거였다) |
| `## Time belongs to each observation` | 그대로. `observed_at`과 `as_of`·기간 종료·추정 실적일·봉 epoch의 구분, 맵 `value`와 버블 `size`가 시가총액이 아니라는 것 | — |
| `## Follow the evidence the question needs` | 그대로. 뉴스 `url`은 외부이고 `finviz.com/news/...`만 읽을 수 있다, Market Pulse는 원천 생성이라 단서이지 근거가 아니다, SEC 원문은 `sec`, 비-Finviz 가격·재무는 `yfinance` | — |
| `## When a result is too large` | 기본값이 한 화면이고 전수는 요청해서 받는다는 **의미**, `too_large`가 빈 결과가 아니라 예산 조건이라는 것, 응답은 이미 저장돼 있다는 것 | 어느 인자로 좁히라는 지시(`fix`가 리프마다 정확히 이름 붙인다), 페이지 id 열거 기전 |

## 검증 기록

- 실측: 이 세션에서 `--help` 3계층, `schema` 35개, 42리프 중 40개를 기본 옵션으로, 오류 10종, 각 리프의 `fix` 문장을 그대로 실행. 격리 저장소 관측 156건. `validate_harness.py --path .` errors 0 / warnings 0.
- 커버리지: 익명 요청으로 finviz.com 홈·스크리너(`ft=4`)·종목(`t=A&ty=c`)·스크리너 뷰 4종(`v=321,411,311,341`)을 받아 내비게이션·뷰·탭을 열거하고 CLI 42리프·허용목록 21경로와 대조.
- 잉여: 달력 4리프에 거절되는 인자 5조합을 실제로 주고, 공유 옵션 8개의 자수를 재고, 개요 파생 6리프의 `source.url`을 비교하고, `open`으로 종목 페이지를 열어 타입 명령과의 겹침을 확인하고, `groups options`·`screen views`를 각 인자의 `choices`와 대조했다.
- 코덱스 독립 재점검 1회(`gpt-6-astra` high, read-only 격리, `20260919-011356-finviz-reaudit-ed69`, exit 0). 내 판정 7건을 철회·축소시키고 내가 통과로 둔 곳에서 결함 8건을 냈으며 층 경계를 반박했다. 그중 G1·G2·G3·G6과 다중 목표 실패는 **내가 직접 재측정해 확인했고**, G7·G8·G10·G11은 코덱스의 소스 독해이고 내가 실측하지 않았다. 코덱스는 read-only 샌드박스에서 CLI를 실행하지 않고 소스와 테스트만 읽었다.

## 검증하지 않은 것

- G10(내보내기와 이어보기의 상호작용: `--out`은 지역 선택된 행을 쓰고 `continuation`은 받은 페이지로 전진하므로, 기본 상한이 붙으면 이어보기가 내보내지지 않은 행을 건너뛸 수 있다)과 G11(`data` 안쪽 중복)은 코덱스의 소스 독해다. 구현 세션에서 먼저 실측한다.
- `screen run --pages N --out`의 다중 페이지 실행, `--append`, 실패한 후속 페이지의 이어보기는 실행하지 않았다(`tests/finviz/test_screen.py`가 덮는다).
- 403/429 `access_restricted` 경로는 유발하지 않았다.
- `stock` 16리프를 티커 `A`(ETF는 `SPY`)와 3종목 비교로만 실측했다. 다른 종목의 출력 크기는 다를 수 있다.
- 호스트 도구(Claude Code Bash)의 조용한 잘림 지점을 측정하지 않았다. 성진 결정으로 예산 상한은 이번 범위 밖이다.
- 클로드 본체의 E2E 시나리오는 실행하지 않았다. `tests/finviz/model-scenarios.json`의 5개는 정의만 있다.
- `market quotes`에서 `sparkline`을 뺀 뒤의 실제 크기는 계산값(13,571자)이고 구현 후 재측정한다.
- S3의 해법(추출기를 저장된 관측에 대해 돌려 개요 4절을 1회 요청으로 만드는 것)이 실제로 가능한지는 확인하지 않았다. 여섯 리프가 같은 URL을 받는다는 사실만 실측했다. 구현 세션에서 추출기가 저장된 HTML만으로 동작하는지 먼저 확인하고, 안 되면 `--sections` 같은 요청 단위 병합으로 바꾼다.
- S2에서 전송 플래그를 환경 변수로 내릴 때 `test_install.py`가 검사하는 격리 설치 경로가 영향을 받는지 확인하지 않았다.

## 폐기하지 않는 결정

- **스크리너·그룹·옵션·맵의 `conditions` 근거 기계.** 요청한 조건을 페이지 자체 컨트롤에서 확인하고 `confirmed`/`not_applied`/`unverified`로 보고하며 HTTP 200을 근거로 치지 않는다. 달력만 고친다(G1).
- **파서에서 파생하는 `schema`와 3계층 `--help`**, 모든 인자의 `help`·`default`, 닫힌 선택지의 `choices`, `test_schema.py:15`가 도움말과 `schema`를 서로 고정하는 구조.
- **자르지 않는다는 계약.** 프리뷰·절단 없이 `too_large`로 알리고 에코된 `--max-chars`가 재실행 가능하다. 기본 예산 20,000자도 값 그대로 유지한다.
- **의미 선언 `narrow`·`records`·`default_limit`.** 파서는 어떤 플래그가 존재하는지 알지만 어떤 플래그가 이 페이로드를 줄이는지는 모른다. 선언은 남고 그 정확성을 테스트가 고정한다.
- **얇은 봉투, 단일 JSON stdout, `-q --frozen`으로 침묵하는 stderr, 등급 종료 코드, 관측 저장소와 `read`/`inspect`.**
- **전송 계층**: curl 서브프로세스, HTTPS·finviz.com 허용목록, 리디렉션 재검증, Cloudflare 확인 화면 감지, 401/403/429를 우회하지 않는 `access_restricted`.
- **명령 구조** 13그룹 42리프와 `@leaf` 레지스트리, 그리고 `references/` 없는 단일 본문 구조.
- **원천 값 보존**: 값은 원천 문자열 그대로, 라벨 중복은 별 레코드로, 단위는 응답에 있는 것만. `sparkline`을 기본 출력에서 빼는 것은 표현 결정이고, G3이 함께 고쳐질 때만 무손실이다.

## 구현 완료 기록 (2026-09-19, 브랜치 `feat/finviz-selection-evidence`)

보완 작업 1~10을 전부 구현했다. 커밋은 항목 단위이고, 아래는 **계획과 달라진 결정**과 **실측 결과**다. 계획이 그대로 구현된 부분은 커밋 본문에 있으므로 반복하지 않는다.

### 계획과 달라진 결정

- **기본 범위의 적용 지점이 바뀌었다.** 처음에는 리프 본문에서 잘랐는데, 그러면 관측이 저장되기 *전에* 잘려 저장소가 전체를 잃고 `--filter`도 창 안에서만 검색한다. 코덱스 리뷰가 둘 다 재현했다(180건 중 40건만 검색, `read --start 40`이 빈 결과). `@leaf`에 `window` 선언을 더해 **저장 이후·선택 층에서** 적용하고, 순서를 `--filter` → 창 → `--fields`/`--limit`으로 고정했다. "관측은 전부를 보존한다"는 계약이 기본 범위와 양립하는 유일한 배치다.
- **달력 `sort`는 `confirmed`를 주지 않는다.** 계획은 날짜와 같은 에코 비교를 상정했으나, 실측으로 둘이 다르다는 것이 드러났다. 페이지는 쓸 수 없는 `dateFrom`을 자기 기본값으로 바꾸지만(= 검증한다), `sort`는 API가 HTTP 400으로 거절하는 값까지 그대로 되비춘다(= 검증하지 않는다). 그래서 **검증하는 에코만 확정에 쓴다**: 어긋나면 `not_applied`, 같으면 날짜는 `confirmed`·정렬은 `unverified`. 첫 구현은 정렬을 거짓 확정했고 리뷰가 blocker로 잡았다.
- **`market bubbles`의 축은 `--list-fields`가 아니라 `choices`로 닫았다.** 원천이 값 목록을 제공하는 화면이 없고(버블 페이지의 축 목록은 webpack 청크 안에 있다), 대신 잘못된 축을 HTTP 400으로 **거절한다**. 128개 스크리너 컬럼 id를 직접 물어 받아들여지는 57개 + `lastChange`를 확정하고 `choices`로 닫았다. 목록이 낡으면 조용히 틀리는 것이 아니라 400으로 소리내어 실패한다. `--index`는 반대로 모르는 값을 거절하지 않고 5,906종목 전체를 말없이 돌려주므로, 닫는 것이 더 필요했다.
- **`open`이 12번째 실패 리프였다.** 계획의 11개 목록에 없었지만 실측하니 대부분의 페이지에서 기본 옵션으로 실패했다(스크리너 페이지는 컨트롤의 옵션 목록만 355,669자). `screen filters`와 같은 2단 규칙을 줬다: 컬렉션은 개수로 오고 이름으로 요청한다(`--rows`/`--options`/`--initial`).
- **`--keys`를 새로 만들었다.** 계획의 G6은 dict 리프의 키 선택을 `--fields`에서 분리하라는 것이었고, 분리하고 보니 `--fields`가 "각 항목 *안쪽*의 필드"라는 자연스러운 뜻을 갖게 됐다. `market quotes futures --fields label,last`가 도움말이 약속한 대로 동작한다.
- **`screen v=321`(스크린 집합의 뉴스)은 덮지 않는다.** 그 뷰의 뉴스는 서빙되는 HTML에 없고 `route-init-data`에도 없다(실측: `tableSettings`·`pageSettings`뿐). 클라이언트 렌더링이라 읽기 전용 추출기가 닿지 않는다.
- **`stock short-interest`에도 `recent`를 적용했다.** 계획은 `flows`만 지목했지만 같은 모양의 결함(오래된 것부터 실리는 계열을 접두로 자르면 2019년 값이 나온다)이라 공유 선언 한 곳에서 함께 고쳤다.

### 실측 (2026-09-19, 격리 저장소, 익명, 기본 옵션)

| 항목 | 보완 전 | 보완 후 |
|---|---|---|
| 기본 옵션으로 실패하는 리프 | 12 / 40 | **0 / 40** |
| `screen filters` 1회로 받는 필터 | 실패(208,728자) | **88개 전부, 16,017자** |
| `market quotes futures` | 실패(140,470자) | **8,424자**(스파크라인 제외, 저장소는 보존) |
| `stock snapshot` 3종목 | 실패(25,194자) | **11,359자** |
| `open` 종목 페이지 | 실패(67,971자) | **19,137자** |
| 예산을 넘는 호출의 `fix`를 그대로 실행 | — | **9/9 회복** |
| 139,959자 원자료 완독 | 경로 없음 | **8창**(fix가 계산한 창 크기) |
| 개요 4절을 보는 HTTP 요청 | 4회 | **1회** |
| 10종목 실패 시 오류 문서 | id 1개 | **id 10개, 3,049자** |

테스트: `tests/finviz` **99 passed**, 라이브 **48 passed / 1 skipped**(기사 1건은 당시 헤드라인에 finviz 호스팅 기사가 없어 skip). 형제 스킬 회귀 없음(sec 97, yfinance 108, 나머지 1,023). `validate_harness.py --path .` **errors 0 / warnings 0**.

### 모델 시나리오 (코덱스 `gpt-6-astra` medium, 격리, SKILL.md만 주고 소스 읽기 금지)

| 시나리오 | 실행 ID | 결과 |
|---|---|---|
| 조건 발견 → 스크리닝 | `20260919-123138-run-5a38` | CLI 6회, **실패 0회**. `conditions`를 근거로 인용하고 `coverage`(169 중 20 수신, 10 표시)를 정확히 해석했다. |
| 3종목 비교 | `20260919-123138-run-82b5` | CLI 3회, **실패 0회**. 한 호출로 세 종목을 받고, 정의가 없는 것은 "제공받지 못했다"고 적었다(일반 지식으로 채우지 않았다). |
| 한 회사 여러 절 | `20260919-123138-run-89c4` | CLI 9회, **HTTP 요청 1회**. `--from`으로 절을 뽑고 각 절의 관측 시각을 밝혔으며, 내부자 거래 5건만으로 전체를 판단할 수 없다고 명시했다. |

### 남긴 한계

- **`calendar season --limit N`은 `items`만 자르고 `totals_per_day`는 전체를 남긴다.** 일자별 합계는 프리뷰 전체의 요약이라, 보이는 항목에 맞춰 자르면 원천의 요약과 어긋난다. 242자이므로 예산 문제도 아니다.
- **`inspect`는 `/source/headers` 아래 포인터를 남긴다.** 헤더는 모델이 실제로 열어 보는 동적 dict이고, 봉투의 *스칼라* 포인터만 뺐다.
- **리프 `schema`에 공유 옵션 설명이 1,237자 반복된다.** 값을 바꿀 조건은 무인자 `schema`로 한 번만 옮겼지만, 각 인자의 한 줄 설명은 리프마다 남는다. 모델은 한 번에 한 리프의 schema를 읽으므로 사용 지점에서는 중복이 아니다.
- **`stock earnings --fiscal-period`와 `stock filings --form`은 여전히 저장 전에 거른다.** 둘 다 명시적 선택자이고 v2부터의 동작이며, 원자료는 전체를 보존한다. `window` 선언으로 옮기면 같은 계약이 되지만 이번 범위 밖으로 뒀다.
- **호스트 도구의 조용한 잘림 지점은 여전히 측정하지 않았다.** 성진 결정으로 `--max-chars` 상한은 이번 범위 밖이다.
- **오류 문서의 바닥은 216자다.** 저장된 id(32자)와 통과할 크기를 남기는 최소 형태이고, 그보다 작은 `--max-chars`에서는 예산을 넘는다.
