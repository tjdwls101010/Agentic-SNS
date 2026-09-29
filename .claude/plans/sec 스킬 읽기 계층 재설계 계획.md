# sec 스킬 읽기 계층 재설계 계획

## Context

`sec` 스킬의 일은 finviz·yfinance가 주는 가공된 숫자의 **출처**를 주는 것이다. "NBIS 주식수가 왜 늘었나"에 yfinance는 shares outstanding 시계열을 주지만, "선불워런트 2,000.0을 NVIDIA에 발행했고 행사가 $0.0001이며 basic EPS 계산에 포함된다"는 6-K EX-99.2 본문에만 있다. 성공 기준은 하나다 — **정확한 기업·기간의 원문을 고르고, 근거가 되는 문단과 표를 실제로 읽어낼 수 있는가.**

2026-09-16 4프레임 점검(`sec 스킬 4프레임 점검.md`)이 이미 같은 모양을 짚었다: *"「점진적 로드」 원칙이 「모든 것을 20개씩 균등 페이지」라는 레일로 구현됐다."* 그때 `context`/`header`/`--kind`/`schema` 범위가 추가됐지만 **Apple 한 건으로만 검증됐고**, 같은 잘못된 모델을 그대로 인코딩했다 — *"표는 셀 레코드의 평평한 스트림이고 헤더는 한 행이다."*

그 결과가 실제 분석 과제에서 드러났다. NBIS 지분변동표에서 주식수·워런트·전환 행을 읽어야 하는데 모델이 "어느 숫자가 주식수인지 알 수 없다"에 막혔다. 외부 세션은 이를 "표가 감지되지 않는다"로 보고했으나 **원인 진단이 틀렸다.** 이 계획은 원인을 실측으로 확정하고 읽기 계층을 격자 모델로 재작성한다.

이 세션은 측정과 합의만 했다. 구현 파일은 바꾸지 않았다.

---

## 실측 사실 장부

측정 주체를 구분한다 — **[C]** 이 세션(Claude)의 직접 측정, **[X]** 코덱스 `gpt-6-astra` 3개 관점의 독립 측정, **[미검증]** 아직 확인하지 않은 것.

측정 대상 (실제 fetch·파싱, 격리 캐시):

| 문서 | 크기 | snapshot |
|---|---|---|
| NBIS 6-K EX-99.2 분기재무제표 `nbis-20260812xex99d2.htm` | 1.5MB | `dadff2e579…` |
| AAPL 10-K `aapl-20250927.htm` | 1.5MB | `c0322b57f6…` |
| MRVL 10-Q `mrvl-20260801.htm` | 2.0MB | `b671b746ea…` |
| (픽스처) Apple 2024 10-K, Microsoft 2026, ASML, `old.txt`, `form4.xml` | — | `tests/sec/fixtures/` |

### 보고된 증상과 실제 원인 [C]

외부 세션 보고: "NBIS 지분변동표가 표로 감지되지 않는다." **틀렸다.** 그 표는 `table-7`(block 1287, 32행)로 정상 감지되며 block 1753은 내부적으로 `table_id: table-7`을 갖는다.

실제 결함은 **매치 위치에서 그 표로 가는 경로가 인터페이스에 없다**는 것이다.

| 경로 | 실측 |
|---|---|
| `find` 항목 | `table_id` **없음** (JSON·텍스트 모두) |
| `read --json` | `table_id: table-7` **있음** |
| `read` 텍스트 모드(기본) | **버려짐** — `output.py:passage()`가 `text`만 렌더, `HEADER`에 없음 |
| `outline`의 표 항목 | 표 **시작 블록**(1287) — 매치(1753)에서 466블록 앞 |

### 불가시 문자 — 범위를 좁혀야 한다 [C]+[X]

`document.py:38 _clean()`이 `re.sub(r'\s+', ' ')`인데 파이썬 `\s`는 **U+200B를 매치하지 않는다.** Workiva로 생성된 현대 공시는 레이아웃 셀을 `&#8203;`로 채운다.

| 문자 | 관측 | 처리 |
|---|---|---|
| **U+200B** | NBIS DOM에 2,913개. **저장 블록에서 다른 문자와 섞인 사례 0개** [X] | 공백·U+200B만인 레이아웃 문자열을 빈 값으로 |
| U+00A0 | NBIS 365 / Apple 1,134 / MSFT 9,968 [X] | **이미 `\s`에 잡힘** |
| U+202F | NBIS 12개 [X] | **이미 `\s`에 잡힘** |
| U+2007 | 로컬 자료 24개 [X] | 이미 잡힘. 서식용 빈 자리를 숫자로 해석하지 말 것 |
| U+2011 | NBIS EX-99.1의 `Share‑based` 등 2개 [X] | **보존** |
| U+2060, U+00AD | 조사 범위에서 미발견 [X] | 보존 |

> **정정.** 나는 처음에 "특수 공백 전반"이 문제라고 봤으나 U+00A0·U+202F·U+2007은 이미 `\s+`에 잡힌다. 실제 문제는 **U+200B 레이아웃 셀이 빈 값으로 판정되지 않는 것** 하나다. 그리고 혼합 문자열(`foo​bar`)의 U+200B까지 지울 근거는 이번 표본에 없으므로 **레이아웃 셀 제거만** 적용한다. 증거성이 우선이다.

영향 [C]: NBIS 블록 5,591개 중 **2,831개(51%)가 순수 `​`**; table-7 셀 564개 중 310개(55%); **표 79개 중 78개의 `header`가 `​ | ​ | ​ …`**. AAPL은 `​`가 없으나 셀 6,443개 중 **4,034개(63%)가 빈 칸**. `table`이 문서화한 "empty layout cells are omitted"가 **조용히 실패**한다 — `'​'`는 truthy.

**절대 건드리지 않을 것**: 괄호, 소수점, 쉼표, `%`, 통화기호, `—`/`–`/`-`/`−`, U+2011. NFKC·ASCII 치환·광범위한 `Cf` 삭제도 적용하지 않는다. `(1,968.1)`과 `—`는 NBIS table-7에 실제로 있는 값이다. [X]

### 블록의 대부분이 표 셀이다 — 격자 모델의 근거 [C]

| | 블록 | 표 셀 | ZWSP/빈칸 | 산문 | 표=블록1개 환산 |
|---|---|---|---|---|---|
| NBIS | 5,591 | **5,163 (92%)** | 2,831 (51%) | 334 (6%) | **413 (7%)** |
| AAPL | 3,124 | 2,449 (78%) | 0 | 675 (22%) | 737 (24%) |
| MRVL | 3,532 | 2,662 (75%) | 0 | 870 (25%) | 925 (26%) |

`read`로 문서를 훑으면 NBIS에서 **92% 확률로 셀 조각 하나**를 받는다. 이것이 "셀 하나가 한 줄인 조각"의 근원이다.

### 표 출력 계약 크기 — NBIS `table-7` (원본 19열×32행, 값 있는 셀 254/564) [C]

| 계약 | 크기 | 호출 | 판정 |
|---|---|---|---|
| 현행 셀-레코드(ZWSP 포함) | 46,000자 | 4회+ | 읽히지 않음 |
| 현행 계약 + ZWSP만 제거 | 17,797자 | 2회 | 값마다 `column: 7` |
| 행라벨×열라벨=값 | 18,627자 | 2회 | **틀린 사실 180건 생성** |
| **빈 열 접은 파이프 무패딩 격자** | **2,086자** | **1회** | **채택** |
| (참고) 열폭 맞춤 정렬 | 5,927자 | 1회 | 2.8배, 대부분 공백 |

코덱스가 독립적으로 같은 접기를 재현했다 — 19열→10열, 남는 원래 열 `[0,1,3,5,7,9,11,13,15,17]`, 본문 2,045자. [X]

"행라벨×열라벨" 안이 기각된 이유: 이 표는 **2025년 상반기와 2026년 상반기가 세로로 스택**돼 있어 열 라벨을 기계적으로 합성하면 `Six months ended June 30, 2025 … June 30, 2026`이 한 라벨로 붙는다. 격자를 그대로 주면 모델이 15행에서 두 번째 기간이 시작되는 것을 **눈으로 본다.**

```
1||Six months ended June 30, 2025
2||Ordinary Shares||||Accumulated|||Non-redeemable
3||Issued and||Treasury|Additional|Other||Total equity|non-
4||Outstanding||shares at|Paid-In|Comprehensive|Retained|attributable to|controlling|Total
5||Shares|Amount|cost|Capital|Loss|Earnings|Nebius Group N.V.|interests|Equity
6|Balance as of December 31, 2024|235,753,600|9.2|(1,968.1)|2,016.7|(22.1)|3,218.0|3,253.7|—|3,253.7
7|Net income|—|—|—|—|—|470.9|470.9|—|470.9
```

**격자만으로는 복원되지 않는 정보가 하나 있다** [X]: `FY2025`가 두 열을 span하고 아래에 `Shares|Amount`가 있으면 원점 문자열만으로는 첫 행이 두 열을 포괄한다는 사실이 사라진다. 따라서 **비단위 span은 보조 메타데이터로 남긴다.** 접힌 span 폭은 원래 점유 구간과 `kept_columns`의 교집합 크기로 계산한다. 헤더 판정은 여전히 필요 없다.

### 표에는 의미 구조가 사실상 없다 [C]

측정한 3사 모두 `<th>` **0개**, `scope` **0개**, `headers` **0개**, `<caption>` **0개**.

