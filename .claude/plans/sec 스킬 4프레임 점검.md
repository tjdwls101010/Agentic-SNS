# sec 스킬 4프레임 점검과 보완 계획

## Context

성진이 코덱스에 준 프롬프트(`.claude/plans/user-inputs/260913_sec 스킬 구현.md`)의 의도는 "클로드·코덱스가 SEC 원문을 사람처럼 쓰는 역량", 즉 어떤 기업의 SEC 문서를 부탁하면 Yahoo 뉴스나 이전 기간 공시를 가져오는 대신 **정확한 기업·정확한 기간의 원문을 고르고, 목차→섹션→표→이미지로 컨텍스트를 점진적으로 로드**하는 스킬을 harness-creator 네 프레임(principle over rail, interface over document, for user not developer, dense information)에 맞게 만드는 것이었다. 기업·양식별 포맷이 달라 통일 파서가 불가능하다는 인식이 있었고, 로그인 필요 여부는 계획 세션에서 실측으로 정하기로 했다. 코덱스는 계획 인터뷰에서 직접 HTTPS(로그인·Aside 불필요), edgartools 부품 사용, 판단 중심 SKILL.md, 자기서술 CLI(`company/filings/search/open` + `outline/find/read/table/links`)로 확정했고 PR #8(4296032)·#9(36be9cf)로 머지됐다.

이 세션은 그 결과물이 네 프레임을 실제로 충족하는지 SKILL.md·코드·`--help` 11개·`schema`·`doctor`를 읽고, 격리 캐시에서 Apple 최신 10-K(accession 0000320193-25-000079)를 대상으로 탐색 체인 전체와 오류 6종을 기본 옵션으로 실행해 점검했다. finviz v1 점검(c47eb26)과 같은 잣대다. 코덱스의 세 차례 독립 리뷰와 E2E 5/5는 정확성만 판정했고 호출 수·출력 밀도는 합격 기준에 없었다. 결함은 거기서 나왔다.

이 파일은 점검 세션의 유일한 산출물이다. 구현 파일은 바꾸지 않았다. 구현 세션은 시작 시 이 파일을 형제 기록과 같은 이름 `.claude/plans/sec 스킬 4프레임 점검.md`로 옮긴다.

## 점검 결과 요약

| 프레임 | 본문(SKILL.md) | 인터페이스·출력 | 근거 |
|---|---|---|---|
| Principle over rail | 통과 | **결함 1건(C1)** | 본문은 섹션마다 판단 이유와 실제 함정(목차 중복, 제출일 vs 보고일, 정정, 첨부≠제출자)이 있고 고정 순서가 없다. 읽기 명령의 `--limit` 1..20과 `--max-chars` ≤12,000은 이유 없는 상한이다. |
| Interface over document | 통과 | **결함 4건(A1~A4)** | 본문은 인자·기본값·복구를 help/schema로 보냈고 help는 전 인자에 설명·기본값·범위가 있다. 표 선택 근거 부재, snapshot 오류의 cursor 복구 안내, schema 범위 없음, warnings 열거 불일치. |
| For user not developer | 통과 | 경미 1건(A4와 동일) | 본문에 개발 이력이 없다. 개발자용 warning 식별자 하나. |
| Dense information | 통과 | **결함 4건(D1~D4)** | 46줄. 출력은 `read` 본문 비율 21%, `table` 7회·46K자, `outline` 83% 앵커, 텍스트 모드가 한 줄 JSON, stderr 설치 로그. |

의도 정합성: 구조는 정확하다. `company/filings/search/open(index)`가 "정확한 기업·기간·문서 고르기"를, `open(doc) → outline/find/read/table/links`가 "점진적 로드"를 맡고, 원 프롬프트의 실패 사례(이전 기간 문서)는 제출일·보고일 분리, 정정 분리, 이름 후보 비확정, accession 비대체로 인터페이스와 본문 양쪽에서 막았다. 발견·전송 층(`filings.py`·`transport.py`·`store.py`)은 정직하고 견고하다. 미달은 **reader 출력 층**에 집중된다. "점진적 로드" 원칙이 "모든 것을 20개씩 균등 페이지"라는 레일로 구현됐다. 사람은 10-K를 열면 Item 20개짜리 목차를 보고 점프하고 8행 표를 한눈에 읽는데, 현재 인터페이스는 앵커 1,242개 사이에서 제목 83개를 찾고 셀 20개씩 7번 읽게 한다.

