# Finviz 읽기·탐색 스킬 구현 계획

## 승인된 목표와 범위

비로그인 Finviz가 반환하는 자료를 보존하면서 Claude Code와 Codex가 질문에 맞게 탐색·수집·비교·이해할 수 있는 역량을 제공한다. Finviz 명시 요청·URL과 그 후속 대화에서 선택한다. 출처 미지정 미국 주식 조건검색의 기본 스킬로 등록하지 않는다.

종목 식별·조건검색, 기업·ETF 정보, 가격·재무제표·실적·예상치·배당·매출 구성·보유 현황·공매도·옵션·공시 목록, 그룹·맵·버블의 수치와 분류, 선물·외환·암호화폐, 뉴스·내부자 거래·일정을 포함한다. 점진 읽기·전체 수집·재사용·재개와 모델의 로컬 계산을 지원한다. 무료 화면보다 넓은 정상 익명 응답도 보존한다. Finviz 자체 기사와 Market Pulse 상세는 읽으며, 외부 기사와 SEC 원문은 링크로 연결한다.

로그인이 필요한 계정 자료, 변경 동작, 실제 권한 거절을 우회하는 조회, 시각 캡처·렌더링, 투자 전략 강제는 제외한다. 기존 SEC 스킬·테스트와 yfinance 및 다른 작업은 수정하지 않는다.

## 실행과 인터페이스

Python 3.11+, curl 8.4+, uv 잠금 환경을 사용한다. Beautiful Soup 4.15.0과 JSON5 0.15.0 외에는 표준 라이브러리를 우선 사용한다. Aside와 고수준 Finviz 클라이언트에 의존하지 않으며 JavaScript를 실행하지 않는다. API·구조화된 초기 데이터·필요한 HTML 중 원문 의미를 충실하게 제공하는 원천을 사용한다.

`doctor/schema/catalog`는 환경과 계약, `lookup/open`은 대상과 URL, `screen/stock/prices/groups/market/map/calendar/news/insiders`는 조회, `inspect/read`는 저장 결과, `collect`는 연속 수집을 담당한다. 기본 출력은 간결한 텍스트이며 `--json`을 제공한다. 큰 자료는 식별자·저장 위치·JSON Pointer로 부분 읽기한다. 인자·필드·선택지·복구 방법은 인터페이스에서 설명한다. 공개 Python API는 약속하지 않는다.

필터와 열은 현재 원천에서 발견한다. 맵 자산은 현재 로더와 매니페스트로 선택하며 해시를 고정하거나 다른 유형을 대신 사용하지 않는다. 분류·가중치·성과를 구별한다.

## 데이터 계약

원문과 관측 시각·대상·출처·요청 조건·적용 근거·범위·이어 읽기를 함께 반환한다. 조건은 적용 확인·미적용·확인 불가를 구별한다. 표시명·원래 값·정의·단위·추가 필드를 보존하며 중복 이름을 합치지 않는다. 누락은 0이 아니다. 날짜·가격 배열 길이가 다르면 조용히 잘라 맞추지 않는다.

수신 원문은 추출 실패와 무관하게 SQLite에 보존한다. 수신 미완료는 따로 표시한다. 원문·추출 결과·체크포인트를 트랜잭션으로 관리하고 저장 결과 읽기와 새 관측을 구별한다. JSONL 내보내기는 출처·조건·범위를 포함하며 무관하거나 사용자가 수정한 파일을 덮어쓰지 않는다. 실제 수집량·표시량·서버 전체 수를 구별하고 변하는 목록을 한 시점의 완전한 집합으로 주장하지 않는다.

읽기 경로와 리디렉션 목적지를 검사한다. 확인 화면·접근 거절·빈 결과·구조 변경을 구별하며 Retry-After를 존중한다. 연결 10초·요청 60초·응답 16MiB를 변경 가능한 기본값으로 둔다.

## 스킬 구성

설치 단위는 `.claude/skills/finviz/`다. SKILL.md·잠금 환경·CLI와 필요한 코드만 제공한다. references 폴더와 별도 레퍼런스 파일은 만들지 않는다. 내부 모듈 11개를 고정한 이전 계획은 폐기한다.

Principle over rail: 근거·범위·시점을 선택할 이유와 실제 사례를 제공하고 명령 순서를 강제하지 않는다. Interface over document: 도구가 소유하는 지식은 도움말·카탈로그·결과에 둔다. For user not developer: 본문은 에이전트의 판단에 필요한 내용만 담고 개발 이력은 여기 남긴다. Dense information: 일반 금융 설명·반복 경고를 제거하고 실제 판단을 바꾸는 정보만 남긴다.

중복 EPS next Y, EPS Q/Q의 실제 툴팁, 맵 가중치의 기준 차이를 짧은 사례로 쓴다. 새 CLAUDE.md·rules·hooks·agents·workflow·전역 권한은 추가하지 않는다.

