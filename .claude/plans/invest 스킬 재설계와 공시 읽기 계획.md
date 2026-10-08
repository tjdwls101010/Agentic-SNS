# invest 스킬 재설계와 공시 읽기 계획

> 계획 세션 2026-10-05~06. **첫 동작**: 승인 직후 이 파일을 `.claude/plans/invest 스킬 재설계와 공시 읽기 계획.md`로 `mv`한다(계획 모드는 지정 경로만 쓸 수 있고 ExitPlanMode가 그 경로를 읽어서, 승인 전에는 옮기지 않는다). 구현 세션은 시작하자마자 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커를 불러 `## 작업 단계`의 단계마다 `TaskCreate`하고(description에 완료 판정을 그대로), 단계마다 `TaskUpdate`로 옮긴다. 코드·테스트를 쓰기 전에 `coding` 스킬을, 리뷰·채점은 `codex` 스킬을 연다. 작업 트리의 무관한 변경(`.claude/harness-spec.md` 삭제, `.ultra-search/`)은 커밋에 섞지 않는다. 스크래치 산출물은 `/private/tmp/claude-501/-Users-seongjin-Coding-Agentic-SNS/9f82b452-8323-49f6-bb60-1915aa4dfc8f/scratchpad/`에 있고 세션이 바뀌면 사라질 수 있다. 그래서 단계 0에서 `proto/skillL/SKILL.md`(비교 기준선 L), `proto/skillB/scripts/filing.py`, `proto/contrast*.py`, `contrast*/`의 `summary.json`·`answer.md`, `codex/*result*`를 `.tmp/invest-plan/`로 복사한다.

## Context

`yfinance` 스킬은 Claude가 숙련된 애널리스트처럼 투자 데이터를 상황에 맞게 불러오게 하는 역량이다. 지금은 공시 목록·링크까지만 있고 본문을 읽지 못한다. 성진은 여기에 **공시 원문을 사람처럼 읽는 역량**을 더하고 싶어 했다. 사람처럼 읽는다는 것은 문서의 지도(목차·절 크기)를 먼저 보고, 질문에 필요한 절로 가서, 문단 → 표 → 주석으로 좁혀 들어가고, 문서가 가리키는 곳(Note 14, EX-99.1)을 따라가며, 어디서 읽었는지 인용하는 것이다. 통째 읽기를 금지하는 규칙이 아니라, 필요한 부분만 읽는 길을 가장 싸고 자연스럽게 만드는 수단이다. 용도는 **서술(narrative)**이다. 경영진의 실적 해석, 전망, 산업관, 고객·공급사·파트너 관계처럼 yfinance로 알 수 없는 것과, yfinance에 없는 숫자(부문 수치·회사 가이던스·고객 비중)를 읽는다. 예전에 만든 `sec` 스킬은 참고만 하고 완료 뒤 은퇴시킨다.

세션 중 범위가 넓어졌다. 성진은 새 스킬 `invest`가 **skill-maker 프레임을 철저히 반영**해야 하고 `yfinance`는 그렇지 못하다고 보았다. yfinance에 기본값 대조를 처음 적용한 결과(17건, 런 한 번씩)는 다음과 같다.

- 스킬 없음: 14/17, $1.09.
- 현 CLI: 16/17, $3.13.
- L(CLI 없이 SKILL.md 지식 + 라이브러리 직접 사용): 17/17, $2.13.

현 CLI가 모델에게 읽힌 글자의 67%는 help였다(427K자 중 285K자). 한 종류의 help가 그룹 전체의 단위·한계 설명을 9–21K자씩 찍었기 때문이다. 이것은 읽힌 글자의 비중이지 달러 비용의 비중이 아니다. 성진은 L 대신 **Claude 전용으로 완결된 CLI**를 택했다(결정 18). 이유는 yfinance 라이브러리가 사람 개발자용이라 단위 혼재, 조용한 실패, 대량 로드, 매번 다른 사용법이라는 한계를 Claude에게 그대로 넘긴다는 것이다. 공시 쪽에서는 문서를 받아 읽기 좋은 텍스트와 지도로 바꾸는 명령(B)이 제값을 했다. 스킬이 없을 때 모델은 서술형 질문에 공시를 거의 열지 않았고, 연 경우에도 큰 문서는 그 자리에서 짠 변환기로 구조를 잃었다.

**결론.** `yfinance`를 `invest`로 다시 만든다.

- **Yahoo 데이터**: 도메인 명령 12개로 된 새 CLI. 명령마다 help가 짧고, 결과는 언제나 파일에 저장하고 영수증(receipt)을 출력한다. 영수증에는 비율로 정규화한 단위 표시, 시점(`as_of`), 범위(`coverage`), 대상별 실패가 담긴다. 옛 `yahoo/`의 실측 지식은 이식하고 나머지는 다시 쓴다.
- **공시**: `filing URL…` 명령이 Yahoo CDN 사본을 읽기 파일과 지도로 바꾼다. 읽기 자체는 Claude의 Read·`grep`이 한다.
- **은퇴**: `sec` 스킬과 그 테스트·CI·문서 언급.
- **PR 셋**: ① 이름 변경과 Yahoo CLI 재설계, ② 공시 읽기, ③ sec 은퇴.

**의도한 결과**

- 숫자 질문: 모델이 짧은 SKILL.md와 명령 하나의 help를 읽고 명령 두세 번으로 답한다. 단위를 스스로 환산하지 않는다. 장중인지 확정인지, 목록이 무엇을 덮는지, 어느 대상이 실패했는지를 영수증에서 읽는다. 계산은 결과 파일을 자기 Python으로 읽어서 한다.
- 서술 질문: 모델이 `company filings`로 회사 자신의 문서를 찾는다. `filing` 한 번으로 지도와 파일을 얻고, 필요한 줄 범위만 읽고, 원문 문서와 절을 인용한다.
- 스킬 폴더에는 실행 중인 모델이 쓰는 것만 남는다(SKILL.md, `scripts/`, `data/`). 테스트·시나리오·개발 기록은 레포와 이 파일에 둔다.

## 장부

### 사실 (2026-10-05~06 실측·읽기)

**Yahoo 공시 사본**

- Yahoo `get_sec_filings()`(현 CLI `company filings`)가 주는 문서 URL은 sec.gov가 아니라 Yahoo CDN 사본이다.
  - `edgarUrl`은 Yahoo 페이지(`finance.yahoo.com/sec-filing/<SYM>/<accession>_<cik>`)다.
  - `exhibits`가 `{문서유형: cdn.yahoofinance.com/prod/sec-filings/<cik10>/<accession18>/<filename>}` 맵이다.
  - 엑셀 재무보고서만 `s3.amazonaws.com/finance-pri-uw2/sec-filings/.../Financial_Report.xlsx`에 있다.
- CDN 사본은 SEC 원본과 내용이 같다(AAPL 8-K EX-99.1, NBIS 6-K EX-99.2: 유일한 차이는 SEC(Akamai)가 끝에 끼워 넣는 `<script>` 한 줄이다).
  - CDN은 User-Agent 신원 없이 200을 주고, 문서 속 이미지도 준다.
  - 404인 것: 색인 페이지, XBRL 뷰어(`R2.htm`), `FilingSummary.xml`, 2019년 AAPL 10-K 경로.
- Yahoo 목록 관측 범위(2026-10-05): AAPL 80건(2022-01-27~), NBIS 121건, MRVL 104건, TSM 213건. Form 4는 없다.
  - exhibits 맵은 EDGAR 폴더의 HTML 문서를 빠짐없이 담는다(EDGAR `index.json`과 대조). 키에 공백 변형이 있다(`EX-10.12 1`).
  - 다섯 종목 목록의 형식: `.htm` 1,297, `.xlsx` 134, `.pdf` 2, XML·SGML 0.
  - 8-K 제목은 대부분 "Corporate Changes & Voting Matters"다.

**기존 sec 스킬과 변환 크기**

- 기존 sec 스킬은 동작하지만 항해에 결함이 있다.
  - 문서 자체의 링크 목차(AAPL 35 대상, MSFT 34, MRVL 19, NBIS 7)가 `internal_link`로 분류되어 기본 `outline`에서 빠진다. `<h1>`–`<h6>` 조상을 요구하는데, 측정한 문서의 h 태그는 0개다.
  - NBIS 주석 제목은 1행 표 안에 있다.
- 변환 크기(문단·표 행 하나가 한 줄):
  - AAPL 10-K 21–23만 자, MSFT 10-K 34만, MRVL 10-Q 31–33만, MRVL 10-K 49만.
  - TSM 20-F 58만 자·7,647줄(인쇄 줄 단위로 끊긴 문서), NBIS EX-99.2 11만, 실적 보도자료 1–4만.
  - 줄 길이 p99는 1.2–1.6천 자다.
  - 통째 굵은 블록(글자의 80% 이상, 표 밖)이 위험요인 제목·MD&A 소제목·주석 이름과 일치한다(AAPL 176개, MRVL 183개).
- sec 파서의 내부 의존:
  - `markup` → `emphasis`·`grid`·`snapshot`.
  - `grid` → `snapshot.cell_text`·`output.SecError`.
  - `emphasis` → `snapshot.LAYOUT`.
  - `snapshot`은 판독·형식 판정·저장을 함께 하고, 안에서 `markup`을 import한다.

**Claude Code와 실행 환경**

- Claude Code Read는 5,009자 한 줄을 자르지 않는다. offset·limit 없이 256KB를 넘는 파일은 거절하고, 범위를 주면 2,000줄도 된다.
- 이 빌드에는 Grep 도구가 없다(검색은 Bash `grep`).
- 성진의 기본 권한 모드는 `auto`이고, 전역 설정에 `Bash(uv run python:*)`가 있다.
- 이 머신의 시스템 `python3`에는 yfinance 1.5.1이 있고(현 CLI는 1.7.0 고정), 스킬 없는 모델은 1.5.1을 조용히 썼다.

**현 yfinance 코드**

- 파일:
  - `scripts/cli.py`(708줄) + `scripts/yfinance_skill/` 약 2.2천 줄.
  - 공용: `envelope shape display selection budget leaf`.
  - 저장: `store export`.
  - 기능: `querying/{observe,read,out}`, `describe`.
  - 시스템: `yahoo/` 15모듈.
- `yahoo/`는 다음 실측 지식을 코드로 가지고 있다. 이식 대상이다.
  - 데이터셋마다 필드 스케일 선언: `RATE`·`PERCENT`·`WEIGHT`·`CURRENCY`·`MULTIPLE(inverted)`·`SHARES`·`COUNT`·`PER_SHARE`. 예: `INFO_UNITS`, 펀드 `equity_holdings` 역수 배수, `Surprise(%)`, 옵션 `percentChange`.
  - 해석문(`interpretation`·`gotchas`·`limits`), 원천 거절 메시지 판독(`refusals.py`: 429, span·reach 제약, NoData).
  - 스크린 쿼리 검증, 서비스되는 지역 코드(`DOMAIN_REGIONS` 실측), 인트라데이 한계, 가격 정밀도(float32 7자리).
- 저장소는 `data/observations`(`YF_STORE`로 바꿈)이고, yfinance 캐시는 라이브러리 기본 위치다.
- 테스트(`tests/yfinance/`, 약 4.9천 줄)는 전부 CLI 하위 프로세스로 돈다.
  - HTTP 대체: `fixtures/sitecustomize.py` + `fixtures/shapes/` 6개.
  - 시스템 의미: `test_company`·`test_market`·`test_prices`·`test_vocabulary`·`test_boundary`·`test_live`.
  - 지울 기능: `test_budget`·`test_selection`·`test_store`·`test_export`·`test_display`.
- 실행기는 `scenarios/yfinance/run.py`다.
- 은행 `tests/yfinance/model-scenarios.json`은 24건이다. `budget:true`가 7건이고, 여기에 전제가 있는 news-all 1건을 더해 전제가 붙은 시나리오가 8건이다. 예산이 아닌 17건에는 news-all이 들어 있다.

**현 CLI의 실측 비용 구성**(실험 3 cli, 17런)

- 호출 115회 중 help가 40회였다.
- 읽은 글자 427K자 중 help가 285K자(67%)였다. 그룹 help가 9–21K자씩 찍혔다.
- 데이터 결과는 약 142K자였다.

**yfinance 1.7.0의 신호**(2026-10-06 실측)

- `get_history_metadata()`에 `currentTradingPeriod.regular{start,end}`·`regularMarketTime`·`exchangeTimezoneName`이 있다. 그래서 마지막 일봉이 확정인지 추가 호출 없이 판정할 수 있다.
- 주식 스크린 쿼리 필드는 93개이고, 그중 비율 성격(성장률·마진·수익률·변화율·보유 비율)이 약 35개다.
- 실패 신호(`hide_exceptions=False`):
  - 없는 심볼: `history`는 `HTTPError 404`를 던지고, `get_info()`는 `None`을 돌려준다.
  - 주식에 펀드 데이터(`funds_data.top_holdings`·`equity_holdings`): `KeyError 'topHoldings'`.
- 스케일 재확인:
  - KO `dividendYield` 2.48 = `dividendRate` 2.12 / 가격 86.51 × 100이므로 퍼센트다. `trailingAnnualDividendYield` 0.0243은 비율이다.
  - `debtToEquity` 115.5는 퍼센트다.
  - 주식의 `52WeekChange` 0.296은 비율이고 `fiftyTwoWeekChangePercent`는 29.58(퍼센트)이다. 지수 ^GSPC는 둘 다 14.58(퍼센트)이다.

**구조 검사**(`tests/test_skill_layout.py`)

- 단위 종류는 `common`·`system`·`store`·`feature`·`cli`다.
- 등록 스킬은 `scripts/` 아래에 `cli.py`와 패키지를 요구한다(`:149`).
- `allowed_tools()`는 한 줄 정규식이고 `INVOCATION`과 정확히 같아야 한다(`:136`,`:237`). 본문에 `CALL`이 있어야 한다(`:240`).
- 입구 밖 import·patch 경로를 금지한다.
- 상태 위치는 정적으로 검사한다. `home`·`expanduser`·`XDG_CACHE_HOME`·`.cache` 문자열을 찾는다(`:409`).
- offline CI는 pytest·ruff만 설치한다(`.github/workflows/test.yml:16`).

**은퇴·이름 변경 영향 범위**

- sec 은퇴: CI `sec` 잡(`test.yml:41-42`)과 offline 잡의 `--ignore=tests/sec`, `CONTRIBUTING.md:5,15,31-40`, `README.md:20,79`, `SECURITY.md:25`, `docs/usage.md:27,50,58-68`, `.gitignore:20`.
- yfinance를 가리키는 곳: README·CONTRIBUTING·docs/usage.md, CI yfinance 잡, `.gitignore`(`yfinance/data/`), finviz `SKILL.md:3`("yfinance covers those").
- `.github/`에 PR 템플릿이 없다 → PR 본문은 `## 무엇을 바꿨나/왜/영향/검증`.

### 대조 실험 (2026-10-06, `claude -p --safe-mode --restricted --model claude-opus-5-5`, 스크래치 `contrast1/`~`contrast4/`)