## 실측 사실 장부 (2026-09-15, Apple 10-K, 격리 캐시)

| 항목 | 실측 |
|---|---|
| `--help` | 11개 명령 전부 description, 전 인자 help·기본값·범위·choices. `schema`는 argparse 정의에서 생성 |
| `schema` | 20,249자, 명령 범위 지정 불가(yfinance는 `schema GROUP LEAF` 가능) |
| stderr | `--isolated`로 매 호출 "Installed 43 packages in ~90ms". SKILL.md 명령에 `-q` 없음 |
| zsh | 명령 전체를 변수 하나에 담으면 실행 안 됨(이 세션에서 재현). yfinance SKILL.md에는 이 함정이 있고 sec에는 없음 |
| `company Apple` | 후보 13개(Form 4 개인 포함), `selection_required: true`. 정직함 |
| `filings AAPL --form 10-K --limit 3` | 2,591자. 제출일·보고일·정정·`index_url`·`document_url` |
| `open <index>` | 첨부 16건. 4,360자 |
| `open <doc>` | 1.5MB HTML → 3,124블록, 표 62개 중 20개만 `{table_id, rows, block}`. 캡션·첫 셀 없음. `table-0`은 빈 레이아웃 표 |
| `outline` | 1,489항목 = anchor 1,242(83%) + heading 83 + toc 72 + table 62 + internal_link 30. 20개/호출, `--kind` 없음 → 완주 75회. 표 항목 text는 `table-11`처럼 ID만 |
| `find "Risk Factors"` | 5건. 첫 히트 목차(block 93), 실제 제목 block 221. 본문 사례가 출력에 보임 |
| `read --position <221>` | 20블록/호출. 본문 2,214자 / 출력 10,653자 = 21%. `items`(7,809자)가 `text`(2,236자)와 블록별 메타데이터를 중복 |
| Risk Factors 전체 | block 221→340, 119블록 → `read` 6회 |
| `table table-15` (카테고리별 매출 8행) | 138항목 → 7회, 총 45,895자, 값 있는 셀 약 60개(≈1KB). 첫 페이지 20항목 중 18개가 빈 spacer 셀. 셀 레코드 키 12개 |
| 표 크기 분포 | 62개 중 52개가 20항목 초과, 최대 396항목(→20회) |
| 오류 6종 | 모두 `code/message/fix`. `read not-a-snapshot` → `invalid_cursor` "Restart the query without a cursor"(오답). 나머지 5종 정확 |
| `warnings` | `nonbody_inline_xbrl_metadata_omitted_from_reader_original_preserved`는 schema 열거에 없는 개발자용 식별자 |
| 구조 검사 | validate_harness: sec 오류·경고 0(finviz만 4E/1W). audit: 4296032·36be9cf |
| 캐시 읽기 | identity·네트워크 없이 동작. `find/read/table`이 같은 snapshot·position 계약 사용 |

## 확정 결함

### A1. 표를 고를 근거가 인터페이스에 없다 — `Scripts/document.py:27,205`, `Scripts/reader.py:134`

`open` 요약의 `tables`와 `outline`의 `kind=table` 항목이 `table_id`·행수·블록만 준다. 본문은 "A table value needs its row, column header, unit and qualifying footnotes"라고 판단을 요구하지만, 어느 표가 매출 표인지는 62개를 열어 보거나 `outline` 75회를 완주해야 안다. `outline`에 `--kind` 필터가 없어 제목 83개가 앵커 1,242개에 묻힌다(`links`에는 `--kind`가 있다).

### A2. snapshot 오류에 cursor 복구 안내 — `Scripts/store.py:58`

`Store.get`의 식별자 정규식 검사가 모든 저장 레코드에 공통이라 잘못된 snapshot id에도 `invalid_cursor` "Restart the query without a cursor"를 낸다. schema의 recovery 표에는 `missing_snapshot`이 있고 `document.load_snapshot`에는 `invalid_snapshot`이 있지만 이 경로에 먼저 도달하지 못한다. help 문구와 구현이 어긋난 사례다.

### A3. `schema` 범위 지정 불가 — `Scripts/sec.py:133`

20KB를 매번 받는다. yfinance·finviz 재작성 계획은 `schema [GROUP [LEAF]]`다.

