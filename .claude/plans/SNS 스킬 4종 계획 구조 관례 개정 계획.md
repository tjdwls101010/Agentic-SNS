# SNS 스킬 4종 계획의 구조 관례 개정 계획

> 계획 세션 2026-09-25~26. 승인 직후 `.claude/plans/SNS 스킬 4종 계획 구조 관례 개정 계획.md`로 옮긴다(계획 모드 도구가 이 경로를 읽으므로 승인 전에는 옮기지 않는다). 작업 트리의 무관한 변경(`.gitignore`, `.claude/harness-spec.md` 삭제, 다른 계획 파일, `.ultra-search/`)은 건드리지 않는다.

## Context

facebook·reddit·threads·twitter 스킬의 재설계 계획 4개(`.claude/plans/` 아래 `facebook 스킬 총체 점검 재설계 계획.md`, `reddit 스킬 4프레임 점검 재설계 계획.md`, `threads 스킬 총체 점검 재설계 계획.md`, `twitter 스킬 총체 점검 재설계 계획.md`)는 skill-maker v0.2.0(`3f946f7`, `## Code the skill bundles`)보다 먼저 만들어졌다. v0.2.0은 스킬 디렉터리 트리를 `--help`보다 먼저 읽히는 인터페이스로 본다. 그래서 모든 스킬이 같은 틀을 갖는다: `scripts/cli.py` 하나 + `scripts/<스킬명>/` 패키지 하나, 기능·외부 시스템·저장소 기준 하위 패키지, `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"` + PEP 723, 스킬 밖 구조 테스트.

**산출물은 4개 계획 파일의 개정이다.** 다음 세션이 이 계획대로 4개 파일을 고치고, 이후 세션들이 각 계획으로 스킬을 구현한다. 개정은 외과적이다. 구조 관례가 닿는 절만 고치고, 전제가 바뀐 결정은 이 세션의 재합의(M1–M13)로 바꾸며, 나머지 합의(결함 목록·성진 결정·검증 설계·SKILL.md 섹션 구조)는 보존한다. 새 skill-maker에서 바뀐 것은 코드 구조 절 하나뿐이고 네 프레임은 그대로이기 때문이다.

## 장부