**실험 1 — 공시를 짚은 과제**(도구 Bash·Read·Write·WebFetch·WebSearch). 조건: none, sec(기존 sec 스킬), B(yfinance + `filing.py` 시제품 v1).

| 과제 | none | sec | B |
|---|---|---|---|
| NBIS 지분변동표 선불워런트 | ✓ 7회 $0.24 | ✓ 9회 $0.33 | ✓ 9회 $0.22 |
| MRVL 세 10-Q 공급 제약 변화 | ✓ 13회 $0.44 | ✓ 18회 $0.70 | ✓ 16회 $0.49 |
| AAPL 위험요인 FY2025 대 FY2024 | ✓ 8회 $0.32 | ✓ 18회 $0.71 | ✓ 18회 $0.64 |

- none은 SEC에 지어낸 User-Agent(`Research Bot admin@example.org`)로 접속했다. HTML을 정규식으로 한 줄로 평탄화해(문단·표 구조 소실) 키워드 창과 difflib로 읽었다.
- sec 리더는 `schema` 읽기에 최대 27K자를 썼다. B는 지도 줄 범위를 실제로 썼다.

**실험 2 — 공시를 말하지 않는 서술형 질문**(같은 도구). 조건: none, M(안내 한 절만), B(같은 안내 + `filing.py` v2).

| 과제 | none | M | B |
|---|---|---|---|
| NVDA 경영진의 실적 해석·전망 | 콜 녹취록·뉴스 3회 $0.17 | 8-K EX-99.1·.2 4회 $0.17 | 같은 문서 7회 $0.28 |
| TSMC의 산업·AI 수요 시각 | 콜·뉴스(최신 설비투자 상향) 7회 $0.29 | 20-F, 즉석 변환기 16회 $0.47 | 20-F, 지도 범위 12회 $0.39 |
| MRVL의 대형 고객 관계 | 검색 스니펫, 추측 섞임 3회 $0.16 | 공시, 2025-12 8-K 놓침 12회 $0.45 | **가장 정확** 16회 $0.54 |
| AAPL 관세 영향 설명 | 콜·뉴스 5회 $0.17 | 세 10-Q 분기별 변화 9회 $0.33 | 환급 회계·GM 2%p 6회 $0.21 |

- 평균 비용은 none $0.20, M $0.36, B $0.36이었다.
- none은 이 네 질문에서 공시를 열지 않았다. 다만 TSMC는 콜에 더 최신 정보가 있었다. 그래서 공시를 열었는지는 판정 기준이 아니다. 판정 기준은 맞는 최신 근거를 찾았는지다.

**실험 3·4 — yfinance 은행 17건**(도구 Bash·Read·Write, codex 독립 채점). 조건: none, cli(현 yfinance), L(CLI 없이 단일 SKILL.md 8.9K자 + 라이브러리 직접).

| | none | cli | L |
|---|---|---|---|
| 합격 | 14/17 | 16/17 | 17/17 |
| 비용 합계 | $1.09 | $3.13 | $2.13 |
| 런당 호출 중앙값 | 2 | 6 | 3 |
| help 글자 합계 | 0 | 285K | 0 |

- 판정이 갈린 시나리오는 넷이다.
  - blackrock-position: none ✗(13F 기준일과 현재가 평가액을 혼동).
  - unplanned: none ✗(기록 범위 없이 '매수 없음'이라고 단정).
  - date-close: none ✗(장중 값을 확정 종가로 씀).
  - screen-tech: cli ✗(확인되지 않은 조건을 적용됐다고 보고).
  - L은 넷 모두 합격했다.
- 단위·스케일 함정(TM 통화, SPY PER, 서프라이즈 %, KO 배당, 성장률 퍼센트 포인트)은 세 조건 모두 맞혔다. 이 은행에는 희귀 필드가 적어, 단위 처리의 차이를 보여주지 못한다(→ C13에 희귀 단위 시나리오를 더함).
- 조건이 같지 않았다. none은 yfinance 1.5.1에서, L은 장 마감 뒤(POST)에, cli는 장중에 돌았다.

### 정답 근거 (원문에서 확정, 은행의 `expect`가 된다)

- **NBIS**: 6-K(2026-08-12) EX-99.2 `nbis-20260812xex99d2.htm`, 지분변동표 반기(2026-06-30)의 "Issuance of pre-funded warrants (Note 14)" 행.
  - 금액($ millions): APIC 2,000.0, 회사 귀속 자본 2,000.0, 자본총계 2,000.0. 주식 수 열은 "—".
  - Note 14: NVIDIA, 21,065,936주, 행사가 $0.0001.
- **MRVL 공급 제약**(10-Q 2025-11-01 / 2026-05-02 / 2026-08-01, Part II Item 1A):
  - 문구 변화: "in the first few quarters of fiscal 2023 … supply constraints" → "tight supply environment for AI related components …" → "**We are currently in a supply constrained environment.**".
  - 소제목 변화: "No Guarantee of Capacity or Supply" → "**Supply Constraints**".
  - 생산능력 확보 보증금 $870.0M.
- **AAPL 위험요인 FY2025 대 FY2024**:
  - 2025년 관세(대상국, 보복 관세, Section 232 반도체 조사).
  - Google 검색 계약의 DOJ 판결(2024-08-05)·구제조치·항소 위험.
  - 미국 App Store 수수료 금지 법원 명령, AI 위험 확대.
  - 제목 재편: ESG → "Varied stakeholder expectations", 분기 변동 → "net sales and gross margins are subject to volatility and downward pressure", 소매점 위험요인 제목 삭제.
- **NVDA**(8-K 2026-08-26 EX-99.1 `q2fy27pr.htm`·EX-99.2 `q2fy27cfocommentary.htm`):
  - Q2 FY27 매출 $96.2B, 데이터센터 $89.0B.
  - CEO: "AI has reached its inflection point … compute is revenue … demand is accelerating".
  - Q3 전망: 매출 $108.0B ±2%(중국 데이터센터 컴퓨트 미포함), GM 74.0% ±50bp, 영업비용 GAAP $9.2B / non-GAAP $9.0B.
- **TSMC**(6-K 2026-07-16 EX-99.1, 20-F 2026-04-16):
  - CFO: "continued strong demand for our leading-edge process technologies, including the steep ramp-up of our 2-nanometer technology".
  - Q3 가이던스: 매출 $44.6–45.8B, GM 65–67%, 영업이익률 56–58%.
  - 20-F: "entering a period of higher growth as the multiyear megatrends of 5G, AI and HPC …", HPC 58%(2025), 2026 설비투자 $52–56B(20-F 시점 값 — 7월 콜에서 상향됨).
- **MRVL 고객**(10-K 2026-03-11, 10-Q 2026-08-01, 8-K 2024-12-02 EX-99.1, 8-K 2025-12-02):
  - 10% 이상 고객 둘(유통사·직접 고객), 상위 10개 82%.
  - AWS 5년 다세대 계약(2024-12-02 보도자료).
  - 워런트: FY2025 최대 420만 주, 2025-12 Celestial AI 관련 100만 주.
  - 공시 본문은 고객을 "a customer"로 쓴다. Microsoft는 이 공시들에 없다.
- **AAPL 관세**(10-Q 2026-07-31 MD&A "Tariffs and Other Measures", 8-K 2026-07-30 EX-99.1):
  - 대법원 IEEPA 판결(2026-02-20), 환급 신청과 원가 차감 처리.
  - Q3 GM 50.1% 중 약 2%p가 환급 효과.
  - Section 232 1차 결과(2026-01-14) 추가 관세 없음, Section 301 관세 신규.

### 코덱스 검토 (`gpt-6-astra` high, read-only, 스레드 `01a10c9a-4772-7ea1-9c8a-17b130199197`)

- **방향 검토**(run `20261006-000639-yf-sec-direction-9f21`): B를 권하되 시제품 그대로는 안 된다. A의 cursor·예산·`fp:block:offset`·`schema`는 버리고, 파서와 원본 픽스처·독립 기대값은 남긴다.
- **구조 감사**(run `20261006-003835-yf-sec-structure-1f6a`): 현 yfinance의 구조 검사 위반은 0이다. 공시 단위는 `sec/`(system)·`filing/`(feature)·`documents.py`(store)이고, 파이프 출력은 feature에 둔다. 시제품 v2 결함은 머리줄 뒤 `[→L]` 한 줄 어긋남과 굵게 정의 불일치다.
- **skill-maker 전 조항 감사**(run `20261006-004348-yf-fidelity-497a`): 판정은 부분 충족이다.
  - 공백: 기본값 대조 부재, `<kind> --help`가 그룹 전체 문서라는 점(→ C21), 시나리오 판정 기준, `DOMAIN_REGIONS` 문구, 측정 이력 주석.
  - 줄 수로 얕음을 판정한 것(G4)은 틀렸다.
- **은행 채점**(run `20261006-005747-yf-judge-31eb`, `20261006-072614-yf-judge-L-bd7f`): 실험 3·4의 판정.
- **계획 검토 1차**(run `20261006-074804-invest-plan-review-3fa6`, L안 기준): 판정은 "major를 고치면 승인"이다.
  - 공시 쪽 반영(이 계획에 유지):
    - F2: 결과 식별 → C3.
    - F3: 표 행 좌표·`th`·독립 기대 목록 → P3.
    - F4: 목차 판정 → C6·P2.
    - F5: 출력 예산·종료 코드 → C7·C24.
    - F6: 받기·형식 → C4·C5·P5·P6.
    - F10: 파서 이식 의존·테스트 입구 → P1.
  - 공통 반영:
    - F1: 결정 변경 기록 → 결정 16·18.
    - F8: 합격선·과장 → C13.
    - F9: 권한 검증 → 단계 7·12.
    - minor 전부.
  - F7(필드 사실 검증)은 L안의 산문 사실 검증이었다. 이 계획에서는 정규화 코드 검증(C12)으로 바뀌었다.
- **계획 검토 2차**(run `20261006-083150-invest-plan-review2-bc21`, CLI안 기준): 판정은 "major를 고치면 승인"이다. 구조와 결정 18–23은 유지해도 된다고 보았다. 반영 내용:
  - M1: 스크린 미측정 필드를 원값으로 보내면 결정 19 위반 → C23(사전 거절 + `--source-units`, presets는 입력 스케일).
  - M2: `screen()`은 반환 필드를 고를 수 없고 OR 판정이 틀림 → C26(필드 대응표, 3값 논리, 표본 범위).
  - M3: 혼합 단위 표 → C23(긴 형식 `metric/value/unit`, `rank`·`unverified`).
  - M4: 통화 역할 → C23(필드별 역할, 미확인 표시), C12(실제 연결 검사).
  - M5: 봉 확정 판정 → C25(관측 시각 대 세션 끝, 주기별, `unknown`).
  - M6: `not_found` 근거 → C24(증거 기준, 상태 표).
  - M7: 영수증 스키마 → C22(출력·저장 스키마, `warnings`는 줄이지 않음).
  - M8: 정밀도 → C22·Y6(파일은 전 정밀도, export 불변식 이식).
  - 그 밖의 major: 마감의 `BaseException` 보존(C27), 입력 단위는 help에(C21·Y1), 일관성은 의미 불변식으로, 효율 지표 정의, L 짝 2쌍 이상, 조정 런과 평가 런 분리, 실패·희귀 단위·대량 시나리오 고정(C13), 잃으면 안 되는 의미 목록(C28).
  - minor: 67% 표현, 단계 2 선행 조건, CLI의 종류 선언 위치, `--limit` 표기, 정규장 증거.
- **계획 검토 3차**(run `20261006-084343-invest-plan-review3-4a7b`, 반영 확인): 판정은 "major를 고치면 승인"이다. 새 blocking은 없었다.
  - 이전 major 가운데 M2·M4·M5·M8, 마감, 입력 단위, 효율 정의, L 짝, 조정/평가 분리, 잃으면 안 되는 의미 표는 해결로 판정됐다.
  - 남은 것과 새로 생긴 것을 반영했다:
    - M1 잔여: 추론 절의 원값 전송 문장 → C23과 일치.
    - M7 잔여: `warnings` 코드를 최소 영수증에 넣고 `over_budget` → C22·Y6.
    - 역수 검사는 개연성일 뿐 → C12(`declared` 유지).
    - live 판정은 그 런의 응답 기준, 전체 파일 사용은 계산 입력으로 확인 → C13.
    - N1: 혼합 표 `source_column` → C23·Y6.
    - N2: `not_found`는 HTTP 신호로, 단계 3에서 정의 → C24·Y5.
    - N3: 음수 역수 부호 보존 → C23.

### 성진 결정

1. 의도 이해가 맞다. 걱정: 공시가 종류·티커마다 달라 CLI에 미리 로직을 만들어 두기 어려울 수 있다(→ C6: 변환은 문서 자신의 신호만 쓴다).
2. 대조 실험을 세 조건 모두로 했다(NBIS·MRVL·AAPL).
3. 공시 읽기의 용도는 **서술**이다.
4. 원문 출처는 **Yahoo 경로만**이다(SEC 신원 없음). 오래된 공시·Form 4·EDGAR 전문 검색·XBRL 뷰어는 후속 과제다.
5. 서술형 2차 대조를 과제 넷(NVDA·TSM·MRVL·AAPL)으로 했다.
6. 공시는 **방향 B**로 한다. 기존 sec 리더는 이식하지 않는다.
7. 컨퍼런스콜 녹취록은 **모델 판단에 맡긴다**. 스킬은 콜에 대해 말하지 않는다.
8. 스킬 이름은 **`invest`**다. 당시 약속은 "동작을 바꾸지 않는 이름 변경 PR을 먼저"였는데, 결정 16으로 바뀌었다.
9. 숫자 경계: **yfinance가 가진 숫자는 yfinance에서, yfinance에 없는 숫자와 서술은 공시에서.**
10. sec 은퇴는 **함께 정리**한다. 쓸 파서의 테스트·픽스처는 `tests/invest`로, 나머지는 `.tmp`로 옮기고, CI·문서·`.gitignore`도 정리한다.
11. `invest`는 **skill-maker 프레임을 철저히** 반영한다.
12. 전 조항 감사와 yfinance 대조를 한다.
13. 문서는 **단일 SKILL.md**로 둔다(`references/` 없음). 결정 18 이후에는 명령별 사실이 각 `<command> --help`와 영수증으로 가므로 SKILL.md는 짧다.
14. ~~Yahoo 데이터는 L 채택~~ → **결정 18로 대체**.
15. ~~`allowed-tools`에 고정 버전 Python 실행을 미리 승인~~ → **결정 18로 철회**. Python으로 Yahoo를 부르는 길이 없어졌으므로 승인할 것도 없다.
16. PR 순서: 순수 이름 변경 PR 없이 **① 이름 변경 + Yahoo 재설계 → ② 공시 → ③ sec 은퇴**로 간다. 다시 쓸 층의 이름 변경을 피하기 위해서다. 이식하는 `yahoo/` 모듈은 `git mv`로 이력을 잇는다. PR ① 머지 전에 그 시점의 SKILL.md 전문 승인을 받는다.
17. yfinance 라이브러리 캐시(시간대·쿠키)는 **라이브러리 기본 위치에 두고**, skill-maker `data/` 규칙의 승인된 예외로 기록한다(현 CLI도 같다).
18. Yahoo 데이터는 **Claude 전용 CLI로 확정**한다(2026-10-06). 성진의 근거: yfinance 라이브러리는 사람용이고 skill-maker 프레임이 반영되지 않아, Claude가 그대로 쓰면 역량에 한계가 있다. L과의 비교는 구현 뒤 합격선(C13)으로 확인하고, 지면 재작업을 감수한다.
19. 단위: **비율로 정규화하고 결과에 단위를 표시**한다. 스크린 조건도 비율로 받고, CLI가 Yahoo 단위로 바꿔 보낸다.
20. 전달: **언제나 파일 + 작은 영수증**. `read`·`--out`·예산에 따른 행 자르기는 없앤다.
21. 명령: **도메인 명령 약 13개, 종류는 닫힌 선택지, 명령별 help는 짧게**. 단위·시점·범위는 help 산문이 아니라 각 결과에 둔다.
22. 코드: **`yahoo/` 지식은 이식하고 나머지는 다시 쓴다**. HTTP 대체 seam과 yahoo 테스트를 이식하고, 지운 기능(예산·read·표시)의 테스트는 버린다.
23. 성진이 본 라이브러리 직접 사용의 한계는 **단위·스케일 혼재, 조용한 실패·대량 로드, 매번 다른 사용법**이다. 이 셋은 시나리오에 반드시 넣는다(C13).

