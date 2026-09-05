# Harness Spec — Agentic SNS

## Context

상태: approved. 2026-09-05 계획서 D1–D7과 구현 요청으로 승인됨. Python 3.11+ 표준 라이브러리, Aside 브라우저 u0, pytest·node. 스킬 본문·도움말·주석은 영어, 스펙·Git 기록은 한국어.

## Goals

페이스북·레딧·Threads·X의 피드→글→댓글→작성자 탐색을 밀도 높은 텍스트와 다음 홉 핸들로 수행한다. 실계정 읽기 전용이며 요청 예산과 차단 상태는 코드로 강제한다.

## Behavior inventory

| id | behavior/knowledge/constraint | layer | component | status |
|----|-------------------------------|-------|-----------|--------|
| B1 | 페이스북 읽기·탐색·수집·쿼리 복구 | skill | `.claude/skills/facebook/SKILL.md` | validated |
| B2 | 좋아요·댓글 작성·게시 | skill | — | declined |
| B3 | 반응한 사람 목록 | skill | — | declined |
| B4 | 레딧 읽기·탐색·댓글 상태·수집 | skill | `.claude/skills/reddit/SKILL.md` | validated |
| B5 | 레딧 게시·댓글 작성·추천·저장·구독 변경 | skill | — | declined |
| B6 | 레딧 메시지함·알림 | skill | — | declined |
| B7 | Threads 읽기·탐색·수집·쿼리 복구 | skill | `.claude/skills/threads/SKILL.md` | validated |
| B8 | Threads 쓰기·좋아요·답글·팔로우·저장 변경 | skill | — | declined |
| B9 | Threads 활동·알림(열람 시 읽음 처리) | skill | — | declined |

| B10 | X 읽기·탐색·수집·쿼리 복구 | skill | `.claude/skills/twitter/SKILL.md` | validated |
| B11 | X 게시·답글·좋아요·리포스트·팔로우·북마크 변경 | skill | — | declined |
| B12 | X 알림·DM | skill | — | declined |

## Component specs

facebook은 scripts/ 아래의 독립 CLI와 브라우저 스니펫을 포함한다. 기존 `.tmp/Agentic Facebook`의 검증된 파서만 이식하고 브라우저 세션은 Aside에 맡긴다. 테스트 경계와 단계별 완료 기준은 [승인 계획](plans/facebook%20스킬%20구현%20계획.md)을 따른다. 사용자 스코프에는 레포 스킬 심볼릭 링크로 배포한다. 다른 스킬과 코드를 공유하지 않는다.

reddit은 [승인 계획](plans/reddit%20스킬%20구현%20계획.md)의 D1–D8과 테스트 경계·P0–P5 완료 기준을 따른다. Aside u0 실계정, 읽기 전용, Python 표준 라이브러리, 독립 scripts/를 사용하고 사용자 스코프 심볼릭 링크로 배포한다. 본문·도움말·주석은 영어이고 description에 한국어 트리거를 포함한다. Claude 헤드리스 e2e는 실행하지 않는다.

threads는 [승인 계획](plans/threads%20스킬%20구현%20계획.md)의 D1–D9·P0–P6와 확정된 테스트 경계를 따른다. Python 표준 라이브러리·Aside u0·독립 스킬·사용자 스코프 심볼릭 링크, 영어 본문/도움말/주석과 한국어 description 트리거를 사용한다. SSR 직접 답글의 미수집 추정치와 로컬 예산을 출력에서 구분한다. Claude 헤드리스 e2e는 실행하지 않는다.

twitter는 [승인 계획](plans/twitter%20스킬%20구현%20계획.md)의 D1–D12·P0–P6와 테스트 경계를 따른다. Aside u0 로그인 세션을 사용하는 독립 읽기 전용 스킬이며, 요청별 서명·query id별 예산·공유 차단·페이지 단위 재개를 CLI 경계에서 책임진다. 영어 본문/도움말/주석과 한국어 트리거, 사용자 스코프 심볼릭 링크로 배포한다. Claude 헤드리스 e2e는 실행하지 않는다.

## Design rationale

필요할 때만 사용하는 절차이므로 skill에 둔다. 요청 간격·예산·차단은 CLI 경계에서 강제하고 팬아웃·데이터 삭제는 도메인 원리로 안내한다. 새 hook·전역 permissions.allow·agent·workflow는 필요하지 않다. 승인 계획의 실행 패턴에 맞춰 스킬 활성 중에는 자신의 facebook.py 한 경로만 allowed-tools로 허용한다. 쓰기와 반응 목록은 D2에 따라 제외한다. 릴스·스토리·알림·메신저·미디어 다운로드는 범위 밖이다. 프로세스 스폰 최적화는 대량 수집의 병목이 측정될 때 검토한다.