### A4. warnings 값이 schema 열거와 어긋난다 — `Scripts/document.py:306`, `Scripts/sec.py:198`

`nonbody_inline_xbrl_metadata_omitted_from_reader_original_preserved`는 열거에 없고 개발자용 식별자다.

### C1. 이유 없는 상한 — `Scripts/reader.py:30`, `Scripts/sec.py:93,101`

읽기 명령의 `--limit` 1..20, `--max-chars` 1024..12000. 8행 표를 한 번에 읽을 예산이 있어도 20셀씩만 준다. "Numbers need a reason and the conditions under which another value is right"에 어긋난다. `filings.validate_options`는 1..100을, `reader._page`는 1..20을 따로 검사한다.

### D1. `read`의 `items`/`text` 중복 — `Scripts/reader.py:52-88`

`_page`가 블록마다 `kind/text/url/block/offset/text_offset/text_complete/position`을 `items`에 싣고 같은 텍스트를 `text`에 다시 이어 붙인다. 본문 비율 21%.

### D2. `table`의 셀 단위 페이지와 spacer 셀 — `Scripts/document.py:185`, `Scripts/reader.py:168`

셀 하나가 12개 키의 레코드이고 빈 레이아웃 셀도 같은 비용이다. 8행 표에 7회·46K자.

### D3. 텍스트 모드가 한 줄 JSON — `Scripts/output.py:16`

`key: json.dumps(value)`라서 `--json`과 같은 정보를 이스케이프된 줄바꿈으로 한 줄에 받는다. 읽기 명령에서 평문의 이점이 없다.

### D4. stderr 설치 로그 — `SKILL.md:15`

`uv run --isolated`가 매 호출 "Installed 43 packages"를 stderr에 낸다. finviz v1과 같은 결함이며 `-q`로 사라진다.

## 경미한 항목 (권고안에 포함)

- E1. description에 의도어가 없다. "SEC"를 말하지 않고 "애플 최신 연간 보고서 위험요인 읽어줘"라고 하면 트리거 근거가 약하다(yfinance description이 "Not for original SEC filing text"로 밀어주기는 한다). annual/quarterly report text, risk factors, MD&A, exhibits, 연차보고서·분기보고서를 추가한다.
- E2. zsh 변수 함정 한 문장을 yfinance 문구 그대로 넣는다.
- E3. 본문 "Missing contents, unsupported media, decoding uncertainty, parsing failure and access failure have different implications"는 계산 가능한 결과 문장이라 잘라도 된다. 다른 본문은 건드리지 않는다.

## 검증하지 않은 것

- Apple 10-K 하나만 실측했다. Microsoft·ASML·Form 4 XML·SGML·TXT의 출력 형태는 코덱스 기록과 fixture에 의존한다.
- `search --sort relevance`, 이어보기 cursor의 원격 재생, 403/429 경로는 실행하지 않았다(테스트 72개가 덮는다).
- Claude E2E는 v1에서도 이 세션에서도 실행하지 않았다.
- `${CLAUDE_SKILL_DIR}` 치환은 harness-creator 스킬 본문이 절대 경로로 치환되어 온 것으로 확인했고 sec에서 별도 확인하지 않았다.

## 네 프레임이 이 보완에서 결정하는 것

첫 초안의 보완안을 같은 프레임으로 다시 점검해 네 곳을 고쳤다(옛 셀 형태를 테스트 때문에 `--cells`로 남기려던 것, 응답 안의 산문 안내문을 그대로 두려던 것, 이유 없는 완료 수치, 인용하지 않을 출처를 매 응답에 싣던 것). 아래 원칙이 각 항목의 형태를 결정하고, 숫자는 원칙에서 계산한 결과만 쓴다.