### Claude가 정한 것 (근거와 함께)

**공통**

- **C1. PR 셋**(결정 16).
  - PR ①은 동작 변경이다. 은행(C13)과 테스트로 검증한다.
  - PR ①의 description은 아직 없는 공시 기능을 광고하지 않는다("Not for original SEC filing text"를 유지).
  - PR ② 머지 직후 PR ③을 낸다. 그 사이 짧게 `sec`와 `invest`가 공존한다.
- **C9. yfinance는 1.7.0으로 고정한다.** `cli.py` PEP 723에 `exclude-newer`와 함께 둔다. 업그레이드는 범위 밖이다(게터·형태·스케일에 영향).
- **C10. `allowed-tools`는 한 줄이다**: `Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)`. 구조 검사의 정확 일치 규칙을 그대로 쓴다(결정 15 철회). 분석용 Python은 모델 자신의 일이다. 스킬은 그것을 미리 승인하지 않는다(임의 코드 실행을 넓게 승인하는 셈이라서).
- **C16. 언어·위치**: SKILL.md·help·코드는 영어, 계획·커밋·PR은 한국어. 프로젝트 스킬 `.claude/skills/invest`이고 자기완결이다.
- **C17. 개발 기록**은 커밋 본문과 이 파일 끝 `# 구현 기록`(PR ③에 포함)에 둔다. 스킬 코드의 `# 성진:` 주석은 불변조건·실패 조건만 남긴다. 옛 `yahoo/`의 측정 이력 주석(감사 지적)은 이식할 때 기록으로 옮긴다.
- **C18. `data/`는 커밋하지 않는다.** `.gitignore`에 `.claude/skills/invest/data/`를 넣고, 자리표시 파일은 두지 않는다.
- **C19. 라이브러리 캐시**는 결정 17의 승인된 예외다. 모델이 분석 중 만드는 파일은 작업 디렉터리에 둔다. 이것은 스킬 상태가 아니다.

**Yahoo CLI**(결정 18–23)

- **C21. 명령 표면**:
  - 명령: `search`, `quote`, `history`, `company`, `financials`, `analysts`, `holders`, `fund`, `options`, `screen`, `market`, `calendar` + PR ②의 `filing`.
  - 종류가 여럿인 명령은 `KIND`를 첫 위치 인자로 받는다(닫힌 선택지). 옛 46종을 모두 담고, 옛 `prices actions`는 `history --actions`가 된다.
  - help는 두 단계다. 루트 지도는 한 화면이고, `<command> --help`는 그 명령의 종류(한 줄씩)·인자·영수증 형식·종료 코드만 담는다.
  - 크기 상한을 테스트로 고정한다: 루트 ≤ 2,500자, 명령 help ≤ 4,000자. 상한은 짧음의 검사일 뿐이고, 자기완결성은 Y1이 따로 본다.
  - **출력** 필드의 단위·시점·범위 사실은 help에 쓰지 않고, 결과의 `units`·`as_of`·`coverage`·`warnings`·`notes`로 낸다.
  - **입력**의 단위는 인자 계약이므로 help가 말한다. 예: `screen run --query`의 값은 `screen fields`가 필드마다 보여주는 입력 단위를 따른다. 결과에서야 알려주면 늦다(M2 검토).
  - 종류와 인자 선언은 `cli.py`가 가진다(표면). `load` 입구의 `kinds()`가 `yahoo` 카탈로그의 키를 돌려주고, 테스트가 두 목록이 같은지 본다. CLI는 system을 직접 import할 수 없기 때문이다.
  - 검증하는 입력 한도(`screen --limit ≤ 250`, `calendar --limit ≤ 100`)는 help의 인자 설명에 적는다. 원천이 바꿀 수 있는 그 밖의 한도는 거절 메시지와 fix가 말한다.
- **C22. 영수증과 파일**(결정 20, M7·M8):
  - **저장**: 명령마다 결과 전체를 `data/results/<id>/`에 저장한다.
    - `result.csv`: 표. 긴 형식이고 `target` 열이 있다.
    - `result.json`: 중첩 기록(뉴스, 프로필 본문, 섹터 개요, 공시 목록의 exhibits).
    - `receipt.json`: 잘리지 않은 영수증. 모든 열과 단위, 모든 경고·notes, 보낸 쿼리, 대상별 시각.
    - `<id>`는 호출마다 시각과 무작위 값으로 새로 만든다. 임시 디렉터리에 쓴 뒤 rename으로 게시해, 반쯤 쓴 결과가 보이지 않게 하고 이전 결과를 덮어쓰지 않는다.
    - 파일은 원천의 전 정밀도를 보존한다. 가격 7자리 반올림은 인라인 표시에만 적용한다(옛 `prices.PRECISION` 계약).
  - **출력**(stdout, JSON 문서 하나, 키 순서 고정):
    - 문서: `status`, `command`, `receipt_path`, `file{path,format,rows,columns}`, `units`, `warnings`, `notes`, `results`, `trimmed`, `projected`.
    - 대상마다: `target`, `status`, `rows`, `observed_at`, `as_of`, `currency`·`financial_currency`(돈이 있을 때), `coverage`, `conditions`(검증한 인자가 있을 때), 그리고 `data`(인라인 상한 안) 또는 `first`/`last` 미리보기, 실패면 `error{code,message,fix}`.
  - **필수와 생략 가능의 구분**: `warnings`는 해석을 바꾸는 사실이라 줄이지 않는다. 예: "Value prices those shares at the current quote, not at Date Reported", "query sent in Yahoo's own units (--source-units)", "last bar provisional". `notes`는 설명이라 줄일 수 있다. 줄이는 순서는 `data` → 미리보기 → `notes`이고, 줄였으면 `trimmed: true`다. 대상·상태·`warnings`·`receipt_path`는 줄이지 않는다.
  - `--fields A,B`는 인라인 투영만 바꾸고 `projected: true`로 표시한다. 파일과 `receipt.json`은 언제나 전부다.
  - **`warnings`의 형태**: 경고마다 짧은 코드와 한 줄 문장(≤ 160자)이다. 예: `{"code":"value_at_current_quote","text":"…"}`. 전문과 근거는 `receipt.json`에 있다.
  - **최소 영수증**은 줄일 수 없는 부분이다.
    - 문서: `{status, command, receipt_path, warnings(코드만), trimmed}`.
    - 대상마다: `{target, status, warning 코드, error.code}`.
  - **크기 검사**:
    - 인자 검증 때, 데이터셋이 낼 수 있는 경고 코드 전부를 넣은 최소형의 크기로 `--max-chars`를 사전 검사한다. 넘으면 네트워크 전에 exit 2다.
    - 네트워크 뒤 필수 부분만으로도 상한을 넘으면(예상 밖의 경고가 많을 때), 필수 부분을 그대로 출력하고 `over_budget: true`를 표시한다. 필수 의미를 버리지 않는 것이 상한보다 우선한다.
  - **파일이 없는 경우**:
    - 인자 오류: 아무것도 저장하지 않는다(`receipt_path` 없음).
    - 모든 대상이 빈 결과·실패: `receipt.json`만 저장하고 `file`은 null이다.
    - 저장 실패: `local_io`로 실패를 보고한다. 존재하지 않는 경로는 내지 않는다.
  - `--max-chars` 시작값은 8000이다. 단계 7의 **조정 런**에서 정하고, 최종 평가 런 전에 고정한다(C13).
  - 보존은 전역 `--ttl-days`(기본 14, 0은 보존)이고 `data/results`·`data/filings`에 함께 적용한다. 테스트 격리는 `INVEST_DATA`로 한다.
  - 같은 `get_info()` 응답에서 나오는 `quote`와 `company profile`은 둘 다 info 전체를 파일에 저장한다. 그래서 다른 쪽 필드가 필요할 때 다시 조회하지 않아도 된다는 것을 `notes`가 말한다(옛 `--from`이 지키던 것).
- **C23. 단위**(결정 19, M1·M3·M4):
  - `yahoo/`가 결과를 넘기기 전에 정규화하므로, 기능 단위는 정규화된 값만 본다.
  - **어휘**: `ratio`, `multiple`, `shares`, `count`, `rank`, `money:quote`, `money:financial`, `money:unconfirmed`, `per_share:quote`, `per_share:financial`, `per_share:unconfirmed`, `date`, `datetime`, `text`, `unverified`(단위를 확정하지 못한 값 — 계산에 쓰면 안 되는 이유를 `warnings`가 말함). 대상별 `currency`·`financial_currency`가 `money:*`를 푼다.
  - **선언의 상태**: 단위 선언마다 `verified`(관계 검사·측정 근거가 있음)와 `declared`(옛 선언을 이식)를 구분해 `receipt.json`에 남긴다. "미선언 0"과 "검증됨"은 다른 주장이다.
  - **변환**(옛 선언과 1차 검토의 대조로 확정):
    - ÷100 → `ratio`: info의 `dividendYield`·`fiveYearAvgDividendYield`·`fiftyTwoWeekChangePercent`·`regularMarketChangePercent`·`postMarketChangePercent`·`debtToEquity`, `quoteType` INDEX일 때만 `52WeekChange`, 펀드 `3 Year Earnings Growth`, 옵션 `percentChange`, 캘린더 `Surprise(%)`.
    - 그대로 `ratio`: 주식의 `52WeekChange`, `SandP52WeekChange`, `trailingAnnualDividendYield`, 마진·성장·수익률, 보유 비율, 옵션 `impliedVolatility`, `earnings_history.surprisePercent`.
    - 1/x → `multiple`: `fund equity`의 Price/Earnings·Price/Book·Price/Sales·Price/Cashflow 네 행만(펀드 값과 Category Average 열 모두). 음수는 부호를 보존해 1/x로 바꾼다(음수 이익의 배수). 0은 역수가 없으므로 null로 바꾸고 `warnings`에 이유를 남긴다. null은 null 그대로다. 다른 `trailingPE`나 개별 종목 PER에는 적용하지 않는다.
    - 이름이 말하는 단위(`marketCap`이 돈이라는 것)는 변환하지 않고 `money:quote`로 표시만 한다.
  - **혼합 표**(한 열에 단위가 섞인 표: `fund equity`, `fund operations`, `holders insider-purchases`)는 긴 형식 `target, metric, source_column, value, unit`으로 저장한다.
    - `source_column`이 원래 열을 보존한다. 예: 펀드 값과 `Category Average`, `Shares`와 `Trans`.
    - 문서 `units`는 "per row: see the unit column"이라고 말한다.
    - `Total Net Assets`는 `unverified`이고, ISS 위험 지표는 `rank`(1–10, 1이 가장 낮은 상대 위험)다.
  - **통화 역할**: 데이터셋·필드마다 `quote`·`financial` 역할을 선언한다.
    - info: `marketCap`·가격·`dividendRate`는 quote, `totalRevenue`·`ebitda`·`totalCash`·`totalDebt` 등 재무 항목은 financial.
    - 재무제표: 전부 financial. 옛 `context["currency"]`가 financialCurrency였으므로 이식할 때 이름을 바꿔 `financial_currency`로 옮긴다.
    - ADR의 EPS·추정치처럼 근거가 없는 것은 단계 3에서 확인한다. 확인되지 않으면 `*:unconfirmed`로 남기고 역할을 추정하지 않는다.
    - 통화 자체를 받지 못하면 값은 유지하고 `warnings`에 "currency unconfirmed"를 남긴다.
  - **스크린 입력**(M1):
    - `screen fields`가 필드마다 `input_unit`·`yahoo_unit`·`status(measured|declared|unmeasured)`를 보여준다.
    - 비율 성격인데 Yahoo 단위가 측정되지 않은 필드를 비율로 쓰면, 네트워크 전에 exit 2로 거절한다. fix는 "send in Yahoo's own scale with `--source-units`"다. `--source-units`를 주면 쿼리 전체를 쓴 그대로 보내고 영수증 `warnings`가 그 사실을 말한다.
    - 금액·배수·개수·날짜·문자열 조건은 원래 단위다. help는 "값은 비율"이라고 뭉뚱그리지 않는다.
    - `screen presets`가 보여주는 쿼리는 CLI 입력 스케일로 바꿔 보여준다(그대로 `--query`에 넣을 수 있게). 영수증의 `sent_query`는 Yahoo 전송 스케일임을 이름으로 밝힌다.
    - 측정은 단계 3의 `measure_screen_scales.py`로 한다. 비율 성격 필드마다 반환 행의 대응 필드(예: `quarterlyrevenuegrowth.quarterly` ↔ `revenueGrowth`)와 비교하고, provenance를 표에 남긴다.
