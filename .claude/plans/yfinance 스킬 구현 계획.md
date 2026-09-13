# 에이전트가 바로 활용할 수 있는 yfinance 조회 스킬

## 1. 목표와 확정 범위

Claude·Codex가 **스킬과 CLI의 안내만으로 필요한 데이터를 발견하고, 조회 조건을 선택하고, 결과와 한계를 정확히 해석**할 수 있게 만든다. yfinance의 객체·메서드 구조를 그대로 노출하지 않고 데이터 목적별 인터페이스로 재구성한다.

- 조회 기능군은 폭넓게 지원한다. 질문에 따라 몇 개에서 수십 개 종목을 탐색하는 사용을 중심으로 설계하고 미국 시장을 우선 검증한다.
- 분석 방법·투자 판단·보고서 작성은 상위 에이전트의 책임이다.
- 스트리밍, 대량 수집 서비스, 결과 저장·복원, 원본 포크·내부 패치는 제외한다.
- 배포물은 `SKILL.md`와 실행용 `Scripts/`로 구성한다. 별도 참고 문서·훅·에이전트·권한 허용 규칙은 추가하지 않는다.
- 일반적인 요청을 처리하기 위해 yfinance 소스·외부 문서를 읽거나 임시 Python 코드를 작성해야 한다면 인터페이스의 부족으로 검토한다.

직접 Python API를 사용하도록 안내하는 초기안과 전용 저장 도구 구상은 이번 합의로 대체한다.

## 2. CLI와 데이터 계약

### 데이터 목적별 명령

| 명령 | 제공할 데이터·기능 |
|---|---|
| `search` | 이름·티커·자산 종류에 따른 종목 후보와 지원되는 검색 결과 |
| `prices` | 가격 현황, 기간별 가격, 배당·분할·자본이득 등 기업행사 |
| `company` | 기업 개요, 주식 수, 관련 뉴스·공시 목록, 지속가능성 정보 |
| `financials` | 손익계산서·재무상태표·현금흐름표, 기간별 가치평가 지표 |
| `analysts` | 목표가, 추천·등급 변경, 실적·매출 추정, 추정 수정·추세·성장 |
| `holders` | 주요·기관·펀드 보유자, 내부자 보유·매수·거래 |
| `fund` | ETF·펀드 개요·운영 정보, 보유 종목, 자산·업종·채권 구성 |
| `options` | 만기 목록과 선택한 만기의 콜·풋 |
| `screen` | 기본 스크리너, 필드·허용값 탐색, 주식·펀드·ETF 조건 검색 |
| `market` | 시장 상태·요약, 섹터·산업과 관련 기업·펀드·보고서 |
| `calendar` | 종목별 실적 발표 이력과 시장의 실적·경제·IPO·분할 일정 |

동일 기능의 속성·메서드 별칭은 합친다. 데이터를 제공하지 않는 폐기 API는 노출하지 않고 대체 조회로 연결한다. 구현 시 명령별 공개 API 대응표와 검증 상태를 계획 기록에 유지한다.

호출 형태는 다음과 같다.

```text
prices history AAPL MSFT --period 1mo --interval 1d --adjust auto
financials income AAPL --frequency quarterly --fields TotalRevenue --periods 4
options expirations AAPL
screen fields --type equity
schema financials income
```

### 기능과 입력을 발견하는 방법

- 전체·그룹·세부 명령에 `--help`를 제공하고, `schema [그룹 [세부 명령]]`으로 입력과 출력 계약을 조회한다.
- 파서의 인자·기본값·선택지 정의를 도움말과 입력 스키마가 공유한다.
- 짧은 고정 선택지는 도움말에 표시한다. 옵션 만기, 대상별 데이터 항목, 스크리너 필드·허용값처럼 길거나 변하는 선택지는 해당 목록 조회에서 제공한다.
- 조회 결과의 티커·만기·섹터 키·필드명은 다음 명령에 그대로 사용할 수 있게 한다.
- 스크리너 조건은 `operator/operands` 형태의 JSON으로 받고 Python 코드나 `eval`을 사용하지 않는다.
- `screen run --help`와 `schema screen run`에 연산자, 피연산자의 형식·개수, 중첩 예시를 포함한다. 조건 오류는 잘못된 위치와 기대 형식을 알려준다.
- 도움말·스키마는 외부 조회 없이 동작한다. 실제 대상에 의존하는 선택지 조회는 필요한 공개 API를 호출한다.

