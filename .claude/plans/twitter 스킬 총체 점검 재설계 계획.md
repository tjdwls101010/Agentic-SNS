# twitter 스킬 총체 점검과 재설계 계획

> **첫 동작**: 승인 직후 이 파일을 `.claude/plans/twitter 스킬 총체 점검 재설계 계획.md`로 `mv`한다(성진 결정 3). 구현 세션은 시작하자마자 아래 "작업 단계"의 단계들을 `TaskCreate`로 열고(각 `description`에 완료 판정을 그대로), 단계마다 `TaskUpdate`로 옮긴다.
> 2026-09-26 개정: skill-maker `## Code the skill bundles`에 맞춰 트리·호출 형태·테스트 기계를 `## 공통 구조 기반`으로 바꿨다(`SNS 스킬 4종 계획 구조 관례 개정 계획.md`). 결함 목록과 다른 결정은 그대로다.

## Context

`.claude/skills/twitter`는 Claude가 성진의 로그인된 Aside 브라우저로 X를 전문 리서처처럼 읽게 하는 스킬이다 — 계정이 잠기지 않게 요청을 아끼고, 조용히 틀리지 않고(리포스트 작성자, Top≠시간순, 답글 일부만 보임), 컨텍스트를 적게 쓴다. 이번 세션은 skill-maker의 네 프레임(principle over rail · interface over document · For the model, not the maintainer · dense)으로 총체 점검했다.

**결론: 재작성은 필요 없다. 재배치 + 인터페이스 수리다.**
- 동작은 건강하다: 테스트 160 passed, live 4회(doctor·user·search(서명 표면)·post) exit 0, ruff·node·PII·`claude plugin validate --strict .claude/skills` 모두 통과. 계정 보호·서명 재현·페이지 커밋 회복은 실측으로 얻은 지식이라 다시 쓰면 재발견 비용만 든다(코덱스 독립 감사도 같은 결론).
- 결함은 두 곳에 몰려 있다. ① **구조**: 명령 하나의 정의가 5~6곳(`twitter.py` 파서 if 사슬·`validate`, `_cmds_browse.operation`, `_browse` 특수 분기·`more_command`, `_render` 분기)에 흩어져 있어 표면 하나를 바꾸면 한 곳을 반드시 빠뜨리고, help가 모든 명령에 같은 문구를 붙인다. 합성 패키지 부트스트랩(`importlib.spec_from_file_location('twitter_skill')`)이 CLI와 `conftest.py`에 복제돼 있다(새 레이아웃은 실제 패키지 `scripts/twitter/`로 부트스트랩 자체를 없앤다). ② **인터페이스**: 인자 오류에 "doctor를 돌려라"는 fix, 효과 없는 `--type media --sort`, 48KB schema, 경고·오류 메시지를 숨기는 렌더, `more:`가 `--chars`/`--json`을 잃음, 영구 누적되는 연속 파일, 뷰어를 대조하지 않는 doctor, 기존 파일에 0600을 보장하지 않는 `--out`.

**의도한 결과**: 표면 하나의 변경이 선언 한 곳에서 끝나고, X가 바꾸는 층(통신)·응답 해석·수집 정책·모델이 보는 출력이 각자 한 폴더에서 바뀌며, 모델이 읽는 모든 help·fix·schema·SKILL.md 문장이 판단을 바꾼다.

## 장부

### 사실 (2026-09-25 실측)
- 구성: `SKILL.md` 40줄, `scripts/` 평면 `_*.py` 20개(≈2,500줄) + `twitter.py` + `registry.json`(33 ops, 39 features) + `browser/*.js` 4개. 표준 라이브러리만. 커밋 1개(`544c1c7`).
- 테스트: `python3 -m pytest tests/twitter -q` → 160 passed, 3 deselected(live), 31.9s. 가짜 Aside(`TWITTER_ASIDE_BIN`)+시나리오 스위치(`TWITTER_FAKE_SCENARIO`=429·empty…)+호출 로그(`TWITTER_FAKE_LOG`)로 CLI 프로세스 seam이 이미 있다(`tests/twitter/test_cli.py:57-76`). 14개 파일은 내부 모듈 import.
- live(요청 8회): `doctor` → `registry age 19.847080325426326 days · txid age 1.35e-05 days`. `user @AnthropicAI --limit 3` 헤더 ≈230자(`fetched 0.28MB`·버킷 2개·`requests`·`account window`), bio의 t.co 미전개, `⏎  ⏎`, `likes=0 …`, `more: … --tab posts --limit 3 --after 37`(기본값 메아리). `post … --limit 4` → `replies: 4 direct shown of 1460 reported · hidden branches 1`. `--json` 트윗 1개 ≈2.7KB(원시 `entities`·작성자 전체 카드).
- `schema` 텍스트 48,195B/1,773줄, `--json` 25,803B(`results[0]`와 `schema.$defs` 중복).
- 연속 핸들 `~/.cache/twitter-skill/cursors/N.json` 36개 누적, 정리 경로 없음, 번호 재사용 가능.
- `registry.json`의 `captured_at`·`txid_ingredients_2026_09_05`·op별 `verified`(계정 핸들 포함)·`rate`·`kind`는 코드·테스트 어디서도 읽지 않는다(grep 0).
- 외부 의존: `SKILL.md` `allowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/twitter.py" *)`, `README.md`·`docs/usage.md`가 `scripts/twitter.py` 인용, `CONTRIBUTING.md:25-28`·`.github/workflows/test.yml:27-29`가 `tests/twitter`·`tests/twitter/js/*.js`·`tests/twitter/tools/check_fixtures_pii.py`·`ruff … .claude/skills/twitter/scripts tests/twitter` 실행. JS 테스트가 `scripts/browser/` 경로 하드코딩. `.github/pull_request_template.md` 없음 → PR 본문은 무엇을 바꿨나/왜/영향/검증.
- ruff는 PATH에 없다 → `.claude/skills/finviz/.venv/bin/ruff check --config pyproject.toml …`로 실행(통과 확인).
- 기존 `# 성진:` 주석 2개: `_blocked.py:17`(단일 계정 락), `_budget.py:28`(1초·20% 감속 추정).

### 코덱스 감사 (`gpt-6-astra` medium, read-only, run `20260925-143210-twitter-audit-6510`)
1. 회복 안내 오류: 인자 오류 다수가 기본 fix "Run doctor…"(`_errors.py:19`, `twitter.py:108-130`); 서명 오류는 명령 무관하게 `--tab replies-only`(`_txid.py:38`); 타임아웃은 효과 없는 "요청 크기 줄이기"(`_aside.py:30`).
2. 연속 상태 무기한 누적·번호 재사용(`_output.py:20-44`), SKILL.md는 삭제를 지시하지만 위치·수단이 없음.
3. `doctor`가 캐시 viewer와 새 viewer를 대조 안 함(`_cmds_meta.py:19-24`), 차단 중엔 진단 불가, `bundled days`·`None days`.
4. `search --type media --sort`가 같은 요청을 보내면서 헤더엔 sort 표시(`_cmds_browse.py:23`, `_render.py:99`).
5. schema: 봉투·stop_reason·오류·연속·NDJSON 페이지 레코드 미기술, 동적 필드(`role`·`depth`·`module`·`index_in_module`·`community_url`) 누락, trend `id`와 "missing is null" 설명 부정확.
6. help 16개 전수: 공용 문구가 무관 명령에 붙음, `trends`·place 카드는 `--chars` 무시, `list/community --tab about`은 `--after`를 제시 후 거절, `trends`는 페이지 나머지를 볼 수단 없음, argparse 기본 포매터가 문장을 줄바꿈.
7. 렌더: 경고는 개수만, 오류는 메시지 없이 분류+fix만, `more:`가 `--chars`·`--json` 유실.
8. `--out` 기존 파일은 0600 미적용.
9. `registry.json` 기록용 필드. 10. 내부 import 테스트 14개.
- 권고 구조의 요지(변경 이유별 묶음, 정상 패키지, `twitter.py`·`browser/`·`registry.json` 제자리)는 채택. 차이: 코덱스는 3묶음, 성진은 4묶음 결정.