> **범위 제한** [X]: 측정한 3개 문서에서 없었다는 것이 **전체 SEC 문서에서 죽은 필드라는 증명은 아니다.** 기본 출력의 빈 필드는 제거하되, **실제 존재하는 원문 선언은 선택적 관측으로 보존**한다. 추론된 첫 행 `header`와 원문 `<th>`를 같은 이름으로 취급하지 않는다.

### 중첩 표는 실제로 존재한다 [X]

측정 3사와 Apple 2024·Microsoft 2026에는 없었으나 로컬 EDGAR 자료에는 있다 — Apple `R7.htm`은 표 69개 중 **중첩 34개**, 13F 정보표는 4개 중 2개. 현재 `_dom_text()`(`document.py:41`)는 **자식 표의 텍스트를 부모 셀에 합치고** 기존 합성 테스트가 부모 셀 `"10 20 30 40"`을 요구한다. 새 모델에서 이 중복을 없애야 한다.

### 표 크기 분포 (격자 환산) [C]

| | 표 수 | 격자 총합 | ≤300자 | 301~3000 | >3000 | 최대 | 중앙값 |
|---|---|---|---|---|---|---|---|
| NBIS | 79 | 33,510 | 51 | 27 | 1 | 3,310 | 235 |
| AAPL | 62 | 37,466 | 25 | 35 | 2 | 4,199 | 385 |
| MRVL | 55 | 36,982 | 16 | 39 | 0 | 2,970 | 388 |

표 **전부**를 한 줄 요약(id, 행×열, context 60자)으로 나열해도 AAPL 3,455 / NBIS 4,672 / MRVL 3,160자 — 예산 12,000의 26~39%. AAPL `table-0`~`table-3`은 값 있는 셀이 0이라 격자 환산 `0×0`으로 **저절로 드러난다**(표지 레이아웃 표).

> **정정** [X]: 외부 세션이 보고한 `tables: 20 vs 24` 불일치는 **오진이다.** 최종 `open`이 누락 여부를 재계산한다. 진짜 문제는 `summary()`(`document.py:31`)가 먼저 20개로 자르기 때문에 **`--limit 100`이 무력**하고, schema가 두 필드를 `tables` 설명 안에서만 언급한다는 것이다.

### edgartools 비용 [C]

`import edgar.documents` = **warm 캐시에서도 23초**, 그중 pandas 14.2초. `edgar/__init__`이 `edgar._filings`를 타고 pandas 전체를 로드하므로 서브모듈만 import하는 우회가 불가능하다. 실제 파싱 작업은 0.48초, edgar를 타지 않는 명령(`filings`/`find`/`read`) 전체가 0.48초. 현재 lock은 **51개**(직접 의존성 5개 + dev 2개의 전이 폐쇄). 내가 처음 쓴 125는 lock의 의존성 참조 줄까지 센 계수 오류다.

쓰이는 곳은 세 군데지만 **import는 네 군데**다 [X] — `parse_document()` 안의 `from edgar.exceptions import ParsingError`를 남기면 HTML뿐 아니라 XML·SGML·텍스트·unsupported 파싱 경로 전부에 영향이 남는다.

### 강조 탐지 — SDK는 정답이 아니다 [X]

3사 모두 `<h1>`~`<h6>` **0개** [C]. 픽스처 실측:

| 픽스처 | h1~h6 | 실제 강조 표현 |
|---|---|---|
| Apple 2024 | 0 | `font-weight:700` 403곳, italic 84, 밑줄 256. 본문 대표 **9pt** |
| Microsoft 2026 | 0 | `font-weight:bold` 3,236곳, italic 96, 밑줄 154. 본문 대표 **10pt** |
| ASML | 0 | `<font>` 12개, 1pt 텍스트와 **이미지 중심**. 강조 후보 0 |

세 픽스처 모두 `<b>/<strong>/<em>`과 `<style>`이 **0개**. Microsoft에 class 속성은 있으나 내장 CSS 없음 → **태그·CSS class 기반 탐지는 이번 원본으로 미검증.**

코덱스 프로토타입의 단계별 축소:

| 단계 | Apple | Microsoft |
|---|---|---|
| 강조 신호가 있는 블록 | 528 | 889 |
| 강조가 블록의 80% 이상 | 523 | 842 |
| 표 밖 | 226 | 363 |
| **강한 항해 신호를 가진 발생 위치** | 53 | 163 |
| **동일 문구를 묶은 항해 항목** | **53** | **63** |

규칙: 표 밖 + 링크비율<80% + (강조된 `Item`/`Part`/`Note` 번호 패턴 | h태그 | 본문 대표 크기의 1.15배 이상이 80% 이상 | 전체 대문자 & bold 80% 이상).

**SDK 일치율**: 정확일치 Apple **54/87**, MSFT **29/105**. 후보 블록 안 포함까지 세면 **64/87, 79/105**. SDK에는 `ITEM 1. B`, `ITEM 1A. RIS` 같은 **잘린 문자열**과 오판(`TM`, `adopted a policy requiring`)이 섞여 있다.

> **판정 기준 정정.** 초안의 "edgartools 대비 recall ≥95%"는 **달성 불가능할 뿐 아니라 틀린 기준**이다. 정답이 아닌 것을 정답으로 삼았다. 「검증」의 구조적 도달성으로 대체한다.

주의 [X]: Microsoft의 `PART I` 30회·`PART II` 60회는 반복 페이지 머리말이다. **묶되 발생 위치는 보존**해야 한다 — 전역 문자열 set으로 지우면 같은 제목의 서로 다른 절(두 감사보고서, 여러 `Competition`)에 접근할 수 없다. 그리고 Apple에서 **180자 길이 제한은 표 밖 강조 블록 15개를 제외**했고 거기에 실제 위험요인 강조문이 포함된다 — 길이로 관측을 버리지 않는다.

### SGML [X]

`old.txt` 실측: 10,112바이트, 문서 2개(`1/24F-2NT`, `2/EX-99.11`). **두 문서 모두 `<FILENAME>` 없음**, `<DESCRIPTION>`은 존재. SDK도 filename을 빈 문자열로 반환. **`<FILENAME>` 필수화는 역사 공시를 즉시 깨뜨린다.** 줄 기반 상태 기계로 문서 2개를 복원했고 조각을 합친 디코딩 문자열이 원문과 완전히 일치했다.

기존 비탐욕 정규식은 본문에 나타나는 `</DOCUMENT>` 문자열에서 일찍 끝날 수 있다. 그리고 ASML 원본처럼 **단일 `<DOCUMENT>` wrapper 안에 HTML이 있는 경우** `<DOCUMENT>` 발견만으로 SGML 처리하면 이미지 12개를 노출하는 기존 동작이 깨진다.

### 색인 첨부표 [X]

직접 파싱이 **SDK 결과와 전부 일치**했다.

| 픽스처 | 행 | 빈 sequence/type | 빈 description | iXBRL 링크 | SDK 일치 |
|---|---|---|---|---|---|
| `filing-index.html` | 12+6 = 18 | 각 1 | 0 | 0 | 18행 전부 |
| `apple-index-live.html` | 18+6 = 24 | 각 1 | 4 | 1 | 24행 전부 |

6개 필드(`sequence_number`, `document`, `description`, `document_type`, `size`, `url`)와 행 순서까지 일치. 빈 sequence/type인 **Complete submission text file** 행을 버리면 안 되고, Document 셀에는 `iXBRL` 배지가 붙으므로 파일명은 링크에서 읽어야 한다. `/ix?doc=` 처리는 이미 있는 `transport.validate_url()`을 재사용한다. 열 순서 변경·4/6열 색인·중복 행은 **미검증**.

### 모듈 이름이 표준 라이브러리를 가린다 [X]+[C]

`Scripts/sec.py`를 직접 실행하는 구조에서는 `Scripts/`가 `sys.path[0]`이라 **`html.py`가 표준 라이브러리 `html`보다 먼저 발견된다.** 유지할 의존성 `bs4/dammit.py`가 `html.entities`를 import하므로 CLI가 기동 자체를 못 한다. 격리 환경에서 재현 [C]:

```
FAIL: ModuleNotFoundError No module named 'html.entities'; 'html' is not a package
```

`xml.py`도 같다(`lxml`은 별개지만 `xml.etree` 등을 쓰는 경로가 가려진다). 따라서 모듈명을 `markup.py`·`records.py`·`submission.py`로 정한다.

### 기타 확정 결함