### 결과와 오류

- 조회당 JSON 문서 하나를 반환한다. 공통 구조는 전체 상태와 대상별 결과이며, 각 결과에 대상·적용 조건·관측 시각·데이터·맥락·경고·오류를 담는다.
- 표의 행·열 식별과 축 이름을 보존한다. 재무표는 기간을 읽기 쉽게 정리하되 원래 항목명과 값의 관계를 유지한다.
- 날짜는 ISO 표현을 사용하고 확인된 시간대·통화·변환 맥락을 남긴다. 모르는 단위나 기준 시각은 추정해서 채우지 않는다.
- NaN·NaT는 JSON의 `null`로 표현하며 0으로 보간하지 않는다. 단위 환산·통화 통합·백분율 변환은 임의로 수행하지 않는다.
- 성공, 빈 반환, 일부 실패, 요청 제한, 상위 서비스·해석 오류, 출력 한도 초과를 구분한다. 빈 반환은 실제 부재를 증명하지 않는다.
- 오류는 `code`, `message`, `fix`를 제공한다. 라이브러리 로그는 stderr로 분리하고 예상 가능한 오류에서도 stdout의 JSON을 유지한다.
- 여러 종목은 개별 결과·예외를 기록한다. 실패 종목을 결측 열로 섞어 전체 성공처럼 반환하지 않는다.
- 요청 제한을 확인하면 남은 외부 조회를 중단하고 성공·실패·미실행 대상을 구분한다. 별도 전송·재시도·캐시 계층은 재구현하지 않는다.

### 범위·기간·변환

- 기간·필드·종목·개수로 필요한 데이터를 선택한다. 원격 조회 범위와 출력 선택 범위를 구분한다.
- 기본 출력 한도는 **20,000자**로 시작하고 `--max-chars`로 명시적으로 변경할 수 있게 한다. 대표 시나리오에서 불필요한 재호출이 반복되면 근거와 함께 기본값을 조정한다.
- 한도를 넘으면 데이터를 일부만 성공처럼 내보내거나 JSON을 자르지 않는다. 필요한 필터·범위 축소·한도 변경 방법을 반환한다.
- 원격 오프셋을 지원하는 목록만 다음 위치를 안내한다. 미출력 행을 건너뛰지 않으며, 재조회가 동일 스냅샷이라는 보장은 하지 않는다.
- 가격 조정은 `none/auto/back` 중 하나로 선택한다. 기본은 `auto`, `repair`는 명시적 선택이며 기본은 꺼진 상태다.
- 가격의 시작은 포함, 종료는 제외하며 시간대 없는 가격 날짜는 거래소 시간대로 해석한다.
- 일정별 날짜 기준은 명령에서 설명한다. IPO의 상장·제출·수정일처럼 다른 의미를 가진 날짜를 구분한다.
- 연간·분기·TTM 재무와 가치평가 지표의 `Current`를 구분하고 불가능한 조합은 조회 전에 거부한다.
- 실적 일정은 새 객체로 조회해 캐시 문제를 피하고, 원본 요청 묶음 크기와 CLI 반환 개수를 분리한다.
- 원본이 이미 잃어버린 0·결측 구분 등은 복원했다고 주장하지 않고 영향이 있는 결과에서 한계를 알린다.

## 3. 실행 환경과 파일 구성

```text
.claude/skills/yfinance/
├── SKILL.md
└── Scripts/
    ├── yfinance_cli.py
    ├── prices.py
    ├── company.py
    ├── market.py
    ├── output.py
    ├── pyproject.toml
    └── uv.lock

tests/yfinance/
├── conftest.py
├── test_cli.py
├── test_prices.py
├── test_company.py
├── test_market.py
└── fixtures/
```

