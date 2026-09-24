# finviz 스킬 선택·재생 계층 재설계 계획

> 구현 세션의 첫 동작: 이 파일을 형제 관례에 맞춰 `.claude/plans/finviz 스킬 선택·재생 계층 재설계 계획.md`로 옮긴다(plan mode에서는 이 파일 외 조작이 불가했다). 작업 트리의 무관한 변경(`.gitignore`, `.claude/harness-spec.md` 삭제, 다른 계획 파일)은 커밋에 섞지 않는다.

## Context

성진의 목표는 클로드가 **Finviz를 숙련자처럼** 쓰는 것이다 — 스크리너에서 조건을 고르고 적용됐는지 화면에서 확인하고, 종목 페이지를 한 번 열어 여러 표를 읽고, 여러 종목을 한 표로 비교하고, 뉴스는 원문으로 따라간다. 클로드는 언어로 일하므로 그 역량은 **스스로를 설명하는 CLI**로 주고, SKILL.md에는 기본 모델에게 없는 판단만 둔다. 잣대는 skill-maker의 네 성질(principle over rail, interface over document, for the model not the maintainer, dense)과 **기본값과의 대조**다. 성공 기준은 퀄리티뿐이다.

v2(PR #13)와 보완(PR #15)은 "기본 옵션의 첫 호출이 성공하는가"를 통과시켰다. 이번 점검은 **"모델이 고른 선택이 그대로 적용되고, 복구해도 같은 질문에 답하는가"**를 물었고 통과하지 못했다. 뿌리는 하나다: **선택이 1급 객체가 아니다.** `--filter/--fields/--keys/--limit`·`window`·`recent`·`--from`·`read --pointer`가 데이터 모양마다 다른 뜻을 가져서, 조용히 무시되는 선택자, 복구하면 다른 데이터가 나오는 경로, "최신순"이라며 2023년 자료를 주는 기본값이 생겼다. 스킬이 가르치는 "행이 왔다고 조건이 적용된 건 아니다"를 CLI 자신이 어긴다. 그리고 "예산 초과 = too_large 오류 + 휴리스틱 복구 문장" 계약은 개수 기반 기본값과 맞지 않아, 데이터가 많은 날 기본 호출이 다시 실패하고 복구 휴리스틱에 특례가 계속 쌓였다(`# 성진:` 25개 중 11개가 `output.py`, 리뷰 4라운드).

그래서 **전송·추출기·조건 근거 기계는 살리고, 선언·선택·예산·재생 계층을 다시 쓴다.**

## 합의된 결정 (성진, 2026-09-24)

| 결정 | 내용 |
|---|---|
| 범위 | 선택·재생 계층 재작성. 전송(curl·허용목록·리디렉션)·페이지 추출기·`conditions` 근거 기계는 유지 |
| 판단 근거 | **타 스킬과의 일관성은 근거가 아니다.** finviz 자체로 완결적으로 최선인 설계를 택한다 |
| 예산 계약 | 넘치면 **들어가는 만큼의 창 + `status: partial` + 같은 선택을 여는 continuation**. `too_large`는 한 레코드가 혼자 예산을 넘을 때만 |
| 발동 | 핀비즈 명시·finviz URL·그 후속일 때만(현행 description의 경계 유지) |
| 커버리지 추가 | 스크리너 티커 목록(`t=`), **덮는 화면의 검증된 원천 컨트롤 전부**를 인자로(아래 표). 차트 이미지는 제외 유지 |
| 개요 페이지 | `stock overview TICKER --sections …` 한 호출·한 요청·한 관측. 기본은 **스냅샷 + 나머지 절의 이름과 항목 수**. `--from` 폐기 |
| `read` | **원 리프의 선택 어휘 그대로.** continuation은 실행 가능한 명령 한 줄. JSON Pointer·`inspect` 폐기(원자료는 `--raw --chars`) |
| `open` | **폐기.** 붙여 준 URL은 모델이 인자를 읽어 전용 명령을 부른다 |
| 검증 모델 | **Claude(Opus 5.5)만.** 대조·제거 시험·시나리오 전부 Claude. 코덱스(`gpt-6-astra`)는 리뷰어 |
| 개발 기록 | 이 계획 파일의 "구현 완료 기록" + 커밋 본문. 스킬 폴더에는 두지 않는다 |

## 실측 장부 (2026-09-24, 스크래치 저장소, 익명)

### 결함 — 클로드 실측과 코덱스 감사(`20260924-150821-finviz-audit-v3-ed0c`, CLI 56회·HTTP 29회)
| # | 증상 | 재현 | 뿌리 |
|---|---|---|---|
| D1 | 조용한 no-op 선택자 | `stock news A --keys foo`, `market map --limit 3`, `stock statement --filter Revenue --limit 1`, `market map --filter AAPL --limit 1`, `screen views --keys X`, `groups performance --keys x` 전부 ok·무변화 | 공유 옵션 6개를 모든 리프에 붙이고 적용 가능성을 모양 추측으로 판정 |
| D2 | 복구가 질문을 바꾼다 | `stock options AAPL --type put --strikes 0 --fields strike,type,… --max-chars 3000` → fix의 `read … --limit 23`이 콜 포함·21필드 전체 | 선택이 직렬화되지 않고 복구 문장을 휴리스틱으로 재구성 |
| D3 | 기본값이 약속과 반대 | `stock earnings AAPL --dataset revisions` 기본 40건 전부 2023-07(9,284건 중 앞 40; 선언은 newest first) | 정렬 의미가 선언에 없고 데이터 구조(기간×EPS/매출)를 모름 |
| D4 | 기본 호출 실패 재발 | `calendar earnings --date 2026-10-27`, `groups table --group industry`, `stock short-interest AAPL`(20,754자, 복구는 2020~2025-02만 줘 최신 누락), `market map --type sec_all`(77,968자) | 개수 기반 기본값 + 크기 오류 계약 |
| D5 | `--fields` 뜻이 모양마다 다름 | `stock statement --fields 'Total Revenue'` 실패(필드=절 이름), `read …/contracts/0`의 coverage가 필드 수 21/21 | 레코드·키·절 세 모양을 한 플래그로 |
| D6 | `--from` id 혼동 | `stock news --from S` 후 `read S`는 스냅샷을 줌 | 추출 결과가 아닌 원 관측 id를 재사용 |
| D7 | 헤드라인 날짜 소실 | `stock news AAPL --filter uGreen` → `08:10PM`만 | 날짜가 앞 행에만 있고 추출기가 상속하지 않음 |
| D8 | 로컬 필터 0건을 원천 empty로 보고 | `--filter ABSENT` → exit 7, "The source returned no usable items" | 원천 empty와 선택 결과 empty 미구분 |
| D9 | 전송 실패 fix가 없는 플래그를 권함 | `FINVIZ_MAX_BYTES=10 … search` → `--timeout`·`--max-bytes` 권유 | 플래그를 환경 변수로 옮기며 오류 경로 누락 |
| D10 | 인자 오류 fix 대상 오류 | `--store P screen run --tickers X` → 루트 도움말을 가리키고 `target`에 argv 전체 | 공유 옵션이 GROUP 앞에 오면 리프 탐색 실패 |
| D11 | 암묵적 단위 | 추정 수정 매출 `mean 113250.57`(백만 달러), `shortInterest 139.75`·`sharesFloat 14576.2`(백만 주), 달력 `marketCap 4911.5`(백만 달러) — 응답에 단위 없음 | 원천 문자열 보존 원칙이 JSON 숫자를 덮지 못함 |
| D12 | 모델 대상 문장의 개발자 사유 | `market bubbles --index` help "The source does not refuse an unknown name … so the choices are closed here"; `--max-chars` help "a shorter budget could not hold the error document" | for the model 위반 |
| D13 | 잘못된 닫힌 값 | `market bubbles --index sec_all`은 유효한 `idx`가 아님(UI "All"은 `any`). 맵 composite는 `sec_ixic`가 아니라 `sec_comp` | 추정으로 닫은 choices |
| D14 | 유지보수 | 500자 초과 줄 24개, 최장 선언 1,541자, `window`가 네 뜻, `finalize`·`select`가 같은 창을 두 번 호출(멱등성 의존) | 선언이 데이터가 아니라 람다·문자열 |

### 대조 실험 (Claude Opus 5.5, `claude -p --safe-mode --restricted`, 4과제 × {B: CLI만, C: CLI + SKILL.md 본문}, T1은 A: 아무것도 없음 추가)
- **본문의 대표 예시는 대조를 싣지 않는다.** 세 팔 모두 "EPS Q/Q는 YoY", "EPS next Y 두 번"을 알았다(A는 WebFetch로 값까지). 가치는 CLI의 정의 추출에 있다(A는 툴팁을 못 받아 "일반적 정의"로 채움).
- **행동을 바꾼 본문 원칙**: (1) 확인 안 된 정의를 채우지 않는다 — B는 PEG를 "P/E÷5년 성장률"로 채웠고 C는 "Finviz가 밝히지 않는다"고 비워 둠. (2) 시각의 역할 구분 — C만 시세 시각과 `observed_at`을 나눔. (3) 정렬 `unverified`를 보고 순서를 직접 검증(T4-C). (4) zsh 문장 — B에서 `F="uv run …"; $F` 실패 2회, C는 전부 셸 함수.
- **같은 질문이 다른 질문으로 답해졌다(T4)**: B는 최신 200건을 로컬 정렬("최근 5영업일 중 큰 것"), C는 원천 정렬("원천이 보유한 최근 묶음 중 큰 것"). 원천 정렬은 원천이 가진 창 안에서만 정렬한다 — 본문이 가질 판단 후보.
- 기본 모델이 이미 잘하는 것: 3티커 중복 공시(Berkshire LEN/BRK-A/BRK-B) 인지, 금액 분포 편향 설명, 스크리너 버킷 선택.
- 5종목 비교는 두 팔 모두 `stock snapshot` 5요청(5.4초). 스크리너 `t=`면 1요청.

### 화면 컨트롤 → 인자 (코덱스 `20260924-153753-finviz-controls-498c`, 익명 149요청, V=요청으로 효과 확인)
원자료·카탈로그: `/private/tmp/claude-501/finviz-controls/`(`request-index.json`, `control-catalogues.json`, `map-subtypes.json`, `bubble-control-catalogue.json`, `090-route-init-data.json`). 재부팅으로 사라졌으면 단계 7에서 같은 방법(번들·init-data 역산 → 익명 요청 검증)으로 다시 만든다. **B(번들에서만 발견)는 인자로 올리지 않는다.**

| 화면 | 올릴 인자 (V) | 원천 에코 | 비고 |
|---|---|---|---|
| 스크리너 | `t=` 티커 목록, `s=` 시그널, `o=`(±), `c=` 열, `r=` 시작 행(CLI `--row`), `v=` 표 뷰. **한 필터 다중값 `f=a\|b`는 번들에서만 발견(B) — 단계 7에서 효과를 검증한 뒤에만 올린다** | 선택된 옵션·ticker input·`selectedColumns`·행 번호 | `ft`·`ar`·차트 뷰(211·311·341·351·711)·`p`/`ty` 차트 인자는 제외 |
| 옵션 | 만기 `e=`(API `expiry`), **행사가 `s=`/API `strike`(전 만기)**, `ov=chain_date\|chain_strike\|plot` | `currentExpiry`·`currentStrike`·`view` | `view=`는 무효(에코 불변). 콜/풋·정렬은 로컬. `/api/options/{t}?expiry=\|strike=` |
| 공시 | `page`, `o=filingDate\|reportDate\|form`(±), **`f=` 카테고리 10종** | 페이지 `initialSort`·`initialFilter`, API는 에코 없음 | `/api/quote/filings`. 단일 폼 서버 필터 없음(로컬 `--form` 유지) |
| 재무제표 | `s=IA\|IQ\|BA\|BQ\|CA\|CQ` | `Period` 행 | `so=R`은 익명에서 F와 바이트 동일 → 올리지 않음 |
| 그룹 | `g`·`sg`, `v=110\|120\|140\|150\|160`, `o`(±) | 선택 옵션 | 차트 뷰 제외. `/api/groups_perf`는 모든 기간을 한 번에 |
| 내부자 | `tc=7\|1\|2`, `oc=` 소유자, `tv=` 금액 하한, **`or=-10`(Top Insider)·`10`(Top 10% Owner)**, `o=` 7키(±) | 선택 옵션·관계 열 | `b=`는 내비게이션 |
| 실적 달력 | `dateFrom`, `page`, `sort` 14키(±) | 페이지 `initialDateFrom`·`initialSort` | 50행/페이지 |
| 배당 달력 | `dateFrom`, `page`, `sort` 6키 | 동상 | |
| 경제 달력 | `dateFrom`(주 단위), **이벤트 상세 `/api/calendar/economic/detail?ticker=&dateFrom=`**(시계열) | 이벤트 날짜 | `dateTo`는 무효. 중요도·국가 필터는 요청 인자 없음 |
| 시즌 프리뷰 | `dateFrom`, **일별 전체 `/season-preview/day?date=`** | `initialDateFrom` | 타일/목록·정렬은 로컬 |
| 뉴스 | `v=` 최신·출처별·주식·ETF·암호화폐·Pulse | 활성 탭 | 출처·티커 필터 없음 |
| Pulse | id 상세, **티커별 `/api/stocks-why-moving/{ticker}`**(없으면 204) | `id`·`ticker` | |
| 맵 | `t=` 15종(`sec_comp` 정정), **`st=` 기간 + 펀더멘털 지표**(`map-subtypes.json`, 장중 i*는 gated) | `subtype` | 표시 설정은 로컬 |
| 버블 | x·y·size·color 축별 닫힌 enum(카탈로그), `idx=any\|sp500\|ndx\|dji\|rut`, `tickers`·`excludeTickers`(각각 단독 V). `sec`·`cap`·`sh_avgvol`은 한 요청에 묶여 검증돼(요청 158) **개별 효과 미확인 — 단계 7에서 하나씩 검증 후 올린다** | 에코 없음 | `ind`는 미검증 → 올리지 않음. 축 범위는 로컬 |
| 선물·FX·암호 | `timeframe=d\|w`(V), 암호 `c=USD\|USDT\|EUR\|BTC`, 성과는 신 API `/api/{kind}/performance`(모든 기간 열) | 신 성과 API `currency` | 구 `_perf` 대체 |
| ETF 보유 | **`/api/symbol/{t}/holdings`** 상위 10 + 전체 개수 | 보유 심볼 | 전체 목록 `/holdings/list`는 302→Elite, 따라가지 않음 |

## 네 프레임이 이 재설계에서 결정하는 것

- **principle over rail → 선택은 한 곳에서 정의되고, 기본값은 "사람이 한 번 보는 것", 넘치면 창.** 출력 크기는 모델이 고른 선택의 결과이고 예산은 안전 경계다. 예산이 자르면 `partial`이 그 사실을 말하고 continuation이 **같은 선택**을 이어 연다. 복구 문장을 사람이 휴리스틱으로 짓지 않는다 — 선택을 직렬화한다.
- **interface over document → 리프가 받는 선택자만 그 리프의 파서에 있다.** 적용되지 않는 인자는 argparse가 거절한다(D1). 닫힌 집합은 `choices`, 필드 단위는 `schema`의 `units`(D11), 정렬 방향과 기본 창은 선언에서 파생된 `schema` 항목. 발견 전용 명령(`groups options`·`screen views`)은 그 정보가 `choices`와 help로 옮겨가면 사라진다.
- **for the model, not the maintainer → 모델이 읽는 문장은 "무엇이고 어떻게 읽는가"만.** "왜 이렇게 닫았는지", 측정 이력, 버전 날짜는 코드 주석·커밋으로. 오류 `fix`는 실행 가능한 명령이다. `# 성진:`은 성진의 규칙대로 "한계, 바꿀 조건"에만 쓰고, 패치 사유 주석은 일반 주석이나 커밋으로.
- **dense → 모든 결과는 "문맥 + 레코드 목록"이라는 한 모양.** 매핑·표·트리를 레코드로 정규화해 선택 규칙이 하나가 된다. 싼 신호 먼저(개요의 절 목록·항목 수, `coverage`), 비싼 상세는 요청해서. SKILL.md는 대조 실험에서 행동을 바꾼 판단만 남기고, 제거 시험으로 확인한다.

## 설계

### 명령 표면 (42리프 → 33리프)

| 그룹 | 리프 | 변화 |
|---|---|---|
| (내장) | `schema`, `doctor`, `search`, `read` | `inspect`·`open` 폐기. `read ID…`는 다중 id(다종목 continuation) |
| `screen` | `filters`, `signals`, `columns`, `run` | `views` 폐기(설명은 `--view` help로). `run`에 `--tickers`, 필터 다중값 |
| `stock` | `overview`, `earnings`, `forecast`, `dividends`, `revenue`, `short-interest`, `options`, `filings`, `statement`, `prices`, `holdings` | snapshot·profile·ratings·news·insiders·ownership·flows → `overview --sections`. `holdings` 신설(ETF 상위 10) |
| `groups` | `table`, `performance` | `options` 폐기(`--group`·`--sort` choices로) |
| `market` | `quotes`, `performance`, `map`, `bubbles` | `performance`는 신 API. 맵·버블 인자 확장 |
| `calendar` | `earnings`, `dividends`, `economic`, `season` | `economic --event ID`(시계열 상세), `season --day DATE` |
| `news` | `headlines`, `pulse`, `article` | `pulse --ticker` |
| `insiders` | `trades` | `--preset top-insider\|top-owner`, `--value`, `--owner`, 정렬 choices |

리프 수는 결과이지 목표가 아니다. 개요 7리프 병합과 발견 전용 3리프(`views`·`groups options`·`inspect`)·`open` 폐기가 줄어든 몫이다.

### 결과의 한 모양: 문맥 + 컬렉션

모든 리프는 추출 결과를 `{context: {...}, collections: {name: [records]}}`로 낸다. 봉투의 `data`는 `{…context, name: [records]}`로 평탄하게 싣는다(모델이 읽는 모양은 지금과 비슷하다).

| 원천 모양 | 정규화 |
|---|---|
| 재무제표 `{항목: [기간별 값]}` | 레코드 `{item, <기간>: 값…}`. `--fields TTM,2025FY`가 기간, `--filter Revenue`가 항목. `currency`·`periods`·`period_end_dates`는 문맥 |
| 매출 구성 `{series: [...]}` | 레코드 `{series, fiscal_year, value, report_end_date, source_filing_url}`, `unit`은 문맥 |
| 시세 `{ticker: quote}` | 레코드 `{ticker, label, last, change…}`. 스파크라인은 `--sparkline` 옵트인 유지 |
| 맵 성과 `{ticker: value}` + 분류 트리 | 레코드 `{ticker, performance}`, `--classification`이면 `sector, industry, description, weight`를 조인 |
| 개요 페이지 | 문맥 = 헤더(ticker, name, last_close, as_of, change), 컬렉션 = 요청한 절들(`snapshot`=지표, `news`, `ratings`, `insiders`, `insider_monthly`, `ownership_managers`, `ownership_funds`, `flows`, `profile`은 문맥으로) |

이 정규화로 `--keys`는 사라진다(키였던 것이 레코드의 필드가 되어 `--filter`·`--fields`로 닿는다). 원천 값은 문자열·숫자 그대로이고 바뀌는 것은 구조뿐이다.

### 선언 (`contract.py`)

리프는 데이터 선언이다. 람다·문자열 대신 명시적 필드:

```
Leaf(group, name, help,
     source_args=[...],                 # 원천 요청 인자 (choices·help 포함)
     collections={name: Collection(order=newest_first|oldest_first|source|by_strike…,
                                   default=Count(n) | None,        # 사람이 한 번 보는 양
                                   local=[Selector(...)]  )},      # 이 컬렉션에만 듣는 로컬 선택자(--type, --strikes, --form …)
     context=[...], units={field: "millions USD" | "millions of shares" | "percent" | …},
     targets="tickers" | None, remote_paging=Paging(arg="--page"|"--start", …) | None)
```

파서·`--help`·`schema`는 이 선언에서만 파생된다. 인자는 두 부류다.
- **운영 인자** `--max-chars`, `--store` — 모든 리프에 붙는다(`doctor`는 저장소 경로를 보고하고 `schema`도 예산을 받는다).
- **레코드 선택자** `--filter`, `--fields`, `--start`(0부터, 매치된 레코드 안의 로컬 위치), `--limit` — **컬렉션이 있는 리프에만** 붙는다. 원천 페이지 위치는 이름을 달리한다: 스크리너는 `--row`(1부터, 원천 `r=`), 달력·공시는 `--page`. 한 값이 원격과 로컬을 동시에 뜻하는 인자는 없다.

`schema GROUP LEAF`는 `arguments`(파서 파생), `collections`(이름·정렬·기본 창·로컬 선택자), `context`, `units`, `statuses`, `exit_codes`를 낸다.

**여러 컬렉션(개요의 절)**: 요청은 `--sections a,b`, 재생은 `read ID --section a`(단수). 절이 둘 이상이면 받는 선택자는 절마다 적용되는 `--limit`뿐이고, `--filter`·`--fields`·`--start`는 절이 하나일 때만 받는다(절마다 필드가 달라 한 투영이 성립하지 않는다 — 거절하고 fix가 `--sections <하나>`를 권한다). `coverage`는 절별 `{section: {...}}`. 원천이 그 절을 싣지 않은 경우(주식의 `flows`)는 절의 `coverage.absent: true` + 경고이고, 전체 상태는 다른 절이 있으면 `ok`다. 재생한 절의 상태는 그 절의 것이다(부재한 절을 `read --section`하면 `empty`).

### 선택·예산·연속 (`selection.py`, `budget.py`)

한 선택 = `{ids, section, filter, fields, start, limit, 로컬 선택자…}` — 직렬화 가능한 값.

적용 순서(한 곳): 원천 레코드 → 선언된 정렬 → `--filter` → 로컬 선택자 → `start` → `limit` 또는 기본 창 → `--fields` 투영. 모든 결과의 `coverage = {received, matched, shown, start, cut}`: `received`=원천이 준 수, `matched`=선택에 맞은 수, `cut`=`default`|`limit`|`budget`|없음.

상태:
- `ok` — 요청(명시 또는 기본 창)한 범위를 다 보였다.
- `partial` (exit 8) — **예산이 요청 범위보다 적게 보였다**, 또는 다중 목표 중 일부 실패, 또는 원천이 기록된 공백을 가짐.
- `empty` (exit 7) — **원천**이 레코드를 주지 않았다. 선택이 0건이면 `ok` + `matched: 0`이고 경고는 "선택이 received N건 중 0건에 맞았다"(D8).
- `too_large` (exit 9) — 레코드를 하나도 싣지 못한다: **문맥+봉투만으로 넘치거나 첫 레코드 하나가 혼자 넘친다.** 합의된 "한 레코드" 예외에 문맥을 포함한 이유: 문맥은 레코드 해석에 필수라 잘라서 싣지 않는다. fix는 `--fields`로 투영한 같은 명령, 또는 `read ID --raw --chars 0-N`. 레코드가 없는 결과(`doctor`, 오류 봉투들)는 이 규칙이 아니라 아래 오류 문서 경계를 따른다.
- `partial`의 원인은 결과가 말한다: `coverage.cut: budget`(예산), 목표별 `error`(실패한 목표), `warnings`의 원천 공백(맵 분류 실패, 스크리너 후속 페이지 실패). 상태 하나로 원인을 추정하지 않게 한다.

예산 맞춤: 문서를 만들고 넘치면 `shown`을 줄인다. **같은 절의 여러 목표는 같은 개수로** 줄여(비교가 한쪽으로 쏠리지 않고 커서 하나로 이어진다), 여러 절은 절마다 따로 줄인다. 이진 탐색으로 들어가는 최대 개수를 찾는다.

연속은 두 필드로 나눈다 — "요청을 끝내는 것"과 "그 너머를 더 보는 것"은 다른 질문이다.
- `continuation` — **예산 때문에 요청 범위를 다 못 보였을 때만.** 실행 가능한 명령 한 줄: `read ID… [--section S] --start <다음 위치> --limit <요청 범위의 남은 개수> <같은 선택자>`(셸 인용, `--store`·`--max-chars`가 기본값이 아니면 포함). 이어 붙인 결과는 예산 없이 받은 요청 범위와 같고, 요청 끝을 넘지 않는다. 같은 절의 여러 목표는 같은 개수로 잘렸으므로 한 `--start`로 이어지고, 짧은 목표는 그 위치에서 빈 결과를 준다. 여러 절이 잘렸으면 절마다 한 줄씩 `continuation` 목록.
- `next` — 요청 범위를 다 보였고 그 너머가 있을 때. 저장분에 매치된 레코드가 남았으면 `read … --start <요청 끝>`, 저장분을 다 봤고 원천에 다음 페이지가 있으면 같은 리프의 다음 페이지 명령(`--row`·`--page`, 새 관측이므로 새 `observed_at`).
- 둘 다 없으면 없다 — 부재는 완전성의 증명이 아니다(원천 목록은 페이지 사이에 바뀐다).

오류 문서 자체도 예산 안에 든다: 목표가 많아 오류 봉투만으로 넘치면 현행 `too_large_document`처럼 목표별 반복 문장을 묶고, 끝까지 첫 목표의 fix와 모든 저장 id(들어가는 만큼)를 남긴다. 이 불변식과 테스트(`output.py:273-293`의 사다리)는 유지하고 구현만 새 모양에 맞춘다.

### 재생 (`read`)

`read ID… [--section S] [원 리프의 선택자]` — 저장된 관측의 리프 선언을 찾아 **같은 선택 함수**를 돌린다. 원 리프가 받지 않는 선택자는 `invalid_argument`(리프 이름과 받는 선택자 목록을 fix에). 원 관측의 `status`·`warnings`·`conditions`·문맥을 그대로 싣는다(`partial`·`empty`가 재생에서 `ok`가 되지 않는다). `read ID --raw --chars A-B`는 원자료 문자 창. 개요 페이지는 한 관측이므로 `read ID --section news`가 새 요청 없이 다른 절을 준다(`--from`의 대체).

**실패한 관측도 읽힌다**: 전송 실패·추출 실패·리디렉션 거절의 응답은 `error`와 함께 저장되고(현행 `finviz.py:394-409`), `read ID`는 `error`를 경고로 싣고 원자료는 `--raw`로 준다(현행 `finviz.py:171-178`의 의도 유지, `tests/finviz/test_screen.py:215-226`이 고정). 컬렉션이 없는 실패 관측에 선택자를 주면 fix가 `--raw`를 권한다.

### 저장 (`store.py`, `transport.py`에서 분리)

관측 = `{id, leaf, request, observed_at, source, status, error, warnings, conditions, context, collections}` + 원자료. 성공 경로에서는 추출이 저장 **전에** 끝나고, 실패 경로에서는 받은 응답과 `error`가 그대로 저장된다. 선택·예산은 저장 **후** 출력에만 적용된다(현행 "관측은 전부를 보존한다" 유지). 스크리너 `--pages N`의 집계 관측도 같은 모양.

**정규화는 내용을 떨어뜨리지 않는다**: 원천 레코드의 알 수 없는 필드는 그대로 따라가고(현행 `test_stock.py:8-23`의 `newField`), 비어 있는 이름 있는 계열은 문맥의 이름 목록(예: 매출 `series_names`, 각 계열의 레코드 수)에 남는다(현행의 빈 `Services`). 정규화가 바꾸는 것은 중첩 구조뿐이다.

### 단위 (`units`)

JSON API의 숫자 필드는 리프 선언의 `units`에 단위를 싣고 `schema`가 낸다. 단위는 **같은 종목의 페이지 표시 문자열과 대조해 확정한 것만**(예: 개요 `Shs Float 14.58B` ↔ `sharesFloat 14576.2` → 백만 주). 확정 못 한 필드는 `units`에 넣지 않는다 — 부재는 "모른다"이다. HTML 표의 값은 원천 문자열(`4827.02B`, `-0.70%`)이라 단위를 스스로 싣는다.

단위는 **변형에 따라 달라질 수 있다**: 추정 수정 레코드의 `mean`·`high`·`low`는 `estimateType`에 따라 EPS(`E`)·매출(`S`)·기타(`R`, 의미 미확인)로 단위가 바뀐다(`2026Q4/E.mean=1.9823`, `2026Q4/S.mean=113250.57`). 선언은 `units={"mean": {"by": "estimateType", "E": …, "S": …}}`처럼 변형 키를 받고, 선언되지 않은 변형(`R`)은 `schema`에 "unresolved"로 드러난다. 테스트는 변형마다 대조 근거를 요구한다.

### 데이터별 기본 창 (D3·D4·D7)

| 리프·컬렉션 | 기본 |
|---|---|
| `earnings --dataset revisions` | `(fiscalPeriod, estimateType)`마다 **가장 최근 추정 1건** + 그 조합의 이력 개수. `--fiscal-period P`면 그 기간의 이력 최신순 |
| `short-interest`, `flows`, `prices` | 최신 쪽 N(oldest-first 원천을 끝에서) |
| `options` | 기초자산가에 가까운 N개 행사가(`--strikes`, 로컬 선택자), `--strike X`면 전 만기 |
| `news headlines` | 섹션마다 최신 몇 건(현행 섹션 균형 유지) |
| 개요 `news` | 각 헤드라인이 **앞 행에서 날짜를 상속한 `date`** 필드와 원문 `time`을 함께 가짐 |
| 달력·그룹·스크리너 | 한 화면 개수. 넘치면 예산 창(`partial`) |

### 전송

현행 유지(curl, HTTPS·finviz.com 허용목록, 리디렉션 재검증, Cloudflare 감지, 401/403/429는 `access_restricted`로 우회하지 않음). 허용목록에 새 API 경로(`/api/options/`, `/api/quote/filings`, `/api/symbol/*/holdings`, `/api/stocks-why-moving/*`, `/api/calendar/economic/detail`, `/api/calendar/earnings/season-preview/day`, `/api/{kind}/performance`)를 더하고, 맵 자산 경로는 유지. 전송 실패 fix는 `FINVIZ_*` 환경 변수를 실효값과 함께 이름 붙인다(D9).

## 최종 스킬 디렉터리 구조

```
.claude/skills/finviz/
├── SKILL.md              판단만. 인자·출력·단위·회복은 CLI가 소유
├── pyproject.toml        beautifulsoup4, json5 / dev: pytest, ruff (현행 위치 유지 — CI 경로 불변)
├── uv.lock
└── scripts/
    ├── finviz.py         진입점: 파싱 → 리프 실행 → 저장 → 선택 → 예산 → 출력 (얇게)
    ├── contract.py       Leaf·Collection·Selector 선언, 레지스트리, 파서·help·schema 파생, 상태·종료 코드
    ├── selection.py      선택 적용, coverage, continuation 명령 직렬화
    ├── budget.py         예산 맞춤(partial 창), too_large 판정, 오류 문서 경계
    ├── store.py          SQLite 관측 저장소 (transport.py에서 분리)
    ├── transport.py      curl, URL 경계, 리디렉션, Failure
    ├── markup.py         공용 HTML 추출
    ├── builtin.py        schema, doctor, search, read
    ├── screener.py       screen filters|signals|columns|run
    ├── stock.py          stock 11리프
    ├── markets.py        groups 2 + market 4
    ├── calendars.py      calendar 4 (표준 라이브러리 calendar를 가리지 않도록 복수형)
    ├── news.py           news 3
    └── insiders.py       insiders trades

tests/finviz/             (CI 경로 불변: .github/workflows/finviz.yml)
├── conftest.py           실제 CLI 서브프로세스 + 가짜 curl — 공개 seam, 유지
├── pages.py              페이지·API 픽스처 빌더 (새 API 모양 추가)
├── test_contract.py      선언→파서·help·schema 파생, 부적용 선택자 거절
├── test_selection.py     순서·coverage·상태·continuation 직렬화
├── test_budget.py        partial 창, continuation 체인 = 전체 선택(의미 동치), too_large 한정
├── test_read.py          재생의 선택 어휘·상태 보존·다중 id·raw 창
├── test_screen.py / test_stock.py / test_markets.py / test_calendars.py / test_news.py / test_insiders.py
├── test_install.py       한국어·공백 경로 격리 설치 (유지)
├── test_live.py          `live` 마커: 전 리프 기본 호출, continuation 의미 동치, 컨트롤 표의 각 인자 에코
└── model-scenarios.json  Claude 시나리오
```

`references/`는 만들지 않는다. 참고 파일이 맡을 내용(필터·시그널·열·맵 지표·버블 축)은 라이브 카탈로그이고 발견 명령·`choices`가 정확히 낸다. 이 스킬의 분기는 명령 선택이며 그것은 `--help`·`schema`가 계층으로 준다.

## SKILL.md 섹션 구조 (영어, 현행 언어 유지)

프론트매터는 `name`·`description`. description은 발동 경계(핀비즈 명시·URL·후속, yfinance·sec·코드 작성과의 경계, Elite·계정 제외)를 유지하고 표면 나열을 줄인다.

| 섹션 | 남는 판단 | 근거 |
|---|---|---|
| `# Finviz through one CLI` | 호출 한 줄, `CLAUDE_SKILL_DIR` 미치환 대안, zsh 한 문장, `--help`→`schema GROUP LEAF` 한 문장 | zsh는 B에서 2회 재현·C에서 0회 |
| `## Which view answers the question` | 여러 종목을 같은 지표로 비교 = 스크리너 표 한 번(`--tickers`), 한 회사의 깊이 = 개요의 절, 스크리너 조건은 원천이 정한 버킷이라 사용자의 임계값이 아니라 버킷을 보고한다 | 5종목 5요청 실측, T3-C의 버킷 경계 인지 |
| `## Meaning comes from the source` | 라벨이 측도를 특정하지 않는다, 반환된 정의·단위와 함께 읽는다, **확인되지 않은 정의는 채우지 않는다** | T2 PEG 대조. EPS 예시는 기본 모델이 알므로 제거 시험으로 존폐 결정 |
| `## Scope travels with the observation` | 행이 왔다고 조건이 적용된 것이 아니다, `conditions` 세 상태, `unverified`면 결과에서 직접 확인, 원천 정렬은 원천이 가진 창 안에서만 정렬한다 | T4 대조 |
| `## Time belongs to each observation` | `observed_at`·시세 시각·기간 종료·추정 실적일·봉 epoch의 역할 구분 | T2-C만 구분 |
| `## Follow the evidence the question needs` | 뉴스 `url`은 외부 원문, Market Pulse는 원천 생성 설명(단서), SEC 원문은 sec, 비-Finviz는 yfinance | 경계 |
| `## A window is not an inventory` | 상태를 재정의하지 않는다(정의는 `schema`가 소유). 판단만: `partial`이면 **원인을 결과에서 읽는다**(예산 절단이면 `continuation`으로 끝내거나 답에 한계 명시, 실패한 목표·원천 공백이면 이어 읽기로 메워지지 않는다), `continuation`은 요청을 끝내는 것이고 `next`는 다른 질문을 여는 것, 둘 다 없어도 완전성의 증명이 아니다 | 새 예산 계약의 의미, 코덱스 계획 검토 11 |

빠지는 것: 라우팅 문단(`--help` 사본), 맵 `value`·버블 `size`·커스텀 뷰 확인법(리프 help·schema로), "87 controls" 류 카디널리티, 절차. 각 문단은 단계 9의 **제거 시험**을 통과해야 남는다.

## TDD 단계와 완료 판정

각 단계는 `tdd` 스킬을 열어 seam(= `conftest.py`의 실제 CLI 서브프로세스 + 가짜 curl)을 확인한 뒤 **재현 테스트(레드) → 그린 → 리팩터**. 트래커는 `TaskCreate`로 열고 아래 완료 판정을 description에 그대로 적는다. 커밋은 단계 단위, 각 단계 후 `uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest tests/finviz -q`와 같은 project의 `ruff check --config pyproject.toml`.

0. **기준선** — 브랜치 `refactor/finviz-selection-contract`. 현행 오프라인 테스트 전체 통과 수와 `-m live` 결과를 기록. D1~D14 중 오프라인 재현 가능한 것을 레드 테스트로 먼저 쓴다(D1·D2·D3·D5·D7·D8·D9·D10). **완료**: 재현 테스트가 현행 코드에서 전부 실패하고 기존 테스트는 통과.
1. **선언 계층** (`contract.py`) — Leaf/Collection/Selector 선언과 파서·help·schema 파생. 운영 인자는 전 리프, 레코드 선택자는 컬렉션 있는 리프에만, 원격 위치는 `--row`/`--page`. **완료**: 모든 리프의 `--help`에 그 리프가 적용하는 선택자만 있고, `stock statement --keys x`·`schema --filter x` 같은 부적용 인자가 JSON 봉투 `invalid_argument`·exit 2이며 fix가 그 리프의 help를 가리킨다(D1·D10). `doctor --store P`·`schema --max-chars N`은 여전히 동작한다. help·schema에 개발자 사유 문장이 없다(D12, 문자열 검사 테스트).
2. **정규화** — 각 추출기가 문맥 + 레코드 컬렉션을 낸다(재무제표·매출·시세·맵·개요). 헤드라인 날짜 상속. **완료**: `stock statement --filter Revenue --fields TTM`이 한 항목·한 기간을 주고(D5), `stock overview AAPL --sections news --filter X`의 각 행에 `date`가 있다(D7), 매출의 알 수 없는 필드와 빈 계열 이름이 보존된다(현행 `test_stock.py:8-23`의 의미를 새 모양으로 유지).
3. **선택** (`selection.py`) — 한 적용 순서, 선언된 정렬, coverage, 로컬 empty 구분, 다중 절 규칙. **완료**: revisions 기본이 조합별 최신 1건이고 전부 최근 추정일(D3), short-interest 기본의 마지막 행이 원천의 최신 행, 로컬 필터 0건이 `ok`+`matched: 0`(D8), `--sections snapshot,news --fields x`가 거절되고 `--sections news --fields title`은 동작.
4. **예산** (`budget.py`) — partial 창, 같은 절 목표 동수 절단, 절별 절단, too_large 한정, 오류 문서 경계, `continuation`/`next` 분리. **완료**: 레코드가 있는 픽스처 리프 전부를 작은 `--max-chars`로 부르면 `partial` + `continuation`이고, **`continuation`을 끝까지 실행해 모은 레코드가 예산 없이 받은 요청 범위와 정확히 같다**(같은 필터·투영·순서·문맥, 요청 끝을 넘지 않음 — D2의 의미 동치). `--limit 10`에 예산이 4개만 허락하면 이어 읽기의 합이 정확히 10개다. 2종목×뉴스, 개요 2절에서도 같은 동치가 성립한다. 첫 레코드만으로 넘치는 경우는 `too_large`이고 그 fix가 실제로 들어간다. 10종목 실패에서도 문서가 예산 안.
5. **재생** (`read`) — 원 리프 선택 어휘, 다중 id, 상태 보존, 실패 관측 읽기, raw 창. `--from`·`inspect`·JSON Pointer 제거. **완료**: `partial` 관측의 read가 `partial`·exit 8, 옵션 관측을 `read ID --type put --fields strike,iv`로 읽으면 풋만·두 필드, 개요 관측에서 `read ID --section news`가 새 HTTP 없이 뉴스(D6), 추출에 실패한 관측의 `read ID`가 오류 경고를, `--raw`가 원문을 준다.
6. **표면 정리** — 개요 병합(`--sections`, 기본 스냅샷 + 절 목록·개수), `open`·`screen views`·`groups options` 제거와 그 정보의 `choices`/help 이전, 전송 fix(D9), 잘못 닫힌 값 정정(D13), `units` 선언(D11). **완료**: `schema` 무인자에 33리프, 제거된 명령이 help·schema에 없음, 전송 실패 fix가 `FINVIZ_MAX_BYTES`를 이름 붙임, `units`의 모든 항목에 대조 근거 테스트(픽스처의 표시 문자열 ↔ API 숫자).
7. **컨트롤 추가** — 위 "화면 컨트롤 → 인자" 표의 V 항목 전부, 그리고 B로 남은 것(스크리너 다중값, 버블 `sec`·`cap`·`sh_avgvol`)은 하나씩 효과를 검증한 뒤에만. 각 인자는 원천 에코가 있으면 `conditions`로 판정(에코 없으면 `unverified`, 에코가 요청을 그대로 되비추기만 하면 `unverified`). **완료**: 표의 각 인자에 오프라인 픽스처 테스트 1개 + 라이브 테스트 1개. 라이브 테스트는 에코만이 아니라 **효과**를 단언한다(값을 바꾸면 반환 레코드가 그 조건을 만족하도록 바뀐다 — 에코만 보는 테스트는 무시된 선택자를 통과시킨다). `screen run --tickers AAPL,MSFT,NVDA --view valuation`이 1요청 3행, `stock holdings SPY`가 10행 + 전체 개수.
8. **라이브 스위트** (`test_live.py`) — 전 리프 기본 호출이 `ok|partial|empty`(오류 아님), 무작위가 아닌 고정 대상(AAPL·A·SPY·오늘·실적 시즌 날짜)으로 continuation 의미 동치, 컨트롤 에코. **완료**: `-m live` 전체 통과, 실패 0.
9. **SKILL.md 재작성 + 제거 시험** — 위 섹션 구조로 쓰고, 이번 세션의 대조 방법(`claude -p --safe-mode --restricted --tools Bash,Read --allowedTools Bash Read --add-dir <cli> --model claude-opus-5-5 --append-system-prompt-file <body>`)으로 **문단 하나씩 뺀 본문**을 과제 4개 + 신규 2개(5종목 비교, 추정 수정 이력)에 돌린다. **완료**: 남은 모든 문단이 빼면 적어도 한 과제의 행동이 나빠지는 근거를 갖고, 근거 없는 문단은 삭제됐으며, 그 결과표가 "구현 완료 기록"에 있다.
10. **모델 시나리오** (`model-scenarios.json`, Claude) — 기존 8개를 새 명령으로 갱신 + 5종목 비교(1요청), 개요 여러 절(1요청), 예산 partial을 끝까지 읽거나 한계를 명시, 내부자 원천 정렬 범위 해석. **완료**: 전 시나리오 통과, 호출 수·HTTP 수 기준 충족.
11. **문서·전달** — `docs/usage.md` finviz 절(`inspect`·`too_large`·URL 문장 갱신), README 표 문구. `claude plugin validate --strict .claude/skills` exit 0(그리고 결과가 finviz를 실제로 포함하는지 확인 — 이번 세션엔 `contents: []`였다). 코덱스(`gpt-6-astra`, `danger-full-access` — 네트워크 필요, 저장소 쓰기 금지 지시) 리뷰를 **닫힌 술어**로: "D1~D14와 컨트롤 표 각 항목이 재현되지 않음을 실행으로 확인, 그리고 일반 단일 세션에서 도달 가능한 새 결함만 보고". 도달 가능한 결함 0이 될 때까지 같은 스레드에서 `resume`. PR 제목 `refactor: finviz 선택·재생 계층 재설계`, `gh pr merge --squash`, 머지 직후 `Graphify` 스킬로 그래프 리빌드(그래프 커밋은 main 직접).

## 폐기하지 않는 결정

- 전송 계층 전부와 `access_restricted`의 비우회 계약.
- 스크리너·그룹·옵션·맵·달력의 `conditions` 근거 기계: 원천 컨트롤의 에코로만 판정하고 HTTP 200은 근거가 아니다. 요청을 그대로 되비추기만 하는 에코는 확정에 쓰지 않는다(달력 sort 선례).
- 원천 값 보존: HTML 값은 원천 문자열, 라벨 중복은 별 레코드. 정규화는 구조만 바꾼다.
- 관측은 전부를 보존하고 선택은 출력에만. `--max-chars` 기본 20,000.
- 단일 JSON stdout, 침묵하는 stderr, 등급 종료 코드, 파서 파생 `schema`, 3계층 help.
- 맵 분류 트리의 자산 해석(로더·매니페스트), 스크리너 `--pages/--out/--append`.

## 폐기하는 결정

- "자르지 않고 `too_large`로 알린다" → 예산 창 + `partial`.
- 공유 선택자 6개를 모든 리프에 → 선언된 컬렉션에만.
- 개요 절별 리프와 `--from` → `overview --sections`.
- `open`, `inspect`, JSON Pointer `read`, `screen views`, `groups options`.
- "시각 렌더링 제외"는 유지(차트 이미지 URL은 이번에도 제외).

## 검증하지 않은 것 · 남은 위험

- 컨트롤 표는 **컨트롤 계열** 검증이다. 스크리너 89필터의 개별 옵션, 실적 달력 정렬 키 14개 중 ticker 외, 버블 축 enum 전체, 맵 펀더멘털 `st` 전체는 샘플만 확인했다 → 단계 7·8에서 닫힌 값마다 라이브로 확인하고, 원천이 거절하지 않고 무시하는 값은 `choices`에서 뺀다.
- 버블 `ind`, 그룹 `st`, 경제 달력 중요도·국가 필터, 옵션 `ocv`는 요청 인자로 확인되지 않아 올리지 않는다.
- 단위(D11)는 필드별로 페이지 표시 문자열과 대조해야 확정된다. 이번 세션은 세 필드의 스케일만 관찰했다.
- ETF 전체 보유 목록은 Elite다. `holdings`는 상위 10과 전체 개수만 준다고 help가 말해야 한다.
- 대조 실험은 과제당 1회 실행이다. 행동 차이의 방향은 보였지만 빈도는 모른다 → 제거 시험은 과제당 2회 이상.
- `claude plugin validate --strict`가 `.claude/skills`에서 `contents: []`를 냈다. 스킬을 실제로 검사하는 대상 경로를 단계 11에서 확인한다.
- 원천 구조는 바뀐다. 실측 수치(행 수·크기)는 2026-09-24의 것이고 계약이 아니다.

## 계획 검증 기록

- 코덱스 계획 검토(`gpt-6-astra` medium, read-only, 감사와 같은 스레드 `20260924-155649-finviz-audit-v3-7446`): 11건 — 차단 6(다중 목표·절 continuation 커서, 요청 범위 종료 규칙, 원격·로컬 `--start` 충돌, 다중 절 선택 규칙, 변형별 단위, 문맥 초과 예외), 모순 2(미검증 컨트롤을 V로 표기, too_large 예외와 합격 기준 불일치), 회귀 3(운영 인자 소실, 정규화의 필드·빈 계열 소실, 실패 관측 읽기 소실), 프레임 위반 1(SKILL.md가 `partial`을 좁게 재정의). **전부 반영했다** — 위 설계의 운영 인자/레코드 선택자 구분, `--row`, 다중 절 규칙, `continuation`/`next` 분리, 변형별 `units`, 정규화 보존 규칙, 실패 관측 읽기, 컨트롤 표의 B 표기, SKILL.md 창 절.

## 구현 완료 기록

작업 트리: `../Agentic SNS-finviz`(worktree, 브랜치 `refactor/finviz-selection-contract`). 같은 작업 트리에서 yfinance 작업이 진행 중이어서 브랜치를 바꾸지 않았다.

### 계획과 달라진 결정

| 계획 | 실제 | 이유 |
|---|---|---|
| 단계마다 커밋 | 1~5단계를 한 커밋(`363aca4`) | 리프 선언 하나가 파서·선택·예산·재생을 동시에 바꿔 중간 상태가 테스트를 통과할 수 없다 |
| 33리프 | 34리프: `calendar economic --event` 대신 `calendar event TICKER` | 이벤트 상세는 레코드 모양(이력·릴리스)이 달라 한 리프 한 모양 원칙을 깬다. 릴리스 표를 문맥에 넣자 문맥만 43,019자가 됐다(라이브 실측) |
| `earnings --dataset`, `revenue --by` | 한 페이지의 컬렉션으로 선언해 `--sections`(재생은 `read ID --section`) | 같은 응답을 다시 요청하지 않는다. `dividends`(지급·연간)·`holdings`(보유·구성)도 같은 규칙 |
| "short-interest 기본의 마지막 행이 최신" | 오래된 순으로 싣는 원천(공매도·펀드 흐름·가격 봉·연간 실적·추천 이력·연간 배당)은 뒤집어 최신순으로 낸다 | `--start`·`--limit`·continuation이 한 방향으로만 움직인다. schema의 `order`가 뒤집었음을 밝힌다 |
| 뉴스 섹션 균형 기본 창 | 로컬 선택자 `--per-section N`(기본 20) | 기본 창이 선택의 일부가 되어야 continuation이 같은 목록을 잇는다 |
| 맵 레코드 `{ticker, performance}` | `{ticker, <period>: 값}` — 필드 이름이 원천이 적용한 `subtype` | `--period pe`면 값이 성과가 아니라 P/E다 |
| coverage `exhaustive` | 제거 | 부재는 완전성의 증명이 아니라는 문장이 schema·SKILL.md에 있다 |
| continuation "실행 가능한 명령 한 줄" | `finviz.py` 뒤에 붙일 인자 한 줄(`read ID … --start N --limit M`) | 호출 접두사는 환경마다 다르다. schema `envelope`가 그렇게 설명한다 |
| 옵션 `ov=chain_date\|chain_strike\|plot` | `--strike`(API, 전 만기)와 `--all-expiries`(`ov=plot`) | chain/list는 같은 데이터의 배치다. plot은 26만기×130행사가 전체라 다른 데이터여서 올렸다 |
| 스크리너 다중값 `f=a\|b`(B) | 올리지 않음 | 익명 요청 `f=sec_technology\|healthcare`가 전 섹터 11,673건을 돌려줬다(미적용) |

### 원천 실측으로 드러난 것
- 공시 정렬: 현행 코드가 페이지에 `sort=`를 보내 무시되고 있었다(`initialSort` 불변). 페이지 인자는 `o=`. 카테고리 `f=`는 모르는 값도 되비추므로 반환 폼이 원천의 `formCategories[].forms` 안에 드는지로 판정한다.
- 추정 수정 `R`: SNX에서 `R.mean 3.798 = epsReportedEstimate`, `E.mean 4.7019 = epsEstimate` — R은 보고 기준 EPS 추정치. 단위 확정.
- 맵 `st` 54개(기간 14 + 지표 40)는 모두 `subtype`으로 되비추고, 모르는 값은 `d1`로 되돌아간다 → 에코가 적용 신호다. 장중 `i*`·포트폴리오 값은 제외.
- 버블: x/y 64개·size 7개·color 18개 모두 원천이 받는다(모르는 축은 400). 필터 `sec` 11·`cap` 14·`sh_avgvol` 18값 각각 범위대로 적용(개별 요청으로 확인). `tickers`·`excludeTickers` 적용.
- 내부자 프리셋은 페이지의 `is-active` 버튼이 에코다. 암호 `c=BTC`의 BTC 자신은 `BTCUSD`로 남는다.
- ETF `weight`는 페이지가 JS로 그려 정적 표시 문자열이 없어 단위로 올리지 않았다(`marketCap`만 AAPL 표시값과 대조).

### 단계별 실측
- 0단계: 기준선 오프라인 107 통과·라이브 49 제외. 재현 테스트 13개가 현행 코드에서 전부 실패(`xfail strict`).
- 1~6단계: 재현 13개 통과. 예산 스위트는 레코드 있는 24리프 전부에서 "작은 예산 → partial → continuation 합 = 예산 없는 답". 긴 선언 줄(500자 초과) 24개 → 9개(최장은 그룹 정렬 키 표 상수).
- 7~8단계: 오프라인 140 통과, 라이브 48 통과·1 건너뜀(목록에 Finviz 호스팅 기사가 없을 때). 라이브는 인자마다 반환 레코드로 효과를 단언한다.

### SKILL.md 제거 시험 (9단계)

Claude Opus 5.5, `claude -p --safe-mode --restricted --tools Bash,Read --append-system-prompt-file <본문>`, 과제마다 2회(FULL T1은 6회, LEAN T1은 4회). 과제 T1~T4는 이전 대조 실험 원문, T5 추정 수정 이력, T6 뉴스 건수·최다 언급 종목(창과 근거), T7 URL을 준 스크리너(H1의 URL 문장 시험용, FULL·minus-H1만). 판정은 Claude가 과제별 기준으로 했다(도구 출력은 900자로 잘려 들어가 T5 `no_fabrication`에는 잘림 때문의 오판이 섞였다). LEAN은 근거 있는 부분만 남긴 후보(H1의 zsh·schema 문장 + Meaning + 버킷 문장)다.

| criterion | FULL | LEAN | minus-H1 | minus-view | minus-meaning | minus-scope | minus-time | minus-evidence | minus-window |
|---|---|---|---|---|---|---|---|---|---|
| T1:definitions | 5/6 | 3/4 | 1/2 | 0/2 | 0/2 | 0/2 | 0/2 | 1/2 | 2/2 |
| T1:shell | 6/6 | 4/4 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T1:time_roles | 6/6 | 4/4 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T2:one_request | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T2:peg | 2/2 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T2:shell | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T2:time_roles | 2/2 | 2/2 | 2/2 | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T3:bucket | 2/2 | 2/2 | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T3:conditions | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T3:shell | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T4:coverage | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T4:shell | 2/2 | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T4:window_scope | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T5:estimate_dates | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T5:no_fabrication | 1/2 | 1/2 | 1/2 | 0/2 | 1/2 | 2/2 | 2/2 | 1/2 | 2/2 |
| T5:partial_handled | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T5:shell | 2/2 | 2/2 | 1/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T6:evidence_reason | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T6:shell | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T6:window_count | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |
| T7:shell | 2/2 | - | 2/2 | - | - | - | - | - | - |
| T7:url_to_command | 2/2 | - | 2/2 | - | - | - | - | - | - |

판정과 남긴 것:
- **H1 zsh 문장**: 빼면 T3 0/2·T4 1/2·T5 1/2 셸 실패 → 유지. **URL 문장**은 빼도 T7 2/2 → 삭제.
- **Meaning**: 빼면 T2 PEG 0/2, T1 정의 0/2 → 유지. 버킷 문장(Which view에서 옮김)은 빼면 T3 1/2 → Meaning에 합쳐 유지.
- **다종목 한 요청 문장**: 이 문장이 있는 팔은 T2 14/14, 없는 팔(minus-view·LEAN)은 3/4 → 유지. 개요 절 문장은 과제로 시험되지 않아 삭제(시나리오 `one-company-several-sections`가 확인).
- **Scope·Time·Evidence·Window**: 목표 항목(T3 조건, T4 창, T1·T2 시각, T6 근거·건수, T5 partial)에서 손실 없음 → 삭제. 이 판단들은 CLI 출력(`conditions`·`coverage`·`continuation`, schema의 봉투 설명, 컬렉션 설명의 "source-generated explanation")이 이미 싣는다.
- T1 정의는 어느 문단을 빼도 0~1/2로 흔들렸다. FULL을 6회로 늘리니 5/6, LEAN 3/4 — 잡음 범위로 보고 Meaning 외 문단의 근거로 쓰지 않았다.

### 모델 시나리오 (10단계)

스킬이 발견되는 환경(스크래치 프로젝트 디렉터리에 작업 트리의 `.claude/skills` 전체를 링크)에서 `claude -p --model claude-opus-5-5 --permission-mode acceptEdits --allowedTools Bash Read Skill Glob Grep`, 시나리오마다 자기 관측 저장소. 판정은 Claude가 `expect`와 저장소 관측 수(받은 HTTP 응답 수)로 했다.

1차(제거 시험으로 줄인 본문): 통과 6 — `followup`·`large`·`unspecified`·`compare-five`·`budget-partial`·`insider-window`. 실패 5와 그 대응:
- `code`: 코드 설계 요청에 스킬을 호출 → description 경계를 "writing or designing code that parses or calls Finviz"로.
- `compare-three`: "세 종목의 현재 지표"에 스크리너 뷰 5개를 돌려 5요청 → 다종목 문장에 뒤집히는 조건 추가: 많은 지표×적은 종목은 종목별 개요(정의 포함 스냅샷)가 더 싸다.
- `discover-then-screen`: `--sort -marketcap`이 argparse에서 거절(help가 `=` 형태를 빠뜨림 — CLI 결함, fix가 `=` 형태를 알려 주게 고침). 필터 목록을 `--filter`만 바꿔 4번 다시 받음 → "저장된 결과를 `read ID`와 그 명령의 선택자로 다시 고른다" 문장 추가(제거 시험 때 뺀 개요 절 문장이 싣던 판단).
- `explicit`: 정의가 말하지 않는 회계연도를 일반 지식으로 덧붙임(제거 시험 T1 실패 사유와 같은 행동) → Meaning에 정의의 빈칸 세 가지(회계연도 여부, EPS 기준, 성장률의 기준)를 이름 붙임.
- `one-company-several-sections`: 요청은 1회였으나 `observed_at`과 시세 시각을 구분하지 않고 `last_close`를 "현재가"로 부름 → 제거 시험에서 손실이 없어 뺀 시각 문단을 짧게 되살림(과제 T1·T2는 시각을 한 번만 말해 이 행동을 드러내지 못했다).

2차(위 대응 반영 본문): 통과 9/11. `compare-three`·`compare-five`의 기대 문구를 조정했다 — `compare-three`는 1차가 반증한 원칙("넓은 지표도 스크리너 1요청")을 담고 있어 "뷰 루프 금지, 넓은 지표면 종목별 개요 가능"으로, `compare-five`는 "정의를 읽는 개요 1회 추가 허용, 종목마다 요청 불가"로 계획의 의도(종목별 요청 금지)를 명시했다. 이후 `compare-three`가 스크리너 결과에 없는 "EPS Q/Q는 전년 동기 대비"를 단정해 실패 — SKILL.md의 예시 사실을 결과 없이 옮긴 것이어서 EPS 예시 두 개를 뺐고(계획의 "기본 모델이 이미 안다"와도 맞음), "덧붙인 원인·사실은 자기 것으로 표시한다"에 이유(독자는 표시 없는 것을 Finviz의 보고로 읽는다)를 붙인 뒤 2/2 통과.

최종 본문(마지막 사실 정정 두 문장 — `id`가 없는 오프라인 결과, `last_close`의 시각이 `as_of`·`last_time`이거나 없음 — 직전 판): 통과 8/11. 실패는 `unspecified`(Finviz 미지정 요청에 finviz 선택, 23요청)·`code`(코드 설계 요청에 스킬 호출, 조회 0)·`compare-three`(스크리너 행에 없는 정의를 표시 없이 씀). 같은 설명 문구로 2차에서는 `unspecified`·`code`가 통과했다. 시나리오별 누적(1차 이후 같은 계열 본문): `unspecified` 2/3, `code` 1/3, `compare-three` 3/6(요청 방식은 3차부터 매번 맞음), 나머지는 마지막 두 회차 모두 통과. 회차 간 분산이 커서 문구 반복 조정을 멈췄다 — 라우팅과 "표시 없는 외부 지식"은 남은 위험이다.

### 코덱스 리뷰 (11단계)
- 네 성질 검토: 초안(`20260924-174719-finviz-skill-review-2027`) — 사실 오류 4건 반영, "필드 이름을 빼고 추상 원칙으로"는 대조 실험 근거와 어긋나 따르지 않음. 최종본(`…183001-finviz-skill-review-final-bcd2`) — 네 성질 전부 ok, 사실 오류 2건 반영.
- CLI 리뷰(`gpt-6-astra` high, `danger-full-access`, 같은 스레드 5회차): 1회차 D1~D13 재현 안 됨·컨트롤 표 전 행 노출·효과 확인, 새 결함 3(시세 timeframe 설명, 다중 절 공통 상한 too_large, 실패 관측 재생의 partial→ok)+D14 잔존. 2회차 새 결함 2(다른 절을 보인 id들의 continuation 누락, 스파크라인 설명). 3회차 2(내림차순 next가 실행 불가, `-`값 오류 fix가 예시값 제안). 4회차 1(`--limit` 내보내기의 next가 받은 행 건너뜀). 5회차 **none**. 모두 재현 테스트 후 수정.
- `claude plugin validate --strict .claude/skills` exit 0. `contents: []`는 "검사 안 함"이 아니라 "문제 없음"이다 — 같은 디렉터리에 깨진 스킬을 넣으면 거기서 잡는 것을 확인했다.
- 최종 실측: 오프라인 147 통과, 라이브 48 통과·1 건너뜀, ruff 통과, 500자 넘는 줄 0.

### 남긴 한계 (`grep -rn "성진:"`)
- 로컬 선택자가 명시됐는지를 argv 문자열로 판정한다.
- 맵 로더는 진입 파일과 그 앞 번들 10개, 중첩 없는 switch만 해석한다(기존).