- **principle over rail → "자르지 않고 선택으로 좁힌다."** 출력 크기는 모델이 고른 범위(`--kind`, `--position/--end`, 행 범위)의 결과여야 하고, 도구가 정한 개수 상한의 결과여서는 안 된다. 유일하게 남는 경계는 `--max-chars`이며 그 이유는 하나다: 호스트 도구가 결과를 조용히 잘라내는 지점 아래에 있어야 한다. 넘으면 잘라내지 않고 `too_large`와 함께 그 명령이 실제로 가진 좁히기 인자를 이름으로 안내한다. 기본 페이지 개수(`--limit`)는 목록 명령에만 남고 읽기 명령에서는 없어진다.
- **interface over document → "도구가 소유하는 지식은 도구가 말한다. 단, 데이터 자리에서 말하지 않는다."** 인자·기본값·복구는 help/schema에, 응답에는 데이터와 그 데이터의 상태 필드만 있다. `table_discovery`·`snapshot_scope`처럼 매 응답에 반복되는 산문 문장은 schema 한 곳으로 옮기고 응답에서 뺀다. 상한·기본값을 바꾸면 그 이유 문장도 `schema.defaults`에 함께 둔다.
- **for user not developer → "모델이 쓰지 않는 필드·형태는 만들지 않는다."** 옛 형태를 호환·테스트 목적으로 남기지 않는다. 필요한 위치 정보는 새 레코드가 싣는다. 응답의 `sources`는 모델이 인용할 문서·인덱스·검색 요청만 담고, 식별용 티커 파일 같은 내부 조회는 담지 않는다. 식별자(`warnings` 값, 오류 `code`)는 모델이 그대로 읽어 판단할 수 있는 짧은 이름이어야 한다.
- **dense information → "사람이 한눈에 보는 단위가 한 호출이다."** 표 하나, 문서의 실제 목차(toc 항목), 섹션 하나가 각각 한 호출에 들어오는 것이 기준이다. 그래서 항목 레코드는 모델이 다음 행동에 쓰는 필드(`kind`, `text`, `position`, 표는 `table_id`와 `context`)만 갖고, 메타데이터가 본문을 두 번 실어서는 안 된다. Apple 10-K로 계산하면 toc 72 + heading 83 = 155항목 × 약 120자 ≈ 18,600자, 표 62항목 × 약 200자 ≈ 12,400자, table-15의 값 있는 셀 약 60개는 행 레코드로 약 1,500자다. 완료 판정 수치는 이 계산에서 나온다.

## 보완 작업 (성진 결정: reader 출력 층 재설계, 본문·발견 층 유지)

전면 재작성은 하지 않는다. 바꾸는 파일은 `Scripts/reader.py`·`Scripts/document.py`(표·개요 레코드)·`Scripts/sec.py`(상한·schema)·`Scripts/output.py`(렌더러)·`Scripts/store.py`(오류 코드)·`Scripts/filings.py`(`sources`·`snapshot_scope`)·`SKILL.md`(명령줄·description·문장 2개)와 `tests/sec/`다. 디렉터리 구조는 그대로다. 기존 테스트 72개 중 옛 출력 형태에 붙은 것은 새 공개 계약으로 고쳐 쓴다. 테스트를 위해 옛 형태를 남기지 않는다. 각 항목은 `tdd` 스킬로 공개 CLI seam(`tests/sec/test_cli_documents.py`, `tests/sec/test_documents.py`, fixture `tests/sec/fixtures/documents/apple.html.gz` 등)에 재현 테스트를 먼저 쓰고 통과시킨다. 트래커는 `TaskCreate`로 열고 아래 완료 판정을 그대로 적는다.