### 성진 결정
1. 형제 스킬과 닮게 만드는 것은 목표가 아니다. 이 스킬이 제 목적에 맞게 선다. (→ M4로 좁힘: 내용에만 적용)
2. 목적 이해 확인(위 Context 첫 문단).
3. 계획 파일명 `twitter 스킬 총체 점검 재설계 계획.md`, 승인 직후 mv.
4. 범위: **재배치 + 인터페이스 수리**(전면 재작성 아님).
5. 명령 정의: **명령마다 선언 하나**, 파서·검증·operation·more·렌더가 모두 이것을 읽는다. (M11: 선언은 `cli.py`, operation·prepare·fetch는 `browse/operations.py`에 구현하고 선언이 참조)
6. 이식성: **Claude Code 전용**(M3과 같음). `${CLAUDE_SKILL_DIR}` 외 경로 해석 규칙은 두지 않는다. 표준 라이브러리만, Unix(fcntl) 전제, 호출은 `uv run` + PEP 723.
7. ~~폴더: **4묶음** `protocol/`·`reading/`·`collection/`·`output/`, 정상 패키지 `twitter_skill/`~~ → M1·M12·M13으로 대체: 패키지 `twitter/`, X 소유 코드는 시스템 폴더 `graphql/` 하나에 모으고 그 안에서 `protocol/`(선)·`responses/`(응답 모양)로 결정 7의 구분을 유지, 수집 정책은 `browse/`, 출력은 `output/`.
8. 테스트 seam: **S1 CLI 프로세스+가짜 Aside(주)**, S2 서명 알고리즘, S3 예산 예약(clock·sleep 주입), S4 브라우저 스니펫(node), S5 live(옵트인). 나머지 내부 import 테스트는 S1로 옮기고 지운다.
9. PR 두 개: ① 이동·선언(동작 불변) → 머지 → ② 인터페이스·문서.
10. 레포 문서(README·usage.md의 Codex 안내)는 건드리지 않는다. 단 **거짓이 되는 twitter 문장**만 고친다 — 진입점 경로가 거짓이 되는 문장(`README.md:10,69`, `docs/usage.md:10-12,93,102-103,133`)은 PR ① 단계 2에서, 동작 설명은 PR ②에서.
11. 텍스트 출력: 제안안(아래 "렌더") 채택. 0 카운트는 null과 구분하려고 유지.
12. 레코드: 원시 `entities` 제거 + `mentions` 추출, 작성자 카드는 유지.
13. 연속: **24시간 만료 + 무작위 핸들**.
14. 모델 시나리오: **가짜 Aside fixture 위에서** + live 2~3건. 실행 모델(행동을 재는 대상) Claude Opus(`claude-opus-5-5`).
15. SKILL.md: 아래 6섹션 구조(영어, 한 문단=한 줄). 전체 문안은 제거 시험 후 성진 승인.
16. references/: **두지 않는다**.
17. schema: **짧은 목차 + 주제별 상세**.
18. live 상한: **세션 전체 150요청, 10분에 50 이하**.
19. ~~진입점·폴더: **`scripts/twitter.py` + `scripts/twitter_skill/` 래퍼 유지**~~ → M1로 대체(2026-09-26): `scripts/cli.py` + `scripts/twitter/`. 아래 근거 중 sys.modules 충돌은 고유 패키지 이름 `twitter`가 같은 방식으로 막고(테스트 폴더와의 이름 충돌은 `tests/__init__.py`로 해소, 공통 기반 6), 문서가 거짓이 되는 문제는 이행 PR이 문서를 함께 고쳐 해소한다. 옛 기록: 근거: twitter는 `twitter` 라이브러리를 import하지 않아 개명이 막을 가림이 없고, 개명하면 allowed-tools·README·usage.md·테스트 경로가 함께 거짓이 된다. `tests/sec/conftest.py:4`·`tests/facebook/conftest.py:8`이 스킬 `Scripts/`를 `sys.path`에 넣고 sec에 최상위 `output.py`·`store.py`·`transport.py`가 있어, 래퍼 없이 `output/`·`errors.py`를 최상위에 두면 한 pytest 프로세스에서 `sys.modules` 충돌 — 네임스페이스 한 겹이 이를 구조적으로 막는다.

### Claude 판단(묻지 않고 정함, 근거)
- `entities`를 빼면 렌더가 t.co를 펼칠 근거가 사라지므로 **정규화에서 `text`의 t.co를 `expanded_url`로 치환하고 미디어 t.co는 제거**한다. 모델은 t.co가 필요 없다. 옛 레코드와 섞이지 않게 `--out` 헤더와 연속 상태 파일에 `format: 2`를 넣어 옛 형식을 거절한다(fix: 새 파일 / 처음부터).
- `--out` 기존 파일이 group/other 권한을 가지면 조용히 chmod하지 않고 거절한다(fix에 `chmod 600` 또는 새 경로). 사용자 파일 권한을 몰래 바꾸지 않는다.
- `--type media`의 `--sort`는 거절한다(`--type users`와 같은 방식).
- `trends`: `--chars`를 설명에 적용하고, 이미 받은 페이지의 나머지는 연속 핸들(요청 0)로 연다 — "캐시된 뒤띠는 공짜" 원칙과 일치.
- help 포매터는 문장을 접지 않는다 — `RawDescriptionHelpFormatter`는 인자 help를 여전히 접으므로, 폭을 사실상 무제한으로 준 `argparse.HelpFormatter` 하위 클래스(`width=10_000`)를 쓴다. 성진 줄바꿈 규칙. 실행 출력으로 확인.
- `doctor`: 쿠키를 강제로 다시 읽어 viewer를 대조하고(바뀌면 기존 세션 갱신 경로와 같은 무효화), 차단 중이면 요청 없이 차단 상태를 먼저 보고한다. 나이는 반올림(`registry refreshed 20d ago`/`bundled`). "나이가 많으니 refresh"라는 권고는 넣지 않는다 — refresh의 근거는 `operation_rotated` 오류이지 나이가 아니다.
- `doctor` 실행 로직은 viewer 대조만 `graphql/protocol/session.py`, 조립(Transport 생성·`--unblock`)은 `browse/maintenance.py`(session → transport → session 순환 방지, 2026-09-26), 요약 문장만 `output/doctor.py`.
- `_models.py`+`_entities.py`는 한 파일 `graphql/responses/records.py`로 합친다(둘 다 레코드 정의·빌더, 합계 ≈210줄). `timestamp`만 `dates.py`(공용)로.

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

### 미결
- 없음. 구현 중 새 판단이 필요하면 AskUserQuestion으로 묻는다.

### 코덱스 계획 비판 반영 (run `20260925-145240-twitter-plan-review-777f`, 18건)
17건 수용, 1건 부분 기각. 수용: ① PR ①은 순수 재배치 — 새 의미는 전부 PR ② 슬라이스에서 ② 골든 정규화 계약 명시 ④ `args.command` 전면 grep 대신 "명령명 기반 분기·검증" 금지(저장·표시는 허용) ⑤ `more:`는 `--limit`을 항상 유지(명시 limit이면 요청 상한 40, 아니면 10 — `_browse.py:82`) ⑥ 연속 상태도 형식 버전, 옛 숫자 핸들은 거절 ⑦ 핸들 문법을 파일 접근 전에 검증 ⑧ 만료·삭제·재발급 방지를 분리 기술 ⑨ `mentions` 의미 확정 ⑩ 스레드 완결성·trend 제외 수·viewer 변경을 헤더에 유지 ⑪ 차단 중 doctor와 `--unblock` 결과 계약 ⑫ schema 주제 범위와 무인자 `--json` ⑬ 시나리오 하네스의 스킬 주입·셸 경계 ⑭ 후보 SKILL.md 먼저, 역할 명칭 정리, 문단↔시나리오 대응표 ⑮ live 상한을 가드가 사전 강제 ⑯ live는 구조 단언, 전후 비교는 결정적 골든으로 ⑰ drift fix 과장 제거, 배지·핸들 전용 조회는 인터페이스로 ⑱ 단계별 판정 보강·승인 후 변경 시 재승인·PR ① 후 그래프 리빌드. 부분 기각 ③: `tests/twitter/fixtures/surfaces.ndjson`는 git 추적 파일로 존재한다(`git ls-files`) — 다만 어떤 테스트도 읽지 않으므로 "유지(미사용 원천 캡처)"로 표기. `partial` 시나리오는 없으므로 "첫 페이지 성공 후 429"(`test_cli.py:153-155`)로 바꿈.

## 네 프레임이 이번에 결정하는 것

