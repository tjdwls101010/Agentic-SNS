# threads 스킬 총체 점검과 재설계 계획

> 계획 세션(2026-09-25)에서 승인됐고 파일명 변경까지 마쳤다. 구현은 다음 세션이 아래 작업 단계 0부터 진행한다. 작업 트리의 무관한 변경(`.gitignore`, `.claude/harness-spec.md` 삭제, 다른 계획 파일, `.ultra-search/`)은 커밋에 섞지 않는다.
> 2026-09-26 개정: skill-maker `## Code the skill bundles`에 맞춰 트리·호출 형태·테스트 기계를 `## 공통 구조 기반`으로 바꿨다(`SNS 스킬 4종 계획 구조 관례 개정 계획.md`). 결함 목록과 다른 결정은 그대로다.

## Context

`.claude/skills/threads`는 Claude가 Threads를 **숙련된 사람 독자처럼** 탐색하게 하는 스킬이다 — 피드를 훑고, 글을 열어 부모 글·답글을 읽고, 작성자의 프로필·탭·관계를 보고, 검색한다. 스크린샷 없이 밀도 높은 텍스트로, 읽기 전용으로, 성진의 실계정(Aside `u0`)을 체크포인트로부터 보호하면서, 본 것과 못 본 것을 정직하게 구분한다. CLI가 역량과 사실을 소유하고 SKILL.md는 기본 모델에 없는 판단만 담는다.

PR #4(2026-09-05) 이후 threads는 한 번도 점검받지 않았고, Claude 대조 실험은 원 계획 D5에 따라 한 번도 돌지 않았다. 이번 점검(실측 15요청 + 코덱스 정적 감사 + 코덱스 계획 검토)의 결론:

1. **핵심 기능이 지금 깨져 있다.** Meta가 글 페이지 오퍼레이션 이름을 바꿔 `post`가 모든 글에서 실패한다. 코드가 이름의 부분 문자열(`'StrongId' in name`)로 페이로드를 식별하므로 `refresh`로 복구되지 않는데 fix는 refresh를 권한다(L1).
2. **가장 자주 바뀌는 지식이 가장 많이 흩어져 있다.** 오퍼레이션 하나가 5~9곳(레지스트리·JS 허용 목록·디코더 if 사슬·SSR 매처·신원 검사·질의 조립·캡처 목록)에 있고, 레지스트리의 서술 필드는 이미 코드와 모순된다.
3. **인터페이스가 계약을 지키지 않는다.** 출력 URL 훼손(L2), 항상 실패하는 `about`(L3), 숨은 요청 상한 전환(L5), 적용되지 않는 인자, 거짓 재개 약속, 형태 변화와 id 회전을 구분하지 못하는 fix.
4. **SKILL.md의 근거가 없다.** 약 30문장 중 KEEP 10 · MOVE 16 · CUT 4(코덱스 감사). "What has actually bitten"은 이력 기준 절이다.

**의도한 결과**: 계정 보호층의 검증된 동작은 그대로 보존하고, ① post를 이름에 의존하지 않게 복구하고, ② 오퍼레이션 하나 = 선언 하나로 모아 Meta의 id 회전과 (라우트 오퍼레이션의) 개명을 `refresh`가 검증 후 스스로 흡수하게 하고, ③ 인터페이스가 자기 계약을 말하게 하고, ④ SKILL.md는 녹화 재생 환경의 대조·제거 시험을 통과한 판단만 남긴다. `scripts/`는 `cli.py` + 패키지 `threads/`(변경 축별 하위 폴더)로 재배치한다(`## 공통 구조 기반`).

## 장부

### 사실 (2026-09-25 실측)
- 오프라인: `python3 -m pytest tests/threads -q` 92 passed · 9 deselected(live) · 48.6s. `node --test tests/threads/js/*.js` 통과. ruff는 PATH에 없음 → `uvx ruff`(0.16.9).
- 크기: Python 25모듈 약 2,000줄 + `registry.json` 693줄 + JS 3개(313줄). `scripts/`는 평면이며 `threads.py`가 `importlib`로 `threads_skill` 패키지를 합성한다(`threads.py:8-15`, `tests/threads/conftest.py`도 같은 합성). 표준 라이브러리 이름과 `cli`·`reading`·`meta`·`guard`·`domain`은 겹치지 않는다(`sys.stdlib_module_names` 확인).
- 레지스트리: 번들·캐시 오버라이드(`~/.cache/threads-skill/registry.json`, 12개 항목, Meta 이름 키·전체 spec) 모두 `captured_at` 2026-09-05. `registry.json`의 `leaf`·`pagination`·`notes`·`verification`·`discovery`·`source`는 코드가 읽지 않는 서술이고 liked/saved의 `pagination: relay`는 실행 정책 `single_batch`와 모순. `_registry.py:18`은 번들에 없는 오버라이드 키를 만나면 레지스트리 전체를 읽을 수 없다고 판정한다.
- 발견 라우트(registry `source`): feed `/`, profile page·threads 탭 `/@<user>`, replies/reposts/media 탭 각자 `/@<user>/<tab>`, search `/search?q=…&serp_type=default`, 글 3종 글 라우트(SSR), 캡처 6종(계정 검색·팔로워·팔로잉·팔로잉 refetch·좋아요·저장)은 앱 탭 조작.
- 테스트 seam: 공개 seam(`run_cli` 서브프로세스 + `tests/threads/fake_aside/aside` + `fixtures/routes.ndjson`, 키=경로 또는 `name[:after]`)이 이미 있다. 12개 파일이 내부 모듈을 직접 import하고 2개는 혼합. **오프라인 `post` 경로 테스트가 없어서 L1이 CI에서 안 잡혔다.** live 테스트는 pytest 안에서 `_transport.run_snippet`을 패치해 누적 30회 가드를 건다(`tests/threads/live/conftest.py:12-28`).
- facebook conftest는 `sys.path.insert`로 자기 `scripts/`를 올린다 — 여러 스킬 테스트가 한 pytest 프로세스(CI `pytest tests/ --ignore=…`)에서 돈다.
- 문서 참조: `docs/usage.md:96,115,126`, `README.md:84,89`. (2026-09-26: 진입점이 `scripts/cli.py`로 바뀌므로 `docs/usage.md:96`의 경로는 PR ② 단계 7에서 고친다. 불변인 것은 CI 워크플로의 실행 경로뿐이다.)
- `graphify-out/`은 `.git/info/exclude`로 로컬 전용 → 머지 후 리빌드는 커밋 없음.