- **C24. 실패와 종료 코드**(Yahoo·공시 공통, M6):
  - **실패 코드와 증거**:
    - `not_found`: 원천이 심볼의 존재를 부정한다는 구체 신호가 있을 때만 쓴다.
      - 신호는 단계 3에서 정한다. 새 CLI와 같은 설정(`hide_exceptions=False`, yfinance 1.7.0)으로 없는 심볼(XYZQQ 등)과 정상 심볼의 빈 기간에 대한 **원천 HTTP 응답(상태·본문)**을 기록한다. 두 경우를 가르는 응답 신호(예: chart와 quoteSummary 응답의 오류 코드·설명)를 `refusals.py`에 정의한다.
      - getter 반환값(`get_info()`가 `None`)은 신호로 쓰지 않는다(3차 검토 N2). 2026-10-06 실측은 `hide_exceptions=False`에서 `None`이었다. 그러나 설치본 `quote.py`는 경로에 따라 예외·dict·`None`을 낸다. 그래서 반환값이 아니라 그 밑의 HTTP 신호로 판정한다.
      - 신호를 정하기 전까지 이 경우는 `no_data`다.
    - `no_data`: 그 밖에 이 요청에서 자료를 얻지 못한 경우. "possibly delisted"는 yfinance의 추측이므로 이 코드다. fix는 기간·interval 확인과 `search`를 권한다.
    - `not_applicable`: `quoteType`을 확인했고 그 종류가 이 상품 유형에 없을 때만. 예: EQUITY에 펀드 보유종목(`KeyError 'topHoldings'`). 유형을 확인하지 못했으면 `no_data`다.
    - `source_constraint`: span·reach 거절. fix가 허용 일수를 말한다.
    - `rate_limited`: 남은 대상은 `not_attempted`로 둔다.
    - 그 밖에 `upstream`, `invalid`, `local_io`, `unsupported`(공시 형식).
  - **보존할 옛 동작**:
    - `yf.config.debug.hide_exceptions = False`.
    - 부가 metadata 조회에서 429가 나도 이미 받은 본문은 보존하고 다음 대상을 멈춘다(옛 `prices.bars`, `financials`).
    - 그 뒤 저장 오류가 나도 관측한 rate-limit 상태를 지우지 않는다.
  - **상태 표**(대상 상태 → 문서 상태 → 종료 코드):

    | 대상 상태의 조합 | 문서 `status` | 종료 코드 |
    |---|---|---|
    | 모두 `ok` | `ok` | 0 |
    | `ok` + (`empty`·`error`·`not_attempted` 중 하나 이상) | `partial` | 8 |
    | 모두 `empty` | `empty` | 7 |
    | `ok` 없음, `error` 하나 이상 | `error` | 오류 코드 우선순위: `rate_limited` 5 > `invalid` 2 > `local_io` 4 > `upstream`·`no_data`·`not_found`·`not_applicable`·`source_constraint` 6 |
    | 공시: 모두 `unsupported` | `error` | 7 |
    | 인자 거절(네트워크 전) | `error` | 2 |

    표의 모든 칸을 `test_cli.py`가 고정한다.
- **C25. 시점(`as_of`)**(M5):
  - 모든 결과는 `observed_at`(CLI가 응답을 받은 시각, UTC)을 가진다.
  - `quote`: `market_state`와, 응답이 가진 원천 시각 필드 전부(`regularMarketTime`, `postMarketTime`, `preMarketTime`)를 각각 낸다. info 전체에 공통 시각이 있는 것처럼 말하지 않는다(notes).
  - `history`: 마지막 봉의 상태 `final | provisional | unknown`.
    - 일봉: 마지막 봉의 날짜가 `currentTradingPeriod.regular`의 세션 날짜와 같고 `observed_at` < `regular.end`이면 `provisional`, `observed_at` ≥ `regular.end`이면 `final`. 세션 날짜보다 이른 봉이면 `final`.
    - 주·월·분기봉: 마지막 봉이 덮는 기간이 `observed_at`에 끝나지 않았으면 `provisional`.
    - 인트라데이: `observed_at` < 마지막 봉 시작 + interval이면 `provisional`.
    - 판정 자료(세션 메타데이터, 시간대)가 없으면 `unknown`과 그 이유를 낸다. `final`로 기본값을 두지 않는다.
    - 메타데이터는 history 응답에 실려 오지만, 없으면 yfinance가 별도 요청을 한다. 그 요청의 실패는 본문을 지우지 않는다(C24).
  - 보유자: `Date Reported`는 분기말이다. `Value`는 `money:quote`이고 `warnings`가 현재가 평가임을 말한다.
  - 재무제표 열은 회계기간 말이고, 추정치 행은 상대 기간이다(notes).
- **C26. 범위·조건 확인**(M2, 옛 `conditions`):
  - 데이터셋마다 범위 문장을 선언한다. 예: "the largest institutional holders Yahoo lists", "Yahoo's recent insider transactions, not every filing", "first page of search".
  - 원천에 수를 보내는 데이터셋은 `requested`/`received`를 낸다. 그리고 옛 shortfall 경고를 `warnings`로 유지한다. 예: 뉴스의 sponsored 항목 제거, 첫 페이지만 읽음. 받은 수가 적다는 것이 목록의 끝을 뜻하지 않는다.
  - 페이지가 있는 원천(`screen run`, 캘린더)은 `next_offset`·`total`을 낸다. `total`은 원천의 주장이고, 페이지 사이에 행이 움직일 수 있다는 것을 `warnings`가 말한다.
  - 옛 `conditions`(요청값과 원천이 확인한 값의 구분)를 유지한다. 날짜 범위는 반환 행의 날짜로, offset·limit은 원천의 `start`·`count`로, 정렬은 단조성으로 `confirmed | not_applied | unverified`를 판정한다.
  - **스크린 조건**:
    - `screen()`은 반환 필드를 고를 수 없다(yfinance 1.7.0). 그래서 쿼리 필드 → 반환 필드 대응표(측정과 함께 단계 3에서 작성)로 비교한다. 대응이 없으면 `unverified`이고, 자동 추가 조회는 하지 않는다.
    - 쿼리 논리식 전체를 행마다 3값(참·거짓·미확인)으로 평가한다. 문서 `conditions.query`는 `{rows_true, rows_false, rows_unknown}`을 낸다. `OR`의 한 갈래가 거짓인 행은 정상이다.
    - `confirmed`는 "반환된 표본이 조건을 만족한다"는 뜻이다. 서버가 조건을 적용했다거나 모집단이 완전하다는 증거가 아니다(`warnings`). 빈 결과는 확인으로 세지 않는다.
- **C27. 대량 로드·마감**:
  - 심볼을 여러 개 받는 명령은 한 호출로 처리하고, 결과는 대상별 상태와 함께 긴 형식 파일 하나에 담는다. 대상마다 열 집합이 달라도 합집합 열로 쓴다. 429를 받으면 멈춘다.
  - 대상마다 `--timeout` 마감은 옛 방식을 보존한다: `SIGALRM` + `DeadlineExpired(BaseException)`(라이브러리의 넓은 `except Exception`을 통과시키기 위해), 그리고 `finally`에서 `alarm(0)`. 이것은 Unix·메인 스레드 계약이며, 네이티브 블로킹 호출의 즉시 중단까지 보장하지는 않는다(help의 `--timeout` 설명).
  - 30종목 1년 일봉 한 호출을 테스트(Y7)와 시나리오로 확인한다. 30개 대상 상태, 실제 원천 요청 수, 대상별 기간과 행 수를 본다.
- **C28. 이식 경계**(결정 22):
  - `yahoo/`의 fetch, 스케일 선언, 해석문, 거절 판독, 스크린 검증, 지역, 가격 정밀도를 새 계약(정규화된 표 + 단위 + 시점 + 범위 + warnings/notes)으로 옮긴다. 옛 `interpretation`·`gotchas` 문장 가운데 해석을 바꾸는 것은 `warnings`로, 설명은 `notes`로 보낸다. 옛 CLI 손잡이를 말하는 문장(`--fields`, `read ID`)은 버린다.
  - **잃으면 안 되는 의미** — 장치는 없어져도 의미는 남긴다:

    | 의미 | 새 자리 |
    |---|---|
    | 요청값과 원천 확인값의 구분(`conditions`) | C26 |
    | 원천 페이지(`next_offset`, `total`, 페이지 이동) | C26 |
    | 여러 원천 시각과 관측 시각 | C25 |
    | shortfall 경고 | C26 |
    | quote·profile이 같은 응답이라는 사실(`--from`) | C22 |
    | 열 이름 충돌 방지(`target`·`side`·index 이름), 대상별 열 합집합, index·시간대·큰 정수·결측 보존, 중첩은 JSON | Y6 |
    | 게시 실패 시 부분 파일 비노출 | C22 |
    | 화면은 7자리, 저장은 전 정밀도 | C22 |

  - `--periods`:
    - 재무제표(income·balance·cashflow)에서는 없앤다. 옛 구현은 받은 뒤 로컬에서 잘랐는데, 새 계약은 받은 것 전부를 저장한다.
    - `valuation`에서는 원천에 보내는 수이므로 유지한다.
  - `history --actions`는 옛 `prices actions`와 같다. 배당·분할·자본이득이 있는 날짜의 행만 낸다.

**공시**(결정 4·6, 계획 검토 1차 반영)

- **C2. 공시 명령은 `filing URL…` 하나다.** 받는 URL을 주면 결과 파일과 지도를 낸다.
- **C3. 결과 식별과 저장**(F2):
  - 결과 키는 `sha256(canonical source URL ⏎ 원본 sha256 ⏎ 변환 버전 ⏎ 디코딩 조건(content-type charset))`의 앞 16자다. canonical source는 sec.gov 아카이브 URL이고, CDN 별칭은 같은 값으로 정규화한다.
  - 결과는 `data/filings/<key>/`에 `document.txt`·`map.json`·`source.json`·`original.<ext>`로 둔다.
  - 게시는 임시 디렉터리를 만든 뒤 rename으로 한다. 이미 있으면 재사용하고, 덮어쓰지 않는다.
- **C4. 받는 URL**(F6):
  - 허용: Yahoo CDN `https://cdn.yahoofinance.com/prod/sec-filings/<cik10>/<acc18>/<file>`, 그리고 같은 문서의 `https://www.sec.gov/Archives/edgar/data/<cik>/<acc18>/<file>`(CDN으로 매핑).
  - Yahoo S3 `…/Financial_Report.xlsx`는 받지 않고 `unsupported`로 낸다.
  - 그 밖의 호스트·자격증명·`..`·fragment는 네트워크 전에 거절한다(exit 2).
  - redirect는 따라가지 않는다(3xx → `upstream`). 이미지는 받지 않고 `[image: alt | URL]`로 남긴다.
- **C5. 형식**(F6): HTML(인라인 XBRL·단일 `<DOCUMENT>` 래퍼 포함)과 일반 텍스트만 변환한다.
  - PDF·XLSX·이미지·XML·여러 문서 SGML을 감지하면 `unsupported`다.
  - 200이어도 본문이 비었거나 읽을 텍스트가 없으면 `empty_document` 오류다.
- **C6. 목차는 문서 자신의 링크 목차이고, 확정할 수 있을 때만 낸다**(결정 1·F4).
  - 내부 링크를 출처 묶음(표 하나 또는 표 밖 블록 하나)으로 모은다.
  - 다음을 모두 만족하는 묶음이 정확히 하나일 때만 `contents`로 낸다.
    1. 서로 다른 목적지가 3개 이상이다.
    2. 링크 순서와 목적지 순서가 90% 이상 일치한다.
    3. 묶음이 첫 목적지보다 앞에 있다.
    4. 같은 조건을 만족하는 다른 묶음보다 목적지가 많다.
  - 확정하지 못하면 `headings`(set-apart 줄)를 낸다. `map.json`에는 모든 묶음을 후보로 남긴다.
  - 양식·티커별 규칙은 두지 않는다.
- **C7. 공시 영수증**(F5): C22의 문서 형식을 따른다. 대상마다 `target`·`status`·`source`·`path`·`map_path`·`lines`·`chars`를 먼저 두고, 그다음 `contents`나 `headings`, `tables`·`images`·`links` 개수, `limits`, `trimmed`를 둔다. 축소는 `inside` → `headings` → `contents` 순서로 한다. 종료 코드는 C24를 따른다.
- **C8. 공시 발견은 `company filings SYMBOL`**이다. 결과 파일(JSON)에 날짜·유형·제목·exhibits 맵이 있다. 영수증 미리보기는 날짜·유형·첨부 수를 보이고, `notes`가 "date is the filing date; exhibits map document types to Yahoo's copies of the SEC documents, which `filing` reads"라고 말한다.

**검증**

- **C11. 지우는 것·이식하는 것**은 `## 구현 후 디렉터리 구조`에 목록으로 둔다.
- **C12. 단위 검증은 셋으로 나눈다**(M3·M4·2차 검토 §2).
  1. **변환 함수 검사**(`test_units.py`, offline, 기록된 응답).
     - 단계 3에서 yfinance 1.7.0으로 받은 원천 응답을 `tests/invest/fixtures/yahoo/`에 provenance와 함께 저장하고, HTTP 대체로 CLI에 넣는다.
     - 원천 raw 값과 리터럴 기대값으로 출력값과 `units`를 정확히 비교한다. 비교 대상은 C23 변환 표의 모든 항목(÷100, 그대로, 1/x)이다.
     - 경계: 역수의 0·null·음수, 음수·0 EPS의 surprise, INDEX가 아닌 상품의 `52WeekChange`, `unverified` 값.
     - 스크린 번역: 측정된 필드 0.2 → 보낸 값 20. 미측정 비율 필드 → 네트워크 전 exit 2. `--source-units` → 그대로 보냄. presets는 입력 스케일로 보임.
     - 통화 연결: TM에서 `marketCap`·가격은 `currency`(USD)와, `totalRevenue`와 재무제표 금액은 `financial_currency`(JPY)와 묶인다. 두 통화를 받아 놓고 역할을 잘못 연결한 구현이 실패하도록 필드 단위로 검사한다.
  2. **원천 스케일 사실**(같은 기록 응답, 관계는 정확한 산식과 허용오차로 정의). 비교할 수 없는 경우(null, 0)는 그 사실을 기록하고 건너뛴다.
     - KO `dividendYield` raw = `dividendRate`/`regularMarketPrice`×100 ± 0.05.
     - 같은 분기에서 `earnings_history.surprisePercent` = (`epsActual` − `epsEstimate`)/|`epsEstimate`| ± 0.0005이고, `get_earnings_dates` `Surprise(%)` raw = 그 값 × 100 ± 0.05.
     - 지수 raw `52WeekChange` = raw `fiftyTwoWeekChangePercent`.
     - 펀드 P/E 역수: 산식이 다른 수치(`trailingPE`)와는 비교하지 않는다. 네 행이 수익률 형태(|x| < 1)인지 보는 것은 개연성 검사일 뿐이다. 그것만으로는 `verified`를 주지 않고 `declared`로 둔다. 독립 근거(같은 펀드의 공개 P/E 등)를 단계 3에서 찾으면 그때 `verified`로 올리고 출처를 남긴다.
  3. **선언 완전성**(`test_units_declared.py`, offline): 데이터셋마다 모든 숫자 열·행이 어휘 하나로 선언됐는지와, 각 선언의 `verified|declared` 상태를 본다. 예외 목록은 테스트 안에 명시한다.
  4. **drift**(`test_live.py`, live): 2의 관계를 같은 산식·허용오차로 다시 잰다. 자료 부족·429·시점 불일치는 `inconclusive`이고 통과로 세지 않는다. 재시도는 1회, 그다음은 중단한다.