### 사실 (실측, 2026-09-25~26)
- skill-maker 변경은 `3f946f7` 하나다: `## Code the skill bundles` 신설 + 완료 조건 한 줄(새 코드와 합의된 이행 코드는 구조 테스트 통과).
- 8개 스킬 어느 것도 새 레이아웃을 따르지 않는다. 4개 계획의 목표 트리도 전부 어긋난다(충돌표).
- `more:`는 4개 스킬 모두 `shlex.join`으로 만든다(`facebook.py:149`, `reddit/_cmds_common.py:26`, `threads/_cmds_common.py:37`, `twitter/_browse.py:34`). 그래서 공백 경로("Agentic SNS")에 작은따옴표가 붙는다. 실측(`claude -p --safe-mode --restricted --model haiku`, `--allowedTools 'Bash(uv run "<p>" *)'`): 큰따옴표 호출은 거절 0, 작은따옴표 호출은 거절 1. 즉 지금의 `more:`는 allowed-tools 사전 승인에 맞지 않는다.
- 소비자 쪽 영향: 테스트가 `shlex.split(more)[2:]`로 접두 두 토큰을 떼어 낸다(`tests/facebook/test_cli.py:72,109,181,283,357,376`, `tests/reddit/test_cli.py:55,72,138`, `tests/reddit/live/test_live.py:34,65,68`, `tests/twitter/live/test_live.py:44,49`). `uv run "<p>"`는 세 토큰이다.
- 셸 인용: 경로를 큰따옴표로만 감싸면 `$`·백틱·`"`·`\`가 해석된다(코덱스 실측: `$LAYOUT_REVIEW`가 확장됨).
- `uv run "<p>/scripts/cli.py"`(PEP 723, `requires-python >=3.11`, 의존성 없음)는 같은 격리 하네스에서 동작한다(uv 0.8.0, Python 3.13.5 선택).
- 테스트 패키지 충돌: `tests/{reddit,threads,twitter}/__init__.py` 때문에 pytest(prepend)가 `tests/`를 경로에 넣고, 테스트 폴더를 최상위 패키지 `twitter` 등으로 등록한다. 그러면 스킬 패키지가 가려진다(스크래치 재현, prepend·importlib 모드 모두).
- 해법 비교(레포 사본 실측): `--import-mode=importlib`을 전역으로 켜면 offline 1023·sec 182는 통과하지만, yfinance·finviz가 **수집 단계에서 오류**를 낸다(`from conftest import`, `from pages import` 의존). 반면 빈 `tests/__init__.py` 하나를 추가하고 prepend를 유지하면 offline 전부·sec 182·yfinance 352·finviz 147이 통과하고, 스킬 패키지 `twitter` import도 확인된다. `tests/` 전체의 중복 basename은 19개다.
- 미이행 스킬의 테스트에는 경로 조작이 남는다(`tests/sec/conftest.py:4` `sys.path.insert`, `tests/naver_blog/conftest.py:14` `spec_from_file_location`).
- root `--help` 종료 코드표: reddit·threads·twitter에는 있고 **facebook에는 없다**.
- 네 스킬의 `_aside.py:11,14-22`가 자기 옆 `browser/`에서 이름으로 JS를 읽어 ARGS와 결합한다.
- 현재 진입점들은 사이트 대상 파서를 직접 import한다(`facebook.py:96 → _resolve`, `reddit.py:17 → _target`, `threads.py:18 → _target`, `twitter.py:18-19 → _entities.timestamp·_target.parse`).
- 옛 진입점을 인용하는 곳: `README.md:10,69`, `docs/usage.md:10-12,93-96,102-103,133`, 각 `SKILL.md`의 allowed-tools·첫 문단, `tests/<s>/test_cli.py`와 facebook·threads·twitter `live/test_live.py`의 `CLI`(reddit live는 진입점의 parser/validate를 import하고 `live/conftest.py:11-27`이 pytest 프로세스의 `_transport.run_snippet`을 패치한다), `tests/<s>/js/*.js`의 `scripts/browser`. CI(`.github/workflows/test.yml`)의 ruff·node·PII 실행 경로는 그대로다.
- CI offline 잡은 Python 3.12 + pip pytest이고 uv가 없다.
- 계획 파일은 구현 PR이 커밋한다(`.claude/plans/` 추적 파일은 각 구현 PR로 들어갔다). 개정 대상 4개는 아직 추적되지 않는다.

### 계획별 충돌표
| 관례 | facebook | reddit | threads | twitter |
|---|---|---|---|---|
| 진입점 `cli.py` | `facebook.py` | `reddit.py` | `threads.py` | `twitter.py` |
| 최상위 이름 둘 | 패키지 5개 | 폴더 5개 + 무파일 부트스트랩 | 폴더 5개 | `twitter_skill/` + `browser/` + `registry.json` |
| `uv run` + PEP 723 | `python3` | `python3` + 3.11 검사 코드(I2) | `python3` | `python3` |
| cli.py = 표면 전부 | `COMMANDS`는 진입점 ✓, 종료 코드는 `reading/outcome.py` 소유, epilog에 표 없음 | `cli/` 폴더 | `cli/` 폴더 | `surfaces.py`·`cli.py`가 패키지 안 |
| 하위 패키지 기준 | queries·records 둘 다 Facebook 소유인데 둘로 갈라짐 | 계층(cli/read/model/net/store) | meta=시스템 ✓, 나머지 계층 | protocol·reading 둘 다 X 소유인데 둘로 갈라짐 |
| 레이아웃 구조 테스트 | `test_layout.py` | "쓰지 않는다" | `test_layers.py`(+ 오퍼레이션 리터럴 단일 원천 검사) | 없음(명령 선언 단일 원천을 보는 일회성 AST만) |
| 테스트의 경로 | conftest 삽입 | conftest 부트스트랩 | 서브프로세스 전용(결정 7), `helpers.call`이 sys.path 조작 | conftest 삽입 |
| Codex 호스트 | 절대경로 원리 | `$RD` 줄 | `${CLAUDE_SKILL_DIR}` + 절대경로 | 전용(결정 6) |

### 성진 결정 (이 세션)
- M1. 4개 모두 새 레이아웃으로 이행한다.
- M2. 외과적 개정 + 전제가 바뀐 결정만 재합의한다.
- M3. Claude Code 전용이다. 호출은 관례 형태만 쓰고, Codex용 문장은 지운다.
- M4. 틀은 같게, 내용은 스킬별로 둔다. 틀은 트리 뼈대·진입점·호출 형태·구조 테스트·테스트 import 방식이고, 내용은 명령·기능 폴더·출력·SKILL.md다. 각 계획의 "형제 유사성은 기준이 아니다"를 이 범위로 좁혀 고친다.
- M5. 테스트 import: 빈 `tests/__init__.py` 하나 + pyproject `pythonpath`에 이행한 스킬의 `scripts/`를 넣는다. import 모드는 prepend를 유지한다. 처음 고른 importlib은 yfinance·finviz가 깨진다는 실측으로 재합의했다. threads 결정 7(서브프로세스 전용)은 전제(최상위 이름 충돌)가 사라졌으므로 "순수 계약은 in-process import"로 바뀐다.
- M6. 구조 테스트는 레포 공통 `tests/test_skill_layout.py` 하나다. 먼저 구현하는 계획이 만들고, 나머지는 항목만 추가한다.
- M7. 모듈 하나짜리 기능·저장소는 패키지 바로 아래 파일로 둔다. 폴더는 모듈이 둘 이상이거나 외부 시스템일 때만 만든다(외부 시스템은 항상 폴더).
- M8. 사이트 쪽 시스템 폴더 이름은 사이트가 제공하는 인터페이스 이름으로 짓는다: `graphql/`(facebook·twitter·threads), `json_api/`(reddit). 그 사이트가 소유한 다른 형식(URL·HTML 토큰·번들 채굴)도 이 폴더에 둔다.
- M9. 이행은 각 계획의 기존 "행동 불변 재배치" PR에 합친다(facebook PR①, reddit 단계 2, threads PR②, twitter PR①).
- M10. reddit I2(3.11 검사 코드)를 삭제한다. PEP 723 `requires-python`이 이 요구를 소유한다. POSIX 선언 구절은 유지한다.
- M11. 명령 선언은 cli.py에 명령당 하나다. 도메인 함수(operation·prepare 등)는 패키지 기능 모듈에 구현하고 선언이 참조한다. twitter 결정 5를 유지하고, facebook·threads에도 같은 규칙을 적용한다.

- M12. twitter `graphql/` 안에 `protocol/`(선)·`responses/`(응답 모양)을 둔다. 결정 7의 구분을 시스템 폴더 안에서 유지한다.
- M13. facebook·reddit·threads 목표 트리는 아래 초안 방향으로 확정한다. 모듈·함수 단위는 다음 세션 단계 1에서 정한다. reddit 계층 폴더 결정은 이 트리로 대체된다.

### Claude가 정한 것 (성진 수용, 2026-09-26)
- 대상 URL·식별자 해석(사이트 형식)은 cli.py가 아니라 기능의 준비 함수가 한다. cli.py는 옵션·조합의 문법 검증만 한다. 해석 실패는 여전히 요청 전 exit 2다. 사이트와 무관한 순수 변환(날짜 파싱)만 공용으로 뺀다. 사이트 파서를 공용으로 재분류해 규칙을 우회하지 않는다.
- 사이트 시스템이 자기 스니펫을 읽어 Aside 실행기(`aside/`)에 소스를 넘긴다. Aside의 봉투 프로토콜(threads `envelope.js`)은 `aside/`가 소유한다. 스니펫 이름 검증·누락 오류·fake의 스니펫 식별 계약은 이동 시 보존 대상이다.
- reddit live 테스트는 pytest 프로세스 패치를 버린다. 대신 CLI 서브프로세스 + Aside 래퍼(`REDDIT_ASIDE_BIN`)가 누적 30요청을 자식 프로세스 경계에서 센다(facebook 장부 래퍼·threads `live_bridge`·twitter `guard_aside`와 같은 모양).
- 다음 세션은 계획 파일을 커밋하지 않는다. 각 구현 PR이 자기 계획 파일을 커밋하는 기존 흐름을 따른다.

## 공통 기반 (4개 계획에 같은 블록으로 들어간다)

1. **트리 뼈대.**
   ```
   .claude/skills/<s>/
   ├── SKILL.md
   └── scripts/
       ├── cli.py          # PEP 723 헤더 + 명령 표면 전부
       └── <s>/            # 유일한 패키지 (__init__.py 비어 있음)
           ├── aside/      # 시스템: Aside CLI — repl 스폰·봉투·조각 회수(+ 봉투의 브라우저 쪽 JS)
           ├── <iface>/    # 시스템: 사이트 — graphql/ | json_api/ (레지스트리·토큰·스니펫·응답→레코드·URL 형식)
           ├── <기능>      # 모듈 또는 폴더 (M7)
           ├── <저장소>    # 모듈 또는 폴더 (M7)
           └── <공용>.py   # 공용 어휘: errors 등
   ```
   비파이썬 자산(`registry.json`, `*.js`)은 그것을 소유한 시스템 폴더 안에 두고 `Path(__file__)`로 찾는다.
2. **`cli.py` 계약.** PEP 723 헤더에 `requires-python = ">=3.11"`, `dependencies = []`를 둔다. 담당: 명령 선언(M11) → argparse(모든 인자의 help, 닫힌 집합은 choices, epilog의 **종료 코드표**), 옵션·조합 검증, 디스패치, emit, 결과 → 종료 코드 매핑, `more:`/`resume:` 직렬화. stdout에는 모델이 쓸 결과만 싣는다(텍스트 기본, `--json`이면 JSON 한 문서, 싼 신호 먼저 + 비싼 상세는 핸들). stderr에는 진행·진단을 싣는다. 0은 성공, 2는 잘못된 인자이고, 나머지 코드는 epilog가 정의한다. 종료 코드표는 cli.py의 한 선언에서 help와 schema로 전달한다(두 사본을 만들지 않고, 패키지 → cli 역방향 import도 만들지 않는다).
3. **호출 형태.** SKILL.md 프론트매터는 `allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)`이고, 첫 문단의 호출문도 같은 형태다. `more:`/`resume:`은 `uv run "<호출된 cli.py 절대경로>" <명령> …`으로 쓴다. 경로는 resolve하지 않고(링크 철자 보존), 큰따옴표 안에서 `\ " $ \``를 escape한다. 나머지 인자만 `shlex.join`한다. 이렇게 하면 allowed-tools 패턴과 글자 그대로 맞는다.
4. **import 방향**(구조 테스트가 강제한다). 패키지의 최상위 하위 이름은 각각 기능·시스템·저장소·공용 중 하나다.
   - 공용은 다른 공용만 import한다.
   - 시스템·저장소는 공용·시스템·저장소를 import할 수 있고, 기능은 import하지 않는다.
   - 기능은 시스템·저장소·공용을 import할 수 있고, 다른 기능은 import하지 않는다. 기능은 나머지를 건드리지 않고 바뀌거나 사라질 수 있어야 하기 때문이다.
   - `cli.py`는 기능·공용만 import하고, 패키지는 `cli`를 import하지 않는다.
   - 모듈 단위 순환은 없다.
5. **공통 구조 테스트 `tests/test_skill_layout.py`.** 이행한 스킬마다 선언 한 항목(`{패키지: {최상위 하위 이름: 분류}}`)을 둔다. **검사 범위는 등록된 스킬의 `scripts/`와 `tests/<s>/`, 그리고 이 파일 자신이다.** 미이행 스킬은 범위 밖이다(skill-maker: 합의 전 레거시엔 비적용). 검사 항목:
   - `scripts/`의 항목이 `cli.py`와 패키지 둘뿐이다(`__pycache__`는 무시).
   - 패키지 이름이 `sys.stdlib_module_names`에 없다.
   - 모든 최상위 하위 이름이 선언돼 있다.
   - 위 import 방향을 지키고 순환이 없다(AST).
   - 범위 안에 `sys.path` 변경·`site.addsitedir`·`spec_from_file_location`이 없다.
   - 범위 안 테스트가 `cli`를 import하지 않는다.
   - `cli.py` PEP 723 블록을 실제로 파싱해 `requires-python`·`dependencies`가 있다.
   - SKILL.md allowed-tools가 호출 형태와 일치한다.

   파일이 없으면 이 규칙으로 만든다. 있으면 그 파일이 규칙의 원천이고, 항목만 추가한다. 스킬 고유의 단일 원천 검사(threads 오퍼레이션 리터럴, twitter 명령명 분기, facebook records seam 제한)는 이 테스트로 대체하지 않고 스킬 테스트에 남긴다.
6. **테스트 기계.** 빈 `tests/__init__.py`가 없으면 만든다(M5). pyproject `pythonpath`에는 이행하는 스킬의 `scripts/`를 추가한다. 테스트는 CLI를 `[sys.executable, CLI]`로 부른다(CI에 uv가 없다). `more:`/`resume:` 소비자(위 사실의 `shlex.split(...)[2:]` 전부, 골든 도구, 캡처한 `more:`를 실행하는 곳)는 먼저 접두가 `['uv','run',CLI]`인지 단언한 뒤 나머지 인자를 `[sys.executable, CLI]`로 실행한다. 실제 `uv run`은 이동성 검증이 확인한다: 공백·한국어가 든 레포 밖 사본을 무관한 cwd에서 실행하고, 인용이 까다로운 경로(`$`·따옴표 포함)에서 출력된 `more:`를 셸로 실행한다.
7. **이행 PR의 경계(M9).** 그 PR에서 함께 바뀌는 것:
   - 진입점과 호출 형태, `more:` 접두(따옴표 결함 수정 포함)와 소비자
   - SKILL.md 프론트매터와 호출문(섹션 구조·나머지 문안은 불변)
   - README/docs의 해당 스킬 문장(경로가 거짓이 되므로 이 PR에서 고친다)
   - 테스트의 CLI·JS 경로, pyproject, `tests/__init__.py`, 구조 테스트 항목

   **전환 시점**: 기존 테스트 부트스트랩(conftest의 sys.path 삽입·패키지 합성) 제거, M5 설정, 테스트 import 경로 전환, 구조 테스트 등록은 `scripts/<s>/` 패키지를 실제로 만드는 단계에서 한꺼번에 한다. 그보다 앞선 seam 이관·골든 캡처 단계는 기존 부트스트랩을 유지한다(threads 단계 6 → 7, twitter 단계 1 → 2, reddit 단계 1 → 2, facebook 단계 2).

   계획의 "행동 불변"은 "승인된 호출·help 변경을 뺀 행동 보존"으로 한정해 적는다. 골든 비교가 허용하는 차이는 셋뿐이다: `more:`/`resume:` 접두, argparse `prog`(`usage: cli.py`), facebook root epilog의 종료 코드표 신설. 앞의 둘은 별도 테스트가 단언한다(접두 = allowed-tools 형태, 표 = cli.py 선언). 완료 명령에 `python3 -m pytest tests/test_skill_layout.py`를 넣는다.
8. **시나리오 하네스.** 각 계획의 하네스가 실제로 주입하는 호출문·허용 패턴을 그 자리에서 고친다. twitter는 `Bash(python3 "<복사본>/scripts/twitter.py" *)`를 `Bash(uv run "<복사본>/scripts/cli.py" *)`로 바꾼다. facebook·reddit·threads는 `--allowedTools Bash` 기반이나 스킬 발견 방식이므로 주입하는 호출문과 CLI 경로만 고친다. 문자열 일괄 치환만으로 개정됐다고 판정하지 않는다.

## 스킬별 목표 트리 (다음 세션이 모듈·함수마다 실제 import를 AST로 확인해 확정)

### facebook
```
scripts/
├── cli.py              # ← facebook.py: COMMANDS 선언→argparse·epilog(종료 코드표 신설), 검증, 디스패치, emit, 결과→종료 코드, more:
└── facebook/
    ├── errors.py       # 공용 ← _errors
    ├── outcome.py      # 공용: STOP_REASONS·결과 봉투·커버리지 진리표·원인별 fix (종료 코드 번호는 cli.py)
    ├── aside/          # 시스템 ← _aside (소스를 받아 실행; 스니펫 선택은 graphql)
    ├── graphql/        # 시스템: Facebook 웹 GraphQL
    │   ├── session.py  registry.py  registry.json  resolve.py  refresh.py  transport.py
    │   ├── snippets/*.js      # ← browser/ (첫 줄 `// facebook-snippet: <name>`)
    │   └── records/           # 공개 API(seam ②) — posts_from_raw(← _cmds_posts) 포함
    ├── account.py      # 저장소: 차단·간격·계정 락·원자 저장 ← _blocked
    ├── cursors.py      # 저장소 ← _output.CursorStore
    ├── collect.py      # 저장소: --out ← _output.OutFile
    ├── reading/        # 기능: paging·posts·comments·search·about·maintenance(doctor·refresh·schema)
    └── render.py       # 기능 ← _render
```
`graphql.refresh`가 `reading.posts`를 부르던 역방향(`_refresh.py:14`)은 `posts_from_raw`를 records로 옮겨 없앤다.

### reddit
```
scripts/
├── cli.py              # ← reddit.py + 명령 표면 + more:/resume:·emit
└── reddit/
    ├── errors.py       # 공용 ← _errors (scrub·diagnostic 삭제)
    ├── files.py        # 공용: 안전 열기(seam 5, F8)·원자 교체·잠금·슬롯 루트 경로
    ├── aside/          # 시스템 ← _aside
    ├── json_api/       # 시스템: reddit.com JSON — target.py(seam 2, target_dict 포함)·things.py·transport.py·snippets/fetch.js
    ├── budget.py       # 저장소: 공유 예산·페이싱·차단
    ├── cache.py        # 저장소: 스레드 상태·커서·식별 + TTL·용량 정책
    ├── collect.py      # 저장소: --out 레코드 NDJSON + .state
    ├── reading/        # 기능: listing.py·thread.py(seam 3, 순수)·flows.py(← _cmds_* 접착층)
    └── render.py       # 기능: 요약 줄·항목·본문 정규화
```
`_thread.target_dict`(`_thread.py:22-25`)는 json_api/target.py로 옮겨 reading과 cache가 함께 쓴다.

### threads
```
scripts/
├── cli.py              # ← threads.py + cli/commands
└── threads/
    ├── model.py  errors.py    # 공용 ← domain/model·errors
    ├── aside/          # 시스템 ← _aside + envelope.js
    ├── graphql/        # 시스템 ← 계획의 meta/*(operations·registry·registry.json·session·ssr·decode·normalize·transport·refresh·capture·snippets/) + target
    ├── guard/          # 저장소: budget·blocked·state
    ├── store.py        # 저장소: --out·커서 핸들
    ├── reading/        # 기능: listing·post·profile·collect·window·maintenance(doctor·refresh 조립)
    └── output/         # 기능: render·schema
```
`_refresh.py:7 → _cmds_common.finish` 역방향은 refresh가 시스템 결과만 반환하고 `reading/maintenance.py`가 봉투를 완성하게 해서 없앤다. `_cmds_common`(context·finish·profile_from_route·check_access)과 `_cmds_meta`의 목적지는 다음 세션이 함수 단위로 적는다.

### twitter
```
scripts/
├── cli.py              # ← surfaces.py의 표면(인자·명령별 help·금지 조합+fix·행 종류·도메인 함수 참조) + cli.py
└── twitter/
    ├── errors.py  dates.py    # 공용 (dates: ← _entities.timestamp 순수 부분)
    ├── aside/          # 시스템 ← _aside
    ├── graphql/        # 시스템: X 웹 GraphQL
    │   ├── protocol/   # 선: session(viewer 대조 포함)·registry(+registry.json)·transport·signature(S2, MIT 고지)·refresh·snippets/*.js
    │   └── responses/  # 응답 모양: targets·timeline·records·thread·pages
    ├── account/        # 저장소: state.py(차단·락·원자 쓰기)·budget.py(S3)
    ├── continuation.py # 저장소: 무작위 핸들·24h 만료
    ├── export.py       # 저장소: --out
    ├── browse/         # 기능: operations(명령별 operation·prepare·fetch)·pagination·조립·maintenance(doctor·refresh 조립)
    └── output/         # 기능: render·schema·doctor 요약
```
doctor를 `session.py`에 합치면 session → transport → session 순환이 생긴다(`_cmds_meta.py:4,12`, `_transport.py:95`). 그래서 viewer 대조만 session에 두고 조립은 `browse/maintenance.py`에 둔다. 명령명 분기 금지 검사는 "cli.py 밖에 명령명 분기 0"으로 좁혀 twitter 테스트에 커밋한다.

## 계획별 개정 목록 (다음 세션의 체크리스트; 줄 번호는 개정 전 기준)

공통: 각 계획의 `## 최종 스킬 디렉터리 구조`를 위 트리로 바꾸고, 공통 기반 블록을 새 절로 넣는다(`## 공통 구조 기반`). 이 계획의 M1–M13을 각 계획의 결정 장부에 "(2026-09-26 개정)"으로 추가하고, 대체된 옛 결정은 지우지 않고 "→ M?로 대체"라고 표시한다. 옛 코덱스 리뷰 기록은 남긴다. SKILL.md 섹션 구조는 첫 문단 호출문과 프론트매터만 바꾸고 나머지는 보존한다. `references/`를 두지 않는다는 결정도 유지한다.

- **facebook**
  - `:7` 실행 호스트
  - `:47-52` 결정 2·3·6·7 → M4·트리·M5
  - `:62` Codex 경로 원리 → M3
  - `:75` 종료 코드 소유권 → cli.py
  - `:81-128` 트리·import 규칙·모듈 DAG·`__init__`·자산 기준점 → 공통 기반 4·5
  - `:132-147` conftest(sys.path 삭제)·JS 경로·seam·`test_layout.py` → 공통 구조 테스트 + records seam 제한 검사 유지
  - `:150-166` records API 경로(`facebook.graphql.records`), `posts_from_raw` 귀속
  - `:168-188` COMMANDS가 핸들러를 참조(M11), 대상 해석은 reading 준비 함수로
  - `:197·245` outcome 소유권과 AST 예외 경로
  - `:278` `schema result`의 종료 코드표를 cli.py 선언에서 전달
  - `:305·309` allowed-tools·첫 문단
  - `:339-341` 단계 1·2 골든 허용 차이(공통 7)·재배치 판정·구조 테스트 명령
  - `:349·354` outcome·schema 선언 대조
  - `:355` 문서 갱신 시점을 PR①로
  - `:381-382` 이동성(`uv run`)·시나리오 호출
- **reddit**
  - `:68·74` 결정(계층 폴더·`reddit.py`만 최상위) → M1·M4·트리
  - `:106-184` 트리·의존 방향·"구조 테스트를 쓰지 않는다"·매핑표·무파일 부트스트랩·conftest → 공통 기반
  - `:212` F8 seam 경로
  - `:220` I2와 `:368` 해소 행렬 A11 → M10
  - `:234·239` allowed-tools·`$RD` 줄 → M3
  - `:257-266` seam 경로(`reddit.json_api.target`, `reddit.reading.thread`, `reddit.files`)
  - `:295-304` 단계 2 판정(`ls scripts`, grep 방향 검사 → 구조 테스트)
  - `:315·324` 하네스
  - `:333-342` live를 CLI 서브프로세스 + Aside 래퍼 가드로, 문서
  - `:404` 계층 폴더 위험 문장 삭제
  - `:414` 부트스트랩 기록에 "대체됨" 표시
- **threads**
  - `:7·16` 설명(`scripts/` 재배치 문장)
  - `:27` "경로 불변" 주장 → 워크플로 실행 경로에 한정
  - `:52·57-59` 결정 1·6·7·8 → M4·트리·M5(결정 8의 PR 셋은 유지)
  - `:81` 명령 선언 위치 → cli.py
  - `:85-139` 트리·import 방향·`helpers.call`(sys.path 조작) 삭제 → 순수 계약은 in-process
  - `:146-157` 테스트 트리: `test_layers.py`의 import 검사는 공통 구조 테스트로, 오퍼레이션 리터럴 검사는 `test_catalogue.py`로 남김, JS 경로 `graphql/snippets`·`aside/`, `live_bridge` 유지
  - `:213·217` allowed-tools·첫 문단
  - `:277-279` 단계 6–8: 단계 6은 기존 importlib 합성을 유지한 채 seam 이관·골든을 끝낸다. 부트스트랩 제거·`helpers.call` 삭제·in-process 전환·M5 설정·구조 테스트 등록은 `scripts/threads/`를 만드는 단계 7로 옮긴다(공통 7 전환 시점). 골든 허용 차이·재배치 판정도 고친다
  - `:286` 단계 10(명령 선언이 cli.py)
  - `:293` 문서 시점을 PR②로
  - `:309-312` 골든·이동성·하네스
  - `:321` CI 불변은 워크플로 실행 경로에 한정
- **twitter**
  - `:3` 첫 동작 문장
  - `:41·47·50·59` 결정 1·7·10·19 → M4·트리(protocol·reading을 `graphql/` 아래 둘로)·문서는 PR①에서·M1
  - `:66` 포매터 판단 유지
  - `:68-69` doctor·records 위치 → 위 트리
  - `:88-129` 트리·자산 경로 상수(`twitter_skill/__init__` 삭제, 시스템 폴더가 `Path(__file__)`로)·삭제 목록
  - `:131-149` conftest(sys.path 삽입 삭제)·seam 경로(S2 `twitter.graphql.protocol.signature`, S3 `twitter.account.budget`)
  - `:152-171` `Surface` 선언은 cli.py(M11), 구조 판정을 "cli.py 밖 명령명 분기 0" 커밋 테스트로
  - `:214·218` 호출
  - `:254-262` 골든(소비자 접두 처리)·이동·선언 판정
  - `:275` `more:` 검증(`uv run` 접두)
  - `:283-285` 시나리오 주입
  - `:291·299` 문서 시점·검증 명령

## 다음 세션 작업 단계

파일을 바꾸는 단계가 셋 이상이다. 그래서 먼저 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커 스키마를 불러오고 단계마다 `TaskCreate`를 한다. description에는 아래 완료 판정을 그대로 적는다.

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | 이 파일을 정식 이름으로 옮긴다(이미 옮겼으면 생략). 트래커를 등록한다 | 파일 존재, 트래커 5단계 |
| 1 | **트리 확정 조사**. 네 스킬의 모든 모듈에 대해 현재 import와 각 계획이 추가하는 의존을 AST로 뽑고, 위 트리의 분류로 방향 규칙 위반 간선을 찾는다. 위반은 가장 작은 재배치(함수 이동)로 해소하고, threads `_cmds_common`·`_cmds_meta`, facebook `_cmds_*`, reddit `_cmds_*`, twitter `_cmds_*`·`_browse`는 함수 단위 목적지를 적는다. 조사 스크립트는 스크래치에 두고 커밋하지 않는다 | 스킬별 "옛 모듈/함수 → 새 위치" 표, 그 표를 적용한 가상 그래프에서 위반 간선 0·순환 0 |
| 2 | **4개 계획 개정**. 위 체크리스트를 한 계획씩 적용한다. 새 절 `## 공통 구조 기반`(공통 기반 1–8, 네 계획에서 같은 문장), 개정된 `## 최종 스킬 디렉터리 구조`(단계 1의 표 반영, 트리 + import 방향 + tests 트리), 결정 장부의 M1–M13과 대체 표시, SKILL.md 섹션 구조의 프론트매터·호출문, 작업 단계의 완료 판정·검증 명령을 고친다. 줄바꿈은 성진 규칙(의미 단위 한 줄)을 따른다 | 체크리스트 모든 항목이 반영됐다. `grep -n "python3 \".*\(facebook\|reddit\|threads\|twitter\)\.py\|twitter_skill\|reddit_skill\|helpers.call\|sys.path.insert"`가 "대체됨" 표시 줄 말고는 0이다. 네 계획의 공통 블록이 `diff`로 동일하다 |
| 3 | **코덱스 리뷰**(`codex` 스킬, `gpt-6-astra` medium, read-only, 이 계획 세션의 리뷰 스레드 `01a0d922-d490-7ec2-b899-ae44d8e30d7a`를 resume). 입력은 개정된 4개 계획, skill-maker SKILL.md, 이 계획이다. 닫힌 술어로 묻는다: "(a) 각 계획을 그대로 구현했을 때 새 관례(Code the skill bundles)나 공통 기반을 어기는 지점, (b) 개정이 보존해야 할 기존 합의를 잃은 지점, (c) 네 프레임 기준으로 계획이 스킬을 나쁘게 만드는 지점 — file:line 근거가 있는 것만". `--schema` 응답을 받는다 | 최신 라운드의 blocking·major가 0이다. 반영하지 않은 지적은 이유를 계획의 코덱스 리뷰 기록에 남긴다. M1–M13과 충돌하는 지적은 AskUserQuestion으로 성진에게 올린다 |
| 4 | **성진 승인**. 계획마다 바뀐 절의 요약(무엇이 왜 바뀌었나, 대체된 결정)을 AskUserQuestion `preview`로 보인다 | 네 계획 각각 명시적 승인. 부분 승인·침묵은 승인으로 치지 않는다 |
| 5 | 이 파일 끝에 `# 개정 기록`을 쓴다: 단계 1의 이동표 요지, 코덱스 run id와 반영 내역, 승인 일자 | 기록 존재. 커밋은 하지 않는다(각 구현 PR이 자기 계획을 커밋한다) |

## 검증 (이 계획 세션에서 이미 한 것과 다음 세션이 할 것)

- 이 세션: `more:` 따옴표와 allowed-tools 매칭(`claude -p` 두 런), `uv run` 격리 하네스 동작, 테스트 패키지 충돌 재현, importlib 모드 전 스위트(offline 1023·sec 182 통과, yfinance·finviz 수집 오류), `tests/__init__.py` 대안 전 스위트(offline·sec 182·yfinance 352·finviz 147 통과). 코덱스 초안 리뷰(run `20260926-001533-meta-plan-review-17f0`, 17건 — 전부 반영: F01·F06·F10 트리, F02·F03 maintenance 경계, F04 대상 해석 위치, F05 구조 테스트 범위, F07·F17 `more:` 소비자·인용, F08 골든 허용 차이, F09 cli 계약·PEP 723 파싱, F11–F14 체크리스트, F15 충돌표 사실, F16 하네스). 재검증(같은 스레드, run `20260926-002158-meta-plan-review2-7377`): 16 RESOLVED, F13 PARTIAL(threads 부트스트랩 제거 시점) → 공통 7 "전환 시점"과 threads 체크리스트로 반영.
- 다음 세션: 단계 1의 가상 그래프 위반 0, 단계 2의 grep·diff 판정, 단계 3의 코덱스 blocking·major 0, 단계 4의 승인.
- 구현 세션(개정된 계획이 요구): 각 이행 PR의 `python3 -m pytest tests/test_skill_layout.py`, 스킬 스위트, 골든 동일(허용 차이 셋 제외), 이동성(`uv run`, 공백·한국어·까다로운 인용 경로), `claude plugin validate --strict .claude/skills` exit 0.

## 하지 않는 것
- 미이행 스킬(sec·finviz·yfinance·naver-blog)의 구조 변경이나 그 테스트 수정.
- 4개 계획의 비구조 결정(결함 수정·인터페이스 변경·SKILL.md 판단 문안) 재검토.
- 계획 파일 커밋(구현 PR의 몫), 스킬 코드 변경(구현 세션의 몫).

# 개정 기록 (2026-09-26, 같은 세션에서 수행)

- **단계 1 트리 확정 조사.** 네 스킬의 함수 단위 의존을 AST로 뽑아 목표 트리의 분류로 가상 이동했다(조사 스크립트는 스크래치, 커밋 안 함). 남은 위반은 네 범주로 수렴했고, 각각 규칙으로 해소해 계획의 `## 최종 스킬 디렉터리 구조`에 "이동으로 풀리는 역방향"으로 적었다.
  - ① 기능 → cli: `more:`·문맥 조립(네 스킬 모두). 해소: cli가 질의 신원을 계산해 넘기고, 기능은 핸들을 돌려준다.
  - ② 기능 → 기능: `schema` 명령(threads·twitter). 해소: cli가 output으로 바로 디스패치한다.
  - ③ cli → 시스템: 대상 파서(네 스킬 모두). 해소: 기능의 준비 단계로 옮긴다.
  - ④ 스킬별:
    - facebook: 진입점 배선 → `reading/dispatch.py`, `posts_from_raw`·`fetch_post_story` → records(refresh 역방향과 posts↔people 순환 해소), emit → cli.
    - reddit: `target_dict` → `json_api/target`, 시각 표시 → render.
    - threads: refresh → finish 역방향 해소, transport↔capture 순환 제거.
    - twitter: doctor 조립 → `browse/maintenance`, `timestamp` → `dates.py`.
- **단계 2 개정.** 체크리스트 전 항목을 반영했다.
  - 네 계획의 `## 공통 구조 기반`은 md5가 같다(`7c24a8c8…`).
  - 옛 경로 grep에 걸리는 줄은 현행 사실·삭제 지시·"대체됨" 표시뿐이다.
  - 체크리스트 밖 추가 발견: `tests/twitter/fake_aside/aside:8`의 `sys.path.insert` → twitter 단계 2에서 `runpy.run_path`로 교체.
  - 개정 전 사본은 세션 스크래치에만 있다.
- **단계 3 코덱스 리뷰**(스레드 `01a0d922-d490-7ec2-b899-ae44d8e30d7a`):
  - `20260926-003853-plans-review-8a6e`: major 2건, 둘 다 반영.
    - facebook 단계 2가 `test_registry.py:7` 부트스트랩을 남김.
    - reddit 단계 2 판정이 "import 외 수정 없음"이라 새 접두 처리와 충돌.
  - `20260926-004253-plans-review2-75a5`: 2건 RESOLVED, 새 major 1건 반영(facebook 원본 수집 스크립트의 옛 import 경로 → `facebook.graphql.transport` + PYTHONPATH 실행).
  - `20260926-004407-plans-review3-adde`: RESOLVED, blocking·major 0.
- **단계 4 승인.** 성진이 네 계획 각각을 명시적으로 승인했다(2026-09-26).
- 커밋 없음: 각 구현 PR이 자기 계획 파일과 이 파일을 커밋한다. 이 레포에서 먼저 구현되는 계획이 `tests/__init__.py`·`tests/test_skill_layout.py`·pyproject `pythonpath`를 만든다.