| 프레임 | 이번 변경 |
|---|---|
| principle over rail | SKILL.md는 판단의 이유만(버킷 공유·필터 위치·행의 의미). "Three surfaces" 같은 목록 레일은 "서명 표면은 따로 깨지고, 대체 표면은 질문을 바꾼다"는 원리로 바꾼다. 모든 fix가 "doctor"로 향하던 레일을 경우별 이유 있는 fix로 바꾼다 |
| interface over document | 명령별 help가 자기 인자만 정확히 말한다(선언에서 생성). 금지 조합은 실행 전 거절+정확한 fix. 연속 수명은 자동 만료로 코드가 소유(SKILL.md 삭제 지시 제거). schema가 봉투·stop_reason·NDJSON·동적 필드를 소유. 효과 없는 옵션(`media --sort`)은 닫힌 선택에서 뺀다 |
| for the model, not the maintainer | "What has actually bitten" 섹션과 파서 세부(빈 focal·둘째 페이지 focal) 제거. `registry.json`의 `verified`·`rate`·`kind`·`captured_at`·`txid_ingredients_*` 제거 → 경위는 커밋 본문 |
| dense | 헤더 ≈230→≈100자, 기본값 메아리 제거, `⏎  ⏎`→`⏎⏎`, JSON 레코드에서 원시 entities 제거, schema 48KB→목차 수백 바이트 + 주제별 |

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
.claude/skills/twitter/
├── SKILL.md                       # 6섹션, 모든 경로가 필요로 하는 판단만 (references/ 없음)
└── scripts/
    ├── cli.py                     # ← twitter.py + 계획의 surfaces.py 표면 + cli.py: PEP 723 · 명령 13개 + meta 3개의 Surface 선언(유일한 진실: 인자·명령별 help·금지 조합+fix·도메인 함수 참조·행 종류·연속 가능·personal) → argparse(비접힘 포매터, root epilog 종료 코드표) · 공통 검증 · 디스패치(schema는 output으로 직접) · emit(← _output.emit) · exit 코드 · 문맥(질의 신원) 계산(← _browse.context_for) · more: 조립(← _browse.more_command)
    └── twitter/                   # 유일한 패키지 (__init__.py 비어 있음)
        ├── errors.py              # 공용 ← _errors: TwitterError·코드→분류·scrub(비밀 제거)
        ├── dates.py               # 공용 ← _entities.timestamp: 날짜 파싱(사이트 무관 순수 변환)
        ├── aside/                 # 시스템: Aside CLI
        │   └── repl.py            # ← _aside: aside repl 서브프로세스·봉투 검증 (스니펫 소스를 받아 실행)
        ├── graphql/               # 시스템: X 웹 GraphQL (M12: 안에서 선과 응답 모양을 나눈다)
        │   ├── protocol/          # X가 선·서명·버킷을 바꾸면 여기만 바뀐다
        │   │   ├── session.py     # ← _session: ct0·viewer 캐시, viewer 대조(doctor가 호출)
        │   │   ├── registry.py    # ← _registry: 사양 로드·캐시 오버라이드(query_id·gated·features만)
        │   │   ├── registry.json  # 실행 사양만: bearer, features, operations{query_id, method, gated, root, vars, fieldToggles}
        │   │   ├── transport.py   # ← _transport: query·classify·재시도 한도. 스니펫을 읽어 aside에 넘긴다 (account 사용)
        │   │   ├── signature.py   # ← _txid: x-client-transaction-id 유도·생성 (S2, MIT 고지 유지)
        │   │   ├── refresh.py     # ← _bundles: 채굴→두 연산 재생 검증→게시
        │   │   └── snippets/      # ← browser/: cookie.js·page.js·graphql.js·bundles.js
        │   └── responses/         # X 응답 모양이 바뀌면 여기만 바뀐다
        │       ├── targets.py     # ← _target: 핸들·URL·ID 파싱
        │       ├── timeline.py    # ← _walk: instructions 워커(모듈·커서·광고 계수)
        │       ├── records.py     # ← _models + _entities(timestamp 제외): Tweet·User·Media·List·Community·Trend + 빌더(t.co 전개, mentions)
        │       ├── thread.py      # ← _thread: parent/focal/reply 역할·깊이·완결성 증거
        │       └── pages.py       # ← _browse.normalize_page: 원시 루트 → 레코드 행(행 종류는 선언이 지정)
        ├── account/               # 저장소: 계정 보호 상태
        │   ├── state.py           # ← _blocked: 캐시 경로(TWITTER_HOME)·원자적 쓰기·계정 락·영구 차단
        │   └── budget.py          # ← _budget: 예약·간격·관측 버킷 (S3)
        ├── continuation.py        # 저장소 ← _output.CursorStore: 무작위 핸들·24h 만료·컨텍스트 결속
        ├── export.py              # 저장소 ← _output.OutFile: --out NDJSON 잠금·헤더(format 2)·페이지 커밋·꼬리 회복·권한 검사
        ├── browse/                # 기능: 페이지·연속·내보내기 정책이 바뀌면 여기만 바뀐다
        │   ├── operations.py      # ← _cmds_browse.operation + 명령별 prepare·fetch: 선언이 참조하는 도메인 함수 (대상 해석 포함)
        │   ├── pagination.py      # ← _listing: collect(중복 제거·창·pending 꼬리·stop 판정)
        │   ├── run.py             # ← _browse.run: 선언을 받아 준비→fetch→collect→결과 조립. 핸들과 이어갈 인자를 돌려준다
        │   └── maintenance.py     # ← _cmds_meta(schema 제외): doctor·refresh 조립(Transport 생성·viewer 대조 호출·--unblock)
        └── output/                # 기능: 모델이 보는 모양이 바뀌면 여기만 바뀐다
            ├── render.py          # ← _render: 텍스트 렌더
            ├── schema.py          # ← _schema: 목차 + 주제(tweet·user·media·list·community·trend·envelope·export)
            └── doctor.py          # doctor·refresh 요약 문장
```

- **분류(구조 테스트 항목)**: 공용 `errors`·`dates` · 시스템 `aside`·`graphql` · 저장소 `account`·`continuation`·`export` · 기능 `browse`·`output`.
- 삭제: `scripts/__init__.py`, `twitter.py`(표면은 `cli.py`로), `twitter_skill/` 래퍼와 그 `__init__`의 자산 경로 상수(각 시스템 폴더가 `Path(__file__)`로 자기 자산을 찾는다), `_cmds_browse.py`·`_cmds_meta.py`(browse로 흡수), `tests/twitter/conftest.py`의 부트스트랩. 이동은 `git mv`로 이력 유지.
- **이동으로 풀리는 역방향**(2026-09-26 AST 조사): `_browse.run → context_for·more_command`(기능→cli)는 cli.py가 문맥(질의 신원)을 계산해 넘기고 viewer는 기능이 붙이며, 기능은 핸들을 돌려주고 cli.py가 `more:`를 조립하는 것으로 뒤집는다. `_cmds_meta.run → _schema.schema`(기능→기능)는 cli.py가 `schema`를 `output/schema.py`로 바로 디스패치해 없앤다. `twitter.validate → _target.parse`(cli→시스템)는 대상 해석을 `browse/operations.py`의 prepare로 옮긴다(해석 실패는 요청 전 exit 2 유지). `validate → _entities.timestamp`는 `dates.py`(공용)로 옮긴다. `_output.emit → _render`(저장소→기능)는 emit을 cli.py로 옮겨 없앤다. doctor를 `session.py`에 합치면 session → transport → session 순환이 생기므로(`_cmds_meta.py:4,12`, `_transport.py:95`) viewer 대조만 session에 두고 조립은 `browse/maintenance.py`에 둔다. 이 표를 적용한 가상 그래프에서 위반 간선 0·순환 0이다.

```
tests/
├── __init__.py                    # 빈 파일(공통 기반 6), 없으면 만든다
├── test_skill_layout.py           # 공통 구조 테스트(공통 기반 5), 없으면 만들고 있으면 twitter 항목만 추가
└── twitter/
    ├── conftest.py                # 부트스트랩 제거(pyproject pythonpath). 공용 fake_env·invoke 픽스처를 여기로 — CLI는 [sys.executable, CLI]
    ├── fake_aside/aside           # 유지 (시나리오 확장)
    ├── fake_data.py               # 유지 + 시나리오 추가(서명 거절·CSRF 353·viewer 변경·드리프트·청크 봉투·함정 fixture)
    ├── fixtures/{surfaces.ndjson, transaction.json}   # 유지 (surfaces.ndjson은 현재 어떤 테스트도 읽지 않는 원천 캡처 — 함정 fixture를 유도할 때 원천으로 쓴다)
    ├── test_cli.py                # S1: 명령별 help·인자 거절+fix·operation 매핑·exit 코드·more: 접두 = allowed-tools 형태
    ├── test_reading.py            # S1: 리포스트·인용·스레드 역할/깊이/완결성·place·trend 해석 (← test_models·test_thread·test_places·test_target)
    ├── test_collection.py         # S1: 페이지·창·pending 꼬리·연속 핸들 만료·--out 커밋/재개/권한 (← test_listing·test_output)
    ├── test_protocol.py           # S1: 분류(429·353·404빈본문·422·400 features)·재시도·viewer 변경·레지스트리 오버라이드·refresh·Aside 봉투
    ├── test_output.py             # S1: 텍스트 렌더·schema 목차/주제·doctor 요약 (← test_render)
    ├── test_signature.py          # S2 (`from twitter.graphql.protocol.signature import …`)
    ├── test_budget.py             # S3 (`from twitter.account.budget import …`)
    ├── test_declarations.py       # AST: cli.py 밖에 명령명으로 분기·검증하는 코드 0 (옛 일회성 판정을 커밋 테스트로)
    ├── js/{test_bundles.js, test_graphql.js}   # S4, 경로를 graphql/protocol/snippets로
    ├── live/{guard_aside.py, test_live.py}     # S5. guard_aside는 상한을 env로(TWITTER_LIVE_TOTAL·TWITTER_LIVE_WINDOW) 받아 누적·10분 창을 발송 전에 강제. more: 소비는 공통 기반 6
    ├── model/                     # 신규: fixture 위 모델 시나리오
    │   ├── scenarios.json         # 과제·함정·must/must_not·대응 SKILL.md 섹션
    │   └── run.py                 # 격리 디렉터리·가짜 Aside 환경으로 claude -p 실행, 결과 JSONL
    └── tools/{derive_fixture.py, check_fixtures_pii.py, golden.py}