- **C13. 은행과 합격선**(F8, 결정 23). `expect`는 결과가 지켜야 할 것(단위·시점·범위·출처·실패 보고)으로 쓴다. 시점마다 변하는 수치 범위는 보조 신호다. 공시를 열었는지는 경로 지표이지 판정이 아니다.
  - 계약 검사와 모델 비교를 나눈다.
    - 실패·단위·시점·대량의 **분류 정확성**은 기록 응답 테스트(Y2–Y7)가 증명한다.
    - 모델 시나리오는 모델이 그 결과를 답으로 옮기는지를 본다.
  - 구성:
    - **Yahoo 17**: 실험 3·4와 같은 프롬프트.
    - **큰 결과 9**: 옛 예산 7건(전제: 결과가 인라인 상한을 넘어 파일로 감) + 고정 30종목·2025년 일봉 상관·분포 2건. 기대값은 단계 1에서 독립 계산해, 계산 스크립트·입력 시점과 함께 저장한다.
    - **조용한 실패 3**: 원인별로 하나씩 둔다. 전제와 원천 증거는 단계 1에서 실측으로 고정한다.
      - 실제로 없는 심볼이 섞인 다종목 수익률 → `not_found`.
      - 주식에 펀드 보유종목 → `not_applicable`.
      - 정상 심볼이지만 상장 전 기간을 요청 → `no_data`.
    - **희귀 단위 3**: 항목마다 원천 필드·상품 유형·변환 규칙·허용오차·null/0 처리를 고정한다. raw 값은 런마다 받은 응답에서 읽는다.
      - KO `debtToEquity`(÷100).
      - QQQ의 펀드가 **보고한** `equity_holdings` P/E(1/x). 모델이 종목별 PER을 평균 내는 문제가 아니라고 프롬프트에 밝힌다.
      - AAPL 최근월 ATM 콜의 `impliedVolatility`(그대로)와 `percentChange`(÷100)를 같은 결과에서 묻는다.
    - **일관성 5×3**: Yahoo 17 중 다섯(ko-dividend·msft-pe-trend·qqq-top10·unplanned·growth-screen)을 세 번씩 돌린다.
    - **PR ②**: 공시 7, 경계 2.
    - **홀드아웃 5**(Yahoo 3, 공시 2): 단계 1·8에서 쓰고, 마지막 검증 전까지 돌리지 않는다.
  - **조정 런과 평가 런**:
    - 인라인 상한·미리보기 행 수·notes 문구는 조정 런(Yahoo 17 중 일부와 큰 결과, 1회)으로 정한다.
    - 그다음 설정과 `judge.md`를 커밋해 고정하고, 평가 런을 돌린다. 평가 런 뒤 설정을 바꾸면 평가 런을 다시 돈다.
    - 홀드아웃은 평가 런 뒤에 한 번 돌린다.
  - **합격선(PR ①, 평가 런)**:
    - **L과 짝 비교**: 같은 모델·같은 yfinance 1.7.0·같은 도구(`Bash,Read,Write`)로 Yahoo 17을 **invest·L 짝 2쌍** 이상 돌린다. 짝 안에서는 시나리오마다 실행 순서를 번갈아 두고, 각 런이 받은 데이터 시각(영수증 `observed_at`, L은 stream의 출력)을 기록한다.
      - 한 쌍은 미국 정규장에 돌린다. 실행일의 거래소 세션·휴장·DST를 `get_history_metadata()`로 확인하고, 그 증거를 결과 폴더에 저장한다.
      - invest가 L보다 나쁜 시나리오(같은 쌍에서 L 합격·invest 불합격)가 0이어야 한다. 실험 4 판정 대비 새 의미 오류도 0이어야 한다. 아니면 성진이 받아들일 때만 통과한다.
      - 네 함정은 전제가 성립한 invest 런에서 오류 0.
    - **live 판정의 기준**: 고정 수치 비교는 기록 응답 테스트에만 쓴다. live 런은 **그 런이 실제로 받은 응답**(invest는 `receipt.json`·결과 파일, L은 stream의 출력)에서 계산한 기대값·계약·시각으로 판정한다.
    - **큰 결과·대량**:
      - 독립 계산은 그 런의 결과 파일(같은 입력 자료)로 하고, 모델의 답과 허용오차 안에서 일치해야 한다.
      - 역사적 구간(2025년, 수정 전 `Close`)은 단계 1에 저장한 값과도 대조해 원천 변화를 따로 기록한다.
      - 전체 사용 확인: 모델의 계산 코드(stream의 Python)가 쓴 대상·기간·행 수가 파일의 것과 같고, 답이 보고한 기간·행 수도 같아야 한다. `head()` 등 일부만 쓴 계산이나 미리보기만 보고 낸 결론은 실패다.
    - **조용한 실패**: 실패한 대상과 영수증이 말한 이유(코드)를 답에 밝힌다. 빠뜨리거나, 0으로 채우거나, 영수증에 없는 이유를 지어내면 실패다.
    - **희귀 단위**: 그 런의 응답에서 고른 계약·raw 값을 기준으로, 정규화 기대값과 허용오차 안이어야 한다. 최근월 ATM 옵션은 런마다 계약이 달라질 수 있으므로 그 런의 만기·행사가를 쓴다.
    - **일관성**(의미 불변식): 세 번의 런이 다음을 지켜야 한다. 다섯 중 넷 이상이 이를 지켜야 한다.
      - 같은 요청 범위(대상·기간·조정 방식).
      - 같은 단위·스케일.
      - 같은 실패 보고, 같은 시점·범위 문장.
      - 각 런의 수치는 **그 런의 응답**에 맞을 것. 런 사이 수치가 같을 필요는 없다.
      - 명령 집합의 동일 여부는 진단 지표로만 기록한다. L에도 같은 불변식으로 비교 수치를 낸다.
    - **효율**(평가 런의 invest Yahoo 17, 쌍마다 따로 집계):
      - help 글자 합계 ≤ 57K. 옛 CLI 285K의 20%다.
      - CLI 실행 수 중앙값 ≤ 4. Bash 안의 `cli.py` 실행을 각각 센다. 한 Bash에 묶어도 줄지 않는다.
      - 함께 보고만 하는 것: 모델에게 읽힌 전체 글자(SKILL.md + help + 영수증 + 결과 파일 Read·Python 출력), 비용, 시간. L·옛 CLI와 나란히 놓는다.
      - 효율만으로 합격이라 하지 않는다.
    - 하나라도 못 미치면 증거를 들고 성진에게 묻는다(재설계 / 기준 조정 / L로 회귀).
  - 홀드아웃: 해결하지 못한 중대한 의미 오류가 있으면 머지를 막는다. 고쳤으면 그 사례를 회귀 세트로 옮기고, 같은 성질의 새 홀드아웃으로 다시 확인한다.
- **C14. 채점은 codex 독립 채점**(스키마 출력)이다. 규칙은 `scenarios/invest/judge.md`·`judge-schema.json`에 둔다.
- **C15. 실행기 도구**: 기본은 `Bash,Read,Write,WebFetch,WebSearch`이고, Yahoo 은행은 실험과 같게 `Bash,Read,Write`다. `INVEST_DATA`는 런마다 다르게 주지만, 모델이 만든 파일이나 라이브러리 캐시까지 격리하지는 않는다(한계).
- **C20. 읽기 전략 문장의 제거 시험**: 공시 7건을 문장 있음/없음으로 같은 시각에 각 2회 짝지어 돌린다. 합격 수가 같고 읽은 글자 중앙값 차이가 20% 이내면 문장을 지운다.

### 원리 충돌과 해소

| # | 서로 당기는 두 원리 | 정하는 조건 | 갈리는 사례 |
|---|---|---|---|
| ① | "직접 할 수 있는 조회를 명령으로 감싸면 좁힌다" ↔ "정해진 계산·검증 계약은 인터페이스에" | 매번 같게 가는 일(호출·스케일 환산·시점 판정·범위 표시·실패 판정·저장)은 명령이 숨긴다. 질문마다 달라지는 일(어떤 계산·비교·해석)은 결과 파일 위에서 모델이 한다. 좁히는 정도를 줄이는 장치: 받은 결과 전부를 파일로 연다, 스크린 쿼리 문법(AND/OR·연산자)은 그대로 통과시킨다, 스케일을 모르는 필드는 `--source-units`로 원천 단위 그대로 보낼 수 있다. 그래도 명령이 고른 게터·인자 밖은 닿지 않는다(성진이 결정 18로 받아들인 비용) | 스케일 환산 → `yahoo/` / 상관계수 → 모델의 Python |
| ② | "Interface over document" ↔ 단위 사실을 어디에 | 출력의 단위·시점·범위는 결과 자신이 말한다(`units`·`as_of`·`coverage`·`warnings`). 입력의 단위는 인자 계약이라 help와 `screen fields`가 말한다. SKILL.md에는 단위 표를 두지 않는다 | `dividendYield` → 출력 `ratio` / `screen run --query` 값의 단위 → help·`screen fields` |
| ③ | "필요한 때로 분리" ↔ 단일 SKILL.md(결정 13) | 명령별 사실은 그 명령의 help와 결과가 가진다. 그래서 SKILL.md에는 모든 경로가 쓰는 것만 남는다 | 옵션 체인 사실 → `options --help`·영수증 / 라우팅 → SKILL.md |
| ④ | "사람처럼 점진적으로" ↔ 통째 읽기 금지 아님 | 도구는 지도와 크기로 싼 길을 만들고 강제하지 않는다. C20으로 문장의 필요성을 확인한다 | 20-F 58만 자 → 지도 범위 / 1만 자 보도자료 → 통째 |
| ⑤ | 문서 신호만 쓰기(결정 1) ↔ 양식 지식으로 더 좋은 지도 | 지도는 링크 목차·굵게·표에서만 만들고, 확정할 수 없으면 확정하지 않는다(C6) | "Item 1A" 정규식 없음 / NBIS 1행 표 제목은 set-apart로 |
| ⑥ | 원천 충실(값 그대로) ↔ 정규화(결정 19) | 값의 스케일만 바꾸고, 이름과 의미는 바꾸지 않는다. 바꾼 사실은 `notes`·`units`로 밝힌다. 원천 응답은 파일 옆에 두지 않는다(정규화 전 값이 두 번째 진실이 되지 않도록). 검증은 C12가 한다 | `dividendYield` 3.02 → 0.0302 `ratio` / `marketCap`은 그대로 `money:quote` |

### 추론·가정·남은 불확실성

- 새 CLI가 L 이상일지는 측정 전이다. 근거는 두 가지다. 옛 CLI의 비용 67%가 help였다는 실측, 그리고 L이 이긴 지점(시점·범위)을 이 설계가 결과에 넣는다는 점이다. C13 짝 비교로 확인하고, 지면 성진에게 묻는다.
- 인라인 상한 8000자와 미리보기 행 수는 시작값이다. 단계 7 은행 런에서 조정한다.
- 스크린 필드 스케일 표가 모든 비율 성격 필드를 덮는지는 단계 3 측정 뒤에 안다. 못 덮은 필드를 비율로 쓰면 거절하고, 원값 전송은 명시적 `--source-units`에서만 한다(C23).
- 수용된 가정: Yahoo CDN 경로는 당분간 유지된다. 바뀌면 `filing`이 `not_found`/`upstream`으로 실패한다.
- 기본값을 교정하는 문장은 claude-opus-5-5 기준이다. 모델이 바뀌면 같은 은행으로 다시 본다.

### 미결

- 없음. 계획 검토 2·3차의 major는 모두 반영했다. 구현 중 결정이 필요하면 AskUserQuestion으로 묻는다. 단계 3에서 정해지는 것(스크린 스케일 표, `not_found` 신호, ADR 통화 역할, 역수의 독립 근거)은 측정 결과와 함께 구현 기록에 남긴다.

## skill-maker 조항 대조표

`/Users/seongjin/.claude/skills/skill-maker/SKILL.md`의 조항마다, 이 계획에서 그것을 채우는 자리다. "충족 예정"은 구현·검증 뒤에야 성립한다.

| 절·조항 | 이 계획의 자리 |
|---|---|
| 도입: 기본값과 전문가의 차이만 | 실험 1–4. 차이를 낸 시점·범위는 결과 필드(C25·C26)로, 공시 구조 상실은 `filing`으로 간다 |
| 도입: 사용자 수단이 목표를 해치면 증거·대안·권고 | 결정 18 전에 실측(L 17/17, 옛 CLI help 67%)과 대안 셋을 보이고 실측 후 결정을 권했다. 성진은 확정을 택했고, 비교는 C13으로 옮겼다 |
| 도입: 기존 스킬에도 같은 이해 | 옛 CLI의 비용 원인(help)과 실패(screen-tech)를 추적해 설계에 반영(C21·C26) |
| What earns: 각 줄이 행동을 바꾸는가 | 묶음 단위 대조(C13 짝 비교). 문장 단위는 C20 하나만 시험(나머지 미검증으로 기록) |
| What earns: principle over rail | SKILL.md는 이유와 함께 판단만 쓴다. 명령 순서를 강제하지 않는다 |
| What earns: interface over document | 원리 충돌 ②: 단위·시점·범위는 결과에, 인자·실패는 help에. SKILL.md에 명령 사실 복사본 없음 |
| What earns: for the model | C17. SKILL.md·help에 측정 경위·모델 이름 없음(단계 6·11 판정) |
| What earns: dense, 원천 소유 값은 실패로 | CLI가 검증하는 입력 한도(250행·100행)는 help의 인자 설명에, 원천이 바꿀 수 있는 한도(인트라데이 span·reach)는 거절 메시지와 fix에 둔다(C21). 목록 범위는 "현재 나열하는 것"으로 쓴다 |
| What earns: 교정 문장은 행동·이유, 모델은 기록 | SKILL.md의 판단 문장, 기준 모델은 구현 기록에 |
| What earns: 차이 없으면 스킬 없음 | none 14/17과 차이가 관측됐다 |
| What earns: 이웃 스킬 경계 | 단계 7·12 skill-doctor(finviz), C1의 sec 공존 창 |
| Drawing out: 읽고 묻기·대조·실행 실패 분리 | 장부, 실험 1–4, 조건 차이 명시, 판정 순서(검증 절) |
| Drawing out: 권위 구분·장부 | 사실·실험·정답 근거·결정(변경·철회 표시)·Claude가 정한 것·추론 |
| Drawing out: 새 사례로 경계 확인 | 결정 9 경계 시나리오, 홀드아웃이 머지를 막음 |
| Drawing out: 위치·언어 | C16 |
| Writing judgment: 이유·조건·뒤집는 조건·사례 | 원리 충돌 표 |
| Writing judgment: 예시는 차이를 보일 때만 | 정규화 notes, 스크린 0.2 → 20 |
| Writing judgment: 확인 가능한 완료 | C13 합격선, 작업 단계 판정 열 |
| Writing judgment: 직접 할 수 있는 조회를 감싸지 않음 | 원리 충돌 ①: 결과 전부를 파일로 열고 쿼리 문법을 통과시켜 좁힘을 줄인다. 계산은 모델이 한다. 남는 좁힘은 결정 18의 비용으로 기록한다 |
| Writing judgment: 필요한 때로 분리 | 원리 충돌 ③: 명령별 사실은 명령 help와 결과에 |
| Code: 트리·실행용만·테스트가 지킴 | `## 구현 후 디렉터리 구조`, 단계 6·11 구조 검사 등록 |
| Code: `cli.py` 하나·패키지 `invest`·`sys.path` 무편집 | 구조 검사, `pyproject.toml` pythonpath(테스트용) |
| Code: `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`, PEP 723 | C9·C10 |
| Code: 명령은 반복·불안정한 일을 숨길 때만 | 원리 충돌 ① |
| Code: `cli.py`는 표면, 도메인 판단은 단위 | 재시도·정규화·형식 판정은 시스템, 대상 순회·영수증 조립·축소는 기능, 저장은 스토어 |
| Code: `--help` 두 단계, 명령 help가 스스로 | C21, Y1(크기 상한과 별개로 입력 단위·인자 적용 범위·실패·출력을 명령 help만으로 알 수 있는지 검사) |
| Code: stdout 결과·싼 신호 먼저·고유 손잡이, 종료 코드 | C22·C24, 결과마다 새 `<id>`·공시는 내용 키 |
| Code: 깊은 단위·공개 입구 | 각 단위의 `__init__`만 공개(함수·타입), 테스트도 입구로만 |
| Code: system이 시스템 말을 전부, 스킬의 말로 | `yahoo/`가 정규화·시점·범위·실패를 스킬 어휘로 넘김. `sec/`가 URL·HTTP·형식·HTML |
| Code: import 한 방향, 간선 등록 | 기능 → 시스템·스토어 → 공용, 기능 간선 없음 |
| Code: 상태는 `data/` | `data/results`·`data/filings`, 라이브러리 캐시는 결정 17의 예외 |
| Code: 테스트·job은 레포, 입구만 | `tests/invest`, `scenarios/invest`, `UNITS['invest']` |
| Code: 레거시 이행은 따로 합의 | 이 스킬은 결정 16·18·22로 합의. 다른 스킬은 그대로 |
| Done: 전문 승인 | 단계 7(PR ①), 단계 12(PR ②) |
| Done: 판단·경계·불확실성, 승인 ≠ 성능 | 원리 충돌 표, 남은 불확실성, 구현 기록 |
| Done: 대조 차이마다 자리 | 시점 → `as_of`, 범위 → `coverage`, 단위 → 정규화, 조건 오보고 → 조건 판정, 지어낸 SEC 신원 → CDN 경로, 공시 구조 상실 → `filing`, 공시로 안 감 → 라우팅 문단 |
| Done: validate `--strict .claude/skills` | 단계 7·12 |
| Done: 코드 계약·help 일치·구조 검사 | `## 테스트 설계` |
| Done: 다른 모델 계열 검토와 판단 | codex(단계 7·12), 수용·기각 이유를 구현 기록에 |
| Done: 개발 기록은 밖 | C17 |

