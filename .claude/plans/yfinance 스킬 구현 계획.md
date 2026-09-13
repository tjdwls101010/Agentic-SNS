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

TaskCreate/TaskUpdate와 도구 검색 인터페이스를 가용 도구 목록에서 확인했으나 제공되지 않아 이 표를 영속 진행 기록으로 사용한다.

| 단계 | 상태 | 완료 판정 |
|---|---|---|
| 인터페이스·환경 | 완료 | 도움말·스키마 무네트워크 실행, 잠금 환경과 다른 위치 실행 확인 |
| 기능별 TDD | 완료 | 공개 CLI에서 기능별 정상·빈 반환·대표 실패 검증 |
| 스킬·활용 검증 | 진행 중 | 실제 조회와 Claude·Codex의 발견·조회·복구 기록 |
| 통합 검토·전달 | 진행 중 | 리뷰 수정, 필수 검사·CI 통과, PR 머지와 그래프 갱신 |

### 구현·검토 기준

- Principle over rail: 정해진 조회 순서 대신 선택·해석의 이유를 제공한다.
- Interface over document: 인자·선택지·기본값·출력·오류 복구는 실행 인터페이스가 소유하며 설명을 중복하지 않는다.
- For user, not developer: 모델이 라이브러리 구조를 공부하지 않고 데이터 목적과 반환 식별자로 다음 호출을 구성한다.
- Dense information: 판단 근거는 보존하고 중복·개발 과정·불필요한 문서는 런타임에서 제거한다.
- 리팩터링: 공개 CLI 회귀 검증을 유지하며 중복된 계약, 잘못된 책임 분리, 수정이 여러 파일로 번지는 결합을 검토하고 수정한다. 필요하면 신규 스킬 내부를 재작성하되 추상화 수를 품질로 판단하지 않는다.

### 작업 전 상태

기준 커밋 23916d6, 작업 브랜치 feat/yfinance-skill. 기존 사용자 변경(.gitignore, .claude/harness-spec.md 삭제, 미추적 기획·조사 파일)은 스테이징하거나 되돌리지 않는다.

### 검증 기록 — 구현 초기

- `python3 -m pytest tests/ --ignore=tests/sec --ignore=tests/yfinance -q`: 1023 passed, 40 deselected, 241.18s. 기존 SNS 테스트 기준선이 통과했다.
- `git diff --check`: 통과. 사용자 변경(.gitignore와 harness-spec 삭제)은 별도 보존 중이다.
- GitHub workflow `Social skill checks`는 시작 시 disabled_manually(350663910)였다. CI 검증 단계에서 실행 상태와 결과를 별도로 기록한다.
- 기존 graphify 실행 링크는 사라진 uv tool 환경을 가리켰다. 이전 SEC 전달 기록의 `uvx --from graphifyy` 실행 방식으로 CLI 로딩이 되는 것을 확인했다. 전역 설치나 링크를 변경하지 않았다.
- 런타임 구현 run: 20260913-205147-yfinance-runtime-8ea1. 첫 명령 미구현 red와 scoped schema green을 보고받았으며, 최종 결과에서 실행 기록을 대조한다.

### 중간 검증

- 하네스 검사 `validate_harness.py --path . --json`: errors=0, warnings=0.
- 문서 리뷰 20260913-210043-yfinance-skill-review-7a11: 확정 문제 없음. 런타임의 문법·JSON·실패 관측성은 별도 실행으로 확인한다.
- 실제 가격 비교: AAPL 2026-08-17 이상/2026-08-22 미만, adjust none, Close/Volume 5행이 같은 잠금 yfinance1.7.0 직접 호출의 값·날짜와 일치했다.
- 별도 임시 프로젝트의 가격 E2E: Claude는 Skill(yfinance)을 호출했고 Codex는 해당 SKILL.md를 로드했다. 양쪽 모두 CLI help/schema로 end-exclusive/adjust-none 조건을 찾아 AAPL·MSFT의 5거래일을 조회했다. 소스·외부 문서·임시 Python 없이 완료했다. Claude 실제 모델은 claude-opus-5[1m], Codex는 gpt-6-astra high다. 실행본 .tmp/yfinance-acceptance/claude-prices 및 run 20260913-210610-yfinance-e2e-prices-8445.
- 카탈로그 필드·값, US 시장 상태, most_actives 3개, 시장 실적 일정 3개, AAPL offset25/limit1, technology 섹터 개요의 CLI live 조회 7개가 모두 exit0/status ok를 반환했다. 일정 next_offset은26으로 반환돼 읽은25행만큼 건너뛰지 않았다.
- 사용자 피드백에 따라 문서 리뷰를 반복하지 않고 구현·필수 검증·집약 코드 리뷰를 병행한다.
- 구현 중 계획 파일명이 날짜 접두사 없는 현재 이름으로 변경됐다. 진행표가 포함된 동일 문서를 확인했고 현재 경로를 유지한다. SEC/finviz 등 다른 작업의 변경은 포함하지 않는다.

