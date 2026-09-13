# SEC 원문 탐색 스킬 구현 계획

## 1. 목표와 확정 범위

기업의 EDGAR 공시와 첨부자료에서 정확한 기업·기간의 원문을 찾고, 필요한 부분만 점진적으로 읽어 근거를 확보하는 sec 스킬을 구현한다.

- 직접 HTTPS 접근을 사용한다. SEC 로그인이나 Aside 설치는 필수가 아니다. 정상 요청자 식별정보로 직접 접근을 실측했다.
- edgartools 5.58.0을 자료 처리 부품으로 사용한다. 기존 MCP·터미널 출력을 그대로 감싸거나 라이브러리를 포크하지 않는다.
- 모델이 질문에 맞게 탐색 경로를 선택한다. 정해진 순서를 강제하거나 양식별 섹션 경계의 완전 자동화를 약속하지 않는다.
- 본문·표·각주·이미지·첨부의 탐색과 원문 연결을 제공한다. 필요한 시각적 확인은 기존 도구로 이어간다.
- SEC 규칙·집행 자료·뉴스, 재무 수치 표준화, 전용 문서 비교, 대량 수집·내보내기, 자동 감시, 자체 OCR은 제외한다.
- E2E와 독립 코드 리뷰는 Codex gpt-6-astra, medium으로 수행한다. Claude E2E는 실행하지 않는다.

승인 계획과 실측·검증 기록은 실행 시작 시 .claude/plans/260913_sec 스킬 구현 계획.md에 기록한다. 계획 단계에서는 구현 파일을 변경하지 않는
다.

## 2. 처리 구조와 공개 계약

### 네트워크는 한 경계에서 통제한다

transport.py가 모든 네트워크 요청을 담당한다. 받은 자료를 라이브러리에 전달하며, 추가 다운로드를 일으키는 SDK 편의 속성은 사용 경로에서 제외
한다.

- 요청자 식별, 인증서 검증, URL·리다이렉트 검증, 요청 간격, 유한 재시도, 응답 판정을 공통 경계에 둔다.
- 정식 SEC 호스트의 읽기 경로만 사용한다. 임의 미러 설정이나 외부 링크를 자동으로 따라가지 않는다.
- sec 프로세스끼리는 SQLite에 요청 시점을 예약해 기본 초당 2회 이하로 조절한다. 재시도와 리다이렉트도 각각 검증·예약한다.
- 403·429는 자동 반복 요청하지 않고 복구 방법을 반환한다. 일시적인 연결 오류·5xx만 제한적으로 재시도한다.
- 다른 프로그램이나 다른 기기의 요청까지 통제한다고 주장하지 않는다.