## 구현 후 디렉터리 구조

### 스킬 (오른쪽 주석에 skill-maker 트리 틀의 칸을 적는다)

```
.claude/skills/invest/
├── SKILL.md                         # 호출법·라우팅·결과를 답에 쓰는 판단·공시 찾기/읽기/인용 (짧게, C10 allowed-tools 한 줄)
├── data/                            # [data/] 런타임 생성, 커밋 안 함(C18)
│   ├── results/<id>/                #   Yahoo 명령 결과: result.csv | result.json, receipt.json (C22)
│   └── filings/<key>/               #   공시 문서: document.txt, map.json, source.json, original.<ext> (C3)
└── scripts/
    ├── cli.py                       # [cli.py] 유일한 진입점: PEP 723(yfinance 1.7.0·lxml·bs4·requests, exclude-newer), 루트 지도와 명령 help, 인자·검증·디스패치·종료 코드
    └── invest/                      # [<skill_name>/] 유일한 패키지
        ├── __init__.py              #   비어 있음
        ├── receipts.py              # [<helper>] 영수증 문서: 상태 집계·축소 순서·최소 receipt 사전 검사·실패 정보 형식 (load·filing 공용)
        ├── yahoo/                   # [<system>/] Yahoo Finance(yfinance). 입구 = kinds·fetch·실패 타입
        │   ├── __init__.py
        │   ├── catalog.py           #   (이식) 명령 종류 → 데이터셋, fetch 호출
        │   ├── datasets.py          #   (이식·개편) Dataset 계약: fetch·단위 선언·notes·coverage·as_of·순서
        │   ├── units.py             #   (신규) 단위 어휘, 퍼센트 → 비율·역수 → 배수 정규화, 돈 열의 통화 종류
        │   ├── encode.py            #   (이식) pandas/numpy → 기본 값, 손실 없이(반올림은 인라인 표시에서만)
        │   ├── refusals.py          #   (이식·확장) 원천 거절 → not_found·not_applicable·source_constraint·rate_limited·upstream
        │   ├── timing.py            #   (신규) as_of: 시장 상태·마지막 봉 확정 판정·원천 시각
        │   ├── info.py  prices.py  company.py  financials.py  analysts.py  holders.py
        │   ├── fund.py  options.py  market.py  calendar.py  search.py      #   (이식) 데이터셋별 fetch·선언
        │   └── screen.py            #   (이식·확장) 쿼리 검증 + 비율 → Yahoo 단위 번역 표(측정, provenance) + 반환 행으로 조건 판정
        ├── load/                    # [<feature>/] Yahoo 명령 하나를 실행해 파일과 영수증으로. 입구 = run·kinds
        │   ├── __init__.py
        │   ├── run.py               #   대상 순회·대상별 마감(DeadlineExpired(BaseException))·429 정지·not_attempted
        │   └── receipt.py           #   표 → 긴 형식 행(열 충돌 방지·열 합집합·혼합 표는 metric/value/unit), 인라인/미리보기(7자리 표시), warnings/notes
        ├── results.py               # [<store>] data/results: <id> 생성·임시 → rename 게시·보존기간 삭제·INVEST_DATA
        ├── sec/                     # [<system>/] (PR ②) Yahoo가 내주는 SEC 공시 문서. 입구 = locate·fetch·parse·Document·실패 타입
        │   ├── __init__.py  failures.py  locate.py  fetch.py
        │   ├── text.py              #   공백·U+200B·셀 텍스트(맨 아래)
        │   ├── decode.py  emphasis.py  grid.py  markup.py
        │   └── document.py          #   parse 조합: decode → markup → Document
        ├── filing/                  # [<feature>/] (PR ②) 공시 문서 → 읽기 파일과 지도. 입구 = open_documents·render
        │   ├── __init__.py  open.py  render.py  contents.py
        └── documents.py             # [<store>] (PR ②) data/filings 게시·재사용·보존기간
```

등록과 import 방향:

- PR ①: `SKILLS['invest'] = ('invest', {'receipts': 'common', 'yahoo': 'system', 'load': 'feature', 'results': 'store'})`, `UNITS['invest'] = {'edges': set(), 'jobs': ['scenarios/invest']}`. `INVOCATION`은 C10의 한 줄이다.
- PR ②: `'sec': 'system'`, `'filing': 'feature'`, `'documents': 'store'`를 더한다.
- import 방향:
  - `cli` → `load`·`filing`(+ `receipts`).
  - `load` → `yahoo`·`results`·`receipts`.
  - `filing` → `sec`·`documents`·`receipts`.
  - `sec` 안은 `text` ← `decode`·`emphasis`·`grid` ← `markup` ← `document`.
- 라이브러리 경계:
  - `yfinance`·`pandas`·`numpy`는 `yahoo/` 안에서만 import한다(옛 `test_boundary` 이식). 결과 파일은 `csv`·`json` 표준 라이브러리로 쓴다.
  - `lxml`·`bs4`는 `sec/` 안에서만, `requests`는 `sec/fetch.py`에서만 import한다.

### 옛 코드의 행방 (PR ①)

| 옛 위치 | 새 위치·처리 |
|---|---|
| `.claude/skills/yfinance/SKILL.md` | 새로 씀 → `invest/SKILL.md` |
| `scripts/cli.py` | 새로 씀(C21) |
| `yfinance_skill/yahoo/*` (15모듈) | `git mv` → `invest/yahoo/*`, 새 계약으로 개편(C28) |
| `yfinance_skill/{envelope,shape,leaf}.py` | 필요한 판정(빈 결과·조건)만 `load`·`yahoo`로 옮기고 삭제 |
| `yfinance_skill/{budget,selection,display,describe}.py`, `querying/` | 삭제(결정 20·21) |
| `yfinance_skill/{store,export}.py` | 삭제 → `results.py` 새로 씀 |
| `tests/yfinance/fixtures/{sitecustomize.py,shapes/}` | `git mv` → `tests/invest/fixtures/`, `INVEST_DATA`·새 경로로 고침 |
| `tests/yfinance/test_{company,market,prices,vocabulary,boundary,portability,live}.py` | `git mv` → `tests/invest/`, 새 출력 계약으로 기대값 재작성(의미는 유지) |
| `tests/yfinance/test_discovery.py` | 단위 부분 → `test_units_declared.py`, help 부분 → `test_help.py` |
| `tests/yfinance/test_{budget,selection,store,export,display,cli}.py`, `fixtures/store/` | 삭제(정밀도 규칙은 `test_prices`로, CLI 입력 검증은 `test_cli`로 새로 씀) |
| `tests/yfinance/model-scenarios.json` | `git mv` → `tests/invest/`, C13대로 개편 |
| `scenarios/yfinance/run.py` | `git mv` → `scenarios/invest/run.py`, 개편 |
| 로컬 `data/observations/` | git 밖이라 그대로 둔다(구현 기록에 "지워도 됨") |

PR ③: `.claude/skills/sec/` → `.tmp/sec-skill/`, `tests/sec/` → `.tmp/sec-tests/`(git에서는 삭제. 쓸 픽스처는 PR ②에서 `tests/invest`로 복사됨).

### 레포 (스킬 밖)

```
<레포>/
├── .gitignore                     # + .claude/skills/invest/data/, − yfinance/data/(①), − sec/Scripts/.env(③)
├── .github/workflows/test.yml     # ① yfinance 잡 → invest 잡(cli.py 의존성 export + pytest로 tests/invest), ③ sec 잡 삭제; offline 잡 --ignore=tests/invest
├── pyproject.toml                 # ① pytest pythonpath에 .claude/skills/invest/scripts
├── CONTRIBUTING.md  README.md  SECURITY.md  docs/usage.md     # yfinance(①)·sec(③) → invest
├── scenarios/invest/              # [<job>/] 유지보수자 일
│   ├── run.py                     #   모델 시나리오 실행기(조건: invest | L 기준선)
│   ├── judge.md  judge-schema.json  #   codex 채점 규칙(C14)
│   └── measure_screen_scales.py   #   스크린 필드 스케일 실측(C23) → yahoo/screen.py 표의 provenance
├── tests/invest/
│   ├── conftest.py                #   CLI seam(하위 프로세스 + HTTP 대체 + INVEST_DATA)
│   ├── fixtures/
│   │   ├── sitecustomize.py       #   (이식) requests·curl_cffi → 기록 응답, 그 밖의 네트워크는 exit 97
│   │   ├── shapes/                #   (이식) 옛 응답 모양 6개
│   │   ├── yahoo/                 #   ① 기록된 Yahoo 응답 + provenance(C12)
│   │   ├── documents/  holdout/   #   ② ← tests/sec/fixtures 복사
│   ├── test_help.py               #   ① 두 단계 help·크기 상한·모든 종류/인자 문서화·네트워크 0·data 미생성
│   ├── test_cli.py                #   ① 인자 검증(네트워크 전)·영수증 형식·축소·종료 코드 표 전 칸
│   ├── test_units.py  test_units_declared.py   #   ① C12
│   ├── test_timing.py             #   ① as_of: 장중/확정 판정, 원천 시각
│   ├── test_coverage.py           #   ① 범위 문장·requested/received·스크린 조건 판정
│   ├── test_failures.py           #   ① not_found·not_applicable·source_constraint·429 정지·부분 성공·마감
│   ├── test_bulk.py               #   ① 30종목 한 호출, 긴 형식 파일, 대상별 상태
│   ├── test_company.py  test_market.py  test_prices.py  test_vocabulary.py  test_boundary.py   #   ① 이식
│   ├── test_results.py            #   ① 결과 저장: 새 id·덮어쓰기 없음·보존·INVEST_DATA·다른 cwd
│   ├── test_portability.py        #   ① (이식) 실제 uv run, 공백·한글·$·' 경로
│   ├── test_live.py               #   ① (이식·개편) live + 정규화 drift
│   ├── test_parse.py  test_render.py  test_filing.py  #   ② 공시(P1–P8)
│   └── model-scenarios.json       #   ① 은행(C13), ② 공시·경계·홀드아웃 추가
└── tests/test_skill_layout.py     #   ① yfinance 등록 → invest 등록, ② invest 단위 추가
```

## SKILL.md 섹션 구조 (영어, 성진 전문 승인 대상)

```
---
name: invest
description: (PR ①) Read structured Yahoo Finance market and company data through a CLI built for analysis. Use for current
  or historical prices, dividends and splits, financial statements, valuation, analyst estimates, ownership, ETF and fund
  holdings, options, screening, markets and economic or company calendars — including 주가, 시세, 재무제표, 실적 추정,
  ETF 구성, 옵션 체인 and 종목 스크리닝 even when Yahoo is not named. Not for original SEC filing text, full news articles,
  Finviz-specific data, trade execution, or generic Python programming.
  (PR ②) + "and what a company says in its own SEC filings: how management reads its results, its outlook, its industry,
  customers, suppliers and partners — 경영진의 실적 해석, 회사 전망, 산업 시각, 고객·공급사 관계, 10-K·10-Q·8-K·6-K·20-F 원문",
  "Not for … filings Yahoo does not list". 단계 12에서 skill-doctor로 확정.
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
---

# Investment research data
¶ 호출: `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …`을 한 줄로. `--help`는 명령 지도, `<command> --help`는 그 명령의 종류·인자·영수증·종료 코드.
¶ 두 원천(결정 9): Yahoo가 가진 숫자는 데이터 명령에서, 회사 자신의 말과 Yahoo에 없는 숫자(부문 수치·가이던스·고객 비중)는 공시에서. (PR ①은 앞 절반만)

## Turning a result into an answer
¶ 계산은 결과 파일(영수증의 `file.path`)을 자기 Python으로 읽어서 한다. 미리보기 행은 확인용이고 표본이 아니다.
¶ 답에는 영수증이 말한 시점·범위·`warnings`를 함께 쓴다.
  - 마지막 봉이 provisional·unknown이면 종가라고 하지 않는다.
  - 목록이 덮는 범위(최대 보유자, 최근 내부자 거래, 첫 페이지, 스크린 매칭 행) 밖의 부재는 일어나지 않았다는 증거가 아니다.
  - 스크린 조건은 반환 표본에서 확인된 만큼만 말한다.
  - 실패·`not_attempted` 대상은 영수증의 코드 그대로 밝히고, 그 대상을 빼고 결론 내지 않는다. 이유를 지어내지 않는다.

## What a company says in its filings                         # PR ②
¶ 찾기: `company filings SYMBOL` → 결과 파일의 exhibits(문서 유형 → Yahoo의 SEC 원본 사본). 제목이 일반적이라 유형·날짜·첨부 구성으로 고른다. 서술이 있는 곳: 실적 8-K EX-99.1(일부 회사는 EX-99.2 CFO 코멘터리), 10-Q·10-K의 MD&A·위험요인, 10-K Item 1, 6-K 첨부·20-F. 짧은 본 문서가 첨부를 인용만 하면 첨부로 간다. 목록은 Yahoo가 지금 나열하는 것이다.
¶ 읽기: `filing URL…` → 읽기 파일과 지도(형식은 `filing --help`). 지도 → 절 → 구절·표·주석을 Read(offset·limit)·`grep -n`으로. 10-K·20-F는 20–60만 자이고, 1만 자 보도자료는 통째로 읽어도 된다(C20 대상).
¶ 인용: 원문 문서(source URL, 양식·첨부·제출일)와 절·표로. 로컬 줄번호는 이 파일 안의 좌표일 뿐이다.
```