- **`read`의 "본문 비율"은 결함을 못 잡는 지표다** [C]. 직전 점검의 21%를 재측정 없이 인용했으나 현재 실측은 AAPL **90%**, NBIS **81%**로 이미 높다. 그런데 재무제표 안(`1740:0`~`1800:0`)을 읽으면 본문 280자·60줄 중 **48%가 불가시 문자만, 95%가 8자 이하 조각**이다. 비율은 합격인데 내용은 못 읽는다 — 지표를 **조각 비율**로 바꾼다
- `search --json` 항목이 EDGAR 원시 히트 — `_index`, `_score`, `sort`, `xsl`, `film_num`, `sics`, `biz_states`, `inc_states`, `file_num`. 쓸 필드 6개에 ~700자. 텍스트 모드도 같다 [C]
- 텍스트 모드가 `find`/`outline`/`links`/`table`에서 **한 줄 JSON** [C]. 직전 점검 D3이 `read`만 고쳐졌다
- `find --json`에 매치 총수 없음 [C]
- **`schema COMMAND` 11개 전부에 `recovery`·`global_options`가 없다** [X]. `read` 4,753자, `table` 4,792자, `search` 5,034자이며 `reading.items` 한 문자열에 5개 명령 설명이 합쳐져 있다 → "계약은 schema가 소유한다"는 본문을 유지하려면 이것부터 고쳐야 한다
- **"context/caption/footnotes always accompany"가 사실이 아니다** [X]. 본문 앞 레코드로 넣어 함께 페이징하므로 **후속 페이지에는 없다**(`reader.py:89-103,136,203,295-301`)
- **저장 snapshot에 `fetched_at`과 응답 헤더가 없다** [X]. schema는 약속하는데 저장에는 URL·sha256만 남고 `open`만 일시적으로 덮어쓴다(`document.py:360`, `filings.py:394`)
- **텍스트 예산을 JSON 크기로 계산한다** [X]. 격자가 작아져도 JSON 구조 비용 때문에 먼저 잘린다(`reader.py:150,204-209` vs `output.py:42-46`)
- **`extraction_complete = not warnings`는 과한 이름** [X]. warning 부재가 누락 부재의 증명이 아니다
- `rowspan=0`을 `len(rows)`까지 확장하는 현재 구현은 **여러 `tbody`에서 경계를 넘는다** [X]. span 충돌도 시작 열만 검사해 덮어쓸 수 있다(`document.py:177`)
- 기준선: `97 passed, 1 skipped in 84s` [C] / 수집 98개 [X]. stderr 깨끗 [C]

---

## 네 프레임이 결정한 것

| 프레임 | 결정 | 기각된 대안 |
|---|---|---|
| **principle over rail** | 헤더를 CLI가 판정하지 않고 격자 **관측**만 준다. 제목도 "강조 블록" 관측으로 노출한다 | `헤더=행2-5`로 단정 → 두 기간 스택 표에서 틀린 사실 180건 |
| **interface over document** | 형식별 차이는 `schema`가 소유하고 References 문서를 두지 않는다. 단 그러려면 **`schema`가 먼저 실제 계약이 되어야 한다** | SKILL.md에 "표 읽을 땐 헤더를 확인하라" 산문 추가 |
| **for user not developer** | 값마다 붙던 `column: 7`·`rowspan: 1`, 내부 페이징 사정(`tables_has_more`), position의 내부 문법 설명 제거 | 내부 모델을 그대로 노출 |
| **dense information** | table-7: 46K자·4회 → **2,086자·1회**. 표 목록은 전부 한 줄씩 | ZWSP만 고쳐 17,797자 |

**두 가지를 구별한다** [X]:

- **헤더를 추론하지 않는 것**과 **원문 헤더 선언을 버리는 것**은 다르다. 추론된 첫 행 `header`는 제거하되 실제 `<th>`·`scope`는 선택적 관측으로 보존한다.
- **"강조"도 추출 규칙을 숨기면 판정이다.** 길이·마침표로 후보를 걸러 놓고 단순 관측이라 부르면 제외된 강조가 보이지 않는다. `schema`에 관측 범위를 명시하고 자동 섹션 경계로 쓰지 않는다.

### 확정된 설계 결정 8개

1. **범위** — 읽기 계층(`document.py` 395 + `reader.py` 301 + `output.py` 46) 재작성. **"읽기 계층만"이라는 말은 정확하지 않다** [X]: `company`의 총수 의미, `filings`의 projection, `search`의 제출자 묶음, `doctor`의 출력도 바뀌므로 이는 파일 분리가 아니라 **발견 계층의 공개 계약 변경**이다. 그래서 위 「공개 계약」이 각 필드와 변환 규칙을 정하고, 발견 cursor에도 version을 넣는다 — 정하지 않으면 "마감"이라는 이름으로 설계가 구현 중 확장된다. `transport.py`·`store.py`는 **파일을 유지**하되 snapshot이 transport의 `fetched_at`·`content-type`을 저장하도록 호출부를 바꾼다. 보존 범위는 **현재 transport가 수집하는 `content-type` 하나**다 — "응답 헤더 보존"은 모든 헤더를 뜻하지 않는다. 완료 판정은 줄 수가 아니라 「검증」의 도달성이다.
2. **헤더 판정 없음** — 격자 관측만. 잘릴 때 표의 **도입부 행을 `context_rows`로 동반**하되, `header`라고 부르지 않는다. **"항상 충분히 동반한다"는 보장은 불가능하므로**(기간이 세로로 쌓인 표에서 맨 앞 도입부는 뒤 기간을 설명하지 못한다) `context_truncated`와 추가 읽기 위치를 노출한다.
3. **격자 표기 = 파이프 무패딩** — 빈 열은 **표 전체 기준**으로 접는다(페이지마다 열이 움직이면 비교가 깨진다). 중간 빈칸은 연속 파이프로 남긴다. **비단위 span은 보조 메타데이터로 보존**한다. 셀 안의 실제 `|`·개행은 텍스트 출력에서 escape하고 JSON에는 원래 문자를 둔다. `0×0`도 삭제하지 않고 식별 가능하게 둔다.
4. **edgartools 제거** — 제목은 "강조 블록" 관측으로 노출하되 **위치와 근거**(`bold_fraction`, `font_size_ratio`, `alignment`, `table_id`)를 동반한다. 임의의 제목 레벨은 만들지 않는다. SGML·색인 파서는 직접 구현.
5. **`read`가 표를 만나면 격자로 인라인 펼침** — `read`와 `table`이 **같은 격자 표현**을 쓴다. 단 셀 중간 position에서 시작하거나 표 중간에서 끝낼 때 **전체 표를 강제로 펼치지 않는다**(범위 계약 위반). 선택 범위와 재첨부 문맥을 구분한다.
6. **위치는 불투명 유지**(`fp:block:offset`) + `find`가 셀 매치 시 `table_id`·`row`, 가능하면 `column`을 동반한다. 중첩 문단 속 매치도 같은 셀로 연결하고, **여러 셀·행에 걸친 매치를 한 행으로 축약하지 않는다**.
7. **References 문서 없음** — SKILL.md + 자기서술 CLI. 단 **`schema COMMAND`의 `recovery`·`global_options` 누락을 먼저 해결**해야 이 결정이 성립한다.
8. **판정** — 「검증」 참조. 튜닝 문서와 판정 문서를 분리한다.

---

## 목표 디렉터리 구조

```
.claude/skills/sec/
  SKILL.md                판단만. 계약은 schema가 소유
  Scripts/
    sec.py                CLI 표면: 인자 정의, schema 생성, 오류 봉투
    output.py             텍스트·JSON 렌더러 (모든 명령, 예산 측정의 단일 기준) [재작성]
    transport.py          식별된 HTTPS 경계                                     [유지]
    store.py              내용주소 저장 + 프로세스 공유 요청 스케줄              [유지]
    discover.py           company / filings / search                [filings.py에서 분리]
    index.py              open 색인 + 첨부표 파싱                    [분리 + edgartools 대체]
    snapshot.py           형식 판별·인코딩·정규화·provenance·저장/로드  [document.py 재작성]
    markup.py             HTML → 블록 + 강조 관측 + 표                [document.py 재작성]
    grid.py               표 → 격자 (span 점유, 전체 기준 열 접기)      [신규]
    records.py            XML 경로·속성 (Form 4 등)                     [분리]
    submission.py         SGML 제출 문서 경계 (줄 기반 상태 기계)   [분리 + edgartools 대체]
    reader.py             예산 페이징 + outline/find/read/table/links    [재작성]
    pyproject.toml
    uv.lock
tests/sec/
    conftest.py
    test_cli.py           인자·오류 봉투·schema 완결성
    test_discover.py      company/filings/search
    test_index.py         색인·첨부표
    test_snapshot.py      형식 판별·인코딩·정규화·provenance
    test_markup.py        블록·강조 관측·표 추출
    test_grid.py          span 점유·전체 기준 열 접기·격자 렌더·중첩 표
    test_submission.py    문서 경계 (FILENAME 없는 경우 포함)
    test_reader.py        예산 페이징·context_rows·위치 안정성
    test_output.py        텍스트 렌더러·예산 단일 기준
    test_live.py          (live 마커)
    fixtures/             기존 + NBIS·MRVL(gz) + 홈드아웃
```

직접 의존성은 **4개**로 줄인다 [X] — `python-dotenv`, `httpx`, `lxml`, `beautifulsoup4`(`UnicodeDammit`). 이들의 **전이 폐쇄는 11개**다(실측: anyio, beautifulsoup4, certifi, h11, httpcore, httpx, idna, lxml, python-dotenv, soupsieve, typing-extensions). 현재 lock은 51개. CSS class 기반 스타일시트까지 지원하게 되면 자체 CSS 파서 대신 `tinycss2`/`cssselect2`를 명시적으로 추가한다.

---

## 저장 표현 (격자 모델)

```text
block:  kind, text, table_id, url
table:  table_id, block, parent_table_id, parent_cell
        original_rows, original_columns, kept_columns, row_ranges
        cells: row, column, rowspan, colspan, text_start, text_end,
               th?, scope?,                       # 원문 선언이 있을 때만
               parts?,                            # text → child_table_ref → text 조각 목록
               nonempty_reason?                   # image | child_table (문자열이 없어도 빈 칸이 아님)
        context/caption/footnote/link 참조
```