1. **outline을 선택 가능하게, 표에 문맥을 (A1)**. `outline --kind` choices `heading,toc,table,anchor,internal_link`(쉼표 복수), 기본값 `toc,heading,table`. 앵커는 인용용 위치이므로 옵트인이다. 항목 레코드는 `{kind, text, position, url}`로 줄이고(`block/offset/text_offset/text_complete`는 위치에 이미 들어 있다), 표 항목과 `open` 요약의 `tables`는 `table_id, rows, position, context`를 갖는다. `context`는 caption, 없으면 직전 비어 있지 않은 블록 텍스트와 첫 헤더 행 텍스트다(`document._html_blocks` 159~207행이 이미 두 블록 문맥을 모으므로 그것을 재사용한다). `open` 응답의 `table_discovery` 문장은 뺀다. 완료 판정: Apple 10-K에서 `outline --kind toc`가 1회, 기본 `outline`이 3회 이내에 `scope_complete`(위 계산 약 31,000자 ÷ 12,000), 표 항목의 `context`만으로 "net sales by category" 표를 식별, `--kind anchor`로 앵커 1,242개가 여전히 나옴.
2. **표는 행 단위로 한 번에 (D2, C1)**. `table`의 출력을 `context, caption, footnotes, rows: [{row, header, position, cells: [{column, colspan, text}]}]`로 바꾸고 텍스트가 빈 레이아웃 셀은 생략하되 남은 셀의 원래 `column` 번호는 유지한다(원본 DOM은 그대로 보존되므로 손실이 아니다). 구현은 인접 셀의 colspan에 병합하지 않으며, 2단계 커밋 메시지의 '병합' 서술은 코덱스 리뷰가 확인한 실제 동작과 다르다. `--limit`은 없어지고 `--rows A-B`가 부분 읽기, `--max-chars`가 경계다. 완료 판정: table-15가 1회 호출 3,000자 이내에 `scope_complete`(값 있는 셀 60개 × 약 25자 + 봉투), 2025/2024/2023 값·`$`·`%`·각주 (1)·`Total net sales`·헤더 행 표시 보존, 최대 표 table-29(396항목)가 `too_large` 없이 12,000자 이내인지 실측하고 넘으면 `fix`가 `--rows`를 이름으로 안내.
3. **read는 본문을 한 번만, 평문으로 (D1, D3, C1)**. `_page`가 `read`에서 `text`를 한 번만 내고 `items`는 `{kind, position}`만 남긴다. 기본 렌더링은 `snapshot_id/source_url/next_position/has_more` 헤더 뒤 `text` 평문이며 `--json`은 유지한다. `--limit` 상한 20을 없앤다. `--max-chars` 기본 12,000은 유지하고 상한은 호스트 잘림 한도에서 계산한다(Claude Code Bash 도구 `BASH_MAX_OUTPUT_LENGTH`의 기본값을 구현 세션에서 확인하고 그 80%를 상한으로, 이유 문장을 `schema.defaults`에 기록). 커서 계약 `version`을 3으로 올린다. 완료 판정: Risk Factors(block 221→340, 119블록·약 60,000자)가 기본 예산으로 5회 이내(60,000 ÷ 12,000), 매 호출 본문 비율 90% 이상(헤더 4줄 약 300자), 기존 `--max-chars 2048` 예산 테스트가 새 계약으로 통과.
4. **복구·계약 정합 (A2, A3, A4)**. reader 경로에서 `load_snapshot`이 식별자 형식을 먼저 검사해 `invalid_snapshot`을 내고, `Store.get`의 형식 오류는 cursor 경로에서만 `invalid_cursor`다. warnings 값을 `inline_xbrl_metadata_excluded`처럼 짧게 하고 schema 열거에 넣는다. `schema [COMMAND]`를 추가한다. `search` 응답의 `snapshot_scope` 문장은 schema의 `search.snapshot_scope`에만 남긴다. 완료 판정: 오류 6종 재현 테스트가 각자 맞는 `code`·`fix`, `schema read`가 2KB 이내, `schema`(무인자)는 문장 이동 외 동일.
5. **sources는 인용할 것만 (dense, for user)**. `filings`·`search`·`company`의 `sources`에서 `company_tickers_exchange.json` 조회 항목을 빼고 submissions·EFTS·인덱스·문서만 남긴다(`filings.resolve`가 돌려주는 sources를 listing에 합치지 않는다). 완료 판정: `filings AAPL` 응답의 `sources`가 submissions 1건, 라이브 테스트 통과.
6. **SKILL.md 외과 수정 (D4, E1~E3)**. 명령줄에 `-q`, zsh 문장 1개, description 의도어, E3 문장 삭제. 본문 다른 문장은 건드리지 않는다. 완료 판정: `validate_harness.py --path .` sec 오류·경고 0, description 1,536자 이내.
7. **검증·리뷰·전달**. `uv run --isolated --frozen --python 3.11 --group dev --project .claude/skills/sec/Scripts python -m pytest tests/sec -q`, 같은 project의 ruff, `SEC_LIVE=1 … test_live.py`. 이 세션의 probe 체인(`company → filings → open → outline → find → read → table → links → search` + 오류 6종)을 새 격리 캐시에서 재실행해 위 완료 판정 수치를 기록한다. 코덱스(`gpt-6-astra`, medium) 독립 리뷰 1회. E2E는 Apple 표·Microsoft 위험요인 두 시나리오를 코덱스 격리 세션으로 재실행하고 **호출 수와 출력 총량을 합격 기준에 포함**한다(Apple 표: `table` 1회, Microsoft 위험요인 끝: 섹션 길이 ÷ 12,000으로 계산한 횟수 이내). 브랜치 `feat/sec-reader-output`, 커밋 단위는 위 1~6, PR 제목 `feat: sec 읽기 출력을 선택 인자와 행 단위로 재설계`, `gh pr merge --squash`, `graphify-out/`이 있으면 리빌드. 머지 후 이 점검의 결론(본문 통과·출력 층 미달·재설계 결정)을 프로젝트 메모리에 한 줄로 남기고, 성진의 교정("프레임 점검 뒤에 내는 보완안도 같은 네 프레임으로 다시 점검한다. 첫 초안이 네 곳에서 어겼다")을 feedback 메모리로 남긴다.

