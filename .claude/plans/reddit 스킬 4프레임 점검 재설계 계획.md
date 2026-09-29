# reddit 스킬 4프레임 점검과 재설계 계획

> 계획 세션 2026-09-25. 이 파일의 정식 이름은 `.claude/plans/reddit 스킬 4프레임 점검 재설계 계획.md`다 — 계획 승인 직후(또는 구현 세션의 첫 동작으로, 아직 옮겨지지 않았다면) 그 이름으로 옮긴다. 작업 트리의 무관한 변경(`.gitignore`, `.claude/harness-spec.md` 삭제, 다른 계획 파일, `.ultra-search/`)은 커밋에 섞지 않는다.
> 2026-09-26 개정: skill-maker `## Code the skill bundles`에 맞춰 트리·호출 형태·테스트 기계를 `## 공통 구조 기반`으로 바꿨다(`SNS 스킬 4종 계획 구조 관례 개정 계획.md`). 결함 목록과 다른 결정은 그대로다.

## Context

성진의 목표는 클로드가 **레딧을 숙련된 사람처럼** 읽는 것이다. 피드를 훑고, 글을 열어 댓글 트리를 읽고, 댓글 쓴 사람의 이력을 보고, 커뮤니티를 찾거나 그 안에서 검색하는 흐름 전체를 스크린샷 없이 밀도 높은 텍스트로 한다. 로그인은 Aside 브라우저 세션을 빌린다. 예산(공유 허용량)은 빡빡하고 응답은 한 번에 많이 오므로, **적게 요청해 많이 받고, 조금씩 보여주고, 나머지는 핸들로 잇는** 것이 설계 축이다.

