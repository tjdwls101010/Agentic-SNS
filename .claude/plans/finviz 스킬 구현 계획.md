# Finviz 스킬 재작성 계획

## Context

2026-09-13에 코덱스가 구현하고 PR #10으로 머지한 `.claude/skills/finviz`를 harness-creator의 네 프레임(principle over rail, interface over document, for user not developer, dense information)으로 점검했다. 본문(SKILL.md)은 네 프레임을 통과했지만 모델이 실제로 받는 CLI 출력과 발견 경로가 미달이었다. 성진은 외과 수정 대신 전면 재작성을 택했고, 상호작용 모델은 "목적별 명령 + 자기서술 schema", 출력 계약은 "자르지 않고 선택 인자로 좁힌다"로 결정했다. 계획 단계의 추가 독립 검증 레인은 걸지 않기로 했다.

점검에서 확인한 결함은 다음과 같다. 기본 출력이 16,000자 한도에서 응답 헤더와 사이트 공통 링크에 예산을 먼저 쓰고 데이터는 깊이 5 이하를 통째로 생략해, `stock A`는 지표 84개 중 5개만 보이고 본문 사례인 `EPS next Y`가 보이지 않았다. `screen` 결과는 행의 `cells`가 생략되어 티커만 보였다. 섹션 데이터가 `initial.route-init-data`에 있다는 사실이 도움말·schema 어디에도 없어 모델이 inspect로 더듬어야 했다(PR #10의 모델 검증 기록에도 "잘못된 명령 뒤 복구"로 남아 있다). 인자 기본값이 도움말에 나오지 않았다. `catalog screen`은 컨트롤 91개·옵션 4,318개·304KB인데 검색 인자가 없었다. `catalog stock`은 `stock`과 같은 요청이었다. 설명에 한국어 트리거가 없었다. `uv run --isolated`가 매 호출 stderr에 설치 로그를 남겼다.

이 파일은 계획 세션의 유일한 산출물이며 2026-09-13 계획을 같은 경로에서 대체한다. 이전 계획의 결정과 실행 기록은 git 이력(91dee47, b6d31af)에 남으며, 이 계획이 뒤집는 결정은 아래 "폐기한 결정"에 이름을 붙여 둔다.

## 승인된 목표와 범위

목표는 Finviz를 사람처럼 필요에 따라 탐색하는 역량을 Claude Code와 Codex에 주는 것이다. 익명 Finviz가 반환하는 자료를 원문 그대로 보존하면서, 질문에 맞는 화면을 고르고, 조건이 실제로 적용됐는지 근거로 확인하고, 큰 자료는 좁혀 읽거나 파일로 모으고, 저장된 관측을 다시 읽을 수 있어야 한다. 스킬 본문은 판단 원칙만 담고, 인자·기본값·출력 형태·복구 방법은 CLI가 스스로 설명한다.

범위는 이전 계획과 같다. 종목 식별·조건검색, 기업·ETF 개요·소개·애널리스트 등급·뉴스·내부자·기관 보유·펀드 자금 흐름, 재무제표·실적 이력과 추정·추정 수정·배당·매출 구성·공매도·옵션·공시 목록·가격 봉, 그룹 표와 성과, 맵·버블, 선물·외환·암호화폐, 실적·배당·경제·실적 시즌 일정, 뉴스 목록·Finviz 자체 기사·Market Pulse, 내부자 거래, 임의 Finviz 읽기 URL. 로그인 자료, Elite 전용 자료, 변경 동작, 접근 거절 우회, 시각 렌더링, 외부 기사와 SEC 원문 추출은 제외한다. 다른 스킬과 테스트는 수정하지 않는다.

## 실측 사실 장부 (2026-09-15, 익명 curl, 약 60회 요청, 403·429 없음)

- 종목 찾기: `/api/suggestions?input=NAME` → `[{ticker, company, exchange}]`.
- 스크리너 표: `/screener?ft=4&v=111&f=…&c=…&s=…&o=…&r=N` → `table.screener_table`, 익명은 20행/페이지, `r`은 1·21·41…, 헤더 11개(No., Ticker, Company, Sector, Industry, Country, Market Cap, P/E, Volume, Price, Change %). 뷰 링크 실측: 112 Overview, 122 Valuation, 132 Ownership, 142 Performance, 152 Custom, 162 Financial, 172 Technical, 182 ETF, 192 ETF Perf(끝자리 2는 필터 패널 포함 링크, 끝자리 1은 표 요청으로 111이 실제 동작 확인). 212 Charts, 312 Basic, 322 News, 342 Snapshot, 352 TA, 412 Tickers는 표가 아니므로 제외.
- 스크리너 필터: `/screener?ft=4` 페이지의 `select#fs_<id>` 87개(fs_exch, fs_idx, fs_sec, fs_ind, fs_geo, fs_cap, fs_fa_pe … fs_theme, fs_subtheme). 선택지 값은 `cap_largeover`처럼 `<id>_<value>`로 조합한다. 라벨과 정의는 같은 행 앞 셀 `span.screener-combo-title`의 텍스트와 `data-boxover-html`에 있다(예: Market Cap. / "Total market value of a company's outstanding shares"). 적용 근거는 응답의 `selected` 옵션. 존재하지 않는 필터(`cap_bogus`)는 HTTP 200에 20행을 돌려주며 선택 옵션이 없어 `not_applied`로만 구별된다.
- 스크리너 시그널: `select#signalSelect` 34개(값은 `s=ta_topgainers` 형태의 링크에서 추출).
- 스크리너 열: `script#route-init-data`의 `tableSettings.columnsMap` 128개 `{id, title, index, categoryIndex}`, `categories`, `selectedColumns`, `availableColumns`. 커스텀 뷰는 `v=152&c=<index,…>`이고 적용 근거는 `selectedColumns`(실측 `c=1,6,7` confirmed).
- 스크리너 정렬: `orderSelect` 옵션 링크의 `o=` 값, 내림차순은 `o=-key`.
- 종목 개요 `/stock?t=A&ty=c`: `.snapshot-table2` 지표 84개(ETF는 72개), 정의는 `td[data-boxover-html]`. `EPS next Y`가 두 번 등장(정의 "EPS estimate for next year" 6.74 / "EPS growth next year" 8.75%), `EPS Q/Q` 정의는 "Quarterly earnings growth (YoY)". ETF는 `Tags` 라벨이 7번 반복. 소개문은 `.fullview-profile`, 헤더는 `.quote-header-wrapper`(회사명, Last Close, 날짜). 표 3개: 애널리스트 등급(Date, Action, Analyst, Rating Change, Price Target Change, 20행), 뉴스(헤더 없음, 시각·제목·출처, 100행), 내부자 거래(Insider Trading, Relationship, Date, Transaction, Cost, #Shares, Value ($), #Shares Total, SEC Form 4). 스크립트 JSON: `fa-init-data-0`(annual/quarterly 각 3개 시리즈 `{name, value}`), `institutional-ownership-init-data-0`(managersOwnership/fundsOwnership 각 10개 `{investorId, name, slug, percOwnership}`), `insider-init-data-0`(13개 월별 집계). ETF에는 `route-init-data-fundflows-0`(758개 `{date, aum, flow}`)가 추가되고 보유 종목 표는 익명 페이지에 없다.
- 종목 섹션(`ty=` ea·dv·rv·fc·si·oc·lf)은 같은 지표 표를 반복하고 실제 페이로드는 `script#route-init-data`에 있다. earnings: `earningsData` 116, `earningsAnnualData` 21, `earningsRevisionsData` 5,964, `priceReactionData` 12, 전체 1.56MB. dividends: `dividendsData` 40 `{Ticker, Exdate, Ordinary, Special}`, `dividendsAnnualData` 16 `{FiscalPeriod, Amount, Yield, Payout, Estimate}`, `dividendExDate`, `dividendEstimate`, `dividendTTM`. revenue: `products_and_services`·`regions`·`segment` 각 `{revenues: {이름: [{fiscal_year, report_end_date, source_filing_url, value}]}, unit}`. forecast: `targetPrice`·`targetPriceLow`·`targetPriceHigh`·`targetPriceAnalysts`·`recommendationsData` 50 `{recomDate, targetPrice, analysts, buy, overweight, hold, underweight, sell, price}` + earnings 데이터 일부. short-interest: 160개 `{timestamp, shortInterest, sharesFloat, averageVolume}`. options: `expiries` 9개, `currentExpiry`, `options` 64개(`exDate`는 260918 같은 정수, `type` put/call, iv·greeks), `e=YYYY-MM-DD`로 만기 선택하고 근거는 `currentExpiry`. filings: `entries.{items 30, page, pageSize, totalItemsCount 1144, totalPages}`, `formCategories`, `descriptions`, `availableForms`, `initialPage`·`initialSort`(-filingDate)이며 폼 필터의 서버 인자는 링크에 없다(로컬 필터만 가능).
- 재무제표: `/api/statement?t=A&so=F&s=IA|IQ|BA|BQ|CA|CQ` → `{currency, data: {"Period": [...], "Period End Date": [...], 항목명: [원문 문자열]}}`. 값은 "7,372.00" 같은 문자열이고 단위는 응답에 없다.
- 가격 봉: `/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=N` → `{date[], open[], high[], low[], close[], volume[], lastClose…}`, date는 epoch 초. 배열 길이 불일치를 오류로 다룬다.
- 그룹: `/groups?g=sector|industry|industry&sg=<sector>|…&v=110|120|140|150|160&o=key&st=…` → `table.groups_table` 헤더 14개(No., Name, Stocks, Market Cap, Dividend, P/E, Fwd P/E, PEG, LTDebt/Eq, Debt/Eq, Float Short, Recom, Change %, Volume), industry는 144행. 뷰 링크: 110 Overview, 120 Valuation, 140 Performance, 150 Custom, 160 Financial(210·310·410·510은 차트). 성과 API `/api/groups_perf?g=…` → 11개 `{ticker, label, screenerUrl, perfT, perfW, perfM, perfQ, perfH, perfY, perfYtd}`로 모든 기간이 한 번에 오므로 이전 CLI의 `--period`는 효과가 없던 인자였다. 페이지의 `groupSelect`·`orderSelect`·`orderDirSelect`가 식별자 목록.
- 시장: `/api/futures_all|forex_all|crypto_all?timeframe=d` → 티커별 `{label, ticker, last, change, changeUsd, prevClose, high, low}`, `/api/*_perf` → `{USD: 0.0, AUD: -0.19 …}` 소형 dict.
- 맵: `/api/map_perf?t=sec|geo|sec_all|cap|etf|…&st=d1` → `{nodes: {티커: 성과}, subtype, version, hash}` 817개. 분류 트리(`{name: Root, children: [{name, children: [{name, description, value}]}]}`)는 페이지가 로드하는 JS 청크 안에 있고 청크 번호는 로더의 `case …Sector:return …e(N)` 스위치, 해시는 runtime 매니페스트에서 얻는다(현재 maps.py 방식, 유일하게 JS 번들 파싱에 의존). 맵 `value`는 시가총액과 기준이 다르다. 버블 `/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=sp500` → 503개 `{ticker, company, x, y, size, color, isETF}`.
- 일정: `/calendar/earnings?page=1&sort=earningsDate`·`/calendar/dividends?page=1` → `route-init-data.data.{initialDateFrom, initialSort, initialPage, entries: {items, page, pageSize, totalItemsCount, totalPages}}`(dividends 304건 50/페이지). `/api/calendar/earnings?dateFrom=YYYY-MM-DD&page=1&sort=…`는 dateFrom 없이 400. `/calendar/economic` → `entries` 목록(`{calendarId, ticker, event, category, date, reference, actual, previous, forecast, teforecast, importance}`) 페이지 없음. `/calendar/earnings/season-preview` → `entries` 64건, `totalsPerDay`, `totalCount`.
- 뉴스: `/news`(v=3 기본)는 News·Blogs 표 2개 각 90행(시각, 제목, 링크). v=2는 출처별 표 48개(12행), v=4 ETF, v=5 암호화폐, v=6 Market Pulse 100행(`tr[data-wiim-trigger]`가 pulse id, 셀은 경과 시간과 헤드라인). `/api/stocks-why-moving/by-id/ID` → `{id, ticker, dateTime, headline, summary(markdown), source, sentiment, catalyst, bulletPointsList}`. Finviz 자체 기사 `/news/<id>/<slug>`는 `article` 본문.
- 내부자: `/insidertrading?tc=7|1|2&oc=…&o=…&tv=…` → `#insider-table` 헤더 10개(Ticker, Owner, Relationship, Date, Transaction, Cost, #Shares, Value ($), #Shares Total, SEC Form 4) 200행, 링크는 종목·소유자·SEC 원문.
- 접근 실패 형태: 존재하지 않는 티커는 404, Cloudflare 확인 화면은 `#challenge-form`·"just a moment", 제한은 401·403·429와 `Retry-After`.
- 실행 환경: uv `--isolated`는 매 호출 "Installed 10 packages"를 stderr에 찍고 0.27초 걸린다. `.claude/skills/finviz/.venv/`는 이미 gitignore되어 있다. 저장소 ruff는 line-length 120, `E4 E7 E9 F`. CI는 `.github/workflows/finviz.yml`이 `tests/finviz`와 ruff를 돌린다. PR 템플릿은 없다. `graphify-out`은 주 작업 폴더에 없다. 이전 worktree `/private/tmp/agentic-sns-finviz`는 prunable 상태다.

## 설계

### 실행과 인터페이스

Python 3.11+, 시스템 curl 8.4+, uv 잠금 환경, Beautiful Soup 4.15.0과 JSON5 0.15.0(맵 자산 리터럴 전용)만 의존한다. Aside와 JavaScript 실행은 쓰지 않는다. 호출은 `uv run -q --frozen --project "${CLAUDE_SKILL_DIR}" python "${CLAUDE_SKILL_DIR}/scripts/finviz.py" GROUP LEAF …`이며 `-q`로 설치 로그를 없애고 `.venv/`는 스킬 폴더에 남긴다.

명령은 yfinance와 같은 GROUP LEAF 구조다. 공통 옵션은 GROUP 앞에 한 번만 둔다: `--max-chars`(기본 20000), `--filter TEXT`(발견 명령과 `--list-fields`의 대소문자 무시 부분 일치), `--fields a,b`, `--limit N`, `--store PATH`(기본 `~/.cache/finviz-skill/observations.sqlite3`, 환경변수 `FINVIZ_STORE`), `--connect-timeout`·`--timeout`·`--max-bytes`(10초·60초·16MiB). `schema [GROUP [LEAF]]`는 오프라인으로 그룹·리프의 한 줄 의미, 인자별 help·default·choices·required, 출력 키와 의미, 상태·종료 코드를 argparse 정의에서 생성한다(문서 사본이 아니라 파서에서 파생하므로 어긋날 수 없다). 모든 인자에 `help`, 닫힌 선택지는 `choices`, 기본값은 도움말에 표시한다.

| GROUP | LEAF | 원천 | 주요 인자 | data |
|---|---|---|---|---|
| schema | – | 오프라인 | `[GROUP [LEAF]]` | 위 설명 |
| doctor | – | 오프라인 | – | python, curl, store 경로, 오류 |
| search | – | suggestions | `NAME` | `[{ticker, company, exchange}]` |
| screen | filters | screener?ft=4 | `--filter` | `[{id, label, definition, options: [{value, label}]}]` (값은 `id_value` 조합 형태로 제공) |
| screen | signals | 같은 페이지 | `--filter` | `[{value, label}]` |
| screen | columns | route-init-data | `--filter` | `[{id, title, index, category}]` |
| screen | views | 고정 choices | – | `[{name, view_id, description}]` |
| screen | run | screener | `--filters a,b` `--signal` `--view {overview,valuation,ownership,performance,financial,technical,etf,etf-performance,custom}` `--columns id,…` `--sort key` `--start N` `--pages N` `--out PATH` `--append` | `[{헤더: 셀 문자열, ticker, url}]`; `--out`이면 행은 JSONL로 가고 stdout은 요약 |
| stock | snapshot | stock?ty=c | `TICKER…` `--filter` | `{name, last_close, as_of, metrics: [{label, value, definition, unit}]}` |
| stock | profile | 같은 페이지 | `TICKER` | `{name, description, links}` |
| stock | ratings | 같은 페이지 | `TICKER` | 등급 표 행 dict |
| stock | news | 같은 페이지 | `TICKER` | `[{time, title, url, source}]` |
| stock | insiders | 같은 페이지 | `TICKER` | 내부자 표 행 dict + 월별 집계 |
| stock | ownership | 같은 페이지 | `TICKER` | `{managers, funds}` |
| stock | flows | 같은 페이지(ETF) | `TICKER` `--limit` | `[{date, aum, flow}]`; 주식이면 empty |
| stock | earnings | ty=ea | `TICKER` `--dataset {quarterly,annual,revisions,reaction}` `--fiscal-period` | 선택한 데이터셋 원문 레코드 |
| stock | forecast | ty=fc | `TICKER` | `{target_price…, recommendations}` |
| stock | dividends | ty=dv | `TICKER` | `{ex_date, estimate, ttm, payments, annual}` |
| stock | revenue | ty=rv | `TICKER` `--by {products,regions,segment}` | `{unit, series: {이름: [...]}}` |
| stock | short-interest | ty=si | `TICKER` `--limit` | 원문 레코드 |
| stock | options | ty=oc | `TICKER` `--expiry` `--type {call,put}` | `{expiries, current_expiry, last_close, contracts}` |
| stock | filings | ty=lf | `TICKER` `--page` `--sort` `--form` (로컬 필터) | `{items, form_categories}` + coverage·continuation |
| stock | statement | api/statement | `TICKER` `--kind {income,balance,cashflow}` `--period {annual,quarterly}` | `{currency, periods, period_end_dates, items: {항목: [문자열]}}` |
| stock | prices | api/quote | `TICKER` `--instrument {stock,futures,forex,crypto}` `--timeframe` `--bars` | `[{date_epoch, open, high, low, close, volume}]` + 원문 last 필드 |
| groups | options | groups 페이지 | – | group·order 식별자 목록 |
| groups | table | groups | `--group` `--view {overview,valuation,performance,financial,custom}` `--sort` | 행 dict |
| groups | performance | api/groups_perf | `--group` | 원문 레코드 |
| market | quotes | api/*_all | `{futures,forex,crypto}` `--timeframe` | 티커별 원문 |
| market | performance | api/*_perf | `{futures,forex,crypto}` | 원문 |
| market | map | api/map_perf + 자산 | `--type` `--period` `--performance-only` | `{performance, classification, classification_source}` |
| market | bubbles | api/bubbles | `--x --y --size --color --index` | 원문 레코드 |
| calendar | earnings, dividends, economic, season | calendar 페이지 | `--date` `--page` `--sort` | `{items}` + coverage·continuation |
| news | headlines | news?v= | `--kind {latest,by-source,stocks,etfs,crypto}` | `[{time, title, url, source, ticker}]` |
| news | pulse | news?v=6 / by-id | `[ID]` | 목록 또는 상세 |
| news | article | news/<id>/<slug> | `URL` | `{title, paragraphs, links, images}` |
| insiders | trades | insidertrading | `--transaction {all,buy,sale}` `--owner` `--sort` `--value` | 행 dict + 링크 |
| open | – | 허용된 Finviz URL | `URL` | 범용 추출 `{metrics, tables, initial, controls, article, links}` |
| read | – | 저장소 | `ID` `--pointer` `--start` `--limit` `--raw` | 저장 관측의 일부 |
| inspect | – | 저장소 | `ID` | 포인터·타입·개수 목록 |

`stock`의 snapshot·profile·ratings·news·insiders·ownership·flows는 같은 개요 페이지에서 각자 필요한 부분만 추출한다. 호출마다 새 관측이며 캐시하지 않는다. 여러 티커를 받으면 결과를 티커별로 나눈다.

### 출력 계약

stdout은 JSON 한 문서, 진단은 stderr. 봉투는 yfinance와 같다: `{"status", "results": [{"target", "request", "id", "observed_at", "source": {"url", "http_status", "redirects"}, "conditions", "coverage", "continuation", "status", "data", "warnings", "error"}]}`. 비어 있는 `conditions`·`coverage`·`continuation`·`warnings`·`error`는 생략한다. 응답 헤더와 사이트 공통 링크는 출력하지 않고 저장소에만 둔다(`read ID --raw`, `inspect`로 접근). 상태는 ok·empty·partial·error, 종료 코드는 0 ok·2 invalid·5 rate_limited·6 upstream·7 empty·8 partial·9 too_large.

`--max-chars`를 넘으면 잘라내지 않고 `too_large` 오류를 내며, 오류의 `fix`는 그 리프가 실제로 가진 좁히기 인자(`--fields`, `--filter`, `--limit`, `--dataset`, `--out`)와 `read ID --pointer`를 이름으로 안내한다. 관측은 오류와 무관하게 저장되므로 같은 자료를 다시 받지 않고 부분 읽기할 수 있다.

`conditions`는 모델이 고른 인자만 담는다(필터, 시그널, 열, 정렬, 페이지, 날짜, 만기, 통계 기간). 라우팅 상수(`ft`, `v`, `t`, `ty`, `so`, `s`)는 담지 않는다. 각 항목은 `{requested, status: confirmed|not_applied|unverified, evidence}`이며 HTTP 성공만으로 confirmed가 되지 않는다. `coverage`는 `{received, source_total, exhaustive: false, pagination_end}`, `continuation`은 다음 페이지를 얻는 인자(`{"start": 21}` 또는 `{"page": 2}`)다.

표는 헤더를 키로 한 dict 행이고 셀은 원문 문자열이다(단위·기호 유지, 숫자 변환 없음). 같은 이름이 반복될 수 있는 지표는 레코드 목록으로 유지해 `EPS next Y` 두 값과 ETF의 `Tags` 일곱 개를 합치지 않는다. JSON API 값은 원문 그대로다. 결측은 null이며 0으로 바꾸지 않는다. 가격 배열 길이가 다르면 정렬된 봉을 만들지 않고 `array_alignment` 오류와 원문 배열을 남긴다.

`screen run --pages N`은 한 호출에서 최대 N페이지를 `continuation`을 따라 읽고, `--out PATH`이면 행을 JSONL로 파일에 쓰며 stdout에는 페이지 수·행 수·조건·다음 `--start`만 남긴다. 기존 파일은 `--append` 없이는 거절한다. 재개는 반환된 `--start`와 같은 `--out --append`로 한다. 변하는 목록을 한 시점의 완전한 집합으로 주장하지 않는다(`exhaustive: false`).

리디렉션은 최대 5회, 목적지도 Finviz 읽기 URL이어야 한다. 401·403·429는 `access_restricted`와 `Retry-After`를 보고하고 우회하지 않는다. Cloudflare 확인 화면은 `access_restricted`, 지원 구조가 없으면 `structure_changed`다.

### 디렉터리 구조 (목표 형태이며 모듈 수는 계약이 아니다)

```
.claude/skills/finviz/
├── SKILL.md
├── pyproject.toml          # bs4, json5; dev: pytest, ruff
├── uv.lock
└── scripts/
    ├── finviz.py           # 파서, 디스패치, schema 생성, main
    ├── output.py           # 봉투, 상태·종료 코드, --fields/--filter/--limit 선택, too_large
    ├── transport.py        # URL 검증, curl, 리디렉션, SQLite 관측 저장소
    ├── html.py             # 표→dict 행, 지표 레코드, script JSON, 컨트롤, 기사, 링크
    ├── screener.py         # filters/signals/columns/views/run, 조건 근거, 페이지·JSONL
    ├── stock.py            # 개요 파생 리프, 섹션 리프, statement, prices
    ├── markets.py          # groups, market quotes/performance, map(자산 해석), bubbles
    └── feeds.py            # calendar, news, insiders, open
tests/finviz/
├── conftest.py             # curl 대체 seam(기존 패턴 유지), 응답 매핑, 임시 store
├── fixtures/               # 실서비스에서 기록한 축약 HTML·JSON (*.html, *.json)
├── test_cli.py             # 리프별 오프라인 계약 테스트
├── test_schema.py          # schema 출력이 파서·실제 data 키와 일치
├── test_install.py         # 한글·공백 경로에서 독립 실행, stderr 무음
├── test_live.py            # -m live, 리프별 실서비스 1건
└── model-scenarios.json    # 모델 시나리오
```

### SKILL.md 골격

frontmatter: `name: finviz`, `description`은 다음 초안을 다듬는다. "Read publicly accessible Finviz data through a self-describing CLI: stock screening with Finviz filters and signals, company and ETF snapshots, statements, earnings history and estimates, dividends, revenue breakdown, short interest, options, SEC filing lists, price bars, sector and industry groups, market maps and bubbles, futures, forex and crypto quotes, earnings, dividend and economic calendars, news, Market Pulse and insider trades. Use when the user names Finviz — 핀비즈, 핀비즈에서, finviz 스크리너, 핀비즈 맵 — or supplies a finviz.com URL, and for follow-up questions continuing that work. Not the default for source-unspecified price, screening or financial-statement questions (yfinance covers those), not for Finviz account changes or Elite-only data, not for reading SEC originals or external articles, and not for writing Finviz-related code."

본문은 ultra-search·yfinance 스타일의 `#`/`##` 사실+결과 문단이며 명령 표를 두지 않는다.

- `# Finviz through one CLI`: 호출 한 줄, `${CLAUDE_SKILL_DIR}` 미치환 시 대처, 도움말과 `schema`가 인자·기본값·출력·복구를 소유하므로 여기 반복하지 않는다는 문장.
- `## Which surface the question needs`: 조건으로 찾는 질문은 screen, 한 종목의 현재 수치는 snapshot, 보고된 결과와 추정은 statement·earnings·forecast, 집계는 groups·map, 사용자가 URL을 줬으면 open. 크기가 판단을 바꾸는 사례로 earnings revisions 5,964건을 든다.
- `## Meaning comes from the source`: `EPS next Y` 중복과 `EPS Q/Q` YoY 툴팁, ETF `Tags` 반복, 표 셀은 원문 문자열이라 단위가 셀 안에 있다는 사실.
- `## Scope travels with the observation`: 조건 근거(confirmed·not_applied·unverified), 존재하지 않는 필터도 200과 20행을 돌려준다는 사례, 페이지 수집이 시점 완전 집합이 아니라는 원칙.
- `## Time belongs to each observation`: 관측 시각·시장 시각·보고 기간·추정 일자, 맵 가중치와 시가총액의 기준 차이.
- `## Follow the evidence the question needs`: 뉴스 목록은 위치만, Market Pulse는 출처 생성 설명, Finviz 기사만 본문 읽기, 외부 기사와 SEC 원문은 각 스킬로.
- `## When a result is too large`: too_large는 실패가 아니라 좁히라는 신호이며 관측은 이미 저장돼 있다는 한 문단.

## 폐기한 결정 (이전 계획·구현을 뒤집는 항목)

- 잘라내는 미리보기(`preview`, 깊이 5 생략, `--full`) → too_large 오류와 선택 인자.
- 텍스트 모드와 `--json` 플래그 → JSON 단일 출력.
- 범용 HTML 묶음(article·embedded·navigation·initial·controls·tables·metrics)을 모든 명령의 공개 data로 → 리프별 형태, 범용 묶음은 `open`에서만.
- `catalog SURFACE` → `screen filters|signals|columns|views`, `groups options`. `catalog stock`은 제거.
- `collect`와 `c_` 수집 ID, 전체 관측 JSONL 내보내기 → `screen run --pages/--out/--append`와 `continuation`.
- `groups --period` → 제거(성과 API가 모든 기간을 한 번에 반환).
- `uv run --isolated` → `uv run -q --frozen`.
- 라우팅 상수까지 `conditions`에 unverified로 나열 → 모델이 고른 인자만.

## 단계와 완료 판정

| 단계 | 파일 | 완료 판정 |
|---|---|---|
| 1 실행 기반 | output, transport, finviz(schema), search, read, inspect, doctor, conftest, test_schema, test_install | 오프라인 테스트 통과. `schema`가 모든 리프의 인자·기본값·choices를 파서에서 출력하고 test_schema가 이를 검증. `search Agilent` 실서비스에서 `[{ticker:"A"…}]`. 한글·공백 경로 설치 테스트에서 stderr가 비어 있음 |
| 2 스크리너 | screener, html | filters가 87개 id·라벨·정의를, `--filter cap`으로 1개만 반환. run이 `--filters sec_technology,cap_largeover`를 confirmed, `cap_bogus`를 not_applied로 보고. `--columns` confirmed, `--pages 3 --out`이 60행 JSONL과 `continuation.start 61`. 60행이 `--out` 없이 too_large를 내고 fix가 `--out`·`--fields`를 이름으로 안내 |
| 3 종목 | stock | snapshot이 `EPS next Y` 두 레코드를 다른 정의로 보존. profile·ratings·news·insiders·ownership·flows 각각 픽스처 테스트. earnings 기본이 quarterly 116건, `--dataset revisions`가 too_large와 `--fiscal-period`·`--limit` 안내. options `--expiry` confirmed. statement periods와 items 길이 일치. prices 길이 불일치가 `array_alignment`. SPY flows 758건 `--limit` |
| 4 그룹·시장·일정·뉴스·내부자·open | markets, feeds | 각 리프 픽스처 테스트와 실서비스 1건. map 분류 트리 해석 실패가 partial과 성과 데이터 보존. calendar dividends coverage source_total 304와 continuation page 2. news pulse ID 상세. insiders 200행 dict와 SEC 링크. open이 외부 URL을 unsupported_url로 거절 |
| 5 스킬 본문·설명 | SKILL.md | `validate_harness.py` 오류 0·경고 0. 설명을 yfinance·sec 설명과 나란히 읽어 겹침 없음. 본문에 명령 표·개발 이력 없음, 각 문단이 판단을 바꾸는 사실 하나 이상 |
| 6 전체 검증·전달 | tests, 계획 파일 | 오프라인·live 전부 통과, ruff 통과, 모델 시나리오 Claude Code·Codex 각 5건 PASS(아래), 코덱스 최종 리뷰 지적 0건 잔존, PR squash merge, 계획 파일 실행 기록 갱신 |

각 단계는 `tdd` 스킬을 열어 seam(공개 CLI 입력·출력·종료 상태·저장 결과, curl만 대체)을 확인하고, 실패 테스트를 먼저 보고 최소 구현한다. 단계 2·4·6 뒤에 `codex` 스킬(gpt-6-astra, high)로 코드 리뷰를 받고 지적은 재현 테스트와 함께 고친 뒤 run_id를 실행 기록에 남긴다.

## 재사용 지도

- `tests/finviz/conftest.py`의 curl 대체 seam과 `FINVIZ_STORE` 주입은 그대로 쓴다.
- 기존 `runtime.py`의 URL 허용 목록·리디렉션 검증·curl 인자·SQLite 스키마, `extract.py`의 지표·표·script JSON·Cloudflare 감지·조건 근거(selected 옵션, selectedColumns, pageSelect, currentExpiry·initialPage·initialSort·initialDateFrom), `maps.py`의 로더 케이스·runtime 해시 해석은 새 모듈로 옮겨 쓴다. 코드 골격은 새로 쓰되 검증된 선택자와 정규식은 유지한다.
- `.claude/skills/yfinance/Scripts/output.py`의 봉투·상태·종료 코드·`select`(fields/list-fields/limit)와 `too_large` 문구 형식을 따른다(pandas 의존은 가져오지 않는다).
- `tests/finviz/model-scenarios.json`의 explicit·followup·unspecified·code 시나리오는 유지하고 partial을 "earnings revisions too_large를 좁혀 읽되 없는 값을 만들지 않는다"로 바꾼다.
- `.github/workflows/finviz.yml`은 경로가 같으므로 수정하지 않는다.

## 검증

- 오프라인: `uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest tests/finviz -q`.
- 실서비스: 같은 명령에 `tests/finviz/test_live.py -m live`, 리프당 1건, 원문은 로컬 저장소에만.
- 정적: `ruff check --config pyproject.toml .claude/skills/finviz/scripts tests/finviz`, `python3 /Users/seongjin/.claude/skills/harness-creator/scripts/validate_harness.py --path . --json`.
- 인터페이스 일치: test_schema가 `schema GROUP LEAF`의 인자 목록을 파서에서, 출력 키를 픽스처 실행 결과에서 대조한다.
- 모델 시나리오: PR #10과 같은 방식으로 Claude Code(`claude -p`, 실제 기본 모델)와 Codex exec에서 5개 시나리오를 돌리고 독립 코덱스 판정을 받는다. 판정 기준은 호출 순서가 아니라 답의 근거(원문 정의 인용, 조건 근거 언급, 없는 값을 만들지 않음, 출처 미지정에서 Finviz 미호출, 코드 요청에서 미호출).
- 트리거 근접 사례: "미국 주식 시가총액 1,000억 이상 스크리닝"(yfinance 또는 판단), "핀비즈에서 반도체 섹터 상위 20개", "이 링크 읽어줘 https://finviz.com/quote.ashx?t=AAPL", "Finviz 파서 함수 인터페이스 제안".

## 위험과 대응

- Finviz HTML·API 구조 변경: 선택자를 모듈당 한 곳에 모으고 `structure_changed`로 원문을 보존한다. live 테스트가 감지한다.
- 맵 분류 트리의 JS 번들 의존: 실패 시 성과 데이터는 ok, 분류는 partial. `# 성진:` 주석으로 한계를 남긴다.
- 접근 제한·Cloudflare: 실측 60회에 제한 없었으나 `Retry-After`를 존중하고 우회하지 않는다. live 테스트는 리프당 1건으로 제한한다.
- 필터 라벨 추출: `screener-combo-title`과 `select#fs_*`가 같은 행에 있다고 실측했으나 행 구조가 다른 필터(theme·subtheme)는 1단계에서 확인한다.
- 재무제표 단위: 응답에 없으므로 추측하지 않고 schema에 "원문 문자열, 단위 미제공"으로 적는다.

## 가정

- 익명 접근만으로 범위의 모든 화면이 열린다(2026-09-15 실측). Elite 전용 항목(`data-elite-only`)은 발견 명령에서 표시만 한다.
- 스크리너 뷰 181·191(ETF)은 111과 같은 표 구조다. 2단계 live에서 확인하고 다르면 choices에서 뺀다.
- 구현은 `main`에서 `feat/finviz-skill-rewrite` 브랜치를 파 주 작업 폴더에서 진행한다. prunable worktree 두 개는 건드리지 않고 알린다.
- 2026-09-16 주 작업 폴더에 `graphify-out/`이 있음을 재확인했다. 이전 부재 판단을 정정하고 머지 후 Graphify를 리빌드한다.
- 커밋·PR 제목은 `feat: Finviz 스킬 재작성` 형식, PR 본문은 무엇을 바꿨나·왜·영향·검증 4섹션.

## 코덱스 반영

계획 단계 독립 리뷰는 성진의 결정으로 걸지 않았다. 구현 단계 2·4·6의 코덱스 리뷰 run_id와 반영 내용은 실행 기록에 적는다.

## 실행 기록

### 2026-09-16 최종 리뷰 후속 수정

이번 세션은 부모가 승인한 재작성의 최종 리뷰 12개 OPEN_ITEMS만 수정했다. 변경 범위는 `.claude/skills/finviz/`, `tests/finviz/`, 이 계획 파일로 한정했고 커밋·푸시·브랜치 변경·새 에이전트 실행은 하지 않았다. 최종 PR·머지 내역은 부모가 기록한다. 시작 시 이미 수정되어 있던 SKILL.md의 이상치 원칙(관측값을 임의로 오류라 배제하거나 근거 없는 원인을 붙이지 않음)은 보존했다. 기존의 다른 경로 변경은 손대지 않았다.

TDD 지침은 `/Users/seongjin/.codex/skills/tdd/SKILL.md`에서 읽어 적용했다. 이 실행 환경에는 Skill 호출 도구 및 TaskCreate/TaskUpdate/ToolSearch가 노출되지 않아 호출·트래커 생성은 할 수 없었다. 사용자에게 이미 승인받은 seam(실제 CLI subprocess 입력·출력·종료 코드·저장 관측, 외부 curl만 대체)을 재확인한 것으로 처리하고 질문 없이 진행했다. 동작 수정은 항목별 재현 실패 확인 → 최소 수정 → 해당 테스트 통과 순으로 진행했다. 문서의 네 가지 오류는 기존 CLI 동작을 먼저 재현·검증한 뒤 설명만 바로잡았으며, 이를 억지로 코드 실패/수정으로 만들지 않았다. 완료 판정은 아래 각 재현의 통과와 전체 오프라인·Ruff 결과이며, 라이브·모델 시나리오 실패는 별도로 사실대로 남긴다.

확인한 기존 리뷰 ID는 단계 2 `20260915-200755-finviz-stage2-review-0062`, 단계 4 `20260915-202842-finviz-stage4-review-2f98`, 최종 `20260915-204017-finviz-final-review-cb3c`이다. 최종 결과는 `python3 /Users/seongjin/.claude/skills/codex/scripts/codex_bridge.py result --run 20260915-204017-finviz-final-review-cb3c`로 읽었다. 단계 2·4 로그와 기존 테스트도 읽었고, 추가 독립 리뷰 에이전트는 실행하지 않았다.

| 최종 OPEN_ITEM | 수정·완료 판정 | 검증 |
|---|---|---|
| 이전 지적: 합산 start 불일치 | 두 번째 `r=21` 응답이 첫 페이지를 돌려주면 합산도 `not_applied`, 페이지별 근거·원문 행은 그대로 보존 | `test_aggregate_reports_a_later_page_returning_the_wrong_start` 실패 → 통과 |
| 이전 지적: economic page 무시 | `calendar economic --page 2`를 날짜 유무와 관계없이 `invalid_argument`, 종료 2로 거절 | `test_economic_calendar_rejects_unsupported_pagination_before_fetching` 2경우 실패 → 통과 |
| 이전 지적: map/bubbles 조건 누락 | map `type`, bubbles `x/y/size/color/index`를 저장·출력하며 확인 근거 없는 선택은 `unverified` | `test_map_and_bubbles_report_selectors_without_inventing_confirmation` map·bubbles 누락을 차례로 재현 → 통과 |
| 이전 지적: revenue/quotes 계약 변경 | revenue `{unit,series}`, quotes 티커 키 객체 복원; `--fields`는 각각 시리즈명/티커 키, `--filter`와 `--limit`으로 축소 가능 | 기존 형태 테스트 수정 후 실패 → 통과; revenue·quotes selection 테스트로 단위·출처 URL·추가 원문 필드·키·전체 저장 자료 확인 |
| 이전 지적: 일반·표 메뉴 노출 | 본문 컨테이너 밖의 사이트 메뉴 링크를 표 추출 전에 제외; 쿼리가 있는 자료 링크·외부 출처·헤더 없는 실제 표 보존 | `test_open_excludes_plain_and_table_navigation_without_removing_data_links` 실패 → 통과 |
| N1: 큰 합산 자료에서 후속 페이지 복구 불가 | `--pages > 1`은 별도 합산 ID에 선택 전 모든 행과 `source.pages` 저장; 각 페이지 ID는 독립 원문·자료를 유지 | `test_oversized_aggregate_and_every_page_are_recoverable_without_fetching` 실패 → 통과; 빈 export 선택에도 저장된 전체 행이 남는 테스트 추가 |
| N2: 내부에서 잡힌 실패가 ok로 저장 | 공유 `Failure.record()`를 최상위·스크리너·맵의 실패 처리에서 사용; 원래 오류와 raw 읽기 경고 보존 | `test_caught_later_page_failure_is_saved_with_original_error` HTTP 429·구조 변경 2경우 실패 → 통과; 맵 자산 실패 저장도 검증 |
| N3: 기사 header 삭제 | article/main/본문 컨테이너의 헤더·제목·작성자·본문 링크 보존 | `test_open_preserves_article_headers_and_content_links_like_the_article_reader` 실패 → 통과 |
| 문서: leaf help가 모든 기본값을 설명 | root help는 공통 옵션, leaf help는 자체 인자, schema는 공통 인자와 기본값 포함으로 정정 | `test_help_and_schema_disclose_shared_defaults_and_parser_errors_use_stderr` |
| 문서: 일반 /data 부분 읽기 보장 | `inspect`로 실제 컬렉션 포인터를 찾으며 earnings는 `/data/records`; 큰 개별 레코드는 더 작게 선택한다고 설명 | `test_nested_earnings_recovery_requires_the_record_pointer_not_the_data_object` |
| 문서: 모든 오류에 fix | JSON 오류와 stderr usage·종료 2인 argparse 오류를 구분 | bogus earnings dataset의 stdout 공백·stderr invalid choice 검증 |
| 문서: 모든 결과에 conditions/coverage | 두 필드가 선택적으로 존재하며 부재가 확인·완전성을 뜻하지 않는다고 정정 | profile 결과에 두 필드가 없는 사실을 CLI에서 검증 |

복원한 객체 인터페이스에서도 저장 자료를 선택할 수 있도록 `read --start/--limit`은 선택한 객체의 키도 자른다(그 안의 중첩 컬렉션까지 자르지는 않음). 매출 시리즈 포인터를 읽으면 상위 `unit`을 `selection.unit`에 동반해 값의 문맥을 보존한다. 합산의 `read ID --raw`는 합산 JSON이며, 실제 HTTP 원문은 `source.pages`의 각 ID에서 읽도록 schema에 명시했다. 합산은 첫 페이지 HTTP 메타데이터를 전체 자료의 출처로 가장하지 않고 페이지 ID 목록을 출처로 삼는다. navigation의 무쿼리 화면 링크 판정 한계와 바꿀 조건은 해당 코드의 `# 성진:` 주석에 남겼다.

데이터·신뢰 경계 점검: quotes는 source key를 ticker 필드로 재구성하지 않아 ticker 필드가 없거나 중복되어도 자료를 잃지 않는다. revenue의 fiscal year·report end·SEC URL·unit·새 원문 필드, bubbles의 새 필드, 스크리너 문자열과 페이지 관측 ID를 보존하는 assertions가 통과했다. 로컬 선택 전 전체 자료는 저장소에서 다시 읽힌다. HTTPS/호스트/route 허용 목록·리디렉션 검증·중복 JSON 키 거절·응답 크기 제한 코드는 완화하지 않았다. 기존 외부 URL·금지 경로·외부 리디렉션·검증 화면·배열 정렬 검증도 전체 오프라인 실행에 포함되어 통과했다.

검증 명령에서 `SCRATCH`는 `/private/tmp/claude-501/-Users-seongjin-Coding-Agentic-SNS/38f4ee2d-bba5-4734-a290-ce66cf434485/scratchpad`를 뜻한다. 임시 테스트 디렉터리·curl 임시 응답·로그·라이브 저장소·변경 전 재생 사본은 이 경로에 두었다. 테스트는 `TMPDIR="$SCRATCH" PYTHONDONTWRITEBYTECODE=1`로 실행했고 pytest 캐시를 비활성화했다.

- 최종 오프라인: `uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest -p no:cacheprovider --basetemp "$SCRATCH/finviz-repairs-pytest" tests/finviz -q` → **71 passed, 41 deselected, 44.87s**, 종료 0. 독립 설치/한글·공백 경로 테스트 포함. 로그: `$SCRATCH/finviz-repairs-offline.log`.
- 정적: `uv run -q --frozen --group dev --project .claude/skills/finviz ruff check --no-cache --config pyproject.toml .claude/skills/finviz/scripts tests/finviz` → **All checks passed**, 종료 0. 레포의 Ruff 설정을 따랐고 문단은 수동 하드랩하지 않았다.
- 라이브: `uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest -p no:cacheprovider --basetemp "$SCRATCH/finviz-repairs-live" tests/finviz/test_live.py -m live -q` → **40 passed, 1 failed, 53.74s**, 종료 1. 실패는 `market map --type geo --fields classification_source,period`: `asset_structure`, `The loader has no case for World.`, partial/종료 8. 성과 자료는 저장되고 분류만 비어 있다. 로그: `$SCRATCH/finviz-repairs-live.log`.
- 라이브 실패 분리: 위 실행에서 저장한 응답만 curl 대체에 공급해 `git show HEAD`로 얻은 수정 전 전체 CLI와 수정 후 CLI를 동일 입력으로 재생했다. 둘 다 동일한 `World` loader 오류·partial·종료 8이다. 이번 변경에서 발생한 회귀는 아니며 JS 분류 로더 변경은 12개 지적 밖이라 확장 수정하지 않았다. 결과: `$SCRATCH/finviz-map-replay/HEAD.json`, `$SCRATCH/finviz-map-replay/repaired.json`. **전체 라이브 통과를 막는 잔여 항목**으로 부모에게 전달한다.
- 합산 복구 라이브 확인: 실제 CLI에 `--max-chars 1000 screen run --pages 2` → 종료 9, 반환 ID의 `/source/pages` → 2개 독립 ID, `/data --start 20 --limit 1` → 둘째 페이지 첫 행과 일치, 둘째 페이지 `/conditions/start` → requested 21/evidence 21/confirmed. **PASS**, 합산 ID `7b46986fa39f4c6c94cde46a7b21d247`. 전체 호출 인자·출력: `$SCRATCH/finviz-repairs-live-aggregate.json`; 저장소: `$SCRATCH/finviz-repairs-live-aggregate.sqlite3`.
- 모델 시나리오: 판정 run `20260915-203906-finviz-scn-grader-a2c2`의 **9 PASS·1 FAIL**을 유지한다. FAIL은 Claude Code `large`: 2025-02-14 mean 5.2783을 근거 없이 오류 취급, 연중 안정·관세 해석·17건 하향 수정의 의미를 과장했다. 숫자 조작이 확인됐다는 판정은 아니며 원본 CLI 응답 부재에 따른 검증 한계도 판정에 있다. 이후 Claude large 재실행(`models/claude-large2.jsonl`, session `5826d21d-ff7e-49c4-a25d-cd8f412e243b`)은 five_hour 사용량 한도로 HTTP 429/API error가 나서 검증되지 않았다. 10/10으로 바꾸거나 이번 세션에서 모델을 새로 실행하지 않았다.

최종 12개 지적에 대응한 수정과 재현은 완료했다. 기존 전체 완료 기준 중 라이브 세계 지도 분류 1건과 모델 시나리오 1건의 통과는 충족하지 않았으며, 새 독립 최종 리뷰·PR·머지 완료를 주장하지 않는다.

### 2026-09-16 맵 로더 후속 수정 — 기존 라이브 차단 해소

부모가 맵 로더도 원래 전체 구현 범위라고 명시하여 앞 기록의 세계 지도 차단 항목을 이어서 수정했다. 이번 추가 변경은 `.claude/skills/finviz/scripts/markets.py`, `tests/finviz/test_feeds.py`, 이 계획 파일뿐이다. TDD 지침과 기존 승인 CLI subprocess·저장 관측 seam을 적용했으며 curl만 대체했다. 완료 판정은 현재 진입 파일 구조의 종류별 CLI 재현 통과, 모호한 후보 거절, 전체 오프라인 및 실제 맵 조회 성공으로 정했다. 커밋·푸시·브랜치 변경·새 에이전트·모델 시나리오 재실행은 하지 않았다.

저장된 실패 응답(`finviz-repairs-live/test_anonymous_source_provides29/observations.sqlite3`)을 먼저 확인했다. 기존에 검사한 숫자 번들에는 분류 로더가 없고, 저장된 HTML이 가리키는 `map.v1.67823970.js`를 읽으니 module 30092의 `function o(e){switch(e){case i.IZ.World:return a(n.e(6207).then(n.t.bind(n,68379,23)));...}}`가 실제 로더였다. SectorFull 분기는 7791, 같은 switch의 기본 섹터 분기는 8119였다. 이 숫자는 진단에서 관측한 사실과 테스트 픽스처에만 쓰며 구현에 하드코딩하지 않았다. 진단용 추가 응답은 `$SCRATCH/finviz-map-diagnosis.sqlite3`에 저장했다.

현재 `map` 진입 파일을 먼저 검사하고, 이전 구조를 위해 앞쪽 숫자 번들 최대 10개 검사도 유지한다. 지도용 World·SectorFull 반환 분기가 있는 동일 switch 안에서 요청 종류의 chunk를 찾으며 기본 섹터만 그 switch의 default를 사용한다. 다른 레이아웃 switch의 default를 섞지 않고, 요청 종류가 없으면 다른 종류로 대체하지 않는다. 여러 로더 후보 및 여러 Root 객체는 `asset_structure`/partial/종료 8로 거절하고 성과 자료는 보존한다. chunk 해시는 기존처럼 실제 runtime 매니페스트에서 읽는다. JavaScript를 실행하거나 URL 신뢰 경계를 완화하지 않았다. 지원하는 switch 형태와 검사 범위의 한계는 코드의 `# 성진:` 주석에 남겼다.

`test_map_loads_the_requested_universe_from_the_current_entry_script`에서 geo/sec_all/sec 세 경우가 기존 코드로 각각 종료 8인 것을 먼저 확인(3 failed)한 뒤 진입 파일 검사로 통과시켰다. 이어 서로 다른 로더 후보 두 개를 넣었을 때 잘못 성공하는 재현(3 failed)을 확인한 뒤 switch 범위와 단일 후보 검증을 추가했다. 같은 CLI 테스트는 추가 원문 필드 보존·무관한 default 무시·중복 Root 거절도 검증한다. `test_map_does_not_substitute_the_default_for_a_missing_requested_type`은 cap 분기가 없을 때 default로 대체하지 않음을 검증한다. 기존 앞쪽 번들 로더 픽스처도 계속 통과한다.

- 전체 오프라인: `TMPDIR="$SCRATCH" PYTHONDONTWRITEBYTECODE=1 uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest -p no:cacheprovider --basetemp "$SCRATCH/finviz-map-pytest" tests/finviz -q` → **75 passed, 41 deselected, 33.97s**, 종료 0. 로그: `$SCRATCH/finviz-map-offline.log`.
- 최종 맵 라이브: `TMPDIR="$SCRATCH" PYTHONDONTWRITEBYTECODE=1 uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest -p no:cacheprovider --basetemp "$SCRATCH/finviz-map-live-final" tests/finviz/test_live.py -m live -k 'market and map' -q` → **1 passed, 40 deselected, 3.97s**, 종료 0. 앞서 실패했던 geo 분류 조회가 통과했다. 로그: `$SCRATCH/finviz-map-live-final.log`.
- 종류별 추가 라이브: 같은 실제 CLI로 `market map --type sec --fields classification_source,period` 및 `--type sec_all`을 실행 → **둘 다 종료 0**, 저장된 `/data/classification/name`도 각각 `Root`. sec는 `8119.v1.e0fc3674.js`, sec_all은 `7791.v1.e3ae587f.js`를 반환해 서로 다른 실제 자산 선택을 확인했다. 관측 ID는 각각 `90535da3b8e54c14a0d3c0243283deed`, `3813dca1a7814f74a3c99eb202737279`; 결과 `$SCRATCH/finviz-map-types.json`, 저장소 `$SCRATCH/finviz-map-types.sqlite3`.
- Ruff: `uv run -q --frozen --group dev --project .claude/skills/finviz ruff check --no-cache --config pyproject.toml .claude/skills/finviz/scripts tests/finviz` → **All checks passed**, 종료 0. 범위 내 `git diff --check`도 종료 0.

세계 지도 로더의 라이브 차단은 해소했다. 전체 라이브 41건을 다시 실행한 것은 아니며, 앞 실행 40 PASS·1 FAIL과 이번 해당 맵 재검증 결과를 구분해 기록한다. 모델 시나리오는 기존 9 PASS·1 FAIL 및 Claude 재실행 사용량 제한 기록 그대로이며 이후 처리는 부모가 맡는다. PR·머지 세부 사항도 부모에게 남긴다.

### 2026-09-16 최종 검증과 전달 준비

- 후속 수정 실행: `20260916-224820-finviz-final-repair-6d1c`, 지도 로더 수정: `20260916-230448-finviz-map-repair-1e3d`. 기존 최종 리뷰의 12개 항목과 실서비스 지도 로더 변경을 수정했다.
- 부모 세션 회귀: `uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest tests/finviz -q -p no:cacheprovider` → **75 passed, 41 deselected**.
- 부모 세션 라이브: `uv run -q --frozen --group dev --project .claude/skills/finviz python -m pytest tests/finviz/test_live.py -m live -q -p no:cacheprovider` → **41 passed**. 지도 실패는 현재 해소됐다.
- Ruff 검사 통과. `validate_harness.py --path . --json` → **오류 0, 경고 0**. Finviz 범위 `git diff --check` 통과.
- Claude large 시나리오를 2026-09-16 재실행했다. 원본 transcript는 세션 scratchpad의 `models/claude-large3.jsonl`. 독립 판정 `20260916-231059-finviz-delivery-verification-63a8` → **LARGE_SCENARIO PASS**, 표의 날짜·평균값 18/18개가 실제 도구 응답과 일치하고 일시 급락을 보존했다. 이전 9 PASS·1 FAIL 기록을 지우지 않으며, 실패 사례 수정 후 재검증으로 누적 최종 시나리오는 **10 PASS**다. 모든 시나리오를 최종 버전에서 동시에 다시 실행했다는 뜻은 아니다.
- 같은 독립 검증은 지정된 최종 리뷰 항목에 **NO_BLOCKERS**를 반환했다. 리뷰어는 코드를 읽고 시나리오 응답을 대조했으며 테스트 실행은 부모 세션의 위 결과와 구별한다.