- `yfinance_cli.py`: 파서, 도움말, 스키마, 입력 검증과 라우팅.
- `prices.py`: 가격·기업행사 조회.
- `company.py`: 기업·재무·애널리스트·보유자·펀드·옵션 조회.
- `market.py`: 검색·스크리너·시장·섹터·산업·일정 조회.
- `output.py`: 공통 JSON 변환, 결과 선택·한도, 오류와 부분 결과 처리.

`yfinance[repair]==1.7.0`과 개발 의존성을 잠그고 `uv run --isolated --frozen`으로 실행한다. 실행 파일 이름은 라이브러리 import와 충돌하지 않는 `yfinance_cli.py`로 한다.

스킬 디렉터리만 다른 프로젝트로 옮겨도 실행되어야 한다. `.tmp/yfinance`, 작성자의 절대 경로, 시스템에 설치된 패키지에 의존하지 않는다. 검증 환경은 macOS·Linux의 Python 3.12로 한다.

`SKILL.md`의 섹션은 다음 네 개다.

1. **실행과 기능 발견:** 설치 위치를 기준으로 CLI를 호출하고 필요한 도움말·선택지를 찾는 방법.
2. **대상과 데이터 선택:** 종목 식별, 질문에 맞는 데이터 선택, 다른 스킬로 넘길 경계.
3. **기간·단위·조정 해석:** 회계기말·발표일·관측 시각, 통화·비율, 가격 조정의 의미.
4. **조회 범위와 실패 해석:** 빈 반환·부분 성공·조회 제한을 해석하고 다음 행동을 선택하는 원칙.

인자 목록, 라이브러리 구조 설명, 조사 과정과 테스트 기록은 스킬 본문에 중복하지 않는다. 기존 사용자 안내·기여 문서·CI에는 새 스킬에 필요한 부분만 추가한다.

## 4. 구현 순서와 완료 판정

| 단계 | 작업 | 완료 기준 |
|---|---|---|
| 1. 인터페이스·환경 | 합의한 명령 지도·선택지·출력·오류 계약과 잠금 환경 구현 | 도움말·스키마가 외부 조회 없이 동작하고 다른 위치에서도 실행됨 |
| 2. 기능별 TDD | 가격·검색부터 각 기능군을 공개 CLI 경계에서 순차 구현 | 기능별 정상·빈 반환·대표 실패 테스트 통과 |
| 3. 스킬·활용 검증 | 본문 작성, 실제 Yahoo 조회, Claude·Codex 시나리오 실행 | 소스·외부 문서·임시 Python 없이 발견·조회·복구하는 증거 확보 |
| 4. 통합 검토·전달 | 독립 코드·동작 리뷰, 수정과 관련 재검증, CI·기록 정리 | 유효한 문제 해결, 필수 검사 통과, 미검증 범위 명시 |

테스트는 기능 하나씩 실패를 먼저 확인하고 최소 구현으로 통과시킨다. 리팩터링은 검토에서 필요성을 확인한 범위에 한정한다.

파일 변경 단계는 트래커에 완료 기준과 상태를 기록한다. 기존 사용자 변경을 보존하고, 요청과 무관한 코드·포매팅·하네스는 수정하지 않는다.

## 5. 검증·전달과 현재 근거

### 검증 경계

- **공개 CLI:** 실제 argv, stdout JSON, stderr, 종료 상태를 검증한다. 내부 함수 이름이나 호출 순서에 고정된 테스트는 만들지 않는다.
- **외부 연결:** 통제된 HTTP 응답을 사용하더라도 실제 yfinance의 요청·응답 해석 코드를 통과시킨다. 내부 getter를 모사한 테스트로 연결 검증을 대체하지 않는다.
- **실제 에이전트:** Claude `opus[1m]`·`high`, Codex `gpt-6-astra`·`high`의 실행 기록과 실제 CLI 응답을 확인한다.

### 필수 사례