## 구현 결과 실측 (2026-09-16, Apple 10-K `aapl-20250927.htm`, 격리 캐시, 기본 옵션)

| 항목 | v1 | 재설계 후 |
|---|---|---|
| `outline` 완주 | 1,489항목 ÷ 20 = 75회 | 기본(toc·heading·table) 3회. `--kind toc` 1회(4,440자), `--kind heading` 1회, `--kind table` 2회, `--kind anchor` 11회 |
| 표 선택 근거 | `table_id`·행수뿐 | 항목마다 `context`(캡션·직전 문장)와 `header`(첫 비어 있지 않은 행), 각각 200자로 끊은 힌트. table-14와 table-15를 열지 않고 구분 |
| `table table-15` | 7회, 45,895자 | 1회, 텍스트 3,271자 / JSON 6,205자, `scope_complete` |
| `table` 최대 표 | table-58이 셀 20개씩 20회 | 3회. 각주 결함 수정 전에는 `budget_too_small` |
| Item 1A 전체 읽기 | 본문 비율 21% | 기본 예산 7회·95.2%, 상한 24,000에서 4회·97.4% |
| `read` 응답 | `items`가 본문을 메타데이터와 함께 중복 | 산문은 `text` 하나와 `{kind, position}` 항목, XML은 `path`·`parent`·`attributes`를 가진 항목 |
| 기본 렌더링 | 이스케이프된 한 줄 JSON | 출처·사본·상태·warnings·이어읽기 헤더 뒤 평문 |
| `schema` | 20,249자 통짜 | 전체 21,334자, `schema read` 3,905자(18%), `schema table` 3,944자 |
| 잘못된 snapshot id | `invalid_cursor` "cursor 없이 다시 실행" | `invalid_snapshot` "open이 준 snapshot_id를 쓰라" |
| 위치 | 사본을 밝히지 않아 다른 사본에도 통함 | 사본 지문 열 자를 앞에 달고 다른 사본에서는 거절 |
| `filings AAPL` sources | 티커 파일 + submissions | submissions 1건 |
| 각주 | 컨테이너까지 올라가 206,100자 문서 전체를 한 각주로 | 앵커·부모·앵커의 다음 형제·부모의 다음 형제만, 표를 포함하는 요소와 제목은 거부. 애플 10-K에 남는 각주는 실제 주석 1건(17자) |
| stderr | 호출마다 "Installed 43 packages" | `-q`로 없음 |

`open` 문서 요약만 2,332자에서 5,603자로 늘었다. 표 20개에 `context`·`header`가 실렸기 때문이고, 그 대가로 표를 고르려고 62개를 열어보거나 `outline`을 75회 완주할 필요가 없어졌다.

계획의 완료 판정 중 하나는 도달하지 못했다. Item 1A를 기본 예산으로 "5회 이내"로 잡았는데 실제 섹션이 68,040자여서(계획의 추정 60,000자) 12,000자 예산에서는 6회가 하한이고 측정값은 7회다. 상한 24,000에서는 4회다. 본문 비율 기준(90% 이상)은 95.2%로 충족했다. 표의 "3,000자 이내"는 기본 텍스트 모드 3,271자로 사실상 충족했고, 계획이 잡은 25자/셀 추정은 압축 JSON 기준이어서 pretty JSON에서는 6,205자다.

## 검증 기록