```

## 명령 선언 설계 (`cli.py`의 `Surface`)

```python
@dataclass(frozen=True)
class Surface:
    name: str
    help: str                          # 명령 한 줄 설명 (명령별)
    args: tuple[Arg, ...]              # 위치 인자·옵션: 공용 생성자 + 명령별 help 문구
    rules: tuple[Rule, ...] = ()       # (조건, message, fix) — 실행 전 거절
    operation: Callable | None = None  # args → (op, variables)
    prepare: Callable | None = None    # userId 해석·community 카드 등 선행 요청
    fetch: Callable | None = None      # trends처럼 두 단계 요청이 필요한 표면
    rows: str = 'tweet'                # tweet|user|trend|place — pages.py와 render가 읽음
    continuable: Callable = always     # 연속 핸들 발급 여부(args별: about 탭·batch 제외)
    personal: bool = False             # home·me: viewer 쿠키 재확인
    runner: Callable | None = None     # doctor·refresh·schema
```
- 공용 인자 생성자: `LIMIT(noun, default)`, `CHARS(what)`, `OUT`, `AFTER`, `DATES(when=…)`, `TAB(choices, default)`, `SORT(choices, default)` 등 — **문구의 명사·기본값·적용 범위는 명령이 채운다**(help가 틀리던 원인 제거).
- 선언은 `scripts/cli.py`에 있고(M11), `operation`·`prepare`·`fetch`·`runner`는 `browse/`의 함수를 참조한다(`schema` runner는 `output/schema.py`). `cli.py`는 선언만 순회해 파서를 만들고, 기본값 채우기·rules 검사·dispatch를 한다. 대상(target) 파싱은 `prepare`가 `graphql/responses/targets.py`로 한다(요청 전 exit 2 유지). `more:` 명령은 cli.py가 선언의 인자 목록과 기능이 돌려준 핸들로 재구성한다. **PR ①에서는 접두(공통 기반 3) 말고는 현행 문자열을 그대로 재현**(기본값 메아리 포함)하고, PR ② 슬라이스 6에서 기본값 생략·`--chars`/`--json` 보존으로 바꾼다. 단 `--limit`은 항상 싣는다 — 명시 limit 여부가 다음 호출의 요청 상한(40/10, `_browse.py:82`)을 정하기 때문.
- 완료 판정(구조): `cli.py` 밖에 **명령명으로 분기하거나 검증하는 코드가 없다**(`if/elif/match`·비교·`in` 멤버십에서 `args.command`나 명령명 리터럴 사용). 명령명을 컨텍스트에 저장하거나 헤더에 표시하는 것은 허용. 판정은 커밋하는 `tests/twitter/test_declarations.py`(AST) 0건 + 코덱스 리뷰 확인. 레이아웃(최상위 이름·방향·sys.path)은 공통 구조 테스트가 따로 본다.

## 인터페이스 변경 명세 (PR ②)

**help** — 명령별 문구, 문장 비접힘. 코덱스 표의 오류를 전부 해소: `user` target은 "numeric IDs are not accepted", `--limit`은 그 명령의 단위(posts/accounts/replies/trends)와 기본값만, 날짜 옵션은 허용 탭/피드를 명시, `post`는 batch가 `--limit/--sort/--after`를 거절한다고 명시, `articles` 탭은 본문 미전개 명시, 루트 epilog는 exit 코드 표 유지.

**fix** — 인자 오류(exit 2)는 전부 명시적 fix(바꿀 플래그를 이름으로). 기본 fix "Run doctor"는 세션·Aside 계열에만. 서명 계열 fix는 표면별: `user --tab replies` → `--tab replies-only`(비답글 섞임 명시), `graph followers` → `following`은 다른 질문임을 명시, 대체 없는 표면(search·quotes)은 `refresh` 후 재시도만. Aside 타임아웃 fix는 "Aside 상태 확인 후 같은 명령 재시도"(표시 목표를 줄이라는 권고 제거). `contract_drift`·`envelope_drift`는 "코드 수정 필요 — 이 연산에 국한될 수 있으나 이 실패가 다른 표면의 정상을 보여주지는 않는다".

**렌더**(성진 결정 11)
```
user posts · 3 shown · stopped=limit_reached · 2 requests · UserTweets 49/50 resets 15m · UserByScreenName 149/150 · window 6/200
@AnthropicAI (Anthropic ✓business) · followers 1.8M · … bio: "… on https://claude.ai." · https://x.com/AnthropicAI
[t1] @AnthropicAI ✓business · 2026-09-24 08:08+09:00 · likes=855 reposts=63 replies=137 quotes=14 views=126.2K
     "…outbreak ⏎⏎ Read the full piece…"
     https://x.com/AnthropicAI/status/2102897863097545197