reddit의 강제 경계는 CLI·GET 브라우저 스니펫·공유 예산 예약이다. 매 요청의 파일 잠금과 사전 예약, 성공 응답의 잔여 0 보존, 댓글 fullname 그래프와 스레드 단위 저장, 출력 페이지 마커로 중단을 복구한다. 공유 링크는 중간 헤더를 놓치지 않도록 실제 HTTP 홉마다 예약한다. 본문은 도메인 사실과 사용 이유만 담고 명령·복구 절차는 CLI 인터페이스가 소유한다. 새 hook·전역 권한은 만들지 않고 승인 계획의 reddit.py 실행 패턴만 스킬 활성 동안 허용한다. 위키 본문·멀티레딧·모더레이터 목록·미디어 다운로드와 프로세스 묶음 최적화는 범위 밖이다.

Threads의 유효 동작은 닫힌 읽기 명령·오퍼레이션과 호스트 검증으로 제한한다. 요청 예산·차단·관측 캡처 예약은 계정 잠금 안에서 강제하며, SSR 답글의 미수집 추정치·서버 제한·로컬 pending은 출력 계약에서 분리한다. SKILL.md는 사용 시점의 도메인 사실과 해석을, CLI·schema·error.fix는 명령과 유효 데이터 계약을 소유한다. 전역 권한·hook·agent·workflow는 추가하지 않았다.

X의 회전하는 쿼리·플래그는 레지스트리 데이터에 두고, 읽기 허용 목록·세션 보호·예산은 실행 인터페이스에 둔다. 본문에는 피드의 개인화·순위·리포스트 저자·답글 완전성처럼 결과 해석을 바꾸는 원리만 남긴다. 명령·옵션·복구는 도움말과 오류 출력이 소유하며 별도 hook·permission 규칙은 추가하지 않는다.

## Validation

- `python3 -m pytest tests/ -q`: 228 passed, 7 deselected.
- `node --test tests/facebook/js/*.js`: 30 passed.
- `python3 -m pytest -m live tests/facebook/live/ -q`: 7 passed. FACEBOOK_LIVE_POST와 FACEBOOK_LIVE_GROUP에 소량 검증 대상을 지정했다.
- `uvx ruff check --config pyproject.toml .claude/skills/facebook/scripts tests/facebook`: All checks passed.
- `python3 tests/facebook/tools/check_fixtures_pii.py`: 합성 fixture 13개 통과. 실제 값은 변환 도구로 치환하고 구조만 검토했다.
- harness-creator의 `validate_harness.py --path .`: 오류 0·경고 0. `audit_harness.py --path .`: skill 1개·드리프트 0. 사용자 스코프 facebook은 동일 소스에 대한 의도한 심볼릭 링크다.
- 라이브: 피드 텍스트 3건/11줄, 프로필 6건 및 more 6건의 id 중복 0, 글 전문+첫 댓글 10개, 댓글 커서 다음 배치 10개, 검색→그룹 3건, 소개 14필드/12섹션, 날짜 창 6건 및 완료 파일 재실행을 확인했다. 새 레지스트리의 답글 읽기는 부모 3개·답글 23개이며 더 남은 2개 배치는 batch_limit으로 표시했다.
- 기본 refresh: 39요청으로 6종 새 쿼리 검증·갱신, 실패 0. 캡처는 답글 쿼리 1종의 실제 요청·재생을 확인했다. 댓글 root/page 2종의 새 ID 캡처는 이번 실계정에서 관찰하지 못해 기존 유효 ID를 유지하며 missing으로 보고한다. 이 두 종류의 읽기와 커서 호환은 별도로 확인했다.
- 단계별 codex 검토의 P1/P2를 재현·수정했다. 최종 본문·도움말·스키마 사용성 검토에서 발견한 옛 fetch 안내도 profile/about으로 수정했다. 별도 Claude 세션 e2e는 실행하지 않았다. 사용자 요청에 따라 이후의 검증과 그래프 명명은 Codex만 사용한다.
- Graphify 코드 그래프를 세 차례 갱신했다. 마지막 결과는 558노드·1,315간선·28커뮤니티다. 기본 명명 스크립트의 Claude 호출은 세션 한도로 실패했으나, 이후 Codex가 커뮤니티 구성원을 확인하여 28개 이름을 부여하고 그래프·보고서·HTML에 반영했다. 이후에는 Claude를 호출하는 기본 래퍼 대신 코드 전용 추출과 Codex 명명을 사용한다.

Reddit 추가 후 최종 검증:

- `python3 -m pytest tests/ -q`: 435 passed, 12 deselected, 157.79초(Facebook 228개 포함).
- `node --test tests/facebook/js/*.js tests/reddit/js/*.js`: 36 passed(Facebook 30, Reddit 6).
- `uvx ruff check --config pyproject.toml .claude/skills/reddit/scripts tests/reddit`: All checks passed.
- `python3 tests/reddit/tools/check_fixtures_pii.py`: 합성 fixture 5파일 통과. 도구 회귀 테스트 20개와 합성 본문 수동 검토를 수행했다.
- `validate_harness.py --path .`: 오류 0·경고 0. `audit_harness.py --path .`: skill 2개·드리프트 0. 사용자 스코프 reddit은 같은 레포 원본 심볼릭 링크다.
- 라이브 5개 시나리오를 개별 선택 실행해 최종 통과했고, 실제 출력 Codex 사용성 검토와 합쳐 누적 30요청이다. 글 1요청→캐시 댓글 0요청→morechildren 1요청, 실제 목록 after와 fullname 중복 제거, 댓글 앵커, 검색·소개·파일 재실행을 확인했다. 구체 명령·초기 실패와 보정은 승인 계획의 최종 검증 절에 기록했다.
- 사용성 V1–V4는 구현 소스 없이 수행했다. V1은 캐시 피드, V4 활동은 정상 빈 결과 exit 7로 종료했다. Claude headless e2e와 자동 description 트리거 실행은 D4에 따라 미실행이다.
- 익명 modhash(A1), raw_json 옵션 유무 동일 표본 비교(A2), 실제 /s/ 공유 링크(A3)는 라이브 미확인이다. 현재 로그인·raw_json 강제·엔티티 정규화·공유 링크 안전성은 각각 실계정 또는 오프라인 경계 테스트로 검증했다. morechildren은 요청한 댓글의 자손도 반환함을 실측하여 계획의 잘못된 부분집합 단언을 보정했다.

- Reddit P3·P5 뒤 Graphify를 두 번 갱신했다. 최종 960노드·2,358간선·63커뮤니티이며 Codex가 전체 커뮤니티를 명명하고 HTML 내보내기를 검증했다. 그래프는 기존 로컬 제외 정책을 유지했다.

Threads 추가 검증은 [통합 계획의 구현 기록](plans/threads%20스킬%20구현%20계획.md)에 명령·수치·실패 후 수정·라이브 미확인 범위를 함께 기록한다. 전체 Python 525개·JS 52개 통과 후 사용성 수정 경계는 추가 검증하며, 최종 CI 결과를 같은 기록에 반영한다.

X 검증: Twitter 오프라인 160개·JavaScript 9개, 기존 Facebook/Reddit 435개 통과. 전체 실행은 595 passed·15 deselected다. Ruff·PII·하네스 검사 통과. 실계정 탐색과 33종 발견/2종 재생 복구를 확인했다. 북마크는 빈 목록이며 실제 항목 형태는 미검증이다. 단계별 실패·수정·실제 명령은 Twitter 승인 계획의 최종 검증 기록에 둔다.

## Change history

- 2026-09-05: 승인 계획의 facebook 읽기 스킬·브라우저 브리지·복구·CI 구현과 검증 완료. .codex 상대 링크 및 사용자 스코프 링크를 연결했다. 대형 응답은 Aside 파일 권한 제한 때문에 디스크 대신 순서가 검증되는 stdout 조각으로 전달한다. 현재 prefetch 메타데이터에서 relay 플래그를 읽어 새 필수 변수를 복구한다.

- 2026-09-05: Reddit 승인 계획에 따라 독립 읽기 전용 스킬, 공유 예산·댓글 그래프·페이지 커밋·CLI·합성 픽스처·실계정 검증·CI를 구현했다. 단계 진행은 사용자 요청에 따라 계획서 한 파일에 통합했다. 독립 Codex 리뷰의 통신 3건·댓글 상태 6건·목록/출력 4건을 재현 테스트로 수정했다. 사용성 검토에서 발견한 댓글 표시 수·수집 시각도 개선했다.

- 2026-09-05: 승인된 Threads 읽기 스킬과 독립 CLI·브라우저 브리지·SSR 완전성·로컬 보호·커서/파일·레지스트리 복구를 구현했다. 조사 JSON과 구현 기록은 기존 계획 한 파일로 통합했다. 단계별 Codex 리뷰와 V1–V4 합성 사용성 검토, 실계정 읽기와 복구를 수행했으며 제한된 직접 답글·미관측 캡처·관계 수 누락을 숨기지 않는다. Twitter 작업은 별도 워크트리를 보존한다.

- 2026-09-05: Twitter 독립 읽기 스킬·요청 예산·세션/서명 복구·탐색·수집·CI를 구현했다. Threads 동시 작업을 보존하기 위해 별도 worktree에서 진행하고 사용자 스코프 링크도 그 원본을 가리킨다. 스냅샷과 구현 기록은 Twitter 계획 한 파일에 유지했다.