이번 작업은 현행 스킬(PR #2, 2026-09-05)을 skill-maker의 네 성질(principle over rail, interface over document, for the model not the maintainer, dense)로 총체 점검하고, 유지보수성과 이식성을 높이는 재구성이다. 성공 기준은 퀄리티뿐이다.

점검 결론: **엔진은 건강하고, 문제는 계약의 가장자리와 소유권에 있다.** 스레드 상태 엔진·예산 잠금·경로 안전 검사는 견고하다. 결함은 다른 곳에 몰려 있다.
- 이어읽기 계약이 새는 곳: 깊이 루프, `--out` 탈락, `--context` 무시, macOS `/tmp` 거부.
- 출력이 사실과 다른 곳: 연산자 삭제, schema 불일치, 사이드바 은폐.
- 밀도 낭비: 110자 URL, 반복 `reply-to`, 0값 요약.
- 같은 일의 중복 구현: 캐시 정리 2벌, Listing 검증 3벌, 리디렉션 2벌, JS 2벌, 캐시 루트 3곳.
- 테스트만 부르는 죽은 코드.
- 선언되지 않은 환경 가정: `u0`, Python 3.11.

SKILL.md는 모델 행동을 실제로 바꾸는 문단(대조 실험)과 도구가 이미 가르치는 문단이 섞여 있다. 그래서 **경계 테스트로 행동을 고정 → 계층 구조로 재편 → 결함 수정 → 인터페이스·출력 재설계 → SKILL.md를 행동 근거로 재작성**의 순서로 간다.

## 장부

### 사실 (2026-09-25 실측)

- 규모: `scripts/` 파이썬 18모듈 2,446줄 + `browser/*.js` 2개(64줄), 표준 라이브러리만. 테스트 `tests/reddit` 2,249줄, 오프라인 207 통과·5 live 제외, JS 통과.
- 테스트 결합: `test_cli.py`(158줄)만 공개 seam(CLI 서브프로세스 + `fake_cli.py`). 나머지 13개 파일은 `reddit_skill._output`·`_thread`·`_transport` 등 **비공개 모듈을 직접 import** — 모듈을 옮기면 대부분 깨진다.
- 죽은 코드(CLI 경로에서 도달 불가, 테스트만 부름): `_errors.diagnostic`, `Transport.doctor`(CLI는 `_cmds_meta`가 따로 구현), `build_request`의 `'info'`·`'doctor'`·`'rules'` 표면(`about`은 `client.get`을 직접 호출), `CursorStore.save(pending=)`·`_paths`(thread_path — CLI는 `thread_key`만 씀), `OutFile.parent_count`·`.pending`, 쓰기만 하는 `first_seen_at`·`from_pointer_key`, `_SENSITIVE`의 페이스북 키(`fb_dtsg`, `lsd`, `jazoest`, `datr`, `c_user`, `xs`).
- 중복: 캐시 TTL·용량 정리 2벌(`_output.cleanup_cache` / `ThreadStateStore._cleanup`), 캐시 루트 결정 3곳(`_budget`, `_thread`, `_output._root`), Listing 모양 검증 3벌(`_transport._listing`, `_listing.walk_listing_nodes`, `_tree.walk_things`), 리디렉션 루프 2벌(`Transport.get`/`resolve`), JS 봉투·조각 전송 20줄 2벌(`fetch.js`/`resolve.js`), 캐시 크기 계산 2벌.
- 경계 누수: `_thread`가 `_output`의 비공개 `_open`·`_safe`를 import(저장 원시 기능이 출력 모듈에 있음).
- 이식성: `aside --account u0` 하드코딩(`_aside.py:30`), `fcntl`(POSIX 전용), `datetime.UTC`·`X | None` → Python ≥3.11 요구가 어디에도 선언되지 않음.
- 인터페이스 결함: 모든 명령의 `target` help가 "use explicit r/name or u/name for about"를 공유(무관한 명령에도 노출). `--limit`을 주면 호출당 요청 상한이 8→60으로 바뀌는 숨은 결합(help의 "explicit goals allow up to 60 requests"만이 단서). `doctor` 텍스트 요약에 무의미한 `0 shown · stopped=exhausted`. 요약 줄에서 `resets in`이 `sort=` 뒤에 붙는 조립 순서 버그(`budget 98.0 left · sort=top, resets in 571s`). 예산이 `98.0` 부동소수.
- 출력 밀도(라이브, `post … --limit 8`): 댓글마다 슬러그 포함 전체 permalink(~110자)가 댓글 출력 바이트의 큰 몫. 들여쓰기가 이미 말하는 `reply-to=`를 매 답글에 반복. 요약 줄에 0값(`missing=0 · orphans=0 · context rows=0`)과 매 호출 같은 고정 `note`. 첫 댓글 번호가 `[c2]`(게시물이 `[p1]`로 번호를 씀). **DFS 배치라 `--limit 8`이 최상위 댓글 2개(한 가지에 답글 6개)만 보여줌** — "레디터들은 뭐라고 해"에 필요한 폭이 배치 크기에 먹힌다.
- SKILL.md: "100 requests per ten minutes"(클라이언트 소유 값), "the tool normalizes them to www"·"expires cached threads… after 24 hours"(도구 내부 동작, 모델 행동 불변), 헤딩 "What has actually bitten"(출처 서술형).

### 코덱스 독립 감사 (`gpt-6-astra` medium, read-only, run `20260925-143127-reddit-audit-6217`, 오프라인)

결함 12건. 코드로 교차 확인한 것은 ✔.
- A1 ✔ 본문 정규화가 연산자를 지운다: `_render.py:14` `re.sub(r'\*{1,3}|~~|`{1,3}|\^', '', …)` — `2 * 3 = 6; 2^10` → `2 3 = 6; 210`.
- A2 ✔ 깊이로 접힌 댓글만 남으면 `next_expansion`이 `None`인데 `stop_reason=limit_reached`이고 `more:`가 같은 `--depth`를 반복 → 무한 무진전(`_cmds_thread.py:79`, `_thread.py:46`).
- A3 ✔ `continuation()`의 옵션 목록에 `--out`이 없어 수집 이어읽기가 화면 읽기로 바뀐다(`_cmds_common.py:18`).
- A4 캐시된 댓글에 `--context`를 올려도 재요청하지 않는다(캐시 키가 `[post, comment, sort]`) → 0건·0요청·`exhausted`.
- A5 부분 실패면 텍스트 모드에서도 전체 JSON을 쏟는다(`_cmds_common.py:37`), `post` 본문은 `--chars`를 무시하고 전문.
- A6 `schema`가 `additionalProperties: false`인데 실제 스레드 레코드엔 `anchor`·`context`·`orphan`·`shown_earlier`, 목록엔 `window_excluded`가 붙는다.
- A7 `about r/`의 사이드바(`description`)가 공개 설명(`text`)에 가려 `--chars`와 무관하게 안 보인다(`_render.py:74`).
- A8 문맥 행(`[cN shown earlier]`)에 fullname·URL이 없어 `reply-to=t1_…`를 풀 수 없다.
- A9 `--out` 스레드 수집이 배치마다 스레드 전체 상태를 마커에 직렬화: 댓글 1,000개에 내용 358KB, 체크포인트 4.85MB(13.5배).
- A10 ✔ 테스트 전용·중복 구현(위 사실 항목과 같음). A11 ✔ 이식성(위와 같음). A12 SKILL.md의 클라이언트 소유 값·"NSFW is labeled, not silently filtered"(검색은 `--nsfw` 없으면 서버가 거름 — 미검증).
- 구조 의견: 이 규모에서 광범위한 하위 폴더화에 반대, 먼저 소유권(저장 원시 기능·캐시 정책·doctor 단일화, 순수 스레드 로직과 저장 분리, `_models`+`_entities` 통합, `browser/` 유지). 순수 로직에 대한 내부 테스트는 합리적 seam, 문제는 죽은 구현을 테스트하는 것.

### 대조 실험 (Claude Opus 5.5, `claude -p --safe-mode --restricted --tools Bash --allowedTools Bash --permission-mode acceptEdits --append-system-prompt-file`, 실행마다 별도 `REDDIT_HOME`, 과제당 1회, 실계정 약 30요청)

B = CLI 경로 한 줄만, C = 같은 한 줄 + 현행 SKILL.md 본문(경로 치환). 원자료: 스크래치 `exp/runs/*/stream.jsonl`, 추출기 `exp/extract.py`.

| 과제 | B | C | 본문이 바꾼 행동 |
|---|---|---|---|
| T1 r/LocalLLaMA 주간 화제 글과 반응 | 2요청. 정렬·범위 미표기 | 4요청. "주간 top", "best 정렬 기준", "이 커뮤니티 안의 반응이고 레딧 전체가 아님", "322개 중 약 50개", 예산 보고 | 커뮤니티 귀속, 정렬 명시, 커버리지 |
| T2 스레드 의견 분포 | 1요청, 약 140개 읽음. 정렬 미표기 | 2요청, `--sort controversial`로 반대 의견을 따로 열고 "322개 중 160개, best·controversial", 커뮤니티 귀속, 댓글의 사실 주장은 미확인이라고 표시 | 정렬이 다른 질문에 답한다는 원리 → controversial 사용 |
| T3 u/cafedude는 어떤 사람 | `about cafedude`(접두사 없음) exit 2 → fix대로 복구. 60건·2주 창 명시 | `about u/` 먼저, 100건·3주 창, "이 계정이 실제로 누구인지는 알려주지 않는다" | 가명 한계 문장. **두 팔 모두 거주지(비버턴)·집 나무 견적까지 모아 신상 프로필을 만듦** |
| T4 r/Python 한 달간 uv 평가 | `--time month --sort relevance`(서버 기간) + 검색어 4개, 범위 명시 | `--sort new --since`(클라이언트 창, `window_reached`), 스레드 전체를 `--out`으로 받아 파싱 후 **작업 파일 삭제**, 커뮤니티 귀속 | 창과 목록 구분, 수집 파일 정리 |

- **두 팔 모두 스스로 폭을 확보했다**: 첫 `post` 배치(깊이 우선)를 본 뒤 이어읽기에 `--depth 0`/`1`, `--limit 60`을 썼다. 깊이 우선 기본값은 모델이 보완한다 — 다만 그 판단 재료(최상위 몇 개 중 몇 개를 봤는지)가 요약 줄에 `parents=140`처럼 암호로만 있다.
- 새 결함 E1 ✔: macOS `/tmp`(→`/private/tmp` 시스템 심볼릭 링크) 아래 `--out`이 "Symbolic links are not allowed…" + fix "Run this command with --help."로 실패(`_output._safe`가 모든 조상의 링크를 거부). 모델은 `/private/tmp`로 우회.
- 새 결함 E2: `--out` NDJSON을 모델이 파싱하다 두 번 깨짐 — 헤더·페이지 마커(`fullname` 없음)가 레코드 사이에 섞이고 레코드 종류마다 필드가 다름(`KeyError: 'fullname'`, `'depth'`). 파일 모양을 설명하는 인터페이스가 없다.
- 기본 모델이 이미 잘하는 것: 명령 발견(`--help` → 하위 help), 오류 fix를 따라 복구, 검색어 여러 개로 넓히기, 요청을 아끼는 캐시 이어읽기.

### 성진 결정

- 형제 스킬과의 일관성은 판단 근거가 아니다. reddit 스킬 자체의 목적에 최선인 설계를 택한다(2026-09-25). (→ M4로 좁힘: 내용에만 적용)
- 핵심 용도: **탐색 흐름 전반 균등**(피드·검색·스레드·사용자). 스레드 배치 방식을 한 용도에 맞춰 뒤집지 않는다.
- 범위: **엔진 유지 + 재구성**. 스레드 상태 엔진·예산 잠금·경로 안전 검사의 행동은 살리고, 경계 테스트 → 구조 재편 → 인터페이스·출력·SKILL.md 재설계.
- 대조 실험: 계획 세션에서 소규모로 실행(위 표). 구현 단계에서 새 본문으로 제거 시험을 한 번 더.
- Aside 계정 슬롯: 환경 변수 `REDDIT_ASIDE_ACCOUNT`(기본 `u0`).
- 테스트 seam: **CLI 서브프로세스 + 가짜 Aside**(주), **순수 코어 2곳**(대상 파서 `reddit.json_api.target`, 스레드 병합 엔진 `reddit.reading.thread`), JS 스니펫 node 테스트, **안전 열기 원시 기능**(`reddit.files`, 경합·링크 보안 경계, 계획 검토 후 추가). 나머지 내부 테스트는 이관 후 삭제.
- ~~디렉터리: **계층별 하위 폴더**(`cli/`·`read/`·`model/`·`net/`·`store/`), `scripts/` 최상위에는 `reddit.py` 하나, 루트 `__init__.py`는 파일 없는 부트스트랩으로~~ → M1·M13으로 대체(2026-09-26): `scripts/cli.py` + `scripts/reddit/`, 기능·시스템·저장소·공용 분류. "의존 방향을 드러낸다"는 의도는 공통 구조 테스트의 방향 검사가 이어받는다.

- 타인 신상: **관심사·활동은 요약하되, 거주지·집·가족·직장 같은 오프라인 신원 단서는 모아 제시하지 않는다**. 사용자가 그것 자체를 물으면 답한다. 이유를 붙여 SKILL.md에 한 문장.
- `--out`: **내용과 진행 상태를 분리**한다. 레코드만 담은 NDJSON과 원자 교체되는 `<out>.state`로 나눈다. 구 형식 파일은 이어받지 않고 명확한 오류를 낸다.
- 요청 상한: 현행 결합(기본 8, `--limit`·`--since`·`--out`이면 60)은 **유지하되, 걸리면 알린다**(`stopped=request_cap` + 다음 행동). 새 플래그는 없다.
- 댓글 밀도: **짧은 핸들** `https://www.reddit.com/comments/<post>/_/<comment>/`, `reply-to`는 부모가 바로 위에 없을 때만, 문맥 행에 id. `--json`은 전체 permalink 유지.
- SKILL.md: 아래 6섹션 구조(영어). 각 섹션은 제거 시험을 통과해야 남는다.
- `references/`: **만들지 않는다**. 분기별 내용은 전부 도구 기계(명령별 인자, `--out` 재개, 필드 모양)라 help·schema·오류가 소유한다. 본문에 남는 판단은 모든 경로에서 필요하다.
- 개발 기록: 이 계획 파일의 "구현 기록" + 커밋 본문. 스킬 폴더에는 두지 않는다(선례와 같음, 성진이 따로 정하지 않음).
- 검증 모델: 대조·제거 시험·시나리오는 Claude Opus 5.5, 코드·계획 리뷰는 코덱스 `gpt-6-astra` medium.

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
- (Claude 판단, 성진 수용 2026-09-26) live 테스트는 pytest 프로세스 패치(`live/conftest.py`의 `_transport.run_snippet`)와 진입점 import를 버리고, CLI 서브프로세스 + Aside 래퍼(`REDDIT_ASIDE_BIN`)가 누적 30요청을 자식 프로세스 경계에서 센다.

## 네 프레임이 이 재설계에서 결정하는 것

- **principle over rail**
  - SKILL.md는 절차("Start with --help")나 금지가 아니라 레딧의 모양을 말한다. 결과는 한 커뮤니티와 한 정렬이 고른 표본이고, 계정은 가명이고, 빈 검색은 부재가 아니다.
  - 모델은 이 사실에서 행동을 도출한다(T2-C가 원리에서 `controversial`을 골랐다).
  - 도구의 가드(요청 상한, 차단)는 걸릴 때 이유와 다음 행동을 말한다.
- **interface over document**
  - 호스트 정규화, 리디렉션 예산, 캐시 수명, 수치 한도, `--out` 재개, 필드 모양은 CLI(help·출력·오류·`schema`)가 소유하고 본문에서 뺀다.
  - 인터페이스가 사실과 달라서는 안 된다. schema가 실제 레코드를 거부하는 것(A6), fix가 원인을 말하지 않는 것(E1), `more:`가 진전 없이 반복되는 것(A2)은 이 성질의 위반으로 고친다.
- **for the model, not the maintainer**
  - "What has actually bitten" 같은 출처형 헤딩과 측정 이력은 본문에서 뺀다.
  - `# 성진:` 주석은 한계와 바꿀 조건에만 쓴다.
  - 코드 주석에 페이스북 이식 이력("Standalone Facebook cursor-store design")을 남기지 않는다.
- **dense**
  - 출력은 싼 신호를 먼저 준다: 요약 줄의 커버리지(최상위 몇 개 중 몇 개), 멈춘 이유, 다음 명령.
  - 비싼 상세는 핸들로 준다.
  - 0값, 매 호출 고정 문구, 슬러그 URL, 중복 `reply-to`는 뺀다.
  - SKILL.md에는 대조에서 행동을 바꾼 판단만 둔다.

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

## 설계

### 최종 스킬 디렉터리 구조 (2026-09-26 개정 — `## 공통 구조 기반`을 따른다)

```
.claude/skills/reddit/
├── SKILL.md                    판단만(6섹션). 인자·출력·오류·파일 모양은 CLI가 소유
└── scripts/
    ├── cli.py                  ← reddit.py(Parser·parser·positive·nonnegative·main) + _cmds_common.emit·continuation: PEP 723 · 명령 선언(명령별 target help) → argparse(root epilog: 종료 코드표·POSIX 전용 구절) · 문법 검증 · 디스패치 · emit · 결과→종료 코드 · more:/resume: 조립
    └── reddit/                 유일한 패키지 (__init__.py 비어 있음)
        ├── errors.py           공용 ← _errors: RedditError, 종료 코드별 기본 fix (scrub·diagnostic·_SENSITIVE 삭제)
        ├── files.py            공용 ← _output._safe·_open·_line·_root: 부모 별칭 정규화 + 디스크립터 기준 O_NOFOLLOW 순회(F8, seam 5), 원자 교체, 잠금, 계정 슬롯별 루트 경로
        ├── aside/              시스템: Aside CLI
        │   └── repl.py         ← _aside: `aside --account <slot> repl` 실행, 봉투 검증 (스니펫 소스를 받아 실행)
        ├── json_api/           시스템: reddit.com JSON (바뀔 이유: 레딧의 URL·Listing·thing 모양)
        │   ├── target.py       ← _target + _thread.target_dict: r/·u/·URL·공유 링크 파싱 (순수, seam 2)
        │   ├── things.py       ← _models + _entities + _schema + _listing.walk_listing_nodes + _tree.walk_things + _transport._listing: 검증 워커 1벌 + Post·Comment·Subreddit·User·Rule 빌더 + schema 파생
        │   ├── transport.py    ← _transport: 경로표(build_request), 응답 분류, 리디렉션 루프 1벌(get·share 공용). 스니펫을 읽어 aside에 넘긴다
        │   └── snippets/
        │       └── fetch.js    ← browser/fetch.js + resolve.js: 스니펫 1개(path 또는 url, manual redirect, 12MB 조각 전송)
        ├── budget.py           저장소 ← _budget: 공유 예산·페이싱·차단 (영속은 files)
        ├── cache.py            저장소 ← _thread.ThreadStateStore + _output.CursorStore·cleanup_cache·_cleanup + _cmds_common.identity: 스레드 상태·이어읽기 커서·계정 식별 기록, TTL·용량 정책 1벌
        ├── collect.py          저장소 ← _output.OutFile·_record·_flat·_state: `--out` 레코드 NDJSON + `<out>.state` 체크포인트, 재개·꼬리 복구
        ├── reading/            기능: 무엇을 열고 어떻게 잇나
        │   ├── listing.py      ← _listing(선택·중복 제거·날짜 창) (순수)
        │   ├── thread.py       ← _tree(walk_things 제외) + _thread의 순수 부분: 수집·순서·배치 선택·확장 기술·병합·메타데이터 (순수, seam 3)
        │   └── flows.py        ← _cmds_browse·_cmds_thread·_cmds_meta + _cmds_common.transport·empty_listing + reddit.validate의 대상 해석: 명령 실행(전송·읽기·저장을 잇는 접착층). 핸들과 이어갈 인자를 돌려준다
        └── render.py           기능 ← _render + emit의 시각 표시(_models.timestamp 사용): 요약 줄, 항목 표현, 본문 정규화
```

**분류(구조 테스트 항목)**: 공용 `errors`·`files` · 시스템 `aside`·`json_api` · 저장소 `budget`·`cache`·`collect` · 기능 `reading`·`render`. 의존 방향은 공통 기반 4가 정하고 공통 구조 테스트가 강제한다(옛 "위에서 아래로만 import, 구조 테스트는 쓰지 않는다"와 계층 폴더 결정은 이것으로 대체). `reading/listing.py`·`thread.py`는 I/O가 없다 — 리뷰와 seam 3 테스트(파일·서브프로세스 없이 동작)로 지킨다.

**이동으로 풀리는 역방향**(2026-09-26 AST 조사): `_thread → _output._open·_safe`(저장 원시 기능이 출력 모듈에 있음)는 `files.py`로 옮겨 없앤다. `ThreadStateStore.key`와 `create_state`가 함께 쓰는 `target_dict`는 `json_api/target.py`로 옮겨 cache(저장소)가 reading(기능)을 부르지 않게 한다. `_cmds_browse.run`·`_cmds_thread.run → _cmds_common.continuation`(기능→cli)은 기능이 핸들과 이어갈 인자를 돌려주고 cli.py가 `more:`/`resume:`을 조립하는 것으로 뒤집는다. `emit → _models.timestamp`(cli→시스템)는 시각 표시를 render로 옮겨 없앤다. `reddit.validate → _target.parse_target`(cli→시스템)은 대상 해석을 `reading/flows.py`의 준비 단계로 옮긴다(해석 실패는 요청 전 exit 2 유지). 이 표를 적용한 가상 그래프에서 위반 간선 0·순환 0이다.

**기존 파일 → 새 위치.** 위 트리의 `←` 주석이 이동표다. 삭제: `scripts/__init__.py`와 `reddit.py:8-14`의 루트 `__init__.py` 로드 부트스트랩(패키지가 실제로 있으므로 부트스트랩이 필요 없다), `tests/reddit/conftest.py`의 `reddit_skill` 합성(pyproject `pythonpath`로 대체, 공통 기반 6).

### 삭제 (죽은 코드·중복)

- 삭제 대상:
  - `errors.diagnostic`·`scrub`·`_SENSITIVE`. Aside stderr는 어디서도 출력하지 않는다.
  - `Transport.doctor`.
  - `build_request`의 `'info'`·`'doctor'` 표면. `about`·`rules`는 `build_request`를 거치게 해서 경로 결정이 한 곳에 있게 한다.
  - `CursorStore.save(pending=)`와 `_paths`(thread_path).
  - `OutFile.parent_count`·`.pending`·`.cursor`의 미사용분.
  - 쓰기만 하는 `first_seen_at`·`from_pointer_key`.
  - 페이스북 이식 주석.
- 중복 해소:
  - 캐시 정리 1벌: 스레드·커서 JSON과 크래시 `.tmp`, 보호·예약 규칙 포함.
  - 캐시 루트 1곳. Listing 검증 워커 1벌. 리디렉션 루프 1벌. JS 스니펫 1개. 캐시 크기 계산 1벌(doctor).
- 이 삭제와 해소로 테스트만 호출하던 내부 테스트도 사라진다.

### 계약 변경 (결함 수정 — 각각 재현 테스트 먼저)

| # | 변경 | 완료 판정 (CLI seam) |
|---|---|---|
| F1 (A1) | 정규화는 **모호하지 않은 강조 서식만** 벗긴다: 단어 경계에서 열고 닫히는 `**x**`, `*x*`, `~~x~~`(여는 기호 앞과 닫는 기호 뒤가 공백·문장부호·줄 끝). 인라인 코드 백틱 짝은 백틱만 벗기고 **안의 내용은 그대로** 둔다. `^`는 건드리지 않는다. 짝이 모호하면 원문을 남긴다(지우는 것보다 남기는 쪽이 안전) | CLI 텍스트 출력에서 원문 그대로 나와야 하는 것: `2 * 3 = 6; 2^10 = 1024; a ** b`, `a*b*c`, `x^(n+1)`, `\*literal\*`, `` `a**b` ``의 `a**b`. 벗겨져야 하는 것: `**bold** and ~~gone~~` → `bold and gone` |
| F2 (A2) | 표시 깊이 아래에만 미표시 댓글이 남으면 `stop_reason=depth_limited`로 멈춘다. 요약 줄에 `folded N below depth D`를 싣고, `more:`는 남은 것 중 최소 깊이를 `--depth`로 싣는다 | 4단 합성 스레드에서 `more:`를 그대로 따라가면 유한 단계 안에 `exhausted`에 도달하고, 무진전 반복(0건·0요청·같은 명령)이 없다 |
| F3 (A4) | 스레드 상태가 앵커별로 받아 둔 `context` 수를 기록한다. 더 큰 `--context`를 요청하면 1요청으로 다시 받아 병합한다 | 같은 댓글을 `--context 0` 다음 `--context 3`으로 부르면 조상 3개가 나오고, 두 번째 호출은 1요청이다 |
| F4 (A5) | 부분 실패도 텍스트 모드에서는 텍스트로 낸다. 순서는 오류 줄(message·fix) → 받은 결과(성공 경로와 같은 렌더러, 같은 `--chars`) → `more:`/`resume:`. `post` 본문의 전문 예외는 부분 실패에도 그대로다(게시물 본문만, 댓글은 `--chars`). `--json`일 때만 JSON 문서 하나다 | 2페이지째에 오류를 내는 픽스처(긴 본문 포함)에서 확인한다: 종료 코드 8, 첫 줄이 오류, 각 항목 본문 길이 ≤ `--chars`이고 잘림 신호 `text[n/N chars]`가 있음, `more:`가 있음, `{`로 시작하는 줄 없음. 같은 호출에 `--json`을 주면 파싱 가능한 문서 하나 |
| F5 (A6) | `schema`는 **내보내는 모양 그대로**를 설명한다: 결과 봉투, 명령별 레코드(기본 필드 + 조건부 표시 필드 `context`·`anchor`·`orphan`·`shown_earlier`·`window_excluded`·`replies_unshown` 등 — 어느 명령·조건에서 붙는지까지), `--out` 레코드 줄(`kind`별로 필드가 다름을 명시), `.state` | 테스트의 독립 검증기(schema 부분집합: type·properties·required·additionalProperties·`kind` 분기)로 확인: 모든 명령 `--json` 봉투와 레코드, 목록·스레드·앵커·창 제외 조건의 레코드, 혼합 `kind` `--out` 파일의 모든 줄이 통과한다. 레코드를 `kind`로 분기해 읽는 소비자 예(게시물엔 `depth`가 없다)가 테스트로 동작한다 |
| F6 (A7) | `about r/`는 공개 설명(`text`)과 사이드바(`sidebar`, 기존 `description` 필드명 교체)를 따로 표시한다. 각각 크기 신호를 붙인다 | 둘이 다른 픽스처에서 두 필드가 다 보이고 `--chars`가 각각에 적용된다 |
| F7 (A8) | 문맥 행에 댓글 행과 같은 짧은 핸들(I4)과 잘림 신호를 싣는다(조기 반환 경로 포함) | 이어읽기에서 부모가 캐시에 있는 `reply-to=t1_x`에는 같은 배치에 `t1_x`의 핸들을 가진 행이 있고, 그 핸들을 `comments`에 넣으면 그 댓글이 열린다. 부모가 없는 진짜 고아는 부모 행을 지어내지 않고 `orphan`으로 남는다 |
| F8 (E1) | 경로 안전 검사: 사용자가 준 경로의 **부모까지만** 한 번 실경로로 정규화해 `/tmp`처럼 시스템 링크 별칭을 허용한다. 그 정규 경로는 현행처럼 루트부터 디렉터리 디스크립터 기준 `O_NOFOLLOW` 순회로 연다(`_output.py:169-175`의 경합 안전성 유지). 마지막 요소가 링크·하드링크·비정규 파일이면 거부한다. 레코드·`.state`·잠금·임시 파일·캐시 모두 같은 원시 기능을 쓴다. fix는 원인을 이름으로 댄다 | 링크된 부모 디렉터리 아래 `--out`이 성공한다(`tmp_path/link → real`). `--out` 경로 자체가 링크면 exit 2이고 fix에 "symbolic link"가 있다. 정규화 뒤 조상 디렉터리를 링크로 바꿔치기해도 열기가 실패한다(seam 5: `reddit.files` 안전 열기) |
| F9 (A3·A9·E2) | `--out`: 레코드 NDJSON + `<out>.state`. **프로토콜:** 수집 파일마다 잠금 하나(`<out>.lock`, 비차단 — 다른 프로세스가 쓰는 중이면 exit 2). 커밋 = 레코드 추가 → flush·fsync → 새 `.state`(질의 문맥·계정·커밋 오프셋·레코드 수·마지막 fullname·진행 커서/스레드 키)를 임시 파일에 쓰고 fsync → 원자 교체. 재개할 때는 **먼저 검증하고** 그다음에 고친다: `.state`의 문맥·계정 일치, 오프셋 ≤ 파일 크기, 오프셋이 줄 경계, 오프셋 앞 마지막 줄의 fullname이 `.state`와 일치. 전부 맞을 때만 오프셋 뒤 꼬리를 자르고 이어 쓴다. `.state`가 없는데 레코드가 있거나 불일치하면 어느 파일도 건드리지 않고 exit 2. 스레드 수집은 스레드 캐시가 사라져도 `.state`의 스레드 상태로 복구된다(현행 `tests/reddit/test_cli.py:89` 계약 유지 — 단 `.state`는 스레드 상태를 매 커밋 **교체**하므로 누적되지 않는다). 이어읽기 명령은 `resume:` 한 줄(원 명령 그대로, `--out` 포함, `--after` 없음). 구 형식 파일(첫 줄이 `kind: header`)은 exit 2 + "use a new path" | 레코드 파일의 모든 줄이 F5 schema의 `--out` 레코드로 검증된다. 각 커밋 경계(레코드 쓰기 중, fsync 뒤·state 교체 전, 교체 뒤)에서 강제 종료한 뒤 같은 명령을 다시 돌리면 중복·누락 없이 완료된다. `.state` 불일치·부재는 두 파일을 바꾸지 않고 exit 2. 스레드 캐시를 지운 뒤 재개된다. 댓글 1,000개 합성 스레드 수집에서 `.state` 크기가 레코드 파일 크기 이하이고 커밋 수에 비례해 자라지 않는다. `resume:`를 따라가면 같은 파일에 이어진다 |

### 인터페이스·출력 변경 (성진 결정·밀도)

| # | 변경 | 완료 판정 |
|---|---|---|
| I1 | `REDDIT_ASIDE_ACCOUNT` 환경 변수(기본 `u0`, `u?\d+`만 허용, `u<N>`으로 정규화)를 `aside --account`에 넘긴다. 상태는 `<REDDIT_HOME>/<slot>/`로 나눈다. **조정 상태(예산·차단·식별 기록)와 읽기 캐시(스레드·커서)를 구분한다**: 슬롯 `u0`을 처음 쓸 때 레거시 루트의 `budget.json`·`identity.json`이 있으면 계정 잠금 아래에서 새 위치로 옮긴다 — 챌린지 차단과 만료 전 소진 상태가 살아남아야 한다(`_budget.py:67-68`, `:155`). 레거시 스레드·커서는 버린다(24시간 캐시). doctor가 슬롯을 보고하고, 로그인 오류의 fix가 이 변수를 이름으로 댄다 | 가짜 Aside가 받은 argv에 `--account u3`. 잘못된 값이면 exit 2. doctor 출력에 `slot=u3`. 레거시 루트에 챌린지 차단이 있으면 새 `u0` 첫 호출이 요청 없이 exit 5이고, 레거시에 만료 전 `remaining 0`이 있어도 exit 5 |
| I2 | ~~진입점의 Python < 3.11 검사 코드~~ → M10으로 대체: `cli.py` PEP 723 `requires-python = ">=3.11"`이 요구를 소유하고 `uv run`이 강제한다. POSIX 전용(`fcntl`)임을 top-level help 한 구절에 싣는다 | 공통 구조 테스트가 PEP 723 블록을 파싱해 `requires-python`을 확인 · `--help` epilog에 POSIX 구절 |
| I3 | 호출당 요청 상한에 걸리면 `stopped=request_cap`과 `N/N requests`를 내고, 기본 상한일 때는 다음 행동("pass --limit N to allow up to 60 requests")을 붙인다. `--limit` help는 이 규칙을 한 줄로 쓴다 | 가짜 Aside로 9요청이 필요한 확장에서 기본 호출이 `request_cap`이고 `more:`가 있다 |
| I4 | 댓글 핸들을 `https://www.reddit.com/comments/<post>/_/<comment>/`로 줄인다(CLI 인자로 그대로 쓸 수 있다). `reply-to`는 부모가 바로 앞 행이 아닐 때만 붙인다. 게시물 `[pN]`과 댓글 `[cN]`은 번호를 따로 센다 | 라이브 형태 픽스처의 `post --limit 8` 텍스트 바이트가 현행 대비 줄고, 모든 댓글 핸들이 `comments`에 넣었을 때 그 댓글을 연다 |
| I5 | 요약 줄 순서 고정: `<cmd> · <n> shown · stopped=<reason> · sort=<s> · budget <정수> left, resets in <s>s · requests=<n>`. `shown`과 `requests`는 **0이어도 항상** 싣는다(캐시 이어읽기의 `requests=0`은 핵심 신호). 스레드는 아래 정의의 커버리지를 붙이고, **선택적 진단 수치만** 0이면 뺀다(`unshown`, `pending`, `missing`, `orphans`, `folded`). doctor는 `shown/stopped`를 빼고 `slot · account · cache · block`을 낸다. "mixed capture times" 안내는 출력에 **서로 다른 관측 시각이 둘 이상** 있을 때만 낸다 — 초기 `fetched_at`과 확장 하나면 이미 둘이다 | 요약 줄에 `unshown=0`·`missing=0` 같은 진단 0값이 없고, 캐시 이어읽기에는 `requests=0`이 있다. `resets in`이 budget 바로 뒤에 온다. doctor 텍스트가 한 줄. 안내가 초기 조회만 있으면 없고, 초기 + 확장 1회면 있고, 그 뒤 캐시 이어읽기에서도 유지된다 |
| I6 | 폭·깊이를 고르는 싼 신호. **정의:** 스레드 요약의 `top-level S/P cached`는 이 스냅샷에 파싱된 최상위 댓글 P 중 지금까지 보인 S. 최상위에 대기 포인터가 있으면 `+K top-level not yet fetched`(포인터의 id 수 합, 서버 `count`와 다를 수 있음을 help가 말한다)를 붙인다. 댓글 행의 `+N replies`는 **캐시에 있는 미표시 후손 수**다. 그 아래 대기 포인터가 있으면 `+more unfetched`, id 없는 포인터(서브트리 요청 필요)면 `+branch unresolved`를 따로 표시한다. 정확해 보이는 수를 서버 총계로 오해하지 않게 라벨이 출처를 말한다 | 픽스처 셋에서 확인한다: 가지 하나에 캐시 미표시 답글 3개 → 그 행에만 `+3 replies`. 최상위 포인터 → `+K top-level not yet fetched`. id 없는 포인터 → `+branch unresolved`. 이미 보인 조상 문맥 행에는 수를 중복하지 않는다 |
| I7 | 명령별 `target` help를 그 명령이 받는 대상만으로 쓴다(`about`의 접두사 안내는 `about`에만) | `comments --help`에 "about"이 없다 |
| I8 | 검색 help가 over-18 결과는 `--nsfw` 없이 서버가 제외한다고 말한다(SKILL.md의 NSFW 문장 삭제에 대응) | help 문자열 |

**유지하는 결정:** `post` 본문은 전문을 싣는다(`text[full N chars]`로 크기 신호). 글을 연다는 명령의 목적이 본문이기 때문이다. 코덱스는 상한을 권했으나 따르지 않는다. 단계 5 시나리오에서 긴 글이 문제를 일으키면 다시 연다.

### SKILL.md 섹션 구조 (영어)

프론트매터:
- `name: reddit`
- `allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)`(공통 기반 3, 단계 2에서 바뀐다).
- `description`: 현행 유지. 발동 경계(레딧·URL·한국어 트리거, 다른 SNS·레딧 회사 뉴스·쓰기 동작 제외)가 잘 그어져 있다. 단계 5 시나리오에서 오발이 나오면 고친다.

| 섹션 | 남는 판단 | 근거 |
|---|---|---|
| `# Reddit through the user's own browser` | 호출 한 줄: `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" …`(프론트매터와 같은 형태). `$RD`·Codex용 절대경로 문장은 삭제(M3) | "Start with --help"는 뺀다. 두 팔 모두 스스로 help를 탔다 |
| `## One allowance serves every call` | 모든 호출·세션이 한 허용량을 나눈다. 새 대상을 여는 데는 요청이 들고, 열린 스레드를 이어 읽는 데는 거의 들지 않는다(글 하나가 스레드 대부분을 한 요청에 가져오므로). 그래서 열기 전에 고른다. 0이 되면 기다릴지는 사용자의 결정이다 | 수치 제거. 행동 근거는 약하다(B·C 요청 수 비슷) → 제거 시험 대상 1순위 |
| `## A result is a sample chosen by a community and an ordering` | 반응은 그 커뮤니티의 것이다(`r/popular`·`r/all`은 넓은 청중). 정렬을 밝힌다. best·top은 보상받은 자리를 보여 주고, controversial·new는 다른 질문에 답한다. 레딧의 댓글 총계는 삭제분을 포함하므로 읽은 양을 보고한다. 날짜 창은 유한한 목록을 늘리지 않는다 | T1·T2·T4에서 C만 귀속·정렬·커버리지. T2-C의 controversial |
| `## A thread is one snapshot read in batches` | 순서는 배치 안에서만 성립하는 스냅샷이다. 펼친 답글은 관측 시각이 다르다. 폭(최상위)과 깊이(가지)는 질문이 정한다 | 두 팔 모두 `--depth 0`으로 폭을 확보. 제거 시험으로 존폐 판정 |
| `## An account is a pseudonym` | 프로필은 활동을 해석하는 문맥이고, 활동은 관측 창 안의 것이다. 거주지·집·가족·직장 같은 신원 단서는 모아 제시하지 않는다(물으면 답한다). 가명 계정의 흩어진 단서를 모으면 동의하지 않은 사람이 식별되기 때문이다 | T3 두 팔 모두 신상 수집. 성진 결정 |
| `## Empty is not absent` | 검색은 일시적으로 빈 페이지를 준다. 두 번 비어도 부재의 증명이 아니다 | 이번 실험에서 빈 검색이 나오지 않아 미검증. 제거 시험에 빈 검색 과제(T6)를 넣는다 |
| `## Collected files hold other people's activity` | `--out` 파일과 캐시는 타인의 활동을 담는다. 레포 밖에 두고 작업 후 지운다. 모으면 식별이 가능해지기 때문이다 | T4-C만 작업 파일 삭제 |

빠지는 것과 그 소유자:
- 호스트 정규화·리디렉션 홉 예산: `transport` 동작. 모델이 행동할 일이 없다.
- 24시간 캐시: doctor 출력.
- "100 requests per ten minutes": 출력의 `budget N left, resets in`.
- "hundreds of comments": `post` help.
- `[c1]` 번호의 배치 한정: I4의 짧은 핸들이 대체한다.
- "Missing or closed differs from empty": 종료 코드 7·9와 그 fix.
- NSFW 문장: 검색 help(I8).
- 헤딩 "What has actually bitten".

### 테스트 seam (성진 합의)

1. **CLI 서브프로세스 + 가짜 Aside** (주 seam)
   - `REDDIT_ASIDE_BIN`이 가리키는 가짜 하나로 합친다(현행 `fake_cli.py`와 `fake_aside/aside`). 경로별 응답 시퀀스, 요청 로그, 지연, 비정상 종료를 지원한다.
   - 명령·출력·이어읽기·재개·오류·종료 코드·예산(프로세스 간 공유·429·챌린지·unblock)·`--out` 크래시 복구를 여기서 검증한다.
   - 기대값은 픽스처에서 손으로 도출한다. 현행 출력을 복사한 리터럴은 쓰지 않는다.
2. **대상 파서** `reddit.json_api.target.parse_target` (순수 seam): 입력 문자열 → `Target` 또는 exit 2 사유. 호스트 변형·인코딩 슬러그·공유 링크 등 표가 큰 경우.
3. **스레드 엔진** `reddit.reading.thread`의 `create_state`·`select_batch`·`next_expansion`·`merge_more`·`metadata` (순수 seam): 고아 재연결, 빈 포인터 서브트리, 정체, 형제 위치 삽입처럼 CLI 픽스처로 만들기 비싼 경우만.
4. **JS 스니펫** `node --test`: 경로·URL 검증, 조각 전송.
5. **안전 열기** `reddit.files`의 비공개 파일 열기 함수(입력: 경로·플래그 → fd 또는 exit 2 사유). 링크 파일, 하드링크, 링크된 부모 허용, 정규화 뒤 조상 바꿔치기처럼 CLI로 재현할 수 없는 보안 경계만 여기서 검증한다(성진 합의 2026-09-25).

실제 외부 경계(Aside·레딧)는 `-m live` 스위트와 대조·시나리오 실행이 따로 확인한다. 가짜와 일치하는 것만으로는 증명되지 않는다.

모든 seam 테스트는 pyproject `pythonpath`로 `from reddit.… import …`를 쓴다(공통 기반 6). 테스트 트리: `tests/__init__.py`(없으면 생성), `tests/test_skill_layout.py`(없으면 생성, 있으면 reddit 항목 추가), `tests/reddit/`(conftest의 `reddit_skill` 합성 삭제, CLI는 `[sys.executable, CLI]`, `test_cli.py:55,72,138`의 `shlex.split(...)[2:]`는 접두 단언 후 실행, js 경로 `json_api/snippets/fetch.js`, live는 CLI 서브프로세스 + Aside 래퍼).

## 작업 단계와 완료 판정

- 트래커: 첫 동작으로 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")` 후 `TaskCreate`로 아래 단계를 열고, description에 완료 판정을 그대로 적는다.
- 테스트를 쓰는 모든 단계는 `tdd` 스킬을 먼저 연다. seam은 위에서 합의됐다.
- 버그는 재현 테스트(레드) → 수정(그린) 순서로 간다.
- 각 단계 후 실행한다: `python3 -m pytest tests/reddit -q`(단계 2부터 `tests/test_skill_layout.py` 포함), `node --test tests/reddit/js/*.js`, `python3 tests/reddit/tools/check_fixtures_pii.py`, `uvx ruff check --config pyproject.toml .claude/skills/reddit/scripts tests/reddit`.

0. **기준선**
   - 이 파일을 정식 이름으로 옮긴다(아직 옮기지 않았다면).
   - 브랜치 `refactor/reddit-layered-structure`.
   - 현행 오프라인 통과 수(207)와 live 목록을 기록한다.
   - **완료:** 기준선 수치가 "구현 기록"에 있다.
1. **경계 테스트로 현행 행동 고정**
   - 합의된 seam에 "살아남아야 할 행동" 목록을 테스트로 쓴다.
     - 목록 이어읽기가 캐시를 먼저 비우고 서버 `after`로 잇는다.
     - 날짜 창의 `window_reached`와 `exhausted`를 구분한다.
     - 검색 0건은 1회 재시도하고, 예산이 없으면 8이다.
     - 개인 표면을 이어받기 전에 계정을 확인한다.
     - 스레드: 첫 배치, 캐시 0요청 이어읽기, morechildren 병합, 앵커 검증, 공유 링크 홉별 예산, 정체.
     - `about` 대상 접두사, 종료 코드 2~9, `schema` 오프라인 동작.
     - 예산: 두 프로세스가 한 허용량을 나눈다, 429 차단, 챌린지와 unblock.
     - `--out`: 재실행하면 이미 완료, 크래시 꼬리를 재생, 문맥이 다르면 거부.
     - 경로 안전: 링크 파일 거부, 하드링크 거부.
   - 현행 결함(F1~F9)은 여기서 고정하지 않는다. 해당 테스트는 단계 3·4의 레드다.
   - 이 단계는 기존 conftest의 `reddit_skill` 합성을 그대로 쓴다(공통 기반 7 전환 시점).
   - **완료:** 새 seam 테스트가 현행 코드에서 전부 통과한다. 목록의 각 항목이 테스트 이름으로 추적된다. 기존 내부 테스트도 통과한다.
2. **새 레이아웃 이행** (행동 불변 — 승인된 호출·help 변경 제외, M9)
   - 위 트리로 옮긴다(함수 이동 포함). 삭제·중복 해소를 하고, 테스트만 부르던 내부 테스트 파일은 지운다.
   - `cli.py`에 PEP 723 헤더, `more:`/`resume:` 접두를 공통 기반 3으로, 소비자(`tests/reddit/test_cli.py:55,72,138`, `live/test_live.py:34,65,68`)를 공통 기반 6으로 고친다. SKILL.md 프론트매터·호출문, `docs/usage.md:94`의 경로, JS 테스트 경로를 갱신한다.
   - 전환 시점 작업: `scripts/__init__.py`·파일 없는 부트스트랩·conftest `reddit_skill` 합성 삭제, `tests/__init__.py`, pyproject `pythonpath`, `tests/test_skill_layout.py` 생성 또는 reddit 항목 추가.
   - live를 CLI 서브프로세스 + Aside 래퍼 가드로 옮긴다(누적 30요청을 자식 프로세스 경계에서 센다, 래퍼는 커밋 안 하는 `.tmp/` 또는 `tests/reddit/live/`의 가드 스크립트).
   - **완료:**
     - 단계 1 테스트가 행동 기대값을 유지한 채 통과한다. 허용하는 수정은 모듈 seam 3곳(대상 파서·스레드 엔진·안전 열기)의 import 경로, CLI·자산 경로, 승인된 `more:`/`resume:` 접두 처리(공통 기반 6), 테스트 부트스트랩 제거뿐이다.
     - `python3 -m pytest tests/test_skill_layout.py`가 통과한다(최상위 이름 둘·방향·sys.path·PEP 723·allowed-tools).
     - 하위 패키지의 `__init__.py`를 빼면 `_`로 시작하는 모듈이 없다.
     - `more:`/`resume:` 접두 = allowed-tools 형태 테스트가 통과한다.
     - 이동성(공통 기반 6): 한국어·공백 경로와 `$`·따옴표 경로 사본에서 무관한 cwd로 `uv run` `--help`·`schema`·가짜 Aside 목록 1회가 동작하고, 출력된 `more:`가 셸에서 그대로 실행된다.
     - 런타임 줄 수가 줄었다(수치 기록).
   - PR①: `refactor: reddit을 cli.py와 패키지 하나로 옮긴다`. 코덱스 리뷰 후 머지.
3. **결함 수정** F1~F8
   - 브랜치 `fix/reddit-continuation-contracts`. 항목마다 재현 테스트가 현행에서 실패하는 것을 확인한 뒤 고친다.
   - **완료:** F1~F8의 완료 판정이 테스트로 전부 통과한다.
   - PR②: `fix: reddit 이어읽기·표시 계약의 결함을 바로잡는다`.
4. **인터페이스·출력 재설계** F9, I1~I8
   - 브랜치 `feat/reddit-output-density`.
   - **완료:** 위 표의 판정이 전부 테스트로 통과한다. 라이브 형태 픽스처 기준 `post --limit 8` 텍스트 바이트 현행 대비 감소율을 기록한다.
   - PR③은 단계 5와 함께 낸다.
5. **SKILL.md 재작성 + 제거 시험 + 시나리오**
   - 위 섹션 구조로 쓴다.
   - 제거 시험: 이번 세션의 대조 하네스(스크래치에 스킬 `scripts/`만 복사하고 순차 실행; 형태는 "장부 › 대조 실험"과 같다. 주입하는 CLI 경로 한 줄은 `uv run "<사본>/scripts/cli.py"` — 공통 기반 8)로 팔을 돌린다.
     - 예산 파일은 모든 실행이 공유한다. 실행 사이에는 **읽기 캐시(스레드·커서)만 지운다.**
     - 이번 세션처럼 실행마다 `REDDIT_HOME`을 새로 만들면 챌린지 차단이 실행 사이에 전달되지 않는다.
     - 30요청 live 가드는 쓰지 않는다. 제거 시험은 30요청을 넘고, 계정 보호는 CLI의 예산·차단이 한다.
     - 차단이나 소진으로 멈춘 실행은 "미검증"으로 기록하고 재시도하지 않는다.
     - 팔: FULL, 섹션마다 minus-X 6개, B(본문 없음).
     - 과제: T1~T4(이번과 같은 문장) + T5 "이 댓글의 논쟁을 끝까지 따라가 줘"(깊은 가지, `depth_limited` 경로) + T6 "레딧에서 <드문 주제> 얘기 있어?"(빈 검색).
     - 팔×과제는 섹션이 관여하는 과제만 돌리고, 과제당 2회.
   - 판정 기준은 실행 전에 적는다: 귀속, 정렬 명시, 커버리지 수치, 가명·신상 비수집, 빈 검색 해석, 파일 정리, 요청 수.
   - 이어서 Claude 시나리오: 스크래치 프로젝트에 스킬을 링크해 발견되게 하고, `claude -p --model claude-opus-5-5 --permission-mode acceptEdits --allowedTools Bash Read Skill`로 돌린다.
     - 발동: "레딧에서 …", 맨 reddit/redd.it URL.
     - 오발: Threads URL, "레딧 회사 IPO 뉴스", "레딧에 댓글 달아줘".
   - **완료:**
     - 남은 모든 섹션이 "빼면 적어도 한 과제의 행동이 나빠진다"는 근거를 갖고, 근거 없는 섹션은 삭제·병합됐다. 결과표가 "구현 기록"에 있다.
     - **예외:** 신원 단서 비수집 문장(`## An account is a pseudonym`)은 성진의 가치 결정이라 제거 시험의 대상이 아니다. 시험은 그 적용만 본다: T3에서 거주지·집 같은 단서를 모아 제시하지 않고, "이 사람 어디 살아?"라고 직접 물으면 답한다.
     - 시나리오가 전부 기대대로다.
     - 성진이 SKILL.md 전체 문안을 승인했다.
6. **라이브·리뷰·문서·전달**
   - 라이브: `tests/reddit/live`를 새 출력(`depth_limited`, `resume:`, `.state`, 짧은 핸들)에 맞춘다. 30요청 가드는 단계 2의 Aside 래퍼로 유지한다. `python3 -m pytest -m live tests/reddit/live -q`.
   - 코덱스 리뷰(`gpt-6-astra` medium, `danger-full-access`)
     - 네트워크가 필요하다: 스킬 시나리오는 네트워크 샌드박스가 필요하다는 기억에 따른다. 저장소 쓰기는 금지한다고 지시한다.
     - **닫힌 술어**로 묻는다: "아래 해소 행렬의 '수정' 항목이 재현되지 않고 F·I 완료 판정 테스트가 통과함을 실행으로 확인하라. 그리고 일반 단일 세션에서 도달 가능한 새 결함만 보고하라. 행렬의 '수용한 예외'와 '검증 한계'는 결함으로 세지 않는다."
     - 도달 가능한 결함이 0이 될 때까지 같은 스레드에서 `resume`한다.
     - 네 성질 기준의 SKILL.md 리뷰는 따로 한 번 받고, 전부 받아들이지 않고 가늠한다.
   - 문서:
     - README 표 문구는 필요하면만 고친다.
     - `docs/usage.md:113`의 구현 기록 링크에 이 계획 파일을 추가한다.
     - CONTRIBUTING의 reddit 명령(테스트·ruff 경로)은 불변이라 그대로다. 진입점 경로 문장은 단계 2에서 이미 고쳤다.
   - `claude plugin validate --strict .claude/skills`가 exit 0인지 본다.
   - PR③: `feat: reddit 출력 밀도·수집 형식·SKILL.md 재설계`. `gh pr merge --squash`.
   - 머지 직후 `Graphify` 스킬로 그래프를 리빌드하고 main에 직접 커밋한다.
   - **완료:**
     - 라이브 전부 통과.
     - 코덱스 도달 가능 결함 0.
     - validate exit 0.
     - 세 PR 머지.
     - 그래프 갱신.
     - 이 파일 끝에 "구현 기록"(계획과 달라진 결정, 실측 수치, 제거 시험표, 남긴 한계 `grep -rn "성진:"`).

## 해소 행렬 (최종 리뷰의 기준)

| 발견 | 처리 | 근거 |
|---|---|---|
| A1 | 수정 F1 | |
| A2 | 수정 F2 | |
| A3 | 수정 F9(`resume:`) | |
| A4 | 수정 F3 | |
| A5 | 수정 F4. **수용한 예외:** `post` 본문 전문 | 글을 여는 명령의 목적이 본문이고, `text[full N chars]`가 크기 신호다 |
| A6 | 수정 F5 | |
| A7 | 수정 F6 | |
| A8 | 수정 F7(짧은 핸들 포함) | |
| A9 | 수정 F9 | |
| A10 | 수정: 삭제·중복 해소(단계 2) | |
| A11 | 수정 I1, I2는 M10(PEP 723 `requires-python`)으로 대체. **수용한 예외:** Windows 미지원(POSIX 선언만) | |
| A12 | 수정: SKILL.md 재작성 + I8. **검증 한계:** 서버의 over-18 필터 동작 | 단계 6 라이브에서 1회 확인 |
| E1 | 수정 F8 | |
| E2 | 수정 F5·F9 | |
| 밀도(라이브 관찰) | 수정 I4·I5·I6 | |
| 공유 링크 `/s/` 실표본 | **검증 한계** | 표본 없음, 합성 테스트만 |

## 폐기하지 않는 결정

- 읽기 전용(GET만), 메시지함 제외, 표준 라이브러리만 사용, 한 요청 = 한 `aside repl` 프로세스(`# 성진:` 주석 유지).
- 예산 계약:
  - 잠금 안에서 예약하고 헤더를 관측한다.
  - 0이면 요청 없이 exit 5.
  - 429와 js_challenge 표식에만 차단을 건다.
  - 챌린지 해제는 `doctor --unblock`으로만 한다.
- 스레드 상태 계약: fullname 노드 맵, 형제 위치 삽입, `requested`/`received`/`missing`, 고아 보관·재연결, 정체 판정, 24시간·200MB 캐시.
- 식별자 계약: 로컬 정규화를 우선하고, 공유 링크만 홉별 예산으로 해석한다.
- 종료 코드 체계(0·2~9)와 오류 JSON `{ok, error, message, fix}`.
- 7과 9를 구분한다: 7은 다른 창이나 정렬로 다시 물을 가치가 있고, 9는 없다.
- 픽스처 PII 검사와 live 30요청 가드.

## 하지 않는 것

- 쓰기 동작, 메시지함, 멀티레딧, 위키 본문, 미디어 다운로드.
- 요청당 프로세스 스폰 최적화(측정된 병목 없음).
- Windows 지원: POSIX 전용을 선언만 한다.
- `references/`.
- 스레드 배치의 기본 순서 변경: 깊이 우선을 유지하고, 폭 판단은 I5·I6의 신호로 모델에게 맡긴다.

## 검증하지 않은 것 · 남은 위험

- 대조 실험은 과제당 1회였다. 방향은 보였지만 빈도는 모른다 → 제거 시험은 과제당 2회.
- "search excludes over-18 unless `--nsfw`"는 코드상 요청 인자로만 확인했고, 서버 동작은 미실측 → 단계 6 라이브에서 1회 확인한 뒤 I8 문구를 확정한다.
- `/r/<sub>/s/<id>` 실제 공유 링크 표본은 아직 없다(원 계획 A3) → 계속 합성 테스트로만 검증한다.
- F9 파일 형식 변경으로 구 `--out` 파일은 재개할 수 없다(명확한 오류로 알린다).
- 캐시 루트를 슬롯별로 나누면서 기존 `~/.cache/reddit-skill/*` 캐시는 버려진다(24시간 캐시이고 마이그레이션은 하지 않는다). doctor가 옛 루트 파일을 보고할지는 구현 중에 판단한다.

## 계획 검증 기록

코덱스 계획 검토(`gpt-6-astra` medium, read-only, 감사와 같은 스레드, run `20260925-145347-reddit-plan-review-1160`)에서 14건이 나왔다. 13건은 그대로, 1건은 부분 반영했다.

| 분류 | 건수 | 내용 |
|---|---|---|
| 회귀 | 4 | F8 경합 안전 순회, F9 커밋·복구 프로토콜, 슬롯 이관 시 챌린지 차단 상실, 제거 시험의 예산 격리 |
| 누락 | 4 | F1 모호 사례, F4 밀도 판정, F5·F9 검증 범위, F7 핸들 |
| 차단 | 5 | I5 `requests=0` 모순, 혼합 시각 조건, 루트 `__init__.py` 누락(→ 성진 요청으로 파일 없는 부트스트랩으로 해소, 2026-09-26 M1로 대체: 실제 패키지 `scripts/reddit/`), 제거 시험이 고정 규칙을 지울 수 있음, 최종 리뷰 술어가 수용 예외와 모순 |
| 프레임 | 1 | I5·I6 수치의 출처 라벨 |

**부분 반영(1건):** 제거 시험을 live 가드 래퍼에 태우라는 제안은 따르지 않았다. 30요청 상한이 시험 규모와 맞지 않고, 계정 보호는 공유 예산 파일의 차단이 한다. 예산 공유는 반영했다.

코덱스 판정은 "지적 사항을 고치면 구현 가능"이다.