more: uv run "/…/scripts/cli.py" user @AnthropicAI --limit 3 --after k7f2
warning: <경고 문장>          (있을 때만, 중복 제거)
stopped: <error>: <message> · fix: <fix>   (부분 실패 시)
```
헤더: 명령+탭/피드/정렬(실제 요청을 바꾼 것만), shown/stored, stop, 요청 수, 사용한 버킷 `remaining/limit`(주 연산에만 reset), 계정 창. 삭제: `operation=`, `fetched MB`. search users는 `rank=people`, media는 `product=media` 유지. **조건부로 유지(현행 `_render.py:106-109,118-119`)**: 스레드 `replies: D direct shown of R reported · +N nested · hidden branches H`, trends `other items · promoted excluded`, `viewer changed`. 각각 S1 텍스트 단언.

**레코드**(성진 결정 12): `entities` 제거, `mentions` 추가, `text`는 t.co 전개·미디어 t.co 제거, `urls`는 전개 URL 목록 유지. User bio t.co 전개(`legacy.entities.description.urls`). `mentions` = `@` 없는 handle 문자열, 본문 등장 순서, 대소문자 무시 중복 제거, 엔티티 출처는 `text`와 같은 우선순위(note_tweet `entity_set` → legacy `entities`, `_models.py:62-63`), 리포스트 행은 원글 값을 복사(`_models.py:83` 복사 키 목록에 추가), 인용은 인용 레코드 자신의 값. `--out` 헤더 `format: 2`, 연속 상태 파일에도 `format: 2` — 형식이 다르면 거절(fix: 같은 명령을 처음부터 / 새 `--out` 파일), 거절 시 옛 파일은 변경하지 않는다.

**연속**(성진 결정 13):
- 핸들 문법: `[a-z0-9]{6}`(무작위, `secrets.choice`). `--after` 입력은 파일 접근 **전에** 이 문법으로 검증 — 경로 구분자·`..`·길이 위반은 exit 2. 옛 숫자 핸들도 이 검증에서 거절(fix: 처음부터 다시).
- 생성: `O_EXCL`로 만들고 충돌 시 재추첨. 파일에는 컨텍스트(쿼리+viewer)와 `created_at`을 싣고, 로드 시 컨텍스트 불일치면 거절 → 만료 뒤 같은 토큰이 다른 쿼리에 재발급돼도 옛 명령이 남의 상태를 읽지 못한다(재발급 자체를 금지하지는 않는다; 공간 36⁶).
- 만료: **로드 시** `created_at`으로부터 24h 지나면 거절. 후속 핸들은 새 `created_at`을 갖는다(체인 전체가 아니라 각 핸들 기준).
- 삭제: 핸들을 저장할 때와 `doctor` 실행 때 만료 파일을 지운다. 백그라운드 삭제는 약속하지 않는다 → SKILL.md는 "자동 삭제"를 주장하지 않는다. viewer 변경 시 전부 삭제(유지).

**doctor**: 위 Claude 판단 참조. 출력 예: `@handle · viewer 1818… (matches cache) · unblocked · registry refreshed 20d ago · signature material 0d · Viewer 98/100 · window 4/200 · cache ~/.cache/twitter-skill (3 continuations)`.
- 차단 중(`--unblock` 없음): 요청 0, 차단 사유·`doctor --unblock` fix, viewer는 `unverified (blocked)`, exit 5.
- `--unblock`: 사람이 풀 수 있는 차단(challenge·account_locked)만 지우고 이어서 정상 진단(쿠키 재읽기·Viewer 요청). 관측 버킷·10분 창은 건드리지 않는다(현행 `unblock()` 동작 유지).
- viewer 불일치: 세션 강제 갱신 경로(`_session.ensure(force=True)`)와 같은 무효화(연속 삭제), 출력에 `viewer changed`.

**schema**(성진 결정 17): 인자 없음 → 목차(주제·필드 수·`next: schema <topic>`), `schema --json`(무인자)은 같은 목차의 기계용 JSON. `schema <topic>` 닫힌 선택: `tweet user media list community trend envelope export`. 텍스트 모드는 `이름 타입 설명` 한 줄씩, 설명은 자명하지 않은 필드에만(`id`, `author`, `text`, `url`, `created_at`, `retweeted_tweet`, `quoted_tweet_id`, `is_blue_verified`(구독, 신원 아님), `in_reply_to_id`, `role`, `depth`, `module`, `community_url`, 카운트의 null≠0, trend `id`는 엔트리 식별자). 동적 필드는 해당 레코드 주제(`tweet`)에만, stop_reason 전 목록은 `envelope`에만. `schema <topic> --json`은 그 주제의 JSON Schema와 **참조하는 정의를 각 한 번씩**(`$defs`). `envelope`: 결과 필드·stop_reason 의미·exit 코드·오류 분류. `export`: header/record/page 줄 모양·format·재개 규칙. 레코드 필드 목록은 dataclass에서 생성(두 번째 사본 금지), 동적 필드 설명은 한 표에만.

**그 밖**: `--type media --sort` 거절, `trends --chars` 적용 + 연속 핸들, place 카드 `--chars` 적용, `--out` 기존 파일 권한 검사.

## SKILL.md 섹션 구조 (영어, 한 문단=한 줄, 문단 단위 제거 시험으로 존폐 판정)

```
---
name: twitter
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)      # 공통 기반 3, PR ① 단계 2에서 바뀐다
description: … (현행 유지 + 알림·DM 제외를 여기로 옮김)
---
# X through the person's own browser
  호출 경로 한 줄; --help=명령별 인자, schema=필드 의미, 오류 fix=복구
## Every request spends the person's account
  버킷은 연산별·검색 제품은 한 버킷 공유; 수집 전에 몇 명·몇 건이 답인지 정함; 표시 목표를 줄여도 첫 요청은 안 싸지고 캐시된 꼬리는 공짜
## Some surfaces break while others keep working
  서명 표면은 X 배포에 따라 따로 깨짐; 대체 표면은 질문을 바꿈(replies-only는 비답글 섞임) → 바꾼 것을 답에 밝힌다
## What a row shows is not what it seems
  리포스트 행=리포스터의 행동+원글 본문·수치; Top·For you는 표본 아님; 보고된 답글 수≠본 답글, 숨은 가지 미전개; 좋아요 누른 사람 목록 없음
  (배지 의미는 schema·렌더가 소유)
## Joining records and following links
  ID로 잇고 핸들은 바뀜; 팔로우≠친분, 리포스트≠동의
  (프로필 조회가 핸들만 받는다는 기계적 제약은 target help가 소유)
## Date windows: server filter vs client filter
  검색 연산자=서버 필터, 타임라인 창=클라이언트 필터; window_reached 외의 멈춤은 창 완주의 증거가 아님(프로필 posts만 시간순 근거)
## Large collections are personal data
  큰 수집은 --out; 파일은 레포 밖, 작업 후 삭제; 캐시 세션은 같은 사람이 계속 로그인했다는 증거가 아님