## 검증과 단계별 완료 판정

테스트와 fixture는 프로젝트 루트 `tests/finviz/`에 둔다. 공개 CLI 입력·출력·종료 상태·저장 결과가 승인된 seam이다. 외부 curl만 통제하고 내부 함수를 모킹하지 않는다. 각 기능은 실패 테스트를 실제 확인한 뒤 최소 구현한다. SEC 테스트는 실행하지 않는다.

필수 사례는 티커·중복 지표·새 필드, 조건 적용·확인 불가, 넓은 응답 보존, 결측·0, 기간·실제·예상, 배열 대응, 정상 빈 결과·제한·실패, 변동·반복·재개, 추출 실패 원문 보존, 안전한 내보내기, 맵 자산 선택, 읽기 경계·제한, 독립 설치와 공백·한글 경로, 도움말·스키마·실제 동작의 일치다. 기대값은 원문 사례와 독립적으로 정한다.

Claude Code와 Codex에서 Finviz 명시 요청·후속 탐색·불완전 자료·출처 미지정 질문 near-miss·Finviz 코드 작업 near-miss를 검증한다. 실제 모델·CLI를 사용하고 통제 응답과 실서비스 검증을 구별한다. 실행과 평가는 분리하며 호출 순서가 아닌 결과의 근거를 평가한다.

| 단계 | 완료 판정 | 상태 |
|---|---|---|
| 실행 기반·첫 조회 | 독립 CLI의 종목 식별·원문 저장·재열람 | 완료: 첫 실패 확인 후 통과 |
| 스크리너·수집 | 현재 카탈로그·조건·열·페이지·중단·재개·범위 보고 | 완료 |
| 나머지 원천 | 합의한 각 기능의 원천과 정상·실패 검증 | 완료 |
| 스킬·인터페이스·설치 | 레퍼런스 없이 발견·사용, 독립 설치 | 완료 |
| 전체 검증·전달 | 회귀·실서비스·모델 검증·코드 리뷰와 결과 기록 | 완료 · PR #10 머지 |

`feat/finviz-skill` 브랜치에서 관련 변경만 한국어 커밋·PR·squash merge한다. 병행 작업은 보존한다. 머지 후 Graphify를 갱신하고 깨진 실행 링크는 사전 점검한다. 완료는 합의 역량의 검증 근거가 있으며 식별·의미·범위·보존을 깨는 미해결 문제가 없는 상태다.

## 실행 기록

- 2026-09-13: 주 작업 폴더는 feat/yfinance-skill에서 수정 중이므로 origin/main(23916d6) 기반 `/tmp/agentic-sns-finviz` worktree에서 작업한다. TaskCreate 계열과 도구 검색 제공 여부를 전체 도구 메타데이터에서 확인했으나 사용할 수 없어 이 표로 진행을 기록한다.
- CLI 조회·원문 재열람, 스크리너 식별·조건·계속 읽기, 지표 의미·옵션 만기, 재무제표·가격 배열 불일치, 일정 페이지 계약을 순서대로 red→green 검증했다.

- 독립 Codex 코드 리뷰는 리디렉션의 요청 조건 소실, JSONL 내보내기의 표 헤더·상위 메타데이터 소실, 부분 관측 오류 누락을 지적했다. 재현 테스트의 실패를 확인한 뒤 원래 요청 조건 유지와 완전한 관측 단위 JSONL로 수정했다. 리뷰어 환경에서는 임시 디렉터리 쓰기 제한으로 테스트를 실행하지 못했으며, 실행 검증은 주 세션에서 수행했다.

- 실서비스 32개 조회가 모두 통과했다. 기본 날짜 없는 일정 API의 HTTP 400은 사이트 기본 날짜를 제공하는 페이지로 연결해 수정했고, Custom 열과 필터 컨트롤이 다른 응답에 있는 경우 두 관측을 출처와 함께 결합했다. 일반적인 JSON 파싱 실패·중복 키·재귀 한계에서도 수신 원문이 보존된다.
- 독립 설치 테스트는 한글·공백 경로와 다른 작업 디렉터리에서 잠금 환경으로 통과했다. harness validator는 오류 0·경고 0이며 SKILL.md는 약 2.7KB, references 폴더는 없다.
- Graphify의 기존 실행 링크는 대상 패키지가 없었으므로 uv tool로 graphifyy 0.9.61을 설치해 복구했다. Finviz 런타임 의존성에는 포함하지 않는다.


## 최종 검증 기록