- `block.text`는 **접힌 격자의 canonical text**다. 셀 경계는 탭, 행 경계는 줄바꿈으로 고정한다. 파이프 문자열은 **출력할 때 조립**한다 — 파이프 출력 자체를 검색 원본으로 삼으면 escape 변경만으로 위치가 바뀐다.
- 문자열은 **원점 셀에 한 번만** 저장한다. `(r,c,rowspan,colspan)` 직사각형에는 **소유권**만 기록한다. rowspan 값을 복제하면 검색 건수와 관측값이 늘어난다.
- `row_ranges`는 원래 행 번호와 canonical 구간을 연결한다. 빈 행 때문에 재번호를 매기지 않는다.
- `find`는 canonical text를 검색하고 매치 offset을 `row_ranges`·셀 구간에 대조해 `table_id`·원래 `row`를 붙인다. **문자열 생성과 위치 매핑은 반드시 같은 정규화 경로를 쓴다** — 다르면 U+200B 제거 이후 모든 위치가 밀린다.
- context·도입부·rowspan 문자열을 canonical에 **반복 삽입하지 않는다**. 원문에 한 번 있는 문구가 여러 검색 결과가 된다.
- 빈 표도 블록과 ID를 남긴다. 없애면 anchor가 다음 산문으로 잘못 이동한다.
- **빈 열 판정은 문자열만으로 하지 않는다.** 이미지나 자식 표를 가진 셀은 `nonempty_reason`을 달아 비어 있지 않은 것으로 센다 — 문자열만 보면 이미지 전용 열이 사라진다.
- **`parts`와 canonical의 대응**: 부모 셀의 canonical 문자열은 조각들의 **텍스트 부분만** 이어붙인 것이고, 자식 참조 자리에는 **검색 경계 문자**(행 구분과 같은 `\n`)를 둔다 — 없으면 자식 표 앞뒤의 부모 텍스트가 이어져 **원문에 없는 문장이 검색에 잡힌다.** 각 `part`는 `{kind: text|child_table, text_start, text_end | child_table_id}`다.
- **이미지 전용 셀**은 `nonempty_reason: image`와 함께 그 이미지의 `links` 항목 id를 싣는다 — `links --kind image`로 실제 URL에 도달할 수 있어야 관측이 쓸모를 가진다.
- **중첩 표의 읽기 순서**: 자식 블록은 부모 블록 **다음에** 자식들의 DOM 순서로 놓는다. `read`는 부모 격자의 참조 표시(`[table-12 → r3c1]`) 뒤에 자식 격자를 펼치고 `parent_table_id`와 부모 행·열을 함께 표시한다. 이 평탄한 순서는 브라우저 표시 순서와 다르므로 **참조 표시가 그 차이를 보존한다** — 자식 표를 독립 산문처럼 내보내면 검색상 존재하지 않는 문장이 이어진다.
- 중첩 표: 모든 표에 독립 ID·블록. 부모 셀은 `text → child_table_ref → text` 조각 목록으로 보존하고 **자식 문자열을 부모 canonical에 복사하지 않는다.**
- **`rowspan=0`은 정상 입력이다** — 해당 행 그룹(`tbody`/`thead`/`tfoot`)의 남은 행까지를 뜻한다. 현재 구현의 `len(rows)`까지 확장은 여러 `tbody`에서 경계를 넘는다. 명시적 그룹이 없는 행은 하나의 암묵 그룹으로 본다. **오류로 보고할 대상은 span 직사각형의 실제 충돌과 범위 이상뿐이다.**
- span 충돌을 조용히 덮어쓰거나 옆으로 옮기지 않는다(현재 `document.py:177`은 시작 열만 검사한다). 거대 span에 dense 배열을 먼저 할당하지 말고 구간으로 계산하며, 자원 한도를 넘으면 명시적으로 실패한다.

**`snapshot version`을 1→2로 올린다.** `fp:block:offset` 문법은 유지하되 v1 레코드를 만나면 `unsupported_snapshot_version`과 재열기 안내를 반환한다 — 옛 block 번호에 새 의미를 부여하면 **에러 없이 다른 문단을 인용**하게 된다. cursor query version도 함께 올리고, 출력 모드가 페이지 경계에 영향을 주면 그 모드도 query에 포함한다.

**도입부 행 수는 예산으로 정한다** — envelope과 **본문 최소 진행량을 먼저 확보한 뒤** 남은 예산의 절반을 상한으로 두고, 표 시작부터 들어가는 가장 긴 연속 행 prefix를 동반한다(아래 「페이징 불변식」의 우선순위 사다리). 남은 몫은 본문에 돌린다. 이 비율은 **출력 예산 정책이지 헤더 추정 규칙이 아니다.** `next_position`은 항상 **아직 읽지 않은 본문**을 가리킨다 — 도입부를 반복했다고 앞 행으로 돌아가지 않는다.

---

## 공개 계약

계약의 진실은 `--help`와 `schema`가 소유한다. 아래는 **무엇이 바뀌는지**의 목록이지 계약의 사본이 아니다.

| 명령 | 제거·교정 | 추가·명시 |
|---|---|---|
| `company` | 후보 수처럼 보이는 `total` 교정. 모든 query에 붙는 공통 설명 제거 | 이름 검색 총수가 **공시 히트 수**임을 필드명으로 표현 |
| `filings` | submissions 원시 행 전체 노출, `isXBRL` 등 판단에 불필요한 필드 | accession·CIK·양식·제출일·보고일·문서명·URL의 명시적 구조. 보고일 없는 행의 필터 처리 |
| `search` | `_index`/`_score`/`sort`/`xsl`/`film_num`/`sics`/`biz_states`/`inc_states` 원시 덤프 | accession+filename 문서 정체성, **제출자별 `{cik, name, document_url}` 묶음**, 원격 total과 로컬 필터·중복제거 후 반환 수의 구별. 제외 사실을 schema에 명시 |
| `open` | 숨은 20개 상한(`--limit`을 무력화). `tables_has_more` | 표 **전 항목** `{table_id, rows, columns, context}`. `columns`는 접은 뒤 수라 `0×0`이 레이아웃 표를 드러낸다. index/document/unsupported 결과 유형 구분 |
| `outline` | 추론된 첫 행 `header`. 강조를 확정 `heading`으로 가장하는 것 | `emphasis` — 관측 종류·텍스트·위치 + **근거**(bold비율·크기비·정렬·table_id). 표 내부/외부 선택. **링크 타깃 보존을 제목 탐지 성공 여부에서 분리** |
| `find` | 앞뒤 60/100자 고정 스니펫을 표 문맥의 대체물로 쓰는 것 | **전체 매치 수**와 이번 반환 수. `table_id`·`row`·가능하면 `column`. 여러 블록에 걸친 매치 표시. 텍스트 모드도 같은 위치 정보 |
| `read` | 텍스트 모드가 표·위치 정보를 버리는 동작. 산문에서 `items`와 `text` 중복 | 구조가 보이는 인라인 격자, 선택 범위와 재첨부 문맥 구분, 표 내부에서 재개 가능한 위치 |
| `table` | 셀별 `column`·`colspan`·`rowspan`·빈 `header`/`scope`/`headers`. "context/caption/footnotes always accompany" 과장 | 전체 표 기준 열 접기, 원래 행·열 대응, spans, **0-based·양끝 포함** 행 범위, 조각난 셀·행 상태, `context_rows`의 실제 범위와 `context_truncated` |
| `links` | 한 줄 JSON 렌더링 | 링크 출현 위치와 타깃 위치의 구분, 표 내부 링크에 표·셀 위치 연결 |
| `doctor` | `{identity_configured:true}`를 전체 진단으로 간주하는 것 | 설정 없음/잘못됨의 오류·복구, live/non-live 출력 구조, exit code |
| `schema` | `reading.items` 한 문자열에 5개 명령을 합친 설명, 무관한 defaults, 의미 없는 `supported:true` | **명령별 `recovery`·`global_options`·exit code**, 출력 구조·타입·nullable·조건부 필드, 새 계약 version |

### 새 동작의 좌표계와 대표 출력 (여기서 확정한다)

schema가 계약을 소유하지만 **schema를 쓸 사람이 다음 구현자**이므로, 새로 생기는 동작의 좌표계·필드·범위 의미는 이 문서가 정한다.

