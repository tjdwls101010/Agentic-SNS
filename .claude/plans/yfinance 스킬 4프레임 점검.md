# yfinance 스킬 4프레임 점검과 재작성 계획

> **이 파일은 승인 직후 `.claude/plans/yfinance 스킬 4프레임 점검.md`로 이름을 바꾼다** (성진 결정). `finviz 스킬 4프레임 점검.md`·`sec 스킬 4프레임 점검.md`와 같은 계열이고, 기존 `yfinance 스킬 구현 계획.md`(최초 구축)와 역할이 구별된다.

## Context

`.claude/skills/yfinance`는 클로드가 Yahoo Finance를 사람처럼 능숙하게 다루도록 만든 스킬이다. 목적 지향 11그룹 45리프, `schema` 발견, 무손실 인코딩, 타깃별 결과 봉투 — 골격은 옳고 45리프 중 38개가 기본 옵션에서 정상 동작한다.

그러나 전수 실측 결과 **계약과 회복 경로가 무너져 있고, 일부 경로는 클로드를 조용히 틀린 답으로 안내한다.** 같은 저자가 더 나중에 재작성한 `finviz`(#15)가 이미 해결한 문제가 그대로 남아 있다. finviz 커밋 본문의 판정 기준이 그대로 적용된다:

> 기본 옵션으로 호출한 42리프 중 12개가 too_large였다. 첫 호출이 실패하면 "모델이 범위를 고른다"는 계약 자체가 성립하지 않는다 — 무엇을 고를 수 있는지 알려면 첫 호출이 성공해야 한다.

**의도한 결과**: 클로드가 이 CLI로 막히지 않고, 헛돌지 않고, 한 번 낸 비용을 버리지 않고, **조용히 틀리지 않는다.** 모든 리프의 첫 호출이 성공하고, 잘라낸 사실은 항상 말해지며, 안내된 회복은 실제로 회복시킨다.

**이 스킬의 초점은 미국 주식 분석이다**(성진 결정). 리프 개수를 줄이는 것이 목표는 아니지만, 남기는 리프는 전부 검증된 계약(기본창·함정·테스트)을 갖는다. 그 비용을 치를 값어치가 없는 리프는 남기지 않는다 — **검증이 덜 된 리프는 없는 리프보다 나쁘다.** 클로드가 그걸 쓰고 믿기 때문이다.

## 점검 결과 요약

| 등급 | 항목 | 성격 |
|---|---|---|
| **B (조용히 틀린 답)** | B1 시계열 한도가 가장 오래된 조각을 남긴다 / B2 재무제표 통화가 결과 어디에도 없다 / **B3 달력 `--end`가 선언과 반대라 "그날" 질의가 0행** / **G1 존재하지 않는 지역이 미국 데이터로 대체** / **G2 같은 이름의 값이 100배 다름** | 최우선. 실패가 아니라 **성공으로 위장한 오답** |
| **A (인터페이스가 거짓)** | A1 회복 안내가 실행 불가능 / A2 회복 안내가 B1으로 인도 / A3 요청을 관측처럼 되비춤 / A4 선언한 필드명이 출력에 없음 / **A5 원천이 답을 줬는데 `fix`가 엉뚱한 소리** | `interface over document` 정면 위반 |
| **C (첫 호출 실패)** | C1 기본 옵션 4리프 실패 / C2 대범위 요청에 도달 경로 없음 / C3 지불한 요청을 버림 | 계약 성립 자체를 막음 |
| **D (밀도)** | D1 같은 데이터셋에 두 이름 / D2 불변 문장이 매 결과 반복 | `dense information` |
| **E (검증 공백)** | E1 테스트가 문장의 모양만 검사 / E2 라이브 스위트 없음 | A1이 통과한 원인 |
| **S (잉여)** | S1~S4 | `잉여 점검` 절 참조 |

**성진 결정: 계약 재설계 + 분류 정리.** 그룹 분류는 보존하고(45개 중 38개 정상 동작 — 분류를 버리면 검증된 어댑터 지식을 재발견해야 한다), 계약·회복·해석 층을 다시 쓴다. 사실상 `yfinance_cli.py`·`output.py` 재작성 + 신규 모듈 3개 + 어댑터 개수.

## 실측 사실 장부 (2026-09-19, 기본 옵션, AAPL·SPY·SAP·TM·005930.KS)

### 45리프 전수 호출

| 결과 | 리프 | 수치 |
|---|---|---|
| **too_large** | `company news` | 23,830자 (예산 20,000) |
| **too_large** | `company filings` | 44,435자 |
| **too_large** | `analysts upgrades` | 82,681자 |
| **too_large** | `screen run --preset day_gainers` | 62,216자 |
| upstream 오류 | `company sustainability` | — |
| empty (정당) | `prices actions`(1mo), `fund bond`(SPY) | — |
| ok | 나머지 38개 | 391 ~ 10,367자 |

### 인트라데이 간격의 기간 제한 (schema `limits` 후보)

`--interval`의 현행 도움말은 *"intraday intervals cover only recent history"* 뿐이고 실제 값이 없다. 전부 Yahoo가 거절하며 알려주는 값이다.

| 간격 | 제한 | 비고 |
|---|---|---|
| `1m` | **8일** | — |
| `2m`·`5m`·`15m`·`30m`·`90m` | **60일** | `30m` 요청의 오류 메시지는 **"15m data not available"**이라고 답한다 — 요청과 다른 간격을 이름 붙인다 |
| `1h`·`60m` | 기간 제한 없음 | 1년 성공하나 84,246자로 예산 초과 |

이 숫자들은 클로드가 재유도할 수 없고, 모르면 정당한 요청이 upstream 오류로 튕긴다. `limits`가 소유해야 할 전형이다.

### 조용히 틀린 답 (B1)

```
prices history AAPL --period 5y --fields Close --limit 5
→ status: ok, 경고 없음
→ 2021-09-20, 2021-09-21, 2021-09-22, 2021-09-23, 2021-09-24

prices actions AAPL --period max --limit 3
→ 1987-05-11, 1987-06-16, 1987-08-10
```
`context`는 `returned_before_selection: 1255`를 싣지만 **어느 쪽 1250개를 버렸는지 말하지 않는다.**

### 회복이 함정으로 인도한다 (A2)

```
prices history AAPL --period 5y --fields Close   → too_large (61,425자)
FIX: "Narrow --fields (...), --limit, --periods or --start/--end; ... --max-chars 61425."
                          ↑ 이 안내를 따르면 B1 발동
```

### 회복이 실행 불가능하다 (A1)

```
company news AAPL              → too_large (23,830자)
FIX: "Narrow --fields (discover with --list-fields --filter TEXT), ..."
company news AAPL --list-fields → ["id", "content"]      ← 2개뿐
company news AAPL --fields content → too_large           ← 여전히 실패
```
실제 페이로드는 `{id, content{18개 키}}` 2단 중첩이라 `--fields`가 원리적으로 닿지 못한다.

### 통화 (B2)

| 종목 | 호가 통화 | 재무제표 통화 |
|---|---|---|
| SAP | USD | **EUR** |
| TM (Toyota) | USD | **JPY** |
| 005930.KS | KRW | KRW |

`financials income TM`의 `context.currency`는 **`null`**이다. CLI가 정직하게 대체를 거부하지만, 그 결과 클로드는 재무제표 통화를 알 방법이 없다(별도로 `prices quote --fields financialCurrency`를 불러야 한다). USD 주가와 JPY 순이익으로 PER을 계산하면 약 150배 틀린다.

같은 표의 한 행에 스케일이 섞인다 — `TaxRateForCalcs=0.086389`(비율)과 `NormalizedEBITDA=96664037000000.0`(원화 금액)이 나란히 있다.

### 중복 (D1)

`prices quote AAPL`과 `company profile AAPL`의 필드 집합이 **바이트 단위로 동일**하다(185필드, 각 9,024/9,027자 — 3자 차이는 타임스탬프). `company.py:16-17`이 둘 다 `get_info()` 하나를 부른다.

### 정렬 방향은 리프마다 다르다 (B1 수정을 규정하는 실측)

**"앞자르기를 뒤자르기로 바꾼다"는 일괄 수정은 틀린다.** 방향이 리프마다 다르다.

| 리프 | 행 | 첫 행 → 끝 행 | 방향 |
|---|---|---|---|
| `prices history` (1y) | 251 | 2025-09-19 → 2026-09-18 | 오래된 것이 먼저 |
| `prices actions` (max) | 97 | 1987-05-11 → 2026-08-10 | 오래된 것이 먼저 |
| `analysts history` | 4 | 2025-09-30 → 2026-06-30 | 오래된 것이 먼저 |
| `company shares` | 65 | 2025-03-27 → 2026-08-05 | 오래된 것이 먼저 |
| **`analysts upgrades`** | 971 | 2026-09-18 → 2012-09-12 | **최신이 먼저** |
| **`calendar earnings SYMBOL`** | 30 | 2026-10-29 → 2019-07-30 | **최신이 먼저** |

`analysts upgrades`에서는 현행 `iloc[:limit]`가 **옳은 답**(최근 20건)을 준다. 방향을 뒤집는 일괄 수정은 이 리프를 망가뜨린다. 따라서 `leaves.recent`는 **리프마다 실측해서 선언**하고, 테스트가 각 선언을 현실에 고정한다.

**주의**: `holders insider-transactions`는 인덱스가 정수(0~80)라 인덱스로는 방향을 알 수 없다. 정수 인덱스 프레임은 **날짜 컬럼**으로 방향을 판정해야 하고, 날짜 컬럼이 없으면 원천이 준 순서를 그대로 두고 `coverage`가 어느 쪽을 잘랐는지 말한다.

### 무엇이 예산을 먹는가 — `company news` 10건 분해 (설계 입력)

| 필드 | 자 수 | 비중 |
|---|---|---|
| `thumbnail` (이미지 URL 묶음) | 7,107 | **34.3%** |
| `storyline` (관련기사 체인) | 3,715 | **18.0%** |
| `summary` | 1,949 | 9.4% |
| `canonicalUrl` | 1,520 | 7.3% |
| 나머지 13개 | 6,405 | 31.0% |
| **합계** | **20,696** | |

**절반 이상이 클로드가 쓰지 않는 것이다.** 제안 기본집합(`title`·`pubDate`·`provider`·`canonicalUrl`·`summary`)은 10건에 5,428자(26%)로 예산에 넉넉히 들어온다.

`screen run --preset day_gainers`(25행)는 메커니즘이 다르고 결론이 같다: **93개 필드**에 지배적인 것이 없이(최대 `longName` 3.1%) 행당 686자가 쌓인다. `messageBoardId`·`quoteSourceName`·`corporateActions`·`exchangeTimezoneName`은 스크리닝 결과에 순수한 노이즈다. 10필드 투영이면 12%로 떨어진다.

| | `company news` | `screen run` |
|---|---|---|
| 병목 | 소수의 거대 필드 (`thumbnail` 34%) | 93개 필드, 지배적인 것 없음 |
| 10필드 투영 | 26% | 12% |

**이 두 측정이 기본창의 정의를 바꾼다: 기본창은 행 수만이 아니라 필드 투영을 함께 자른다.** news는 3건으로 줄여도 썸네일이 따라오고, screen은 행을 줄여도 93필드가 그대로다. 그리고 `--fields`가 중첩에 닿지 못한 것(A1)이 왜 치명적이었는지도 여기서 설명된다 — news의 올바른 축소는 행이 아니라 필드인데 `--fields`가 그걸 표현할 수 없었다.

따라서 `leaves.py`의 기본창 선언은 **행 범위와 필드 투영을 함께** 갖고, `--fields`는 점 경로(`content.title`)로 중첩에 닿을 수 있어야 한다.

### C1 네 리프의 기본창 제안 (전부 실측 근거)

| 리프 | 초과량 | 병목 | 제안 기본창 |
|---|---|---|---|
| `company news` | 23,830 | `thumbnail` 34% + `storyline` 18% | 10건 × `{title, pubDate, provider, canonicalUrl, summary}` → 5,428자 |
| `company filings` | 44,435 | **`exhibits` 69.3%** (80건 중) | 20건 × `{date, type, title, edgarUrl}` — `exhibits`는 `--fields`로 옵트인 |
| `analysts upgrades` | 82,681 | **행 수 971** (2012~2026), 필드 7개뿐 | 최근 20행(이 리프는 최신이 먼저라 접두 자르기가 맞다) → 약 1.3KB |
| `screen run` | 62,216 | **필드 93개**, 행당 686자 | 25행 × 10필드 투영 → 12% |

네 리프의 병목이 서로 다르다 — 거대 필드 / 중첩 배열 / 행 수 / 필드 개수. **한 가지 처방으로 덮이지 않으므로 리프별 선언이 필요하다**는 것이 `leaves.py`의 존재 이유다.

### 조건 판정 가능성 (설계 입력)

| 인자 | 응답의 증거 | 판정 |
|---|---|---|
| `screen --offset/--limit` | `upstream: {start, count, total}` 에코 | **confirmed 가능** |
| `screen --sort` | 에코 없음. 반환값이 단조(16.39>15.39>13.75) | **데이터 성질로 확인 가능** |
| `calendar --start/--end` | 반환 행의 `Event Start Date`가 전부 범위 안 | **confirmed 가능** |
| `market sector --region` | US/JP 모두 같은 응답, `context.region`은 **입력을 되비칠 뿐** | **판정 불가 (A3)** |
| `calendar ipo` 경계 | 원천이 되비추지 않음 | **판정 불가** |

### 발견 비용 (잉여 판단의 근거)

`--help` 1,659자 / `schema`(전체 그룹) 3,730자 / `schema prices history` 3,160자. **45리프여도 발견 비용은 작다** — 리프 개수가 클로드의 선택을 희석한다는 가설은 실측이 지지하지 않는다.

## 잉여 점검 — 불필요한 것이 필요한 것을 희석하는가

희석은 **클로드의 주의**에서 일어나지 않는다(위 발견 비용 참조). 희석은 **검증 예산**에서 일어난다. 리프마다 선언·기본창·함정 발굴·테스트가 붙고, `market sector --region JP`의 함정을 파는 시간은 `financials`의 통화 함정을 파는 시간을 빼앗는다.

**성진 결정: 아래 5개만 제거(45→40).** 근거가 분명한 것만 자르고, 나머지 40개는 전부 완전한 처우를 받는다.

| # | 제거 | 근거 |
|---|---|---|
| S1 | `company sustainability` | 실측 upstream 오류. ESG는 미국 주식 분석의 주류가 아니다 |
| S2 | `search --dataset nav` | Yahoo 내비게이션 링크. 분석에 쓰일 경로가 없다 |
| S3 | `market status` | `prices quote`의 `marketState`가 같은 질문에 답한다. (제거 근거를 정정한다 — 처음에 쓴 "`--region`이 무시된다"는 **틀렸고**(G1 참조) 중복만이 근거다. 미국 집중이라는 초점에서 거래 상태는 quote가 이미 싣는다) |
| S4 | `fund bond`, `fund rating` | 채권형 펀드 전용. SPY에서 empty 확인 |

**유지하는 것과 이유**: `analysts` 10개·`holders` 6개는 미국 주식 분석의 핵심(추정치 수정·내부자 거래·기관 보유)이라 전부 남긴다. `fund` 나머지 7개는 섹터 익스포저·경쟁사 발견에 쓰인다. `calendar economic`은 FOMC·CPI가 미국 주식에 직접 작용하므로 남긴다. **명령 개수를 줄이는 것은 목표가 아니다.**

`market sector/industry`의 `--region`은 제거하지 않고 **닫힌 선택지로 통일**한다(`yfinance_cli.py:124`가 `market status`에 이미 쓰는 `yf.MarketRegion`). 무효한 값을 argparse가 거절하면 G1이 인터페이스 층에서 소멸한다 — 초기 판단("US 고정")은 잘못된 측정에 근거했고 G1에서 정정했다.

## 확정 결함

번호는 발견 순서이고 **배열은 심각도 순**이다(B3가 B2보다 앞에 오는 이유). 등급 B는 조용히 틀린 답, A는 인터페이스가 거짓을 말하는 것, C는 첫 호출 실패, D는 밀도, E는 검증 공백이다.

### B1. 시계열 한도가 가장 오래된 조각을 남긴다 — `Scripts/output.py:135`

```python
data = data.iloc[:limit] if isinstance(data, pd.DataFrame) else data[:limit]
```

시계열은 오래된 것이 먼저 실리므로 접두 자르기는 항상 가장 오래된 조각을 남긴다. `prices history --period 5y --limit 5`가 2021년을, `prices actions --period max --limit 3`이 1987년 배당을 `status: ok`로 돌려준다. 경고도 없다. finviz는 `leaf.recent`로 이미 해결했다("오래된 것부터 실리는 계열은 한도가 최신 쪽을 남긴다"). **실패는 시끄럽지만 이건 조용하다** — 이 계획의 최우선 항목이다.

### B3. 달력의 `--end`가 선언과 반대다 — `Scripts/market.py:150`, `Scripts/yfinance_cli.py:215-216`

```
calendar earnings --start 2026-10-01 --end 2026-10-01  →  0행    (그날 실제로 12건)
calendar earnings --start 2026-10-01 --end 2026-10-02  →  12행, 전부 10-01
calendar earnings --start 2026-10-01 --end 2026-10-03  →  17행, 10-01과 10-02만
```

`--end`는 **배타적**인데 `context`가 `end_boundary: "native_inclusive"`라고 선언한다. 더 나쁘게, `validate()`가 `start == end`를 명시적으로 허용하면서 오류 문구에 *"calendar start may equal inclusive end"*라고 적는다 — 그 조합은 **0행**을 낸다.

"10월 1일 실적 발표 뭐 있어?"에 클로드는 `--start 10-01 --end 10-01`을 쓰고 **"없습니다"**라고 답한다. `empty` 상태의 경고문("빈 반환이 데이터 없음을 증명하지 않는다")이 있지만, **클로드는 자기가 쓴 인자가 옳다고 믿을 근거를 인터페이스에서 받았으므로** 그 경고를 원천의 공백으로 읽는다. B1과 같은 등급이다.

**이 항목은 코덱스 레인 A의 후보에서 출발해 클로드가 재현했다** — 전수 스윕(기본 옵션)으로는 잡히지 않는 종류다.

### B2. 재무제표의 통화가 결과 어디에도 없다 — `Scripts/company.py:13-14`

```python
context.update(currency=None, ...)
warnings.append("Source statement currency is unconfirmed; ...")
```

대체를 거부하는 판단은 옳다. 그러나 **알 수 있는 값을 싣지 않는다**. `get_info()`의 `financialCurrency`가 TM에서 JPY, SAP에서 EUR을 정확히 준다. 클로드는 별도 호출로만 닿을 수 있고, 그 필요를 아는 경로가 없다. `currency: null`은 "확인 불가"로 읽히지만 실제로는 "이 리프가 조회하지 않았을 뿐"이다.

### A1. 회복 안내가 실행 불가능하다 — `Scripts/output.py:88`

```python
fix = f"Narrow --fields (discover with --list-fields --filter TEXT), --limit, --periods or --start/--end; ..."
```

리프와 무관하게 **한 문자열 템플릿**이 모든 회복을 만든다. `company news`는 페이로드가 2단 중첩이라 `--fields`로 줄일 수 없는데도 `--fields`를 권한다. finviz는 `leaf.narrow` 선언에서 회복 문장을 파생시켜 이 형태를 구조적으로 막는다. "Help text and failure messages must agree with the implementation"의 정면 위반이고, **finviz가 `f3ded99`에서 yfinance로부터 배웠다고 적은 그 결함이 정작 yfinance에 남아 있다.**

### A2. 회복 안내가 조용히 틀린 답으로 인도한다 — `Scripts/output.py:88` + `:135`

A1의 같은 문장이 `--limit`을 권하고, `prices history`에서 그 안내를 따르면 B1이 발동한다. 정당한 질문 → 시끄러운 실패 → **안내받은 회복 → 조용한 오답.** 두 결함이 사슬로 이어져 단독일 때보다 위험하다.

### A3. context가 요청을 관측처럼 되비춘다 — `Scripts/market.py:27,176`

```python
context.update(region=args.region, ...)
```

`context`는 "그 타깃에 실제로 적용된 조건"을 보고하기로 되어 있는데(`yfinance_cli.py:171`의 `default_context` 선언), 여기서는 **입력을 그대로 되비칠 뿐**이다. `--region NOTAREGION`이 미국 데이터를 받아도(G1) `context.region`은 `"NOTAREGION"`을 보고하므로, **CLI가 거짓 조건을 능동적으로 주장한다.** 클로드는 이걸 "지역이 적용됐다"는 증거로 읽는다. finviz의 원칙이 정확히 이것을 금지한다: *"HTTP 200 alone never confirms a condition."*

같은 결함이 `--region`의 계약 불일치와 겹친다: `yfinance_cli.py:124`는 닫힌 선택지를 주고 `:127`은 자유 문자열을 준다.

### A4. 선언한 필드명이 출력에 없다 — `Scripts/market.py:150`

`context.date_field = "startdatetime"`인데 실제 반환 컬럼은 `Event Start Date`다. 클로드가 `--fields startdatetime`을 쓰면 실패한다. 원천 API의 내부 이름과 표시 이름이 다른데 context가 전자를 선언한다.

### A5. 원천이 답을 줬는데 `fix`가 엉뚱한 소리를 한다 — `Scripts/yfinance_cli.py:283`

```
prices history AAPL --period 1y --interval 1m
message: "$AAPL: 1m data not available for startTime=… Only 8 days worth of 1m
          granularity data are allowed to be fetched per request."
fix:     "Retry later or verify the symbol/dataset; use --timeout SECONDS if the
          target timed out."
```

**원천이 정확한 처방(8일)을 메시지에 담아 줬는데 `fix`는 심볼을 의심하라고 한다.** `upstream` 코드 하나에 문자열 하나가 붙어 있어서(`:283`의 삼항 연산자) 모든 업스트림 실패가 같은 조언을 받는다. A1과 같은 병(리프·상황과 무관한 템플릿)이고 경로만 다르다.

**수정**: 업스트림 메시지가 해결 가능한 제약을 담고 있으면 그것을 `fix`로 승격한다. 리프의 `limits` 선언과 대조해 어떤 인자를 어떻게 바꿔야 하는지 이름 붙인다.

### C1. 기본 옵션 호출이 4리프에서 실패한다 — 측정치

`company news`(23,830), `company filings`, `analysts upgrades`, `screen run --preset`(62,216). 첫 호출이 실패하면 "무엇을 고를 수 있는지" 알 방법이 없다.

### C2. 대범위 요청에 도달 경로가 없다 — 실측 61,425자

`prices history --period 5y --fields Close`는 정당한 질문인데 항상 예산을 넘는다. `--limit`은 B1으로 이어지고, `--max-chars 61425`는 컨텍스트를 61KB 태운다. **전수에 안전하게 도달하는 경로가 존재하지 않는다.**

### C3. too_large가 지불한 요청을 버린다 — `Scripts/output.py:89-90`

오류 문서를 출력하고 종료할 뿐, 이미 받아온 데이터는 소멸한다. Yahoo 429가 실재하는 경로(`yfinance_cli.py:281`이 명시적으로 처리)이므로 재요청은 공짜가 아니다. finviz·sec는 둘 다 관측 저장소를 갖고 있다.

### D1. 같은 데이터셋에 두 이름 — `Scripts/company.py:16-17`

`prices quote`와 `company profile`이 `get_info()` 하나를 부르고 185필드를 그대로 낸다. harness-creator: *"Fold equivalent candidates rather than recording two names for one capability."* 덧붙여 "주가 얼마야"에 185필드를 주면 클로드가 가격 필드 8개 중에서 골라야 한다.

### D2. 불변 해석 문장이 매 결과 반복된다 — `Scripts/company.py:14,21,24,27`

`"Native values; currency is unconfirmed unless supplied in data."` 같은 문장이 리프·타깃·호출마다 재전송된다. 이건 그 리프의 **불변 계약**이지 이번 관측의 사실이 아니다. `schema`가 한 번 말하면 된다.

### E1. 테스트가 문장의 모양만 검사한다 — `tests/yfinance/test_prices.py:107-113`

```python
fix = doc["results"][0]["error"]["fix"]
assert fix.startswith("Narrow")
assert "cannot" not in fix
```

**안내를 실행하면 실제로 회복되는지는 검사하지 않는다.** 게다가 합성 라우트(`many_symbol_routes(30)`)가 평평한 페이로드를 만들어 `--fields`가 작동하는 세계를 가정한다. A1이 통과한 원인이 정확히 여기다. harness-creator: *"a verifier must not derive its expected answer from the output it is grading."* — 이 테스트는 한 걸음 더 나빠서, 출력의 **형식**만 보고 내용의 참을 묻지 않는다.

### E2. 라이브 계약 스위트가 없다

루트 `pyproject.toml`에 `live` 마커와 `-m 'not live'`가 이미 있고 finviz는 `tests/finviz/test_live.py`(157줄)를 갖는데 yfinance는 없다. 현실의 모양(중첩 깊이·행 수·필드 수)을 아무도 고정하지 않는다.

## 네 프레임이 이 재작성에서 결정하는 것

이 4프레임은 `SKILL.md`뿐 아니라 **`--help`·`schema`·오류 메시지에도 똑같이 적용된다**(성진 지시). 인터페이스의 모든 문장이 문서다.

- **principle over rail → "기본값은 한 화면, 전수는 옵트인. 그리고 함정은 나열하지 말고 계약으로 싣는다."** 출력 크기는 클로드가 고른 범위의 결과여야 하는데, "고른 범위"가 성립하려면 **고를 수 있는 것을 아는 첫 호출**이 성공해야 한다. 리프마다 기본창을 주고 잘라낸 사실은 `coverage`가 매번 말한다. 리프 설명은 "5년 종가를 얻으려면 X하라"가 아니라 계약이되, **재유도 불가능한 사실**(1분봉 8일 제한, `financialCurrency ≠ currency`)은 반드시 싣는다 — 일반 역량이 공급 못 하는 것만이 무게값을 한다. **그리고 그 사실을 산문 경고 목록으로 쌓지 않는다**: 단위·스케일·역수는 필드별 `units` 계약으로 실어서, 우리가 찾지 못한 필드도 자기 단위를 갖고 오게 한다. 경고 20개는 21번째에서 무력하다.
- **interface over document → "스키마의 모든 주장은 코드에서 파생되거나 테스트로 고정된다."** 손으로 쓴 문장은 도구가 바뀌면 조용히 거짓이 된다(A1이 그 사례). 회복 문장은 `leaves.narrow` 선언에서만 파생되고, 그 선언이 실제로 예산 안에 들어오게 하는지를 테스트가 고정한다. 리프별 함정은 그 리프의 `schema`가 소유하고 `SKILL.md`는 갖지 않는다. `references/`를 만들지 않는다.
- **for user not developer → "사용자는 작업 중인 클로드다. 오류 메시지와 `fix`도 인터페이스다."** "줄이라고 안내한 방법이 실제로 줄여줘야" 하고, 이건 테스트 가능한 명제다. 지불한 네트워크 비용을 버리지 않는다. 판정할 수 없는 인자(`--region`)를 선택지로 내놓지 않는다. **그리고 조용히 틀린 답을 낼 수 있는 경로를 남기지 않는다** — B1이 이 프레임의 가장 큰 위반이다.
- **dense information → "불변은 한 번, 관측은 매번."** 불변 계약은 `schema`가 소유하고 결과에는 실제 관측값만 싣는다(D2). argparse가 이미 보여주는 걸 스키마가 다시 쓰지 않는다. **밀도는 분량이 아니라 재유도 가능성이다** — 똑똑한 모델이 문서 없이도 아는 문장은 빼고, 모르는 문장은 짧아도 남긴다.

## 코덱스 레인 B(설계 비판) 반영 — `gpt-6-astra` medium, read-only

설계안을 깨라고 시킨 결과. **셋은 설계를 고쳤고, 하나는 제 사실 주장을 반증했다.**

### R1. 기본창과 예산 절단을 구분하지 않으면 질문이 바뀐다 (설계안 E 수정)

`--period 5y`로 120행을 받았을 때, 클로드는 그게 **이 리프의 기본창**인지 **요청한 5년이 예산에 잘린 것**인지 구분할 수 없다. 전자는 그걸로 충분할 수 있고, 후자는 반드시 나머지를 읽거나 답변에 한계를 달아야 한다.

**수정**: E를 유지하되 상태로 구분한다. **명시적 범위 요청이 예산 때문에 잘리면 `ok`가 아니라 `partial`(exit 8)이다.** `coverage`는 절단의 이유(`leaf_default` / `budget_truncated`)를 함께 싣는다. 리프 기본창으로 잘린 것은 `ok`로 남는다 — 그건 이 리프가 원래 한 화면을 주기로 한 계약이기 때문이다.

### R2. 범용 JSON Pointer가 표를 훼손한다 (설계안 A 수정)

yfinance는 표를 `{index, columns, data, index_names, column_names}`로 인코딩한다(`output.py:17`). `/data/data/5`를 가리키는 포인터는 **열 이름 없는 배열**을 준다 — 의미가 없다. finviz는 레코드 목록을 다루므로 이 문제가 없었다. **finviz 어휘를 그대로 베끼면 틀리는 지점이고, 앞서 "해석 필드를 놓을 자리가 없다"고 본 것과 같은 뿌리다.**

**수정**: `read`의 슬라이싱은 **표를 인식**한다. 행을 자르면 `columns`·`index_names`가 함께 간다. 포인터가 표 내부를 가리키면 거절하고 행 범위 인자를 안내한다.

### R3. 보관 경과시간과 시세 최신성은 별개다 (설계안 A·D 수정)

장 마감 후 조회하면 저장 경과시간이 1분이어도 **원천 가격은 몇 시간 전 것**이다. 경과시간만으로는 신선도를 판정할 수 없다.

**수정**: 결과는 세 시각을 구분해 싣는다 — 원천이 말하는 시각(`regularMarketTime` 등) / CLI 관측시각(`observed_at`) / 저장 경과시간(`read`에서만). `SKILL.md`의 "시점마다 역할이 다르다" 절이 이 셋을 다룬다.

### R4. 저장 범위가 불명확하다 (설계안 A 보완)

일부 자료는 공통 출력 단계 **이전에** 이미 잘린다(`company.py:15`의 `--periods` 슬라이스, `news`·`screen`의 `--limit` 업스트림 전달). 저장소는 **실제로 가진 것만** 기록해야 하고, 회복 문장이 애초에 받지 않은 자료를 약속하면 안 된다.

**수정**: 저장 시점을 어댑터 반환 직후로 고정하고, `coverage`가 "업스트림에 요청한 양"과 "받은 양"을 구분한다. `read`의 회복 문장은 저장된 범위 밖을 가리키지 않는다.

### R5. 회복 테스트는 성공이 아니라 의미 보존을 봐야 한다 (단계 8 수정)

`fix`를 실행해 `ok`가 나와도, 그게 **다른 질문에 답한 것**이면 회복이 아니다.

**수정**: 회복 테스트의 판정은 "같은 관측·종목·기간·조건을 되찾았는가"다. 저장된 id의 원본과 회복 결과를 대조한다.

### R6. `get_info()`는 단일 HTTP 응답이 아니다 — 제 주장 반증

단계 5에서 "업스트림 호출이 하나임을 `schema`가 밝힌다"고 썼는데 **사실이 아니다.** 설치된 라이브러리 확인 결과 `get_info()`는 여러 엔드포인트를 조립한다. quote/profile을 "동일 시점의 단일 원천 관측"으로 설명하면 부정확하다.

**수정**: 그 문장을 쓰지 않는다. 두 리프가 **같은 조립 결과를 공유한다**고만 말하고, 필드마다 시점이 다를 수 있음을 `interpretation`이 싣는다(현행 `company.py:18`의 `as_of` 문구가 이미 그 방향이다).

### R7. finviz·sec가 이미 푼 것 중 이 설계가 놓친 것 (전부 반영)

경로는 `.claude/skills/` 기준.

| # | 놓친 계약 | 선례 |
|---|---|---|
| R7-1 | **원천 완전성 ≠ 선택 범위 완독.** `coverage.exhaustive` 하나로는 "원천이 다 줬나"와 "내가 다 읽었나"를 구분 못 한다 | `sec/Scripts/reader.py:138-143,197-204` (`scope_complete`와 `extraction_complete`를 따로 반환) |
| R7-2 | **슬라이스가 해석 문맥을 데려가야 한다.** 행만 옳게 반환해도 문맥을 잃으면 해석이 틀린다 | `finviz/scripts/finviz.py:202-206`(slice_context), `sec/Scripts/reader.py:286-301`(표 caption·footnotes) |
| R7-3 | **회복 명령이 원 선택을 보존해야 한다.** 다종목 오류에서 첫 종목만 가리키면 비교 요청이 단일 종목 질문으로 바뀐다. 셸 인용도 보존 | `finviz/scripts/output.py:230-255` |
| R7-4 | **단일 항목이 예산을 넘을 때의 탈출로.** `--limit 1`에서도 막히면 회복이 무한루프가 된다 | `finviz/scripts/output.py:239-241`(raw 문자 창), `sec/Scripts/reader.py:167-194`(cell 내부 offset) |
| R7-5 | **원천 empty와 선택 후 empty를 구분하고 제한을 재생까지 전파.** `read`가 성공했다는 사실로 원 관측의 결함을 지우면 안 된다 | `finviz/scripts/output.py:174-186`, `sec/Scripts/reader.py:140-143` |
| R7-6 | **불변 ID와 continuation의 쿼리 결속.** 저장 바이트 무결성과 "이 커서가 같은 질의의 것인가" 검증. TTL만으로는 재생 안전성을 얻지 못한다 | `sec/Scripts/store.py:56-90` |
| R7-7 | **오류 봉투 자체도 예산 안에 들어야 한다.** 데이터가 아니라 오류 설명이 예산을 넘을 수 있다 | `finviz/scripts/output.py:273-293` |
| R7-8 | **CLI 성공과 모델의 올바른 해석을 따로 검증.** 라이브 CLI 통과만으로는 stale/live·partial/full 오독이 검증되지 않는다 | `tests/finviz/model-scenarios.json:28-40` |

R7-8이 특히 중요하다 — 제 단계 8(라이브 스위트)은 **CLI가 옳게 답하는지**만 보고 **클로드가 옳게 읽는지**는 보지 않는다. 모델 시나리오가 그 역할이며, finviz는 이미 시나리오를 파일로 갖고 있다. `tests/yfinance/model-scenarios.json`을 같은 형식으로 만든다.

### R8. 제 설계안이 4프레임을 위반하는 지점 (전부 수용)

- **rail을 만드는 곳**: 모든 자료에 **동일한 24시간 TTL**을 적용할 이유가 없다. 보관 정책과 최신성 판단은 별개이고, **TTL로 데이터의 유효성을 판정하면 안 된다**(R3의 연장). → TTL은 디스크 정리 정책일 뿐이고, 신선도는 원천 시각이 말한다.
- **인터페이스가 소유할 것을 문서에 둔 곳**: F의 "두 리프가 같은 `get_info`를 쓴다"는 **설명이지 구현이 아니다.** 저장된 전체 info를 **다른 필드집합으로 다시 읽는 인터페이스**가 있어야 관측 재사용이 실제로 일어난다. → `prices quote` 다음의 `company profile`은 저장된 관측을 재사용하고 새 요청을 내지 않는다.
- **사용자에게 비용을 넘기는 곳**: `/data/.../data`와 형제 index를 클로드가 조립하게 하거나, 모든 옵션을 `unverified`로 반복하면 해석 비용을 사용자 쪽에 떠넘긴다. → R2(표 인식 슬라이싱)와 아래 R9의 "중요한 조건만 보고"가 이걸 막는다.

### R9. 더 단순한 대안 (수용 — 유지보수 코드량을 줄인다)

CLAUDE.md의 *"일회성 코드에 추상화를 만들지 않는다"*, *"남이 유지보수하는 것이 내가 소유하게 될 것보다 먼저다"*와 같은 방향이다.

| 축소 | 내용 | 효과 |
|---|---|---|
| **A 축소** | 쿼리 캐시·자동 갱신·HTTP 원문 전수 저장은 만들지 않는다. **로컬 선택 직전의 라이브러리 반환값**만 불변 ID로 저장·재생한다. TTL은 선택적 보관 정책 | `store.py`가 작아지고 R4(저장 범위 불명확)도 함께 해소된다 |
| **B 축소** | 파서·페치를 전면 DSL화하지 않는다. `leaves.py`는 **데이터 종류·순서·기본창·필수 문맥만** 선언한다. `read`는 **그 리프의 선택기를 재사용**하고, 범용 JSON Pointer는 필요해질 때 추가한다 | R2(포인터가 표를 훼손)가 **설계 단계에서 소멸한다** — 표를 아는 선택기를 그대로 쓰므로. 코드도 줄어든다 |
| **C/E 축소** | 일괄 `unverified`는 만들지 않고 **중요한 조건만** 보고한다. 예산 `partial`은 표·목록에 적용하되, **단일 거대 문자열까지 "항상 성공"시키는 범용 절단 엔진은 만들지 않는다** | 앞서 우려한 "`unverified` 남발로 필드가 의미를 잃는 것"을 막고, 예외 경로의 복잡도를 없앤다 |

**B 축소가 특히 중요하다.** `read`가 범용 포인터 대신 원 리프의 선택기를 재사용하면, "표를 어떻게 자를 것인가"라는 문제를 두 번 풀지 않는다. finviz가 레코드 목록이라 포인터로 풀 수 있었던 것을 yfinance에 그대로 가져오려던 것이 애초에 잘못이었다.

## 프레임을 판정하는 검사

위 네 문단은 산문이고, **아무도 검사하지 않는 원칙은 그 자체가 문서다.** 각 프레임을 판정 가능한 검사로 바꾼다. 이 검사들은 `SKILL.md`와 `schema` **양쪽에** 적용된다.

| 프레임 | 검사 | 판정 방법 |
|---|---|---|
| `interface over document` | `narrowing`이 `leaves.narrow`와 항상 일치 | 자동 — 스키마 출력과 선언을 대조 |
| | `limits`의 모든 값이 실제 탐침에서 나왔다 | 자동 — 각 `limits` 항목에 대응하는 라이브 탐침이 `test_live.py`에 있다 |
| | 스키마 문장이 argparse 도움말을 재서술하지 않는다 | 자동 — 중복 문자열 검출 |
| | **SKILL.md에 세는 숫자가 없다** | 자동 — 본문에서 리프·필드·프리셋 개수 패턴 검출 (finviz A2 재발 방지) |
| `for user not developer` | `fix`의 명령을 파싱해 실행하면 `ok`이고 **같은 질문에 답한다** | 자동 — `test_budget.py` + `test_live.py` (R5) |
| | **`fix`가 원천 메시지와 모순되지 않는다** | 자동 — 업스트림 메시지에 제약 수치가 있으면 `fix`가 그 인자를 이름 붙인다 (A5) |
| | 내부 식별자가 모델이 읽는 자리에 새지 않는다 | 자동 — `startdatetime` 같은 원천 내부명이 출력 컬럼과 불일치하면 실패 (A4) |
| | 무효한 인자값이 요청 전에 거절된다 | 자동 — `--region ZZ`가 argparse에서 막힌다 (G1) |
| `dense information` | 불변 문장이 결과 봉투에 없다 | 자동 — 결과에 산문 키가 없고 `schema`에만 있다 |
| | **`schema GROUP LEAF`가 기준선의 2배를 넘지 않는다** | 자동 — 현재 `prices history` 3,160자가 기준선. 넘으면 지식이 구조화되지 않고 산문으로 쌓인 것 |
| | **제거 시험**: `SKILL.md`의 각 문단을 하나씩 빼고 모델 시나리오를 돌린다 | 반자동 — 빼도 시나리오가 통과하면 그 문단은 일반 역량이 이미 공급하는 것이다 |
| `principle over rail` | **`units`로 표현 가능한 것이 `gotchas`에 없다** | 자동 — 단위·스케일·역수는 구조로만, 산문 경고로 두지 않는다. **이게 이 프레임의 주 검사다** |
| | 시나리오에 없는 질문에 도달하는가 | 모델 시나리오 9번(계획에 없는 질문) |
| | 스키마에 절차형 문장이 없다 | 수동 — "~하려면 ~하라"가 있으면 계약 문장으로 고쳐 쓴다 |

**`principle over rail`의 주 검사가 왜 `units`인가**: 함정을 산문으로 나열하면 클로드는 목록에 있는 것만 피한다. 우리가 6개를 찾았다고 6개만 있는 게 아니다 — `fund equity`에서 역수를 찾았으니 다른 펀드 리프도 의심해야 하는데, 산문 경고는 그 일반화를 막는다. 필드마다 계약을 구조로 실으면 **목록에 없던 필드도 자기 단위를 갖고 온다.**

**제거 시험이 중요하다.** harness-creator는 모델 기본값에 맞서 쓴 줄이 가장 유용하면서 가장 빨리 낡는다고 말한다. `SKILL.md`의 모든 문단은 "이 문단이 없으면 클로드가 무엇을 잘못하는가"에 답해야 하는데, **그 답을 추측하지 않고 실제로 빼서 확인한다.** 특히 의심스러운 후보:

- `## 대상을 고르고 그대로 유지한다` — "이름 검색은 후보다"는 똑똑한 모델이 이미 안다. 남을 만한 건 심볼 문장부호뿐일 수 있다.
- `## 기본 답은 창이지 전수가 아니다`의 앞부분 — `coverage`가 매번 말한다면 문단이 다시 말할 필요가 없다.

제거 시험이 "기여한다"고 판정한 문단만 남기고, 제거한 문단과 그 근거는 핸드오프에 기록한다(같은 모델 변경 시 재검토할 수 있도록).

## 재작성 작업 (성진 결정: 계약 재설계 + 분류 정리)

각 단계는 `tdd` 스킬을 열어 seam을 합의한 뒤 **레드(재현 테스트) → 그린 → 리팩터** 순서로 간다. 트래커는 `TaskCreate`로 열고 아래 완료 판정을 그대로 적는다.

### 1. `leaves.py` 선언 카탈로그 (신규)

리프 지식이 지금 세 곳(`yfinance_cli.py`의 `build_parser()` if사슬 · `company.py` if사슬 · `COMMANDS` 딕셔너리)에 흩어져 있다. 한 선언으로 모으고 선택·회복·스키마가 **일반적으로** 소비한다.

리프마다: 목적 · 레코드 경로 · **기본창(행 범위 + 필드 투영)** · **recent 방향** · 실제로 좁혀지는 인자(`narrow`) · 불변 해석 계약 · 재유도 불가능한 함정 · 알려진 한계값 · 판정 가능한 조건.

**기본창은 두 축이다**(위 `company news` 분해 참조). 행만 자르면 `thumbnail`·`storyline` 같은 중량 필드가 그대로 따라온다. 그리고 `--fields`가 점 경로(`content.title`)로 중첩에 닿게 해서, 선언된 투영 밖으로 나가는 길을 남긴다.

**완료 판정**: 40리프 전부가 필수 선언을 갖고, 선언되지 않은 리프가 없으며, `narrow`에 선언된 인자가 그 리프에서 실제로 출력을 줄인다는 것을 테스트가 확인한다. `company news --fields content.title`이 동작한다.

### 2. `output.py` 선택·봉투 재작성 (B1, A3, A4, D2)

**먼저 레드**: `prices history --period 5y --limit 5`가 최신을 남기지 않음을 재현. `prices actions --period max --limit 3`이 1987년을 돌려줌을 재현. **동시에 `analysts upgrades --limit 20`이 현재 옳은 답(최근 20건)을 준다는 것을 고정하는 테스트도 함께 쓴다** — 이게 없으면 일괄 뒤집기로 회귀시킨다.

그린 후: 각 리프가 선언한 방향대로 자른다(위 실측표). `coverage{received, shown, exhaustive}`가 **항상** 실린다(현재는 `--limit`이 있을 때만). `conditions{requested, status, evidence}`는 **응답에서 나온 증거**로만 판정하고, 판정 불가한 것은 `unverified`로 명시하되 선택지 자체를 없앨 수 있으면 없앤다(A3의 `--region`). 불변 문장은 `schema`로 내리고 결과엔 관측값만.

**완료 판정**: recent 계열 재현 테스트 통과. 40리프 전부에서 `coverage`가 실린다. `context`에 입력을 그대로 되비추는 필드가 없다. `date_field`가 실제 출력 컬럼명과 일치한다.

### 3. `store.py` + `read` 명령 (신규, C3, C2)

**로컬 선택 직전의 라이브러리 반환값**만 불변 id로 저장한다(R9-A). 쿼리 캐시·자동 갱신·HTTP 원문 저장은 만들지 않는다. `read ID`는 **그 리프의 선택기를 그대로 재사용**하고 **범용 JSON Pointer는 만들지 않는다**(R9-B) — yfinance의 표는 `{index, columns, data}`로 인코딩되므로 범용 포인터가 열 이름 없는 배열을 주고(R2), 표를 자르는 문제를 두 번 풀게 된다.

**TTL은 디스크 정리 정책일 뿐 유효성 판정이 아니다**(R8). 신선도는 원천이 말하는 시각이 판정하고, 결과는 세 시각을 구분해 싣는다 — 원천 시각(`regularMarketTime` 등) / 관측 시각(`observed_at`) / 저장 경과(`read`에서만)(R3).

관측 재사용을 **구현한다**: `prices quote` 다음의 `company profile`은 저장된 관측을 다른 필드집합으로 읽고 새 요청을 내지 않는다(R8). 저장 시점은 어댑터 반환 직후로 고정해 "받지 않은 것을 회복하라"고 안내하지 않는다(R4). 원천 empty는 저장 **전에** 확정하고, `read`가 원 관측의 `partial`·`warnings`를 지우지 않는다(R7-5). 저장 바이트 무결성과 continuation의 질의 결속을 검증한다(R7-6).

**완료 판정**: 저장→read 왕복이 원본과 의미까지 일치(R5). 61,425자 응답이 기본 예산에서 read 반복으로 완독된다. `partial` 관측을 read하면 `partial`과 종료코드 8이 나온다. `prices quote` 후의 `company profile`이 새 HTTP 요청을 내지 않는다.

### 4. `budget.py` too_large 회복 + 오류 처방 (신규, A1, A2, A5, C1, C2)

**먼저 레드**: `company news`의 fix가 `--fields`를 권함을 재현. `--interval 1m --period 1y`의 fix가 "심볼을 확인하라"고 함을 재현(A5).

그린 후: 회복 문장이 `leaves.narrow` 선언에서만 파생된다. 저장된 id와 **실측 팽창비에서 계산한** 창 크기를 명명한다(finviz `raw_fix()` 선례 — 상수를 쓰면 다시 넘친다). 리프별 기본창(행 범위 + 필드 투영)으로 C1의 4개를 해소한다.

**대범위 요청**(성진 결정 + R1): 실패시키지 않고 전부 가져와 저장한 뒤 창 + `coverage` + `id`를 낸다. 단 **리프 기본창으로 잘린 것은 `ok`, 명시적 범위 요청이 예산으로 잘린 것은 `partial`(종료코드 8)**이다. `coverage`가 절단 이유(`leaf_default` / `budget_truncated`)를 싣는다. 예산 `partial`은 표·목록에만 적용하고, **단일 거대 문자열까지 "항상 성공"시키는 범용 절단 엔진은 만들지 않는다**(R9-C).

회복 명령은 **원 선택을 보존**한다 — 다종목 오류에서 첫 종목만 가리키면 비교 요청이 단일 종목 질문으로 바뀐다. 모든 target과 id를 명시하고 셸 인용을 보존한다(R7-3). 단일 항목이 예산을 넘는 경우의 탈출로를 둔다(R7-4). **오류 봉투 자체도 예산 검사를 받는다**(R7-7).

**업스트림 오류의 처방**(A5): 원천 메시지가 해결 가능한 제약을 담고 있으면 그것을 `fix`로 승격한다. 리프의 `limits` 선언과 대조해 **어떤 인자를 어떤 값으로** 바꿔야 하는지 이름 붙인다 — "8일치만 허용된다"는 메시지를 받았으면 `fix`는 `--period 5d`를 말해야지 심볼을 의심하게 하면 안 된다.

**완료 판정**: 40리프 전부 기본 옵션에서 `ok`. too_large가 난 모든 경우에 **fix가 이름 붙인 명령을 그대로 실행하면 성공하고, 같은 관측·종목·기간·조건을 되찾는다**(R5). `--fields`가 닿지 못하는 리프의 fix는 `--fields`를 권하지 않는다. 10종목 오류의 fix가 열 id를 모두 담고도 예산 안이다. **`--interval 1m --period 1y`의 fix가 기간 인자를 이름 붙인다.**

### 5. 어댑터 개수 + quote/profile 분리 (D1, B2, S1~S4)

`prices quote`는 가격·거래·통화 중심, `company profile`은 사업·지배구조·서술 중심의 **다른 기본 필드집합**. 전체는 `--fields`로 닿고 `--list-fields`로 발견한다. 더 이상 중복이 아니라 두 질문이다. **"같은 호출을 쓴다"고 설명하지 않는다** — `get_info()`는 단일 HTTP 응답이 아니므로(R6) 부정확하고, 대신 단계 3의 관측 재사용으로 **구현**한다. 필드마다 시점이 다를 수 있음은 `interpretation`이 싣는다.

`financials`의 관측 context에 `financialCurrency`를 싣는다(B2). S1~S4 리프 제거. `market sector/industry`의 `--region`을 `yf.MarketRegion` 닫힌 선택지로(G1). 달력 `--end` 경계를 실제 동작(배타적)과 일치시키거나 포함으로 교정하고, 어느 쪽이든 선언과 동작을 맞춘다(B3).

**완료 판정**: 두 리프의 기본 필드집합이 다르고 합쳐서 185필드 전체에 도달 가능. `financials income TM`이 재무제표 통화 JPY를 보고한다. 제거된 5개가 `schema`·`--help`에 없다. `--region ZZ`가 argparse에서 거절된다. `calendar earnings --start D --end D`가 그날 행을 돌려준다.

### 6. `schema` 출력에 interpretation·limits·gotchas 탑재 (D2, principle over rail)

```
description    리프의 목적 (한 문장)
arguments      파서에서 파생 (기본값은 이 호스트에서 해석된 실제값 — 현행 유지)
units          ★ 필드 → {scale, kind, inverted} 구조화된 계약
interpretation 불변 계약: 날짜의 의미, 통화 출처, 커버리지 성격
limits         알려진 한계값 (1분봉 8일 / 2m·5m·15m·30m·90m 60일 / calendar ≤100 / screen ≤250)
narrowing      이 리프에서 실제로 좁히는 인자 (leaves.py 선언에서 파생)
gotchas        units·limits로 표현되지 않는 잔여만
output         형태 · 상태 어휘 · 종료 코드
```

**`units`가 `gotchas`보다 먼저다 — 이게 `principle over rail`의 핵심이다.** 함정을 산문으로 나열하면 클로드는 **목록에 있는 것만** 피하고, 목록에 없는 41번째 필드에서 똑같이 틀린다. 대신 필드마다 계약을 구조화해서 싣는다:

```
surprisePercent   {scale: "ratio",   kind: "rate"}        ← 0.0452는 4.52%
Surprise(%)       {scale: "percent", kind: "rate"}        ← 33.33은 33.33%
Price/Earnings    {kind: "multiple", inverted: true}      ← 0.04는 1/24.8
Total Net Assets  {scale: "millions", kind: "currency"}
```

클로드는 경고를 기억하는 게 아니라 **값을 읽을 때마다 그 필드의 계약을 본다.** `gotchas`에는 구조로 표현할 수 없는 것만 남는다(예: "`Category Average`가 자기 값의 복사본일 수 있다", "비미국 지역은 `name`이 null").

**완료 판정**: 결과에서 반복되던 불변 문장이 사라지고 `schema`에만 있다. G2·G3·B2가 **`gotchas` 산문이 아니라 `units` 항목으로** 표현된다. `gotchas`의 모든 항목이 실측 또는 라이브러리 소스에 근거하고, `units`로 표현 가능한 것이 `gotchas`에 남아 있지 않다. **`schema GROUP LEAF`가 현재 기준선(`prices history` 3,160자)의 2배를 넘지 않고 어느 리프도 예산의 절반을 넘지 않는다** — 넘으면 그 리프의 지식이 구조화되지 않고 산문으로 쌓였다는 신호다.

### 7. `SKILL.md` 재작성

교차 원칙만. 한 리프가 소유할 수 있는 문장은 전부 `schema`로 내린다. 아래 섹션 구조 참조.

**SKILL.md는 살아 있는 카디널리티를 적지 않는다.** 리프 수·필드 수·프리셋 수 같은 숫자는 CLI가 매번 정확히 보고하는 것이고, 본문에 박으면 조용히 낡는다 — finviz의 A2가 정확히 이 사례다("87 controls"가 실측 88이 되기까지 3일). 위 섹션 구조의 실측 예시(TM 호가 USD / 재무 JPY 등)는 **변하지 않는 관계**를 보이는 것이라 남지만, 세는 숫자는 남기지 않는다.

**완료 판정**: 본문의 모든 문장이 "이 문장이 없으면 클로드가 무엇을 잘못하는가"에 답한다. CLI가 이미 내는 사실을 반복하는 문장이 없다. 한 리프에만 해당하는 문장이 없다. **본문에 리프·필드·프리셋 개수가 없다.** `description`의 한국어 트리거와 경계 문장은 유지한다(finviz·sec와의 라우팅이 거기 걸려 있다).

### 8. 테스트 재구성 (E1, E2)

- **모양 녹화**: 실제 `news` 1건·`info` 1개·`filings` 1건의 **구조**(중첩 깊이·키 이름·필드 수)를 `tests/yfinance/fixtures/shapes/`에 녹화. **분량은 합성으로 부풀린다** — 통짜 녹화는 수백 KB이고 Yahoo가 모양을 바꾸면 낡은 현실을 계속 통과시킨다.
- **E1 개정**: `assert fix.startswith("Narrow")`를 **"fix의 명령을 파싱해 실제로 실행하고 `ok`를 요구한다"**로 바꾼다.
- **라이브 스위트**(`test_live.py`, `live` 마커): 40리프 기본 호출 예산 통과 / 안내된 fix가 실제로 회복하고 **의미까지 보존** / 각 리프의 선언된 정렬 방향이 현실과 일치 / 저장→read 전수 도달 / `limits`의 모든 값에 대응하는 탐침.
- **모델 시나리오 파일**(`tests/yfinance/model-scenarios.json`): finviz가 이미 같은 형식을 갖고 있다(R7-8). **라이브 CLI 통과는 "CLI가 옳게 답하는가"만 보고 "클로드가 옳게 읽는가"는 보지 않는다.** stale/live 구분, partial/full 구분, 100배 스케일(G2), 역수 배수(G3) 오독은 시나리오로만 검증된다.

**완료 판정**: 개정된 E1이 현재 코드에서 실패하고 새 코드에서 통과한다. 라이브 스위트가 위 5명제를 고정한다. 시나리오 파일이 아래 6개를 담는다. CI(오프라인)는 지금처럼 `-m 'not live'`로 돈다.

## 최종 스킬 디렉터리 구조

```
.claude/skills/yfinance/
├── SKILL.md
└── Scripts/                    # 기존 대소문자 유지 (CI가 이 경로를 참조)
    ├── pyproject.toml
    ├── uv.lock
    ├── .python-version
    ├── yfinance_cli.py         # 파서 조립 + 실행 루프 + read 명령
    ├── leaves.py               # ★신규 선언적 리프 카탈로그
    ├── output.py               # 봉투: encode / result / coverage / conditions / select
    ├── budget.py               # ★신규 emit / too_large / 리프별 회복 문장
    ├── store.py                # ★신규 id 저장 · read · TTL · 경과시간
    ├── prices.py               # 어댑터 (개수)
    ├── company.py              # 어댑터 (개수)
    └── market.py               # 어댑터 (개수)

tests/yfinance/                 # 레포 규약 위치 (CI가 이미 참조)
├── conftest.py                 # HTTP 전송만 교체하는 현행 방식 유지 — 설계가 옳다
├── fixtures/
│   ├── sitecustomize.py
│   └── shapes/                 # ★신규 실제 페이로드의 '모양'
├── test_leaves.py              # ★신규
├── test_output.py              # 봉투·선택·recent 방향
├── test_budget.py              # ★신규 fix가 실제로 회복시키는가
├── test_store.py               # ★신규
├── test_cli.py / test_company.py / test_market.py / test_prices.py
├── test_live.py                # ★신규 `live` 마커
└── model-scenarios.json        # ★신규 finviz와 같은 형식 (R7-8)
```

`references/` 없음 — 리프 지식은 `schema`가, 교차 원칙은 `SKILL.md`가 소유한다.

## 최종 SKILL.md 섹션 구조

```
--- frontmatter ---
name: yfinance
description: (현행 유지 — 한국어 트리거 및 sec·finviz와의 경계 문장 보존)
---

# Yahoo Finance data

## 실행과 발견
  locked 환경 실행법 · ${CLAUDE_SKILL_DIR} 미치환 시 대처 · zsh 변수 확장 주의
  --help → schema GROUP → schema GROUP LEAF 의 발견 순서
  인터페이스가 인자·출력·회복을 소유한다는 선언

## 대상을 고르고 그대로 유지한다
  이름 검색은 후보이지 정체성이 아니다 / 주식·ADR·동명 펀드는 다른 대상
  심볼 문장부호를 바꾸면 다른 상품 / 스크리닝은 조건 일치이지 시장 전수가 아니다

## 숫자에는 단위가 붙어 있지 않다
  yfinance는 이미 float으로 바꿔 건네준다 — 라벨만으로 측정을 식별할 수 없고, 라벨이 틀릴 수도 있다
  호가 통화와 재무제표 통화가 다를 수 있다 (실측: TM 호가 USD / 재무 JPY)
  한 표에 금액·주식수·비율·배수가 섞인다 (실측: TaxRateForCalcs 0.086 옆에 조 단위 금액)
  같은 이름의 값이 명령마다 다른 스케일일 수 있다 (실측: surprisePercent 0.0452 vs Surprise(%) 33.33)
  라벨이 역수를 담을 수 있다 (실측: fund equity의 Price/Earnings 0.04 = 1/24.8)
  비율인지 퍼센트인지를 값의 크기로 추측하지 않는다 — 그 리프의 schema가 말한다

## 시점마다 역할이 다르다
  원천이 말하는 시각 · CLI 관측시각 · 저장 경과시간은 셋 다 다르다 (장 마감 후엔 저장 1분 전이어도 가격은 몇 시간 전 것)
  회계기간 종료 · 발표일 · 시장 타임스탬프도 서로 다른 질문에 답한다
  한 행 안에서도 시점이 섞일 수 있다 (실측: 기관보유의 신고일은 과거, 평가금액은 현재가)
  관측시각은 값을 최신으로 만들지 않는다 / TTM 열은 완결된 회계기간이 아니다
  거래소 타임존을 보존한다

## 값은 이미 변환되어 도착한다
  조정 방식(none/auto/back)이 Close의 의미를 바꾼다 / 조정주가에 배당을 더하면 이중계산
  repair는 한계를 가진 변환이지 원 체결가의 증명이 아니다
  업스트림이 이미 잃은 구분(0과 결측)은 복원되지 않는다

## 기본 답은 창이지 전수가 아니다
  모든 리프가 한 화면 분량을 기본으로 준다 / coverage가 received 대 shown을 매번 말한다
  ok는 이 리프의 기본창, partial은 내가 요청한 범위가 예산에 잘린 것 — 뒤는 나머지를 읽거나 한계를 달아야 한다
  성공 응답은 조건이 적용됐다는 증거가 아니다 (실측: 무효한 지역이 경고 없이 미국 데이터가 된다)
  프리셋과 이름 붙은 조건은 이름이 아니라 반환된 정의로 서술한다
  빈 결과와 null은 '없음'의 관측이지 0이 아니다 / 페이지 사이에 원천이 바뀔 수 있다

## 막혔을 때
  too_large는 예산 조건이지 빈 결과가 아니다 — 응답은 이미 저장되어 있고 read로 닿는다
  fix가 이름 붙인 방법은 그 리프에서 실제로 작동한다
  rate limit은 남은 목표를 시도하지 않게 한다 / 한계는 사용자의 결론에 영향을 줄 때 말한다
```

## 검증

### 구조·단위 (네트워크 없음, CI)
```bash
uv run --frozen --group dev --project .claude/skills/yfinance/Scripts python -m pytest tests/yfinance
uv run --frozen --group dev --project .claude/skills/yfinance/Scripts ruff check --config pyproject.toml .claude/skills/yfinance/Scripts tests/yfinance
```

### 현실과의 계약 (`live` 마커, 수동)
```bash
uv run --frozen --group dev --project .claude/skills/yfinance/Scripts python -m pytest tests/yfinance -m live
```

고정하는 명제:
1. **40리프 전부** 기본 옵션 호출이 예산 안에서 성공한다 (현재 4개 실패)
2. too_large가 난 모든 리프에서 **fix의 명령을 그대로 실행하면 성공한다** (현재 `company news`가 거짓)
3. `recent` 계열에서 `--limit`가 **최신** 조각을 남긴다 (현재 정반대)
4. 저장→`read`로 재요청 없이 전수에 도달한다 (현재 경로 없음)
5. `read` 결과가 경과시간을 싣는다
6. `financials`가 재무제표 통화를 보고한다

### 회귀 기준선
이 세션에서 측정한 45리프 전수 결과(위 장부의 상태·문자수)를 기준선으로 삼는다. 재작성 후 같은 스윕을 돌려 **어떤 리프도 나빠지지 않았고 4개가 고쳐졌음**을 확인한다.

### 모델 시나리오 (코덱스 `gpt-6-astra`, medium, 격리 세션)

**SKILL.md와 CLI만 주고 소스 읽기는 금지한다.** 이것이 "문서와 인터페이스가 자족적인가"의 유일한 진짜 시험이다(finviz·sec 선례).

1. "애플 최근 5년 주가 흐름" — B1 함정을 밟지 않고 **최신** 데이터에 도달하는가. 예산 절단을 `partial`로 인식하고 답변에 한계를 다는가(R1)
2. "토요타 PER 계산" — 통화 불일치를 발견하는가 (B2). 재무 JPY와 호가 USD를 섞지 않는가
3. "SPY의 PER이 얼마야" — **역수 함정(G3)에 걸리는가.** 0.04를 PER로 보고하면 실패
4. "애플 실적 서프라이즈가 최근 몇 %였어" — **100배 스케일(G2)을 옳게 읽는가.** `surprisePercent 0.0452`를 4.52%로 읽어야 한다
5. "10월 1일에 실적 발표하는 회사" — **B3 경계 함정.** 0행을 "없음"으로 보고하면 실패
6. "블랙록이 애플을 얼마나 들고 있어" — **G5 시점 혼합.** 신고일과 평가 시점이 다름을 말하는가
7. "시총 20억달러 이상 기술주 스크리닝" — 조건 발견에서 시작해 도달하는가. **실패 호출 수를 합격 기준에 넣는다**. 프리셋을 쓴다면 이름이 아니라 반환된 `query`로 서술하는가(G4)
8. "3종목 재무 비교" — 다중 목표에서 예산과 회복이 작동하고, 회복이 비교를 단일 종목으로 바꾸지 않는가(R7-3)
9. **계획에 없는 질문** — 이 계획의 어느 항목도 겨냥하지 않는 실제 분석 질문 1건을, 시나리오를 쓰는 시점에 즉석으로 정해 돌린다. 예: "엔비디아 내부자들이 최근 순매도인가", "SPY와 QQQ의 섹터 구성이 어떻게 다른가". **`principle over rail`을 판정하는 유일한 시나리오다** — 앞의 여덟은 전부 우리가 고친 것을 확인할 뿐이라 레일이 깔린 길이고, 클로드가 원칙에서 재유도하는지는 아무도 예상하지 않은 질문에서만 드러난다. 합격 기준은 정답이 아니라 **막히지 않고 도달하는가, 그리고 한계를 정확히 말하는가**다

**샌드박스는 `danger-full-access`** — 제한 샌드박스에서는 CLI가 네트워크에 나가지 못해 코덱스가 픽스처 값을 답으로 낸다(finviz 세션에서 확인된 함정).

### 코덱스의 역할 (성진 결정: 검증 + 함정 발굴. 구현과 최종 판단은 클로드)

`gpt-6-astra` medium 기준. **구현은 클로드가 끝까지 책임진다** — codex가 모듈을 쓰지 않는다. 계약 일관성이 여러 손을 거치면 깨지고, 그 일관성이 이 재작성의 전부이기 때문이다.

| 시점 | 역할 | 산출물의 처리 |
|---|---|---|
| 계획 (완료) | 레인 A 함정 발굴 / 레인 B 설계 비판 | 이 계획에 반영 |
| **단계 6 — 그룹별 함정 발굴** | `financials`·`options`·`holders`·`fund`·`screen`·`calendar` 등 그룹 단위로 독립 발굴을 맡긴다. 클로드 혼자 하면 클로드가 의심한 곳만 짚는다(이번 세션의 실측이 그랬다) | **클로드가 실측으로 확인·반증한 것만** `schema.gotchas`에 싣는다. 확인 못 한 후보는 "검증하지 않은 것"에 남긴다 |
| 단계 2 완료 직후 | recent 방향·선택 계약 리뷰 | 지적 반영 또는 반영하지 않는 이유 기록 |
| 단계 4 완료 직후 | 회복 계약 리뷰 (가장 위험한 곳) | 동상 |
| 구현 후 | 전체 diff + 새 `SKILL.md`/`schema`를 4프레임 기준으로 1회 | 동상 |
| 구현 후 | 모델 시나리오 (아래) | 실패 시 해당 단계로 되돌아간다 |

**함정 후보는 증거이지 결론이 아니다.** codex가 낸 항목은 클로드가 실제 호출로 재현해야 `gotchas`에 들어간다 — 검증되지 않은 함정을 스키마에 실으면 그 스키마가 곧 A1(거짓말하는 인터페이스)이 된다.

### 전달
브랜치 `refactor/yfinance-contract-recovery`, 커밋 단위는 위 1~8, PR 제목 `refactor: yfinance 계약·회복·해석 재설계`, `gh pr merge --squash`.

## 검증하지 않은 것

- Yahoo 429의 실제 임계 — 이번 세션 약 95회 호출에서 발생하지 않음
- `--interval 30m`이 내부적으로 15m로 매핑되는지, 아니면 오류 메시지만 잘못된 이름을 쓰는지
- `fund operations`의 `Total Net Assets` 단위가 백만 달러인지 (SPY 513,975.7이 실제 AUM과 맞는지 대조 안 함)
- `Category Average`가 항상 자기 값의 복사본인지, SPY에서만 그런지
- 비미국 지역에서 `name`이 null인 것이 모든 데이터셋에 해당하는지
- 역수 배수(G3)가 `fund equity` 외 다른 펀드 리프에도 있는지
- 코덱스 레인 A의 전체 보고 — 전송은 성공했으나 이 세션에 미도착. 요약에서 옮긴 6개 후보는 전부 클로드가 독립 재현했고, 그 보고에만 있던 항목(극소 IV의 의미, 달력 시간대 기준)은 단계 6에서 다시 발굴한다
- `screen`의 `total`이 페이지 사이에서 안정적인지
- 옵션 체인의 `lastTradeDate` 노후 가설 (코덱스 레인 A 결과 대기)

## 폐기하지 않는 결정

- **그룹/리프 분류는 보존한다.** 45개 중 38개가 정상 동작하고, 분류를 버리면 검증된 어댑터 지식(통화·날짜 의미·경고문)을 재발견해야 한다. 백지 재작성은 검토했고 기각했다.
- **`conftest.py`의 HTTP 전송 교체 방식은 옳다.** 실제 yfinance를 돌리고 "UNEXPECTED NETWORK"로 누락을 잡는다. 문제는 이 설계가 아니라 합성 페이로드가 현실의 모양을 재현하지 못한 것이다.
- **`describe()`가 파서에서 기본값을 파생시키는 것은 옳다.** 확장해야 할 방향이지 바꿀 것이 아니다.
- **`--max-chars` 기본 20,000은 유지한다.** 리프별 기본창이 출력 크기를 결정하게 되면 예산은 구속 조건이 아니라 안전 경계가 된다.
- **`references/`를 만들지 않는다.** 리프 지식은 `schema`가 소유하는 것이 클로드가 명령을 쓰려 할 때 이미 보고 있는 자리다.
- **명령 개수를 줄이는 것은 목표가 아니다.** 실측상 발견 비용은 작다(`--help` 1,659자). 잉여는 개수가 아니라 검증 못 할 리프와 판정 불가능한 인자다.
- **`Scripts/` 대문자를 유지한다.** CI가 이 경로를 참조하고, 이름만 바꾸는 변경은 요청에 대응하지 않는다.

## 코덱스 레인 A(함정 발굴) 반영 — 후보 목록

**이 항목들은 코덱스가 낸 후보이지 결론이 아니다.** 클로드가 실제 호출로 재현한 것만 `schema.gotchas`에 싣는다 — 검증되지 않은 함정을 스키마에 실으면 그 스키마가 곧 A1(거짓말하는 인터페이스)이 된다. 단계 6에서 각각 확인·반증한다.

| # | 후보 | 상태 |
|---|---|---|
| G1 | 잘못된 지역이 미국 데이터로 조용히 대체된다 | **✅ 재현 확정** (아래) |
| G2 | 같은 서프라이즈 필드가 명령마다 100배 다른 스케일 | **✅ 재현 확정** (아래) |
| G4 | 프리셋 이름과 실제 조건이 다르다 | **✅ 재현 확정** (아래) |
| G5 | 기관보유의 신고일과 평가금액 시점이 다르다 | **✅ 재현 확정** (아래) |
| G6 | 달력의 종료일이 그날을 포함하지 않는다 | **✅ 재현 확정 → 결함 B3로 승격** |
| G3 | ETF 배수가 라벨과 역수 · 총순자산 단위 미선언 | **✅ 재현 확정** (아래) |

**6개 전부 확정됐고 그중 하나(G6)는 B등급 결함이었다.** 코덱스 역할을 함정 발굴까지 넓힌 결정(성진)이 전수 스윕으로는 잡히지 않는 층을 열었다 — 기본 옵션 호출은 이 중 **어느 것도** 드러내지 못한다.

#### G3 확정 — ETF 배수가 라벨과 역수다

```
fund equity SPY
  Price/Earnings  = 0.04035     1/x = 24.8    (S&P500 실제 PER ≈ 25)
  Price/Book      = 0.18935     1/x = 5.28    (실제 PBR ≈ 5.3)
  Price/Sales     = 0.27339     1/x = 3.66
  Price/Cashflow  = 0.05261     1/x = 19.0
```

**네 배수 전부 라벨과 역수다.** `Price/Earnings` 자리에 **E/P(이익수익률)**가 들어 있다. "SPY의 PER은 0.04"라고 보고하면 완전한 오답인데, 클로드에게는 의심할 단서가 없다 — 0.04라는 값이 배수로서 불가능하다는 것을 알아도, 그게 역수인지 다른 단위인지 판정할 근거가 인터페이스에 없다.

같은 그룹에 둘 더:

```
fund operations SPY
  Annual Report Expense Ratio  [0.000945, 0.0072176997]   비율(0.0945%)이지 퍼센트가 아니다
  Total Net Assets             [513975.7, 513975.7]       단위 미선언(백만 달러로 보임),
                                                          Category Average가 자기 값의 복사본
```

`Category Average`가 자기 값과 같다는 것은 **비교 기준으로 쓸 수 없다**는 뜻인데, 열 이름은 비교 기준이라고 말한다.

#### G1 확정 — 무효한 지역이 조용히 미국이 된다 (그리고 제 초기 판정 정정)

`market sector technology --dataset top-companies`:

| `--region` | index(심볼) | `name` 열 |
|---|---|---|
| `US` | NVDA, AAPL, MSFT | 정상 |
| `KR` | **005930.KS, 000660.KS, 402340.KS** (한국 종목 맞음) | **전부 null** |
| `JP`·`DE` | 해당 지역 종목 | **전부 null** |
| `ZZ`·`NOTAREGION` | NVDA, AAPL, MSFT | 미국 데이터로 대체 |

**세 가지가 동시에 참이다.** ① 유효한 지역은 실제로 적용된다 ② 무효한 값은 경고 없이 미국이 된다(finviz `cap_bogus`와 같은 형태) ③ 비미국 지역은 회사명이 null로 와서, 지역이 작동해도 데이터가 열화된다.

**정정 기록**: 초기 점검에서 "US와 JP가 같은 응답을 낸다 → `--region`은 판정 불가"라고 적었으나 **틀렸다.** 그 탐침은 존재하지 않는 필드명(`name,market_weight`)을 요청해 양쪽 다 null을 받은 것이고, 지역이 무시된 증거가 아니었다. 코덱스 레인 A가 `--region KR`로 한국 종목을 얻어 이 오판을 깨뜨렸다 — **독립 레인이 제 프레임의 오류를 잡은 사례다.**

**원인이 코드에 있다**: `yfinance_cli.py:124`는 `market status`·`summary`의 `--region`에 닫힌 선택지(`choices=[r.value for r in yf.MarketRegion]`)를 주는데, `:127`의 `market sector`·`industry`는 **자유 문자열**이다(`help="Yahoo region code."`, choices 없음). 같은 이름의 인자가 리프마다 다른 계약을 갖는다.

**수정 방향 변경**: "US 고정"이 아니라 **닫힌 선택지로 통일한다.** 인터페이스가 무효한 값을 애초에 받지 않으면 G1은 argparse 층에서 소멸한다 — harness-creator의 *"an explicit argument, schema or restricted tool surface may make the invalid action unavailable"*가 바로 이 경우다. 프로세스(A3) 수정으로 `context`는 입력을 되비추지 않는다. 비미국 지역의 `name` null은 해당 리프의 `gotchas`가 소유한다.

#### G2 확정 — 같은 이름의 값이 100배 다르다

| 리프 | 필드명 | 실측값 | 실제 의미 |
|---|---|---|---|
| `analysts history` | **`surprisePercent`** | `0.0452`, `0.0634`, `0.0346` | **비율** (4.52%, 6.34%, 3.46%) |
| `calendar earnings` | **`Surprise(%)`** | `33.33`, `3.56`, `650.0` | **퍼센트** |

검산: `analysts history` 2025-12-31은 actual 2.84 / est 2.6708 → 6.34%인데 필드값은 `0.0634`. **`surprisePercent`라는 이름이 퍼센트라고 말하면서 비율을 담는다.**

클로드가 `0.0452`를 "0.045% 서프라이즈"로 읽거나 다른 리프의 `33.33`과 비교하면 100배 틀린다. **어떤 모델도 이걸 재유도할 수 없다** — 알려줘야만 안다. `principle over rail`이 말하는 "일반 역량이 공급 못 하는 사실"의 교과서적 사례이고, `SKILL.md`의 "숫자에는 단위가 붙어 있지 않다" 절과 해당 리프의 `gotchas` 양쪽에 근거를 준다.

#### G4 확정 — 프리셋 이름이 조건을 말하지 않는다

```
small_cap_gainers  query: intradaymarketcap < 2B  AND  exchange in (NMS, NYQ)
                   sort:  eodvolume desc
```

**상승 조건이 아예 없다.** 이름은 "gainers"인데 실제로는 *거래량 많은 소형주*다. 이 프리셋 결과를 "오늘 소형주 상승 종목"이라고 서술하면 근거 없는 주장이 된다. `undervalued_growth_stocks`도 정렬이 `eodvolume`이라 "가장 저평가된 것"이 앞에 오지 않는다. (반면 `day_gainers`는 실제로 `percentchange > 3`을 가진다 — 그래서 이름을 믿는 습관이 더 위험하다.)

`screen presets`가 이미 `query`를 그대로 돌려주므로 **인터페이스에 근거가 있다.** SKILL.md는 "프리셋은 이름이 아니라 반환된 조건으로 서술한다"만 말하면 된다.

#### G5 확정 — 한 행 안에 두 시각이 섞인다

```
holders institutional AAPL
  Date Reported = 2026-06-30      (2026-06-30 종가 = $289.11)
  Value / Shares = $336.13        (= 오늘 현재가)
```

주식수는 6월 30일 신고분, 평가금액은 **오늘 시가**로 평가된 것이다. "블랙록이 2026-06-30 기준 $390B 보유"라고 읽으면 16% 틀린다(336.13/289.11). 재유도 불가능하고, `SKILL.md`의 "시점마다 역할이 다르다" 절과 이 리프의 `gotchas`가 함께 소유한다.

레인 A의 전체 보고(전송은 성공했으나 이 세션에 미도착)는 위 확정 항목 외에 ETF 역수형 값·극소 IV·달력 시간대 기준을 미확정 해석으로 남겼다고 요약했다. 단계 6에서 다시 발굴한다.

## 이 세션에서 바로잡은 제 오판 (기록)

핸드오프가 이걸 갖고 있어야 다음 세션이 같은 오판을 반복하지 않는다.

| 처음 쓴 것 | 왜 틀렸나 | 바로잡은 것 |
|---|---|---|
| "yfinance에는 테스트가 없다" | 스킬 디렉터리 안만 봤다. 실제로는 `tests/yfinance/`에 55개 테스트와 CI 잡이 있다 | 테스트 **아키텍처는 옳고**(HTTP 전송만 교체) 합성 페이로드가 현실의 모양을 재현 못 한 것이 문제 |
| "`--region`은 무시되므로 판정 불가" | 탐침이 존재하지 않는 필드명을 요청해 양쪽 다 null을 받았다. 지역이 무시된 증거가 아니었다 | 유효 지역은 **작동하고** 무효 값만 조용히 미국이 된다(G1). 수정도 "US 고정"에서 "닫힌 선택지"로 바뀌었다 |
| "저장+read는 finviz 어휘를 그대로" | yfinance의 표 인코딩에는 범용 포인터가 맞지 않는다 | `read`가 그 리프의 선택기를 재사용한다(R2·R9-B) — 코드도 줄어든다 |
| "대범위도 창으로 주면 항상 성공" | 기본창 절단과 예산 절단을 구별할 수 없게 만든다 | 예산 절단은 `partial`(R1) |

**독립 레인이 없었으면 두 번째와 세 번째는 그대로 구현됐을 것이다.**

---

# 구현 기록 (2026-09-19, PR #16 `refactor/yfinance-contract-recovery`)

스쿼시 머지는 PR 제목만 `main`에 남기므로, 다음 세션이 알아야 하는 결정은 여기 적는다. diff가 보여주는 것은 적지 않는다.

## 계획을 따르지 않은 곳과 그 이유

**G1 수정을 `yf.MarketRegion` 닫힌 선택지로 하지 않았다.** 계획은 `yfinance_cli.py:124`가 `market status`에 쓰는 그 enum을 `sector`·`industry`에도 쓰라고 했는데, 그 enum은 `US/GB/ASIA/EUROPE/RATES/COMMODITIES/CURRENCIES/CRYPTOCURRENCIES` 여덟 개뿐이고 `quote/marketSummary` 엔드포인트용이다. `Sector`·`Industry`는 ISO 3166-1 alpha-2를 받는 **다른 이름공간**이라(`domain.py:24`), 지시대로 했으면 계획이 G1에서 직접 실측해 "작동한다"고 확인한 `KR`·`JP`·`DE`가 전부 argparse에서 거절됐을 것이다.

대신 서비스되는 코드를 실측했다: 각 코드로 `sector technology --dataset top-companies`를 부르고 US와 같은 종목이 오면 조용한 대체로 판정했다. 서비스되는 것 29개(`market.py:DOMAIN_REGIONS`), 대체에 걸린 것은 `ZZ`·`XX`·`UK`·`EU`뿐 아니라 **`NL`·`CH`·`IE`·`ZA`·`AT`·`BE` 등 실제 Yahoo 지역판이 있는 나라들도 포함**된다. `MX`·`NZ`·`VN`은 라이브러리가 예외를 던진다. 이 목록이 낡는 조건은 Yahoo가 지역을 추가하는 것이고, `test_live.py`가 `KR`로 탐침한다.

## 계획의 수치가 틀린 곳

**리프는 45개가 아니라 53개였고, 제거 후 40개가 아니라 49개다.** `COMMANDS` 실집계다. 계획의 "45→40"에 맞추려고 리프를 더 지우지 않았다 — 제거 근거는 S1~S4의 것이지 개수가 아니다. 이 숫자를 코드나 SKILL.md에 박지 않았으므로 다음에 또 어긋나도 조용히 거짓이 되지는 않는다.

`screen run`의 필드 수도 계획은 93개, 이번 실측은 88개다. 같은 이유로 어디에도 적지 않았다.

## 계획에 없던 발견 (전부 실측으로 확인)

- **`prices quote` 안에 100배 충돌이 있다.** `dividendYield` 0.32(퍼센트, = 0.32%)와 `trailingAnnualDividendYield` 0.0031(비율, = 0.31%)이 같은 측정이다. `fiftyTwoWeekChangePercent` 31.26과 `52WeekChange` 0.3126도 같은 쌍이다. G2는 리프 **사이**의 충돌이었는데 이건 한 리프 **안**에 있다.
- **`screen` 질의의 성장률 임계는 퍼센트 포인트다.** `BTWN quarterlyrevenuegrowth.quarterly 20 30`이 quote `revenueGrowth` 0.242인 기업을 주고, 같은 뜻으로 쓴 `0.20 0.30`은 0.2%대 성장 기업 26개를 준다. 둘 다 실패하지 않는다. 출력의 단위를 질의에 그대로 옮기면 100배 틀린 채 그럴듯한 목록이 나온다.
- **`ytd return`의 raw 3.654가 원천 표기로 "365.40%"다.** 그리고 overview는 `market_weight`(밑줄), 구성종목 표는 `market weight`(공백)로 같은 값을 다르게 부른다.
- **`--interval 30m`이 15m에서 리샘플된다.** 계획의 "검증하지 않은 것"에 있던 항목이고, 오류 메시지가 15m을 이름 붙이는 이유가 이것이다.
- **`fund operations`의 `Total Net Assets`는 백만 달러가 아니다.** SPY가 513,975.7을 보고하는데 같은 펀드의 `totalAssets`는 811,937,038,336(= 811,937백만)이다. 계획이 "백만 달러로 보임"이라고 남긴 추정을 **반증**했다. `units`에 `scale: unverified`로 싣고 `gotchas`가 이 대조를 적는다.

## 반증한 함정 후보

- `financials income`의 `BasicContinuousOperations`류가 주당 값이라는 후보(코덱스): GE·F·T에서 그 필드 자체가 반환되지 않는다. 반환되는 것은 `NetIncomeContinuousOperations`이고 명백히 총액이다.
- `fund equity`의 `Median Market Cap`이 백만 단위라는 후보: SPY·QQQ·IWM 모두 NA라 판정 불가. `units`에 스케일을 선언하지 않았다.

## 모델 기본값에 맞서 쓴 줄 (모델이 바뀌면 재검토)

SKILL.md의 **"Do not settle the question from the magnitude — plausible-looking numbers are exactly where this goes wrong"** 한 문장이 여기 해당한다. 교정 대상은 "값의 크기로 단위를 추론하는" 기본 성향이다. 0.04를 PER로 보고 이상하다고 느끼는 모델은 많지만, **느낀 뒤에 역수인지 다른 단위인지 판정할 근거가 인터페이스에 없으면 그럴듯한 쪽으로 정한다** — G3가 그 사례다. 모델이 바뀌어 `units`를 항상 먼저 읽는다면 이 문장은 잉여가 된다.

`units`를 `gotchas`보다 먼저 두는 구조 자체도 같은 성격이다: 함정을 산문으로 나열하면 목록에 있는 것만 피한다는 가정 위에 서 있다.

## 하지 않은 것

- **SKILL.md 문단 제거 시험을 전부 돌리지는 않았다.** 계획이 지목한 두 후보 중 `## Choose the target and keep it`만 제거해 시나리오 2건으로 확인했다(아래). 나머지 다섯 문단은 돌리지 않았다 — 문단×시나리오라 비용이 크고, 이번에 고친 것을 확인하는 시나리오는 어차피 레일이라 판별력이 낮다.
- **`tests/yfinance`의 CI 잡이 실제로는 돌지 않고 있다.** `.github/workflows/test.yml`("Social skill checks")이 레포에서 `disabled_manually` 상태다. 이번 PR에서 통과한 체크는 finviz 워크플로뿐이고, yfinance 잡은 2026-09-16 sec PR 때부터 한 번도 돌지 않았다. 이 PR에서 건드리지 않았다 — 다시 켜면 이 스킬과 무관한 다른 스킬들의 잡까지 함께 살아나므로 성진의 결정이다. 같은 명령을 로컬에서 `--isolated`로 돌려 312 passed를 확인했다.
- Yahoo 429 임계는 이번에도 재현되지 않았다(약 400회 호출).
- `epsTrailingTwelveMonths`의 ADR 환산 단위는 선언하지 않았다. 모델 시나리오 2번이 실제로 이 공백을 지적했다 — TM의 TTM EPS 22.52가 어느 통화·어느 주당 단위인지 스키마가 말하지 않아, 제공된 `trailingPE`와 일치한다는 것만이 근거였다. 다음 세션의 후보다.

## 계약이 서로 물린 곳 (하나만 고치면 깨진다)

- `leaves.recent`와 `read`의 창 방향은 **반대**다. 첫 호출은 리프가 선언한 끝을 남기고(최신), `read`는 `--start`부터 앞으로 걸어간다. `read`에도 `recent`를 적용하면 `--start`를 올려도 같은 꼬리가 반복되고, **합계만 보면 완독한 것처럼 보인다** — 이번 구현 중 실제로 그렇게 통과한 적이 있다. `output.select`의 `paging` 분기가 그 자리다.
- `budget.shrink`가 창을 줄이면 `continuation`을 **다시 계산**해야 한다. 축소 전 개수로 둔 continuation을 따라가면 줄어든 만큼의 행을 건너뛴다.
- `too_large_fix`가 이름 붙이는 `--max-chars`는 **축소 전** 크기다. 축소 후 크기를 실으면 그 값으로 다시 돌려도 또 넘친다.

## 제거 시험 결과 — 한 문단을 실제로 뺐고, 빼는 쪽이 옳았다

`## Choose the target and keep it` 전체를 제거하고 시나리오 2건을 격리 세션에서 돌렸다.

- 토요타 PER: 통과. 제거 전과 **같은 답**이고, USD 호가와 JPY 재무제표를 섞지 않은 것도 그대로다.
- "애플 ADR 말고 보통주": 통과. 그리고 모델이 스스로 *"`EQUITY` 분류 자체는 보통주와 예탁증서를 엄밀히 구분하지 않습니다"*라고 적었다 — **그 문단이 하려던 말을 문단 없이 일반 역량이 공급했다.**

계획의 예측("남을 만한 건 심볼 문장부호뿐일 수 있다")이 맞았다. 그래서 문단은 지우고, 문장부호 한 문장만 `## Execute and discover`로 옮겼다. 그건 일반 역량이 공급하지 않는다 — 심볼에서 점 하나를 빼면 다른 상품이 된다는 것은 이 데이터 원천의 사실이지 추론할 수 있는 규칙이 아니다.

**이 판정의 조건**: `gpt-6-astra` medium, 시나리오 2건. 모델이 바뀌면 다시 봐야 한다 — 정체성 구분을 스스로 하지 않는 모델에게는 그 문단이 다시 기여한다. 지운 문단의 원문은 이 PR의 diff에 있다.