- 가격의 날짜 경계·시간대·조정 방식과 결측·0 구분.
- 재무표 종류·주기·기간·항목 선택과 통화 맥락.
- 검색 결과에서 정확한 종목 선택.
- 스크리너 필드·값·연산자 발견과 중첩 조건 구성.
- 옵션 만기 발견과 선택 조회, ETF 구성 조회.
- 일정 페이지 이동, 요청 개수, 날짜 의미와 원본 정보 손실.
- 정상·잘못된 종목이 섞인 일부 실패.
- 잘못된 입력, 요청 제한, 상위 오류와 복구 안내.
- 큰 결과를 좁혀 다시 조회하되 조용한 생략이 없는지.
- 스킬 이름 없는 데이터 요청의 사용과 SEC 원문·일반 프로그래밍 요청의 비사용.
- 다른 프로젝트 위치에서의 독립 실행.

실제 조회는 미국 시장을 중심으로 수행하고 다른 시장·자산의 대표 사례도 확인한다. 원본 반환과 CLI 결과를 비교해 변환 과정의 값 변경·누락을 점검한다. 구조 검사나 오프라인 테스트만으로 실제 연결·에이전트 사용까지 검증됐다고 주장하지 않는다.

기존 CI에는 별도 yfinance 잠금 환경 작업을 추가한다. 일반 테스트 작업에서는 이 테스트를 분리해 우연히 설치된 다른 버전으로 실행되지 않게 한다. 실패 수정 후에는 실패한 사례와 변경 영향이 있는 사례를 다시 실행한다.

### 현재 확보한 근거

- 로컬 `1.7.0` 소스의 Python 파일 34개가 공식 PyPI 배포본과 동일함을 확인했다.
- 시스템에는 `1.5.1`이 설치되어 있어 독립 잠금 환경의 필요성을 확인했다.
- 공개 API 대표 호출 20회를 관측했다. 이는 전체 기능이나 값 정확성의 검증 완료를 의미하지 않는다.
- 실적 일정의 캐시·반환 개수 문제와 새 객체를 사용하는 우회를 확인했다.
- 다종목 다운로드가 일부 실패에도 표를 반환하는 동작을 확인했다.
- 초기 독립 조사 두 갈래와 설계 검토 한 차례를 수행했고, 스크리너 조건식의 발견 계약 누락을 계획에 반영했다.
- 새 CLI의 구현·테스트·에이전트 활용 검증은 아직 수행하지 않았다.

위 본문은 승인 시점 계획이며, 이후 구현과 변경 결정·검증 결과는 아래 실행 기록을 따른다. 실행 단계에서 `.claude/plans/260913_yfinance 스킬 구현 계획.md`에 계획·판단 근거·실제 검증 결과를 기록한다. 구현 후에는 브랜치·한국어 커밋·PR·스쿼시 머지 절차를 따르고, 머지 후 기존 Graphify 그래프를 갱신한다.


## 실행 진행표

TaskCreate/TaskUpdate와 검색 인터페이스를 가용 도구 목록에서 확인했으나 제공되지 않아 이 표를 영속 진행 기록으로 사용한다.

| 단계 | 상태 | 완료 판정 |
|---|---|---|
| 인터페이스·환경 | 완료 | 도움말·스키마의 무네트워크 실행, 잠금 환경과 다른 위치 실행 확인 |
| 기능별 TDD | 완료 | 공개 CLI에서 정상·빈 반환·대표 실패 검증, 102개 통과 |
| 스킬·활용 검증 | 완료 | 실제 조회와 두 모델의 발견·조회·복구, 식별자 후속 확인 완료 |
| 통합 검토·전달 | 완료 | 리뷰 수정, Linux CI, PR 머지와 그래프 갱신 완료 |

### 구현·리뷰 기준

- Principle over rail: 정해진 조회 순서 대신 선택과 해석의 이유를 제공한다.
- Interface over document: 인자·선택지·기본값·출력·복구는 실행 인터페이스가 소유한다.
- For user, not developer: 모델이 라이브러리 구조를 공부하지 않고 데이터 목적과 반환 식별자로 다음 호출을 구성한다.
- Dense information: 판단 근거를 남기고 중복·개발 과정·불필요한 문서는 런타임에서 제거한다.
- 리팩터링: 공개 CLI 검증을 유지하며 중복 계약과 잘못된 책임 분리를 수정한다. 파일 수나 추상화 수를 품질로 판단하지 않는다.