- **좌표계는 하나다: 원래 행·열 번호.** 접힌 열 번호는 출력에 등장하지 않는다. `kept_columns`는 원래 열 번호의 목록이다. **`colspan`/`rowspan`은 원문 그대로의 값**이고, `spans`의 `w`는 **접힌 폭**(`원래 점유 구간 ∩ kept_columns`의 크기)이다 — 둘은 다른 수이며 예시로 고정한다. 행 번호는 빈 행이 있어도 재번호를 매기지 않는다.
- **행 범위는 0-based·양끝 포함**이다(`--rows 2-5`는 2,3,4,5).
- **텍스트 격자 한 줄** = `원래행번호 | 셀 | 셀 …`. 빈 칸은 연속 파이프. 셀 안의 실제 `|`·개행·백슬래시는 `\|`·`\n`·`\\`로 escape한다. **escape와 행 번호는 position offset에 포함하지 않는다.**
- **JSON 격자** = `{table_id, kept_columns, rows:[{row, cells:[{column, text, colspan?, rowspan?, th?, fragment?}]}], spans, context_rows, footnotes, caption}`. `colspan`/`rowspan`은 1이 아닐 때만, `th`는 원문 `<th>`일 때만 실린다. JSON에는 원래 문자를 그대로 둔다.
- **조각 상태는 네 가지를 구별한다.** 셀: `fragment:{offset, text_complete}` — `offset`은 **셀 문자열 안의 시작 위치**다. 완전한 셀은 `fragment`가 없고, 앞 페이지에서 이어진 마지막 조각은 `offset>0`이면서 `text_complete:true`다. 행: `row_complete`(이 페이지에서 행이 끝났나)와 `row_started_before`(앞 페이지에서 시작했나). 각 셀이 완전해도 행은 불완전할 수 있다.
- **`spans` 원소** = `{row, column, colspan, rowspan, w}` — `colspan`/`rowspan`은 원문 값, `w`는 접힌 폭. `rowspan=0`은 **원문 값 0과 유효 높이를 둘 다** 싣는다(`rowspan:0, effective_rows:n`) — 원문을 지우면 입력을 잃고, 유효 높이를 빼면 읽는 쪽이 계산할 수 없다. 선택 범위 **밖에서 시작한 rowspan**은 `starts_before: true`로 표시한다.
- **`find`의 셀 매치**는 `{position, match_end, table_id, row, column}`. 여러 셀·행에 걸친 매치는 `row_end`/`column_end`를, 여러 표·블록을 가로지르면 `table_id_end`를 실어 **한 행으로 축약하지 않는다.**
- **`outline`의 강조 필터**: `--kind emphasis`가 항해층, `--all`이 관측층. 표 안/밖은 `--in-tables`(`only`/`exclude`, 기본은 둘 다)로 고른다.
- **`emphasis` 항목** = `{text, occurrences:[{position, signals:{bold_fraction, font_size_ratio, alignment, all_caps}, table_id?}]}`. **`signals`는 발생 위치마다 보존한다** — 같은 문구가 한 곳에서는 bold이고 다른 곳에서는 링크나 표 안일 수 있어, 그룹 전체에 근거 하나를 달면 관측을 합치면서 사실이 바뀐다. 그룹화 키는 정규화된 텍스트다. 임의의 제목 레벨은 만들지 않는다.

예시 — `table <s> table-7 --rows 5-7`:

```
table-7 | 원래 32행 × 19열 | kept_columns 0,1,3,5,7,9,11,13,15,17
context: (In millions of U.S. dollars ("$"), except share and per share data)
context_rows: 1-4 (context_truncated: false)
spans: r1c1 colspan=17 w=9 | r2c1 colspan=3 w=2 | r3c1 colspan=3 w=2 | r4c1 colspan=3 w=2

 5||Shares|Amount|cost|Capital|Loss|Earnings|Nebius Group N.V.|interests|Equity
 6|Balance as of December 31, 2024|235,753,600|9.2|(1,968.1)|2,016.7|(22.1)|3,218.0|3,253.7|—|3,253.7
 7|Net income|—|—|—|—|—|470.9|470.9|—|470.9
```

### 강조 관측의 두 층 (여기서 확정한다)

"schema에 명시하라"로 남기면 구현 중에 설계를 새로 하게 된다. 규칙을 여기서 정한다.

- **관측층** — 강조 신호가 있는 모든 블록. `--kind emphasis --all`로 조회한다. 실측 규모: Apple 528, Microsoft 889 [X].
  - 신호는 **텍스트 조각에서 수집**한다: inline `font-weight`(숫자·bold·bolder), `font-size`, `text-align`, `font-style`, 밑줄, 그리고 태그 `<b>`/`<strong>`/`<i>`/`<em>`/`<u>`/`<font size>`. 상속과 재정의를 반영하고 **부모와 자식의 같은 내용을 중복 집계하지 않는다**(Microsoft처럼 span이 잘게 나뉘면 폭증한다).
  - **h1~h6 태그는 inline 스타일이 없어도 관측층에 들어간다.** 측정한 세 문서에 h 태그가 0개라 실전에서 드물 뿐, 있으면 그 자체가 강조 선언이다(현재 `document.py:123`도 그렇게 한다).
  - **본문 대표 글자 크기**는 **표 밖이고 200자 이상인 블록**을 글자 수로 가중한 중앙값이다. 고정 "12pt 이상"은 쓰지 않는다 — Apple 본문 9pt, Microsoft 10pt [X]. **그런 블록이 없으면**(짧은 문서, 이미지 중심) 크기 신호를 쓰지 않고 나머지 신호로만 판정하며 `font_size_ratio`는 `null`이다.
  - **CSS class 기반 스타일시트는 미지원**이다. 측정한 세 픽스처에 내장 `<style>`이 0개라 검증할 수 없었다 [X]. 미지원 사실을 schema가 말한다. 지원이 필요해지면 자체 CSS 파서 대신 `tinycss2`/`cssselect2`를 추가한다.
- **항해층** — `--kind emphasis`의 기본. 관측층에서 다음으로 고른다. 실측 규모: Apple 53, Microsoft 63 [X].
  - 표 밖이고, 링크 비율 80% 미만이며, 다음 중 하나: 강조된 `Item`/`Part`/`Note` 번호 패턴 · h 태그 · 본문 대표 크기의 1.15배 이상인 글자가 80% 이상 · 전체 대문자이면서 bold 80% 이상.
  - **길이·마침표로 관측을 버리지 않는다.** Apple에서 180자 제한은 표 밖 강조 블록 15개를 제외했고 거기에 실제 위험요인 강조문이 있었다 [X].
  - **표 안 강조는 표에 귀속**한다. 셀마다 전역 항목을 만들지 않고 `table_id`와 행으로 연결한다.
- **`--in-tables`는 `--all`에만 의미가 있다.** 항해층은 정의상 표 밖이므로 `--kind emphasis`와 `--in-tables only`를 함께 주면 빈 결과가 아니라 `invalid_argument`로 그 사실을 말한다 — 빈 결과는 "표 안에 강조가 없다"로 읽힌다.
- **승격 규칙은 두지 않는다.** "강한 후보가 없는 구간에 약한 후보를 대표로 올린다"는 구간 경계와 대표 기준을 새로 발명해야 하고, 그 둘 다 근거가 없다. 대신 **모델이 `--all`로 내려간다** — 항해층이 비면 그 사실 자체가 관측이고, 무엇을 볼지는 모델이 정한다.

### 발견 계층의 projection (여기서 확정한다)

| 명령 | 반환 필드 | 누락·불일치 처리 |
|---|---|---|
| `company` | `{cik, name, tickers, match}` + `filing_hits`(이름 검색 총수 — **후보 수가 아니다**. `total`에서 개명) | `ciks`와 `display_names` 길이 불일치는 **오류**(현재 `strict=True`와 같다) |
| 공통 | — | SEC가 주지 않은 필드는 **`null`로 싣고 키를 지우지 않는다** — 키가 사라지면 "원래 없는 것"과 "이번에 안 온 것"을 구별할 수 없다 |
| `filings` | `{accession, cik, form, filing_date, report_date, primary_document, index_url, document_url, items}` | `report_date`가 빈 행은 보고일 필터에 **매치하지 않는다**(현재 동작 유지). 나머지 submissions 원시 필드는 제외 |
| `search` | `{accession, form, file_type, file_date, period_ending, document, filers:[{cik, name, document_url}]}` — 제출자마다 URL이 하나씩 나오므로 **묶는다**. 별도 `document_urls` 배열은 두지 않는다 | 제출자 배열 길이 불일치는 **오류**. `_index`·`_score`·`sort`·`xsl`·`film_num`·`sics`·`biz_states`·`inc_states`는 SEC 검색 인프라 내부이므로 제외하고, 제외 사실을 schema가 말한다 |
| `doctor` | `{identity_configured, identity_source, connection, requests_per_second, cache_dir, snapshot_version}` + exit code | **설정 없음** → `identity_configured:false, identity_source:null`. **형식 오류** → `identity_configured:false, identity_source:"<파일 경로>"`. 둘 다 `identity_required` 오류와 exit 2. `--live` 연결 실패는 `connection:"failed"` + 해당 오류 코드 + exit 2. identity 값 자체는 어느 경우에도 출력하지 않는다 |

### 페이징 불변식 (구현이 먼저 고정할 것)

`next_position`이 뒤로 가지 않는 것만으로는 누락도 무진행 반복도 못 잡는다. 다음을 **테스트로 고정**한다:

1. **재조립 동일성** — 선택 범위를 여러 페이지로 읽어 이어붙이면 누락·중복 없이 같은 canonical 구간이 된다. 예산 1024·12000·24000과 텍스트·JSON 두 모드 전부에서.
2. **유한 완료** — 진행이 가능한 예산에서는 유한 번에 `scope_complete`에 도달하고, 진행이 불가능한 예산에서는 **첫 호출에서** `budget_too_small`로 유한하게 실패한다. 진행량 0으로 같은 위치를 반복하는 응답은 두 경우 모두 금지다.
3. **왕복** — `find`가 준 위치로 `read`하면 그 매치가 반환 범위 안에 있다. 매치가 한 페이지보다 길면 **continuation 전체**를 이어붙인 범위 기준으로 판정한다.
4. 남은 페이지에만 못 들어가는 행은 **다음 페이지로**, 빈 페이지에도 못 들어가는 행은 **셀 내부에서 분할**한다.
5. **예산 배분은 하나의 우선순위 사다리다.** 높은 것부터 채우고, 낮은 것이 못 들어가는 일은 실패가 아니다.

   | 순위 | 무엇 | 못 들어가면 |
   |---|---|---|
   | 1 | envelope과 필수 메타데이터 | `budget_too_small` |
   | 2 | **본문 최소 진행량** — 한 행 전체, 그것도 안 되면 셀 조각 1자 | `budget_too_small` |
   | 3 | **도입부**(`context_rows`) — 남은 예산의 절반까지, 표 시작부터 연속으로 | 실패가 **아니다**. 들어가는 만큼만 싣는다 |

   **도입부는 어떤 경우에도 실패 사유가 아니다.** 1과 2가 들어가면 응답은 성공한다 — 도입부가 한 행도 못 들어가면 `context_rows: []`와 `context_truncated: true`, 첫 행이 통째로는 안 들어가고 조각만 들어가면 그 조각을 싣고 `context_truncated: true`. 문맥은 편의이고 본문이 일이다. 이 순서가 없으면 같은 예산에서 성공과 실패가 갈린다.

   `context_rows`는 **본문 진척량에 포함하지 않는다.** 본문과 겹치면 중복 반환하지 않는다. 한 페이지에서 여러 표를 만나면 **순차 배분**이다 — 먼저 만난 표부터 순위 3을 적용하고, 남은 예산이 없으면 다음 표는 도입부 없이 간다. 균등 배분하지 않는 이유는 읽기 순서가 문서 순서이기 때문이다.

   **도입부 prefix에 목표 끝은 없다** — 예산이 허락하는 만큼이다. "헤더까지"라는 목표를 두면 헤더를 추론해야 한다.
6. **`context_truncated`의 뜻을 고정한다** — "표 시작부터의 연속 prefix가 예산으로 잘렸다". "필요한 문맥이 빠졌다"는 헤더를 추론하지 않고는 계산할 수 없으므로 주장하지 않는다. `context_next_position`으로 나머지를 읽을 수 있다.

### open의 예산 초과 계약

표를 **전부** 반환하는 것과 **유한 예산**과 **누락 상태 없음**은 동시에 약속할 수 없다. 측정한 세 문서가 26~39%에 들어온 것은 임의 문서나 `--max-chars 1024`의 근거가 아니다. 따라서 `tables_has_more`라는 **필드명**은 없애되 **누락 여부와 후속 경로**는 남긴다 — 표 목록은 `next_cursor`로 이어받고, 잘렸을 때 `outline --kind table`이 같은 목록을 준다는 것을 `fix`가 말한다.

**`--limit`의 적용 범위를 고정한다**: 색인 결과(첨부 행)에만 적용하며 기본 20을 유지한다. **문서 결과의 표 목록에는 적용하지 않는다** — 거기서는 예산과 `next_cursor`가 경계를 정한다. 지금은 `summary()`가 `--limit`보다 먼저 20으로 자르기 때문에 `--limit 100`이 무력한데, 두 결과 유형에 같은 인자가 다르게 작동하던 것을 갈라 놓는 것이다.

공통:

- `extraction_complete`를 **`known_extraction_limits`로 바꾼다**(문자열 배열). 빈 배열은 "알려진 제한이 없음"이고 **완전성의 보장이 아니다**. boolean `true`는 계속 완전성 보장처럼 읽히므로 값 타입까지 바꾼다. `scope_complete`(선택 범위 반환 완료)는 그대로 둔다 — 둘은 다른 질문이다.
- 원문 `<th>`·`scope`·`headers`는 **셀 레코드의 선택 필드로 보존**한다(있을 때만). 제거 대상은 **추론된 첫 행 `header`**와 항상 비어 있던 기본 출력 자리다. 둘을 같은 이름으로 부르지 않는다.
- `context`/`caption`/`footnote`는 **첫 페이지에만 싣고 이후 페이지는 `context_position`으로 참조**한다. 근거는 검색 건수가 아니라 예산이다 — 출력용 문맥은 애초에 canonical에 넣지 않으므로 반복해도 검색 건수는 늘지 않는다. 각각이 여러 개일 수 있으므로 `context_position`은 **목록**이다. 긴 각주·caption이 첫 페이지 예산을 넘으면 그 자리에서 조각으로 자르고 `context_next_position`으로 잇는다.
- **발견 계층 cursor에도 version을 넣는다.** 지금은 `filings.py:96-97`이 버전 없이 query를 만들고 `467-476`이 저장 결과를 그대로 재생하므로, reader cursor만 올리면 **옛 cursor가 원시 히트 형태를 다시 반환한다.** 계약이 바뀐 명령의 옛 cursor는 거부한다.
- 저장 snapshot에 `fetched_at`·응답 헤더 **provenance를 보존**한다.
- `returned_chars`와 예산 판정을 **출력 모드별 실제 렌더링 크기** 하나로 통일한다.
- position의 내부 숫자 문법(fingerprint 길이·block·offset)은 사용 계약에서 뺀다 — "반환값 그대로, 같은 snapshot에서만 유효"면 충분하다.

---

## SKILL.md 섹션 구조

줄 수는 합격 기준이 아니다(실측: SEC 46줄·5,139자, finviz 38줄·5,810자, yfinance 55줄·6,227자). 기준은 **구체적인 실패 형태**다.

| 섹션 | SKILL에 남길 것 | schema로 보낼 것 |
|---|---|---|
| frontmatter | 트리거·비트리거. **6-K 추가**(대표 실패 문서), yfinance와의 경계(구조화 재무 데이터 vs 원문 표·주석), "미국 기업 원문 공시" 범위를 `위험요인` 같은 의도어에 직접 부착 | — |
| 실행과 발견 | 설치 위치 기준 실행 명령, `${CLAUDE_SKILL_DIR}` 미치환, zsh 변수 함정, help/schema 진입점 | 인자·기본값·identity 설정·오류 복구 |
| 검색 결과에서 문서 고르기 | EFTS 한 히트에 **여러 제출자**가 붙고 **첨부가 직접 검색된다**는 실제 함정 | CIK·문서 URL 대응, 제출일·보고일 정의, 검색 기간·총수 |
| 원문 배치를 해석하기 | NBIS처럼 **한 표 안에서 기간이 세로로 다시 시작**하므로 표 전체에 하나의 열 의미를 고정하면 틀린다. SEC 표에는 `<th>`도 `<caption>`도 **없을 수 있고 측정한 문서에는 모두 없었다** — 원문 선언이 있으면 셀에 실려 오지만, 없으면 **어느 행이 헤더인지는 격자를 보고 네가 판단한다.** 연속 파이프는 원문의 빈 칸이다 | 격자 문법, 좌표·병합, `context_rows` 범위, `emphasis` 관측 정의, read/table 페이징 |
| 근거와 읽기 범위 | 로컬 위치를 SEC URL fragment로 착각하는 함정, 선택 범위 완료와 원문 추출 완료의 차이 | position 문법, 상태·warning 열거, PDF/XML/SGML 지원 범위, 원격 페이지 관측 시각 |

현재 SKILL.md에서 **탈락**(모델이 일반 역량으로 재도출 가능해 자리값을 못 함):

| 줄 | 문장 | 처리 |
|---|---|---|
| 10 | `Find the right EDGAR source…` | 삭제 — 목표 재진술 |
| 18 | `Their settings diagnosis…` | doctor/error로 이동 |
| 22 | `A name match is a candidate…` | 삭제 — `match`/`selection_required`가 이미 표현. 다중 제출자·첨부 함정만 남김 |
| 24 | `Submission date answers…` / `Report date describes…` | filings/search schema로 |
| 24 | `A request for the latest annual report…` / `Confirm the period…` / `An amendment is a separate filing…` | 삭제 — 앞 정의로 계산 가능하거나 일반 공시 지식 |
| 26 | `Full-text search coverage…` | search schema로 |
| 26 | `A missing search hit…` / `Use the supplied filing identifier…` | 삭제 — 일반적 검색 한계 |
| 30 | `Choose the next source…` | open/search schema로 |
| 30 | `Earnings releases, agreements…` / `Preserve the document's identity…` | 삭제 — 일반적 첨부 탐색 |
| 32 | `Use actual contents links…` | outline schema로 |
| 32 | `Repeated labels…` / `Read around a match…` | 삭제 — 일반적 독해 조언 |
| 36 | `Navigate with the returned snapshot…` | schema로. 로컬 위치≠원문 앵커 함정은 한 문장 유지 |
| 38 | `A table value needs…` / `Merged cells and nearby prose…` | 삭제 — 단위·헤더 확인 상식 |
| 38 | `Long cells continue…` / `Follow their remaining range…` | read/table schema로 |
| 40 | `Text extraction cannot establish…` | 삭제 — 일반적 시각자료 한계 |
| 40 | `Image and PDF links…` / `XML paths…` / `In a submission text file…` | 각 형식 schema로 |
| 44 | 두 문장 | 하나로 축약 — 선택 범위≠추출 완료만 |
| 46 | 세 문장 | search schema로 |

---

## TDD 단계와 완료 판정

각 단계는 `tdd` 스킬을 열고 시작한다. 단계마다 **실패 테스트 먼저**. 아래 수치는 **튜닝 문서**(NBIS·AAPL·MRVL) 기준이며 최종 판정은 「검증」의 홈드아웃으로 한다.