```
삭제: "What has actually bitten"(파서 세부는 코드가 처리, 아티클 미전개는 help, 알림·DM은 description), "Three surfaces" 목록과 오류 3종 구분(fix 소유), 프로필 버킷 크기 비교(헤더가 실측 잔량 표시), 연속 파일 삭제 지시(24h 만료가 코드 소유), 페이지 커밋·재개 세부(`--out` help·`schema export`).

**문단 ↔ 시나리오 대응** (제거 시험의 근거. 대응 시나리오가 없는 문단은 "측정 안 됨"으로 표시하고 코덱스 네 프레임 리뷰 + 성진 승인으로만 존폐를 정한다)

| 문단 | 시나리오 |
|---|---|
| 첫 문단(호출·인터페이스 지도) | 전부(호출 실패율) |
| Every request spends… | ⑤ 검색 버킷 잔량 3에서 다섯 주제 |
| Some surfaces break… | ⑥ 서명 거절 후 답글 요청 |
| What a row shows…(리포스트) | ① 리포스트 행 작성자·좋아요 귀속 |
| What a row shows…(Top·For you) | ② Top 검색으로 "최신"을 묻기 |
| What a row shows…(답글 완결성) | ④ 보고 1,460·본 20·숨은 가지 스레드 요약 |
| Joining…(ID·핸들) | ⑨ 핸들이 바뀐 계정의 두 수집을 합치기(같은 id, 다른 handle) |
| Joining…(팔로우≠친분) | ⑦ 팔로워 목록으로 "친구" 묻기 |
| Date windows… | ③ 날짜 창인데 `limit_reached`로 멈춤 |
| Large collections… | ⑧ 500건 수집(`--out`·레포 밖·삭제) |

## 작업 단계 (각 단계: 완료 판정)

### PR ① `refactor/twitter-surface-declarations` — `refactor: twitter를 cli.py와 패키지 하나로 옮기고 명령 선언을 모은다`
**PR ①은 현행 동작의 재배치만 한다**(승인된 호출·help 변경 제외 — 공통 기반 7). 새 레이아웃 이행도 PR ①이 맡는다(M9). 선언 기반 구현도 현행 help·검증·`more:` 문자열·레코드·저장 형식을 그대로 재현한다. 위 트리의 파일 설명 중 새 의미(t.co 전개, 무작위 핸들, format 2, 권한 검사, schema 주제 등)는 전부 PR ②의 해당 슬라이스에서 시작한다.

0. **골든 기준 캡처**(`tests/twitter/tools/golden.py`, 커밋하되 산출물은 스크래치): 가짜 Aside로 CLI 매트릭스 — 명령 16개 `--help`, `schema`·`schema --json`, `test_cli.py` 성공 매트릭스 전부(텍스트+JSON), 거절 매트릭스, `TWITTER_FAKE_SCENARIO=429`·`empty`·`empty_users`, "첫 페이지 성공 후 429" 부분 결과(`test_cli.py:153-155`), `--out` 신규→재개→완료, `--after` 연쇄.
   정규화 계약: 독립 케이스마다 **새로 시드한 `TWITTER_HOME`**(연속·내보내기 시나리오 안에서만 상태 유지), `TZ=UTC`, `PYTHONHASHSEED=0`, 정규화 허용 목록만 치환 — `reset_at`·`observed_at`·`fetched_at`·`read_at`·상대 시각(`resets in Nm`)·스크래치 절대 경로·`seen` 목록(정렬 후 비교). 보존 비교: 레코드 순서, 요청 수(`TWITTER_FAKE_LOG` 줄 수), operation·variables, exit, stop_reason. 캡처된 `more:` 명령은 **실제로 실행**해 동작을 확인(경로 정규화가 깨진 명령을 가리지 못하게). 단계 2 이후의 `more:`는 접두가 `['uv','run',CLI]`인지 단언한 뒤 나머지 인자를 `[sys.executable, CLI]`로 실행한다(공통 기반 6). 골든 비교의 허용 차이는 `more:` 접두와 `usage: cli.py`뿐이다. 예산 sleep은 그대로 둔다(느리지만 결정적).
   판정: 새 체크아웃에서 두 번 실행해 정규화 후 바이트 동일.
0b. **live 기준선**(guard 경유, ≤16요청): 아래 5단계와 같은 명령 목록을 이동 전에 실행해 exit·헤더 필드·레코드 kind를 기록.
1. **seam 이관(테스트 먼저)**: 내부 import 테스트 12개를 S1 CLI 테스트로 옮긴다(위 tests 트리). 필요한 fake 시나리오(서명 거절·CSRF 353·viewer 변경·드리프트·청크 봉투·refresh 번들)를 `fake_data.py`에 추가. 옛 테스트→새 테스트 대응표를 PR 본문에 싣는다. 이 단계는 기존 conftest 부트스트랩을 그대로 쓴다(공통 기반 7 전환 시점). 판정: 내부 import가 `test_signature.py`·`test_budget.py`에만 남음, 전체 통과, 옛 테스트의 단언 각각이 대응표에서 새 테스트에 짝지어짐, 골든 불변.
2. **패키지화·이동(새 레이아웃 이행)**: `git mv`로 위 트리대로(함수 이동 포함), `twitter.py` → `cli.py`(PEP 723 헤더), 각 시스템 폴더가 `Path(__file__)`로 자기 자산(`registry.json`, `snippets/`)을 찾게 하고, `more:` 접두를 공통 기반 3으로 바꾸며 소비자(`tests/twitter/live/test_live.py:44,49`, 골든 도구)를 공통 기반 6으로 고친다. SKILL.md 프론트매터·호출문, `README.md:10,69`·`docs/usage.md:10-12,93,102-103,133`의 경로, JS 테스트 경로(`graphql/protocol/snippets`)를 갱신한다. 전환 시점 작업: 부트스트랩 제거(`twitter.py`·`conftest.py`, 그리고 `tests/twitter/fake_aside/aside:8`의 `sys.path.insert` — fake가 `fake_data`를 `runpy.run_path`로 형제 파일 경로에서 읽게 바꾼다), `scripts/__init__.py` 삭제, `tests/twitter/__init__.py`는 유지하되 `tests/__init__.py` 생성, pyproject `pythonpath`, S2·S3 import 경로를 `twitter.graphql.protocol.signature`·`twitter.account.budget`로, `tests/test_skill_layout.py` 생성 또는 twitter 항목 추가. `# 성진:` 주석 2개 이동. 판정: pytest·node·ruff·PII 통과, 골든 동일(허용 차이 둘), `more:` 접두 = allowed-tools 형태 테스트 green, `python3 -m pytest tests/test_skill_layout.py` green, 이동성(공통 기반 6: `ln -s`로 스크래치에 링크한 스킬과 공백·한국어·`$`·따옴표 경로 사본, 다른 cwd에서 `uv run` `--help`와 가짜 Aside 한 명령, 출력된 `more:` 셸 실행) 동작.
3. **선언 통합**: 파서·`validate`·`more_command`·렌더의 명령 분기를 `cli.py`의 `Surface` 선언으로 옮기고, operation·prepare·fetch는 `browse/operations.py`에 두어 선언이 참조한다(M11). 판정: 골든 동일, `test_declarations.py` 0건.
4. **registry.json 정리 + live 가드**: 런타임 미사용 필드 제거. `guard_aside.py`가 `TWITTER_LIVE_TOTAL`(기본 150)·`TWITTER_LIVE_WINDOW`(기본 50/600초)를 **발송 전에** 강제하고 실패한 시도·auxiliary도 센다. 판정: registry 키 집합 = {bearer, features, operations{query_id, method, gated, root, vars[, fieldToggles]}}, 골든 동일, 가드 상한 초과 호출이 발송 없이 거절됨을 가짜 real-aside로 확인. 제거 경위는 커밋 본문.
5. **live 스모크**(guard 경유, ≤16요청): home following, user posts, user replies(서명), about 2개, post 스레드, search posts, search users, graph followers(서명), me bookmarks, list(공개 리스트 하나), trends, community(공개 하나), doctor. 판정은 출력 동일이 아니라 **구조 단언**: exit가 0·7(empty) 또는 0b 기준선과 같은 비0, 헤더 필드와 레코드 kind가 0b와 같음. `rate_limit`·`challenge`·`account_locked`이면 즉시 중단·성진 보고.
6. **코덱스 리뷰**(`gpt-6-astra` medium, read-only, fast): "골든 밖에서 바뀐 동작을 열거하라"는 경계 있는 질문. 판정: 지적마다 수용/기각 사유 기록, 수용분 반영 후 같은 스레드 재리뷰 1회.
7. 푸시·PR·`gh pr merge --squash`. PR 본문: 무엇을 바꿨나/왜/영향/검증(실행 명령과 수치 그대로, 옛→새 테스트 대응표). 머지 후 `graphify-out/` 리빌드(Graphify 스킬)를 main 직접 커밋.

### PR ② `feat/twitter-interface-repair` — `feat: twitter help·복구·출력·연속 수명을 모델 기준으로 고친다`
각 슬라이스는 tdd 루프(S1에서 빨강→초록, 기대값은 명세·fixture 원본에서, 현재 출력 복사 금지). 슬라이스마다 커밋. 순서와 완료 판정:
1. **인자 오류 fix 전수**. 판정: 거절 매트릭스(현행 + 새 금지 조합) 전부 exit 2, fix가 기본 문구가 아니고 관련 플래그 이름을 포함.
2. **닫힌 선택 정리**: `--type media --sort` 거절, `trends --chars`를 설명에 적용 + 받은 페이지 나머지를 연속 핸들로(추가 요청 0 — `TWITTER_FAKE_LOG` 줄 수로 확인), place 카드 `--chars` 적용. 판정: 각각 S1 단언, media 거절 fix가 `--sort` 제거를 지시.
3. **명령별 help + 비접힘 포매터**. 판정: 16개 help를 실행해 코덱스 감사 표의 오류 각각이 사라졌음을 개별 assert(예: `user` target에 "numeric" 거절 문구, `home --help`에 "batch"·"focal" 없음, 날짜 옵션이 허용 탭/피드 명시), 어떤 help 문장도 두 줄로 나뉘지 않음(출력에서 줄바꿈 뒤 소문자로 이어지는 줄 0).
4. **서명·드리프트·타임아웃 fix 표면별화**. 판정: fake 시나리오(404 빈 본문, 422, 청크 봉투 타임아웃)에서 `user --tab replies`는 replies-only(비답글 섞임 명시), `graph followers`는 following이 다른 질문임을, `search`·`quotes`는 refresh만 제시. 어떤 fix도 "reduce the request size"를 포함하지 않음.
5. **레코드**(entities 제거·mentions·t.co 전개·format 2 — 내보내기와 연속 상태 둘 다). 판정: fixture 원본의 (t.co, expanded) 쌍으로 기대값 구성; note_tweet·중첩 인용·리포스트 케이스에서 `mentions`가 표시 텍스트와 일치; 옛 format 연속 핸들·옛 헤더 `--out` 파일은 거절되고 파일 바이트 불변; 한 출력에 옛/새 형식이 섞이지 않음.
6. **연속**(`[a-z0-9]{6}` 핸들·로드 시 24h 만료·저장/doctor 시 삭제·`more:` 기본값 생략·`--chars`/`--json` 보존·`--limit` 항상 유지). 판정: `created_at` 조작으로 만료 거절; `../x`·`1`·`ABCDEF`·7자 입력이 파일 접근 없이 exit 2; 강제 충돌(난수 고정)에서 재추첨; 컨텍스트 다른 핸들 거절; 기본 limit으로 받은 `more:`를 실행했을 때 요청 상한이 이전 호출과 같음(40/10).
7. **렌더**(헤더·경고 문장·오류 메시지·`⏎⏎`·url 따옴표 제거·조건부 완결성/trend/viewer 줄). 판정: 위 렌더 예시를 fixture로 재현, 스레드·trends·viewer 변경 각각의 줄 존재 단언, 헤더 ≤120자(스레드·trends 조건부 줄 제외).
8. **`--out` 권한 검사**. 판정: 0644 기존 파일 → exit 2, fix에 `chmod 600` 또는 새 경로, 파일 바이트·권한 불변; 새 파일은 0600.
9. **doctor**(viewer 대조·차단 선보고·`--unblock` 계약·반올림 나이·캐시 위치·만료 정리). 판정: fake로 viewer 변경 → `viewer changed`+연속 삭제; 차단 상태 → 요청 0·exit 5·`unverified (blocked)`; `--unblock` → 차단 해제 후 진단, `budget.json`의 버킷·창 불변; 나이에 소수점 없음.
10. **schema 목차·주제**. 판정: 목차 텍스트 ≤1KB; `schema tweet`에 동적 필드 5개; `schema envelope`에만 stop_reason 전 목록; `schema <topic> --json`의 `$defs`에 각 정의 한 번; 무인자 `--json`은 목차.
11. **SKILL.md 후보 초안**: 위 6섹션 구조대로 작성(`description`에 알림·DM 제외 이동). 판정: 섹션 구조 일치, 한 문단=한 줄, 인터페이스가 소유하는 사실(배지·핸들 전용 조회·복구 분류·커밋 세부)이 본문에 없음.
12. **모델 시나리오 하네스 + 기준선**(`tests/twitter/model/`): 시나리오 ①~⑨(대응표). 함정 fixture는 `fake_data.py` 시나리오로.
    - 실행 모델 **Claude Opus**(`claude-opus-5-5`, 성진 결정 14). 채점은 코덱스 `--schema` 배치가 must/must_not을 판정하고, Claude가 불일치 전부를 원 transcript로 확인.
    - 격리: 스크래치에 스킬 디렉터리 복사 + 시드된 `TWITTER_HOME` + `TWITTER_ASIDE_BIN`=가짜 Aside 절대 경로 + `PATH`에서 실제 `aside` 디렉터리 제거. 명령: `claude -p --safe-mode --restricted --strict-mcp-config --tools Bash --permission-mode dontAsk --allowedTools 'Bash(uv run "<복사본>/scripts/cli.py" *)' --model claude-opus-5-5 --output-format json` — `--safe-mode`는 CLAUDE.md·스킬·플러그인을 꺼서 성진 전역 지시가 섞이지 않게 하고(`--append-system-prompt`는 그래도 전달됨, `claude --help`로 확인), `dontAsk`+허용 패턴으로 그 밖의 셸은 거부된다. 스킬 자동 발견에 기대지 않는다. 첫 실행 전에 허용 패턴 밖 명령(`aside --help`)이 거부되는지 한 번 확인.
    - 처치: A = 과제 + "CLI는 `uv run \"<복사본>/scripts/cli.py\"`, `--help`부터" / C = A + `--append-system-prompt`로 후보 SKILL.md 본문. A 디렉터리에는 SKILL.md가 없다(복사 시 제외).
    - 무효 런: `permission_denials` 존재, CLI 미실행, 가짜 로그에 호출 0, A가 SKILL.md에 접근. 재실행하고 카운트하지 않는다.
    - 판정: 9개 × A/C 각 1회 완료, 결과표(시나리오별 A/C 통과 여부) 기록.