- 단위 표·게터별 사실은 SKILL.md에 없다(원리 충돌 ②). 결과의 `units`·`notes`와 명령 help가 맡는다.
- `references/` 없음(결정 13).

## 명령 표면

### 루트 `--help` (≤ 2,500자)

```
usage: cli.py [--max-chars N] [--ttl-days N] COMMAND ...
Investment research data. stdout: one JSON receipt; each command's full result is a file under the skill's data/.
`COMMAND --help` states that command's kinds, arguments, receipt and exit codes.
commands:
  search QUERY                 instruments, news, lists or research matching a name or keyword
  quote SYMBOL...              current price, session state and market fields
  history SYMBOL...            bars with dividends and splits over a range (--actions: only action dates)
  company KIND SYMBOL...       profile | shares | news | filings
  financials KIND SYMBOL...    income | balance | cashflow | valuation
  analysts KIND SYMBOL...      targets | recommendations | upgrades | eps-estimate | revenue-estimate | eps-history | revisions | trend | growth
  holders KIND SYMBOL...       major | institutional | funds | insider-purchases | insider-transactions | insider-roster
  fund KIND SYMBOL...          overview | description | holdings | asset-classes | sectors | equity | operations
  options KIND SYMBOL...       expirations | chain
  screen KIND                  fields | values | presets | run
  market KIND                  summary | sector | industry
  calendar KIND                earnings | economic | ipo | splits
  filing URL...                SEC filing document → text file to read + its map      (PR ②)
options: --max-chars N (default 8000) · --ttl-days N (default 14; 0 keeps everything)
exit codes: 0 ok · 2 invalid · 4 local_io · 5 rate_limited · 6 upstream · 7 empty/unsupported · 8 partial
```

### `<command> --help` (≤ 4,000자, 절 순서 고정)

1. usage 한 줄과 목적 한 줄.
2. kinds: 종류마다 한 줄(무엇을 답하나).
3. arguments: 이 명령이 받는 인자만. 닫힌 선택지와 기본값, 어느 종류에 적용되는지 표시.
   - 예: `history`의 `--period`·`--start`·`--end`(end는 배타)·`--interval`·`--adjust {none,auto,back}`·`--repair`·`--prepost`·`--actions`.
   - 예: `screen run`의 인자.
     - `--query`(문법 5줄). 값의 단위는 `screen fields`가 필드마다 보여주는 `input_unit`이고, 비율 성격 필드는 비율로 쓴다. 측정되지 않은 비율 필드는 거절된다.
     - `--source-units`(쿼리를 Yahoo 단위 그대로 보냄), `--preset`(입력 스케일로 보이는 쿼리), `--sort`, `--limit ≤ 250`, `--offset`.
4. receipt: 공용 문장(한 곳에서 생성, 약 10줄)과 이 명령의 `file.format`.
5. exit codes: 공용 표.
6. `filing`만 추가로: the file / the map / identity / formats 절(공시 C3–C7).

### 영수증 예

```
holders institutional AAPL MSFT
{"status":"ok","command":"holders institutional",
 "receipt_path":".../data/results/20261006T1201-3fa6/receipt.json",
 "file":{"path":".../data/results/20261006T1201-3fa6/result.csv","format":"csv","rows":20,"columns":7},
 "units":{"pctHeld":"ratio","pctChange":"ratio","Shares":"shares","Value":"money:quote","Date Reported":"date"},
 "warnings":["Value prices the reported shares at the current quote, not at Date Reported."],
 "notes":["Date Reported is the quarter end the position is reported as of."],
 "results":[{"target":"AAPL","status":"ok","rows":10,"observed_at":"2026-10-06T03:01:12Z","currency":"USD",
             "coverage":{"statement":"the largest institutional holders Yahoo lists, not every holder","received":10},
             "data":[{"Date Reported":"2026-06-30","Holder":"Vanguard Group Inc","pctHeld":0.0951,…}, …]},
            {"target":"MSFT", …}],
 "trimmed":false,"projected":false}
```

## 동작 명세

각 항목은 손으로 쓴 리터럴 기대값의 테스트를 먼저 red로 만든다. 입구는 단계 첫머리에 빈 구현으로 정의한다. 그래서 red는 import 실패가 아니라 기대값 불일치여야 한다. 기대값은 원천 응답·원문을 읽어 쓰고, CLI 출력에서 베끼지 않는다.

### Yahoo (PR ①)

- **Y1 help**(C21):
  - 루트와 모든 명령 help가 크기 상한 안이다.
  - 모든 종류와 인자가 자기 명령 help에만, 정확히 한 번 나온다. 인자마다 적용되는 종류가 표시된다.
  - 자기완결성: 각 명령 help가 영수증의 키, 그 명령의 실패 코드, 종료 코드를 담는다. 입력에 단위가 있는 인자(`screen run --query`, 날짜, `--max-chars`)는 그 단위를 말한다.
  - 출력 필드의 단위 표가 help에 없다(출력 단위는 결과에).
  - `cli.py`가 선언한 종류 목록이 `invest.load.kinds()`와 같다.
  - 네트워크 0, `data/`가 생기지 않는다.
- **Y2 단위**(C23, C12-1·2·3): C23 변환 표의 모든 항목, 혼합 표의 긴 형식, `rank`·`unverified`, 통화 역할 연결, 스크린 번역·미측정 거절·`--source-units`·presets 입력 스케일·`sent_query`.
- **Y3 시점**(C25): 같은 세션 메타데이터와 마지막 거래 시각을 두고 **관측 시각만** 바꿔 다음을 만든다.
  - 일봉: 장중 → `provisional`, 장후 → `final`.
  - 장후인데 마지막 거래가 장 종료 전인 종목 → `final`(관측 시각 기준).
  - 이전 세션 봉, 휴장일, 시간대 경계(KST 관측 대 뉴욕 세션).
  - 주봉·월봉의 진행 중 기간, 인트라데이의 진행 중 봉.
  - 메타데이터 없음 → `unknown`.
  - quote: `market_state`와 각 원천 시각 필드가 따로 나온다.
- **Y4 범위·조건**(C26):
  - 데이터셋별 coverage 문장, `requested`/`received`와 shortfall `warnings`, `next_offset`·`total`.
  - 날짜·offset·limit·정렬의 `conditions`.
  - 스크린: 기록된 응답으로 3값 판정(AND, OR, 중첩), 대응 없는 필드 → `unverified`, 빈 결과는 확인 아님.
- **Y5 실패**(C24):
  - 상태 표의 모든 칸.
  - 코드별 기록 HTTP 응답을 실제 라이브러리 경로에 통과시켜 검사한다(getter를 대체하지 않는다).
    - `not_found`: 단계 3에서 정한 존재 부정 신호.
    - `no_data`: 정상 심볼의 상장 전 기간, "possibly delisted".
    - `not_applicable`: EQUITY + `KeyError 'topHoldings'`.
    - `quoteType` 불명 → `no_data`.
    - 인트라데이 span·reach(fix에 허용 일수).
  - metadata 429: 본문은 보존하고 다음 대상은 `not_attempted`. 그 뒤 저장 실패가 나도 rate-limit 상태 유지.
  - 한 대상 실패가 다른 대상을 지우지 않음(옛 `test_prices` 이식).
  - 대상별 마감: 지연 응답, 예외를 삼키는 호출, metadata 단계에서 각각 마감이 작동하고 다음 대상과 파일 게시가 이어진다.
- **Y6 영수증과 파일**(C22):
  - 출력 키 순서. `receipt.json` 스키마(모든 열·단위·선언 상태·warnings·notes·`sent_query`·대상별 시각).
  - 인라인과 미리보기의 경계.
  - 축소 순서와 `trimmed`. `warnings`·대상·상태·`receipt_path`는 줄지 않는다. `--fields` → `projected: true`.
  - 최소 영수증 사전 검사 → exit 2, 네트워크 0. 반례: 네트워크 뒤 필수 부분이 상한을 넘으면 필수 부분을 출력하고 `over_budget: true`이며, `warnings` 코드는 하나도 빠지지 않는다.
  - 파일이 없는 세 경우(인자 오류, 모두 빈/실패, 저장 실패).
  - 결과마다 새 id, 덮어쓰기 없음, 게시 중 실패에 부분 파일 비노출.
  - 옛 `test_export` 불변식:
    - 열 이름 충돌 방지(`target`·`side`·index 이름과 원천 열).
    - 대상별 열 합집합, index·시간대·큰 정수·결측 보존.
    - 값 목록·매핑·중첩은 JSON.
    - 혼합 표: 같은 metric의 펀드 값과 `Category Average`, `Shares`와 `Trans`에 서로 다른 값을 넣은 픽스처로 `source_column`의 누락·혼합을 검사한다.
    - 파일은 전 정밀도이고 인라인만 7자리.
- **Y7 대량**(C27): 30종목 한 호출 → 30개 대상 상태, 기록된 원천 요청 수, 대상별 기간·행 수, 한 파일.
- **Y8 이식 의미**: 옛 `test_company`·`test_market`·`test_prices`·`test_vocabulary`가 고정한 의미를 새 출력 계약으로 다시 쓴다.
  - 결측 보존, 정수 보존, 축 이름, 조정 방식, 원천 순서와 최신 쪽.
  - 스크린 검증, 지역 대체 거절, 캘린더 범위·0 손실, 닫힌 선택지 = 라이브러리 값.

### 공시 (PR ②)

- **P1 `sec` 판독 이식**(F10):
  - `text`(공백·LAYOUT·셀 텍스트)를 맨 아래의 순수 함수로 두고, `decode`·`emphasis`·`grid`·`markup`이 그것을 쓰며, `document.parse`가 조합한다.
  - 실패 타입은 `sec/failures.py`에서 정의한다. 파이프 렌더링은 `filing/render`로 옮긴다. `markup`의 `toc` 판정은 지우고, 링크에 출처 블록·표·행·열을 남긴다.
  - 입구 계약은 `parse(Fetched(body, url, content_type)) -> Document`이다.
  - `test_parse.py`가 입구로 고정할 의미:
    - NBIS table-7: 19→10열 `[0,1,3,5,7,9,11,13,15,17]`, 행 15의 기간 재시작, 선불워런트 행.
    - span의 원문 폭과 접힌 폭, `rowspan=0` 행 그룹 끝, 겹친 span·범위 밖 span의 실패.
    - 이미지·자식 표만 있는 열의 생존, 중첩 표 분리와 부모 셀, `th`·`scope` 보존.
    - U+200B 레이아웃 셀은 빈 값으로, 혼합 문자열은 그대로. 인라인 XBRL 숨김은 제외.
    - **원문의 모든 문자가 정확히 한 번**(옛 `test_markup.py:89`, nbis·mrvl·apple).
    - 강조 신호, 반복 페이지 머리의 모든 발생 위치, 표 안 앵커·링크의 셀 좌표.
- **P2 목차**(C6): 문서별 선택 묶음과 항목(제목·목적지 텍스트·줄)을 단계 8에서 원문을 읽어 적는다. 합성 반례: 순서 섞인 참조 표, 동률 두 묶음, 목적지 2개, 두 표로 나뉜 목차.
- **P3 렌더**(F3): 다음 불변식을 고정한다.
  - 모든 `[→Ln]`이 목적지 줄을 가리킨다. 표 셀 안 링크는 그 행 줄에 붙는다.
  - 표 행 줄 수가 `original_rows`와 같다.
  - `**…**`가 정의(글자의 4/5 이상이 굵은 표 밖 문단)와 정확히 일치한다.
  - 표 안 제목 행이 set-apart에 오른다. 같은 제목의 모든 발생 위치가 `map.json`에 남는다. `th:` 줄이 있다.
  - 이미지·링크 수와 표본은 원문을 lxml로 직접 센 독립 목록과 대조한다.
- **P4 저장·식별**(F2):
  - 같은 조건이면 재사용한다.
  - 같은 바이트라도 source가 다르면 각자의 `SOURCE`·URL을 쓴다.
  - 바이트나 버전이 바뀌면 새 결과다.
  - 동시 요청이나 실패에서도 완성된 결과만 보인다.
  - ttl을 지킨다.
- **P5 받기**(F6):
  - 매핑. S3 엑셀 → `unsupported`. 다른 호스트 → 거절(네트워크 0).
  - 3xx → `upstream`.
  - 404 → `not_found`. 403·429 → `upstream`(재시도 없음).
  - 연결 오류·5xx → 한 번 재시도한다. `--timeout`은 재시도를 포함한 마감이다.
- **P6 형식**(C5): `unsupported` 감지, `empty_document`, `encoding_loss`.
- **P7 출력**(C7·C24): receipt 사전 검사, 축소 순서, 상태·종료 코드 표의 모든 칸.
- **P8 상태 위치**: 다른 cwd에서도 `<skill>/data/filings`에만 쓴다.

## 테스트 설계

- **seam**:
  - 공개 CLI는 하위 프로세스로 돌린다(`tests/invest/conftest.py`). HTTP는 이식한 `fixtures/sitecustomize.py`가 기록 응답으로 대체하고, 기록에 없는 네트워크는 exit 97이다.
  - 공시 파싱·렌더 의미는 프로세스 안에서 **입구로만** 검사한다(`from invest.sec import parse, Fetched`, `from invest.filing import render`).
  - `__init__`는 함수·타입만 내보내고 모듈은 내보내지 않는다. 구조 검사가 내부 import·patch를 잡는다.
- **환경**:
  - `uv export --script cli.py`로 만든 요구사항과 pytest로 돌린다(현 yfinance CI 잡과 같은 방식).
  - live 테스트는 마커로 분리한다. 네트워크 의존은 함수 안에 둔다.
- **이식 원칙**:
  - 옛 테스트는 의미를 옮기고 기대값은 새 계약으로 다시 쓴다.
  - 옛 기대값을 출력 문자열 그대로 복사하지 않는다(형식이 바뀌었으므로).
  - 옛 `test_live`의 프로브(인트라데이 한계, 역수 배수, 스크린 스케일, 지수 52주 변화)는 정규화 drift 검사로 남긴다.
- **구조 검사**: 검사기 실패 픽스처는 그대로 쓴다. invest 등록은 PR ①에 하고, PR ②에서 단위를 추가한다.

## 작업 단계

단계는 곧 커밋이다. 테스트를 쓰는 단계는 `coding` 스킬을 연 상태에서 red → green으로 간다. 커밋·PR 제목은 `<타입>: <한국어 제목>`, PR 본문은 `## 무엇을 바꿨나/왜/영향/검증`, 머지는 `gh pr merge --squash`.