완료 판정을 쓸 때의 규칙: **정상 입력을 거부해도 통과하는 기준을 쓰지 않는다.** 정상 동작의 정확한 결과와 비정상 입력의 오류를 각각 고정한다.

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | 원본 고정 | NBIS·AAPL·MRVL의 **원문 URL·전체 SHA-256·픽스처 경로·취득 시각**을 `fixtures/provenance.json`에 기록. 원본 bytes와 v1 snapshot을 구별해 저장. 기존 Apple 픽스처는 **2024년 10-K**이고 장부 측정은 2025년이므로 수치를 섞지 않는다. 기존 97개 통과 |
| 1 | 정규화 (`snapshot.py`) | 공백·U+200B만인 셀이 **빈 셀로 판정**되고, 혼합 문자열(`foo\u200bbar`)은 **보존**된다. `—`/`–`/`-`/`−`/U+2011/괄호/쉼표/통화기호가 읽기 문자열에서 **문자 그대로**. 원본 bytes 보존과 읽기 문자열 보존을 **다른 테스트로** 고정. HTML 외 형식(XML 값·속성, SGML 원문)에는 적용하지 않음 |
| 2 | 격자 (`grid.py`) | **정상**: table-7이 원래 19열→`kept_columns [0,1,3,5,7,9,11,13,15,17]`·32행, 행 5의 라벨 9개가 행 6의 값 9개와 열 일치. `rowspan=0`이 해당 `tbody`의 남은 행으로 **정확히** 해석됨. 중첩 표가 독립 ID·블록으로 나오고 부모 canonical에 자식 문자열이 **없음**. 이미지·자식 표만 있는 셀이 빈 셀로 판정되지 **않음**. **비정상**: span 직사각형 충돌과 범위 이상이 구조 오류로 보고됨. 크기 측정은 **격자 본문만**(메타데이터 제외) ≤2,500자 |
| 3 | 블록 재정의 (`markup.py`) | **필수**: 원문의 **산문과 셀 내용이 모두** canonical에 한 번씩 존재(유실·중복 0). 비교는 정규화로 제거하는 레이아웃 문자를 양쪽에서 똑같이 걷어낸 뒤 하고, 중첩 셀의 **직접 소유 텍스트**만 부모에 센다, anchor·link 위치가 블록 재정의 전후로 같은 텍스트를 가리킴, 빈 표도 블록·ID 유지. **진단값**(합격 기준 아님): NBIS 5,591→413, AAPL 3,124→737, MRVL 3,532→925 |
| 4 | 강조 관측 (`markup.py`) | **각주 추출 회귀 금지** — 현재 `document.py:215-228`이 각주 대상 선정에 `heading` 판정을 직접 쓴다. `emphasis`로 바뀐 뒤에도 각주가 목차 항목이나 표 컨테이너를 삼키지 않음을 기존 경계 테스트(`test_contents_link_inside_a_table_is_navigation_not_a_footnote`, `test_footnote_is_the_note_beside_the_anchor_and_never_a_navigation_section`)로 고정. 문서별 **기대 위치 목록**을 먼저 독립 작성(Item·Part 경계, Note 번호). 그 전부가 `outline --kind emphasis`의 **기본 필터 전체 continuation** 안에서 도달. 같은 문구의 여러 발생 위치에 **각각** 도달. 관측마다 `signals` 동반. 길이 제한으로 관측을 버리지 않음. **적용 대상은 HTML 문서만**(XML·SGML·이미지 중심 문서는 제외하고 그 사실을 schema에 명시). CSS class 기반 스타일시트는 **미지원으로 명시** |
| 5 | edgartools 제거 | `import edgar`·배포 의존성 **부재**(`/Archives/edgar/` URL은 정상이므로 `grep edgar`로 판정하지 않는다). 직접 의존성 4개, **런타임 전이 폐쇄 11개 / lock 전체 19개**(dev의 pytest·ruff 폐쇄 7개 + 프로젝트 1). 런타임 폐쇄와 lock 전체를 섞지 않는다. **SGML**: `old.txt` 2문서가 `<FILENAME>` 없이 복원되고 조각 합계가 원문과 일치. 메타데이터를 `<TEXT>` 이전에서만 읽음. sequence 누락·중복이 문서를 덮어쓰지 않음. 불완전 종료를 조용히 버리지 않음. 문자 offset을 byte offset으로 쓰지 않음. ASML wrapper가 HTML 경로를 유지하고 **이미지 12개와 추출 제한 표시가 그대로**. `<TEXT>` 안에 종료 태그 묶음이 그대로 등장하는 **모호한 입력은 `parse_failed`로 명시적 실패**(상태 기계가 판별 가능하다고 주장하지 않는다). **색인**: 두 픽스처 42행이 6개 필드·행 순서까지 일치. 헤더명으로 열 대응. 빈 sequence/type의 Complete submission 행 보존. 직접 자식 행·셀만 사용. **중복 행 보존**(같은 sequence·URL이어도 지우지 않는다). 헤더보다 짧은 행은 **열 위치를 추측하지 않고 `parse_failed`**. Size 열 자체가 없는 구조는 `None`으로 표현. accession·제출자 CIK·첨부 URL 검증(현재 `filings.py:420-447`) 유지 |
| 6 | reader 재작성 | 「공개 계약」의 **페이징 불변식 6개** 전부. table-7을 `table` **1회**·격자 본문 ≤3,000자로 전부. `find "Issuance of pre-funded warrants"`가 준 위치에서 그 표 끝까지 `read`했을 때 **8자 이하 조각 줄 비율 ≤20%**(같은 구간의 현재 값 95%). **v1 블록 번호를 판정에 쓰지 않는다** — v1을 거부하기로 한 이상 옛 번호는 새 스냅샷에서 의미가 없고, 같은 구간은 내용 앵커로만 식별된다. 측정은 텍스트 모드·기본 예산 12,000, 분모는 본문의 비어 있지 않은 줄. v1 스냅샷에 `unsupported_snapshot_version`. 새 프로세스의 snapshot reload에서도 `fetched_at`·`content-type` provenance가 남음 |
| 7 | output 재작성 | 명령별로 **읽을 수 있는 출력**과 필수 위치·상태 보존을 검사(JSON에 줄바꿈만 넣은 것은 불합격). `returned_chars`와 예산 판정이 **stdout 전체 길이**라는 하나의 기준이고 텍스트·JSON 양 모드에서 대조됨 |
| 8 | 발견 계층 마감 | 공개 projection의 **실제 값** 검사 — 다중 제출자가 CIK/name/URL 묶음으로, 문서 정체성이 accession+filename으로, 원격 total과 로컬 필터·중복제거 후 반환 수가 구별되어 나옴. 길이 불일치·누락 필드 처리. **옛 발견 cursor 거부.** `schema COMMAND` 11개의 `recovery`가 **실제 오류 코드와 일치하고 `fix`의 명령이 실행 가능**함(키 존재만으로는 불합격), `global_options`·exit code 포함 |
| 9 | SKILL.md 재작성 | 섹션 구조·탈락 문장 적용. frontmatter에 6-K·yfinance 경계. **트리거 경계 검증**: 긍정("애플 연차보고서 위험요인", "NBIS 6-K 첨부")과 부정("삼성 DART 사업보고서", "애플 분기 매출 시계열")의 스킬 선택 기대값. 본문이 `<th>` 부재를 **단정하지 않고 "없을 수 있다"**로 씀. `validate_harness.py` 오류·경고 0 |
| 10 | 통합 검증 | 아래 실행 명령 전부 + 홈드아웃 절차 |

### 단계 0에서 함께 고정할 실행 명령

```bash
uv run --isolated --frozen --group dev --project .claude/skills/sec/Scripts python -m pytest tests/sec
uv run --isolated --frozen --group dev --project .claude/skills/sec/Scripts ruff check --config pyproject.toml .claude/skills/sec/Scripts tests/sec
```

그리고 **깨끗한 프로세스에서 실제 문서 열기** — 모듈 이름이 표준 라이브러리를 가리는지는 import 시점에만 드러나고, `doctor`는 HTML 파서와 `bs4`를 import하지 않으므로 기동 검사로 쓸 수 없다:

```bash
uv run -q --isolated --frozen --project .claude/skills/sec/Scripts \
  python .claude/skills/sec/Scripts/sec.py --cache-dir <고정캐시> open <저장된 HTML URL>
```

live와 harness 검증도 여기서 고정한다. live는 `SEC_LIVE=1` 없이는 skip된다(`tests/sec/test_live.py:10-12`):

```bash
SEC_LIVE=1 uv run --isolated --frozen --group dev --project .claude/skills/sec/Scripts python -m pytest tests/sec/test_live.py
python3 /Users/seongjin/.claude/skills/harness-creator/scripts/validate_harness.py .claude/skills/sec
```

**필수 검증을 실행하지 못하면 인계·머지를 보류한다.** 실행 불가 사유(네트워크, identity, 환경)를 기록하고 다른 종류의 검사로 대체하지 않는다.

`open`에는 **캐시 분기가 없다** — `filings.py:386`이 무조건 `transport.get()`을 부르고 transport에 저장 바이트를 읽는 경로가 없으므로, `open`으로 재면 네트워크가 섞여 SDK 제거 효과를 가린다. 그래서 **저장된 바이트를 직접 파싱하는 벤치**로 잰다. 매 회 **새 프로세스**이고 **import를 포함**한다 — 기준선 23초가 바로 import 비용이라, 한 프로세스 안에서 3회 파싱하면 import가 첫 회에만 붙어 중앙값에서 사라진다.