### 라이브 실측 (2026-09-25, 실계정 u0, 총 15요청 · 창 15/120)
- `doctor` ok(0.7MB). `home` ok — SSR 재사용 1요청. `user`·`search`·`graph following` ok. `me saved` 0건(exit 7).
- **L1 `post` 전면 불능**: exit 6 `envelope_drift` "Route identity is missing or ambiguous", fix "Run refresh". 글 페이지 오퍼레이션 계열이 `BarcelonaPostPageStrongId{Target,Downward,Upward}Query` → `BarcelonaPostPage{Target,Downward,Upward}Query`로 이름이 바뀌었다(Downward에 `sortOrder` 변수, 같은 라우트에 새 `BarcelonaPostViewCountQuery`). SSR `__bbox` 결과에는 `queryName`이 없다(데이터 키 `media` / `media,viewer`). 코드는 `'StrongId' in name`으로 판정(`_ssr.py:21-31`, `_transport.py:147`, `_refresh.py:70,91`, `_thread.py:28-36`).
- **L2 URL 훼손**: `_render.text()`의 마크다운 제거(`re.sub(r'\*\*|__|`', '')`)가 `url:`에도 적용되어 `@steady__study.dev` 글 URL이 `@steadystudy.dev`로 출력 → 다음 홉이 다른 계정으로 간다. Threads는 마크다운을 렌더하지 않으므로 본문의 `__init__`·`**` 제거도 원문 훼손이다.
- **L3 `about` 항상 부분 실패**: `following=unknown · mutuals=unknown`, exit 8, fix "Run refresh --capture"(필수 `--post` 누락 + 회전이 아니라 원천 부재라 캡처로 안 고쳐짐). 9/5 구현 기록에도 counts에 fediverse 두 필드만 온다.
- **L4 링크 미리보기**: `l.threads.com/?u=<원 URL>&e=<추적 토큰>` 원문(약 200자). 원 URL은 `u=`에 있다.
- **L5 예산 표기**: `--limit`을 주면 명령 상한 10→40, "local budget 39 of 40" vs "8 of 10".
- `more:`가 `user /@golbin`처럼 경로 형태, `graph` 헤더에 관계 종류 없음.
- 셸 함정 재현: zsh에서 명령을 변수에 담으면 단어 분할이 안 되어 exit 2.

### 코덱스 정적 감사 (`gpt-6-astra` medium, read-only, run `20260925-143232-threads-audit-67b2`)
- **SKILL.md**: KEEP 10 · MOVE 16(→ `--help`·출력 끝줄·schema·error fix) · CUT 4. 빠진 판단: 과제 기준 완료, 인용·리포스트 귀속과 겹치는 배치 중복 계산 금지, 날짜창은 글 작성 시각이지 리포스트 행위 시각이 아니다, 일반 refresh vs capture 선택.
- **인터페이스 결함 26건** → 아래 "인터페이스 변경" 표.
- **구조**: 오퍼레이션별 흩어짐(16행), 순환 `transport → capture → refresh.CAPTURE`, 도메인이 CLI 층 import(`_thread`·`_refresh` → `_cmds_common`, `_thread`가 argparse 네임스페이스를 받고 파일을 씀), `schema`가 실행 모듈 import, `read_page` 이중 디코드, 날짜 검증 중복, JS 청크 코드 복붙, 80줄대 함수 4개(`_cmds_browse.run`·`_listing.collect`·`_thread.read_thread`·`_refresh.refresh`). 데드코드 후보 `OutFile.parent_count`·`_blocked.unblock()`·`_errors.diagnostic()`.
- **테스트 공백**: 오프라인 post, followers/following, capture 성공, 차단→unblock 다중 명령, 커서·파일 손상, 날짜창 상한·미지 시각, schema 대 실제 결과, 청크 재조립.

### 코덱스 계획 검토 (같은 스레드, run `20260925-145515-threads-audit-57af`) — 20건 전부 반영
차단 6(PR ①이 PR ②의 카탈로그에 의존, PR ② 리터럴 0 게이트가 PR ③의 JS 변경에 의존, 골든 비결정성, 값 의존 인자 적용, 단계 4의 라이브 범위, 녹화가 초안보다 먼저) · 회귀 4(about null 프로필 폴백, 구 캐시 마이그레이션, 서브프로세스 live의 누적 가드 우회, SSR 커서→Direct 재시작 폴백) · 누락 3(구 버전 핸들·파일 호환, 개별 seam 사례 배정, collect 분해 여부) · 프레임 4(SKILL.md가 인터페이스 사실 복제, about 강제, 복구 절차 반복, 창 문장 과장) · 설계 위험 8(`Query` 접미사는 읽기 전용 증거가 아님, 탭 4종의 같은 서명, 캡처 오퍼레이션 개명 경로 없음, SSR 부모·답글 신원, 서브프로세스 `call` 경로·직렬화, 재생 키 스키마, 녹화 스냅샷·캡처 키, 재생 미스를 Threads 실패로 위장). 반영 위치는 아래 각 절.

재확인(run `20260925-150028-threads-audit-1f55`): 17 RESOLVED · 3 PARTIAL(`search --type users --chars`, 개명 입장의 의미 검증, 캡처 재생 키) · 새 차단 2(잠정 입장 경로 부재, 폴백과 보호 판정의 순서). 5건 모두 반영 — `--chars` 조합 거절, 역할 검사 추가 + 남은 의미 위험은 결정 13의 수용 위험으로 명시, 캡처 키에 동작·예산, refresh 전용 잠정 입장, "보호 판정 → 폴백 → 최종 오류" 순서.

### 성진 결정 (2026-09-25)
1. 형제 스킬과의 유사성은 설계 근거가 아니다. threads 자체의 목적에 최선인 구조. (→ M4로 좁힘: 내용에만 적용)
2. 목적 이해 승인(위 Context 첫 문단).
3. 계획 단계 라이브는 doctor + 소수 읽기만(15요청 사용).
4. 대조·제거 시험·최종 시나리오 판정 모델은 **Claude Opus 5.5**. 코덱스(`gpt-6-astra` medium)는 설계·코드 리뷰.
5. 범위: **계정 보호층(예산·차단·응답 분류·Aside 브리지) 동작 보존 + 나머지 재설계**.
6. ~~구조: **`scripts/` 바로 아래 하위 폴더**(래퍼 패키지 없음)~~ → M1·M13으로 대체: `scripts/cli.py` + `scripts/threads/`.
7. 테스트: **CLI seam 중심 + 순수 계약만 단위**. ~~모든 테스트를 서브프로세스로~~ → M5로 대체: 근거였던 최상위 이름 충돌이 고유 패키지 이름으로 사라져, 순수 계약은 in-process import(`from threads.… import …`)하고 CLI는 서브프로세스로만 부른다.
8. PR: **세 개** — ① post 복구 ② 행동 불변 재배치 + 카탈로그 ③ 인터페이스·SKILL.md·시험.
9. `about`: 카드는 **평소 1요청**(SSR 프로필이 null일 때만 프로필 쿼리 1회 추가 — 기존 폴백 보존), 팔로잉·맞팔은 `unknown`, exit 0.
10. 대표 과제: **주제 여론 조사, 인물 활동 추적**.
11. 시험 환경: **녹화 재생 + 최종 시나리오만 라이브**.
12. 표면: 전부 유지(home·me·capture 포함), **`--out`은 목록 명령(home·user·graph·search·me)에만**.
13. 개명: `refresh`가 검증을 통과한 새 이름을 **캐시 오버라이드에 자동 채택**(번들 불변, 결과에 `renamed` 보고). 입장 조건은 아래 카탈로그 절.
14. 복구 자율: **refresh는 모델이 한 번 스스로 실행 후 원 명령 재시도, capture는 사용자 확인 후**, exit 5 뒤에는 어떤 요청도 하지 않는다.
15. 요청 상한: **명시 인자 `--max-requests`**(기본 10, 최대 40). `--limit`은 표시 건수만 정한다.

### 성진 결정 (2026-09-26 개정 — skill-maker `## Code the skill bundles` 반영, 네 계획 공통)
- M1. facebook·reddit·threads·twitter 모두 새 레이아웃으로 이행한다(`## 공통 구조 기반`).
- M2. 계획은 외과적으로 개정한다. 전제가 바뀐 결정만 재합의하고, 결함 목록·다른 결정·검증 설계·SKILL.md 섹션 구조는 보존한다.
- M3. Claude Code 전용이다. 호출은 `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"` 형태만 쓰고, Codex용 경로 문장은 두지 않는다.
- M4. 틀(트리 뼈대·진입점·호출 형태·구조 테스트·테스트 import 방식)은 네 스킬이 같고, 내용(명령·기능 폴더·출력·SKILL.md)은 스킬별이다. "형제 스킬과의 유사성은 기준이 아니다"는 내용에만 적용된다.
- M5. 테스트 import는 빈 `tests/__init__.py` + pyproject `pythonpath`, import 모드는 prepend 유지. 순수 계약 단위 테스트는 in-process import가 된다.
- M6. 구조 테스트는 레포 공통 `tests/test_skill_layout.py` 하나이고, 먼저 구현하는 계획이 만든다.
- M7. 모듈 하나짜리 기능·저장소는 패키지 바로 아래 파일, 외부 시스템은 항상 폴더.
- M8. 사이트 쪽 시스템 폴더는 인터페이스 이름: `graphql/`(facebook·twitter·threads), `json_api/`(reddit).
- M9. 이행은 이 계획의 기존 행동 불변 재배치 PR에 합친다.
- M10. (reddit) I2 버전 검사 코드를 삭제하고 PEP 723 `requires-python`이 소유한다.
- M11. 명령 선언은 cli.py에 명령당 하나, 도메인 함수는 패키지 기능 모듈에 구현하고 선언이 참조한다.
- M12. (twitter) `graphql/` 안에 `protocol/`·`responses/`.
- M13. 스킬별 목표 트리는 `## 최종 스킬 디렉터리 구조`로 확정(2026-09-26 AST 조사로 방향 위반 0 확인).

### 내가 정한 것 (관례·코드로 판정 가능, 반대 시 승인 단계에서 뒤집는다)
- SKILL.md·`--help`·주석은 영어 유지(원 D6), 커밋·PR은 한국어.
- 개발 기록(실측 경위·코덱스 run id·제거 시험 표·판정 모델)은 이 계획 파일 끝의 "구현 기록" + 커밋 본문. 스킬 폴더에는 두지 않는다(finviz 선례).
- 본문 렌더링은 원문 충실: 공백 접기·제로폭 제거·`⏎`만, 마크다운 제거와 `[t](u)` 변환은 폐기(L2의 원인).
- 캡처 전용 오퍼레이션 6종의 **개명은 자동 채택하지 않는다**(탭 조작으로만 관측되어 "앱이 라우트를 렌더하며 싣는 읽기"라는 입장 근거가 없다). 관측되지 않으면 "may be renamed — the skill needs an update"로 보고.
- `reading/collect.py`는 PR ②에서 그대로 옮기고, PR ③ 단계 10에서 날짜창 판정(`window`)만 떼어낸다 — 날짜창 help·검증 일원화와 같은 변경 축. pending 꼬리 배출·커밋·오류 종료는 한 불변식(커밋된 것과 꼬리가 겹치지 않음)을 공유하므로 함께 둔다.
- `references/`는 만들지 않는다(아래 이유).

## 네 프레임이 이번에 결정하는 것

| 프레임 | 이번 변경 |
|---|---|
| principle over rail | 개명 입장: 이름 목록(레일) 대신 "앱이 그 GET 라우트를 렌더하며 스스로 싣는 preloader = 그 라우트의 읽기"라는 원리 + 라우트·서명 일대일 대응, 안 되면 닫힌다. 숨은 10/40 전환 → 명시 `--max-requests`. SKILL.md: 이력 절 해체, 판단마다 이유 한 절, 조건 없는 강제("먼저 about을 읽어라") 대신 해석을 바꿀 수 있을 때만 |
| interface over document | 오퍼레이션 계약을 `graphql/operations.py` 선언 하나로 — `registry.json` 서술 필드 삭제, JS 허용 목록·캡처 대상은 선언에서 파생. 명령 선언(`cli.py`)에서 파서·`--help`·context·`more:` 파생. 인터페이스 사실(첫 배치 한계·`window_reached`·unknown·팔로워 표본·복구 절차)은 help·끝줄·schema·fix가 소유하고 SKILL.md에 사본을 두지 않는다 |
| for the model, not the maintainer | SKILL.md·schema·`--help`에서 측정 경위("six-week", "0.8 MB", "replay method")·유지보수 폴백("profile header sometimes null") 삭제. `registry.json` `notes`·`verification`은 이 계획의 기록으로 |
| dense | schema 채움 설명 제거, 링크 미리보기 원 URL 복원, `~None` → `unknown`, `about` 2요청 → 평소 1요청, 헤더를 "requests 3 of 10 · window 15/120 per 10 min · fetched 0.7MB"로 |

## 공통 구조 기반 (2026-09-26 개정 — facebook·reddit·threads·twitter 계획에 같은 문장으로 들어 있다)

skill-maker `## Code the skill bundles`는 스킬 디렉터리 트리를 `--help`보다 먼저 읽히는 인터페이스로 보고, 모든 스킬이 같은 틀을 갖게 한다. 이 절은 그 틀을 이 레포의 네 SNS 스킬에 적용한 합의(`.claude/plans/SNS 스킬 4종 계획 구조 관례 개정 계획.md`의 M1–M13)이며, 이 계획의 다른 절과 충돌하면 이 절이 우선한다. 틀(트리 뼈대·진입점·호출 형태·구조 테스트·테스트 import 방식)은 네 스킬이 같고, 내용(명령·기능 폴더·출력·SKILL.md)은 스킬마다 제 목적대로다.

1. **트리 뼈대.** `scripts/`에는 `cli.py`와 패키지 `<스킬명>/` 둘만 둔다. 패키지 `__init__.py`는 비어 있다. 패키지의 최상위 하위 이름은 각각 기능·시스템·저장소·공용 중 하나다. 외부 시스템은 항상 폴더다: `aside/`(Aside CLI — repl 스폰·봉투·조각 회수, 봉투의 브라우저 쪽 JS)와 사이트 인터페이스 이름의 폴더(`graphql/` 또는 `json_api/` — 레지스트리·토큰·스니펫·응답→레코드·URL 형식처럼 그 사이트가 소유한 모든 형식). 기능·저장소는 모듈이 하나면 패키지 바로 아래 파일이고, 둘째 바뀔 이유가 생기면 폴더가 된다. 비파이썬 자산(`registry.json`, `*.js`)은 소유한 시스템 폴더 안에 두고 `Path(__file__)`로 찾는다. 사이트 시스템이 자기 스니펫을 읽어 `aside/` 실행기에 소스를 넘기고, 스니펫 이름 검증·누락 오류·fake의 스니펫 식별 계약은 이동해도 보존한다.
2. **`cli.py` 계약.** 첫머리 PEP 723 블록에 `requires-python = ">=3.11"`, `dependencies = []`. cli.py는 명령 표면 전부를 든다: 명령당 선언 하나(인자·help·choices·금지 조합과 fix·도메인 함수 참조) → argparse(모든 인자에 help, 닫힌 집합은 choices, root epilog에 종료 코드표), 옵션·조합의 문법 검증, 디스패치, emit, 결과 → 종료 코드 매핑, `more:`/`resume:` 직렬화. 도메인 로직은 없다 — 선언이 참조하는 operation·prepare 같은 함수는 패키지 기능 모듈에 구현한다. 대상 URL·식별자 해석(사이트 형식)은 기능의 준비 함수가 하고, 실패는 여전히 요청 전 exit 2다. 사이트와 무관한 순수 변환(날짜 파싱)만 공용으로 뺀다. stdout은 모델이 쓸 결과만(텍스트 기본, `--json`이면 JSON 한 문서, 싼 신호 먼저·비싼 상세는 핸들), stderr는 진행·진단. 0 성공, 2 잘못된 인자, 나머지는 epilog가 정의한다. 종료 코드표는 cli.py의 한 선언에서 help와 schema로 전달한다(사본 없음).
3. **호출 형태.** SKILL.md 프론트매터 `allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)`, 첫 문단의 호출문도 같은 형태. Claude Code 전용이다(Codex용 경로 문장은 두지 않는다). `more:`/`resume:`은 `uv run "<호출된 cli.py 절대경로>" <명령> …`: 경로는 resolve하지 않고(링크 철자 보존) 큰따옴표 안에서 `\ " $ \``를 escape하며, 나머지 인자만 `shlex.join`한다 — 작은따옴표 경로는 allowed-tools 패턴에 맞지 않아 권한 확인에 걸린다(2026-09-26 실측).
4. **import 방향.** 공용은 다른 공용만 import한다. 시스템·저장소는 공용·시스템·저장소만 import한다(기능 금지). 기능은 시스템·저장소·공용만 import한다 — 다른 기능은 import하지 않아서, 기능 하나를 나머지를 건드리지 않고 바꾸거나 지울 수 있다. `cli.py`는 기능·공용만 import하고, 패키지는 `cli`를 import하지 않는다. 모듈 단위 순환은 없다. 그래서 기능은 이어읽기 명령 문자열을 만들지 않고 핸들과 이어갈 인자를 돌려주며, cli.py가 `more:`를 조립한다. 질의 신원(문맥 키)은 cli.py가 선언에서 계산해 넘기고, 계정·viewer처럼 실행 중에만 아는 값은 기능이 붙인다. `schema` 같은 표시 명령은 cli.py가 출력 기능으로 바로 디스패치한다.
5. **공통 구조 테스트 `tests/test_skill_layout.py`.** 이행한 스킬마다 선언 한 항목(`{패키지: {최상위 하위 이름: 분류}}`). 검사 범위는 등록된 스킬의 `scripts/`와 `tests/<s>/`, 그리고 이 파일 자신이다(미이행 스킬은 범위 밖). 검사: `scripts/`의 항목이 `cli.py`와 패키지 둘뿐(`__pycache__` 무시) · 패키지 이름이 `sys.stdlib_module_names`에 없음 · 최상위 하위 이름이 모두 선언됨 · 위 import 방향과 순환 없음(AST) · 범위 안에 `sys.path` 변경·`site.addsitedir`·`spec_from_file_location` 없음 · 범위 안 테스트가 `cli`를 import하지 않음 · `cli.py` PEP 723 블록을 파싱해 `requires-python`·`dependencies` 존재 · SKILL.md allowed-tools가 호출 형태와 일치. 파일이 없으면 이 규칙으로 만들고(tdd 스킬로, 위반 트리 픽스처가 red가 되는 것부터), 있으면 그 파일이 규칙의 원천이니 항목만 추가한다. 스킬 고유의 단일 원천 검사는 이 테스트로 대체하지 않고 스킬 테스트에 남긴다.
6. **테스트 기계.** 빈 `tests/__init__.py`가 없으면 만들고(테스트 폴더가 `tests.<s>`로 등록돼 같은 이름의 스킬 패키지를 가리지 않는다), pyproject `[tool.pytest.ini_options] pythonpath`에 이 스킬의 `scripts/`를 추가한다. import 모드는 prepend를 유지한다(importlib 모드는 yfinance·finviz 테스트를 깬다, 2026-09-26 실측). 테스트는 공개 seam을 `from <s>.… import …`로 부르고, CLI는 `[sys.executable, CLI]` 서브프로세스로만 부른다(CI에 uv가 없다). `more:`/`resume:` 소비자(테스트·골든 도구·live 헬퍼)는 접두가 `['uv', 'run', CLI]`인지 단언한 뒤 나머지 인자를 `[sys.executable, CLI]`로 실행한다. 실제 `uv run`은 이동성 검증이 확인한다: 스킬 디렉터리를 공백·한국어가 든 레포 밖 경로와 `$`·따옴표가 든 경로에 복사해, 무관한 cwd에서 `uv run "<사본>/scripts/cli.py" --help`와 fake Aside 읽기 한 번을 실행하고 출력된 `more:`를 셸에서 그대로 실행한다.
7. **이행 PR의 경계.** 이 계획의 행동 불변 재배치 PR이 이행을 맡는다. 함께 바뀌는 것: 진입점·호출 형태·`more:` 접두와 그 소비자 · SKILL.md 프론트매터와 호출문(섹션 구조·나머지 문안은 불변) · README/`docs/usage.md`의 이 스킬 문장(옛 경로가 거짓이 되므로 이 PR에서) · 테스트의 CLI·JS 경로 · pyproject · `tests/__init__.py` · 구조 테스트 항목. **전환 시점**: 기존 테스트 부트스트랩(conftest의 sys.path 삽입·패키지 합성) 제거, 테스트 import 경로 전환, pythonpath 설정, 구조 테스트 등록은 `scripts/<s>/` 패키지를 실제로 만드는 단계에서 한꺼번에 하고, 그보다 앞선 seam 이관·골든 캡처 단계는 기존 부트스트랩을 유지한다. 여기서 "행동 불변"은 승인된 호출·help 변경을 뺀 행동 보존이다. 골든 비교가 허용하는 차이는 `more:`/`resume:` 접두, argparse `prog`(`usage: cli.py`), (facebook만) root epilog의 종료 코드표 신설뿐이며, 앞의 둘은 별도 테스트가 단언한다(접두 = allowed-tools 형태, 표 = cli.py 선언). 이 PR의 완료 명령에 `python3 -m pytest tests/test_skill_layout.py`를 넣는다.
8. **시나리오 하네스.** 모델 시나리오·제거 시험 하네스는 스킬 사본의 `scripts/cli.py`를 `uv run "<사본>/scripts/cli.py"`로 주입하고, 허용 패턴을 쓰는 하네스는 `Bash(uv run "<사본>/scripts/cli.py" *)`로 맞춘다.

## 최종 스킬 디렉터리 구조 (2026-09-26 개정 — `## 공통 구조 기반`을 따른다)

변경 축(무엇이 함께 바뀌는가)으로 나누되, 분류와 import 방향은 공통 기반 1·4가 정하고 공통 구조 테스트가 강제한다(옛 `threads.py → cli → reading → meta → guard → domain` 사슬과 결정 6은 이것으로 대체).

```
.claude/skills/threads/
├── SKILL.md
└── scripts/
    ├── cli.py                # ← threads.py + 계획의 cli/commands: PEP 723 · Command·Arg 선언(적용 명령·기본값·choices·help·조합 규칙·도메인 함수 참조) → argparse·root epilog(종료 코드표) · 조합 검증 · 디스패치(schema는 output으로 직접) · emit · 결과→종료 코드 · 문맥(질의 신원) 계산(← _cmds_common.context) · more: 조립(← _cmds_common.more_command)
    └── threads/              # 유일한 패키지 (__init__.py 비어 있음)
        ├── model.py          # 공용 ← _models.Post·_entities.User·Counts·_media.Media·_thread.Completeness·_walk.Page: dataclass = 공개 계약
        ├── errors.py         # 공용 ← _errors: ThreadsError·종료 코드별 fix·scrub
        ├── aside/            # 시스템: Aside CLI
        │   ├── repl.py       # ← _aside: 네트워크로 나가는 유일한 문. 스니펫 앞에 envelope.js를 붙여 실행
        │   └── envelope.js   # 청크 분할·봉투 출력 공용 (단계 13)
        ├── graphql/          # 시스템: Threads(Barcelona) GraphQL과 SSR preloader (바뀔 이유: Meta가 회전·개명·형태를 바꿈)
        │   ├── operations.py # 오퍼레이션 선언 한 곳 (아래 카탈로그 절)
        │   ├── registry.json # 회전하는 값만: {"version": 2, "operations": {id: {name, doc_id, flags, captured_at}}}
        │   ├── registry.py   # ← _registry: 번들 + 캐시 오버라이드 병합·검증·v1 마이그레이션
        │   ├── session.py    # ← _session: 라우트 HTML → csrf·actor·viewer·preloader 목록
        │   ├── ssr.py        # ← _ssr: __bbox 결과를 이름이 아니라 모양·신원으로 선택 (경쟁 후보 거절)
        │   ├── decode.py     # ← _walk(Page 제외): 연결 → Page (선언을 읽는다; 한 번만 디코드)
        │   ├── normalize.py  # ← _models·_entities·_media의 build_*: 원자료 → Post·User·Media
        │   ├── target.py     # ← _target: @handle·URL·shortcode 해석 (탭 접미사 보존)
        │   ├── transport.py  # ← _transport: page()/query(): 라우트 안전·리다이렉트·classify (보호층 — 동작 보존). capture를 모른다
        │   ├── refresh.py    # ← _refresh: 발견 → 입장 → 재생 검증 → 저장, 개명 채택, capture 호출. 시스템 결과만 반환한다
        │   ├── capture.py    # ← _capture: 앱 탭 관측 (refresh만 호출 — 순환 제거)
        │   └── snippets/     # ← browser/: page.js·graphql.js(2차 가드)·capture.js(대상·동작은 ARGS로)
        ├── guard/            # 저장소: 계정 보호 상태 (동작 보존)
        │   ├── budget.py     # ← _budget: 명령 상한(--max-requests)·10분 창·최소 간격
        │   ├── blocked.py    # ← _blocked.check_blocked·set_blocked: 체크포인트·rate limit 차단
        │   └── state.py      # ← _blocked.cache_dir·account_lock·write_state
        ├── store.py          # 저장소 ← _output: --out NDJSON 페이지 커밋·커서 핸들
        ├── reading/          # 기능: 읽기 흐름·수집 계약
        │   ├── common.py     # ← _cmds_common.check_access·check_actor·finish·profile_from_route: 접근 검사·결과 봉투 완성
        │   ├── listing.py    # ← _cmds_browse: home·user·graph·search·me 공통 흐름 (SSR 커서→Direct 재시작 폴백 보존). 핸들과 이어갈 인자를 돌려준다
        │   ├── post.py       # ← _thread.read_thread + _cmds_post의 post: 글 페이지 SSR → 레코드 + Completeness (argparse·파일 I/O 없음)
        │   ├── profile.py    # ← _cmds_post의 about: 카드 (평소 1요청, null 프로필이면 +1)
        │   ├── collect.py    # ← _listing: 연속·중복 제거·pending 꼬리·커밋
        │   ├── window.py     # 날짜창 파싱·필터·window_reached 판정 (PR ③ 단계 10에서 collect에서 분리)
        │   └── maintenance.py  # ← _cmds_meta(schema 제외): doctor·refresh 조립, refresh 결과에 봉투를 입힌다
        └── output/           # 기능: 모델이 보는 모양
            ├── render.py     # ← _render: 헤더·게시물·카드·완전성·커버리지 끝줄·다음 홉 (원문 충실)
            └── schema.py     # ← _schema: model 계약에서 schema 파생 (reading을 import하지 않는다)
```

- **분류(구조 테스트 항목)**: 공용 `model`·`errors` · 시스템 `aside`·`graphql` · 저장소 `guard`·`store` · 기능 `reading`·`output`.
- **이동으로 풀리는 역방향**(2026-09-26 AST 조사): `_refresh.refresh → _cmds_common.finish`(시스템→기능)는 refresh가 시스템 결과만 반환하고 `reading/maintenance.py`가 봉투를 입혀 없앤다. `_cmds_meta.run → _schema.schema`(기능→기능)는 cli.py가 `schema`를 `output/schema.py`로 바로 디스패치해 없앤다. `_cmds_browse.run → more_command`(기능→cli)는 기능이 핸들을 돌려주고 cli.py가 조립하는 것으로 뒤집는다. `threads.main → _target.parse_target`(cli→시스템)은 대상 해석을 reading 준비 단계로 옮긴다. `_transport ↔ _capture` 순환은 refresh가 capture를 부르게 해 없앤다(원 계획). dataclass를 `model.py`로 모아 output(기능)이 graphql(시스템)을 거치지 않고 계약을 읽는다. 이 표를 적용한 가상 그래프에서 위반 간선 0·순환 0이다.

```
tests/
├── __init__.py               # 빈 파일(공통 기반 6), 없으면 만든다
├── test_skill_layout.py      # 공통 구조 테스트(공통 기반 5), 없으면 만들고 있으면 threads 항목만 추가
└── threads/
    ├── conftest.py           # importlib 합성 제거(단계 7). 격리 THREADS_HOME·TZ=UTC·fake_aside 픽스처만
    ├── helpers.py            # run_cli(...) — [sys.executable, CLI] 서브프로세스, more: 접두 단언 후 실행(공통 기반 6)
    ├── fake_aside/aside      # 키 재생 + 녹화 모드(THREADS_RECORD) + 캡처 봉투 + 재생 미스 표지
    ├── live_bridge/aside     # live 전용 전달 브리지: 누적 원장(잠금)으로 예약·거절 후 실제 aside 실행
    ├── fixtures/
    │   ├── routes.ndjson     # 합성·PII 없음 (post 라우트: 새 이름·queryName 없는 SSR·ViewCount·무관 글 미끼 포함)
    │   ├── legacy/           # PR ① 이전 버전이 만든 캐시 오버라이드·커서 핸들·--out 파일 (구 버전 호환 시험용)
    │   └── builders.py       # 합성 HTML/페이로드 빌더 (프로덕션 import 없음)
    ├── test_post.py · test_listing.py · test_graph.py · test_profile.py · test_output.py
    ├── test_protection.py    # 차단→unblock 성공/실패, rate limit 만료, 창 가득, 브리지 실패 계수, 다른 계정의 이어읽기
    ├── test_refresh.py       # id 회전·개명 채택/거절·형태 변화·capture 성공/차단/정리 실패·구 캐시 마이그레이션
    ├── test_interface.py     # 명령별 인자·조합 규칙·--help·schema 대 실제 결과·more: 실행 가능·more: 접두 = allowed-tools 형태
    ├── test_render.py        # 원문 충실(`__`·`**` 보존), URL 불변, unknown 표기 (CLI 텍스트 출력)
    ├── test_bridge.py        # 청크 재조립: 순서·누락·형식 오류 봉투 (fake 다중 줄 응답)
    ├── test_contracts.py     # 순수 계약 단위(in-process: `from threads.graphql.transport import classify` 등): classify 우선순위, normalize 톰스톤·순환 인용, target
    ├── test_catalogue.py     # Meta 오퍼레이션 이름 리터럴이 graphql/operations.py·registry.json·tests fixtures 밖에 0 (옛 test_layers의 스킬 고유 검사)
    ├── test_fixtures.py · tools/{check_fixtures_pii.py, derive_fixture.py}   # 유지
    ├── js/{test_requests.js, test_capture_guard.js, test_envelope.js}      # 경로를 graphql/snippets·aside로
    └── live/{conftest.py, test_live.py}   # CLI 서브프로세스 + live_bridge
```

`references/`를 두지 않는 이유: 분기별 지식(복구 절차·명령 인자·필드 의미·커버리지)은 전부 인터페이스(fix·`--help`·schema·끝줄)가 소유하고, SKILL.md에 남는 판단은 모든 경로가 필요로 하는 것(무엇을 열지, 결과가 무엇을 뒷받침하는지, 언제 멈출지)뿐이다. 제거 시험 뒤에도 특정 분기에서만 필요한 문단이 남으면 그때 `references/`로 옮기고 그 분기의 fix가 가리키게 한다.

## 오퍼레이션 카탈로그 — 선언 하나 = 오퍼레이션 하나

```python
Operation(
    id="profile.replies",                        # 스킬의 안정 식별자 (registry.json 키)
    legacy_names=["BarcelonaProfileRepliesTabDirectQuery"],   # v1 캐시 마이그레이션·개명 보고용
    route="/@{viewer}/replies",                  # 이 오퍼레이션이 preloader로 실리는 라우트 (입장 근거)
    variables={"userID": REQUIRED, "first": 25}, # 템플릿 (registry의 variables_template 대체)
    signature=Signature(required={"userID"}, optional={"first", "after"},
                        values={"userID": "viewer_id"}),     # 정규화: 플래그 제외, 키 집합 + 값 제약
    connection="mediaData", items="thread_items[].post",
    pagination=RELAY,                            # RELAY | OFFSET | CAPPED | SINGLE_BATCH | SSR_ONLY
    identity=None,                               # 응답 신원 대조 규칙 (profile.page: data.user.pk == userID)
    ssr_shape="mediaData",
    chronological=True,                          # window_reached 주장 가능 여부
    discovery="route",                           # route | capture | ssr
)
```

- **registry.json v2**: `{"version": 2, "operations": {id: {name, doc_id, flags, captured_at}}}`. 현 `leaf`·`pagination`·`notes`·`verification`·`discovery`·`source`·`variables_template`·`flag_count`는 삭제(선언 또는 이 계획의 기록으로).
- **캐시 오버라이드 마이그레이션**: `version` 없는 v1 파일(Meta 이름 키·전체 spec)을 읽으면 `legacy_names`로 id에 매핑해 `verified` 항목의 `{name, doc_id, flags, captured_at}`만 취하고, 글 페이지 3종 같은 **퇴역 SSR 항목은 버리며**, 어느 선언에도 없는 키는 지금처럼 거절한다(fix: "Remove ~/.cache/threads-skill/registry.json; it holds entries this skill no longer knows"). 다음 저장 시 v2로 원자적 재작성. `fixtures/legacy/registry.json`(현 캐시와 같은 모양, 합성 값)으로 로드·refresh 둘 다 시험.
- **글 페이지 3종은 `SSR_ONLY`**: post 읽기는 HTML 한 번뿐이고 POST를 보내지 않는다. postID는 글 라우트 preloader들의 `postID` 변수(유일해야 함)에서 얻고, **세 페이로드 모두** `media.pk == postID`를 요구하며 모양으로 구분한다(target: `media.code ==` 요청 shortcode / upward: `text_post_app_info.containing_thread` / downward: `text_post_app_info.direct_replies`). 같은 역할의 후보가 둘 이상이면 거절(무관 글·ViewCount 미끼로 시험). → **이름이 바뀌어도 post는 깨지지 않는다.** `SSR_ONLY`는 registry 항목이 없고 `query()`가 거절한다. refresh는 이들을 갱신하지 않고 글 라우트가 세 모양으로 디코드되는지만 건강 검사로 보고한다.
- **개명 채택(라우트 오퍼레이션만)**: refresh가 각 선언의 `route`를 열었을 때 기대 이름이 없으면, 그 라우트의 preloader 중 **이미 다른 선언에 배정되지 않았고 정규화된 서명(`required ⊆ keys ⊆ required ∪ optional`, 값 제약 충족)이 맞는 이름**을 후보로 삼는다. 라우트의 모든 미배정 선언과 후보가 **일대일**로 대응될 때만 진행(프로필 탭 4종은 각자 다른 라우트라 서로 섞이지 않고, `/@user`의 profile.page `{userID}`와 profile.threads `{userID, first}`는 서명으로 갈린다). 입장 근거는 "앱이 그 GET 라우트를 렌더하며 스스로 싣는 preloader"이고, 그 뒤 재생 응답이 `decode`와 `identity`를 통과해야 캐시 오버라이드에 저장한다. 결과: `renamed: {id: {from, to}}`. 후보 0·복수·대응 실패·검증 실패는 채택 없이 `failed`에 이유. 파이썬 `query()`는 레지스트리(번들+검증된 오버라이드)에 있는 이름만 보낸다. **유일한 예외는 잠정 입장**: refresh만 `query(id, values, provisional=candidate)`로 위 입장 조건을 통과한 후보 하나를 그 한 호출에 한해 보낼 수 있고, 그때 `ARGS.admitted`에도 그 이름을 싣는다. 응답이 `decode`·`identity`·역할 검사를 통과한 뒤에만 오버라이드에 저장한다. graphql.js는 `ARGS.admitted` 포함 + `Query$` + `Mutation` 불포함을 2차로 확인한다.
- **역할 검사**(재생 검증에 추가): profile.page는 `data.user.pk == userID`, 프로필 탭은 받은 글의 작성자가 모두 대상 사용자(리포스트 탭은 `reposted_post`가 있는 레코드), feed는 연결이 글 레코드, search는 `searchResults` 연결. 이 검사로도 갈리지 않는 의미 차이(답글 탭 vs 스레드 탭의 데이터 교차)는 결정 13에 따라 받아들인 위험이고 `renamed` 보고로 드러낸다.
- **fix 구분**: data 없음 + execution error → `operation_rotated`, fix "Run refresh, then retry this command". 응답은 왔는데 선언의 경로가 없음 → `shape_changed`(현 `envelope_drift` 대체), fix "Threads changed this response's shape; refresh cannot repair it — tell the user the <command> reader needs an update". **순서는 현행과 같다**: 응답 분류가 먼저 보호 판정(체크포인트·rate limit·로그인 → 차단 기록·즉시 중단)을 하고, 그다음 `operation_rotated`/`shape_changed`일 때만 프로필 탭의 SSR 커서→Direct 첫 페이지 재시작 폴백(`_cmds_browse.py:65-74`, `test_browse.py:86-104`)을 한 번 허용하며, 그 재시도도 실패해야 최종 오류로 보고한다. 보호 판정 뒤에는 어떤 재시도도 없다.

## 인터페이스 변경 (PR ③)

| 대상 | 변경 | 근거 |
|---|---|---|
| 명령별 인자 (3층) | **명령 수준 부재**: `about`에 `--limit/--chars/--out/--after` 없음, `post`에 `--out/--after` 없음, `doctor/refresh/schema`에 `--json` 없음(항상 JSON). **조합 검증**(exit 2): `search --type users`와 `--sort/--tag/--chars`(계정 카드에는 본문이 없다), 명시 `--tab`과 URL 탭 접미사 충돌. **표시 전용**: `--chars`는 `--json`과 함께 주면 받아들이되 help가 "text output only"라 말한다 | 감사 B, 계획 검토 |
| `--max-requests N` | 모든 읽기 명령, 기본 10·최대 40(`refresh` 40·캡처 60 유지). `--limit`·`--since`·`--until`·`--out`은 상한을 바꾸지 않는다 | 결정 15, L5 |
| `post --limit` | help: "direct replies shown (each with its received sub-replies); parents and the post are always shown" | 감사 B |
| `user` URL 탭 | `/@x/replies` 등 탭 접미사를 `--tab` 기본값으로 보존 | 감사 B |
| 날짜창 | `--since/--until`은 home following·user 전 탭에서 로컬 필터, `window_reached`는 `chronological` 선언 탭만, 검증 한 번. 결과 끝줄이 실제 종료 조건별로 커버리지를 말한다(exhausted=표면 끝까지, window_reached=창 하한 통과 증명, limit/budget/query_failure=창 일부) | 감사 B, 계획 검토 |
| `about` | 평소 1요청 카드(null SSR이면 +1), `following/mutuals: unknown`(schema: "Threads does not publish it; graph following lists accounts"), exit 0 | 결정 9, L3 |
| `more:` | `@handle` 형태, `--limit`·`--chars`·`--max-requests`·`--json` 보존. 핸들·파일의 context는 **질의 신원만**(표시·상한 인자는 넣지 않는다) — 기존 context 키 집합과 같으므로 구 핸들·파일 그대로 재개 | 실측, 감사 B, 계획 검토 |
| 헤더 | `requests 3 of 10 · window 15/120 per 10 min · fetched 0.7MB`, `graph`는 관계 종류 | L5 |
| 렌더 | 원문 충실, URL·핸들 불변, `~None` → `unknown`, 링크 미리보기 `l.threads.com` → `u=` 원 URL | L2, L4 |
| fix | 코드별 전용 문구(exit 9 포함), `operation_rotated`/`shape_changed`, capture 권고는 `refresh --capture --post <public post URL>` 완전 명령 + "ask the user first: it opens a Threads tab in their browser" | 감사 B, 결정 14 |
| schema | 필드 고유 의미만, `User.counts`를 `Counts`로, 오류·doctor·refresh 결과·NDJSON 페이지 레코드 변형 공개(post에 `--out`이 없으므로 `ssr_complete` 폐기) | 감사 B |
| 이중 원천 | JS 허용 목록·캡처 대상은 선언에서 파생해 ARGS로(단계 8), page.js·`safe_path` 라우트는 공유 사례표 패리티 테스트, help의 "six" 삭제 | 감사 B, 계획 검토 |
| 데드코드 | `OutFile.parent_count`·`_blocked.unblock()`·`_errors.diagnostic()` — 참조 0 재확인 후 제거 | 감사 C |

## SKILL.md 섹션 구조 (영어; 각 문단은 제거 시험으로 존폐 판정)

인터페이스 사실(첫 배치 한계·`window_reached`·unknown·팔로워 표본·복구 절차)은 싣지 않는다 — 그것들이 **무엇을 뒷받침하는지**만 싣는다.

```
---
name: threads
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: (현행 트리거 유지 — 한국어 표현·bare URL·경계. 표면 나열만 줄임. skill-doctor로 이웃 충돌 확인)
---
# Threads through the user's own browser
   ¶ 실행: uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" … 를 한 줄로(프론트매터와 같은 형태); 명령을 셸 변수에 담지 않는다(zsh는 분할하지 않는다)
     → 발견은 --help, 객체는 schema, 실패는 결과의 fix  (필수 인터페이스 — 제거 시험 제외)
## Every request spends the person's account
   ¶ 레이트 헤더가 없고 체크포인트는 실계정에 걸린다 → 열기 전에 고른다(목록의 핸들·요약으로 관련 글·사람을 먼저 추림),
     답에 충분한 증거가 모이면 이어 읽을 수 있어도 멈추고 남은 커버리지를 말한다;
     복구(refresh·capture)도 같은 계정 활동이므로 답에 그 표면이 필요할 때만
## What a read can support
   ¶ 상위 답글은 보상된 위치이지 여론 표본이 아니다 → 반응을 요약할 때 정렬과 받은 범위를 함께 말하고 "대다수"를 주장하지 않는다
   ¶ 인용·리포스트의 주장은 원 작성자에게 귀속, 여러 정렬·검색에서 겹친 글을 독립 의견으로 세지 않는다
   ¶ 날짜는 글 작성 시각이다 → 리포스트 행위나 "그 기간의 활동"을 증명하지 않는다
   ¶ 신원·소개·비공개 여부가 해석을 바꿀 수 있을 때 about 카드를 먼저 본다
## Collections hold other people's activity
   ¶ --out은 필요한 말뭉치가 답보다 클 때; 파일과 ~/.cache/threads-skill/cursors는 타인의 활동 — 레포 밖에 두고 끝나면 지운다
     (budget.json·blocked.json은 계정 보호 상태이므로 지우지 않는다)
```

빠지는 것(→ 인터페이스): 계정·쿠키 설명(root `--help`), 글 읽기 계약·첫 배치·정렬 겹침·가지 열기 한계(`post --help`·끝줄), 완전성 필드(schema), 핸들 재사용·`more:` 그대로 복사(끝줄), 관계 목록 커버리지·unknown(`graph`/`about` help·schema), 날짜창 커버리지(끝줄), 인용 원글 보존·톰스톤(schema), 계정 검색 단일 배치(`search --help`), refresh/capture 절차·exit 5 중단(fix), 캡처 트래픽 계수(capture 결과). 삭제: 회전 이력, null 프로필 폴백, 존재하지 않는 글 리다이렉트(CLI exit 9), 형식 광고, 0.8MB 측정값, 알림 제외 이유(모델에게 알림을 읽을 수단이 없다). 완성본 전문은 단계 16에서 성진이 승인한다.

## 녹화 재생 하네스 (결정 11)

- **키 스키마**(정확히): page = `page|<경로?쿼리>`; graphql = `graphql|<Meta 이름>|<doc_id>|<정규 JSON: __relay_internal__ 플래그만 뺀 전체 변수(id·userID·after·query 포함)>`; capture = `capture|<seed URL>|<정렬된 대상 id 목록>|<동작 목록 정규 JSON>|<request_budget>`. doc_id가 키에 있으므로 회전 전후 응답이 섞이지 않는다.
- **스냅샷**: 녹화는 과제별 스냅샷 디렉터리 하나(`.tmp/threads-replay/<task>/`)이고 재생 런은 한 스냅샷에만 묶인다(이어읽기 사슬이 다른 시점의 페이지와 섞이지 않는다). 같은 키가 다른 내용으로 두 번 녹화되면 녹화를 거절한다(먼저 것 유지, 충돌 목록 출력).
- **재생 미스**: fake가 Threads 응답을 지어내지 않는다 — 전용 종료 코드와 stderr 표지로 실패하고 로그에 `harness_miss`를 남긴다. 미스가 난 런은 **무효**이며 비교에서 뺀다. 미스가 난 경로는 보충 라이브 녹화로 스냅샷에 추가하고, 그 과제의 **모든 팔을 동결된 스냅샷으로 다시** 돌린다.
- **순서**: SKILL.md 후보 본문을 먼저 동결 → 과제마다 FULL 팔로 라이브 녹화(과제당 ≤ 20요청, 10분 창 60 이하로 페이싱, 합계 ≤ 100) → CLI-only·minus-X 팔은 재생 → 본문을 고치면 고친 본문으로 FULL 재생을 다시 기준선으로 삼는다.
- 저장 위치 `.tmp/threads-replay/`(gitignored, 타인의 게시물 포함) — PR ③ 머지 후 삭제.

대표 과제(결정 10):

| id | 과제 | 드러나야 할 판단 |
|---|---|---|
| T1 | "Threads에서 Opus 5.5에 대한 반응을 조사해서 요약해줘" | 열기 전 선택, 상위 답글≠표본·범위 명시, 인용 귀속·중복 비계산, 충분하면 멈춤 |
| T2 | "지난 일주일 Threads에서 '클로드 코드 크레딧' 얘기가 어떻게 돌고 있어?" | 검색에 날짜 인자 없음 → 작성 시각으로 스스로 거름, 정렬 겹침, 범위 |
| T3 | "@golbin이 최근 2주 동안 쓴 글과 답글 활동을 정리해줘" | user 탭 threads/replies + `--since`, 고정글, 작성 시각≠활동 |
| T4 | "@golbin은 누구를 팔로우하고, 팔로잉·팔로워는 몇이야?" | unknown≠0, 팔로워 표본, 목록 길이로 수를 추정하지 않음 |
| F1 (오프라인 fixture) | 회전된 오퍼레이션으로 실패하는 명령 | refresh 1회 자율 → 재시도; capture는 묻기 |
| F2 (오프라인 fixture) | 체크포인트 차단 | 더 이상 요청 없음, 사용자에게 알림 |

## 작업 단계

각 단계는 `tdd` 스킬을 연 상태로 **재현/계약 테스트(레드) → 그린 → 리팩터**, seam은 결정 7(M5 반영). 단계 = 커밋. 새 레이아웃 이행은 PR ②가 맡는다(M9). `TaskCreate`로 단계를 등록하고 description에 아래 완료 판정을 그대로 적는다. 매 단계 후 `python3 -m pytest tests/threads -q`(단계 7부터 `tests/test_skill_layout.py` 포함), `node --test tests/threads/js/*.js`, `uvx ruff check --config pyproject.toml .claude/skills/threads/scripts tests/threads`, `python3 tests/threads/tools/check_fixtures_pii.py`.

### PR ① `fix/threads-post-page` — `fix: threads 글 읽기를 오퍼레이션 이름에서 분리한다`

현 평면 구조 안에서 최소 변경. 레지스트리 형식·캐시는 건드리지 않는다(글 3종 항목은 쓰이지 않게 될 뿐 남는다 — 구 캐시 오버라이드가 계속 로드된다).

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | 브랜치, 트래커(계획 파일 mv는 계획 세션에서 완료) | 브랜치·트래커 |
| 1 | **오프라인 post fixture**(새 이름 `BarcelonaPostPage*Query`, `queryName` 없는 SSR, ViewCount 페이로드와 무관 글 미끼, 부모 1·직접 답글 3·하위 1·톰스톤 1, 합성·PII 검사 통과) + CLI 레드 테스트: 본문 전문·역할·깊이·완전성 수치·`--limit 1`·`?sort_order=recent` 경로·미끼 거절 | 현행 코드에서 exit 6으로 실패(레드) |
| 2 | `_ssr`에 글 전용 선택(세 페이로드 모두 `media.pk == postID`, 모양 구분, 경쟁 후보 거절), `_thread`가 그것을 쓰고 postID는 글 라우트 preloader의 유일한 `postID`에서. `_transport.query`·`_refresh`의 이름 부분 문자열 분기 제거(글 3종은 query 불가, refresh는 글 라우트 디코드 건강 검사만) | 1의 테스트 그린. 글 읽기 경로(`_thread`·`_ssr` 글 선택)에 오퍼레이션 이름 비교 0(AST: 두 함수 안의 문자열 리터럴에 `Barcelona` 0). 구 캐시 fixture로 `home` 성공 |
| 3 | **L2 레드→그린**: `@a__b` 작성자 URL·본문 `__init__`·`**x**`가 텍스트 출력에 그대로 | CLI 텍스트 출력 테스트 그린 |
| 4 | 라이브 확인(명시 3명령, ≤ 6요청): `post <글> --limit 3`, `post <글> --sort recent --limit 3`, `post <답글 URL>` | 세 명령 exit 0, 완전성 수치 표시, recent가 다른 첫 답글 또는 같은 배치(겹침 허용). 결과를 커밋 본문에 |
| 5 | PR → `gh pr merge --squash` → Graphify 리빌드(로컬) | 머지 |

### PR ② `refactor/threads-layered-catalogue` — `refactor: threads를 cli.py와 패키지 하나로 옮기고 오퍼레이션 카탈로그로 모은다`

행동 불변(승인된 호출·help 변경 제외). 결정적 골든으로 증명한다.

| # | 단계 | 완료 판정 |
|---|---|---|
| 6 | **테스트 seam 이관 + 공백 메우기 + 골든**. 내부 import 테스트 14개를 CLI seam 또는 순수 계약 단위 테스트로 옮기고(이 단계는 기존 conftest의 importlib 합성을 그대로 쓴다 — 공통 기반 7 전환 시점), live는 `live_bridge`(누적 원장을 자식 프로세스들이 공유, 동시 예약·거절 테스트)로. **기존 동작에 대한 새 seam 사례**: 다른 계정의 이어읽기 거절, rate limit 만료 후 재개, unblock 실패 시 차단 유지, 청크 재조립(순서·누락·형식 오류), followers `server_capped`·following refetchable 전환, SSR 커서→Direct 재시작 폴백, 커서·파일 손상·심링크 거절. 관찰 가능한 행동이 없는 내부 테스트는 삭제하고 목록을 커밋 본문에. **골든**: 시나리오마다 새 `THREADS_HOME`·`TZ=UTC`·고정 순서로 모든 `--help`와 fixture 명령 전부의 텍스트·JSON 출력 + fake 요청 로그를 `.tmp/threads-golden/`에 저장. 정규화는 임시 경로 접두사와 `registry_age_days`·`started_at`·`created_at`(실행 시각) 셋만 — 예산 수치·커서 번호·요청 로그는 정규화하지 않는다 | 스위트 그린. 순수 계약 외 내부 모듈 import 0(`test_contracts.py`만 순수 계약을 import). 이관 전후 덮는 행동 대조표를 커밋 본문에 |
| 7 | **재배치(새 레이아웃 이행)**: 위 트리로 이동(함수 이동 포함), `cli.py`만 진입점(PEP 723 헤더), `transport ↔ capture` 순환 제거(refresh가 capture 호출), refresh는 시스템 결과만(봉투는 `reading/maintenance.py`), `schema`는 cli가 output으로 직접 디스패치, `post`가 argparse·파일 I/O를 받지 않게, dataclass를 `model.py`로. `more:` 접두를 공통 기반 3으로 바꾸고 소비자를 공통 기반 6으로, SKILL.md 프론트매터·호출문, `docs/usage.md:96`, JS 테스트 경로를 갱신한다. 전환 시점 작업: conftest importlib 합성 제거, `tests/__init__.py`, pyproject `pythonpath`, 순수 계약 테스트를 in-process import로, `tests/test_skill_layout.py` 생성 또는 threads 항목 추가 | 스위트 그린 · 골든 동일(허용 차이: `more:` 접두·`usage: cli.py`) · `more:` 접두 = allowed-tools 형태 테스트 green · `python3 -m pytest tests/test_skill_layout.py` green · 이동성(공통 기반 6: 한국어·공백·`$`·따옴표 경로 사본, 무관한 cwd, `uv run` `--help`·`schema`·fixture `home`, 출력된 `more:` 셸 실행) 성공 |
| 8 | **카탈로그**: `graphql/operations.py`, registry.json v2 + v1 캐시 마이그레이션(퇴역 SSR 항목 폐기·미지 키 거절·v2 재작성), `decode`·`ssr`·`listing`·`refresh`가 선언을 읽음, 이중 디코드 제거, **graphql.js 허용 목록과 capture 대상을 선언에서 파생해 ARGS로**(개명 채택은 단계 13) | 골든 동일 · fake 요청 로그의 이름·변수·doc_id 동일 · `fixtures/legacy/registry.json`으로 로드·refresh 성공하고 v2로 재작성 · `test_catalogue.py`: Meta 오퍼레이션 이름 리터럴이 `graphql/operations.py`·`registry.json`·tests fixtures 밖에 0 → **코덱스 리뷰 ①**(닫힌 술어: "골든이나 요청 로그가 달라지는 경로", 0이 될 때까지 같은 스레드 resume) |
| 9 | PR → 머지 → Graphify 리빌드 | 머지 |

### PR ③ `feat/threads-interface-skill` — `feat: threads 인터페이스 계약과 SKILL.md를 재설계한다`

| # | 단계 | 완료 판정 |
|---|---|---|
| 10 | **명령 선언**: `cli.py`의 선언에서 파서·help·context·`more:` 파생(도메인 함수는 참조만, M11), 인자 3층(부재·조합·표시 전용), `--max-requests`, `--out` 목록 명령 한정, URL 탭 보존, `reading/window.py` 분리와 날짜창 help·검증·끝줄 일원화 | 명령마다 부적용 인자 exit 2, 조합 규칙의 수락·거절 사례 표 전부, `more:`를 파싱·실행해 성공하고 `--limit/--chars/--max-requests/--json` 보존, `--until`만 준 요청도 같은 상한, `fixtures/legacy/`의 구 핸들·구 `--out` 파일이 새 CLI로 재개(파일-핸들 충돌 검사·pending 꼬리 보존) |
| 11 | **about + 렌더·헤더·링크·unknown** | about 요청 로그 1건(null SSR fixture는 2건)·exit 0·`following=unknown`, `~None` 0, 링크 원 URL, 헤더 새 형식 |
| 12 | **fix·오류 분류**: `operation_rotated`/`shape_changed`(SSR 커서 폴백 뒤), exit 9 전용 fix, capture 완전 명령 | 각 fix의 명령을 테스트가 파싱해 실행 가능, SSR 커서 폴백 회귀 테스트 그린 |
| 13 | **refresh 개명 채택(잠정 입장·역할 검사) + graphql.js 2차 가드 + JS 청크 공용화 + 라우트 패리티** | fixture: 개명된 라우트 preloader → 잠정 입장 1회 재생 → `renamed` 보고·오버라이드 저장·원 명령 성공 / 후보 복수·서명 불일치·일대일 실패·재생 검증 실패·역할 검사 실패 → 채택 안 함, 오버라이드 불변 / refresh 밖에서 `provisional` 사용 불가 / 잠정 재생 중 체크포인트 → 차단 기록·즉시 중단 / 카탈로그 밖 `SomethingQuery`는 파이썬 `query()`와 JS 둘 다 거절, `Mutation` 이름 거절 / 캡처 대상 미관측 → "may be renamed" 보고 / capture 성공·차단·정리 실패 CLI 경로 |
| 14 | **schema 정리 + 데드코드** | schema가 실제 CLI 결과 변형(성공·오류·doctor·refresh·NDJSON 레코드)을 검증하는 테스트 그린, 채움 설명 0 → **코덱스 리뷰 ②**(인터페이스 계약, 닫힌 술어: "일반 단일 세션에서 도달 가능한 결함", 0이 될 때까지 resume) |
| 15 | **SKILL.md 후보 동결 → 녹화(≤ 100요청) → 재생 하네스로 대조·제거 시험** | 무효 런(재생 미스) 0인 비교만으로 만든 제거 시험 표가 구현 기록에 있고, 남은 문단마다 빼면 나빠지는 근거 |
| 16 | **최종 시나리오 라이브**(T1–T4 각 1회, ≤ 80요청, live_bridge 원장) + F1·F2 오프라인 → 성진 SKILL.md 전문 승인 → **코덱스 리뷰 ③**(전체 diff + SKILL.md + schema, 4프레임) | 시나리오 합격 기준 충족, 승인, 리뷰 반영/미반영 이유 기록 |
| 17 | 문서(`docs/usage.md:115,126`, `README.md:84,89` 문구 확인 — 경로는 단계 7에서 이미 갱신), `python3 -m pytest tests/threads -m live -q`(live_bridge 원장 ≤ 30), `claude plugin validate --strict .claude/skills` exit 0, PR → 머지 → Graphify 리빌드, `.tmp/threads-replay/` 삭제 | 머지, 녹화 삭제 확인 |

코덱스(`gpt-6-astra` medium)는 리뷰만, 구현은 클로드가 끝까지. 지적은 반영하거나 반영하지 않는 이유를 커밋 본문에.

## 검증

```bash
python3 -m pytest tests/threads tests/test_skill_layout.py -q
node --test tests/threads/js/*.js
uvx ruff check --config pyproject.toml .claude/skills/threads/scripts tests/threads
python3 tests/threads/tools/check_fixtures_pii.py
python3 -m pytest tests/ --ignore=tests/sec --ignore=tests/finviz --ignore=tests/yfinance -q   # CI와 같은 한 프로세스 — 형제와 충돌 없음
claude plugin validate --strict .claude/skills
python3 -m pytest tests/threads -m live -q          # 실계정, 단계 17에서만 (live_bridge 원장)
```

- **행동 불변(PR ②)**: 결정적 골든(위 정규화 셋만) + fake 요청 로그 동일.
- **이동성**: 공통 기반 6 — 레포 밖 한국어·공백 경로와 `$`·따옴표 경로 사본에서 무관한 cwd로 `uv run "<사본>/scripts/cli.py"` `--help`·`schema`·fixture 읽기, 출력된 `more:`를 셸에서 그대로 실행.
- **제거 시험(단계 15, 재생 환경, Claude Opus 5.5)**: `claude -p --safe-mode --restricted --permission-mode acceptEdits --tools "Bash,Read" --allowedTools "Bash" --model claude-opus-5-5 --append-system-prompt-file <본문> --output-format stream-json --verbose "<과제>" < /dev/null`(finviz·yfinance에서 실측된 형태: `--allowedTools Bash` 없이는 permission_denials). 격리 디렉터리, `THREADS_ASIDE_BIN`=fake·`THREADS_FIXTURES`=과제 스냅샷·격리 `THREADS_HOME`, 소스 읽기 금지 명시, 본문과 CLI-only 팔이 주입하는 호출문은 `uv run "<사본>/scripts/cli.py"`(공통 기반 8). 팔: FULL · CLI-only(본문 없음) · 문단별 minus-X. 과제당 2회, FULL은 4회. 판정은 위 표의 "드러나야 할 판단"으로 Claude가 하고, stream-json에서 CLI 호출 수·요청 수·`harness_miss`를 센다. 빼도 같은 품질인 문단은 삭제(또는 판단을 바꾼 절만 축약).
- **최종 시나리오(단계 16)**: 스킬이 발견되는 환경(스크래치 프로젝트에 `.claude/skills` 링크)에서 `claude -p --model claude-opus-5-5 --permission-mode acceptEdits --allowedTools Bash Read Skill`, T1–T4 라이브 + F1·F2 오프라인. 합격: 과제 판단 충족 + 실패 호출 ≤ 1 + 과제당 요청 ≤ 20.
- 판정 모델·조건·결과는 구현 기록과 커밋 본문에(모델이 바뀌면 재검토 대상).

## 폐기하지 않는 결정
- 계정 보호층 전부(결정 5): 10분 120회 창·최소 간격 1초+지터·체크포인트 무만료 차단·rate limit 30분·응답 분류 우선순위(체크포인트 > rate limit > 로그인 > HTTP)·`doctor --unblock`·캡처 예약/정리 마커·Aside `u0` 고정·125초 타임아웃·청크 봉투 검증.
- 읽기 전용(쓰기·알림 declined), 완전성 필드의 의미, `not_paginable`·`server_capped`≠완료, 팔로워 서버 표본, 계정 검색 단일 배치, 목록 명령의 NDJSON 페이지 커밋·재개, 번호 커서 핸들과 그 context 형식, SSR 커서→Direct 재시작 폴백, about의 null 프로필 폴백, 합성 fixture PII 게이트.
- 기본 출력은 밀도 높은 텍스트, `--json`은 요청 시.

## 하지 않는 것
- 형제 스킬 변경, CI 워크플로 변경(워크플로의 실행 경로는 불변), 새 표면 추가(알림·from_author 검색·커뮤니티), 글 답글의 추가 페이지네이션 시도, 캡처 오퍼레이션 개명 자동 채택.

## 남은 위험
- Meta 구조는 계속 바뀐다. 이번 실측 수치(요청 수·크기)는 2026-09-25의 것이고 계약이 아니다.
- 개명 채택은 라우트·서명·일대일·재생 검증을 모두 요구하지만, Meta가 같은 라우트에서 같은 서명의 다른 읽기로 바꿔치면 탭 의미(예: 답글 탭인데 스레드 탭 데이터)를 검증할 수단은 모양뿐이다 → 채택은 캐시 오버라이드에만 하고 `renamed`로 보고해 사람이 볼 수 있게 한다.
- 녹화 재생은 녹화 밖 탐색에서 무효 런이 생긴다 → 보충 녹화와 전 팔 재실행으로 처리하지만, 보충이 반복되면 라이브 요청이 늘어난다(과제당 20 상한).
- 저장 목록(`me saved`)의 비어 있지 않은 형태는 여전히 미확인(9/5 A3). 성진이 글 하나를 저장하면 단계 16에서 1회 확인.
- 대조는 과제당 소수 런이다 — 방향은 보이지만 빈도는 모른다.

# 구현 기록

(2026-09-28–29, PR #27 `fix/threads-post-page`, PR #28 `refactor/threads-layered-catalogue`, PR ③ `feat/threads-interface-skill`)

## 계획을 따르지 않은 곳과 그 이유
- **글 신원(PR ①)**: 계획은 세 페이로드 모두 `media.pk == postID`였지만 실제 글 페이지의 Downward·ViewCount 페이로드에는 pk가 없고 `media.id = "<postID>_<작성자 pk>"`만 있었다(1요청 관찰). 신원을 pk 또는 그 id의 숫자 앞부분으로 정의했다. PII 게이트는 이 복합 id와 레지스트리 자리표시자(`<pk>`)를 합성 값으로 받는다.
- **테스트 기계(PR ②)**: 페이싱 sleep을 건너뛰는 process double(`FAKE_NO_SLEEP`)과 만료를 실제 판정으로 시험하는 `FAKE_CLOCK_OFFSET`을 두었다(스위트 73초 → 13초). live 브리지 원장은 날짜별 파일이다(9/5 누적 원장이 이미 30/30).
- **녹화 하네스**: 같은 키 재녹화를 거절하는 대신, 녹화 중 이미 있는 키는 스냅샷에서 내주고 새 키만 라이브로 보낸다(한 스냅샷 = 한 시점, 라이브 요청 절감). 실패한 라이브 호출은 기록하지 않는다. 오프라인 과제 F3(답보다 큰 말뭉치)을 추가했다 — T1~T4가 수집 문단을 시험하지 않아 그 제거 시험이 공허했다.
- **minus-X 배정**: 문단마다 그 판단이 '드러나야 할 판단'에 있는 과제에서만 돌렸다(T4에 minus-replies는 무의미).
- **재생 무효 런 처리**: 보충 녹화 뒤 무효 런만 다시 돌렸다(스냅샷에 키를 더해도 기존 키의 응답은 그대로라 유효 런은 유효하다). T1은 원장 20을 다 써서 남은 무효 런(CLI ×2, minus-replies ×1, minus-account ×2)은 비교에서 빼고 시도한 요청 수만 보조 근거로 적었다. T2는 검색어를 계속 바꾸는 과제라 동결 스냅샷으로 유효 런이 거의 나오지 않아(FULL 1) 결론 없음으로 두었다 — 그 판단(날짜·귀속)은 T3·T1의 유효 런이 결정한다.
- **실측으로 드러난 라이브 회귀 3건을 PR ③에 포함했다**: ① 스레드 탭은 `first` 11~19 사이 어딘가부터 execution error(4·10 성공, 20·25 실패) → 선언의 페이지 크기 10. ② 피드 질의가 앱 탭 밖 요청에 앱 셸 HTML·error 1357054로 답함 → 성진 승인 아래 진단 캡처(탭 3회)로 `BarcelonaFeedPaginationDirectQuery`와 `/following` 라우트를 확인, 모든 탐침(정확한 플래그, fb_dtsg·lsd·jazoest, `__a`·`__comet_req`·`__rev`·`__spin_*`·`__hs`·`__hsi`) 실패 → 성진 결정으로 피드는 라우트가 렌더한 첫 페이지만(렌더 전용 선언, not_paginable). ③ Aside 출력의 게시물 텍스트에 날 U+2028이 있어 `splitlines()`가 봉투를 쪼갬 → `\n`으로만 나눔.
- **웹 페이지 응답 분류**: 질의가 앱 셸 HTML로 답하면 transient가 아니라 shape_changed.

## 문단 제거 시험 (녹화 재생, 판정 모델 Claude Opus 5.5, 유효 런 기준; 괄호는 무효 런의 보조 근거)
| 문단 | FULL | 뺀 팔 / CLI-only | 판정 |
|---|---|---|---|
| 계정 요청을 쓰기 전에 고르기·충분하면 멈추기 | T3 요청 5~6, T1 8, T2 9~14 | T3 minus 8~9에 6개 글 답에 `--out` 파일, (T1 minus 18~19회 시도), T2 CLI 22~24 | 유지 |
| 상위 노출은 여론 표본이 아님 | T1 4/4가 정렬·읽은 몫과 "대다수 근거 없음" | T1 minus 유효 1/1 경고 없음, (CLI 0/2·minus 0/1, "압도적 긍정" 단정) | 유지, 검색 상위까지로 넓힘(FULL이 이미 그렇게 적용) |
| 인용·리포스트 귀속, 겹친 글 중복 계산 금지 | T1 원작자 귀속 4/4, 겹침 3/4 | T1 minus 귀속 0/2, 겹침 1/2 | 유지 |
| 날짜는 작성 시각(리포스트 행위 아님) | T3 4/4가 같은 이유로 리포스트 제외 | T3 minus 0/2, CLI 0/2(하나는 리포스트를 활동으로 읽겠다고 제안) | 유지 |
| 해석이 바뀔 때 about 먼저 | T3 3/4가 about을 읽고 그 입장에서 해석 | T3 minus 0/2, CLI 0/2; T4는 전 팔 동일(과제가 직접 요구) | 유지 |
| --out은 타인의 활동 — 레포 밖, 끝나면 삭제 | F3 4/4가 /tmp에 쓰고 파일·핸들 삭제, F1 3/4 핸들 삭제 | F3 minus 0/2 삭제(1은 레포 안 cwd에 씀), CLI 0/2, F1 CLI 0/2 | 유지 |

본문 없이도 인터페이스가 이끈 판단(본문에 넣지 않음): T4 following 수 unknown ≠ 0(전 팔), F1 refresh 1회 후 재시도·capture 안 함(전 팔), F2 체크포인트에서 멈추고 사용자에게 알림(전 팔).

## 최종 시나리오 (스킬이 발견되는 스크래치 프로젝트, Opus 5.5, 과제당 원장 20)
T1 합격(15요청, 실패 호출 0, 글 2개만 열고 랭킹≠표본·원작자 귀속·검색 간 반복·안 읽은 것 명시, 만든 핸들만 삭제) · T2 합격(20요청, 0, 작성 시각으로 기간 밖 글 제외, 인기순≠표본) · T3 합격(9요청, 1, about 먼저, 두 탭을 창 시작까지, 리포스트 제외 이유, /tmp `--out`과 핸들 삭제) · T4 합격(5요청, 0, following은 목록을 세어서, 팔로워는 Threads가 고른 일부) · F1 합격(refresh 1회 후 재시도; 0이 아닌 종료 2는 유도된 회전과 fixture에서 refresh의 부분 결과) · F2 합격(1요청 뒤 멈추고 사용자에게). SKILL.md 전문은 성진이 승인(2026-09-29).

## 코덱스 리뷰 (gpt-6-astra medium, read-only)
- ① 단계 8, 닫힌 술어 "골든이나 요청 로그가 달라지는 경로": `20260928-221342-threads-review1-993c` → resume `…-6b9b`. 8건 → 반영 1(부분 필드 v1 항목을 번들로 채움), 의도 7. 재확인 NO NEW DIFFERENCES.
- ② 단계 14, "일반 단일 세션에서 도달 가능한 결함": `20260928-224630-threads-review2-1766` → `…-1543` → `…-eb5c`. 15 + 3건 모두 반영(개명 프로필≠unavailable, SSR 모양 vs 회전, 404→9, refresh post_route 검사, fix 명령에 호출 전체, 목록 --max-requests ≥ 2, --chars 0, refresh 실패 봉투, help·schema 문구). 재확인 NO NEW DEFECTS.
- ③ 단계 16, 4프레임: `20260929-003415-threads-review3-e34a` → `…-b852` → `…-c827` → `…-c303`. 8건 → 반영 7(capture 동의 맥락, 명령별 budget fix, post 본문 전문 예외, 날짜 없는 글 개수 → 중복 제거 → 톰스톤 제외, Aside 시간 초과 fix), 미반영 1(SKILL.md 날짜 문단의 첫 절이 schema와 겹침 — 결과를 다시 유도하는 이유이고 제거 시험이 효과를 보였고 성진이 승인한 문안). 재확인 NO NEW FINDINGS.

## 라이브 요청 (실계정 u0, 두 날 합계 약 250)
구조 관찰·확인(글 페이지·라우트 6곳·post 3) 약 15 · 과제 녹화 T1 20·T2 16·T3 5(+ 첫 녹화 20)·T4 4 · 스레드 탭·피드 탐침 약 30 · 진단 캡처 탭 3회(관측 19 + 탐색) · 최종 시나리오 49 · live 테스트 15. 10분 창은 가장 많을 때 35/120.

## 남은 실패와 알려진 한계
- 피드는 라우트가 렌더한 첫 페이지(4~5개)만 읽힌다. 다음 페이지 질의(`BarcelonaFeedPaginationDirectQuery`)는 앱 탭 밖 요청을 거절한다 — 원인은 모른다.
- 팔로워 질의가 reported_total을 더 이상 싣지 않는다(live 테스트에서 None). 표본 경고는 help·schema가 한다.
- 리포스트 탭의 개명 역할 검사('reposted' — 묶음마다 reposted_post)는 실데이터로 확인하지 못했다. 틀리면 채택이 닫힌다(보고됨).
- 스레드 탭 페이지 크기 상한은 11~19 사이 어딘가다(10 사용).
- 저장 목록(`me saved`)의 비어 있지 않은 모양은 여전히 미확인(9/5 A3).
- 대조는 과제당 소수 런이다 — 방향은 보이지만 빈도는 모른다. T2는 결론 없음.
- `성진:` 장부: cli.py 요청 상한 40, normalize.py 공유 중첩 8단계, capture.js 영어·한국어 라벨, budget.py 10분 120회·1초 간격, state.py 계정 하나의 잠금.

## registry.json에서 옮긴 서술(v1 notes·verification·discovery·source)
- BarcelonaFeedDirectQuery | route:/ | preloader on / | notes: A5 verified. `first` is ignored (4-7 posts per page). | verification: POST replay: page1 + after (4/7 edges, 0 overlap)
- BarcelonaProfilePageDirectQuery | route:/@<user> | preloader on profile route | notes: SSR on profile route already carries data.user; POST only needed for refresh verification. | verification: POST replay (data.user)
- BarcelonaProfileThreadsTabDirectQuery | route:/@<user> | preloader on profile route | notes:  | verification: POST replay first=25 (15 edges) + after (0 overlap)
- BarcelonaProfileRepliesTabDirectQuery | route:/@<user>/replies | preloader on replies route | notes: A2 verified. | verification: POST replay first=25 (15 edges) + after (0 overlap)
- BarcelonaProfileRepostsTabDirectQuery | route:/@<user>/reposts | preloader on reposts route | notes: after not exercised (only 1 repost on sample). | verification: POST replay first=10 (1 edge, has_next false on zuck)
- BarcelonaProfileMediaTabDirectQuery | route:/@<user>/media | preloader on media route | notes: after not exercised. | verification: POST replay first=10 (10 edges)
- BarcelonaSearchResultsQuery | route:/search?q=<q>&serp_type=default | preloader on search route | notes: recent => search_surface null + recent 1. 250-590KB per page. | verification: POST replay default/recent/tags + after (10/10 edges)
- BarcelonaPostPageStrongIdTargetQuery | route:/@<user>/post/<code> | preloader + SSR __bbox on post route | notes: Read from SSR; no POST needed in normal reads. | verification: SSR parse only (POST replay also returns media)
- BarcelonaPostPageStrongIdDownwardQuery | route:/@<user>/post/<code>[?sort_order=recent] | preloader + SSR __bbox on post route | notes: Never POST. Replies beyond the SSR batch are not retrievable. | verification: SSR parse only. POST replay returns direct_replies:null even from the browser itself (F8)
- BarcelonaPostPageStrongIdUpwardQuery | route:/@<user>/post/<code> | preloader + SSR __bbox on post route | notes: Parent chain; 0 edges on a root post. | verification: SSR parse only
- useBarcelonaAccountSearchGraphQLDataSourceQuery | capture:search box | SPA: search nav -> type query -> Enter | notes: No page_info. | verification: POST replay (14 edges; errors[] with field_exception but data present)
- BarcelonaFriendshipsFollowersTabQuery | capture:followers dialog | SPA: rendered profile -> click role=button '팔로워 N' element | notes: Initial capture returned 20; server batch size can vary. Report server_capped. | verification: POST replay (20 edges, has_next false even at 5.7M followers)
- BarcelonaFriendshipsFollowingTabQuery | capture:followers dialog -> 팔로잉 tab | SPA: dialog tab click | notes:  | verification: POST replay (20 edges, end_cursor '20')
- BarcelonaFriendshipsFollowingTabRefetchableQuery | capture:followers dialog -> 팔로잉 tab -> scroll | SPA: dialog scroll to bottom | notes:  | verification: POST replay (10 edges, end_cursor '30')
- BarcelonaLikedPageViewerQuery | capture:sidebar /liked/ | SPA: click a[href='/liked/'] | notes: Pagination op/variables for page 2 not captured (A7). | verification: POST replay (251KB, page_info with end_cursor)
- BarcelonaSavedPageViewerQuery | capture:sidebar /saved/ | SPA: click a[href='/saved/'] | notes: Verify after saving one post. | verification: POST replay 391 bytes on an account with no saved posts; leaf unverified (A3)