### PR ① `refactor/invest-yahoo-cli` — `refactor: yfinance를 invest로 바꾸고 Yahoo CLI를 다시 설계한다`

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | 계획 파일 `mv`, 스크래치 산출물을 `.tmp/invest-plan/`로 복사, `main`에서 브랜치, 트래커 | 브랜치·트래커 존재, 계획 파일 정식 이름, `.tmp/invest-plan/`에 L SKILL.md·filing.py v2·실행기·판정 요약 |
| 1 | **은행 개편**(C13): `git mv`로 `tests/invest/model-scenarios.json`. Yahoo 17(expect를 결과 기준으로), 큰 결과 9(독립 계산 기대값과 계산 스크립트), 조용한 실패 3·희귀 단위 3(실측으로 대상 고르고 전제 기록), 일관성 묶음 표시, Yahoo 홀드아웃 3(커밋만). 필드 `kind`·`heldout`·`premise`·`repeat` | expect에 CLI 절차 문구 0, 수치 범위는 "보조" 표시, 기대값·전제·홀드아웃 커밋 |
| 2 | **이름 변경과 이식 골격**: `git mv`로 `yfinance` → `invest`, `yahoo/` → `invest/yahoo/`, `scenarios/yfinance` → `scenarios/invest`. 테스트 seam·shapes 이식. 삭제 대상 삭제. 입구(`invest.yahoo`, `invest.load.run`·`kinds`, `invest.results`, `invest.receipts`) 빈 구현. 구조 검사가 요구하는 최소 표면을 이 단계에 둔다: PEP 723 머리와 빈 루트 help만 있는 `cli.py`, 호출 줄만 있는 SKILL.md(frontmatter + `CALL`), `scenarios/invest/` 폴더. 구조 검사 등록 | 구조 검사 green(새 등록), 이식 테스트 수집 성공(기대값 불일치로 red) |
| 3 | **`yahoo/` 새 계약**: `units.py`(어휘·변환·통화 역할·선언 상태)·`timing.py`·`refusals` 확장(증거 기준)·`screen`(필드 카탈로그의 입력/전송 단위·상태, 쿼리→반환 필드 대응표, 번역, 3값 조건 판정, presets 입력 스케일)·데이터셋 선언 개편(warnings·notes·coverage). `measure_screen_scales.py`로 스크린 스케일과 필드 대응을 실측 → 표·provenance. ADR EPS·추정치의 통화 역할 확인. Yahoo 응답 기록 → `fixtures/yahoo/`. **Y2·Y3·Y4·Y5·Y8** + C12 | 해당 테스트 green. 변환 테스트를 일부러 틀린 스케일·통화 역할로 한 번씩 red 확인(기록). 숫자 열·행의 미선언 0, 선언마다 `verified|declared` 상태 기록 |
| 4 | **`results`·`receipts`·`load`**: 저장·영수증·축소·대상 순회·대량. **Y6·Y7** | 테스트 green, `yfinance`·`pandas` import가 `yahoo/` 밖에 없음(이식한 경계 테스트) |
| 5 | **`cli.py`**: PEP 723, 루트 지도·명령 help(공용 문장은 한 곳에서 생성), 인자 검증·디스패치·종료 코드. **Y1** + `test_cli.py`·`test_portability.py` | 스위트 green, help 크기 상한 통과, 모든 help exit 0·네트워크 0·`data/` 미생성 |
| 6 | **SKILL.md**(PR ① 범위) + `scenarios/invest/run.py` 개편 + `judge.md`·`judge-schema.json` + CI·`pyproject.toml`·`.gitignore`·README·CONTRIBUTING·docs/usage.md·finviz description. 실행기 개편 내용: 조건 invest·L(L은 CLI 데우기 대신 yfinance 1.7.0 환경을 데움), `--tools`, `INVEST_DATA`, 요약 지표(Bash 호출 수와 그 안의 `cli.py` 실행 수를 따로, help 글자, 영수증 글자, 결과 파일을 연 Read·Python과 그 출력 글자, 명령 집합, 데이터 시각, 전제 증거) | `git grep -n "skills/yfinance\|tests/yfinance\|scenarios/yfinance\|yfinance_skill" -- ':!.claude/plans'` → 0, SKILL.md에 단위 표·측정 경위·모델 이름 0, CI 전 잡 green, 실행기가 기록 런 하나로 요약 지표를 모두 냄 |
| 7 | **검증과 리뷰**: (a) 조정 런 → 설정·`judge.md` 고정 커밋 → 평가 런(C13: L 짝 2쌍 이상·정규장 증거, 큰 결과·대량·조용한 실패·희귀 단위·일관성·효율) → codex 채점 → 홀드아웃 (b) codex 코드 리뷰(단위 규칙·help와 동작 일치·Y1–Y8) + SKILL.md 네 성질 검토 (c) `claude -p "/skill-doctor"`(finviz 경계) (d) `claude plugin validate --strict .claude/skills` (e) allowed-tools 실제 호출 확인(임시 프로젝트, `--setting-sources project --permission-mode default`, `permission_denials` 0) (f) **성진 SKILL.md 전문 승인** → PR → 머지 | (a) C13 합격선 전부(못 미치면 증거와 함께 성진에게 물음) (b) blocking·major 0 (c) 충돌 0 (d) exit 0 (e) 거부 0 (f) 전문 승인(부분·침묵 아님) |

### PR ② `feat/invest-filings` — `feat: invest에 공시 읽기 파일과 지도를 더한다`

| # | 단계 | 완료 판정 |
|---|---|---|
| 8 | **공시 시나리오·홀드아웃·기대값**: 은행에 공시 7 + 경계 2 + 공시 홀드아웃 2(실행 안 함). 픽스처를 `tests/sec/fixtures`에서 **복사**. P2 목차 기대값과 P3 독립 기대 목록을 원문에서 lxml로 직접 적음 | 은행·픽스처·provenance(경로·해시 검사) 커밋, 기대값 상수 커밋 |
| 9 | 입구 빈 구현 → **P1** `sec` 판독 이식, **P5·P6** | 이식 테스트 green(기대값 불일치로 red였음), `lxml`·`bs4`·`requests` import 경계 테스트, `sec` 안 순환 없음 |
| 10 | **P2·P3** `filing/contents`·`render`(합성 반례 포함), **P4** `documents` | 불변식·반례·식별 테스트 green, v2 결함 둘(머리줄 뒤 `[→L]` 어긋남, 표 안 앵커가 표 시작으로 감)을 재현한 테스트가 수정 전 red였음 |
| 11 | `cli.py`에 `filing`(help 6절)·**P7·P8**, `company filings`의 notes(C8), SKILL.md 공시 절·description, 구조 검사에 `sec`·`filing`·`documents` | 스위트 green, `filing --help` ≤ 상한(공시 절 포함 상한은 단계 11에서 정해 테스트로 고정), 구조 검사 green |
| 12 | **검증과 리뷰**: 공시 7·경계 2 실행·채점, C20 제거 시험, 홀드아웃 5 첫 실행, Yahoo 17 회귀 1회, codex 코드 리뷰(P1–P8) + SKILL.md 검토, skill-doctor, validate, **성진 SKILL.md 전문 승인** → PR → 머지 | 공시 7·경계 2 주장별 원본 대조 합격, C20 판정 기록, 홀드아웃 C13 기준, Yahoo 회귀에 새 의미 오류 0, 리뷰 blocking·major 0, 전문 승인 |

### PR ③ `chore/retire-sec` — `chore: sec 스킬을 은퇴시킨다` (PR ② 머지 직후)

| # | 단계 | 완료 판정 |
|---|---|---|
| 13 | `.claude/skills/sec/` → `.tmp/sec-skill/`, `tests/sec/` → `.tmp/sec-tests/`(git에서는 삭제), CI sec 잡·offline 잡 `--ignore=tests/sec`, `.gitignore` sec 줄, README·CONTRIBUTING·SECURITY·docs/usage.md의 sec 절 | `git grep -n "skills/sec\|tests/sec\|EDGAR_IDENTITY" -- ':!.claude/plans' ':!tests/invest/fixtures'` → 0, CI 전 잡 green, invest 스위트가 `.tmp`·sec 없이 green |
| 14 | 이 파일 끝 `# 구현 기록`(계획과 달라진 곳과 이유, 시나리오 전후 표, codex 의견의 수용·기각, 원리 충돌 해소의 실제 모습, 남은 한계, 기본값 교정 문장의 기준 모델, 옛 `yahoo/` 측정 이력, `grep -rn "성진:"` 장부) → PR → 머지 | 기록 커밋, 머지 |

## 검증

```bash
# invest 스위트 (cli.py 의존성 + pytest), 현 yfinance CI 잡과 같은 방식
bash -c 'set -euo pipefail; mkdir -p .tmp; uv export --quiet --script .claude/skills/invest/scripts/cli.py --no-hashes -o .tmp/invest-req.txt; uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/invest-req.txt --with pytest==8.4.2 python -m pytest tests/invest tests/test_skill_layout.py -q'
# live (네트워크)
bash -c 'set -euo pipefail; uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/invest-req.txt --with pytest==8.4.2 python -m pytest tests/invest -m live -q'
# offline 잡 · ruff · validate
python3 -m pytest tests/ --ignore=tests/sec --ignore=tests/finviz --ignore=tests/invest -q
uvx ruff check --config pyproject.toml .claude/skills/invest/scripts tests/invest scenarios/invest tests/test_skill_layout.py
claude plugin validate --strict .claude/skills
# help 크기 (Y1이 테스트로 고정, 수동 확인용)
for c in "" search quote history company financials analysts holders fund options screen market calendar; do uv run .claude/skills/invest/scripts/cli.py $c --help | wc -c; done
# 모델 시나리오 (레포 밖 사본으로만; Bash를 되살리므로 격리 아님)
python3 scenarios/invest/run.py --phase tune --cond invest --tools Bash,Read,Write --scenario <조정용 id…>            # 조정 런
python3 scenarios/invest/run.py --phase eval --pairs 2 --cond invest,L --tools Bash,Read,Write --scenario <Yahoo 17 id…>   # 짝 비교(순서 교대, 한 쌍은 정규장)
python3 scenarios/invest/run.py --phase eval --cond invest --tools Bash,Read,Write --scenario <큰 결과·조용한 실패·희귀 단위 id…>
python3 scenarios/invest/run.py --phase eval --cond invest,L --tools Bash,Read,Write --scenario <일관성 5 id…> --repeat 3
python3 scenarios/invest/run.py --phase holdout --cond invest --scenario <홀드아웃 id…>
python3 scenarios/invest/run.py --phase eval --cond invest --scenario <공시 7 + 경계 2 id…>        # PR ②
```

- 실행기:
  - 스킬을 공백 든 임시 경로로 복사하고(`data` 제외), `${CLAUDE_SKILL_DIR}`를 치환한다.
  - L 조건은 `.tmp/invest-plan/proto/skillL/SKILL.md`를 쓰고, `cli.py` 데우기 대신 같은 yfinance 1.7.0 환경을 미리 데운다.
  - `--phase eval`은 설정·`judge.md`의 커밋 해시를 결과에 기록하고, 조정 이후 바뀌었으면 거절한다.
  - 정규장 런은 실행 직전 `get_history_metadata()`의 세션·휴장 증거를 저장하고, 세션 밖이면 그 쌍을 정규장 쌍으로 세지 않는다.
  - 런마다 `INVEST_DATA`를 주고 cwd를 런 디렉터리로 둔다.
  - 실행: `claude -p --safe-mode --restricted --permission-mode acceptEdits --tools <…> --allowedTools <…> --model claude-opus-5-5 --output-format stream-json --verbose`.
  - 이 경로는 프롬프트로 SKILL.md를 읽히므로 frontmatter 권한과 자동 선택은 검증하지 않는다. 그것은 단계 7(e)와 skill-doctor가 맡는다.
- 판정 순서:
  1. 실행 가능성: 권한 거부·환경 실패는 외부 장애가 확인된 경우만 제외한다.
  2. 전제: 장중 여부, 자료 부족, 파일로 감 여부.
  3. 의미: codex 채점(`judge.md`).
- 결과는 `.tmp/invest-scenarios/<날짜>/`(커밋 안 함)에 두고, 요약은 구현 기록에 둔다.

## 계약이 서로 물린 곳 (하나만 고치면 깨진다)

- **고정 버전**: `cli.py` PEP 723(yfinance 1.7.0, `exclude-newer`) ↔ 기록 응답 provenance ↔ 스크린 스케일 표 provenance ↔ 실행기의 L 조건 env ↔ CI 요구사항 export.
- **단위**: `yahoo/units.py` 어휘·변환·통화 역할 ↔ 데이터셋 단위 선언(상태 포함) ↔ 영수증 `units`·`warnings` ↔ SKILL.md 판단 문단(단위 표 없음).
- **스크린 입력**: `screen.py` 필드 카탈로그(입력/전송 단위·상태)·대응표 ↔ `screen --help`·`screen fields` 출력 ↔ presets 표시 스케일 ↔ `sent_query` ↔ `measure_screen_scales.py` provenance ↔ `test_units.py`.
- **영수증**: `receipts.py` ↔ `load/receipt.py`·`filing` ↔ 명령 help의 receipt 공용 문장 ↔ `test_cli.py`·Y6·P7 ↔ 실행기 요약(전제 "파일로 감").
- **상태·종료 코드**: C24 표 ↔ 루트·명령 help ↔ `cli.py` ↔ `test_cli.py`.
- **시점·범위**: `timing.py`·데이터셋 coverage ↔ 영수증 ↔ SKILL.md "Turning a result into an answer" ↔ 은행 expect.
- **읽기 파일 형식**: `filing/render` ↔ `filing --help` ↔ `test_render.py` ↔ SKILL.md 공시 절.
- **식별**: 공시 키(C3)·결과 id(C22) ↔ `documents`·`results` 경로 ↔ 인용 문장.
- **구조**: `SKILLS['invest']`·`UNITS['invest']`·`INVOCATION` ↔ 패키지 자식 ↔ CI invest 잡 ↔ `pyproject.toml` pythonpath.
- **은행**: `model-scenarios.json` 필드 ↔ `scenarios/invest/run.py`·`judge.md`.

## 하지 않는 것

- EDGAR 직접 접근(SEC 신원·전체 이력·전문 검색·색인·Form 4·XML·여러 문서 SGML)과 Yahoo가 나열하지 않는 공시(결정 4 — 후속 과제).
- 컨퍼런스콜 녹취록 안내(결정 7).
- `references/`(결정 13), sec 리더(outline/find/read/table·cursor·`schema`) 이식(결정 6).
- 옛 CLI의 `read ID`·`--out`·`--from`·`--list-fields`·`--filter`(카탈로그 밖)·예산 축소와 그 복구 안내, 재무제표의 로컬 `--periods`(결정 20). 파일과 `receipt.json`이 그 일을 대신하고, 장치가 지키던 의미는 C28 표대로 남긴다.
- 스크린 조건 확인을 위한 자동 추가 조회(C26).
- 분석 명령(상관·수익률 계산 등)과 분석용 Python 사전 승인(C10).
- yfinance 버전 업그레이드(C9), 라이브러리 캐시 이동(결정 17), 다른 스킬의 이행, twitter `tests/twitter/model/` 이동.
- 공시 이미지 내려받기·OCR, PDF·XLSX 변환(C5).