SEC의 공개 API는 인증·API 키 없이 접근할 수 있으며, 공식 요청 한도는 사용자당 초당 10회다. SEC API 설명
(https://www.sec.gov/search-filings/edgar-application-programming-interfaces), 개발자 접근 지침
(https://www.sec.gov/about/developer-resources)

### 조회 응답의 정보를 보존한다

다음 공식 인터페이스를 사용한다.

  대상                     인터페이스
━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  티커·CIK 식별            www.sec.gov/files/company_tickers_exchange.json
───────────────────────  ─────────────────────────────────────────────────────────────────────────────
  기업 공시 이력           data.sec.gov/submissions/CIK##########.json 및 응답에 연결된 과거 이력 파일
───────────────────────  ─────────────────────────────────────────────────────────────────────────────
  기업명 후보·본문 검색    efts.sec.gov/LATEST/search-index
───────────────────────  ─────────────────────────────────────────────────────────────────────────────
  공시·첨부 목록           해당 accession의 SEC 공시 인덱스
───────────────────────  ─────────────────────────────────────────────────────────────────────────────
  원문                     공시 인덱스에 연결된 문서 URL

JSON 응답은 필요한 원본 필드를 보존하는 얇은 코드로 처리한다. 고수준 SDK가 생략하는 복수 제출인, 첨부 파일명, 총수의 정확성, 시간 초과 등을
추측으로 복원하지 않는다.

HTML·첨부 목록·SGML 처리에는 HTMLParser.parse, Attachments.load, FilingSGML.from_text처럼 받은 입력을 처리하는 기능을 재사용한다.

### 공개 CLI

텍스트 출력을 기본으로 하고 --json을 제공한다. 인자·기본값·출력 필드·오류 복구 방법은 CLI의 --help와 schema가 소유한다.

  명령              계약
━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  company           이름·티커·CIK로 기업 후보와 식별 근거를 반환한다. 모호한 이름을 조용히 한 기업으로 바꾸지 않는다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  filings           제출일·보고 대상일·양식·정정 여부로 조회하고 과거 목록을 이어본다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  search            공시·첨부 본문을 기업·기간·양식·정렬 조건으로 검색한다. 첨부 단위 결과를 공시 하나로 뭉개지 않는다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  open              SEC URL·공시 식별자로 시작한다. 공시에는 문서·첨부 목록을, 문서에는 저장 사본 ID와 구조 요약을 반환한다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  outline           실제 목차·앵커와 탐지된 제목을 구분하고 재사용 가능한 탐색 위치를 제공한다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  find              선택한 문서의 본문·표에서 기본적으로 대소문자를 구분하지 않는 문자열 검색을 수행한다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  read              지정한 내부 위치·범위를 읽고 나머지의 이어읽기 위치를 반환한다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  table             표의 행·셀을 제목·단위·헤더·각주 문맥과 함께 읽는다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  links             내부 링크·첨부·이미지의 실제 주소와 주변 문맥을 반환한다.
────────────────  ──────────────────────────────────────────────────────────────────────────────────────────────────────────
  doctor, schema    설정·연결을 진단하고 입력·출력 계약을 설명한다.

목록은 기본 20개, 읽기 출력은 기본 12,000자로 제한한다. 출력량은 도구가 계산하며, 반환하지 않은 내용과 다음 위치를 명시한다. 긴 셀도 조용히
잘라 버리지 않는다.

### 기간·검색·이어읽기

- 제출일과 보고 대상일을 별도로 표시한다. reportDate를 본문의 모든 수치에 적용되는 기간으로 간주하지 않는다.
- 원본과 정정 공시는 별도로 유지한다. 정정 포함이 기본이며 제외·정정만 조회도 제공한다.
- 잘못된 accession을 최신 공시로 대체하지 않는다.
- 본문 검색 기본 범위는 2001년부터 현재까지이며 최신 제출일순이다. 관련도순도 선택할 수 있다.
- 과거 공시 이력과 원문 URL 접근은 본문 검색의 시작 연도와 구분한다.
- EFTS의 원격 페이지 100개와 CLI 출력 개수를 분리한다. 10,000건 검색 한도, 하한인 총수, 시간 초과, 빈 결과를 구분한다.
- 실제로 받은 결과만 고정된 사본이다. 새 원격 페이지에는 조회 시각을 기록하고 문서 식별자로 중복을 제거한다. 아직 받지 않은 페이지까지 최초
  시점에 고정됐다고 표현하지 않는다.

- 검색·읽기·이어읽기는 동일한 저장 사본과 위치 계약을 사용한다. 질의·사본 변경이나 커서 불일치는 조용히 재해석하지 않는다.

### 원문 보존과 문서 읽기

공개 문서 계약은 SourceDocument → DocumentSnapshot과 그 사본에 대한 outline/find/read/table/links다.

- 원본 bytes, 선택한 인코딩, 원본 DOM, 탐색용 본문·표·이미지·링크를 함께 보존한다.
- 기존 범용 디코딩 기능인 UnicodeDammit을 활용해 문자열을 만든 뒤 HTML 파서에 전달한다. 인코딩 추정·충돌·손실 여부를 기록한다.
- 표의 최종 근거는 원본 DOM이다. 셀의 직접 텍스트·중첩 내용·tail·각주 링크·이미지를 보존하며 SDK의 cell.text()만 신뢰하지 않는다.
- 파싱용 사본의 추적 ID로 원본과 연결한다. 실제 SEC 앵커와 내부 위치는 별도로 관리한다.
- 실제 앵커는 원본에서 확인한 경우에만 원문 링크로 제공한다. 매핑이 불확실하면 위치를 만들어 내지 않고 원문 링크와 검색 경로를 제공한다.
- 내부 ID는 저장한 사본과 블록 순서에 연결한다. 재파싱마다 바뀌는 SDK UUID에 의존하지 않는다.
- reader.py는 네트워크 요청이나 재파싱을 하지 않는다. 본문 검색과 발췌가 각자 다른 변환 경로를 갖지 않게 한다.
- XML은 태그·상위 항목·반복 레코드 문맥을 보존하고 외부 엔티티를 해석하지 않는다.
- TXT·SGML은 문서와 첨부의 경계를 보존한다. PDF·이미지는 실제 원문 접근 경로를 제공한다.
- 목차 없음, 파싱 실패, 지원하지 않는 형식, 접근 실패를 “정보 없음”으로 바꾸지 않는다. 선택 범위의 반환 완료와 문서 전체의 추출 완전성을 구
  분한다.

## 3. 목표 구조·설정·스킬 문서

```text
.claude/skills/sec/
├── SKILL.md
└── Scripts/
    ├── .env  # 로컬 전용, Git 제외
    ├── .env.example
    ├── document.py
    ├── filings.py
    ├── output.py
    ├── pyproject.toml
    ├── reader.py
    ├── sec.py
    ├── store.py
    ├── transport.py
    └── uv.lock

tests/sec/
├── fixtures/
│   ├── documents/
│   │   ├── README.md
│   │   ├── apple.html.gz
│   │   ├── asml.html
│   │   ├── expected.json
│   │   ├── form4.xml
│   │   ├── microsoft-expected.json
│   │   ├── microsoft.html.gz
│   │   ├── old.txt
│   │   └── provenance.json
│   ├── apple-index-live.html
│   ├── apple-live.json
│   ├── apple-submissions.json
│   ├── company-name-live.json
│   ├── efts-live.json
│   ├── filing-index.html
│   ├── provenance-notes.json
│   ├── provenance.json
│   └── tickers-live.json
├── conftest.py
├── test_cli.py
├── test_cli_documents.py
├── test_documents.py
└── test_live.py
```

이 트리는 책임 경계를 반영한 목표 구조다. 공개 계약과 기능 범위를 유지하는 내부 분리·통합은 리팩터링에서 조정할 수 있다. 최종 리뷰에서 계획
파일의 트리를 실제 코드와 일치시켜야 완료다.

### 실행·설정

- Python 3.11 이상을 대상으로 한다.
- edgartools==5.58.0, python-dotenv==1.2.3과 실제 사용하는 의존성을 선언하고 uv.lock으로 검증 환경을 고정한다.
- 다음 실행 형태를 사용한다.

uv run --isolated --frozen --project "<스킬 경로>" python "<스킬 경로>/Scripts/sec.py" …

- 설정은 성진이 지정한 Scripts/.env의 EDGAR_IDENTITY에서 읽는다. 해당 실행의 프로세스 환경에 전달하며 다른 계정의 이메일을 자동 추측하지 않
  는다.

- .env.example에는 형식만 제공한다. 실제 .env는 Git에서 제외하고 이메일을 문서·진단 출력·로그에 노출하지 않는다.
- --help와 schema는 이메일 없이 사용할 수 있다.
- 저장 사본과 검색 상태는 사용자 캐시 디렉터리에 둔다. 다른 스킬이나 .tmp 참고 저장소를 런타임에 참조하지 않는다.
- 새 후크·에이전트·워크플로·전역 권한 설정은 추가하지 않는다.

### SKILL.md 구성

1. Purpose and entry point — 제공하는 능력과 CLI 진입점
2. Choose the company and period — 기업·제출일·보고 기간·정정을 구분하는 이유
3. Follow evidence through a filing — 질문에 맞게 본문과 첨부를 선택하는 판단
4. Read text, tables and images — 발췌와 비정형 자료에서 문맥을 보존하는 기준
5. What an incomplete read means — 읽은 범위와 미확인 범위를 해석하는 기준

별도 non-html.md나 references/ 폴더는 만들지 않는다.

네 가지 작성 원칙을 적용한다.

- principle over rail: 고정된 탐색 순서 대신 판단 이유와 실제 함정을 설명한다.
- interface over document: 명령 명세·기본값·복구 방법을 문서에 중복하지 않는다.
- for user not developer: 사용하는 모델에게 필요한 판단만 담고 개발 이력은 계획·검증 기록에 둔다.
- dense information: 일반적인 SEC 백과 설명이나 불필요한 참조 분리를 추가하지 않는다.

트리거는 SEC·EDGAR·미국 공시·양식명·공시 URL을 포함한다. SEC 규정·집행, 현재 주가·일반 뉴스, 초 단위 sec와 구분한다.

## 4. TDD·리팩터링·단계별 완료 기준

실행 시작 시 트래커를 열고 각 단계의 완료 조건을 기록한다.

### 기능마다 수행하는 절차

1. 합의한 공개 CLI와 문서 읽기 계약에서 재현 테스트를 작성한다.
2. 요구 동작이 없어서 실패하는지 확인한다. 환경·import 오류를 유효한 재현으로 간주하지 않는다.
3. 테스트를 통과시키는 최소 구현을 한다.
4. 동작을 고정한 상태에서 중복·불필요한 추상화·책임 분리를 검토하고 리팩터링한다.
5. 공유 함수의 모든 호출 경로와 관련 테스트를 다시 확인한다.
6. 동작 검증과 리팩터링 검토가 모두 끝나야 기능을 완료 처리한다.

리팩터링에는 줄인 유지보수 문제와 동작 보존 근거를 기록한다. 바꿀 근거가 없으면 억지로 변경하지 않는다. 의도적으로 남긴 한계에는 # 성진: <한
계>, <바꿀 조건> 주석을 남긴다.

### 구현 단계

  단계                 작업                                             완료 판정
━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 실행·계약 기반    의존성 잠금, .env, CLI·진단, 테스트 자료 출처    깨끗한 환경의 도움말·설정 진단과 .env 제외 확인
───────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────────────────────
  2. 공시 탐색         기업·기간·공시·첨부·검색·이어보기                정확한 식별자·기간·첨부 반환, 과거 목록·정정·부분 검색 구분
───────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────────────────────
  3. 문서 읽기         본문·표·이미지·원문 위치·사본·커서               긴 본문·셀, 비 UTF-8, 중첩 셀·각주·이미지, 이어읽기 재현 통과
───────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────────────────────
  4. 통합 리팩터링     공통 경계·호출 관계·중복·라이브러리 의존 정리    아래 여섯 기준 충족, 관련 테스트 재통과, 실제 구조 기록
───────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────────────────────
  5. 스킬·배포 연결    SKILL.md, README·사용 안내, CI                   독립 설치·잠긴 환경 실행·하네스 구조 검사·기존 테스트 통과
───────────────────  ───────────────────────────────────────────────  ───────────────────────────────────────────────────────────────
  6. 실제 사용·전달    Codex E2E·최종 리뷰·PR·머지·그래프 갱신          승인한 시나리오와 전달 절차 완료, 실제 결과 기록

### 통합 리팩터링의 여섯 완료 기준

- 요청 제한·URL 검증·설정·오류 판정의 구현이 한곳에 있다.
- 검색·읽기·이어읽기의 내용과 위치가 같은 사본을 가리킨다.
- 변환 경로가 달라도 본문·표·각주·이미지가 조용히 사라지지 않는다.
- CLI 곳곳이 SDK 내부 구조에 직접 의존하지 않는다.
- 기존 기능으로 대체할 코드, 사용하지 않는 분기, 불필요한 계층이 정리됐다.
- 테스트가 내부 호출 순서 대신 공개 동작을 검증해 내부 교체를 허용한다.

리팩터링 범위는 새 sec와 필요한 연결부다. 기존 SNS 스킬 전체를 개편하지 않는다.

## 5. 검증·리뷰·전달

- Microsoft 긴 위험요인의 뒤쪽 문장까지 접근
- Apple 표의 연도·단위·셀·병합 구조 보존
- ASML 이미지 12개와 텍스트·실제 원문 URL 연결
- Form 4 XML, 과거 일반 텍스트, 목차 없는 문서
- 긴 표 셀, 여러 div 사이의 직접 텍스트·tail, 셀 내부 이미지·각주
- Windows-1252 등 비 UTF-8 문자 보존
- 403·429·HTTP 200 오류 응답·부분 검색·검색 한도
- 잘못된 기업·공시 식별자, 변경된 질의·사본·커서, 캐시 손상
- 허용하지 않는 URL·리다이렉트·경로

기대값은 SEC 원문에서 독립적으로 확인한다. 현재 구현의 출력이나 이상치 표시를 정답으로 복사하지 않는다. 오프라인 테스트는 실제 HTTP 기록을
외부 경계에서 재생하고, 별도 라이브 확인으로 그 경계를 검증한다.

계획 단계의 주요 근거는 다음과 같다.

- 정기보고서 54건에서 파싱 예외와 섹션 0개인 결과는 없었다. 길이 이상 표시 14건은 실패율로 해석하지 않는다.
- 기본 텍스트 렌더러의 긴 셀 잘림, 중첩 셀의 직접 텍스트 누락, 비 UTF-8 bytes의 문자 손상을 재현했다.
- 원본 DOM 연결, 디코딩 후 전달, 이미지 URL·원문 앵커 접근 경로를 확인했다.
- 공개 패키지와 로컬 사본의 핵심 파일 8개가 일치했다.
- EFTS는 10,000건을 넘는 요청에서 HTTP 200으로 오류를 반환할 수 있음을 실측했다.

### Codex 검증

- 공시 탐색·문서 읽기·최종 통합의 세 지점에서 독립 코드 리뷰를 수행한다.
- 리뷰에서 발견한 버그도 재현 테스트부터 추가한다.
- E2E는 격리된 작업 사본·캐시에서 정상 탐색 3개와 인접 요청 2개를 새 Codex 세션으로 실행한다.
- 최신 공시 선택, 긴 본문 탐색, 첨부·시각 자료 연결, 스킬 오발 여부를 실제 기록으로 판정한다.
- 막연히 지적이 0개가 될 때까지 반복하지 않는다. 실제로 도달 가능한 결함과 승인한 합격 조건으로 종료한다.
- Claude E2E를 실행하지 않았다는 사실은 검증 기록에 남긴다.

### Git·최종 산출물

현재 사용자 변경인 .claude/harness-spec.md 삭제, .gitignore 수정, 입력 문서를 보존하고 요청에 해당하는 변경만 커밋한다.

기존 지시에 따라 브랜치 생성 → 한국어 커밋·PR → 푸시 → squash merge까지 진행한다. PR 본문은 저장소 템플릿을 따르고 실제 실행 명령과 결과 수
치를 기록한다. 머지 후 Graphify 스킬의 방법으로 그래프를 갱신한다. 현재 끊어진 전역 실행 파일 대신 검증한 uvx 환경을 사용할 수 있다.

실제 코드, 계획 파일의 최종 디렉터리 트리, 검증 기록이 일치해야 완료다. 결과 보고에는 변경 이유, 실행한 검사, 실제 통과 수, 라이브·E2E 근거
와 남은 미검증 범위를 남긴다.

## 6. 실행 트래커 (2026-09-13)

승인된 공개 CLI와 SourceDocument → DocumentSnapshot → outline/find/read/table/links가 테스트 seam이다. Skill·TaskCreate·ToolSearch는 현재 노출된 전체 도구 목록에 없으므로 스킬 파일을 읽고 이 파일을 영속 트래커로 사용한다. 원래 사용자 변경인 `.claude/harness-spec.md` 삭제와 `.gitignore` 기존 수정, 입력 문서, 실제 `.env`는 보존한다.

| 단계 | 상태 | 완료 판정 |
|---|---|---|
| 1. 실행·계약 기반 | 완료 | 깨끗한 환경 도움말·설정 진단과 `.env` 제외 확인 |
| 2. 공시 탐색 | 완료 | 정확한 식별자·기간·첨부 반환, 과거 목록·정정·부분 검색 구분 |
| 3. 문서 읽기 | 완료 | 긴 본문·셀, 비 UTF-8, 중첩 셀·각주·이미지, 이어읽기 재현 통과 |
| 4. 통합 리팩터링 | 완료 | 여섯 경계 기준 충족, 관련 테스트 재통과, 실제 구조 기록 |
| 5. 스킬·배포 연결 | 완료 | 독립 설치·잠긴 환경 실행·하네스 구조 검사·기존 테스트 통과 |
| 6. 실제 사용·전달 | 완료 | Codex 정상 3개·인접 2개 E2E, 세 시점 리뷰, PR·머지·그래프 갱신 및 근거 기록 |

### 저작 원칙 적용

사용자가 재확인한 harness-creator의 principle over rail / interface over document / for user not developer / dense information을 적용한다. 기존 승인을 유지하므로 새 인터뷰·후크·권한·에이전트 파일은 만들지 않는다. SKILL.md는 기업·기간·첨부·범위 완전성의 판단 이유를 설명하고, 옵션과 출력 계약은 help/schema로 보낸다. E2E는 승인대로 Claude runner 대신 Codex gpt-6-astra medium의 격리 세션을 사용하고 실행과 판정은 분리한다.

공시 탐색 구현과 문서 읽기 구현은 Codex의 서로 다른 세션에 파일 소유권을 분리했다. 전자는 CLI·store·transport·filings, 후자는 document·reader와 해당 테스트를 맡는다. 독립 리뷰는 구현 세션과 분리한다.

### 기존 기능 검증 (진행 중)

- `node --test tests/facebook/js/*.js tests/reddit/js/*.js tests/threads/js/*.js tests/twitter/js/*.js tests/naver_blog/js/*.js`: 70 passed, 0 failed.
- `uv run --isolated --no-project --with ruff ruff check --config pyproject.toml .claude/skills/facebook/scripts tests/facebook .claude/skills/reddit/scripts tests/reddit .claude/skills/threads/scripts tests/threads .claude/skills/twitter/scripts tests/twitter .claude/skills/naver-blog/scripts tests/naver_blog`: All checks passed.
- 각 SNS의 `tests/<skill>/tools/check_fixtures_pii.py` 실행: 다섯 스킬 모두 통과(구조적 검사이며 자유 텍스트 비공개 정보 부재의 증명은 아님).
- `python3 /Users/seongjin/.codex/skills/harness-creator/scripts/validate_harness.py --path . --json`: 현재 errors 0, warnings 0. 완성 시 다시 검사한다.
- `python3 /Users/seongjin/.codex/skills/.system/skill-creator/scripts/quick_validate.py .claude/skills/sec`: Skill is valid.

- `uv run --isolated --no-project --with pytest==8.4.2 python -m pytest tests/ --ignore=tests/sec`: **1023 passed, 40 deselected**, 240.10초.

### 독립 원문 판정 근거

Microsoft submissions의 최신 10-K는 accession `0001193125-26-323660`, 제출일 `2026-07-29`, reportDate `2026-06-30`이다. 해당 원문을 구현 parser와 별개로 DOM 텍스트로 읽어 Item 1B 직전의 인재 채용·유지 및 노조 관련 위험 문장을 확인했다. 원문 제목은 `UNRESOLVE D STAFF COMMENTS`처럼 분리되어 있어 고정 문구 일치만으로 섹션 끝을 판정할 수 없다. ASML 원문 DOM에는 실제 `img` 12개가 있다. 원문 URL·sha256·확인 시각은 fixture provenance와 E2E 기록에 남긴다.

### 공시 탐색 독립 리뷰

Codex `gpt-6-astra`, `medium`, run `20260913-141741-sec-review-discovery-f833`에서 XSL primaryDocument 거부, 잘못된 인덱스 연결, HTTP 200 본문 문자열 오탐, 역사적 TXT·ixviewer URL 거부, 재방문 원격 커서의 비고정 결과, 기업명 검색 shard 실패 표시 누락을 재현했다. 이를 CLI 회귀 테스트와 공유 경계 수정으로 처리한다. 읽기 전용 리뷰 샌드박스의 uv cache 접근 제한 때문에 frozen 전체 suite는 시작 전 실패했으며, 기존 interpreter의 help/schema 검사 2개와 메모리 재현을 수행했다. 루트의 전체 검증과 구분한다.

### 문서 읽기 독립 리뷰

Codex `gpt-6-astra`, `medium`, run `20260913-142236-sec-review-document-1aa2`는 네트워크 차단 상태에서 원문 fixture 5개의 SHA256과 MSFT 위험요인 끝·Apple 표의 3개 연도/단위/15열 병합·ASML 이미지 12개 실제 URL을 대조했다. 기존 suite 23 passed 외에 독립 재현 4 pass/5 fail: 중첩 숫자 셀 붙음, 인라인 앵커의 단어 분리, next_position의 미반환 줄바꿈 누락, 명시적 XML 내 p 태그의 HTML 오분류, read에 존재하는 블록 간 문자열을 find가 찾지 못함. 공개 seam 재현 테스트를 먼저 추가해 공통 canonical text와 DOM 경계에서 수정한다. CLI·라이브·독립 설치는 해당 리뷰에서 실행하지 않았다.

### 독립 설치 확인

스킬 디렉터리만 공백이 있는 별도 임시 경로로 복사하고 저장소 밖 `/tmp`에서 `uv run --isolated --frozen --project <복사 경로> python <복사 경로>/Scripts/sec.py`로 실행했다. `.env` 없는 `--help`, `schema --json`은 exit 0, `doctor --json`은 예상한 설정 오류 exit 2, 로컬 identity를 비공개 복사한 뒤 `doctor --live --json`은 exit 0 및 connection=ok였다. 네 검사 모두 예상 결과와 일치했다. 실제 identity는 stdout·검증 기록에 포함하지 않았다.

### 공시 리뷰 수정 및 CLI 통합 완료 시점

Run `20260913-142222-sec-core-fixes-b720`에서 XSL 경로, 인덱스·리다이렉트의 CIK/accession 일치, 정상 JSON의 차단 문구, legacy TXT/viewer 정규화, 원격 커서 재생을 각 CLI 재현 테스트 후 수정했다. 기업명 shard 실패는 이전 공통 `search_status` 수정으로 이미 해결되어 재현이 바로 통과했으며 인위적인 red를 만들지 않았다. SQLite cursor→결과 연결도 질의와 원문 해시에 결합해 캐시 손상이 다른 결과로 재해석되지 않게 했다.

`open → outline/find/read/table/links`는 받은 content-type을 전달하고 캐시 읽기에 identity나 네트워크를 요구하지 않는다. 해당 시점 `uv run --frozen --project .claude/skills/sec --group dev pytest -q tests/sec`는 **57 passed, 1 skipped**, `SEC_LIVE=1 uv run --isolated --frozen --project .claude/skills/sec --group dev pytest -q tests/sec/test_live.py`는 **1 passed**, 소유 파일 Ruff는 통과했다. 문서 리뷰 후속 수정이 진행 중이므로 최종 수치는 이후 통합 검사로 갱신한다. 기본 isolated frozen runtime에서 edgartools 5.58.0 / python-dotenv 1.2.3을 확인했고 pytest와 ruff는 설치되지 않았다.

공통 처리 정리: 날짜·정정은 `matches`, 목록 반환은 `listing`, EFTS 불완전성은 `search_status`, URL/viewer/리다이렉트는 `validate_url`과 `filing_location`, 불변 커서 재생은 dispatch 한 곳에서 처리한다. 원자적 사본 게시로 부분 기록 노출을 피했고 argparse 정의에서 schema 입력을 생성해 명령별 사본을 없앴다.

### 문서 리뷰 수정 및 루트 통합 재현

문서 리뷰 5개 항목을 각각 공개 seam에서 red→green으로 수정했다. 중첩 표의 셀 경계, 인라인 앵커 offset, next_position의 줄바꿈, 명시적 XML 우선 판정, 블록 간 find/read를 하나의 canonical 문자열로 연결했다. 커서는 변경된 계약 version 2에 결합했다. 독립 재현 스크립트 재실행은 **9 passed / 0 failed**, 문서 suite는 **35 passed**였다. Microsoft·Apple 원문 HTML 10,089,281 bytes를 gzip 449,806 bytes로 무손실 저장했고 5개 원본 SHA256을 확인했다.

루트의 실제 Microsoft 첫 읽기에서 숨겨진 iXBRL 메타데이터가 일반 본문에 섞이는 것을 확인했다. 두 네임스페이스의 공개 snapshot→read/find 재현은 **2 failed** 후 **2 passed**로 바뀌었다. 공식 inlineXBRL 네임스페이스의 header/hidden을 본문 탐색에서 제외하고 그 사실을 warnings에 남기며, 원본 bytes·DOM은 보존한다. SDK 표 탐색에서도 제외된 비본문 영역이 돌아오지 않도록 방문한 DOM에 대해서만 표를 만든다.

E2E의 기본 `schema` 호출은 스키마 내부의 error 명세를 실제 오류로 판정하는 렌더러 버그를 드러냈다. `test_schema_default_text_works_without_identity`가 **1 failed**인 것을 확인한 뒤, 실제 오류 envelope만 특수 렌더링하도록 공통 output 경계를 수정했다. schema/doctor 관련 검사는 **4 passed, 25 deselected**였다. 수정된 스킬의 새 격리 사본에서 Apple E2E를 재실행한다.

### 최종 통합 후속 수정

세 번째 독립 리뷰는 앞선 수정을 확인하고 SKILL.md가 네 작성 원칙을 충족한다고 판정했다. 유일한 추가 결함은 iXBRL 메타데이터가 표 셀의 별도 DOM 텍스트 경로에 남는 것이었다. 루트 공개 seam 재현은 **1 failed** 후 **3 nonbody passed**로 바뀌었고, `_dom_text`의 모든 호출자(셀·제목·각주)에 동일한 제외 태그를 전달했다. 원문 bytes는 보존한다. 리뷰의 해당 항목만 재검증해 종료 여부를 판정한다.

E2E의 캐시 읽기 지연을 별도 실행과 10초 traceback으로 조사한 결과, document 모듈의 전역 SDK import가 PyArrow 로딩까지 일으켰다. 파싱에만 필요한 SDK import를 해당 함수로 옮겼으며 캐시 읽기는 SDK를 불러오지 않는다. 같은 로컬 사본 읽기의 해당 환경 관찰은 78.86초 → 2.22초였으며 일반적인 성능 보장이나 벤치마크로 해석하지 않는다.

초기 정상 E2E는 기본 schema 버그와 import 지연을 드러내는 진단으로 남기고 최종 합격으로 세지 않는다. seconds/집행 자료 인접 요청 두 세션은 SEC 스킬 호출 없이 완료했다. 정상 3개는 최종 수정 사본과 새 캐시를 가진 새 Codex 세션(group `sec-e2e-final`)에서 다시 실행한다.

### 최종 코드 검증 결과

- `uv run --frozen --python 3.11 --group dev --project .claude/skills/sec python -m pytest tests/sec -q`: **72 passed, 1 skipped**, 80.72초. skipped는 opt-in 라이브 1개다.
- `SEC_LIVE=1 uv run --isolated --frozen --python 3.11 --group dev --project .claude/skills/sec python -m pytest tests/sec/test_live.py -q`: **1 passed**, 24.57초. 회사·기간·관련도 검색·첨부 목록·원문 저장·사본 find→read까지 실제 SEC 경계를 확인했다.
- `uv run --isolated --frozen --group dev --project .claude/skills/sec ruff check --config pyproject.toml .claude/skills/sec/Scripts tests/sec`: All checks passed. 저장소 코드 포맷의 120자 기준을 따랐고, 새 문단·설명은 하드랩하지 않았다.
- 최종 harness validator **errors 0 / warnings 0**, skill validator **valid**. 실제 원문 fixture의 공백은 바이트 동일성을 위해 유지했고 `git diff --cached --check -- . ':(exclude)tests/sec/fixtures/**'`는 통과했다.
- 배포 대상 40개 파일(gzip 해제 포함)에서 설정된 identity를 검사해 **0 matches**였다. `.env`는 미추적·무변경이다. 예제 설정에서 발견한 실제 이메일은 커밋 전에 형식용 값으로 교체했다.
- 최종 리뷰 closure run `20260913-144225-sec-final-review-closure-321b`: 남은 차단점 없음으로 승인. nonbody 3개, SGML/오류 표적 2개 통과. 새 프로세스에서 edgar/PyArrow import와 네트워크를 금지해도 캐시 load/read/table/find와 CLI read가 성공했다.
- GitHub Actions의 기존 `Social skill checks`는 `disabled_manually`였다. 상태를 변경하지 않았으므로 GitHub runner의 CI 결과는 없다. SEC locked job을 연결했고 로컬에서 같은 검사들을 실행했다. PR의 GitGuardian 검사는 통과했다.

구현 커밋은 `82dd6cd`, PR은 https://github.com/tjdwls101010/Agentic-SNS/pull/8 이다. 사용자 `.gitignore` 기존 삭제는 index에 포함하지 않고 SEC `.env` 제외 추가만 커밋했으며, `.claude/harness-spec.md` 삭제와 입력 문서를 그대로 보존했다.

### E2E 판정 자료 정정과 뷰어 연결 보완

첫 독립 판정의 ASML fail은 **실행 실패가 아니라 판정 자료의 누락으로 인한 오판**이었다. `codex exec --json`의 events.jsonl에는 `functions.exec` 내부의 이미지 도구 호출·출력이 나타나지 않았다. 이를 모든 도구 기록으로 가정해 시각 검토가 없었다고 잘못 판단했다. 원본 rollout에는 실제 `tools.view_image` 루프와 이미지 출력 두 개가 모두 있다.

- 원래 ASML 최종 실행의 thread `01a09949-7266-73c1-9162-9cc41c23574f`: rollout line 138의 `call_W8jkUPOBKAUpzKrtA05ufHXp`가 저장된 두 JPG를 view_image로 열었고 line 143의 대응 출력에 `input_image` 두 개가 있다.
- 추가 재실행 thread `01a09951-1f70-7ca3-b02b-28769f0c2ebe`도 line 94 `call_hvRf3Y3CJ1TJyLYfCQJtrzkn` 및 line 98의 이미지 출력 두 개로 시각 검토가 확인된다.

따라서 앞서 기록한 “다운로드만 하고 시각 검토했다고 주장했다”는 해석과 그에 따른 ASML fail을 철회하고, 독립 grader에 원본 rollout 기반 재판정을 요청했다. 효과가 없다고 판단했던 추가 스킬 문구도 이 오판에 근거했으므로 제거했다. SKILL.md는 이미 승인된 간결한 원칙 중심 본문을 유지한다. 실패 결과를 숨기거나 테스트 기대를 바꾼 것이 아니라, 불완전한 관측 기록을 완전한 원본 실행 기록으로 교정한 것이다.

오판을 해결하려고 추가했던 SKILL 문구와 바이너리 local_path/visual_inspection/next_action 응답 확장도 최종 변경에서 제거했다. 원래 실행은 기존 source URL·sha256·cache와 이미지 도구로 이미 성공했으므로, 실제 결함이 아닌 이유로 유지보수할 인터페이스를 늘리지 않기 위해서다. 이 실험의 회귀 테스트 6 passed는 기록상 진단일 뿐 최종 산출물의 테스트 수에 더하지 않는다. 최종 런타임과 스킬은 검증된 구현 커밋 `82dd6cd`와 같다. 새 응답 실험용 E2E/추가 리뷰는 최종 판정 대상에서 제외한다.

### 확정 E2E 결과

독립 grader의 정정 run `20260913-145744-sec-e2e-grade-corrected-b33b`는 원래 지정한 **5개 시나리오 모두 pass**로 확정했다. 원본 rollout의 turn_context에서도 5개 모두 `gpt-6-astra` / `medium`을 확인했다. Claude E2E는 실행하지 않았다.

| 시나리오 | 실행 ID | 판정 근거 |
|---|---|---|
| Microsoft 최신 10-K와 위험요인 끝 | `20260913-144201-sec-e2e-final-latest-5f4f` | CIK 789019, accession `0001193125-26-323660`, 제출일 2026-07-29/보고일 2026-06-30. item_10이 동일 사본의 563–566 블록을 읽어 Item 1B 직전 채용·유지·노조 위험을 확인. 원문과 일치. |
| Apple 2024 표 | `20260913-144202-sec-e2e-final-table-95d1` | accession `0000320193-24-000123`, table-15의 이어읽기 완료와 주변 설명·주석 확인. 2024/2023/2022 총매출 391,035/383,285/394,328 및 백만 달러 단위를 원문과 대조. |
| ASML 첨부·이미지 | `20260913-144202-sec-e2e-final-exhibits-169e` | 2025-01-29 6-K `0000937966-25-000003`의 EX-99.1/99.2를 구분. 발표자료 HTML의 25개 JPG 연결과 slide 1·6의 실제 view_image 출력 확인. 렌더링 결과 bytes 해시도 저장 원본과 일치. |
| sec=seconds | `20260913-143530-sec-e2e-seconds-851b` | 원본 rollout에서 도구 호출 0개, SEC 스킬 오발 없이 시간 출력 코드 제공. |
| SEC 집행 자료 안내 | `20260913-143530-sec-e2e-enforcement-c0e6` | 원본 rollout에서 도구 호출 0개, EDGAR 공시 탐색과 집행 자료 안내를 구분하고 요청대로 실제 검색을 하지 않음. |

시각 확인 원문은 `https://www.sec.gov/Archives/edgar/data/937966/000093796625000003/a2025_01x29presentationi001.jpg` 및 `a2025_01x29presentationi006.jpg`다. 각 원본 해시는 `54bb0b3a2335c489e4b85faa991fafb10d2804d77c06702494ec014c2d8b1ae0`, `e2705ebcc3bc3cf6c479c73d3f5255aaf9a83b4d4f8e960ac653ba1e4fc9465e`이고, grader도 저장된 두 이미지를 실제로 열어 진술과 대조했다. 시각 확인 범위는 25개 전체가 아닌 이 두 장이다.

Apple 답변의 한국어 비교 방향 제목에 한 번 표현상 역전이 있었지만 값·열·실질 설명은 2024 대 2023으로 정확했다. 이 문구 한계와 선택된 범위/받은 검색 이력의 한계를 기록하며, 모든 공시·미래 SEC 변경·다른 모델까지 검증한 것으로 확대하지 않는다. `git diff --quiet 82dd6cd -- .claude/skills/sec tests/sec`로 최종 코드와 테스트가 마지막 전체 회귀·정상 E2E에 사용한 구현과 같음을 확인했다.
### 전달 완료

PR #8은 2026-09-13 06:02:01 UTC에 squash merge되었고 merge commit은 `4296032da513b5803a6442476e34b744282bcf19`다. 로컬 main을 fast-forward한 뒤 사용자 변경만 임시 보관·복원했으며 `.gitignore`, 입력 문서, 원래 `.env`의 해시와 `.claude/harness-spec.md` 삭제 상태가 그대로임을 확인했다. 임시 설치/E2E 사본의 identity 파일 12개는 검증 종료 후 삭제했고, 원문 캐시와 실행 근거는 유지했다.

머지 후 `uvx --from graphifyy python /Users/seongjin/.codex/skills/Graphify/scripts/build.py .`를 실행해 exit 0으로 그래프를 갱신했다. 29개 코드 파일 재추출, 266개 캐시 재사용, **2,462 nodes / 5,669 edges / 161 named communities**다. code-only 빌드이므로 문서 31개는 제외했고 `pyproject.toml` 하나의 AST node 부재 경고는 있었지만, SEC Python 코드의 `SourceDocument`와 `filings.py` 노드는 후속 query에서 확인했다. 그래프는 Git 추적 대상이 아니며 로컬 graphify-out에 보존한다.

최종 산출물은 이 문서의 실제 디렉터리 트리와 일치하며, 구현/스킬/테스트 bytes는 `82dd6cd`와 같다. 완료 판정은 SEC 72 pass + 라이브 1 pass, 기존 Python 1,023 pass + JS 70 pass, 세 지점 독립 코드 리뷰 승인, 원본 rollout을 포함한 E2E 5/5 pass, 독립 설치와 구조 검사, PR 머지 및 그래프 갱신이다. GitHub Actions는 기존 수동 중지 상태 때문에 서버에서 실행하지 않았고, Claude E2E도 실행하지 않았다. PDF/이미지 자체 추출·OCR은 범위 밖이며 필요한 시각 확인은 기존 이미지 도구로 수행한 경우만 근거로 삼았다.

### 실행 프로젝트 위치 정리 (후속 요청)

사용자 요청에 따라 pyproject.toml과 uv.lock을 Scripts/로 함께 옮기고 개발용 .venv도 해당 프로젝트 위치에 재생성한다. SKILL.md·사용 안내·기여 안내·CI의 --project는 Scripts/를 가리킨다. 위 디렉터리 트리는 최신 배포 구조이며, 앞선 검증 기록의 명령은 당시 실행한 원래 경로를 그대로 보존한다. 생성물인 Scripts/.venv는 배포 트리에서 제외한다. 완료 기준: 잠금 변경 없이 새 위치의 도움말·설정 진단과 SEC 회귀/린트 통과, 실행 안내 경로 일치, PR 머지 후 그래프 갱신.

새 위치 검증: `uv sync --frozen --group dev --python 3.11 --project .claude/skills/sec/Scripts`로 Scripts/.venv를 재생성했고 이전 .venv와 생성된 Ruff 캐시를 제거했다. pyproject.toml·uv.lock bytes는 이동 전과 동일하다. `uv run --isolated --frozen --python 3.11 --group dev --project .claude/skills/sec/Scripts python -m pytest tests/sec -q`는 **72 passed, 1 skipped (79.19초)**, 동일 project의 Ruff는 통과했다. 새 경로의 help/doctor, 저장소 밖 복사본의 identity 없는 schema, 하네스 구조 검사(errors 0/warnings 0)도 통과했다. 네트워크 구현과 .env 위치는 바꾸지 않았으므로 라이브/E2E를 반복하지 않았다.

후속 전달 완료: PR #9 (https://github.com/tjdwls101010/Agentic-SNS/pull/9)를 `36be9cf5754cd850ed286b52c681a18629574e45`로 squash merge하고 main을 갱신했다. `uvx --from graphifyy python /Users/seongjin/.codex/skills/Graphify/scripts/build.py .`는 exit 0, 2,462 nodes/5,669 edges/161 named communities로 완료됐다. 이동 전후 같은 pkg_sec_skill ID 경고에서는 새 Scripts/pyproject.toml 경로가 유지됐다. 사용자 변경과 원래 .env는 그대로 보존했고, GitHub Actions는 기존 disabled_manually 상태여서 서버 CI를 실행하지 않았다.