### 작업 범위와 기록 위치

기준 커밋은 23916d6, 작업 브랜치는 feat/yfinance-skill이다. 기존 .gitignore 변경, harness-spec 삭제, SEC 계획 이름 변경과 다른 기획·조사 파일은 이 변경에 포함하지 않는다. 구현 중 yfinance 계획 파일도 날짜 접두사 없는 현재 이름으로 정리되어 현재 경로를 유지한다.

런타임 구현 run은 20260913-205147-yfinance-runtime-8ea1이다. 구현자가 95개 테스트·Ruff·독립 위치 실행 기록을 남긴 뒤 부모가 소유권을 인계받아 리뷰 수정과 최종 검증을 수행했다. 요약 정리 대기를 줄이기 위해 실행을 중단했으므로 interrupted 상태 자체를 기능 완료의 증거로 쓰지 않는다. 최종 기준은 아래 실제 명령과 결과다.

### 변경 결정 — 실행 환경 재사용

승인 계획의 `uv --isolated`는 `uv run --frozen --project ...`로 대체한다. 같은 시점의 동일 `--help`를 실측했을 때 프로젝트 환경은 0.65초, 매번 새 격리 환경을 만드는 방식은 42.8초였다. 이 시작 지연은 일부 테스트의 30초 시간 초과와 Claude 스크리너의 420초 시간 초과로도 관측됐다.

프로젝트별 가상환경과 uv.lock으로 시스템 패키지와 분리하며, `.python-version`은 검증한 Python 3.12를 선택한다. `[tool.uv] default-groups=[]`로 조회에는 개발 의존성을 요구하지 않고 테스트만 `--group dev`를 사용한다. `.venv`는 자체 ignore로 Git에서 제외된다. 이 변경은 조회 결과 저장 기능을 도입하는 것이 아니다.

### 독립 리뷰와 수정

문서 리뷰 20260913-210043-yfinance-skill-review-7a11에서는 네 프레임을 위반하는 확정 문제가 없었다. 실행 계약과의 대조는 별도 검증으로 남겼다. 코드 리뷰 20260913-211724-yfinance-code-review-9a84에서는 다음 5개를 확인했다.

| 발견 | 수정·검증 |
|---|---|
| 날짜 누락 후 실적 날짜와 EPS 정렬 손상 | NaT 인덱스를 감지하면 데이터를 정상 반환하지 않고 upstream 오류를 낸다. 짧은 페이지로 종료를 확정하지 않고 remaining=null과 후보 offset을 표시한다. 재현 2개 실패 → 관련 3개 통과. |
| schema와 실행 기본값의 이중 정의 | 고정 limit은 파서에, 조건부 기본값은 resolve_defaults 한곳에 두고 schema도 같은 정책을 계산한다. 재현 실패 → 관련 2개 통과. |
| 빈 응답에 필드 선택 시 invalid 오판 | 필드 목록까지 없는 빈 반환은 빈 상태와 필드 검증 미확인을 보존한다. 목록이 있는 경우의 오타 검증은 유지한다. |
| 선택 값이 모두 null이어도 ok | 공통 is_empty에서 값 부재를 검사해 empty/exit 7로 표시하고 축 정보는 보존한다. 실제 0은 유효값으로 유지한다. 재현 3개 실패 → 날짜·결측 관련 9개 통과. |
| 명시적 빈 날짜를 생략으로 처리 | None만 생략으로 인정하고 빈 문자열은 요청 전에 invalid/exit 2로 거부한다. 가격·옵션·일정에 같은 검증을 적용한다. |

추가로 `screen presets --type etf`가 다른 자산의 프리셋까지 반환하는 사례를 재현하고 공개 Query 클래스 기준으로 필터했다(재현 실패 → 관련 2개 통과). E2E에서 반복된 zsh 명령 문자열 변수 실행 실패는 스킬 진입점에 이유와 직접 호출·함수 사용 방법을 짧게 설명했다. 별도 저장소·참고 문서·SDK 내부 패치는 추가하지 않았다.

### 로컬 검사