### 리뷰 수정과 유지보수 정리

코드 리뷰 20260913-211724-yfinance-code-review-9a84의 유효한 발견5개를 대조했다. 빈 필드 반환의 오류분류는 구현자가 마지막에 이미 수정했고, 나머지는 공개CLI 재현을 먼저 확인해 수정했다.

| 발견 | 수정과 근거 |
|---|---|
| 실적 날짜 누락 후 EPS/날짜 정렬 손상 | NaT 인덱스를 감지하면 데이터를 정상 반환하지 않고 upstream 오류. 짧은 페이지로 종료를 확정하지 않고 remaining=null/후보offset을 표시. review-earnings-red/green에서 2개재현 후 관련3개통과 |
| schema/실행 기본값 이중 정의 | 고정 limit은파서에, 조건부기본값은resolve_defaults 한곳에두고schema가동일정책을계산. review-defaults-red/green 재현·통과 |
| 빈 응답 필드 선택이invalid로변환 | 필드목록까지없는빈반환은빈상태와검증미확인을보존. 기존필드가있을때오타검증유지 |
| 모든선택값null인데ok | 공통is_empty에서값부재를검사하고empty/7,축정보보존. 원래0은유효값. review-null-red 및 review-date-null-green(관련9개통과) |
| 명시적빈날짜가가까운만기로대체 | None만생략으로인정,빈문자열은요청전에invalid/2. 가격·일정에도같은검증적용 |

추가로 screen presets의 --type이무시되는사례를재현해공개Query클래스기준으로필터했다(preset-red/green, 관련2개통과). E2E에서반복된zsh명령문자열변수실패는스킬진입점에이유와직접호출/함수방법을짧게설명했다. 새저장소·참고문서·내부SDK패치는추가하지않았다.

### 실행 환경 결정 변경 — --isolated 대체

승인계획의 매번새환경을만드는 uv --isolated는프로젝트환경재사용으로대체한다. 같은시점의동일 --help를실측했을때프로젝트환경0.65초,isolated환경42.8초였고,새격리환경의import지연이테스트30초timeout과Claude스크리너420초timeout을일으켰다. uv --help도 --isolated는격리환경생성, --active만현재활성환경을우선한다고설명한다.

실행은 `uv run --frozen --project ...`로프로젝트별가상환경을재사용한다. uv.lock은계속의존성을고정하며 `.python-version`은검증한3.12를선택한다. 프로젝트외부시스템yfinance에의존하지않고, `.venv`는자체ignore로Git에서제외된다. `[tool.uv] default-groups=[]`로조회에는개발의존성을요구하지않고테스트는 --group dev로실행한다. 이변경은데이터저장기능도입이아니다.

### 로컬 최종 검사

- `uv run --frozen --group dev --project .claude/skills/yfinance/Scripts python -m pytest tests/yfinance -q`: **102 passed, 63.76s**.
- 같은환경의 `ruff check --config pyproject.toml .claude/skills/yfinance/Scripts tests/yfinance`: **All checks passed**.
- `validate_harness.py --path . --json`: **errors=0, warnings=0**.
- `git diff --check`: 통과.
- 초기 런타임 구현자는95개테스트와Ruff/독립이동검증기록을남겼다. 요약정리대기를줄이기위해부모가실행을중단하고소유권을인계받아위리뷰수정을완료했다. 구현run종료상태(interrupted)를최종기능완료증거로쓰지않으며,부모의실행결과가최종기준이다.

### CLI와 공개API 대응

| 데이터목적 | 원본공개API |
|---|---|
| search | Lookup.get_* 및 Search.news/lists/research/nav |
| prices | Ticker.history, get_history_metadata, get_info |
| company | get_info/get_shares_full/get_news/get_sec_filings/get_sustainability |
| financials | get_income_stmt/get_balance_sheet/get_cash_flow/get_valuation_measures |
| analysts | get_analyst_price_targets/get_recommendations/get_recommendations_summary/get_upgrades_downgrades/get_*estimate/get_earnings_history/get_eps_revisions/get_eps_trend/get_growth_estimates |
| holders | get_major_holders/get_institutional_holders/get_mutualfund_holders/get_insider_* |
| fund | get_funds_data의개요·구성·보유자산·등급·운영속성 |
| options | Ticker.options/option_chain |
| screen | EquityQuery/FundQuery/ETFQuery의valid_fields/valid_values,to_dict,screen,PREDEFINED_SCREENER_QUERIES |
| market | Market.status/summary,Sector/Industry의공개데이터속성 |
| calendar | get_earnings_dates,Calendars.get_*_calendar |

테스트fixture는HTTP전송경계만대체하며라이브러리의요청구성과파싱은실행한다. 가격/재무/펀드/옵션/시장/일정/스크리너등의실제연결과모델활용결과는별도기록한다.