```bash
S=.claude/skills/sec/Scripts
for i in 1 2 3; do /usr/bin/time -p uv run -q --isolated --frozen --project $S python -c "
import sys; sys.path.insert(0, '$S')
from store import Store
from snapshot import SourceDocument, parse_document
st = Store('<고정캐시>')
body = st.get('<원문 sha256>')
parse_document(SourceDocument(body, {'url': '<원문 URL>'}, {'content-type': 'text/html'}), st)
"; done
```

`open`의 벽시계 시간도 함께 기록하되 **네트워크 포함임을 명시**하고 합격 기준으로 쓰지 않는다.

## 검증

튜닝 문서와 판정 문서를 분리한다. **설계·디버그에는 NBIS·AAPL·MRVL을 자유롭게 쓰고, 홈드아웃 문서로는 단계 1~9 동안 구현을 실행하지 않는다.**

이것은 맹검이 아니다 — 기대 결과를 쓰려면 원문을 읽어야 하므로 구현자가 문서 내용을 안다. 막는 것은 **구현을 그 문서에 맞춰 튜닝하는 것**이지 문서를 보는 것이 아니다. 검증의 성격을 그 이상으로 주장하지 않는다.

### 홈드아웃 절차

단계 0에서 **다섯 건을 선정해 URL·SHA-256·기대 결과를 고정하고, 단계 1~9 동안 그 문서로 구현을 실행하지 않는다.** 선정은 아래 성질로 하되 구체적 문서는 구현 세션이 고른다.

| 성질 | 무엇을 노리는가 |
|---|---|
| Workiva가 아닌 생성기의 10-K | ZWSP·인라인 스타일 가정 |
| 외국 발행인 20-F | 다른 관행 |
| 구형 SGML `.txt` 제출문 | `<FILENAME>` 없는 역사 공시 |
| Form 4 XML | XML 경로 |
| 이미지 중심 문서 | 텍스트 항해 불가 시 동작 |

**봉인 방식**: 단계 0에서 다섯 건을 고르고, 기대 결과를 **원문을 읽어** `tests/sec/fixtures/holdout/expected/*.md`에 작성해 커밋한다 — 도달해야 할 섹션 경계 목록, 읽어야 할 표의 table_id와 특정 값, 지원 범위(이미지 중심 문서는 "항해 불가를 정직하게 보고"가 기대 결과다). 기대 결과를 쓰는 일은 **원문 읽기이지 구현 튜닝이 아니므로** 같은 세션이 해도 된다. 봉인의 실제 내용은 **단계 1~9 동안 그 문서로 구현을 실행하지 않는 것**이다. 성진이 최종 판정 전에 기대 결과를 검토한다.

**홈드아웃에서 실패하면 그 문서는 소모된다.** 고쳐서 다시 판정하려면 새 홈드아웃을 같은 성질로 확보한다. 소모된 문서는 튜닝 세트로 옮긴다.

### 구조적 도달성 (강조 관측의 판정)

HTML 문서에만 적용한다. SDK를 정답으로 삼지 않고, **기대 위치 목록을 독립적으로 먼저 작성**한다.

- `outline --kind emphasis`의 **기본 필터 전체 continuation** 안에서 Item·Part 경계와 주석 Note 번호 전부 도달
- 같은 문구의 여러 발생 위치에 **각각** 도달(Microsoft `PART II` 60회 — 묶되 위치 보존)
- 강조 관측마다 `signals` 동반, 길이 제한으로 관측을 버리지 않음
- 항해층이 빈 구간에서 `--all`로 내려가면 관측층이 실제로 그 구간을 덮는다(승격 규칙은 두지 않기로 했으므로 승격 동작을 요구하지 않는다)

### 실측 수치

| 항목 | 현재 (실측) | 목표 |
|---|---|---|
| NBIS `table-7` 전체 읽기 (텍스트 모드, 기본 예산) | 46K자·4회+ | **격자 본문 ≤3,000자·1회** |
| `read`의 8자 이하 조각 줄 (선불워런트 행 ~ 표 끝, 텍스트 모드) | **95%** | **≤20%** |
| 저장 바이트 파싱 (새 프로세스, import 포함, 3회 중앙값) | 23초 | **≤1.5초** |
| lock 전체 (dev 포함) | 51 | **19** |
| 3사의 `0×0` 아닌 표 | 격자 불가 | **전부 격자로 읽힘** |

> **폐기한 지표**: "`read` 응답의 본문 비율 ≥70%". 직전 점검의 21%를 재측정 없이 인용했으나 현재 실측은 AAPL 90%·NBIS 81%로 **구현 없이 이미 통과**한다. 게다가 재무제표 안에서는 비율 81%면서 95%가 8자 조각이라 **결함을 놓친 채 합격**시킨다.

**기준 미달은 "사실상 충족"으로 넘기지 않는다.** 직전 계획이 3,000자 기준에 3,271자를 그렇게 처리한 전력이 있다. 미달이면 미달로 기록하고 원인과 함께 남긴다. 정확성·호출 수·출력량·지연은 **분리해서** 판정한다.

### 모델 시나리오

코덱스(`gpt-6-astra`, medium)에게 **SKILL.md만 주고 소스는 금지**한 격리 세션. 리뷰 통과는 시나리오의 대체물이 아니다.

**시작 조건과 정답을 고정한다** — "이번 분기"처럼 실행 시점에 따라 달라지는 표현을 쓰지 않는다. 그리고 **발견(기업·기간·문서 고르기)과 읽기(도달·해석)의 호출 수를 따로 센다.**

| # | 시작 조건 | 정답 |
|---|---|---|
| 1 | "NBIS의 2026년 6월 30일 종료 반기 지분변동표에서 선불워런트 발행이 자본의 어느 항목에 얼마로 들어갔나" — URL 미제공 | accession `0001104659-26-094844`, `nbis-20260812xex99d2.htm`, `table-7`, 행 "Issuance of pre-funded warrants (Note 14)", **Additional Paid-In Capital 2,000.0 / Total Equity 2,000.0**. 읽기 단계 `open`→`find`→`table` **3회 이내** |
| 2 | 같은 질문, 문서 URL 제공 | 위와 같되 발견 단계 0회. 읽기 3회 이내 |
| 3 | "MRVL이 supply constraint를 어떻게 설명하나" — accession `0001835632-25-000197` / `0001835632-26-000019` / `0001835632-26-000025` 제공(축약하지 않는다) | **단계 0에서 세 문서를 열어 해당 문단의 위치와 원문 문장을 미리 기록**해 두고 그것과 대조한다. 기록이 없으면 이 시나리오는 판정 불가로 남긴다 |
| 4 | 홈드아웃 문서 5건 | 목차 없는 탐색, 표 중간 페이징, XML·SGML 읽기가 각 문서의 봉인된 기대 결과와 일치 |
| 5 | 트리거 근처 | "SEC가 이 회사를 제재했나"→범위 밖, "지금 NBIS 주가"→yfinance, "삼성 DART 사업보고서"→이웃 도구 |

**표에 도달한 것만으로 합격시키지 않는다.** 시나리오 1·2는 값 두 개를 정확히 읽어야 통과다.

### 코덱스 코드 리뷰

단계 2·4·5·6 직후 `gpt-6-astra` 독립 검토. 격자 조립(span 점유·전체 기준 열 접기·중첩), 강조 규칙, 대체 파서의 경계 조건, 페이징 불변식이 대상. **프롬프트는 파일로 전달한다** — 백틱이 든 프롬프트를 셸 인자로 넘기면 zsh가 명령 치환으로 실행한다(이 세션에서 재현).

## 전달

- 브랜치 `refactor/sec-reading-layer`, `main`에서 분기
- 논리적 단위마다 커밋(단계 1~10이 대체로 그 단위)
- PR 제목 `refactor: sec 읽기 계층을 격자 모델로 재설계`
- PR 본문은 `.github/pull_request_template.md`를 따르고, 없으면 `## 무엇을 바꿨나` / `## 왜` / `## 영향` / `## 검증`
- `## 검증`에는 위 실측 표의 **실제 측정값**과 모델 시나리오 결과를 그대로. 안 돌린 것은 안 돌렸다고 명시
- `gh pr merge --squash` 후 `graphify-out/` 리빌드(`Graphify` 스킬)

**폐기하지 않는 결정** — 스쿼시 머지에서 PR 제목만 `main`에 남으므로 이유는 커밋 본문과 PR에 있어야 한다:

- edgartools 제거의 이유 (warm import 23초 vs 파싱 0.48초, lock 51→19 패키지, 쓰이는 곳은 3개 용도·import는 4군데, 그리고 SDK 제목이 정답이 아니라는 실측)
- 헤더를 판정하지 않는 이유 (기간 스택 표에서 틀린 사실 180건)
- 격자 표기를 파이프 무패딩으로 정한 이유 (2,086 vs 5,927자)
- U+200B만 처리하고 혼합 문자열은 보존하는 이유 (증거성)
- 튜닝/홈드아웃 분리의 이유 (NBIS 과적합)

**기각된 대안과 재개 조건**: 열폭 맞춤 정렬(2.8배 비용 — 사람이 직접 읽는 용도가 생기면 재검토), 행라벨×열라벨 사실(기간 스택 반례 — 표 구조 판정이 신뢰 가능해지면 재검토), 구조적 위치 주소 `fp:t7:r12:c4`(지어낼 수 있음 — 인용 검증 수요가 생기면 재검토).