- 오프라인 CLI·설치: `.claude/skills/finviz/.venv/bin/python -m pytest tests/finviz -q` → **23 passed, 32 deselected**. 외부 curl만 대체하며 실제 CLI subprocess와 SQLite를 사용한다. 정상 빈 결과, 조건 미적용·미확인, 리디렉션 조건 보존, 중복 지표·JSON 키, 배열 불일치, 추출 예외 원문 보존, 수집 재개·내보내기 보호, 맵 자산 선택, 부분 읽기 경고, 독립 설치를 포함한다.
- 실서비스: `.claude/skills/finviz/.venv/bin/python -m pytest tests/finviz/test_live.py -m live -q` → **32 passed**. 원문은 로컬 관측 저장소에 보존하며 원본 기사·시장 데이터 캡처는 저장소에 커밋하지 않는다.
- 정적 검사: `ruff check --config pyproject.toml .claude/skills/finviz/scripts tests/finviz` 통과. `validate_harness.py --path /tmp/agentic-sns-finviz --json` → 오류 0·경고 0. 코드 포매팅은 저장소의 ruff 설정을 적용했으며 도움말 문장은 자동 하드랩 없이 출력한다.
- GitHub Finviz CI: https://github.com/tjdwls101010/Agentic-SNS/actions/runs/34758009293 및 PR 실행 https://github.com/tjdwls101010/Agentic-SNS/actions/runs/34758068922 통과.
- 독립 코드 리뷰: `20260913-213321-finviz-code-review-700c`. 수정 지적 3건은 각각 CLI 회귀 테스트로 재현 후 수정했다.
- 독립 최종 판정: `20260913-214643-finviz-final-verification-5248` → 아래 모델 시나리오 **10/10 PASS**, 지정한 코드 결함 3건 수정 확인. 리뷰어는 읽기 전용 샌드박스의 임시 파일 쓰기 제한으로 pytest를 재실행하지 못했으며 코드 검사와 주 세션 실행 기록을 구별해 평가했다.

| 시나리오 | Claude Code (실제 모델 claude-opus-5) | Codex (gpt-6-astra, medium, priority) |
|---|---|---|
| Finviz 명시 요청의 지표 의미 구별 | PASS: Skill 호출 후 CLI read의 금액·성장률·YoY 정의로 답변 | PASS: 스킬 읽기·stock 조회·저장 결과 읽기의 원문 정의로 답변 |
| 후속 대화 | PASS: 같은 세션의 실제 resume, 기존 값과 정의 유지 | PASS: 같은 thread의 실제 exec resume, 기존 값과 정의 유지 |
| 불완전 자료 | PASS: 저장 자료만 읽고 배열 불일치 때문에 수익률 계산 불가로 설명 | PASS: 새 조회 없이 배열 불일치·조건 미확인을 설명하고 수익률을 만들지 않음 |
| 출처 미지정 실제 스크리닝 | PASS: ultra-search로 다른 출처 탐색, Finviz 스킬·CLI 호출 없음 | PASS: ultra-search로 다른 출처 탐색, Finviz 스킬·CLI 호출 없음 |
| Finviz 코드 작업 | PASS: 도구 호출 없이 함수 인터페이스 제안 | PASS: 도구 호출 없이 함수 인터페이스 제안 |

판정 근거는 `/tmp/finviz-model-checks/grade-evidence.json`과 각 원본 transcript 및 Codex 실행 기록에 있다. explicit은 실서비스 관측, partial은 외부 curl 경계의 통제 응답으로 실제 CLI가 생성한 저장 관측이다. 최초 개념 설명 near-miss보다 강한 실제 데이터 조회 요청으로 출처 미지정 시나리오를 재검증했다. Claude partial은 잘못된 명령 시도 뒤 도움말과 실제 read로 복구했다. Codex explicit은 짧은 원문 정의에 없는 성장률 분모를 “올해 대비”로 확장해 설명했으므로, 테스트 통과를 모든 금융 해석의 보장으로 일반화하지 않는다.

- 인계 완료: [PR #10](https://github.com/tjdwls101010/Agentic-SNS/pull/10)은 2026-09-13에 `91dee475ebe601dba1e84ab4cc3368347b7e5d36`으로 squash merge됐다. Finviz 전용 CI와 저장소 공통 CI가 모두 통과했다. 로컬 검증은 Finviz 범위로 실행했으며, 기존 GitHub 공통 워크플로는 설정대로 자체 SEC job도 실행했다. SEC·yfinance 코드와 테스트 파일의 diff는 없다.
- 머지 직후 `python3 /Users/seongjin/.codex/skills/Graphify/scripts/build.py /tmp/agentic-sns-finviz` 성공: 2,648 nodes, 5,958 edges, 170 communities named. 그래프는 worktree의 `graphify-out/`에 있으며 Git 추적 대상이 아니다. 루트 pyproject.toml은 AST 노드가 없어 제외됐다는 도구 경고를 남겼다.
- 현재 주 작업 폴더는 진행 중인 feat/yfinance-skill 브랜치이므로 전환하지 않았다. 구현과 검증은 `/tmp/agentic-sns-finviz` worktree에서 완료했고, 제품 코드는 origin/main에 있다.