- `python3 -m pytest tests/ --ignore=tests/sec --ignore=tests/yfinance -q`: **1023 passed, 40 deselected, 241.18s**. 기존 SNS 테스트 기준선이다.
- `uv run --frozen --group dev --project .claude/skills/yfinance/Scripts python -m pytest tests/yfinance -q`: **102 passed, 63.76s**.
- `uv run --frozen --group dev --project .claude/skills/yfinance/Scripts ruff check --config pyproject.toml .claude/skills/yfinance/Scripts tests/yfinance`: **All checks passed**.
- `uv lock --check --project .claude/skills/yfinance/Scripts`: 통과, 40 packages resolved.
- `validate_harness.py --path . --json`: **errors=0, warnings=0**.
- `git diff --check`: 통과.

HTTP fixture는 합성한 응답이며 세션 쿠키·crumb도 fixture 값이다. 테스트는 전송 경계만 대체하고 실제 yfinance 요청 구성·파싱을 실행한다. 로그는 `.codex-runs/yfinance-runtime/`와 `.tmp/yfinance-acceptance/`에 남겼다. 이 로컬 로그 디렉터리는 배포물에 포함하지 않는다.

### 실제 조회와 모델 검증

AAPL의 2026-08-17 이상·2026-08-22 미만, adjust none, Close/Volume 5행을 같은 잠금 버전의 직접 조회와 대조해 값·날짜 일치를 확인했다. 카탈로그 필드·값, US 시장 상태, most_actives 3개, 시장 실적 일정 3개, AAPL offset 25/limit 1, technology 섹터 개요의 실제 CLI 조회도 성공했다. 종목별 일정은 next_offset=26으로 반환되어 읽은 25행만큼 건너뛰지 않았다. 공시 목록은 실제 80개 중 요청한 1개를 반환했다.

두 모델의 별도 임시 프로젝트에는 스킬 디렉터리를 복사해 설치했다. Claude는 Skill(yfinance)을 호출했고 Codex는 해당 SKILL.md를 로드했다. 실제 모델은 Claude의 opus[1m] 설정이 선택한 claude-opus-5[1m]과 Codex gpt-6-astra(high)다.

| 시나리오 | 결과 |
|---|---|
| AAPL·MSFT의 지정 5거래일, 배당 조정 없는 종가 | 두 모델 모두 종료일 제외·adjust none·USD·시간대를 확인하고 완료 |
| 분기 매출·ETF 보유·옵션 만기 발견과 조회 | 두 모델 모두 CLI로 완료하고 재무 기간·보유 기준일 미확인·계약별 거래 시각을 구분 |
| 다종목 일부 실패 | 두 모델 모두 성공분을 보존하고 404를 상장폐지 증거로 단정하지 않음 |
| 전체 가격 출력 한도 초과 → 최근 한 달 재조회 | 두 모델 모두 too_large를 실제 관측하고 전체 이력을 읽었다고 주장하지 않음 |
| 스크리너 필드·허용값·중첩 조건 | Codex 완료. 최초 Claude는 느린 실행 환경에서 420초 초과. 환경 재사용으로 수정한 후 **74.6초에 완료** |
| 시장 상태·시장 일정·종목 실적 이력 | 두 모델 모두 완료, US 범위·날짜 기준·누락과 공급자 한계 설명 |
| SEC 원문·일반 Python 요청 | 두 모델 모두 yfinance 본문이나 CLI를 호출하지 않음 |

최종 실행 방식의 복합 시나리오 6개 항목은 Claude **122.6초**, Codex **143.6초**에 조회·조건 선택·부분 실패·크기 오류 복구를 완료했다. Claude의 복합 답변에는 TRPCF를 TRP.CF로 적은 식별자 오탈자 1건이 있어, 이를 완전한 정확성 통과로 기록하지 않는다. 반환 식별자를 보고할 때도 그대로 유지해야 하는 이유를 본문에 보강하고 일정 시나리오를 후속 확인한다. CLI 원본 JSON의 식별자는 정확했다.