13. **문단 제거 시험**: 후보에서 문단 하나씩 뺀 C′를 대응 시나리오에 1회 → C와 결과가 같으면 2회째 → 두 번 다 같으면 삭제 후보. 기준은 늘 같은 후보 C와 새로 시드한 fixture 상태. 대응 시나리오 없는 문단은 "측정 안 됨" 표시. 판정: 문단마다 {유지 근거 시나리오 | 삭제 | 측정 안 됨} 기록.
14. **코덱스 리뷰**: 코드 diff(계약 위반 열거) + SKILL.md 네 프레임 문단별 판정. 판정: 수용/기각 사유 기록, 수용분 반영 후 재리뷰 1회. SKILL.md가 바뀌면 바뀐 문단만 13단계 재시험.
15. **성진 승인**: SKILL.md 전문을 AskUserQuestion `preview`로(부분·침묵 불가). 이후 SKILL.md를 한 글자라도 바꾸면 재승인.
16. **live 시나리오**: ①·④·⑥ 중 2~3건, guard 경유. 판정: 결과와 소모 요청 수 기록, 세션 누적 150 이하.
17. **문서**: `docs/usage.md:102-103`(schema 설명)·README twitter 행 등 ②로 **거짓이 된 문장만**(경로는 PR ① 단계 2에서 이미 갱신). 판정: `grep -n "twitter" README.md docs/usage.md CONTRIBUTING.md`의 각 줄이 새 동작과 일치함을 확인한 목록을 PR 본문에.
18. `claude plugin validate --strict .claude/skills` exit 0, `claude -p "/skill-doctor"`로 이웃(threads·facebook·reddit) 트리거 충돌 없음.
19. 푸시·PR·스쿼시 머지 → `graphify-out/` 리빌드 main 직접 커밋.
20. 이 계획 파일 끝에 `# 구현 기록`: 계획과 달라진 결정, 시나리오 A/C·제거 시험 결과, live 소모 요청, 남은 한계(`grep -rn "성진:"`), 모델 기본값을 교정하는 문장이 어느 모델(Claude Opus 5.5) 기준인지.

## 검증

- 매 단계: `python3 -m pytest tests/twitter -q`(PR ① 단계 2부터 `tests/test_skill_layout.py` 포함), `node --test tests/twitter/js/*.js`, `.claude/skills/finviz/.venv/bin/ruff check --config pyproject.toml .claude/skills/twitter/scripts tests/twitter`, `python3 tests/twitter/tools/check_fixtures_pii.py`.
- PR ①: 골든(정규화 계약, 허용 차이 둘) 동일 + live 구조 스모크(0b·5단계, 합계 ≤32요청) + 이동성(공통 기반 6: 심볼릭 링크·특수 문자 경로·다른 cwd, `uv run`).
- PR ②: 슬라이스별 S1 테스트, 시나리오 A/C와 제거 시험(가짜 Aside, 계정 요청 0), live 시나리오 2~3건.
- 스킬 형식: `claude plugin validate --strict .claude/skills` exit 0, `claude -p "/skill-doctor"`.
- live 예산: 구현 세션 전체 150요청, 10분 50 이하(성진 결정 18). **모든 live 호출은 `TWITTER_ASIDE_BIN=tests/twitter/live/guard_aside.py`, `TWITTER_REAL_ASIDE=aside`, 세션 전용 `TWITTER_LIVE_LEDGER`(스크래치)로** — 가드가 발송 전에 거절하므로 헤더 합산에 기대지 않는다. 원장 수치를 트래커와 PR 본문에 기록. `rate_limit`·`challenge`·`account_locked`가 한 번이라도 나오면 live를 즉시 멈추고 성진에게 알린다. 예상 소모: PR ① 32 + PR ② 확인 ~20 + 시나리오 ~30 ≈ 80.
- 코덱스: 계획 비판(이 세션), PR ①·② 리뷰(구현 세션). 전부 `gpt-6-astra` medium, read-only, fast.

## 폐기하지 않는 결정 (반드시 살릴 계약)
1. 읽기 전용: 신뢰된 연산 사양, 캐시 오버라이드는 `query_id`·`gated`·`features`만, 허용 호스트 URL, 쓰기 연산 발견·실행 없음.
2. 세션 비밀: 로그인 자격은 브라우저에, 쿠키는 `ct0`·`twid`만, 진단·오류는 scrub.
3. 계정 결속: 연속·내보내기는 쿼리+viewer 컨텍스트에 결속, viewer 변경 시 무효화.
4. 요청 보호: 요청 전 예약, 영구 차단, 관측 버킷 존중, 재시도 한도(CSRF 1회·서명 1회), 1초+지터 간격.
5. 대상 의미: 핸들·x.com URL·ID, 숫자 프로필 ID 거절, 검색어는 그대로 통과.
6. 레코드 의미: 안정 ID, null≠0, note_tweet 우선 전문, 리포스트 행 정체성/원글 내용 분리, 인용 다음 홉 URL.
7. 스레드 정직성: parent/focal/reply, 깊이, 숨은 가지 계수, 보고 수≠수집 수.
8. 페이지네이션: 캐시 꼬리 먼저(요청 0), ID 중복 제거, 명시적 stop_reason, 뒤 실패 시 부분 결과 보존.
9. 날짜 의미: 클라이언트/서버 필터 구분, `until` 배타, 고정글 처리, `window_reached`는 `UserTweets`에만.
10. 내보내기 회복: 날짜 적격 페이지 단위 커밋, 컨텍스트 검증, 배타 잠금, 무결성 마커, 미완 꼬리 회복.
11. 모델용 출력: JSON 모드는 문서 하나, 의미 있는 exit 코드(0·2·3·4·5·6·7·8·9), focal 전문, 실행 가능한 `more:`.
12. refresh 규율: 스테이징 → `UserByScreenName`·`SearchTimeline` 재생 검증 → 게시, 실패 시 캐시 원복. help·schema는 브라우저 없이 동작.
13. 기존 `# 성진:` 주석 2개(새 위치로 이동), `signature.py`의 MIT 고지.

