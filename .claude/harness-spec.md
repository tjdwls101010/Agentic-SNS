# Harness Spec — Agentic SNS

## Context

상태: approved. 2026-09-05 계획서 D1–D7과 구현 요청으로 승인됨. Python 3.11+ 표준 라이브러리, Aside 브라우저 u0, pytest·node. 스킬 본문·도움말·주석은 영어, 스펙·Git 기록은 한국어.

## Goals

페이스북의 피드→글→댓글→작성자 탐색을 밀도 높은 텍스트와 다음 홉 핸들로 수행한다. 실계정 읽기 전용이며 요청 예산과 차단 상태는 코드로 강제한다.

## Behavior inventory

| id | behavior/knowledge/constraint | layer | component | status |
|----|-------------------------------|-------|-----------|--------|
| B1 | 페이스북 읽기·탐색·수집·쿼리 복구 | skill | `.claude/skills/facebook/SKILL.md` | validated |
| B2 | 좋아요·댓글 작성·게시 | skill | — | declined |
| B3 | 반응한 사람 목록 | skill | — | declined |
| B4 | 레딧 읽기·탐색·댓글 상태·수집 | skill | `.claude/skills/reddit/SKILL.md` | approved |
| B5 | 레딧 게시·댓글 작성·추천·저장·구독 변경 | skill | — | declined |
| B6 | 레딧 메시지함·알림 | skill | — | declined |

## Component specs

facebook은 scripts/ 아래의 독립 CLI와 브라우저 스니펫을 포함한다. 기존 `.tmp/Agentic Facebook`의 검증된 파서만 이식하고 브라우저 세션은 Aside에 맡긴다. 테스트 경계와 단계별 완료 기준은 [승인 계획](plans/facebook%20스킬%20구현%20계획.md)을 따른다. 사용자 스코프에는 레포 스킬 심볼릭 링크로 배포한다. 다른 스킬과 코드를 공유하지 않는다.

reddit은 [승인 계획](plans/reddit%20스킬%20구현%20계획.md)의 D1–D8과 테스트 경계·P0–P5 완료 기준을 따른다. Aside u0 실계정, 읽기 전용, Python 표준 라이브러리, 독립 scripts/를 사용하고 사용자 스코프 심볼릭 링크로 배포한다. 본문·도움말·주석은 영어이고 description에 한국어 트리거를 포함한다. Claude 헤드리스 e2e는 실행하지 않는다.

## Design rationale

필요할 때만 사용하는 절차이므로 skill에 둔다. 요청 간격·예산·차단은 CLI 경계에서 강제하고 팬아웃·데이터 삭제는 도메인 원리로 안내한다. 새 hook·전역 permissions.allow·agent·workflow는 필요하지 않다. 승인 계획의 실행 패턴에 맞춰 스킬 활성 중에는 자신의 facebook.py 한 경로만 allowed-tools로 허용한다. 쓰기와 반응 목록은 D2에 따라 제외한다. 릴스·스토리·알림·메신저·미디어 다운로드는 범위 밖이다. 프로세스 스폰 최적화는 대량 수집의 병목이 측정될 때 검토한다.

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

## Change history

- 2026-09-05: 승인 계획의 facebook 읽기 스킬·브라우저 브리지·복구·CI 구현과 검증 완료. .codex 상대 링크 및 사용자 스코프 링크를 연결했다. 대형 응답은 Aside 파일 권한 제한 때문에 디스크 대신 순서가 검증되는 stdout 조각으로 전달한다. 현재 prefetch 메타데이터에서 relay 플래그를 읽어 새 필수 변수를 복구한다.