모델 검증에서 소스·외부 API 문서·임시 Python 통합 코드 없이 동작했는지는 실행 기록으로 확인했다. 실행 한 번의 통과가 모든 향후 요청의 정확성을 보장하지는 않는다.

### 공개 API 대응

| 목적 | 사용하는 공개 API |
|---|---|
| search | Lookup.get_*와 Search.news/lists/research/nav |
| prices | Ticker.history, get_history_metadata, get_info |
| company | get_info/get_shares_full/get_news/get_sec_filings/get_sustainability |
| financials | get_income_stmt/get_balance_sheet/get_cash_flow/get_valuation_measures |
| analysts | 목표가·추천·추천 요약·등급 변경·실적/매출 추정·이력·수정·추세·성장 getter |
| holders | 주요·기관·펀드·내부자 보유/거래 getter |
| fund | get_funds_data의 개요·구성·보유 자산·등급·운영 속성 |
| options | Ticker.options/option_chain |
| screen | EquityQuery/FundQuery/ETFQuery, valid_fields/valid_values, screen, PREDEFINED_SCREENER_QUERIES |
| market | Market.status/summary, Sector/Industry의 공개 데이터 속성 |
| calendar | get_earnings_dates, Calendars.get_*_calendar |

### CI와 전달

시작 시 GitHub workflow Social skill checks(350663910)는 disabled_manually였다. 승인된 Linux CI 검증을 위해 일시적으로 활성화했으며 검증 후 원래 비활성 상태로 돌린다. 이전 Graphify 실행 링크는 사라진 uv tool 환경을 가리켰지만, 기존 전달 기록의 `uvx --from graphifyy` 방식으로 CLI 로딩을 확인했다. 전역 설치·링크는 변경하지 않았으며 머지 후 같은 방식으로 그래프를 갱신한다.

### 최종 전달 완료

- PR #11: https://github.com/tjdwls101010/Agentic-SNS/pull/11 — bbbc28b65c3b98116d65ccd38aa4291bef3bcc70으로 squash merge했다.
- 진행 중 main에 Finviz PR #10이 먼저 병합되어 README 소개와 기본 테스트 제외 목록이 충돌했다. 별도 worktree에서 두 변경을 보존하고 `--ignore=tests/finviz --ignore=tests/yfinance`를 함께 적용했다. yfinance 런타임은 이 통합에서 변경하지 않았다.
- 최종 통합 commit 85f9cdb66be8a8286c916332d84278b59ccc9a08의 Linux CI: Social skill checks run 34758770485에서 yfinance·SEC·offline 모두 success, Finviz skill checks run 34758770489도 success. 앞선 문서 변경 commit의 run 34758347241 역시 모두 success였다. 중복 push 실행은 취소했으며 취소를 테스트 실패로 해석하지 않는다.
- 일시 활성화했던 Social skill checks는 원래 disabled_manually 상태로 복구했다. 기존 Finviz workflow의 active 상태는 유지했다.
- Claude 식별자 후속 시나리오는 72.035초에 완료했고 HELNF·DLMAF·TRPCF를 원본 그대로 보고했다. 이전 복합 답변의 오탈자는 기록에 남겨 한 번의 모델 실행을 무조건적인 정확성 보장으로 해석하지 않는다.
- `uvx --from graphifyy python /Users/seongjin/.codex/skills/Graphify/scripts/build.py .`: exit 0. **2655 nodes / 5997 edges / 180 named communities**, 39 files re-extracted, 289 cached. `graphify query yfinance_cli`로 새 CLI가 그래프에 포함된 것도 확인했다. 그래프는 Git 추적 대상이 아니다.
- main을 원격 머지 결과로 갱신했고 작업 브랜치와 통합 worktree를 정리했다. 체크아웃 중 .gitignore만 일시 보관한 뒤 복원해 사용자의 10줄 삭제와 기존 하네스·SEC 계획 변경을 유지했다. 이 파일들은 커밋하지 않았다.
- 전체 모델·HTTP 실측의 상세 로그는 로컬 `.tmp/yfinance-acceptance/`와 `.codex-runs/`에 보존한다. 독립 설치에 사용한 임시 프로젝트 복사본은 검증 후 제거한다.