## 하지 않는 것
- Codex 호스트 지원·경로 폴백 규칙(성진 결정 6), Windows 지원.
- 레포 공통 문서(README·usage.md)의 Codex·설치 안내 정책 변경(결정 10).
- 새 표면 추가(알림·DM·좋아요 누른 사람 등), 쓰기 동작.
- 예산 계층 수치(1초·20%·200/10분) 변경 — 근거가 계정 보호 추정이며 이번 결함과 무관.
- 형제 스킬 정렬.

## 검증하지 않은 것 · 남은 위험
- fixture 시나리오는 실제 X 응답의 다양성을 다 담지 못한다 → live 2~3건으로만 보완.
- 서명 알고리즘은 X 배포에 따라 언제든 깨질 수 있다. 이번 변경은 그 위험을 바꾸지 않고, 깨졌을 때의 fix만 정확하게 만든다.
- `doctor`의 viewer 불일치 상황은 live로 재현하지 않는다(계정 전환 필요) → S1 fake 시나리오로만.

# 구현 기록

2026-09-29, 한 세션. PR ① #30(2e8376c, `refactor/twitter-surface-declarations`), PR ② #31(087b161, `feat/twitter-interface-repair`), 둘 다 스쿼시 머지.

## 계획과 달라진 결정

- **live 요청 수**: 0b 기준선 21건(graphql 18·auxiliary 3), 5단계 스모크 17건 — 계획의 ≤16·합계 ≤32를 넘었다. 13개 명령 목록 자체가 GraphQL ~18건을 요구한다(프로필 계열은 핸들 해석을 먼저 한다). PR ② live 시나리오 3건 + README 예시 행 1건. 세션 합계 42/150, 10분 창 50 이하, 보호 오류 0.
- **골든 정규화**: 허용 목록에 doctor의 `registry_age_days`·`txid_age_days`와 요약 문장의 나이를 더했다(실행 시각에 따라 바뀐다). 비교의 허용 차이는 계획대로 둘뿐.
- **테스트 기계**: `tests/twitter/helpers.py`를 두었고(계획 트리에 없음), 가짜 Aside에 스크립트 응답(`TWITTER_FAKE_SCRIPT`, op·cursor 매칭, `keep`, `chunks`, `raw`)과 trace를, `process_doubles/sitecustomize.py`에 `FAKE_NO_SLEEP`·`FAKE_CLOCK_OFFSET`·`FAKE_HANDLE_CHARS`를 더했다. 스위트 30s → 16s(PR ① 시점).
- **선언으로 옮기지 않은 검증**: `about --limit`과 about/trends `--after` 거절은 옵션 자체가 없어 argparse가 먼저 막으므로 도달할 수 없어 옮기지 않았다(PR ①). PR ②에서 trends에 `--after`가 생겼다.
- **refresh 요약**: `output/doctor.py`로 옮기면서 refresh 결과가 `feature_changes`를 실어 넘기고 요약이 꺼내 간다(JSON 키 순서를 지키려고 `summary`·`next`는 자리를 먼저 잡는다).
- **헤더**: 넉넉한 보조 버킷은 20% 아래일 때만 보인다 — 계획의 예시 헤더가 보조 버킷을 넣으면 129자라 ≤120 기준과 부딪쳤다. `GlobalCommunitiesLatestPostSearchTimeline` 헤더는 120자를 넘는다(연산 이름이 버킷의 정체). 두 결정 모두 코덱스 리뷰에서 지적됐고 이유를 달아 기각했다.
- **more:의 요청 상한**: `--limit`을 늘 실으면서도 상한(10/40)을 잇기 위해, 핸들 상태에 `limit`·`explicit_limit`을 싣고 모델이 `--limit` 값을 바꾸면 명시로 본다.
- **SKILL.md**: 계획의 6절 대신 성진이 승인한 압축안(4절 5문단). 근거는 아래 제거 시험과 코덱스 네 프레임 리뷰(run 20260929-205805-twitter-skill-review-3b57). 좋아요 누른 사람 목록 없음과 날짜 옵션이 가져온 글만 거른다는 사실은 help로 옮겼다. description은 계획대로(현행 + 알림·DM 제외); 리뷰의 description 재작성 제안은 라우팅을 시험하지 않았으므로 기각.
- **하네스**: 두 처치 모두에 "셸 호출 하나 = CLI 명령 하나" 권한 경계를 알린다(첫 시도에서 `; echo "exit=$?"`·셸 변수로 무효 런이 났다). `grade.py`·`verdict.schema.json`·`__init__.py`를 더했다. `--repeat` 이름 충돌을 고쳤다.
- **③ fixture 결함**: 처음엔 replies 탭·검색을 스크립트하지 않아 기본 가짜 데이터(9월 5일 글 7개)가 섞였다. 두 표면에도 같은 30개를 두고 A·C·C′를 다시 돌렸다.
- **코덱스 코드 리뷰에서 더한 동작**: `cache_unreadable` 오류 분류, doctor가 X의 Viewer 응답이 쿠키와 다르면 확인해 주지 않고 `viewer_changed`, `--out`의 캐시 경로 거절, 커밋 앞의 손상된 줄은 무결성 오류, `schema envelope|export --json`은 JSON Schema.
- **graphify-out**: `.git/info/exclude`로 추적되지 않아 "main 직접 커밋" 대신 로컬 리빌드만(`graphify update . --force`, 두 PR 뒤 각각).
- **CI**: "Social skill checks" 워크플로가 2026-09-13 이후 어떤 브랜치에서도 돌지 않는다. 같은 명령을 로컬에서 돌렸다(PR ① 1402 passed, PR ② 1530 passed).

## 모델 시나리오 (claude-opus-5-5, 가짜 X)

채점은 코덱스 `--schema` 배치(gpt-6-astra medium), 판정 전부를 Claude가 transcript로 확인했고 1건(⑧-C: 개인정보·삭제 안내가 있었다)을 뒤집었다.

| 시나리오 | A | C(6절) | 압축안 |
|---|---|---|---|
| ① 리포스트 작성자 | 통과 | 통과 | 통과 |
| ② 개인화 피드의 최신 | 통과 | 통과 | 통과 |
| ③ 날짜 창 | 통과 | 통과 | 통과 |
| ④ 답글 표본 | 통과 | 통과 | 통과 |
| ⑤ 검색 버킷 | 통과(요청 9, 타임라인으로 우회) | 통과(요청 3) | 통과 |
| ⑥ 서명 실패 대체 | 통과 | 통과 | 통과 |
| ⑦ 친구 | 실패 1 · 통과 2 | 통과 | 통과 |
| ⑧ 500건 수집 | 실패 | 통과 | 통과 |
| ⑨ 핸들 변경 | 통과 | 통과 | 통과 |

제거 시험(대응 시나리오 2회씩): Every request·Some surfaces·What a row·Joining·Date windows는 빼도 두 번 모두 C와 같았다(삭제 후보). Large collections는 빼면 ⑧이 실패했다(유지). 첫 문단은 하네스가 호출문을 주므로 측정 안 됨. 압축안 9/9. 무효 런은 권한 경계 문장을 넣은 뒤 0건, 압축안 ⑧ 1건(다른 런이 스크래치 루트에 남긴 `--out` 파일을 재개함 — 규칙대로 재실행).

## live

PR ①: 0b와 5단계가 exit·JSON 키·레코드 kind·card·stop 모두 같았다(`me bookmarks`는 두 번 모두 빈 타임라인 exit 7). PR ②: 승인된 SKILL로 ① @X 인기 글(리포스트 2건을 빼고 자기 글만 순위)·④ 2089465307844825263 답글(561 중 상위 20 표본임을 명시) 통과. ⑥은 실제 서명 붕괴를 만들 수 없어 돌리지 않았다.

## 남은 한계

- `grep -rn "성진:"`: `account/state.py:17`(단일 계정 락), `account/budget.py:28`(1초·20% 감속 추정) — 둘 다 계획 이전부터의 것, 새로 남긴 것 없음.
- 모델 시나리오는 각 1~2회라 변동을 가리지 못한다(A의 ⑦이 한 번 실패, 두 번 통과). 가짜 데이터로는 실제 계정 잠금·서명 붕괴·계정 전환을 재현하지 못한다. 시나리오 원 transcript와 채점 결과 파일은 세션 스크래치에 있었고 세션 중 지워졌다 — 수치는 이 기록과 PR 본문에만 남아 있다.
- 계정 위험 문단과 팔로우·리포스트 문단은 가짜 데이터로 효과를 잴 수 없어 코덱스 리뷰와 성진 승인으로 남겼다.
- 모델 기본값을 교정하는 문장의 기준 모델은 Claude Opus 5.5(`claude-opus-5-5`)다. 모델이 바뀌면 `tests/twitter/model/run.py`로 A/C와 제거 시험을 다시 돌려 존폐를 다시 정한다.