- `tests/sec`: **95 passed, 1 skipped**(skipped는 opt-in 라이브). 새로 쓴 재현 테스트가 23개이고, 옛 출력 형태에 붙어 있던 기존 테스트는 새 공개 계약으로 고쳐 썼다.
- 라이브: `SEC_LIVE=1 … test_live.py` **1 passed**. 기업·기간·검색·첨부·원문 저장·사본 find→read까지 실제 SEC 경계를 지난다.
- 형제 스킬 회귀: JS **70 passed**, Python **1,023 passed, 40 deselected**. `validate_harness.py` **errors 0 / warnings 0**.
- 코덱스 독립 리뷰 3회(`gpt-6-astra`, high, 격리 read-only). 1차 `20260916-222434-sec-reader-review-f3f3`가 결함 8건, 2차 `20260916-230339-sec-reader-verify-326d`가 그중 5건 수정 확인·4건 부분 수정·새 회귀 3건, 3차 `20260916-231929-sec-verify3-ef95`가 최종 확인이다. 세 번 모두 read-only 샌드박스에서 uv 캐시 접근이 막혀 전체 스위트를 대신 실행하지는 못했고, 모듈 직접 호출로 재현했다. 그 사실을 근거에 남긴다.
- 리뷰가 잡은 것 중 v1부터 있던 결함은 표 각주가 컨테이너를 삼켜 문서 전체(206,100자)를 한 각주로 싣던 것이고, 나머지는 이번 재설계가 만든 것이다. 두 차례의 수정이 각각 새 회귀를 만들었고(각주 후보 순서, XML 구분자, 헤더 행 판정, 문맥 부분 표시), 그것도 재현 테스트와 함께 고쳤다.

### 모델 시나리오 (코덱스 `gpt-6-astra`, medium, 격리 세션, SKILL.md만 주고 소스는 금지)

두 시나리오 모두 통과했다. 첫 시도는 격리 샌드박스가 uv 캐시와 DNS를 막아 CLI가 기동하지 못했고, 네트워크를 허용해 다시 실행했다. 그 사실을 근거에 남긴다.

| 시나리오 | 실행 ID | 결과 |
|---|---|---|
| 애플 카테고리별 매출 | `20260916-232145-sec-e2e-apple2-27f9` | CLI 11회(`--help`·`schema` 포함). 2025 회계연도 10-K를 고르고 `table-15` 한 번으로 2025/2024/2023 값·단위·회계연도 종료일을 원문과 일치하게 답했고, 표 식별자와 위치 `fae4f24678:555:0`, 원문 URL을 제시했다. warnings를 읽고 "표 조회는 전체 반환 완료"와 "문서 추출 완전성"을 구분해 서술했다. |
| 마이크로소프트 위험요인 끝 | `20260916-232146-sec-e2e-msft2-2630` | CLI 9회. 접수번호 `0001193125-26-323660`, 제출일 2026-07-29, 보고일 2026-06-30을 특정하고 Item 1A의 마지막 위험(노조 조직화)과 Item 1B 시작 지점을 원문으로 확인했다. 읽기는 `read --position … --end …` 한 번이었다. |

### 남긴 한계

- 마이크로소프트 원문은 SDK의 제목 텍스트가 `ITEM 1A. RIS`처럼 잘려 블록과 정확히 일치하지 않아 해당 목차 링크가 `toc` 대신 `internal_link`로 분류되고 기본 `outline`에서 빠진다. `--kind internal_link`로 요청하면 정확한 위치가 나오고 그 위치로 읽으면 올바른 절에 닿는다. 코덱스는 이를 "탐색 불편이지 근거 훼손은 아니다"로 두었고 이번 범위에서 고치지 않았다.
- 표 바로 뒤에 다른 표가 이어지면 뒤 문맥에 그 표의 머리 조각이 섞일 수 있다. 주석이 붙는 표에는 주석이 실린다(애플 두 번째 현금성자산 표에서 확인).
- 코덱스 리뷰는 세 번 모두 read-only 샌드박스에서 uv 캐시 접근이 막혀 전체 스위트를 직접 돌리지 못했고, 모듈 직접 호출로 재현했다. 전체 스위트 결과는 내 실행 기록이다.

## 폐기하지 않는 결정

직접 HTTPS와 identity 필수, edgartools 부품 사용, 제출일·보고일·정정 분리, 이름 후보 비확정, accession 비대체, 불변 cursor·snapshot 계약, 기본값 20개·12,000자는 유지한다. 바뀌는 것은 상한, 표·개요 레코드의 내용, `read`·`table`의 출력 형태, 텍스트 렌더링이다.
