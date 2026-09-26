# facebook 스킬 총체 점검과 재설계 계획

> 계획 세션(2026-09-25)에서 승인 직후 이 이름으로 옮겼다(yfinance 선례의 파일명 체계). 원 구현 계획은 `facebook 스킬 구현 계획.md`(PR #1)다.
> 2026-09-26 개정: skill-maker `## Code the skill bundles`에 맞춰 트리·호출 형태·테스트 기계를 `## 공통 구조 기반`으로 바꿨다(`SNS 스킬 4종 계획 구조 관례 개정 계획.md`). 결함 목록과 다른 결정은 그대로다.

## Context

`.claude/skills/facebook`은 Claude가 사람처럼 페이스북을 돌아다니게 하는 스킬이다. 피드를 훑고, 글을 열고, 댓글을 읽고, 댓글 쓴 사람의 프로필·About으로 넘어가 거기서 다시 이어간다. 이 흐름을 로그인된 Aside 브라우저의 GraphQL로, 스크린샷 없이 밀도 높은 텍스트로 수행한다. 불변 제약은 세 가지다. ① 실계정이다: 요청 하나하나가 계정의 요청이고, 체크포인트는 사람이 풀어야 한다. ② 읽기 전용이다. ③ 창·한도에 걸린 결과를 '전부'라고 말하지 않는다. 성진이 이 이해를 확인했다.

**결론: 하층은 옮기고, 상층은 다시 쓴다(성진 결정 3).** 파서·전송·계정 보호·쿼리 레지스트리는 실제 응답으로 검증된 지식이라 동작을 보존한 채 새 레이아웃(`scripts/cli.py` + `scripts/facebook/`)으로 옮긴다. 결함은 그 위에 몰려 있다.
- **인터페이스가 거짓말을 한다.** 모든 읽기 명령이 같은 옵션을 받는다. 그래서 `about --help`에 `--since`·`--after`가 보이지만 런타임에 거절되고, `post --chars`는 무시된다. 결과 봉투(`stop_reason`, `window_complete`, `replies_incomplete`)는 어느 인터페이스에도 설명돼 있지 않다.
- **계정 비용이 보이지 않고 한정되지 않는다.** `--limit`·`--since`·`--out` 중 하나만 있어도 예산이 25에서 400으로 조용히 오른다. 최신순+`--since`는 창 하한을 지나도 멈추지 않는다. 텍스트 출력에는 쓴 요청 수가 없다. 코드 6의 기본 fix는 원인과 무관하게 400요청짜리 `refresh`를 권한다.
- **신호가 모델을 오도한다(실측).** `incomplete`가 거의 모든 글에 붙는다. 전문을 다 받은 글에 `truncated`가 붙는다. 스티커·사진 댓글이 `""`로 나온다. About 항목마다 `(unavailable)`이 붙는다. 광고가 `--limit`을 잡아먹는다.
- **유지보수가 흩어져 있다.** 명령 하나가 등록·검증·문맥·디스패치·핸들러·continuation 여섯 곳에 걸쳐 있다. stop_reason·부분 실패를 다섯 곳에서 다시 해석한다. 테스트는 내부 모듈을 약 100회 import해서, 파일만 옮겨도 깨진다.

**의도한 결과**: 명령마다 그 명령에 해당하는 인자만 보이고, 비용은 모델이 보고 정하는 값이 되고, 출력 첫 줄이 범위와 비용을 말하고, 모델이 읽는 모든 문장이 판단을 바꾼다. 명령·필드 하나를 바꿀 때 고칠 곳은 한 군데이고, 테스트는 공개 경계에 붙는다.

## 장부

### 사실 (2026-09-25 실측)
- 기준선: `python3 -m pytest tests/facebook -q` → 228 passed, 7 deselected(131.8s). 스킬은 SKILL.md 34줄에 `scripts/` 평면 20개 `_*.py`, `facebook.py`, `registry.json`, `browser/*.js` 5개로 총 4,229줄이다. 표준 라이브러리와 Aside만 쓴다(이식성은 이미 충족됐다. 폴더는 탐색성을 위한 것이다).
- 테스트 import: `_transport` 23, `_refresh` 14, `_errors` 12, `_blocked` 8 … 약 100회. 공개 seam(CLI 서브프로세스 + `tests/facebook/fake_aside/aside`)은 `test_cli.py`만 쓴다. fake aside는 스니펫 이름·시각만 기록하고(`fake_aside/aside:23-44`), capture를 소스 문자열 `const actions = ARGS.actions`로 식별한다. 여러 줄 조각·ANSI footer 프로토콜은 `test_repl_integration.py`의 별도 가짜 실행 파일이 검사한다.
- **최신순은 시간순이다**: `feed --sort recent` 12건 중 날짜 있는 9건이 전부 내림차순이다(나머지는 광고 4, 날짜 없는 `unknown` 1). `group --sort recent`도 두 그룹 18건 중 날짜 있는 15건이 전부 내림차순이다. 그룹 하나는 광고가 아닌 날짜 없는 글이 3/9였다.
- `_paginate.py:119-139`는 창 밖 기록을 버리기만 하고 멈추지 않는다. `window_reached`는 `_output.py:68,98`이 읽기만 하고, 어디서도 만들지 않는다. limit에 걸린 페이지의 나머지는 `pending`으로 보존되고, `END` 뒤 pending은 요청 없이 소진된다(`test_paginate.py:19-27`).
- 예산: `facebook.py:225-227`(25, `--limit/--since/--out`이면 400). 토큰용 홈 GET이 첫 요청이다(`_transport.py:189-193`). 코드 6의 기본 fix가 `refresh`다(`_errors.py:7-14`). 이 fix가 반복 커서·페이지 메타 누락·답글 첫 배치 한계에도 나간다.
- `emit`(`_output.py:153-183`)은 `ok=false`면 `--out` 요약 대신 전체 JSON을 출력한다. `schema`도 계정 차단 검사(`facebook.py:214-220`)를 먼저 거친다.
- `about`: 개요 응답에는 `directory_bio` 1개뿐이다. 나머지는 컬렉션 6개에서 나온다(zuck: 9요청·14항목). 컬렉션 토큰은 `app_collection:pfbid…`로 페이지마다 불투명하고, 이름은 화면 언어로 온다. 지금은 `--section`을 줘도 전부 받은 뒤 거른다.
- `incomplete`: `_parse.py:217-221`은 응답 전체에 issue가 하나라도 있으면(`graphql_errors`·`unsupported_path_patch`) 그 응답의 모든 story에 표시한다. 실측에서 profile 9/9, group 18/18, post에 붙었다.
- `schema`는 7,720자다. JSON Schema 4개가 들어 있고, 범위를 고를 수 없다. 설명에는 CLI에 없는 `include_raw=True`, "fetch output array", "date-window handling belongs to the caller" 같은 문장이 섞여 있다. `pinned`/`undated`는 dataclass 필드가 아니라 계산 속성이다(`_post.py:73-79`).
- `doctor`/`refresh`/`schema`의 `--json`은 효과가 없다(항상 JSON). `profile --sort {recent}`는 선택지가 하나뿐이다. 유지보수 명령은 `ready`·`complete` 같은 별도 stop_reason을 낸다.
- 댓글 `--out`은 재시도 가능한 답글 실패가 있으면 그 페이지를 커밋하지 않는다(`_cmds_people.py:105-118`). post→comments 이어읽기는 명령·문맥을 명시적으로 바꾼다(`facebook.py:184-198`, `test_cli.py:365-378`).
- 외부 참조: `.github/workflows/test.yml:18-20`(Python 3.12, `tests/facebook/js`, 픽스처 PII, ruff 경로), `README.md:83`, `docs/usage.md:95,114`, `tests/facebook/live/test_live.py`(모든 호출에 `--json`, About에 `--limit 3`).
- 계획 세션의 실계정 요청: 약 70회(doctor 1, feed 4, 기준선 시나리오 약 45, About 11, search 2, group 7). 구현 할당 300과는 별도다.

### 기준선 시나리오 (Claude Opus 5.5, `claude -p --safe-mode --restricted --permission-mode acceptEdits --tools "Bash,Read,Write" --allowedTools "Bash"`, 격리 디렉터리에 스킬 사본, 소스 읽기 금지)
- s1 "피드 최근 글 5개 요약": 2호출, $0.12. 첫 결과 5개 중 광고 3개와 빈 글 1개가 섞여 `--after`로 다시 읽었다. 답은 정확했고 광고를 따로 적었다.
- s2 "댓글 단 두 명이 평소 뭘 올리나": 4 CLI 호출(실패 1회는 zsh의 `echo =====` 오류로 스킬과 무관), $0.22. 팬아웃은 절제됐다(두 명·각 9건). 스티커·사진으로 보이는 댓글 5/9를 "내용이 비었다"고 보고했다. 모든 글에 붙은 `incomplete`는 무시했다. 캐시 속 개인정보를 사용자에게 알렸다(SKILL.md 문단이 작동함).
- s4 "Mark Zuckerberg About": 2 CLI 호출, $0.08. 인증 배지로 동명이인을 골랐다. 모든 항목의 `(unavailable)`을 "링크를 가져오지 못했다"로 잘못 해석해 사용자에게 전했다.
- 교훈: 모델은 실패하기보다 **잘못된 신호를 그대로 믿고 전달한다**. 그래서 우선순위는 문장보다 출력 신호다.

### 코덱스 리뷰
- 감사(`gpt-6-astra` medium, read-only, run `20260925-143242-fb-audit-eba5`, 11건) — 전부 반영. 요지는 F1 날짜 필터가 조용히 400 예산을 연다, F2 텍스트 출력에서 창 완결성이 사라진다, F3 schema에 봉투가 없다, F4 원인과 무관한 `refresh` 권고, F5 About `--section`이 전부 받은 뒤 거른다, F6 `--out` 실패 시 JSON을 쏟는다, F7 거짓 공통 옵션, F8 결과 상태 소유자 다섯, F9 여러 곳 편집, F10 사적 테스트 결합, F11 SKILL.md의 의식·레일·경위다.
- 계획 리뷰(같은 스레드, run `20260925-145034-fb-audit-bfe2`, 20건) — 전부 반영. 반영 위치는 P01·P02 → 커버리지 진리표, P03 → 예산 절, P04·P07·P15 → 보존 행렬, P05 → 요청 장부, P06 → 신호 품질, P08 → 광고, P09·P16 → records API, P10 → post→comments, P11 → About, P12 → 결과·종료 코드 행렬, P13 → schema, P14 → 상태 버전, P17 → 골든, P18 → 이동성·live 갱신, P19 → SKILL.md, P20 → 시나리오 전제다.
- 재검증(같은 스레드, run `20260925-150626-fb-audit-47c1`): 해소 14, 부분 해소 6(진리표 우선순위, 추정 불가 단계, 장부의 capture·live 헬퍼, 이슈 경로, 0건 예산 종료 코드, 시나리오 전제), 새 모순 5(모듈 DAG, 경계 판정 기준, 골든 전 fake 확장, About 종료 코드, 추정 정의). 전부 반영했다.

### 성진 결정 (2026-09-25)
1. 목적·제약·목표 이해 확인(위 Context).
2. 형제 스킬과의 유사성은 기준이 아니다. facebook이 자기 목적에 맞게 개선한다. (→ M4로 좁힘: 내용에만 적용)
3. 재작성 범위: **하층(계정 보호·쿼리·레코드) 이전 + 상층(CLI·reading·출력) 재작성**. 하층의 새 위치는 `account.py`·`aside/`·`graphql/`(M13).
4. CLI 표면은 자유롭게 바꾼다. 옛 `more:` 번호와 옛 `--out` 파일은 형식 버전으로 식별해, 바이트를 건드리지 않고 거절한다.
5. 요청 예산: **명시적 `--max-requests N`**(기본 25, 최대 400). 출력 첫 줄에 `requests=사용/예산`을 싣는다.
6. 테스트 seam: **① CLI 프로세스 + fake aside ② records 공개 함수(`facebook.graphql.records`) ③ JS 스니펫(node)**. 내부 구조를 단언하는 테스트는 세 경계로 옮기거나 지운다.
7. 구조: **바뀔 이유별 하위 폴더**(아래 트리). (→ M1·M13으로 대체: 기능·시스템·저장소·공용 분류)
8. 광고: **기본 제외 + `sponsored_skipped=N` 표시**, `feed --include-sponsored`로 포함.
9. 신호 품질 세 가지(incomplete·truncated 오탐·댓글 첨부)를 **이번에 고친다**. 원본 응답은 `.tmp/`(gitignore)에만 두고, 조사가 끝나면 지운다.
10. PR **두 개**: ① 행동 불변 재배치 + seam 이관 ② 동작 변경.
11. SKILL.md 검증: **변경·삭제 후보 문단만 제거 시험**. 문단당 시나리오 1건, 삭제 후보만 2건째를 돌린다.
12. `about`: **기본은 전부 읽는다**(비용을 도움말에 적는다). `--section`은 그 섹션을 찾으면 멈춘다.
13. 실계정 요청: **래퍼 장부 + 구현 세션 합계 상한 300**, 하루 150 이하. 시나리오 런에서는 `refresh`를 차단한다.
14. 잘린 글: **결론이 달라질 수 있을 때만 연다**(요약·입장 판단·전문 인용). 받은 부분만 인용할 때는 앞부분임을 밝힌다.

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

### 확정된 사실로 처리한 것 (묻지 않음)
- SKILL.md는 영어다. 위치는 프로젝트 스킬이다. ~~Codex는 `.codex -> .claude` 링크로 같은 파일을 읽으므로 실행 문장은 절대 경로 원리로 쓴다~~ → M3로 대체: 호출문은 `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`.
- `references/`는 만들지 않는다. 분기별 지식이 작고, 필드 의미는 `schema`가 소유한다.
- 판정 모델은 Claude Opus 5.5다(yfinance 결정 11 선례). 코덱스(`gpt-6-astra` medium)는 리뷰를 맡고, 구현은 클로드가 끝까지 책임진다.
- 개발 기록(측정 경위, 기각한 대안, 기본값 교정 줄의 대상 모델)은 커밋 본문과 이 파일의 `# 구현 기록` 절에 둔다.

### 미결
- 없음. 구현 중 새 판단이 필요하면 AskUserQuestion으로 묻는다.

## 네 프레임이 이번에 결정하는 것

| 프레임 | 이번 변경 |
|---|---|
| principle over rail | "Pair a date window with recent order"를 이유로 바꾼다: 최신순은 시간순이라 창 하한을 넘으면 닫히고, 랭킹순 창은 표본이다. "truncated면 인용 전에 열어라"는 "잘린 본문은 나머지 맥락에 대해 아무것도 말하지 않는다 → 그것이 결론을 바꿀 수 있을 때 연다"로 바꾼다. 발견 순서 `--help → schema → fix`도 순서가 아니라 선택지로 쓴다. |
| interface over document | 명령별 인자(선언 하나에서 파서 생성), `--capture POST_URL`, 봉투·stop_reason·NDJSON 레코드·마커 정의를 `schema`가 소유(종료 코드표는 cli.py 선언이 root epilog와 `schema result`에 함께 싣는다), 첫 줄 헤더(`requests`·`sponsored_skipped`·창 판정)와 `coverage:` 줄, 원인별 fix, `--out` 실패 요약, About 비용은 `about --help`에. |
| for the model, not the maintainer | schema의 `include_raw`·"fetch output"·"belongs to the caller"·플랜 § 문구 삭제, `raw` 필드 제거, SKILL.md 제목 "What has actually bitten" 폐기, `$FB` 의식 삭제, `--verbose` 도움말의 "never raw captures" 삭제. |
| dense | `is_pinned` 중복 제거, About의 `(unavailable)` 제거, 프로필 명령에서 명령 대상과 같은 `author:` 생략, 광고 기본 제외, schema는 "필드: 타입 — 의미" 한 줄씩. |

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

```
.claude/skills/facebook/
├── SKILL.md
└── scripts/
    ├── cli.py                   # ← facebook.py의 표면: PEP 723 · COMMANDS 선언(인자·help·choices·금지 조합·도메인 함수 참조·continuation 대상·문맥 키) → argparse·root epilog(종료 코드표 신설) · 문법 검증 · 디스패치 · emit(← _output.emit) · 결과→종료 코드 · 문맥 계산(← context_for) · more: 조립(← next_command)
    └── facebook/                # 유일한 패키지 (__init__.py 비어 있음)
        ├── errors.py            # 공용 ← _errors: FacebookError·scrub·diagnostic
        ├── outcome.py           # 공용(신설): STOP_REASONS·원인별 fix·커버리지 진리표·결과 봉투 — 결과 어휘의 유일한 소유자(종료 코드 번호는 cli.py)
        ├── aside/               # 시스템: Aside CLI
        │   └── repl.py          # ← _aside: repl 스폰·봉투·조각 회수·120s 번역. 스니펫 소스를 받아 실행한다
        ├── graphql/             # 시스템: Facebook 웹 GraphQL (바뀔 이유: 페이스북이 id·변수·URL·응답 모양을 바꿈)
        │   ├── session.py       # ← _session: 홈 HTML → 토큰
        │   ├── registry.py      # ← _registry: QuerySpec·오버라이드 병합·정렬 토큰
        │   ├── registry.json
        │   ├── resolve.py       # ← _resolve: URL·핸들 정규화 → 숫자 id
        │   ├── transport.py     # ← _transport: 간격·예산·classify·retry·iter_chunks. 스니펫을 읽어 aside에 소스로 넘긴다
        │   ├── refresh.py       # ← _refresh: 번들 채굴·캡처·재생 검증·원자 병합
        │   ├── snippets/        # ← browser/: tokens·graphql·page·mine·capture .js (각 파일 첫 줄 `// facebook-snippet: <name>`)
        │   └── records/         # 응답 → 레코드. 공개 API는 __init__의 재노출뿐(seam ②, 모듈과 같은 이름 금지)
        │       ├── parse.py     # ← _parse: NDJSON 해독·조각 병합·이슈를 story 단위로
        │       ├── post.py      # ← _post + _cmds_posts.posts_from_raw·fetch_post_story(선택 규칙): Post·Media·Link + FIELDS
        │       ├── comment.py   # ← _comment: Comment + attachments + 답글 핸들
        │       ├── entity.py    # ← _entity
        │       ├── about.py     # ← _about: 컬렉션 발견·필드
        │       ├── connection.py  # ← _paginate.find_page_info·connection_has_items, _cmds_people._search_edges(검색 순서)
        │       └── fields.py    # ← _schema: _iso·timestamp·FIELDS → "필드: 타입 — 의미"
        ├── account.py           # 저장소 ← _blocked: 차단 파일·계정 락·상태 원자 저장·cache_dir
        ├── cursors.py           # 저장소 ← _output.CursorStore: more: 번호 커서·형식 버전
        ├── collect.py           # 저장소 ← _output.OutFile: --out NDJSON 페이지 커밋·이어받기·형식 버전
        ├── reading/             # 기능: 무엇을 얼마나 읽고 언제 멈추나 (바뀔 이유: 읽기 정책)
        │   ├── dispatch.py      # ← facebook.read + validate의 대상 해석 + main의 배선(차단 검사·Transport·저장소 생성). cli가 준 문맥을 받고, 핸들과 이어갈 인자를 돌려준다
        │   ├── paging.py        # ← _paginate.paginate·in_window, _cmds_posts.page_options: 커서 루프·창(시간순 경계)·광고 계수·pending 꼬리
        │   ├── posts.py         # ← _cmds_posts.run: feed·profile·group·post
        │   ├── comments.py      # ← _cmds_people.comments·_failure: 부모 선택 → 답글 확장, 클로저 대신 작은 상태 객체
        │   ├── search.py        # ← _cmds_people.search
        │   ├── about.py         # ← _cmds_people.about: 개요 우선 매칭·컬렉션 순회·--section 조기 정지
        │   └── maintenance.py   # ← _cmds_maint + _blocked.unblock 호출: doctor·refresh·schema(종료 코드표는 cli.py가 인자로 넘김)
        └── render.py            # 기능 ← _render: 헤더(범위·비용)·레코드 밀도 텍스트·coverage 줄
```

- **분류(구조 테스트 항목)**: 공용 `errors`·`outcome` · 시스템 `aside`·`graphql` · 저장소 `account`·`cursors`·`collect` · 기능 `reading`·`render`. 방향은 공통 기반 4를 따른다. 옛 모듈 DAG(`account.errors ← account.guard ← queries.registry ← …`)는 이 규칙으로 대체한다 — `graphql.transport → account`는 시스템→저장소, `graphql.records.connection → graphql.transport.iter_chunks`는 같은 시스템 안이다.
- **이동으로 풀리는 역방향**(2026-09-26 AST 조사): `_refresh.refresh → _cmds_posts.posts_from_raw`(시스템→기능)는 `posts_from_raw`를 `records/post.py`로 옮겨 없앤다. `_cmds_posts ↔ _cmds_people` 순환은 `fetch_post_story`→records, `page_options`→paging으로 옮겨 없앤다. `_output.emit → _render`(저장소→기능)는 emit을 cli.py로 옮겨 없앤다. `facebook.main → _blocked·_transport`(cli→저장소·시스템)는 배선을 `reading/dispatch.py`로 옮겨 없앤다. `read → context_for·next_command`(기능→cli)는 cli가 문맥을 계산해 넘기고 기능은 핸들을 돌려주는 것으로 뒤집는다. 이 표를 적용한 가상 그래프에서 위반 간선 0·순환 0이다.
- 하위 모듈을 직접 실행하지 않는다. 자산 기준점은 `Path(__file__)`로 다시 잡는다(`graphql/transport.py`의 `snippets/`, `graphql/registry.py`의 `registry.json`). `~/.cache/facebook-skill`, `FACEBOOK_HOME`, `FACEBOOK_ASIDE_BIN`은 유지한다.

```
tests/
├── __init__.py                  # 빈 파일(공통 기반 6), 없으면 만든다
├── test_skill_layout.py         # 공통 구조 테스트(공통 기반 5), 없으면 만들고 있으면 facebook 항목만 추가
└── facebook/
    ├── conftest.py              # run_cli 헬퍼([sys.executable, CLI]·fake aside·FACEBOOK_HOME 격리·응답 큐). sys.path 삽입 삭제(pyproject pythonpath)
    ├── fake_aside/aside         # 확장: 명시적 마커로 스니펫 식별(capture 포함), 호출별 ARGS 기록(변수 이름·doc_id·referer), raw-stdout 모드
    ├── test_repl_integration.py # 유지: tmp_path에 인라인으로 쓰는 가짜 실행 파일(조각·ANSI footer·중복·body_file) — 이미 프로세스 seam
    ├── fixtures/*.ndjson        # 유지 + 신호 품질 쌍 픽스처
    ├── js/*.js                  # 경로만 graphql/snippets로
    ├── tools/{derive_fixture.py, check_fixtures_pii.py}
    ├── test_cli_surface.py      # 명령별 인자·도움말·오류 JSON·종료 코드·schema·차단 상태에서도 도는 help/schema·more: 접두 = allowed-tools 형태
    ├── test_protection.py       # 보존 행렬의 보호 항목 (CLI seam)
    ├── test_reading.py          # 페이지·창·광고·limit·pending·more:·원인별 fix·커버리지 헤더
    ├── test_comments.py         # 부모 선택 후 확장·답글 재시도·post→comments
    ├── test_collect.py          # --out 커밋·중단 복구·문맥·형식 버전·실패 요약
    ├── test_about_search.py
    ├── test_refresh.py          # CLI seam
    ├── test_records.py          # records 공개 함수: 픽스처 → 레코드·페이지 정보·이슈 (`from facebook.graphql.records import …`)
    ├── test_seams.py            # AST: tests/facebook/**가 import하는 production은 `facebook.graphql.records` 공개 API뿐 (옛 test_layout의 스킬 고유 검사)
    └── live/test_live.py        # -m live, 새 인터페이스로 갱신, 모양·불변식만, more: 소비는 공통 기반 6
```

## records 공개 API (seam ②, PR ①에서 만든다)

`captured_at`은 호출자가 넘긴다(재현 가능한 테스트를 위해). 내보내는 레코드는 `to_dict()` 결과이고, 내부 핸들은 레코드와 분리해 돌려준다.

| 함수 | 입력 | 반환 |
|---|---|---|
| `post_page(raw, *, source, connection_key, captured_at)` | GraphQL 응답 바이트 | `Page(records, page_info, has_items, issues)` — 최상위 글, 연결의 page_info, 파싱 실패 판별용 비어있지 않음 여부, 전역 이슈 |
| `post_story(raw)` | permalink 응답 | `(story | None, issues)` — 요청한 root story(현 `fetch_post_story`의 선택 규칙)와 전역 이슈 |
| `post_record(story, *, source, captured_at)` | story dict | Post dict |
| `comment_page(raw, *, post_id, captured_at, parents_only)` | 댓글 응답 | `Page(records, page_info, handles={comment_id: {feedback_id, expansion_token}}, issues)` — 현재 순서 규칙 유지 |
| `reply_page(raw, *, post_id, parent_id, captured_at)` | 답글 응답 | `Page(records, page_info)` — `replies_connection` |
| `search_page(raw, *, search_type, captured_at)` | 검색 응답 | `Page(records, page_info, has_items, issues)` — 연결 인덱스 순서(현 `_search_edges`) |
| `about_collections(raw)` | About 개요 응답 | `[{id, name}]` |
| `about_fields(bodies, *, profile_id, collection_names, captured_at)` | 응답 목록 | ProfileField dict 목록 |
| `SCHEMAS` | — | `{post, comment, entity, about}` → 필드 설명 |

모든 `Page.issues`와 `post_story`의 이슈는 읽기 핸들러가 결과 생성기에 넘겨 `coverage:` 줄이 된다. 이슈가 사라지는 경로가 없음을 명령별 테스트(피드·permalink·검색 각 1건)로 고정한다.

## 명령 선언과 인자 (단일 출처: `cli.py`의 `COMMANDS`)

각 명령은 이름·설명·대상 종류·인자 묶음·핸들러(`reading/`의 함수 참조)·continuation 대상·문맥 키·예산 여부를 한 번 선언한다. 파서·검증·`more:` 재조립이 이 선언을 읽는다. 대상 URL·핸들 해석은 `reading/dispatch.py`의 준비 단계가 `graphql/resolve.py`로 하고, 실패는 요청 전 exit 2다.

| 명령 | 인자 (그 외는 존재하지 않음) | 예산 |
|---|---|---|
| feed | `--sort {top,recent}` · `--limit` · `--since/--until` · `--include-sponsored` · `--chars` · `--after` · `--out` · `--json` | `--max-requests` |
| profile | `target` · `--limit` · `--since/--until`(서버 필터) · `--chars` · `--after` · `--out` · `--json` | `--max-requests` |
| group | `target` · `--sort {top,recent,activity}` · `--limit` · `--since/--until` · `--chars` · `--after` · `--out` · `--json` | `--max-requests` |
| post | `target` · `--limit`(첫 배치의 부모 댓글 수) · `--json` | `--max-requests` |
| comments | `target` · `--sort {top,recent}` · `--limit`(부모, `--out`에선 누적) · `--replies` · `--chars` · `--after` · `--out` · `--json` | `--max-requests` |
| search | `target` · `--type {top,posts,people,pages,groups}` · `--limit` · `--chars` · `--after` · `--out` · `--json` | `--max-requests` |
| about | `target` · `--section` · `--json` | `--max-requests` |
| doctor | `--unblock` | 고정(1~2) |
| refresh | `--capture POST_URL` | 고정 400 (`# 성진:` 주석 유지) |
| schema | `[OBJECT]` choices: `result`·`out`·`post`·`comment`·`entity`·`about` | 요청 없음 |

- 삭제한 것과 이유: `profile --sort`(선택지 하나), `post`의 `--chars`·창·`--after`·`--out`(단일 글·전문 표시·이어읽기는 comments로), `comments`·`search`의 창(측정되지 않음 / 랭킹이라 정지 조건 없는 예산 소모), `about`의 `--limit`·`--chars`·`--after`·`--out`·창(의미 없음), 유지보수 명령의 `--json`(항상 JSON 한 문서).
- `--verbose`는 루트 옵션 하나로 둔다.
- `help`·`schema`는 계정 상태(차단·손상된 캐시)와 무관하게 요청 없이 동작한다. 차단 검사는 요청하는 명령에만 적용된다.
- **post → comments**: `post`의 선언이 `continues_as='comments'`와 기본 문맥 `{sort: top, replies: false}`를 명시한다. `more:`는 `comments <url> --sort top --after N`(+ `--json`·명시한 `--max-requests`)이다. 잘린 첫 배치의 pending 부모, 소진된 root에 남은 pending, 글은 성공했지만 comments가 실패한 경우를 테스트한다.

## 예산 (`--max-requests`)

- 읽기 명령 기본 25, 최대 400(`# 성진: 400회 상한은 실계정 보호용, 일회용 계정으로 바꾸면 올려도 됨` 유지). `--limit`·`--since`·`--out`은 더 이상 예산을 바꾸지 않는다. 예산은 쿼리 정체성이 아니다. 같은 `more:`나 `--out` 재실행에 다른 `--max-requests`를 줘도 된다(`--chars`와 `--out`의 누적 `--limit`도 마찬가지).
- 예산 소진은 두 종류로 나눈다. **이어갈 수 있음**(커서·pending이 저장됨) → ok, exit 0, `stopped=budget` + `more:`(또는 같은 `--out` 재실행). 기록이 0건이어도 마찬가지다(예: 광고만 있는 페이지로 예산을 씀). **다시 시작해야 함**(토큰·id 해석·About 컬렉션 중간처럼 커서가 없는 단계) → exit 8, fix "rerun with a larger --max-requests". 비용을 알 수 있는 단계에서만 추정을 덧붙인다.
- **추정은 호출 전체의 요청 수다.** 홈 1 + id 해석(숫자 id면 0, vanity·URL이면 1) + 본 요청이다. About은 개요 1 + 컬렉션 수이고, 컬렉션 수는 개요를 받은 뒤에야 안다. 그래서 설정·해석 단계에서 멈추면 "setup needs 1–2 requests before any reading"만 말한다.
- 테스트: 설정 단계(홈), id 해석, 읽기 중간, About 중간에서 각각 예산이 다하는 경우.

## 결과 봉투·커버리지·종료 코드 (결과 어휘는 `facebook/outcome.py`, 종료 코드는 `cli.py`)

하나의 결과 생성기가 공개 계약을 만든다. 다른 모듈은 사유를 재매핑하지 않는다(현 `emit`의 `already_complete→exhausted`, `reply_batch_limit→query_failure` 재매핑 삭제).

**STOP_REASONS** — 값마다 (의미, 다음 행동)을 가진 선언 하나(`facebook/outcome.py`, 공용). schema·render·collect가 모두 이것을 읽는다. 결과 종류 → 종료 코드 번호는 cli.py의 선언 하나가 소유하고, root epilog와 `schema result`에 같은 표로 싣는다(cli.py가 `reading/maintenance.py`의 schema에 인자로 넘긴다).

| stop_reason | 의미 | 다음 행동 |
|---|---|---|
| `limit_reached` | 요청한 개수를 채웠다 | 더 필요하면 `more:` |
| `exhausted` | 요청한 범위에 더 읽을 것이 없다(원천의 끝, About 선택 완료, 단일 글) | — |
| `window_reached` | 시간순 결과가 `--since` 이전으로 넘어갔고, 그 경계까지 모두 전달했다 | — |
| `budget` | `--max-requests`를 다 썼다 | `more:` 또는 예산 상향 |
| `blocked` | 체크포인트·요청 제한 | 멈춘다. 사람이 확인한 뒤 `doctor --unblock` |
| `query_failure` | 원인별 실패(아래) | 원인별 fix |
| `ready` / `complete` | doctor / schema·refresh 성공(유지보수 전용) | — |

**원인별 fix.** 쿼리 id·필수 변수 낡음(`missing_required_variable_value`, 기대 구조 부재) → `refresh`. 반복 커서·페이지 메타 누락 → "retry later with the more: command; refresh does not change pagination". 로그인 → 브라우저 로그인 후 `doctor`. 예산 → 위 두 종류. 답글 첫 배치 한계는 실패가 아니라 `coverage:` 줄이다.

**커버리지 진리표** — 창이 있는 읽기의 둘째 줄. 위에서 아래로 **처음 맞는 행** 하나만 쓴다(우선순위: 실패 > 랭킹 표본 > 열린 창 > 닫힌 창).

| # | 순서 | 멈춘 이유 | pending | 실패 | 창 표시 |
|---|---|---|---|---|---|
| 1 | 어느 순서든 | 무엇이든 | — | 있음 | `open — <실패 요약>` |
| 2 | 랭킹순(top/activity) | 무엇이든 | — | 없음 | `sample (ranked order)` |
| 3 | 어느 순서든 | `limit_reached`·`budget` | 있거나 없음 | 없음 | `open — more: continues` |
| 4 | 시간순(feed/group recent) | `window_reached`·`exhausted` | 없음 | 없음 | `closed (as served)` |
| 5 | 서버 필터(profile) | `exhausted` | 없음 | 없음 | `closed (server-filtered)` |

**시간순 경계 판정.** 경계를 판정하는 기록은 **날짜 있고·고정 아니고·광고 아닌 글**뿐이다. 이런 글 중 `--since` 이전인 것이 한 페이지에 하나라도 있으면 그 페이지가 경계 페이지다. 고정글·날짜 없는 글은 창과 무관하게 통과시키되 `pinned`/`undated`로 표시하고, 경계 판정에는 쓰지 않는다. `--until`보다 새로운 글은 건너뛰고 계속 읽는다. `# 성진: 최신순=시간순 실측(피드 9/9, 그룹 15/15) 위의 정지. 순서가 어긋난 응답이 관측되면 경계 이후 한 페이지 더 확인하도록 바꾼다` 주석을 남긴다. 쌍 픽스처: 오래된 고정글만 있는 페이지(계속 읽음) vs 오래된 일반 글(정지) · 날짜 없는 글 · 광고만 오래됨(계속) · `--until`보다 새 글만 있는 첫 페이지(계속).

**시간순 경계와 pending.** 경계 페이지를 받으면 원천 커서를 `END`로 만든다. 그 페이지의 창 안 기록은 limit 규칙대로 전달하고, 남은 창 안 기록은 pending으로 저장한다. `more:`는 요청 없이 pending을 소진하고, 마지막 소진에서 `window_reached`로 끝난다. `--out`은 경계 페이지를 통째로 커밋하고 파일을 완료로 표시한다. 테스트: 경계+limit, 경계+pending 이어읽기, 경계+`--out`.

**결과·종료 코드 행렬** — `schema result`가 이 표를 싣는다.

| 상황 | ok | exit | stop_reason |
|---|---|---|---|
| 성공, 기록 ≥1 | true | 0 | limit/exhausted/window |
| 이어갈 수 있는 예산 소진(기록 0건 포함) | true | 0 | budget (+ `more:`) |
| 요청 전 인자 오류(argparse·검증) | false | 2 | — |
| Aside 불가 | false | 3 | — |
| 로그인 필요 | false | 4 | — |
| 차단(지금 또는 저장된 상태) | false | 5 | blocked |
| 쿼리 실패, 기록 0 | false | 6 | query_failure |
| 명시적 빈 결과·창 안 0건 | false | 7 | exhausted/window_reached |
| 부분 결과(기록 ≥1 + 실패, 또는 다시 시작해야 하는 예산 소진) | false | 8 | query_failure/budget |
| `--out` 이미 완료 | true | 0 | exhausted (`already complete` 표시) |
| 유지보수 성공 | true | 0 | ready/complete |

AST 검사는 "`stop_reason`에 STOP_REASONS 밖의 리터럴을 대입하거나 사유를 다른 사유로 매핑하는 코드가 `facebook/outcome.py` 밖 production에 없음"으로 한정한다(테스트·읽기 코드는 제외).

**텍스트 첫 줄**: `feed · sort=recent · 5 shown · sponsored_skipped=3 · stopped=window_reached · requests=6/25`. 창이 있으면 둘째 줄에 `window 2026-09-20..2026-09-25 · closed (as served)`가 온다. 부분 실패는 `coverage:` 줄, 마지막 줄은 `more:`다.

**`--out` 텍스트 요약**은 성공·실패 모두 한 줄이다: `feed · 42 saved to "…" · stopped=budget · requests=25/25 · resume: <같은 명령>`. 실패하면 `error=… fix=…`를 덧붙인다. 전체 JSON은 `--json`일 때만 낸다.

## 광고

- 적용 범위는 `feed`뿐이다. 그룹·검색·permalink로 연 광고 글은 거르지 않는다.
- 광고는 결과와 `--limit` 계수에서 빼고, 이번 호출에서 처음 본 광고 id 수를 `sponsored_skipped`로 센다(호출 단위, 중복 제외). 건너뛴 광고 id도 `seen`에 넣어, 다음 페이지에서 다시 세지 않는다.
- `--include-sponsored`는 cursor·`--out` 문맥 키다. 정책이 다르면 이어읽기를 거절한다(이미 건너뛴 광고는 되살릴 수 없기 때문이다).
- 테스트: 반복 광고, 광고만 있는 페이지(기록 0, 다음 페이지로 진행), 정책 불일치 이어읽기, `post`로 연 광고 글.

## 신호 품질 (성진 결정 9)

**원본 수집 절차.** CLI에는 원본 출력 옵션이 없다. 그래서 `.tmp/fb-raw/capture.py`(커밋 안 함)가 `facebook.graphql.transport.Transport`로 요청하고(실행은 `PYTHONPATH=.claude/skills/facebook/scripts FACEBOOK_ASIDE_BIN=.tmp/fb-ledger/aside python3 .tmp/fb-raw/capture.py` — 스크립트가 sys.path를 고치지 않는다) 본문을 `.tmp/fb-raw/`에 0600으로 쓴다. 대상은 profile 1페이지, group 1페이지(날짜 없는 글이 있던 그룹), 빈 댓글이 있는 post 1개, truncated 오탐 post 1개로 약 15요청이다. 원인을 확정하면 `tools/derive_fixture.py`로 구조만 보존한 합성 픽스처를 만들고, PII 검사를 통과시킨 뒤 원본을 지운다.

**수정과 쌍 픽스처**(양성·음성 짝이 없으면 "전부 끄기"가 통과하므로 반드시 짝으로):
- `incomplete`: 이슈가 난 조각이 속한 story에만 붙인다. 쌍: 영향받은 story vs 같은 응답의 영향 없는 형제 · 무해한 `errors` 경고 vs 필드가 실제로 빠진 경우 · 치명적 꼬리 청크(`test_transport.py:134-139`, 여전히 실패). story에 귀속할 수 없는 이슈는 `Page.issues` → 봉투 `coverage:`로 올린다.
- `truncated`: 원본에서 오탐을 일으킨 키를 특정해 제외한다. 쌍: 실제로 잘린 본문(서버가 전문보다 짧게 보냄) vs 오탐 본문. 판정 기준은 받은 텍스트 길이가 아니라 서버의 잘림 표시와 permalink 전문의 비교다.
- 날짜 없는 비광고 글: `creation_time`이 다른 경로에 있으면 파서가 읽는다. 없으면 `undated`를 유지하고 쌍 픽스처로 고정한다.
- 댓글 첨부: `Comment.attachments: [{kind}]`(sticker·photo·gif·video·link)를 추가한다. 텍스트는 `text[0/0 chars, complete]: "" · attachment=sticker`로 쓴다. 서명 URL은 싣지 않는다. 쌍: 첨부만 있는 댓글 vs 정말 빈 댓글.
- live 비교: profile·group 1페이지씩, `incomplete` 비율과 undated 수를 수정 전후로 기록한다.

## About (`reading/about.py`)

- 기본은 개요 + 컬렉션 전부다(zuck 9요청 = 홈 1 + 해석 1 + 개요 1 + 컬렉션 6). `about --help`에 "reads every visible collection: 3 + collections requests (2 + collections for a numeric id)"라고 쓴다.
- `--section X`: 개요에서 먼저 찾는다(`directory_bio`는 개요에 있다). 없으면 컬렉션을 순서대로 읽고, X가 처음 나온 컬렉션에서 멈춘다(`exhausted`). "섹션이 보이지 않음"은 모든 컬렉션을 **성공적으로** 읽었을 때만 말한다. 중간 컬렉션이 실패하면 `coverage: collection 2 failed — the section may be there`를 싣고, 종료 코드는 공통 행렬을 따른다(로그인 4, 차단 5, 기록 0건이면 6, 기록이 있으면 8). 테스트: 개요 매치, 첫·나중 컬렉션 매치, 매치 전 실패, 매치 없음, 예산 중단.
- 렌더: 링크가 있을 때만 `(url)`을 쓴다.

## schema

- 출력은 항상 JSON 한 문서다. 사람이 읽을 부분은 문자열 한 줄씩이다: `{"object": "post", "fields": {"id": "string — stable identity; dedupe on this", …}}`.
- `schema`(인자 없음): 객체 이름과 한 줄 설명, 그리고 `result` 요약. `schema result`: 봉투 필드, STOP_REASONS, 커버리지 진리표, 결과·종료 코드 행렬(cli.py 선언에서 전달), 헤더 줄 문법, 마커 정의(`?`=모르는 수, `unavailable` 핸들=막다른 길, `text[shown/received chars, complete|truncated]`, `pinned`/`undated`/`incomplete`/`attachment`). `schema out`: NDJSON `header`/`page` 제어 레코드, 형식 버전, 이어받기 규칙. `schema post|comment|entity|about`: 필드 목록.
- 필드 설명은 각 records 모듈의 `FIELDS` 표에 둔다. 계산 필드(`pinned`·`undated`)와 중첩 모양(`media[]`·`links[]`·`shared_post`·`attachments[]`), 직렬화 타입(datetime→ISO 문자열)을 포함한다. 대표 객체(`_schema_representative_post` 등)는 삭제한다. 테스트는 양방향이다: 대표 픽스처 전체의 `to_dict()` 키 ⊆ FIELDS, FIELDS ⊆ 픽스처에서 도달 가능한 키.
- `media[].url` 설명은 "signed, expiring, viewer-scoped — share only when the user needs the media"로 쓴다.

## 상태 형식 버전

- cursor 파일과 `--out` 헤더에 `format: 2`를 싣는다. 형식이 맞지 않으면 **파일을 수정(꼬리 자르기 포함)하기 전에** 거절한다. fix는 "created by an earlier version; restart the original query with a new path"다.
- 문맥 키(쿼리 정체성)는 명령·대상·정렬·창·type·section·replies·include_sponsored·account_id다. 예산·`--chars`·누적 `--limit`은 조정 가능한 제어값이다.
- 테스트: 옛 파일·옛 cursor(바이트 보존), 다른 계정·쿼리, 허용된 예산 변경, 거절 시 바이트 불변(`test_output.py:31-42,100-108` 이관).

## 보존 행렬 (PR ① 단계 3의 필수 산출물, 커밋 본문에 표로)

기존 테스트 이름마다 → 새 seam 테스트 또는 "삭제: 관찰 가능한 행동 없음 + 이유"를 적는다. 사적 import를 쓴다는 이유만으로는 삭제하지 않는다. 다음 행동은 반드시 새 seam 테스트로 살아남는다.
이 행렬은 **현재 동작**을 PR ①에서 보존하기 위한 것이다. PR ②가 의도적으로 바꾸는 동작(예: 읽기 중 예산 소진이 exit 8 → exit 0 + `more:`)은 해당 단계에서 테스트 기대값을 함께 바꾸고, 커밋 본문에 적는다.
- 보호: 체크포인트 → 차단 파일 → 다음 CLI 호출(`refresh` 포함) exit 5 · 로그인 판정 · 429/1357004 → 30분 차단 · 1357054 1회 재시도 후 차단 · 두 CLI 프로세스 동시 실행 시 요청 간격 ≥1.0s(fake 로그 시각) · 락 안에서 판정이 끝나야 대기자가 차단을 봄 · 예산 초과 exit 8(현재 동작) · 부트스트랩 실패·재시도의 요청 계수 · capture 예산 예약과 불완전 계수 시 예약 유지 · 캡처된 봉투 속 보호 신호 · 손상된 pace/blocked 파일 → exit 5.
- 전송: 조각 재조립, ANSI/status footer, 중복·malformed 봉투, `body_file` 거절, 스니펫 누락, 토큰 누출 없는 진단(`--verbose`).
- 읽기: pending 꼬리 요청 없는 소진, 반복 커서, 빈 페이지 + next 커서 계속, 비어있지 않은 연결의 파싱 실패 = exit 6, 명시적 빈 연결 = exit 7, 혼합 검색 순서, 숫자 대상 해석 생략.
- 댓글: limit 후 확장, 부모 중복 제거, 재시도 가능한 답글 실패 시 페이지 미커밋·재개·중복 0, 누적 부모 limit, 첫 배치 한계는 재시도 안 함, post→comments.
- `--out`: 페이지 커밋·꼬리 절단·문맥 대조·이미 완료·잠금.
- refresh: 미검증 id 비저장, 쿼리별 병합, 기본 모드의 댓글 3종 missing 보고.
- 이 행렬의 **보호** 항목 가운데 체크포인트 지속·간격·예산·capture 예약 네 가지는, 보호 코드를 일시 제거하면 red가 되는지 손으로 확인하고 그 결과를 기록한다.

## SKILL.md 섹션 구조 (영어; 변경 문단 제거 시험으로 존폐 판정)

```
---
name: facebook
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: (현행 유지. 바뀌면 claude -p "/skill-doctor"로 이웃 충돌 확인)
---
# Facebook through the user's own browser
   ¶ 실행: uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" … (프론트매터와 같은 형태, 한 줄).
     --help는 명령과 인자를, schema는 결과와 필드의 의미를, 오류의 fix는 회복을 말한다. (필수 인터페이스, 제거 시험 제외)
## Every request is the person's real account
   ¶ 체크포인트는 실계정에 오고 사람이 풀어야 한다. 팬아웃은 요청을 곱한다 → 가지를 치기 전에 질문에 필요한 사람·그룹 수를 정한다.
     예산은 질문이 요구할 때만 올린다.
## Order decides what a window can prove
   ¶ 최신순은 시간순이라 하한에서 닫히고, 랭킹순 창은 표본이며, 프로필 창은 서버가 거른다 → 날짜 질문에는 닫힐 수 있는 순서를 고른다.
   ¶ 닫힌 창도 페이스북이 그 피드·그룹에 보여준 것이지 친구가 올린 모든 글은 아니다 → 범위를 그렇게 말한다.
## Choosing whom to follow
   ¶ 검색은 같은 이름의 여러 사람을 돌려준다. 누구를 가리키는지가 답을 바꿀 때 정체(인증·About)를 확인하고 고른다.
     낯선 작성자의 About은 맥락이 필요할 때만 연다(컬렉션마다 요청).
## What a partial result can support
   ¶ 잘린 본문은 나머지 맥락에 대해 아무것도 말하지 않는다. 요약·입장 판단·전문 인용처럼 나머지가 결론을 바꿀 수 있으면 글을 열고,
     받은 부분만 인용할 때는 앞부분임을 밝힌다. 열어도 잘려 있으면 그 단서를 유지한다.
     coverage: 줄(빠진 섹션·답글)은 한계로 보고하고 "없음"으로 말하지 않는다.
## Collections and personal data
   ¶ 대화에서 읽기에 너무 큰 결과는 파일로 모은다. 파일과 캐시에는 남의 개인정보가 있다 → 레포 밖에 두고 끝나면 수집 파일을 지운다.
     계정 보호 상태는 지우지 않는다(지우면 차단·간격 보호가 풀린다).
```
삭제되는 옛 문장: `$FB` 별칭, 절대 경로 원리 문장(M3), "three posts … 34 requests", "Pair a date window with recent order", "What has actually bitten" 제목, `?`·`unavailable`·`text[a/b]`·sponsored 날짜 없음의 정의(→ schema), `more:` 복사·`url`/`author` 핸들 사용·post가 첫 댓글 배치를 준다는 설명(→ `--help`·출력), 캐시 경로(→ `schema out`·`doctor`). 완성본 전문은 단계 13에서 성진이 승인한다.

## 작업 단계

두 PR로 나눈다(성진 결정 10). PR ①이 새 레이아웃 이행을 맡는다(M9, `## 공통 구조 기반` 7). 단계=커밋이다. 각 단계는 `tdd` 스킬을 연 상태로, 합의된 세 seam에서만 red→green으로 진행한다. 트래커는 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 불러와 단계마다 등록한다. 설명에는 아래 완료 판정을 그대로 적는다.

### PR ① `refactor/facebook-layered-layout` — 행동 불변(승인된 호출·help 변경 제외) (`refactor: facebook을 cli.py와 패키지 하나로 옮긴다`)

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | `main`에서 브랜치 생성, 트래커 등록(계획 파일 이름 변경은 계획 세션에서 완료) | 브랜치 존재, 트래커 등록 |
| 1 | **fake aside 확장 후 골든 캡처**. 먼저 fake aside를 확장한다(명시적 스니펫 마커 인식과 기존 소스 문자열 인식 병행, 호출별 ARGS 기록, raw-stdout 모드). 이 확장은 CLI 동작을 바꾸지 않고 기존 테스트도 그대로 green이다. 그다음 `.tmp/fb-golden/`에 루트와 10개 명령의 `--help`, `schema`, 그리고 `test_cli.py`의 CLI 시나리오(테스트 함수 26개와 parametrize 3곳의 모든 케이스를 캡처 스크립트에 열거). 케이스마다 새 `FACEBOOK_HOME`과 새 응답 큐로 stdout·stderr·종료 코드·`--out` 파일·`FAKE_ASIDE_LOG` 순서를 저장한다. 정규화는 선언한 휘발 값(임시 경로·시각)만 한다. 이 단계는 기존 conftest의 경로 삽입을 그대로 쓴다 | 캡처 두 번 실행이 바이트 동일 · PR ① 머지 전까지 골든 보존 |
| 2 | **재배치(새 레이아웃 이행)**: 트리대로 `git mv`하고 `## 최종 스킬 디렉터리 구조`의 이동(함수 이동 포함)과 공통 기반 4의 방향을 적용한다. `cli.py`에 PEP 723 헤더를 두고 root epilog에 현재 종료 코드표를 싣는다. `more:` 접두를 공통 기반 3으로 바꾸고 소비자(`test_cli.py:72,109,181,283,357,376`, 골든 도구, live 헬퍼)를 공통 기반 6으로 고친다. SKILL.md 프론트매터·호출문, `README.md`·`docs/usage.md:95`의 경로, `tests/facebook/js`의 스니펫 경로를 갱신하고 스니펫에 명시적 마커를 붙인다. 전환 시점 작업(conftest와 개별 테스트 파일(`tests/facebook/test_registry.py:7` 등 `grep -rn sys.path tests/facebook`의 전부)의 경로 부트스트랩 제거, `tests/__init__.py`, pyproject `pythonpath`, `tests/test_skill_layout.py` 생성 또는 facebook 항목 추가)을 이 단계에서 한다. `graphql/records/__init__.py`에 공개 API를 만든다(기존 함수 재노출·얇은 래핑, 동작 불변). 기존 테스트는 행동 기대값을 유지한 채 import 경로·경로 부트스트랩·CLI/자산 경로·승인된 `more:` 접두 처리만 기계적으로 바꾼다 | 스위트 228 green · node green · 골든 바이트 동일(허용 차이: `more:` 접두·`usage: cli.py`·root epilog 종료 코드표) · `more:` 접두 = allowed-tools 형태 테스트 green · `python3 -m pytest tests/test_skill_layout.py` green · CI의 전체 명령(`python -m pytest tests/ --ignore=tests/sec --ignore=tests/finviz --ignore=tests/yfinance`) green |
| 3 | **seam 이관**: 내부 import 테스트를 세 seam으로 다시 쓰고(단계 1의 fake aside 기능 사용) **보존 행렬**을 채운다 | `test_seams.py`(AST): `tests/facebook/**/*.py`가 `facebook.graphql.records` 공개 API 외 production 모듈을 import하지 않음 · 보존 행렬 전 항목이 새 테스트나 삭제 사유에 대응 · 보호 네 가지 일시 제거 시 red 기록 · 골든 동일 → **코덱스 리뷰 ①**(행렬 누락·잃은 행동) |
| 4 | PR ① 생성(`## 무엇을 바꿨나/왜/검증`), `gh pr merge --squash`, graphify 리빌드 | 머지·그래프 갱신 |

### PR ② `feat/facebook-honest-interface` — 동작 변경 (`feat: facebook 명령 인터페이스와 범위·비용 신호 재설계`)

| # | 단계 | 완료 판정 (CLI/records/JS seam 테스트, 기대값은 손으로 쓴 리터럴) |
|---|---|---|
| 5 | **명령 선언 + 명령별 인자**, `--capture POST_URL`, post→comments 선언, help/schema의 계정 상태 독립, 상태 형식 버전, `live/test_live.py` 갱신(새 인자, 그리고 헬퍼가 `FACEBOOK_ASIDE_BIN`을 지우지 않고 물려받게 — 장부 래퍼 보존) | 명령마다 `--help`의 옵션 집합이 위 표와 같음(표는 테스트 안의 리터럴) · `about --since` → 오류 JSON exit 2 · 차단 상태에서 `schema`·`--help` exit 0, 요청 0 · 옛 cursor·옛 `--out` 거절 시 바이트 불변 · post→comments 네 경우 green |
| 6 | **outcome 단일 생성기**: STOP_REASONS·원인별 fix·결과/종료 코드 행렬·커버리지 진리표·첫 줄 헤더·`coverage:` 줄·`--out` 한 줄 요약 | 행렬의 각 행을 CLI로 재현하는 테스트 · 반복 커서 fix에 `refresh` 없음 · `--out` 실패 시 stdout 1줄 · 한정한 AST 검사 0건 |
| 7 | **`--max-requests`**와 두 종류 예산 소진 | `feed --limit 100`이 fake 로그상 25요청에서 `stopped=budget`·`more:` · 설정·해석·About 중간 소진은 exit 8 + 필요 추정 · `--max-requests 401` → exit 2 · `more:`에 다른 예산을 줘도 이어서 읽고 중복 0 |
| 8 | **시간순 경계 + 광고** | 진리표 각 행 테스트(시간순×{경계, 소진, limit, 예산, 실패}, profile×{소진, 예산}, 랭킹순) · 경계+limit+pending·경계+`--out` · 광고 규칙 네 경우 → **코덱스 리뷰 ②**(정지·예산·봉투·광고 계약) |
| 9 | **신호 품질**: 원본 수집 → 원인 확정 → 쌍 픽스처 → red → 수정 → live 전후 비교 → 원본 삭제 | 쌍 픽스처 전부 green(양성은 여전히 표시됨) · live 전후 수치 기록 · `.tmp/fb-raw/` 부재 확인 · PII 검사 통과 |
| 10 | **About**: 개요 우선, `--section` 조기 정지, 실패 시 부재 단정 금지, 링크 없을 때 생략 | 다섯 경우 테스트 · `--section directory_work`의 요청 수 = 홈+해석+개요+(직장 컬렉션 순번) · 렌더에 `unavailable` 0 |
| 11 | **schema 재설계** + 유지보수자 문장 제거, `raw`·`is_pinned` 제거 | `schema result`가 STOP_REASONS(outcome 선언)·종료 코드(cli.py 선언)·진리표 전부를 선언과 대조해 포함 · FIELDS 양방향 테스트 · 모델이 읽는 텍스트(`--help`·schema·fix)에 `plan §`·`include_raw`·`fetch output`·"belongs to the caller" 0건 |
| 12 | **SKILL.md 개정**, `README.md:83`·`docs/usage.md`의 동작 설명 갱신(경로는 PR ①에서 이미 갱신) | 문서 속 명령 전부 실행 성공 · `claude plugin validate --strict .claude/skills` exit 0 |
| 13 | **검증**(아래) → SKILL.md 확정 → **코덱스 리뷰 ③**(전체 diff + SKILL.md + `--help` + schema를 4프레임으로) | 검증 절 수치를 PR `## 검증`에 적는다 · 성진이 SKILL.md 전문을 승인한다 |
| 14 | PR ②, `gh pr merge --squash`, graphify 리빌드(main 직접 커밋), 이 파일에 `# 구현 기록` 추가 | 머지·그래프 갱신·기록 |

코덱스 리뷰의 지적은 반영하거나, 반영하지 않는 이유를 커밋 본문에 남긴다. 함정 후보는 클로드가 실제 호출로 재현한 것만 schema·SKILL.md에 싣는다.

## 실계정 요청 장부 (성진 결정 13)

- 모든 live 실행(단계 9 원본 수집, live 테스트, 이동성 확인, 모델 시나리오)은 `FACEBOOK_ASIDE_BIN=.tmp/fb-ledger/aside`로 돈다. 이 래퍼(커밋 안 함)는 호출마다 `.tmp/fb-ledger/ledger.tsv`에 시각·스니펫 이름·런 라벨을 한 줄 쓰고 실제 `aside`를 실행한다. 누적 300 또는 당일 150에 닿으면 실행하지 않고 exit 1로 끝난다(CLI는 exit 3으로 멈춤). 시나리오 런(`FB_LEDGER_MODE=scenario`)에서는 `mine`·`capture` 스니펫을 거부한다. 그래서 `refresh`는 첫 요청 뒤 멈춘다.
- 요청 하나 = aside 프로세스 하나다. 예외는 capture(한 프로세스에서 여러 요청)이고, 시나리오에서는 차단된다. 이 계획에는 live `refresh --capture`가 없다. 필요해지면 먼저 성진에게 묻고, 그 출력의 `request_count`를 장부에 더한다. 설정·실패·재시도도 모두 기록된다.
- 모든 런은 실제 `~/.cache/facebook-skill`(공유 보호 상태)을 쓴다. 런마다 남은 할당보다 큰 `--max-requests`를 주지 않는다.
- 할당: 원본 수집 약 15 · live 테스트 약 20 · 이동성 약 5 · 제거 시험 9런과 최종 6런 약 230 · 여유 30.

## 검증

```bash
python3 -m pytest tests/facebook tests/test_skill_layout.py -q
uv run --python 3.11 --with pytest==8.4.2 python -m pytest tests/facebook -q   # 런타임 최소 버전
node --test tests/facebook/js/*.js
python3 tests/facebook/tools/check_fixtures_pii.py
uvx ruff check --config pyproject.toml .claude/skills/facebook/scripts tests/facebook
python -m pytest tests/ --ignore=tests/sec --ignore=tests/finviz --ignore=tests/yfinance   # CI와 같은 전체 명령
claude plugin validate --strict .claude/skills
FACEBOOK_ASIDE_BIN=.tmp/fb-ledger/aside python3 -m pytest -m live tests/facebook/live/ -q
```

- **이동성**: 공통 기반 6대로 스킬 디렉터리를 공백·한국어 경로와 `$`·따옴표 경로에 복사한다. 무관한 cwd에서 `uv run "<사본>/scripts/cli.py"`로 fake aside `feed --limit 3`(레지스트리·스니펫 로드 경로)을 실행하고 출력된 `more:`를 셸에서 그대로 실행하며, 차단 상태 파일이 있는 상태에서 `--help`·`schema result`를 실행한다. live로는 `doctor`와 `feed --limit 3`을 실행한다.
- **모델 시나리오 (Claude Opus 5.5)**: 기준선과 같은 하네스(격리 디렉터리, 스킬 사본, 소스 읽기 금지, stream-json, 장부 래퍼 `scenario` 모드, 사본의 호출문 `uv run "<사본>/scripts/cli.py"` — 공통 기반 8)로 순차 실행하고 여러 날에 나눈다. 시나리오마다 CLI 호출 수(도움말·schema 호출과 읽기 호출을 구분), 실패 종료 코드, 장부의 요청 수를 센다. 전제가 성립하지 않은 런(예: 잘린 글이 한 번도 안 나옴)은 **판정 불가**로 적고, 다른 대상으로 다시 돈다.

  | id | 과제 (대상 고정) | 전제 | 합격 (진실한 종결 대안 허용) |
  |---|---|---|---|
  | F1 | 피드 최근 글 5개 요약 | 제거 시험 2차로 쓸 때: 5건 안에 잘린 글이나 `coverage:` 줄이 있음(없으면 판정 불가) | 읽기 호출 1회, 광고 없는 5건 |
  | F2 | 댓글이 많은 특정 글 URL의 댓글 단 두 명이 평소 뭘 올리나 | 첨부 댓글·잘린 글 존재를 사전 확인 | 두 명만 확장, 첨부 댓글을 "비었다"고 하지 않음, 요청 ≤ 30 |
  | F3 | Mark Zuckerberg About 정리 | — | 동명이인 구분, 링크 부재를 결함으로 전하지 않음 |
  | F4 | 오늘 내 피드에 올라온 AI 관련 글 모아줘 | — | 닫힐 수 있는 순서 선택, `window_reached`·명시적 `exhausted`면 "피드가 보여준 범위"로, 예산·limit이면 "열린 창"으로 서술, 전수 주장 없음 |
  | F5 | zuck이 2026년 7월에 올린 글 전부 | — | `closed (server-filtered)`면 전부로, 예산이면 열린 창으로 서술 |
  | F6 | 특정 사람 최근 글 60개를 파일로 모아줘 | — | 파일 수집, 비용 언급, 수집 파일 삭제 권고, 보호 상태 삭제 권고 없음 |
  합격: 각 기대 충족 + 스킬 원인의 실패 호출 ≤ 1.
- **변경 문단 제거 시험**(성진 결정 11): 먼저 전체본으로 같은 시나리오의 기준 답을 얻는다. 문단 하나를 뺀 사본으로 1차 시나리오를 돌려 판정이 나빠지면 유지한다. 통과하면 삭제 후보로 보고 2차로 확인한다. 둘 다 같은 판정일 때만 삭제한다. 전제가 성립하지 않은 런은 판정에 쓰지 않는다.

  | 문단 | 겨냥하는 판단 | 1차 / 2차 |
  |---|---|---|
  | 실계정·팬아웃·예산 | 여러 사람을 무작정 확장, 예산 무단 상향 | F2 / F6 |
  | 순서가 창의 증명력을 정함 | 랭킹순 창을 전수로 서술 | F4 / F5 |
  | 피드는 선택이지 전부가 아님 | 닫힌 창을 "친구 글 전부"로 서술 | F4 / F1 |
  | 누구를 따라갈지 | 첫 검색 결과를 본인으로 단정 | F3 / F2 |
  | 부분 결과가 뒷받침하는 것 | 잘린 본문을 전문으로 인용, 빠진 답글을 "없음"으로 | F2 / F1 |
  | 수집·개인정보·보호 상태 | 캐시 전체 삭제 권고, 레포 안에 수집 | F6 / F2 |

  판정 모델·조건·결과는 PR ② 커밋 본문과 `# 구현 기록`에 둔다(모델이 바뀌면 재검토 대상).

## 폐기하지 않는 결정

- 요청 간격 1.0~2.0초 지터·계정 락·차단 파일·체크포인트 판정 순서, 토큰 무캐시, 요청당 REPL 1회, 512Ki 조각 전달, JSON 레지스트리 + 쿼리별 오버라이드, 검증된 id만 저장하는 `refresh`, 번호 커서(`more:`), 페이지 단위 `--out` 커밋(limit 초과 가능)과 헤더 대조, 부모 선택 후 답글 확장, 재시도 가능한 답글 실패 시 페이지 미커밋, 밀도 텍스트 기본 출력, 읽기 전용, 스킬 자기완결(다른 스킬 import 없음).

## 하지 않는 것

- 쓰기 동작, 반응한 사람 목록, 릴스·스토리·메신저, 미디어 다운로드, CI 재활성화, 새 명령 추가, 형제 스킬 변경.
