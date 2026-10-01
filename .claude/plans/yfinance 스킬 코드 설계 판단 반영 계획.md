# yfinance 스킬 코드 설계 판단 반영 계획

> 계획 세션 2026-10-01. **첫 동작**: 승인 직후 이 파일을 `.claude/plans/yfinance 스킬 코드 설계 판단 반영 계획.md`로 `mv`한다(계획 모드는 지정 경로만 쓸 수 있고 ExitPlanMode가 그 경로를 읽어서, 승인 전에는 옮기지 않는다). 구현 세션은 시작하자마자 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커를 불러 `## 작업 단계`의 단계마다 `TaskCreate`하고(description에 완료 판정을 그대로), 단계마다 `TaskUpdate`로 옮긴다. 코드·테스트를 쓰기 전에 `coding` 스킬을, 리뷰는 `codex` 스킬을 연다. 작업 트리의 무관한 변경(`.claude/harness-spec.md` 삭제, `.ultra-search/`)은 커밋에 섞지 않는다.

## Context

`.claude/skills/yfinance`는 Agentic SNS 레포의 읽기 스킬 중 구조화 시장 데이터를 맡는다. 성진의 한국어 투자·시장 질문(PER 추이, MDD, 종목 비교, 스크리닝, 보유자, 실적 일정…)에 Claude가 숙련된 애널리스트처럼 답하게 하는 것이 목적이고, 성공은 다섯 가지다: 조용히 틀리지 않는다(스케일·통화·시각·잘린 창), 막히지 않는다, 컨텍스트와 Yahoo 요청을 아낀다, 계산이 전 행 위에서 된다, 다음 세션이 고치기 쉽다.

이번 변경의 계기는 skill-maker #5(2026-09-29, `5f3e572`)다. 9/26–27의 레이아웃 이행(PR #25·#26)은 #4 관례를 따랐고, #5는 그 위에 코드 설계 판단을 더했다: 명령은 모델이 직접 못 하는 일을 숨길 때만 둔다, `--help`는 두 단계이고 명령별 help가 출력·실패까지 스스로 말한다, 단위는 입구 뒤의 깊은 모듈이다, 시스템 단위는 그 시스템의 말을 스킬의 말로 바꿔 넘긴다, 상태는 스킬의 `data/`에 둔다, 유지보수 코드는 레포의 하는 일 폴더에 둔다.

**결론: 재작성하지 않는다(성진 결정 2). 세 PR로 나눠 구조 → 결함 → 표면 순으로 고친다.**

- PR ① 구조(행동 불변): `yahoo`가 실패·시각·간격 사다리를 스킬의 말로 넘기고, 단위 밖에서 내부로 들어가는 import를 없애고, 구조 테스트가 #5의 단위 규칙을 등록별로 검사한다.
- PR ② 결함: "잘려도 잃지 않는다"는 이 스킬의 핵심 약속을 깨는 major 4건(꼬리 뒤 continuation, 옵션 체인의 이어 읽기·필드 목록·예산 축소)과 작은 정확성 결함들, `market summary --fields`의 이중 의미를 고친다.
- PR ③ 표면·상태: 저장 관측을 `data/observations/`로 옮기고 `--store`를 없앤다. `--help`를 지도 → 그룹 문서의 두 단계로 바꾸고 `schema`와 중복 kind 둘을 없앤다. 모델 시나리오 실행기를 레포에 커밋하고 전후 시나리오로 회귀를 판정한다.

**의도한 결과**

- 모델은 `--help`(지도)와 `<group> --help`(그 그룹의 전부) 두 번 읽고 데이터를 부른다. 지금은 3~4회 읽고 인자 설명을 두 번 받는다.
- 잘린 결과의 continuation을 따라가면 저장본의 어느 행도 건너뛰지 않는다. 옵션 체인과 키 붙은 레코드(`market summary`)도 같다.
- 트리가 상태의 위치(`data/`)와 유지보수 코드의 위치(`scenarios/`)를 말한다.
- `yahoo/` 밖의 코드는 Yahoo의 메시지·epoch·내부 모듈을 모른다. 구조 테스트가 이를 강제한다.

## 장부

### 사실 (2026-10-01 실측·읽기)

- skill-maker 변경 이력(`/Users/seongjin/Coding/Skill Maker`): #4(9/25, 번들 코드 구조 관례) → yfinance 이행 PR #25·#26(9/26–27)의 기준. #5(9/29, `5f3e572`, 계획 `skill-maker-code-design.md`)가 이번 반영 대상이다. #5가 더한 판단(번호는 그 계획의 M번호):
  - M12(4절·5절): 명령은 매번 같게 가거나 모델이 믿을 만하게 못 하는 일을 숨길 때만 둔다. 모델이 직접 쓸 수 있는 조회는 감싸지 않는다 — 읽을 수 있는 스키마를 주고 모델이 쿼리를 쓴다. 근거: 성진의 k-politics 교정 "괜히 코드를 만들면 오히려 클로드가 데이터를 필터링하고 서칭하는데 제약이 생겨."
  - M6: `--help`는 두 단계(최상위 지도 → 명령 하나). 명령별 help가 인자·닫힌 집합·출력·실패를 스스로 말한다. 지도가 한 화면을 넘으면 세 번째 단계가 아니라 명령 수를 줄인다.
  - `cli.py`의 도메인 로직 예시(처리할 항목 고르기·폴백·재시도·결과 의존 후속 호출)는 명령이 부르는 단위의 몫.
  - M18: stdout 손잡이는 그 결과만 가리킨다(다음 호출이 덮어쓰지 않음).
  - M9: 단위(패키지 바로 아래 모듈 또는 하위 패키지)는 입구(그 모듈 또는 `__init__.py`) 뒤의 깊은 모듈. 단위 밖은 테스트를 포함해 입구를 건너뛰지 않는다. 두 번째 바뀔 이유가 생기기 전까지 모듈은 패키지에 바로 있다.
  - M15·M26: system 단위는 그 시스템과 말하는 법(코드·위치·날짜 형식 해석 포함)을 빠짐없이 담고 스킬의 말로 넘긴다. 그걸로 하는 일은 목적 쪽.
  - M13: 기능끼리의 import는 구조 테스트에 적은 간선만.
  - M10: 런타임 상태는 스킬 폴더 `data/`(홈·캐시 디렉터리 아님).
  - M14: 레포 `tests/`는 테스트·픽스처·시뮬레이터, 유지보수자·예약 작업 코드는 레포 루트의 하는 일 이름 폴더. 그 코드는 단위 입구를 import할 수 있고 스킬은 그 코드를 import하지 않는다.
- 현 yfinance(`7d0f382`·`8a5a131` 이후): `scripts/cli.py`(531줄, 49리프·11그룹 선언) + `scripts/yfinance_skill/`(공용 envelope·shape·display·selection·budget·leaf, 시스템 `yahoo/` 14모듈, 저장소 store·export, 기능 `querying/`·`schema`). 패키지 약 127KB. SKILL.md 본문은 호출 한 문단뿐(9/27 제거 시험으로 나머지 삭제, 성진 승인).
- 새 판단 대비 현 상태:
  - `--help`가 세 단계다: 루트(그룹 11 + schema·read) → 그룹(`prices --help`는 리프 목록만) → 리프. 49개 리프 help 모두 출력·종료 코드가 없다(루트 epilog에만, 코덱스 실측). 인자 설명이 `--help`(`prices history` 3,612자)와 `schema GROUP LEAF`(2,584자) 양쪽에 있다. argparse formatter가 기본값(interval `1d`, adjust `auto`, periods `5`)을 출력하지 않는다. `read --timeout`은 받지만 쓰지 않는다(`cli.py:416`).
  - 9/27 시나리오 기록의 실제 발견 경로: `--help` → `<group> --help` / `schema <group>` → `<group> <leaf> --help` → `schema <group> <leaf>` → 데이터 호출. 3~4회, 약 9.6천 자.
  - 시제품 그룹 문서(스크래치 `proto/render.py`, kind·인자 적용 표시·공통 인자·출력·kind별 의미·종료 코드): 그룹당 4.0~7.5천 자(search 4.0 · prices 6.8 · financials 7.5 · screen 7.0 · analysts 6.1).
  - 49리프 대부분이 yfinance 게터 하나를 1:1로 부른다. `analysts summary`는 yfinance 1.7.0 `base.py:220`에서 `get_recommendations()`의 별칭인데 CLI는 다른 데이터처럼 설명한다(별칭은 이것 하나 — `base.py`의 단순 위임 게터 전수 확인). `market sectors`는 `market sector KEY`의 choices와 같은 고정 목록이고, `yfinance.const.SECTOR_INDUSTY_MAPPING_LC`의 키 11개와도 같다(산업 키 145개).
  - 저장 관측 기본 위치가 `$XDG_CACHE_HOME/yfinance-skill`(`store.py:30`). yfinance 라이브러리도 `user_cache_dir()/py-yfinance`에 시간대·쿠키·ISIN 캐시를 쓴다(`cache.py:54`).
  - 저장은 `json.dumps(..., sort_keys=True)`(`store.py:43`)라서 저장본의 매핑 키 순서는 원천 순서가 아니라 정렬 순서다.
  - 입구 건너뛰기: `querying/observe.py:11`이 `yfinance_skill.yahoo.refusals`를 import하고 `:107-114`에서 Yahoo 예외를 분류·처방한다. `yahoo/__init__.bind`가 cli의 `Command`를 받아 `Leaf`를 만든다. `yahoo/info.info_time`은 epoch를 넘기고(저장 레코드에도 숫자로 남는다) 공용 `envelope.as_time`이 출력 때 ISO로 바꾼다. `cli.py:203-215`의 `COARSER`·`coarser_bars`가 다음 간격과 그 의미를 판단한다.
  - `budget.emit(..., item=None)`의 크기 초과 처방(`schema_fix`, `budget.py:244`)은 schema뿐 아니라 최상위 `InputError`·`LocalFailure` 문서(`cli.py:518-527`)에도 쓰인다.
  - `tests/test_skill_layout.py`는 두 최상위 이름·import 방향(기능끼리 전면 금지)·`sys.path`·PEP 723·allowed-tools·본문 호출문만 본다. 단위 입구, 테스트의 입구 건너뛰기, 명명된 기능 간선, 상태 위치, 레포 job 코드는 보지 않는다. "정상 트리" 픽스처가 단위 내부 import를 정상으로 단언한다(`:261,264,294`). 등록 스킬은 facebook·threads·twitter·yfinance.
  - twitter(9/29 이행)도 #5를 다 따르지는 않는다: 상태 `~/.cache/twitter-skill`, 명령별 help에 출력·실패 없음, 하위 패키지 `__init__.py` 0바이트, 모델 시나리오 도구는 `tests/twitter/model/`. 패키지 바로 아래 모듈 단위(`continuation.py` 저장소, `export.py`)는 레포 선례다.
- 이전 라운드의 증거
  - 최초 계획(9/13): "yfinance 객체·메서드를 그대로 노출하지 않고 목적별 인터페이스로", "직접 Python API를 쓰게 하는 초기안을 대체" — 성진이 그때 CLI 방식을 택했다.
  - 9/24 기준선(코덱스, 5/5 정답): mdd에서 모델이 `--max-chars 1000000 > file` 우회로를 스스로 찾음 → `--out` 추가(PR #21). 5건 입력 합계 1.44M 토큰.
  - 9/27 시나리오(Claude Opus 5.5, 현 스킬): 14건 합격, 런당 CLI 호출 4–10, 입력 4.3–19.6만 토큰(캐시 포함), $0.09–0.43, 0.4–3.1분. 하네스 `.tmp/yf-golden/scenarios/run.py`(커밋 안 됨, 131줄), 시나리오 은행 `tests/yfinance/model-scenarios.json` 24건(`expect`·`premise`·`budget` 포함).
  - 골든 도구 `.tmp/yf-golden/{capture.py, compare.py, datenorm.py, golden_plugin.py}`가 남아 있다(커밋 안 됨). 골든은 저장 JSON을 기록하지 않고 id를 정규화한다(`golden_plugin.py:17-25`).
- yfinance 최신은 1.7.0(2026-08-26) — 고정 버전과 같다. `repair=True`와 `interval="5d"`는 무조건 `ValueError`(`scrapers/history.py:166-170`). `period="max"`는 1m→8일, 2m·5m·15m·30m·90m→60일, 60m·1h→730일, 그 밖→99년으로 바뀐다(`:227-239`).
- 오프라인 기준선(2026-10-01, Python 3.13, 기본 basetemp): **419 passed, 75 deselected(live), 252초**. 스크래치패드처럼 긴 basetemp(>120자)에서는 `test_export.py:218 path_of_length`가 132자 경로를 만들지 못해 한 건이 환경 때문에 실패한다 — 스킬 결함 아님. 구현 세션은 기본 basetemp를 쓴다.
- 테스트의 `schema` 사용: 12개 파일 약 45곳(`test_discovery`·`test_live`는 수집 시점에 schema를 실행). `--store` 사용: `test_budget.py:256,289-292`, `test_display.py` 1곳.
- 문서의 `schema` 언급: `SKILL.md:9`, `docs/usage.md:76,79,83,85,89`. `.github/`에는 PR 템플릿이 없다(→ `## 무엇을 바꿨나/왜/영향/검증`). CI(`test.yml:52`)의 yfinance ruff 대상은 `.claude/skills/yfinance/scripts tests/yfinance`.

### 코덱스 감사 (`gpt-6-astra` high, read-only, run `20261001-212722-yf-sm5-audit-f0ac`, 스레드 `01a0f76f-037d-7621-8495-21b7827da4ec`)

- 후보 설계 네 가지(그룹 문서 help·schema 제거, kind 2개 제거, `data/`·`--store` 제거, 단위 입구·구조 테스트) 모두 "진행 권고". 반영한 보완점:
  - 그룹 help와 kind help가 같은 문서를 내면 "읽는 경로 두 단계"를 만족한다(subparser가 세 단계인 것 자체는 문제 아님). 사용법·출력·실패를 앞에, 긴 kind별 의미를 뒤에. help는 결과 예산 밖이고 저장소·네트워크를 건드리지 않는다. → `## 명령 표면`.
  - 인자를 한 번씩 쓰더라도 kind별 기본값·필수·허용 조합을 잃지 않는다. → 그룹 문서의 인자 절.
  - `--ttl-days`는 루트 앞에서만 유효(`cli.py:404`). `--filter`는 catalog kind와 `--list-fields`에 남는다. → S7.
  - `search`(kind 없음)와 `read`도 자기완결 문서가 필요하다. `ENVELOPE`에 `context`·`continuation`·`stored_age_seconds`가 없고 `STATUSES`에 `not_attempted`가 없다. → S2·S6.
  - `yahoo`는 실패를 스킬의 말로 넘긴다. 부가 조회 실패는 본 데이터를 보존하고 레이트리밋이면 다음 대상을 멈춘다. "may be delisted"를 정상 empty로 바꾸지 않는다. → R2.
  - `bind`를 `yahoo` 밖으로, 시각은 시스템 경계에서 ISO로, `coarser_bars` 판단은 dataset 정책으로. 기본값 함수·조합 검사·`chosen()`은 표면 계약으로 남는다. → R3–R5.
  - 구조 테스트에 새 검사와 검사기 자체의 실패 픽스처를 함께, 등록별로. → R6·S5.
  - 제거 kind의 옛 관측은 `read`가 거절한다 → C2. 관측만 옮기면 M10이 끝나지 않는다 → 성진 결정 8로 예외.
- 새 결함(클로드가 메모리 재현으로 1–3 확인, 스크래치 `proto/repro.py`; 4는 코드 경로로 확인):
  1. **[major] 꼬리를 보인 첫 응답의 continuation이 앞쪽 행을 건너뛴다.** `budget.py:60`이 `start + shown`을 쓰는데 첫 축소는 최신 꼬리를 고른다. 재현: 100행 중 94–99를 보이고 `read ID --start 6 --limit 6`을 안내 → 0–5행에 영영 닿지 않는다. 기존 테스트(`test_budget.py:129-145`)는 `--start 0`에서 다시 걸어 이 경로를 보지 않는다.
  2. **[major] 옵션 체인 read의 다음 시작점이 calls·puts 행 수의 합이다**(`querying/read.py:31-39`). 재현: side당 60행·`--limit 20` → 다음 시작 40(맞는 값 20).
  3. **[major] 옵션 `--list-fields`가 `--fields`로 쓸 수 없는 내부 키를 알려준다**(`observe.py:99`, `read.py:23`). 재현: `calls, calls.index, calls.columns, calls.data, …`.
  4. **[major] 옵션 저장본의 예산 축소가 `select_sides` 대신 `select`를 부른다**(`budget.py:45`) → `read ID --fields strike`가 크면 invalid로 보고되고 저장 id가 사라진다.
  5. [minor] `--repair --interval 5d`를 받아들이고 일반 upstream으로 처방한다.
  6. [minor] intraday 문구가 `period=max` 변환을 말하지 않는다(`yahoo/prices.py:80-82`).
  7. [minor] 뉴스 gotcha의 경로는 `content.thumbnail`·`content.storyline`(`yahoo/company.py:44`).
  8. [minor] 잘못된 schema scope도 저장소를 정리한 뒤 거절 — schema 제거로 사라진다.
- 이전 라운드의 가장자리 결함 ✓10(기본값 적용 뒤 날짜 범위 재검증 없음)과 ✓7(`market summary --fields`가 화면은 거래소 키, `--out`은 필드)은 성진 결정 9로 이번에 고친다.

### 코덱스 계획 리뷰 (같은 스레드, run `20261001-214424-yf-sm5-plan-review-e6ed`) — major 8 · minor 5, 전부 반영

판정은 "결정 1–9를 바꾸지 않고, major를 반영하면 승인 가능". 반영한 자리:

| # | 지적 | 반영 |
|---|---|---|
| 1 | R4가 옛 레코드의 숫자 `source_time`(read·`--from`)을 놓친다 | R4에 레코드 읽기 경계의 메모리 정규화와 숫자 epoch 픽스처 |
| 2 | F9 매핑 행 순서가 첫 호출(원천 순서)과 저장본(정렬)에서 다르다 | F9: 모든 경로에서 키 정렬 순서, 정렬 안 된 입력 픽스처로 전 경로 리터럴 대조, 표·양면 표 제외 |
| 3 | F1·F2 cursor 계약이 구현자 판단에 남음, 기존 테스트 대체 금지 | F1 재시작·반열린 구간, F2 `start + max(side shown)`, 기존 테스트 유지 + 추가 |
| 4 | F3·F4 판정이 잘못된 구현도 통과 | F3 리터럴 열 집합, F4를 exit 8 사례와 exit 9 사례로 분리 |
| 5 | C4가 `querying.read`(공개 함수)와 `querying/read.py`를 혼동할 수 있고 job 코드·역방향 import가 빠짐 | C4 판정 규칙과 픽스처 목록 |
| 6 | 대응표의 빈틈(kind별 인자 수용·narrowing·실효 기본값·종료 코드·units 문법·live) | 대응표 확장, units는 한 줄 압축 JSON, "46 kind + search" |
| 7 | `schema_fix`는 일반 오류 문서에도 쓰인다 | S8: schema 전용 처방만 삭제, 일반 오류 문서의 초과 처방 분리, 20,000자 바닥은 invalid에만(재검증 ⑦) |
| 8 | `--filter` 루트 기본값 제거와 명시 여부 구분 | C9 명세와 테스트 넷 |
| 9 | help 연결 방식·read 문서 자기완결성 | C7·`## 명령 표면`: 표준 help action, 그룹·kind help 동일 비교, 필수 인자 없이 help, 별도 namespace, kind별 usage, read의 `--max-chars`·`--ttl-days`, 쿼리 문법은 cli `epilog` |
| 10 | R5와 `Leaf` 생성자 충돌 | R5에 `Leaf`·`budget` 호출 변경 명시 |
| 11 | 단계 9–11의 판정과 중간 표면 불일치, CI ruff | 저장 위치(S5)를 help보다 먼저(단계 9), SKILL.md 발견 문장은 help 단계(10)에, grep은 `git grep`, CI·CONTRIBUTING ruff에 `scenarios/yfinance` |
| 12 | `data/`가 사본 복사에서 빠지지 않음 | 기본 위치 테스트는 `YF_STORE`를 지우고 실행 전 부재·실행 후 반환 id 파일 존재, 복사에서 관측 제외(테스트·시나리오) |
| 13 | 전제 미성립 시나리오를 빼면 핵심 경로 없이 합격 | 두 번 모두 미성립이면 "미검증", 핵심 전제별 전후 유효 표본 ≥ 1 |

함께 확인된 것: R2는 본 데이터 보존·부가 조회 레이트리밋 중단과 종료 코드 우선순위(`rate_limited > invalid > local_io`, `cli.py:33-40`)를 유지한다. F5는 `given` 스냅샷 뒤·저장소 열기 전, F6은 history·actions 양쪽.

틀 충실성 독립 대조(run `20261001-220410-yf-sm5-frame-coverage-090e`, 성진의 "skill-maker 프레임을 잘 반영했지?"에 따라 클로드가 1~6절을 다시 대조해 일곱 곳을 고친 뒤 코덱스가 따로 대조): "아직 충실하지 않음"이었고 전부 반영했다 — C18의 측정 일괄 금지를 "행동에 쓰이지 않는 출처만"으로 좁힘, 경위를 `# 성진:` 주석으로 옮기는 것은 스킬 밖 기록이 아님, 다듬은 원리를 사례로 사용자와 대조(→ 결정 11을 사례 둘로 확인), 시나리오의 실행 실패 분리와 하네스 격리 한계, 원리 충돌 ① 사례 재분류(사실의 소유와 배치를 나눔)·②를 이전 결정의 예외로·④의 회복 보장을 해석 가능한 메시지로 좁힘, ⑥은 cli `Command` 권고(생략 상태와 원천 요청량 보존 조건 포함 → R7).

틀 충실성 확인(run `20261001-234259-yf-sm5-frame-verify-a6a1`): 6건 RESOLVED, 2건 PARTIAL → 둘 다 반영(④의 "넘으면 실패" 무조건 보장 삭제, 시나리오의 환경 실패 제외를 확인된 외부 장애로 한정). R7은 골든 동일성과 모순 없음, 연결 지점 셋(`screen_conditions`의 `asked()`, research 예외, 실효 개수를 `args`에 넣지 않음)을 R7에 이름으로 적었다. 판정: 이 두 수정이면 skill-maker에 충실하고 승인 가능.

재검증(run `20261001-215346-yf-sm5-plan-reverify-b404`): 11건 RESOLVED, 2건 PARTIAL → 둘 다 반영했다. ⑥ 실효 기본값을 `request` 메아리로 전부 비교할 수 없다(`cli.py:516`이 `max_chars`·`ttl_days`를 빼고 `chosen()`이 바뀌지 않은 기본값을 생략) → 대응표의 해당 줄을 리터럴·픽스처·실제 메아리 인자로 나눴다. ⑦ 20,000자 바닥은 invalid에만 있고 예산을 넘는 local_io는 지금도 too_large(exit 9) → S8 테스트를 exit 4 / exit 9 둘로 나눴다. 디렉터리 대조표의 근거 문구 두 곳(패키지 접미사, `export`)을 정확히 고쳤다. 새 blocking·major는 이 둘 말고 없었다.

### 성진 결정

1. 의도 이해 확인(Context의 목적 다섯 가지와 범위 해석 — 명령마다 "모델이 직접 못 하는 일을 숨기는가"를 다시 묻는다).
2. **CLI 유지 전제.** 스킬 없음·현 스킬·지식만 세 조건의 대조는 하지 않는다. 확인된 차이(2단계 help, 명령별 출력·실패, `data/`, 단위 입구, 구조 테스트)를 반영하고, M12는 명령 단위의 정리(중복·고정 목록 kind 제거)로 적용한다.
3. 계획 파일 정식 이름: `.claude/plans/yfinance 스킬 코드 설계 판단 반영 계획.md`. 승인 직후 `mv`.
4. **help는 두 단계, `schema` 제거.** 루트 `--help`는 그룹마다 kind를 나열하는 지도다. `<group> --help`(= `<group> <kind> --help`)는 한 문서로 kind·인자(적용 kind 표시)·공통 인자·출력·종료 코드·kind별 기본 창·단위·해석·한계·함정을 말한다. 호출 문법(`prices history AAPL`)은 그대로다.
5. **kind 두 개 제거**: `analysts summary`, `market sectors`.
6. **저장 관측은 `<skill>/data/observations/`, `--store` 제거.** 테스트 격리는 `YF_STORE` 환경변수로 유지하고, 루트 `.gitignore`에 `.claude/skills/yfinance/data/`를 더한다(C3). 기존 `~/.cache/yfinance-skill` 관측은 옮기지 않는다.
7. **모델 시나리오 실행기는 레포 루트 `scenarios/yfinance/`에 커밋한다**(M14). 시나리오 은행 `tests/yfinance/model-scenarios.json`은 그대로 둔다. twitter의 `tests/twitter/model/`은 건드리지 않고 후속 과제로 적는다.
8. **yfinance 라이브러리 자체 캐시(시간대·쿠키·ISIN)는 라이브러리 기본값에 둔다.** M10의 의식적 예외다. 코덱스 감사는 이를 major로 보고 `yf.set_tz_cache_location()`(세 캐시를 함께 옮김)을 권했다. 남은 한계: 이 머신의 다른 yfinance 버전과 캐시 DB를 공유한다.
9. **추가 개선 범위**: 작은 정확성 수정 묶음(✓10 날짜 범위 재검증, `--repair`+`5d` 사전 거절, intraday `period=max` 문구, 뉴스 gotcha 경로)과 `market summary --fields` 의미 통일. screen 쿼리 조건 판정과 ADR EPS 단위는 하지 않는다.
10. (세션 중 요청) 계획에 구현 후의 디렉터리 구조를 담고, skill-maker 틀을 충실히 반영한다 → `## 구현 후 디렉터리 구조`와 그 대조표, `## skill-maker 조항 대조표`, `### 원리 충돌과 해소`.
11. **기본 창(`rows`·`fields` — `--limit`·`--fields`를 생략했을 때 보여줄 행 수와 필드)은 `cli.py`의 명령 선언으로 옮긴다**(이전 결정 4의 분리표를 이 한 줄만 바꾼다). 사례로 확인한 판단: quote와 profile은 같은 응답을 읽고 기본 필드만 다르다 → 기본 창은 데이터의 성질이 아니라 명령의 목적이다. 기본 행 수가 원천 요청량이기도 한 kind(news 10·screen 25·calendar 12·search 10)는 기능이 실효 개수를 계산해 `yahoo`에 넘긴다. 원천 순서(`recent`)·정밀도·단위·해석은 `yahoo`에 남는다. → R7.

### Claude가 정한 것 (묻지 않음, 근거와 함께)

- **C1. PR 셋, 순서는 구조 → 결함 → 표면.** `coding`의 "구조와 행동은 다른 커밋, 구조 먼저" 원칙. 결함 수정은 표면과 독립이라 먼저 머지하고, 표면 PR의 전후 시나리오가 둘 다를 덮는다. 각 PR은 앞 PR이 머지된 `main`에서 판다.
- **C2. 제거 kind의 legacy 읽기 해석기는 두지 않는다.** 저장소를 새 위치로 옮기고 이관하지 않으므로(결정 6) 새 저장소에는 제거된 kind의 관측이 생기지 않는다. 옛 레코드 형식 호환 테스트(`tests/yfinance/fixtures/store/` — history·quote·news, R4로 숫자 시각 레코드 추가)는 `YF_STORE`로 그대로 유지한다.
- **C3. `data/`는 커밋하지 않고 `store`가 처음 쓸 때 만든다. 루트 `.gitignore`에 `.claude/skills/yfinance/data/`를 더한다(결정 6).** `data/.gitignore` 같은 자리표시 파일은 두지 않는다 — 틀의 도입 문단 "the skill folder holds only what the running model uses"를 어기기 때문이다(초안의 이 선택은 틀 재대조에서 되돌렸다). 상태 위치는 실행 뒤의 트리, 이 계획의 구조도, 구조 테스트 C4 ④가 말한다.
- **C4. 구조 테스트의 새 검사는 등록별(`UNITS = {'yfinance': {'edges': set(), 'jobs': ['scenarios/yfinance']}}`)이다.** facebook·threads·twitter는 옛 계약 그대로(skill-maker 레거시 조항). 정적으로 식별 가능한 접근만 판정한다(동적 import·문자열 조립은 범위 밖이라고 검사기 docstring에 적는다).
  - 해석: 패키지의 실제 모듈 목록, 절대·상대 import, import 별칭(`import a.b as c`, `from a import b as c`)을 푼다.
  - ① **입구**: 하위 패키지 단위 `U`의 `__init__.py`가 바인딩한 이름을 "공개 값"(그 이름이 가리키는 정의가 함수·클래스·상수)과 "모듈 객체"(그 이름이 `U`의 하위 모듈)로 나눈다. `U` 밖(다른 단위·`cli.py`·`tests/<skill>`·`jobs`)에서 `pkg.U.<모듈>` import, `from pkg.U import <모듈>`, `U` 별칭의 `.<모듈>` 속성 접근, 문자열 patch 경로(`"pkg.U.<모듈>.x"`)는 위반이다. `U` 안의 서로 접근과 공개 값 접근(`querying.read(...)` — `querying/read.py`와 이름이 같아도 공개 함수)은 허용한다. `__init__`가 하위 모듈 객체 자체를 재수출하면 그것도 위반이다.
  - ② **기능 간선**: 기능→기능 import는 `edges`의 (출발, 도착) 쌍만, 방향 포함. 허용 간선도 기존 순환 검사에서 빠지지 않는다.
  - ③ **레포 코드 방향**: 스킬 코드가 `tests`·`jobs`의 모듈을 import하면 위반. `jobs` 경로도 `sys.path` 편집·`cli` import 검사 대상.
  - ④(PR ③) **상태 위치**: 스킬 코드에 `Path.home`, `expanduser`, `XDG_CACHE_HOME`·`.cache` 문자열이 없다. 라이브러리 기본 캐시는 결정 8의 예외라 검사하지 않는다.
  - 검사기 자체 테스트: v2 합성 트리 — 정상(공개 함수 `read`와 하위 모듈 `read.py` 공존, 이름 붙인 간선 하나 포함)은 위반 0, 위반 트리마다(절대 import·상대 import·별칭 import·속성 접근·하위 모듈 재수출·테스트의 내부 import·테스트의 문자열 patch·job의 내부 import·스킬→tests import·이름 없는 기능 간선·허용 간선이 만드는 순환·홈 경로) 그 규칙의 위반 문자열. 각 위반 픽스처가 검사 구현 전에 red여야 한다.
- **C5. `yahoo`의 입구는 `dataset(key)`, `fetch(key, target, args, context, warnings)`, 실패 타입이다.** `DATASETS` 딕셔너리는 노출하지 않는다. 실패 타입(이름은 구현에서 정함): 레이트리밋 / 원천 제약(`kind=span|reach`, `days`) / 원천이 이 기호·데이터셋에 데이터가 없다고 말함 / 그 밖의 upstream(원 메시지 보존). 분류(Yahoo 메시지·429·예외 이름 읽기)는 `yahoo` 안, 처방 문장(`--period 8d` 같은 인자 이름)은 `querying` 안. `InputError`와 `DeadlineExpired`는 그대로 통과한다.
- **C6. `Leaf(command, dataset)` 결합은 기능이 한다**: `querying`과 `describe`(PR ①에서는 `schema`)가 `Leaf(command, yahoo.dataset(command.dataset))`. `leaf.py`(공용)는 결합만 하고, `coarser`는 dataset에서 온다(R5).
- **C7. help 문서의 배치는 `cli.py`, kind별 의미는 기능 `describe`가 데이터로 넘긴다.** `cli`는 시스템을 import할 수 없으므로(`ALLOWED`) Yahoo의 사실(limit이 남기는 끝·단위·해석·한계·함정)을 `yahoo`에서 꺼내는 일은 기능이 맡는다. 기본 창은 cli 자신의 선언이다(결정 11). `schema.py`를 `git mv`로 `describe.py`로 바꾸고 `describe(command) -> dict`만 남긴다. 출력 봉투의 설명(`ENVELOPE`)은 봉투를 정의하는 `envelope.py`로 옮긴다. `screen run`의 쿼리 문법은 입력 계약이라 cli의 `Command.epilog`를 그대로 싣는다(복사본 없음).
- **C8. help는 결과 예산 밖이고 저장소·네트워크를 건드리지 않는다.** argparse가 `--help`를 저장소 열기 전에 처리하므로 지금 구조로 성립한다. 테스트가 고정한다.
- **C9. `--filter`**: 루트 `--filter`(schema용)는 없앤다. 리프·read 파서가 `--filter`를 기본값 `None`으로 직접 갖는다(명시 여부를 `None`으로 구분 — 빈 문자열도 "준 것"). 의미가 있는 곳: `screen`의 `presets|fields|values`(단독), 데이터 명령·`read`(`--list-fields`와 함께). 그 밖에 주면(빈 문자열 포함) 저장소를 열기 전에 invalid. catalog 어댑터는 `args.filter or ""`. 저장 request와 화면 `chosen()`에서 `None`인 filter는 빠진다(기본값과 같으므로 기존 표시 의미 유지).
- **C10. 테스트 seam은 이전 결정(CLI 프로세스 seam + 전송 교체 + AST 구조 테스트 + live + 모델 시나리오)을 유지한다.** schema JSON에 기대던 단언은 그룹 문서의 고정 줄 형식으로 옮긴다: kind 머리줄, `a limit keeps …`, `units: <한 줄 압축 JSON>`(`scale`·`kind`·`inverted`·`as_of`·`scale_by_quote_type`를 모두 보존), `exit codes` 절. in-process seam은 두지 않는다.
- **C11. PR ①의 행동 불변은 골든으로 판정한다.** `.tmp/yf-golden`의 도구를 재사용하고 커밋하지 않는다(일회성 이행 도구, M14의 반복 작업이 아님). 골든은 저장 JSON을 보지 않으므로 R4의 저장 표현 변경은 픽스처 테스트가 맡는다.
- **C12. 모델 시나리오는 은행 24건 전부를 전(PR ② 머지 뒤 `main`)과 후(PR ③ 브랜치)로 돌린다.** 판정 모델 Claude Opus 5.5(`claude-opus-5-5`). 합격 기준은 `## 검증`.
- **C13. `SECTOR_KEYS`(cli 리터럴)는 `test_vocabulary.py`가 `yfinance.const.SECTOR_INDUSTY_MAPPING_LC`의 키와 대조한다** — `market sectors` 출력과 대조하던 테스트(`test_market.py:162-166`)를 대체한다. 산업 키 145개를 choices로 바꾸지 않는다(이전 결정 13).
- **C14. 코덱스 리뷰는 네 번**: 이 계획(완료 — 위 표), PR ① 그린 뒤(구조 테스트는 이후 작업의 증거), PR ② 그린 뒤(공유 계약: continuation·선택), PR ③ 끝(전체 diff, 그룹 문서의 모든 주장이 테스트나 코드로 뒷받침되는지, SKILL.md와 그룹 문서의 네 성질 — C18). 스레드 `01a0f76f-037d-7621-8495-21b7827da4ec`를 resume한다(`gpt-6-astra`, high, read-only). 결정 1–11과 충돌하는 지적은 AskUserQuestion으로 올린다.
- **C15. `references/`는 만들지 않는다.** kind별 의미는 그룹 문서(인터페이스)가 갖고, 한 갈래에서만 읽을 산문이 없다.
- **C16. 개발 기록**(측정 경위, 기각한 대안, 시나리오 결과)은 커밋 본문과 이 파일 끝 `# 구현 기록`에 둔다.
- **C17. `read`에서 쓰지 않는 `--timeout`을 없앤다**(M6: 명령 help가 설명하는 인자는 그 명령이 쓰는 것). 공통 검증은 `timeout`이 없는 namespace를 받는다.
- **C18. 모델이 읽는 모든 문장에 네 성질을 적용한다.** 그룹 문서가 이제 모델이 읽는 텍스트의 대부분이므로(SKILL.md는 한 문단), 루트 지도·그룹 문서·read 문서·인자 help·kind별 의미(interpretation·limits·gotchas)·fix·warnings를 PR ③ 단계 10에서 한 줄씩 훑는다.
  - principle over rail: 금지·순서는 이유와 함께, 이유보다 세게 쓰지 않는다.
  - interface over document: 같은 사실을 두 곳(예: 인자 help와 kind 의미)에 쓰지 않는다 — 사실의 소유와 문서의 배치는 `### 원리 충돌과 해소` ①.
  - for the model: 판정은 "모델이 이 줄로 다음 행동을 바꾸는가, 아니면 출처만 기록하는가"다. 다음 결정을 바꾸는 측정(예: intraday의 `max`가 줄어드는 범위)과 실효 날짜 기본값·필요한 예시는 남긴다. 행동에 쓰이지 않는 출처·측정 경위·방어 논증은 커밋 본문과 구현 기록으로 옮긴다 — 스킬 폴더 안의 `# 성진:` 주석으로 옮기는 것은 "스킬 밖 기록"이 아니다. 코드의 현재 한계·불변조건을 설명하는 `# 성진:` 주석은 그대로 둔다(`coding`의 규칙).
  - dense: 다시 말하기·계산 가능한 귀결을 뺀다. **소유자가 우리가 아닌 값은 낡는다** — 규칙은 `### 원리 충돌과 해소` ④.
  - 판정: 단계 10에서 클로드가 줄 단위로 훑고, 코덱스 리뷰 ③이 같은 기준으로 다시 본다. 지운·옮긴 문장과 이유는 커밋 본문에. 문자열 grep으로 판정하지 않는다(실효 날짜 같은 쓸모 있는 출력까지 걸린다).
- **C19. 위치·언어는 바뀌지 않는다**: 프로젝트 스킬(`.claude/skills/yfinance`, 자기완결 — 복사해 가도 돈다), SKILL.md·help 영어, Claude Code 전용(9/26 결정 2). 계획·커밋·PR은 한국어.

### 원리 충돌과 해소 (skill-maker: "원리끼리 당길 때 그것을 정하는 조건도 지식이다")

| # | 서로 당기는 두 원리 | 정하는 조건 | 갈리는 사례 |
|---|---|---|---|
| ① | `cli.py`가 표면 전부(help 텍스트 포함)를 든다 ↔ system 단위가 그 시스템의 말(값과 입력의 뜻)을 전부 든다 | **사실의 소유와 문서의 배치를 나눈다.** 소유: **우리가 정한 입력 계약**(인자·choices·기본값·조합·쿼리 JSON 문법)은 cli, **Yahoo가 정한 사실**(돌려준 값의 단위·해석·한계·함정, 그리고 Yahoo가 입력을 읽는 스케일)은 yahoo dataset이 데이터로 갖고 `describe`가 cli에 넘긴다. 배치: cli가 문서 전체를 배치하며, Yahoo 사실은 그것이 설명하는 자리(인자 설명 옆 또는 kind 의미)에 놓는다 | `--end`가 배타적 = 우리 입력 계약 → cli / "statement 행의 index는 회계기간 말일" = Yahoo 값 → yahoo, kind 의미 자리 / 쿼리 JSON 문법 = 우리 입력 계약 → cli `epilog` / "쿼리의 성장률 임계는 퍼센트 포인트(출력 비율의 100배)" = Yahoo가 입력을 읽는 스케일 → yahoo가 소유, cli가 쿼리 문법 옆에 배치 |
| ② | 닫힌 집합은 choices로(표면, 원문에 크기 예외 없음) ↔ 큰 집합을 choices로 펼치면 help가 그 목록에 덮인다 | **원문에서 나오는 일반 조건이 아니라 이전 결정 13(9/26)으로 유지하는 예외다.** 프리셋 19·섹터 11·지역·interval은 choices(cli 리터럴 + `test_vocabulary`가 라이브러리 값과 대조), 산업 키 145·스크린 필드 93은 발견 kind + fix로 둔다 | `--preset` = choices / 산업 키 = `market sector KEY --dataset industries`로 발견 |
| ③ | 상태는 `data/`(M10) ↔ 라이브러리가 소유한 캐시 | 스킬이 직접 쓰는 상태는 `data/`. 라이브러리 내부 캐시는 성진 결정 8로 기본값 | 관측 = `data/observations` / yfinance 시간대·쿠키 DB = `user_cache_dir()` |
| ④ | 모델의 다음 결정을 바꾸는 측정은 남긴다(for the model) ↔ 클라이언트가 소유한 한도·기본값은 낡으니 실패를 쓴다(dense) | **우리 코드가 강제하는 값**(screen 250·calendar 100 상한, 기본 창, `--max-chars` 20000)과 **고정 버전 라이브러리의 동작**(yfinance 1.7.0의 `period=max` 변환)은 숫자로 쓴다. **Yahoo 서버가 정하는 한도**(1m 요청당 일수, 분봉 도달 범위)는 실패와 회복으로 쓴다: "원천이 범위 제약으로 거절하고 그 메시지가 해석 가능하면(현재 `refusals`가 읽는 두 패턴: 요청당 일수, 최근 N일) fix가 그 값으로 `--period`·`--start`를 처방하고, 그 밖의 실패는 일반 처방이다." 범위를 넘으면 반드시 실패한다고 쓰지 않는다(원천이 덜 주거나 조용히 바꿀 수도 있다). 숫자를 지운 자리에 "fix가 늘 현재 값을 말한다" 같은 더 강한 일반화를 넣지 않는다 | F7의 limits 문장 / 지금 `limits`의 "1m: 8 days per request"는 이 실패 문장으로 바뀐다 |
| ⑤ | 틀 그림의 `<helper>.py`(패키지 바로 아래 `.py` = 공용) ↔ "단위는 패키지 바로 아래 모듈 또는 하위 패키지, 두 번째 이유 전까지 모듈" | 본문 문장이 우선한다. 모듈 하나인 기능·저장소 단위는 패키지 바로 아래 `.py`이고, 종류는 이름과 구조 테스트 등록부가 말한다 | `store.py`·`export.py`·`describe.py` / twitter `continuation.py` 선례 |
| ⑥ | 기본 창(`rows`·`fields`): 인자 기본값(표면) ↔ 데이터셋 정책(시스템) | **"이 명령을 인자 없이 부르면 무엇을 얼마나 보여줄까"는 명령의 목적이므로 cli**(성진 결정 11). 원천이 그 데이터를 어떤 순서로 주는지(`recent`)는 Yahoo의 사실이므로 yahoo. 원천에 보낼 개수는 기능이 둘을 합쳐 계산해 yahoo에 넘긴다 | quote(시세 41필드)·profile(사업 31필드)은 같은 `get_info` 응답 / news 기본 10건 = 화면 창이자 요청량 → 기능이 계산해 전달 / "upgrades는 최신이 앞" = yahoo |

### 추론과 수용된 가정

- 추론: 두 단계 help가 발견 호출 수와 읽는 글자 수를 줄인다. 판정은 전후 시나리오의 발견 호출 수다(`## 검증`).
- 추론: 그룹 문서가 길어(최대 약 8천 자) 모델이 필요한 kind의 의미를 놓칠 수 있다. 완화: kind별 의미를 kind 머리줄 아래에 모아 맨 뒤에 둔다. 판정은 함정 시나리오(spy-pe·toyota-pe·earnings-surprise·ko-dividend·growth-screen·blackrock-position)의 합격 유지다.
- 수용된 가정: 옛 관측을 옮기지 않아도 된다(보존 14일, 다시 요청하면 된다 — 결정 6).
- 수용된 가정: 라이브러리 캐시 공유로 인한 충돌은 드물다(결정 8).
- 남은 불확실성(구현 기록에도 옮긴다): 시나리오는 런 한 번씩이라 실사용 여러 세션의 성능을 증명하지 않는다. 성진의 SKILL.md 승인도 그 증거가 아니다. 그룹 문서의 길이가 모델의 주의를 흩는지는 함정 시나리오로만 간접 확인한다. Yahoo 서버 한도는 예고 없이 바뀐다(④의 실패 문장과 fix가 받는다).

### 미결

- 없음. 구현 중 새 판단이 필요하면 AskUserQuestion으로 묻는다.

## skill-maker 조항 대조표 (도입·What earns·Drawing out·Writing judgment·Code·Done 전체)

`/Users/seongjin/.claude/skills/skill-maker/SKILL.md`의 조항마다 이 계획의 자리다. 구현 세션과 코덱스 리뷰 ①–③이 체크리스트로 쓴다. 트리 칸별 대조는 `## 구현 후 디렉터리 구조`의 마지막 표.

| 절·조항 | 이 계획의 자리 |
|---|---|
| 도입: 스킬은 기본값과 전문가의 차이를 이유와 함께 싣고, 모델이 이미 잘하는 것은 뺀다 | SKILL.md는 한 문단(9/27 제거 시험). 차이(단위·스케일·시각·창·회복)는 그룹 문서의 kind별 의미가 싣는다 |
| 도입: 사용자의 수단이 목표를 해치면 증거·대안·권고 후 선택하게 | M12 쟁점을 증거와 함께 올림(결정 2), 라이브러리 캐시(결정 8)에 코덱스 반대를 기록 |
| What earns: principle over rail | C18 ①, 원리 충돌 표의 "정하는 조건"과 "갈리는 사례" |
| What earns: interface over document | 결정 4(의미는 help가 소유, `schema`라는 두 번째 사본 제거), C18 ②, 원리 충돌 ① |
| What earns: for the model, not the maintainer | C18 ③(다음 결정을 바꾸는 측정은 남기고 출처만 기록하는 줄은 커밋·구현 기록으로), 단계 10 판정 |
| What earns: dense, "클라이언트 소유 값은 실패로" | C18 ④, 원리 충돌 ④, F7 |
| What earns: 기본값 교정 문장은 행동과 이유, 모델 정보는 기록으로 | 그룹 문서 gotchas, 구현 기록에 기준 모델(단계 13) |
| What earns: 이웃 스킬과의 경계(skill-doctor) | 단계 12 |
| Drawing out: 읽고 나서 묻기 | 장부 "사실"(이전 계획 4개·실행 기록·코드·yfinance 소스를 먼저 읽음) |
| Drawing out: 기본값과 대조 | 이번에는 하지 않음(결정 2). 대신 기존 동작의 보존을 전후 시나리오로 판정(C12) |
| Drawing out: 권위 종류 구분·장부(사실·추론·결정·가정·미결) | `## 장부`의 절들 |
| Drawing out: 원리끼리 당길 때의 조건 | `### 원리 충돌과 해소` |
| Drawing out: 다듬은 원리는 쓰지 않은 사례·조건을 바꾼 사례로 사용자 판단과 대조 | 원리 충돌 ⑥을 두 사례(같은 응답·다른 기본 필드 / 기본 행 수가 원천 요청량까지 바꿈)로 성진에게 확인(`### 미결`) |
| Drawing out: 대조 실행에서 파일·도구·권한 부족으로 실패한 결과는 증거가 아님, `--tools`로 셸을 되살리면 격리되지 않음 | `## 검증`의 실행 실패 분리 규칙과 하네스 한계 |
| Drawing out: 증거로 못 정하는 것은 하나씩 합의, 위치·언어 | 성진 결정 1–10, C19 |
| Drawing out: 기존 스킬에서 시작 — 살아야 할 행동을 먼저 알고, 최소 범위, 삭제·통합도 개선 | 골든(PR ①), "전" 시나리오(단계 8), `schema`·kind 둘·`--store`·`read --timeout` 삭제 |
| Writing judgment: 원리는 이유·조건·뒤집는 조건·사례 | 원리 충돌 표 |
| Writing judgment: 완료를 확인 가능하게, 보존할 것과 바꿀 수 있는 것 구분 | 작업 단계의 판정 열, `### 표면에서 바뀌는 것 요약`(그대로인 것 / 없어지는 것) |
| Writing judgment: 지식은 작동하는 자리에, 직접 할 수 있는 조회를 감싸지 않음 | 결정 2·5, `--out`으로 계산은 모델이 직접(현행 유지) |
| Writing judgment: 필요한 때에 따라 파일 분리, references | 없음(C15) |
| Code: 트리 — 폴더 이름이 내용을 말하고, 스킬 폴더는 모델이 쓰는 것만, 테스트가 트리를 지킴 | `## 구현 후 디렉터리 구조`, C3(자리표시 파일 없음), C4 |
| Code: 어긋나면 조용히 벗어나지 말고 사용자에게 | 패키지 접미사(이전 결정 3), 라이브러리 캐시(결정 8), 기본 창(결정 11), 큰 닫힌 집합(이전 결정 13, 원리 충돌 ②) |
| Code: `sys.path` 안 건드림, stdlib 가림 | 구조 테스트(현행) |
| Code: `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`·PEP 723 | 현행 유지, 구조 테스트 |
| Code: 명령은 숨기는 일이 있을 때만 | 결정 2·5. 남는 46 kind + search·read는 인코딩·저장·예산·단위 계약·조건 판정·회복을 숨긴다(코덱스 감사 Task 1 #7이 kind별로 검토) |
| Code: `cli.py`는 표면 전부, 결정 로직은 단위로 | R5(`coarser` 판단 이동), R7(기본 창을 cli로, 실효 요청 개수 계산은 querying), C7, 원리 충돌 ①⑥ |
| Code: `--help` 두 단계, 명령별 help가 인자·choices·출력·실패를 스스로 | 결정 4, `## 명령 표면`, S1–S3·S6, 대응표 |
| Code: stdout은 결과만·싼 신호 먼저·그 결과만 가리키는 손잡이, stderr 진단, 0·2 외 코드는 help가 정의 | 현행(봉투 순서·내용 주소 id·덮어쓰지 않는 `--out`) + 모든 문서의 exit codes 절 |
| Code: 단위는 입구 뒤의 깊은 모듈, 테스트 포함 | R1–R3, C4 ① |
| Code: system 단위가 시스템의 말(코드·위치·날짜 형식)을 전부, 스킬의 말로 | R2(실패), R4(시각), R5(간격 사다리), 원리 충돌 ①② |
| Code: import는 한 방향, 기능 간선은 이름 붙인 것만 | 현행 `ALLOWED` + C4 ② |
| Code: 상태는 `data/` | S5, 결정 6·8, C3, C4 ④ |
| Code: 테스트·유지보수 코드는 레포, 스킬은 그것을 import하지 않음, 구조 테스트 | `tests/`, `scenarios/yfinance/`(결정 7), C4 ③ |
| Code: 레거시 이행은 따로 합의 | 다른 세 스킬은 옛 계약(C4) |
| Done: 전문 승인(부분·침묵 아님) | 단계 12 |
| Done: 핵심 판단과 경계, 원리 충돌 해소, 남은 불확실성 명시, 승인은 성능 증거 아님 | 원리 충돌 표, 장부 "남은 불확실성", 구현 기록(단계 13) |
| Done: 대조가 드러낸 차이마다 자리 | 이전 라운드의 차이는 각 자리 유지(`## 계약이 서로 물린 곳`), 이번 대조 없음(결정 2) |
| Done: `claude plugin validate --strict` (`.claude/skills`) | 단계 12 |
| Done: 코드는 자기 계약으로 검증, `--help`가 동작과 일치, 이행 코드는 구조 테스트 통과 | 동작 명세의 재현 테스트, 대응표, 코덱스 리뷰 ③의 "근거 없는 help 주장 0", C4 |
| Done: 다른 모델 계열이 네 성질로 검토 | 코덱스(C14, C18) — SKILL.md와 그룹 문서 |
| Done: 개발 기록은 스킬 밖 | C16 |

## 구현 후 디렉터리 구조

### 스킬 (skill-maker 트리 틀의 칸을 오른쪽 주석에 적는다)

```
.claude/skills/yfinance/
├── SKILL.md                         # 호출 한 문단 + allowed-tools
├── data/                            # [data/] 스킬이 읽고 쓰는 상태 — 커밋하지 않음, store가 처음 쓸 때 생김 (C3)
│   └── observations/                #   <16hex>.json 내용 주소 관측 (YF_STORE가 있으면 그쪽)
└── scripts/
    ├── cli.py                       # [cli.py] 유일한 진입점: PEP 723, 루트 지도·그룹 문서·read 문서의 배치, 인자·choices·기본값·kind별 기본 창(행·필드)·조합 검사, 디스패치, 종료 코드
    └── yfinance_skill/              # [<skill_name>/] 유일한 패키지 (yfinance를 가리지 않으려 접미사 — 이전 결정 3)
        ├── __init__.py              #   비어 있음
        ├── envelope.py              # [<helper>.py] 결과 봉투·ORDER·STATUSES(+not_attempted)·봉투 필드 설명·InputError·LocalFailure·conditions
        ├── shape.py                 # [<helper>.py] 스킬 표현의 형태: 표·양면 표·키 붙은 레코드
        ├── display.py               # [<helper>.py] stdout 표기(원천 정밀도·날짜)
        ├── selection.py             # [<helper>.py] 투영·필드 목록·행 창 — 표·양면 표·키 붙은 레코드에 한 계약
        ├── budget.py                # [<helper>.py] 크기 경계·shrink(양면 포함)·회복 문장·continuation
        ├── leaf.py                  # [<helper>.py] Leaf(command, dataset)
        ├── yahoo/                   # [<system>/] Yahoo Finance + yfinance 라이브러리. 입구 __init__ = dataset(key)·fetch(...)·실패 타입
        │   ├── __init__.py          #   입구: 데이터셋 조회, 가져와 인코딩, Yahoo 실패 → 스킬 실패 타입
        │   ├── datasets.py          #   Dataset 선언 틀(원천 순서·정밀도·단위·해석·한계·함정), 단위 어휘 — 기본 창은 없음(결정 11)
        │   ├── encode.py            #   pandas·numpy → 스킬 표현(무손실)
        │   ├── refusals.py          #   Yahoo 실패 메시지·429 읽기(분류만, 처방 문장은 querying)
        │   ├── info.py              #   quote·profile이 공유하는 조립 응답, source_time을 ISO로
        │   ├── prices.py            #   quote·history·actions, 간격 사다리(coarser)
        │   ├── company.py  financials.py  analysts.py  holders.py  fund.py  options.py
        │   ├── screen.py            #   presets·fields·values·run, 쿼리 파싱, 프리셋 기본값
        │   ├── market.py            #   summary·sector·industry (고정 sectors 목록 삭제)
        │   ├── calendar.py  search.py
        ├── store.py                 # [<store>] 관측 저장·load(옛 숫자 시각 정규화)·prune, 기본 위치 <skill>/data/observations
        ├── export.py                # [<store>] --out CSV 형태 변환과 원자적 게시
        ├── querying/                # [<feature>/] 데이터 명령과 read에 답한다. 입구 __init__ = answer·read·prepare·open_store·LOCAL_FIX
        │   ├── __init__.py
        │   ├── observe.py           #   대상 루프·저장·선택·실패 처방
        │   ├── read.py              #   저장본 다시 읽기(양면·키 붙은 레코드 cursor)
        │   └── out.py               #   --out의 행·게시·요약
        └── describe.py              # [<feature>] (← schema.py) describe(command) → kind별 Yahoo 사실(limit이 남기는 끝·단위·해석·한계·함정)
```

- 분류(구조 테스트 `SKILLS['yfinance']`): 공용 `envelope shape display selection budget leaf`, 시스템 `yahoo`, 저장소 `store export`, 기능 `querying describe`. `UNITS['yfinance'] = {'edges': set(), 'jobs': ['scenarios/yfinance']}`.
- import 방향: 기능 → 시스템·저장소 → 공용, 기능끼리 없음. `cli.py`는 공용·기능만. `yfinance`·`pandas`·`numpy`는 `yahoo/` 아래에만(`test_boundary.py`).

### 레포 (스킬 밖)

```
<레포>/
├── .gitignore                       # .claude/skills/yfinance/data/ 추가 (결정 6)
├── .github/workflows/test.yml       # yfinance ruff 대상에 scenarios/yfinance 추가 (워크플로 재활성화는 안 함)
├── CONTRIBUTING.md                  # 같은 ruff 대상, yfinance 상태 위치 한 줄
├── docs/usage.md                    # schema 언급 → <command> --help, data/observations 위치
├── scenarios/                       # [<job>/] 유지보수자만 돌리는 일, 하는 일 이름
│   └── yfinance/run.py              #   모델 시나리오 실행기(스킬을 import하지 않음)
└── tests/                           # [tests/] 테스트·픽스처·시뮬레이터
    ├── test_skill_layout.py         #   UNITS 등록·C4 검사·v2 합성 트리
    └── yfinance/
        ├── conftest.py              #   CLI seam (YF_STORE·전송 교체) 그대로
        ├── model-scenarios.json     #   시나리오 은행 24건 그대로
        ├── fixtures/{sitecustomize.py, shapes/, store/}   # store/에 숫자 시각 quote 레코드 추가(R4)
        ├── test_discovery.py        #   schema → 루트 지도·그룹 문서 (대응표)
        ├── test_budget.py  test_selection.py  test_export.py  test_store.py  test_market.py  test_prices.py  test_company.py  test_display.py  test_cli.py
        ├── test_portability.py      #   그룹 문서 + 기본 저장 위치(YF_STORE 없이)
        ├── test_vocabulary.py       #   + SECTOR_KEYS ↔ yfinance const
        ├── test_boundary.py  test_live.py
```

### skill-maker 틀과의 대조

| 틀의 칸 | 구현 후 | 근거·판단 |
|---|---|---|
| `SKILL.md` | 한 문단 | 9/27 제거 시험 |
| `references/` | 없음 | 칸은 "한 갈래에서만 읽는 것이 있을 때". 의미는 그룹 문서가 가짐(C15) |
| `data/` | `data/observations/`(런타임 생성, 루트 `.gitignore`) | M10. 자리표시 파일은 두지 않음(도입 문단: 스킬 폴더는 실행 중인 모델이 쓰는 것만). 라이브러리 캐시는 결정 8의 예외 |
| `scripts/cli.py` 유일한 진입점 | 그대로 | 구조 테스트 |
| `scripts/<skill_name>/` 유일한 패키지 | `yfinance_skill/` | 틀의 접미사 문장은 stdlib 충돌을 말한다. 여기서는 스킬 이름 그대로면 의존 라이브러리 `yfinance`를 가리므로(`scripts/`가 `sys.path[0]`) 이전 결정 3으로 접미사를 붙인 기록된 예외다 |
| `<feature>/` 바뀌는 이유마다 | `querying/`(모듈 셋), `describe.py`(모듈 하나) | "단위는 패키지 바로 아래 모듈 또는 하위 패키지 … 두 번째 이유가 생기기 전까지 모듈은 패키지에 바로 있다". twitter `continuation.py`와 같은 선례 |
| `<system>/` 외부 시스템마다, 그 이름으로 | `yahoo/` | Yahoo의 데이터 의미와 yfinance API는 함께 바뀐다(이전 수용 가정) |
| `<store>/` 상태 종류마다 | `store.py`(관측), `export.py`(--out 파일) | 모듈 하나인 단위(M9). `export`는 "저장용 변환은 그 목적의 단위에 둔다"(system 항목)에 따라 `--out` 파일로의 변환·원자적 게시를 맡는 단위이고, `csv/` 시스템 폴더를 두지 않은 것은 이전 라운드의 기록된 설계 예외다(코덱스 확인, 재요구 없음) |
| `<helper>.py` 모든 종류가 공유 | envelope·shape·display·selection·budget·leaf | 공용은 공용만 import |
| 레포 `tests/` | `tests/yfinance`, `tests/test_skill_layout.py` | 테스트·픽스처·시뮬레이터만 |
| 레포 `<job>/` | `scenarios/yfinance/` | 결정 7 |

## 명령 표면 (PR ③)

### 루트 `--help` = 지도

```
usage: cli.py [--max-chars N] [--ttl-days N] COMMAND ...
Yahoo Finance data by purpose. stdout: one JSON document; stderr: diagnostics.
`<command> --help` states that command's kinds, arguments, output, what each kind's values mean, and exit codes.

commands:
  search QUERY                                   instruments, news, curated lists or research reports
  prices {quote,history,actions} SYMBOL...       quotes, historical bars and corporate actions
  company {profile,shares,news,filings} SYMBOL...
  financials {income,balance,cashflow,valuation} SYMBOL...
  analysts {targets,recommendations,upgrades,earnings-estimate,revenue-estimate,history,revisions,trend,growth} SYMBOL...
  holders {major,institutional,fund,insider-purchases,insider-transactions,insider-roster} SYMBOL...
  fund {overview,description,holdings,asset-classes,sector-weights,equity,operations} SYMBOL...
  options {expirations,chain} SYMBOL...
  screen {presets,fields,values,run}
  market {summary,sector KEY,industry KEY}
  calendar {earnings [SYMBOL],economic,ipo,splits}
  read ID                                        a saved observation again, in slices or to a file, without a new request
options: --max-chars (before or after COMMAND), --ttl-days (before COMMAND)
exit codes: 0 ok · 2 invalid · 4 local_io · 5 rate_limited · 6 upstream · 7 empty · 8 partial · 9 too_large (each with its meaning)
```

### `<group> --help` = 그룹 문서 (`<group> <kind> --help`도 같은 문서)

절 순서(앞이 짧고 공통, 뒤가 길고 kind별):

1. usage — kind마다 대상 모양을 반영(`prices {quote,history,actions} SYMBOL...`, `market {summary | sector KEY | industry KEY}`, `calendar earnings [SYMBOL]` 등), 그룹 목적 한 줄.
2. kinds — kind마다 목적 한 줄, `--out`이 없는 kind 표시.
3. arguments — 각 인자 한 번: 적용 kind(`[history, actions]`), choices, 기본값(formatter가 빠뜨리던 것 포함 — 도움말용 기본값은 별도 namespace에서 계산해 실행 파서·`given`·`chosen()`을 바꾸지 않는다), 필수·정확히 하나(`--query`|`--preset`), 모드(calendar earnings의 SYMBOL 유무), 거절되는 조합(`--repair`+`5d`).
4. shared arguments — `--fields`, `--list-fields`, `--filter`(C9 범위), `--limit`, `--timeout`, `--out`, `--max-chars`; `--ttl-days`는 COMMAND 앞.
5. output — 문서 `{status, request, results}`와 receipt 변형, 결과 봉투 키(`target, id, observed_at, source_time, stored_age_seconds, status, context, conditions, coverage, continuation, warnings, data, error`) 각 한 줄, 상태 `ok|partial|empty|error|not_attempted`, coverage 키, continuation(저장본의 다른 조각 — 새 요청 없음; F1의 재시작 표시 포함)과 `context.next_offset`(원천의 다음 페이지 — 새 요청)의 차이.
6. exit codes — 8개와 뜻.
7. what each kind returns — kind 머리줄 아래: 기본 창(행·필드)과 `a limit keeps …`, `units: <압축 JSON>`, interpretation·limits·gotchas 각 한 줄, `screen run`은 쿼리 문법(cli `epilog`).

- 연결: 표준 help action이 cli의 문서 렌더러를 부른다(`argv`에서 `--help` 문자열을 미리 찾는 식의 우회는 쓰지 않는다 — `--` 뒤 검색어를 잘못 처리한다). 그룹 파서와 그 kind 파서 전부가 같은 문서를 낸다(테스트가 바이트 비교). `prices history --help`, `screen run --help`, `search --help`, `read --help`는 필수 대상·쿼리·ID 없이 exit 0.
- `search`는 kinds 절 없이 같은 순서. 그룹 문서 크기는 단계 판정에서 측정해 기록만 한다(상한 단언 없음). 측정이 8천 자를 넘으면 kind별 의미의 중복 문장부터 줄인다.

### `read --help` = read 문서

usage, 목적, 인자(`ID`, `--start`, `--limit` — 저장 순서로 앞에서부터, `--fields`, `--list-fields`, `--filter`, `--out`, `--max-chars`; `--ttl-days`는 COMMAND 앞), output(같은 봉투 + `stored_age_seconds`, continuation은 다음 조각), 읽지 못하는 것(다른 저장 위치의 id, `--ttl-days`가 지운 것, 이 버전에 없는 명령의 레코드), exit codes.

### 표면에서 바뀌는 것 요약

- 없어지는 것: `schema` 명령, `analysts summary`, `market sectors`, `--store`, 루트 `--filter`, `read --timeout`.
- 그대로인 것: 남은 모든 호출 문법, 봉투 키와 순서, 상태·종료 코드 번호, `--max-chars` 기본 20,000, `--ttl-days` 기본 14, `--out` 계약, 저장 레코드 형식(R4의 새 레코드 `source_time` 표현만 ISO).
- 회복 문장·fix가 가리키는 곳: `schema …` → `<group> --help`, `read ID --store …` → `read ID …`.
- 실행 경로: 46 kind + `search` + `read`.

## SKILL.md 섹션 구조 (영어, 성진 전문 승인 대상)

```
---
name: yfinance
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: (현행 유지 — 트리거 문구가 바뀌지 않는다. 단계 12에서 skill-doctor로 이웃 경계만 확인)
---

# Yahoo Finance data

¶ Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` on one line. `--help` maps the commands and their kinds; `<command> --help` states that command's arguments, its output, what each kind's values mean (units, timing, windows, limits) and its exit codes; each error's `fix` says how to recover.
```

- 문단 하나(필수 인터페이스 — 9/27 제거 시험에서 나머지 세 문단은 행동을 바꾸지 않았다). `schema` 언급만 바뀐다.
- `references/`: 없음(C15).

## 동작 명세

각 항목은 CLI seam에서 손으로 쓴 리터럴 기대값의 재현 테스트가 먼저 red여야 한다(빨간 이유가 import·환경이면 무효). 기대값은 픽스처에서 손으로 셈한 행 번호·열 이름·키로 쓰고, CLI 출력에서 베끼지 않는다. 문장만 바꾸는 항목(F7·F8)은 문장 반복 테스트를 쓰지 않고(CONTRIBUTING) 해당 help·schema 출력을 눈으로 확인한다. 모든 재독 경로는 HTTP 요청 0(`routes=[]`)을 함께 단언한다.

### PR ① 구조 (행동 불변 — 골든 동일)

- **R1 `yahoo` 입구**: `dataset(key)`·`fetch(...)`·실패 타입만 공개(C5). `querying`의 `yahoo.refusals` import와 `yahoo.DATASETS` 직접 조회를 없앤다.
- **R2 실패를 스킬의 말로**: `yahoo.fetch`가 Yahoo의 실패를 C5의 타입으로 바꿔 올린다. `querying/observe`는 타입으로 코드(`rate_limited`·`upstream`)와 처방을 고르고, 처방 문장(지금 `refusals.upstream_fix`)은 `querying`으로 옮긴다. 부가 조회의 `context["rate_limited"]` 신호, 본 데이터 보존, 종료 코드 우선순위를 유지한다. 출력 문자열은 바이트 동일.
- **R3 결합**: `yahoo.bind` 삭제, `querying`·`schema`가 `Leaf(command, yahoo.dataset(key))`.
- **R4 시각**: 새 응답의 `source_time`(`info_time` 등)은 `yahoo`가 ISO로 넘긴다. 저장 레코드 형식의 주인인 `store`가 load할 때 옛 레코드의 숫자 `source_time`을 메모리에서 ISO로 정규화한다(원본 바이트·id 불변). `envelope.as_time` 삭제. 새 레코드는 `source_time`을 ISO로 저장한다(출력은 동일, 저장 표현만 바뀜 — 커밋 본문에 적는다). 테스트: 숫자 `source_time`을 가진 옛 quote 레코드 픽스처를 추가해 `read ID`와 `company profile SYMBOL --from ID`의 `source_time`이 리터럴 ISO 문자열.
- **R5 간격 사다리**: "다음 간격과 그것이 뜻하는 막대"는 `yahoo/prices`의 dataset 정책(`coarser(interval) -> (다음 간격, 막대 이름들) | None`)으로, 회복 문장의 `--interval X` 문구는 `budget`으로. `Command.coarser` 선언을 없애고 `Leaf.coarser`는 dataset에서 온다. `budget`은 `args`에 interval이 없으면(read) 제안을 만들지 않는다(현행).
- **R6 구조 테스트**: C4 ①②③과 v2 합성 트리 실패 픽스처. yfinance를 `UNITS`에 등록하면 R1 전에는 red(`querying.observe → yahoo.refusals`), R1–R3 뒤 green.
- **R7 기본 창을 명령 선언으로**(결정 11): `Dataset.rows`·`Dataset.fields`(QUOTE_FIELDS·PROFILE_FIELDS·NEWS_FIELDS·SCREEN_FIELDS·filings 필드 등)를 cli `Command`의 기본 창 선언으로 옮기고, `Leaf.limit`·`Leaf.fields`는 command에서 온다. `args.limit`·`args.fields`의 생략 상태는 그대로 둔다(argparse 기본값으로 채우지 않는다) — `selection.select`가 이것으로 `leaf_default`와 명시 요청을 가르고, 기본 필드의 결측은 넘기되 명시한 잘못된 필드는 거절한다. 원천에 개수를 보내는 kind는 `querying`이 실효 개수(명시 `--limit` 또는 명령의 기본 행 수)를 계산해 `yahoo.fetch(..., rows=N)`로 넘기고, 어댑터는 그 값을 원천 요청·`context.requested`·조건 판정·`next_offset`에 쓴다. `datasets.asked()`는 없어진다 — `screen_conditions`(`yahoo/screen.py:110`)는 이미 있는 `context["requested"]`를 쓴다. `search --dataset research`는 지금처럼 원천 개수도 `context.requested`도 두지 않는다(공통 fetch가 무조건 `requested`를 만들면 골든이 달라진다). 실효 개수는 지역 값·별도 인자로만 넘기고 `args`에 새 속성으로 넣지 않는다(저장 request에 섞인다, `cli.py:510-516`). `Leaf`는 지금처럼 인스턴스 속성 `limit`·`fields`를 갖고 값의 공급처만 command로 바꾼다(`out.exported`가 Leaf 사본의 기본 창을 비우므로, command를 직접 바꾸는 속성이면 공유 기본값이 훼손된다). PR ①의 `schema`는 `item.limit`·`item.fields`로 `default_window`를 만들므로 필드 순서·빈 필드의 `null`·`limit_keeps`를 유지하면 출력이 같다. `--out`은 표시용 기본 창을 무시하되 원천 요청 개수는 계속 적용한다(현행 `out.exported`와 같은 분리). `recent`·`precise`·`sliceable`·`shares_info`·`source_time`·`conditions`·`shortfall`·단위·해석·한계·함정은 yahoo에 남는다. 어댑터가 cli나 `Command`를 import하거나 기본 숫자를 다시 선언하지 않는다(C4 ①이 잡는다). 저장 request와 `chosen()`은 바뀌지 않는다. 판정: 골든 동일, 기존 요청 개수 테스트(`test_budget`·`test_market`·`test_company`의 `requested`) 그대로 green, 기본 projection을 기록된 payload 키와 대조하는 테스트(`test_discovery.py:123`) 유지.

### PR ② 결함

- **F1 꼬리 뒤 continuation**: 예산 축소가 최신 꼬리를 남긴 첫 결과(`recent` 리프 — 첫 호출의 continuation은 축소에서만 생긴다)의 continuation은 `{"start": 0, "restart": true, "shown": [a, b], "command": "read ID --start 0 --limit K"}`다. `shown`은 이미 보인 행의 저장 순서 반열린 구간 `[received-shown, received)`. read의 continuation은 지금처럼 전진(`restart` 없음). 테스트(새로 추가, 기존 `test_budget.py:129-145`는 read 자체의 재축소 회귀라 유지): 100행 픽스처를 예산으로 꼬리만 보인 첫 결과에서 continuation을 끝까지 따라가면 읽은 행이 0–99 각각 정확히 한 번, 첫 결과의 `shown`이 실제로 보인 행과 같음.
- **F2 양면 표의 진행**: `read --start S --limit L`은 side마다 `[S, S+L)`(축소면 더 작은 K)을 자른다. 다음 시작은 `S + max(side별 shown)`, 합계 `shown`은 통계에만 쓴다. 소진된 side는 빈 표와 자기 coverage, 모든 side가 `S`를 넘으면 지금처럼 invalid. 테스트: calls 60행·puts 45행·`--limit 20` → 체인이 calls 0–59·puts 0–44를 한 번씩, 오류 없음 / 처음부터 빈 side / 예산이 limit보다 작게 줄인 페이지에서도 건너뜀 없음.
- **F3 양면 표의 필드 목록**: `--list-fields`가 side 표의 열 이름(+인덱스 이름)을 낸다. 테스트: 픽스처의 열 집합을 리터럴로 단언하고 `calls.`·`.data` 같은 내부 키가 없음, 실제 열 하나(`strike`)를 `--fields`로 골라 두 side의 값이 픽스처 값과 같음, 인덱스 이름은 실제 열과 함께일 때만 받는 기존 계약 유지.
- **F4 양면 표의 예산 축소**: `budget.shrink`가 양면 표를 양면 선택으로 축소한다. 테스트 둘: (a) 행이 작은 픽스처 + 작은 `--max-chars` → 반드시 exit 8, 두 side의 행 수·값·coverage·continuation이 리터럴과 같고 id 보존 (b) 한 행도 담지 못하는 픽스처 → 반드시 exit 9, id 보존, 그 id를 큰 `--max-chars`로 `read`하면 원본 전부. 둘 다 stdout 길이 ≤ `--max-chars`, JSON 한 문서, 재독 HTTP 0.
- **F5 날짜 범위 재검증(✓10)**: `given` 스냅샷 뒤·저장소 열기 전, 기본값 적용 뒤에도 start ≤ end(가격은 start < end)를 다시 본다. 테스트: `calendar economic --end 2020-01-01` → exit 2, 요청 0, 저장소 미생성.
- **F6 `--repair` + `5d`**: history·actions 둘 다 요청 전에 invalid, fix는 "`--repair`를 빼거나 다른 interval". 테스트: 두 kind 각각 exit 2, 요청 0.
- **F7 intraday 문구**(원리 충돌 ④): limits에 고정 버전 라이브러리의 `period=max` 변환(1m 8일, 2m·5m·15m·30m·90m 60일, 60m·1h 730일 — "intraday의 max는 전체 상장 역사가 아님")을 숫자로 쓰고, Yahoo 서버의 요청당 일수·도달 범위는 원리 충돌 ④의 실패 문장으로 쓴다(해석 가능한 제약 메시지일 때만 fix가 그 값으로 처방). "60m/1h no range limit known"과 "넘으면 덜 주지 않고 실패한다"의 일반화는 지운다.
- **F8 뉴스 gotcha**: `content.thumbnail`·`content.storyline`.
- **F9 키 붙은 레코드(✓7)**: 값이 모두 레코드이고 표·양면 표가 아닌 매핑(`market summary`)은 화면·`read`·`--out` 어디서나 행으로 다룬다 — 키가 행, 행 순서는 모든 경로에서 **키 정렬 순서**(저장본이 이미 정렬 — 저장 형식 불변), `--fields`는 레코드 필드, `--limit`·`--start`는 정렬된 키에 적용, `--list-fields`는 레코드 필드 경로. 화면 출력은 매핑 모양을 유지한다. interpretation 문장을 고친다. 테스트: 키가 정렬되지 않은 원천 픽스처(`Z, A, M`)로 첫 조회 `--fields regularMarketPrice --limit 2` → `A, M`의 그 필드만, `read ID --start 1 --limit 2` → `M, Z`, 직접 `--out`과 `read ID --out`의 CSV가 `target,key,regularMarketPrice` 열·`A, M, Z` 순서로 같음, 예산 축소 뒤 continuation을 따라가면 세 키 모두.

### PR ③ 표면·상태

- **S5 저장 위치**(먼저): 기본 `<skill>/data/observations`(스킬 기준 경로 — `Path(__file__).resolve()` 기준이라 cwd와 무관, 심링크 설치는 실제 경로 쪽), `YF_STORE`가 있으면 그쪽, `--store` 삭제(파서·`SHARED`·`POINTER`·request 제외 목록·회복 문장·`LOCAL_FIX`·`store.py` 오류 문구 — 실제 경로를 말한다), 루트 `.gitignore`, C4 ④. 테스트: 사본에서 `YF_STORE`를 환경에서 지우고 실행 전 `data/observations` 부재 → 데이터 호출 → 반환 id의 `<id>.json` 존재. 사본 복사는 `ignore_patterns("__pycache__", "data")`로 개발 중 상태를 뺀다.
- **S1 루트 지도**, **S2 그룹 문서·read 문서**(`## 명령 표면`), **S3 `schema` 제거**(C7), **S4 kind 두 개 제거**.
- **S6 출력 설명의 빈칸**: 봉투 설명에 `context`·`continuation`·`stored_age_seconds`, 상태에 `not_attempted`, receipt 변형.
- **S7 `--filter` 범위**(C9). 테스트: 필터 없는 catalog 조회 성공 / catalog 단독 필터와 데이터·read의 `--list-fields --filter` 성공 / 효과 없는 자리의 `--filter X`와 `--filter ""` → exit 2, 요청 0, 저장소 불변 / `chosen()` 표시 불변.
- **S8 문구**: `cli.py:8,67,77,146,519`, `observe.py:111`, R2 뒤 querying의 처방, `yahoo/screen.py:82`. `budget.schema_fix`는 schema 전용 분기만 삭제하고, `item=None` 문서(최상위 invalid·local_io)의 크기 초과 처방은 일반 문장("Rerun with --max-chars N")으로 분리한다. 20,000자 바닥은 지금처럼 invalid 문서에만(`cli.py:523`) 두고, local_io 문서는 요청한 예산을 쓴다. 테스트 둘: 예산 안의 local_io 문서 → exit 4 / 예산을 넘는 local_io 문서(긴 저장 경로 + 작은 `--max-chars`) → exit 9, JSON 한 문서, 일반 크기 처방(schema 언급 없음).
- **S9 SKILL.md**(위 초안), **C17 `read --timeout` 삭제**.
- **S10 시나리오 실행기** `scenarios/yfinance/run.py`(`## 검증`).

## 테스트 이동 대응표 (PR ③, schema → 그룹 문서)

단언을 지우기 전에 새 자리를 먼저 만든다. 같은 테스트 수는 같은 보장의 증거가 아니므로 줄마다 대응시킨다. 모든 단언은 subprocess(CLI seam)로 한다.

| 지금 | 새 자리 |
|---|---|
| `test_discovery`: schema 카탈로그 = 파서 리프 | 루트 지도의 `{kinds}` = 각 그룹 파서가 받는 kind, 46 kind + search 전부 그룹 문서에 머리줄과 의미 절(결합 누락을 잡음) |
| 제거된 리프가 파서·schema에 없음 | + `analysts summary`·`market sectors`·`schema` → exit 2 |
| 리프마다 목적 + narrowing이 그 리프에서 쓸 수 있음(`:63-71`) | kind 목적은 kinds 절. narrowing은 kind·모드별로: 그 kind의 회복 문장이 이름 붙이는 인자를 그 kind 호출에 실제로 넣어 받아지는지(subprocess, 요청 0으로 끝나는 조합) |
| 리프의 실제 옵션 = 선언 옵션(`test_display.py:169-178`) | kind마다 그룹 문서의 `[kinds]` 적용 표시와 실제 파서의 수용·거절이 같음(적용 안 되는 kind에 넣으면 exit 2) |
| 실효 기본값(`test_cli.py:101-106,133-144`) | 그룹 문서의 기본값 표기는 손으로 쓴 리터럴 기대값과 대조(interval `1d`, adjust `auto`, periods `5`, `--max-chars` 20000, `--ttl-days` 14 …). 실제 행 창은 충분한 행의 픽스처 결과의 행 수로. `request` 비교는 실제로 메아리되는 실효 인자(기본값 함수가 채운 `period`·달력 날짜·프리셋 정렬)에만 — `chosen()`의 표시 계약은 바꾸지 않는다 |
| 종료 코드 전체(`test_cli.py:158-165`, `test_export.py:140-145`) | 루트 지도·11개 그룹 문서·read 문서 모두 8개 번호와 이름 |
| 기본 창이 있는 리프의 limit 방향 | kind 머리줄의 `a limit keeps …` |
| units 어휘·100배 충돌·fund 역수(`test_discovery.py:93-120`) | `units:` 줄의 JSON을 파싱해 같은 단언(`kind`·`scale`·`inverted`·`as_of`·`scale_by_quote_type`) |
| quote/profile 기본 필드·news 중첩 경로 | 그룹 문서 기본 필드 줄 |
| schema 리프 크기 ≤ 4,000 | 그룹 문서 크기 측정·기록(단언 없음) |
| `test_cli` schema 루트·예산·필터 | 루트 지도·그룹 문서 내용, help가 `--max-chars`와 무관하고 저장소를 만들지 않음(C8) |
| `test_display` schema 공통 포인터 | 그룹 문서에 공통 인자·출력 절 |
| `test_selection` schema 리프 | 그룹 문서 |
| `test_vocabulary` schema choices | `market --help`·`screen --help`의 choices + C13 |
| `test_budget` fund description narrowing·schema_fix | fund description의 too_large fix가 축소 인자를 권하지 않음 / S8의 일반 오류 문서 테스트 |
| `test_portability` `schema prices history` | `prices --help` + 픽스처 데이터 호출 + S5 기본 위치 |
| `test_store` 보존기간·로컬 실패를 schema로 촉발 | 오프라인 명령 `screen presets`로 촉발 |
| `test_live` 수집 시점 schema(`:41-48`) | 루트 `--help` 지도 파싱(저장소 안 엶). 방향·intraday 한계·쿼리 스케일·INDEX 단위 예외 확인(`:61,187,269,282`)은 그룹 문서의 해당 줄로 |
| `test_market` sectors ↔ choices | C13 |

## 작업 단계

단계는 곧 커밋이다. 테스트를 쓰는 단계는 `coding` 스킬을 연 상태에서 C10의 seam에서만 red → green으로 간다. 커밋·PR 제목은 `<타입>: <한국어 제목>`, PR 본문은 `## 무엇을 바꿨나/왜/영향/검증`, 머지는 `gh pr merge --squash`.

### PR ① `refactor/yfinance-unit-interfaces` — `refactor: yfinance 단위 입구와 Yahoo 경계를 정리한다`

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | 계획 파일 `mv`(안 됐으면), `main`에서 브랜치, 트래커 | 브랜치·트래커 존재, 계획 파일이 정식 이름 |
| 1 | **골든 캡처**: `.tmp/yf-golden`의 `capture.py`·`golden_plugin.py`로 루트·11그룹·49리프 `--help`, 모든 `schema` 범위, 오프라인 스위트의 모든 CLI 호출(argv·stdout·exit·`--out` 바이트)을 `.tmp/yf-golden-v3/before`에. 정규화는 `observed_at`·`stored_age_seconds`·16hex id·임시 경로·CLI 경로만. 캡처와 비교는 같은 날 | 두 번 캡처가 정규화 뒤 동일 |
| 2 | **R6 구조 테스트**: `UNITS`와 C4 ①②③, v2 합성 트리. 위반 픽스처마다 검사 구현 전 red 확인 → 구현 → green. yfinance 등록 | 위반 픽스처 red 기록 → green · yfinance 등록이 `querying.observe → yahoo.refusals`로 red · facebook·threads·twitter 결과 불변 |
| 3 | **R1–R5, R7**(R4는 숫자 시각 픽스처 테스트 먼저 red) | 기존 419개 전부 green + 새 테스트 green · 골든 동일 · 구조 테스트 green(yfinance 포함) · `test_boundary` green · `git grep -n "yahoo.refusals\|DATASETS\[\|as_time\|COARSER" -- .claude/skills/yfinance/scripts ':!*/yahoo/*'` 0 |
| 4 | **코덱스 리뷰 ①**(R1–R6, 구조 테스트가 증거로 믿을 만한지) → PR → 머지 | blocking·major 0, 머지 |

### PR ② `fix/yfinance-recovery-contracts` — `fix: yfinance 이어 읽기와 옵션 체인 계약을 바로잡는다`

| # | 단계 | 완료 판정 |
|---|---|---|
| 5 | **F1–F4**, 항목마다 red → green 커밋 | 재현 테스트가 수정 전 의도한 이유로 red 기록 · green · 스위트 green |
| 6 | **F5·F6·F9** red → green, **F7·F8** 문장 수정 | 재현 테스트 red → green · `schema prices history`·`schema company news`·`schema market summary` 출력에 새 문장 · 스위트 green |
| 7 | **코덱스 리뷰 ②**(continuation·선택 계약, 수정이 형제 경로를 깨지 않았는지) → PR → 머지 | blocking·major 0, 머지 |

### PR ③ `feat/yfinance-two-level-help` — `feat: yfinance help를 두 단계로 바꾸고 상태를 data로 옮긴다`

| # | 단계 | 완료 판정 |
|---|---|---|
| 8 | **S10 실행기 커밋 + 전 기준선**: `.tmp/yf-golden/scenarios/run.py`를 일반화해 `scenarios/yfinance/run.py`로(`--skill-dir`, `--scenario`, `--repeat`, 예산 조건, 복사에서 `data` 제외, 결과 `results.jsonl`: CLI 호출·발견 호출(첫 데이터 호출 전 help·schema 호출)·실패 호출·토큰·비용·시간·전제 성립 여부). 실행 결과는 `.tmp/yf-scenarios/<날짜>/`(커밋 안 함). PR ② 머지 뒤 `main` 워크트리의 스킬로 은행 24건 "전" 실행·판정 | 실행기 커밋 · CI·CONTRIBUTING ruff 대상 갱신 · ruff green · 24건 결과와 판정 기록 |
| 9 | **S5 저장 위치·`--store` 제거** + C4 ④(먼저 red) | 기본 위치 테스트 green · `git grep -n -- "--store\|args.store" -- .claude/skills/yfinance` 0 · 구조 테스트 green · `git status`가 `data/observations`를 보이지 않음 · 스위트 green |
| 10 | **S1–S4, S6–S8, C17** + SKILL.md 발견 문장(S9): 그룹 문서·read 문서·루트 지도, `schema`·두 kind 제거, 문구. `## 테스트 이동 대응표`대로 테스트 이동(새 자리 먼저, 옛 단언 나중). 이동한 테스트는 한 번 일부러 깨서 red 확인. 끝으로 C18의 네 성질 훑기(지운 문장과 이유는 커밋 본문) | 스위트 green · 모든 그룹·kind·read의 `--help` exit 0, 그룹과 kind help 바이트 동일 · 46 kind + search 전부 의미 절 · help가 `YF_STORE`를 만들지 않음 · 그룹 문서 크기 기록 · `git grep -n schema -- .claude/skills/yfinance` 0 · C18 훑기 완료: 렌더링된 루트·그룹·read 문서와 fix·warnings 문장 중 행동에 쓰이지 않는 출처·측정 경위가 0(줄 단위 판단, 커밋 본문에 지운·옮긴 문장 목록) |
| 11 | `docs/usage.md`·CONTRIBUTING 문서 갱신 | 문서 속 명령 전부 실행 성공 |
| 12 | **후 시나리오 + 승인**: PR ③ 브랜치로 은행 24건 "후" 실행·판정(`## 검증`). 코덱스가 SKILL.md를 네 성질로 검토. 성진이 SKILL.md 전문 승인. `claude plugin validate --strict .claude/skills`. `claude -p "/skill-doctor"`로 이웃(finviz·sec) 경계 확인. **코덱스 리뷰 ③**(전체 diff + 루트 지도 + 그룹 문서 11개 + read 문서: 문서의 각 주장에 대응하는 테스트나 코드, C8, 단위 규칙) | 시나리오 합격 기준 충족 · 성진 전문 승인(부분 승인·침묵은 승인 아님) · validate exit 0 · skill-doctor 충돌 0 · 리뷰 blocking·major 0 · 근거 없는 help 주장 0 |
| 13 | PR ③ → 머지, graphify 리빌드(로컬), 이 파일 끝에 `# 구현 기록`(계획과 달라진 곳과 이유, 시나리오 전후 표, 원리 충돌의 해소가 구현에서 어떻게 됐는지, 남은 한계와 불확실성, 기본값을 교정하는 문장이 어느 모델 기준인지, `grep -rn "성진:"`), `main`에 직접 커밋(`docs: yfinance 코드 설계 판단 반영 구현 기록`) | 머지 · 기록 커밋 |

## 검증

```bash
# 오프라인 스위트 + 구조 테스트 (CONTRIBUTING·CI와 같은 환경)
bash -c 'set -euo pipefail; mkdir -p .tmp; uv export --quiet --script .claude/skills/yfinance/scripts/cli.py --no-hashes -o .tmp/yf-test-req.txt; uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/yf-test-req.txt --with pytest==8.4.2 python -m pytest tests/yfinance tests/test_skill_layout.py -q'
uv run --isolated --no-project --python 3.12 --with-requirements .tmp/yf-test-req.txt --with pytest==8.4.2 python -m pytest tests/yfinance -q   # 선언 범위의 하한
python3 -m pytest tests/ --ignore=tests/sec --ignore=tests/finviz --ignore=tests/yfinance -q   # CI offline 잡: 다른 스킬 + 구조 테스트
uvx ruff check --config pyproject.toml .claude/skills/yfinance/scripts tests/yfinance tests/test_skill_layout.py scenarios/yfinance
uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/yf-test-req.txt --with pytest==8.4.2 python -m pytest tests/yfinance -m live -q   # PR ②·③ 끝에 한 번씩
claude plugin validate --strict .claude/skills
```

- **골든**(PR ①): 단계 1의 캡처와 단계 3 뒤 캡처가 정규화 뒤 동일.
- **live**: 46 kind + search 기본 옵션 스윕에서 상태와 열·필드 이름 집합만 본다(값은 매일 바뀜). PR ③ 뒤 `data/observations`에 관측이 생기는지 한 번 손으로 본다.
- **모델 시나리오**(C12, `scenarios/yfinance/run.py`)
  - 하네스: 스킬을 공백이 든 새 임시 경로에 복사(`data` 제외), 사본 SKILL.md의 `${CLAUDE_SKILL_DIR}`를 사본 경로로 치환, `scripts/` 소스 읽기 금지, 런마다 새 `YF_STORE`, cwd는 런 디렉터리, 사본마다 uv 환경을 순서대로 미리 데움(9/27 기록의 두 결함).
  - 실행: `claude -p --safe-mode --restricted --permission-mode acceptEdits --tools "Bash,Read,Write" --allowedTools "Bash" --model claude-opus-5-5 --output-format stream-json --verbose "<prompt>" < /dev/null`.
  - 세트: 은행 24건. `budget: true`인 8건은 "모든 CLI 호출에 `--max-chars 3000`을 붙이고 올리지 않는다" 조건. 전제(`premise`)가 성립하지 않은 런은 한 번 다시 돌고, 두 번 모두 미성립이면 "미검증"으로 적는다(그 경로를 검증했다고 말하지 않는다).
  - 실행 실패와 판단 실패를 가른다(skill-maker: 파일·도구·권한 부족으로 실패한 결과는 전문성의 증거가 아니다): 판정 전에 각 런을 ① 실행 가능성(`permission_denials`, CLI가 한 번이라도 돌았는지, uv 환경 준비 실패·Bash 시간 초과, 네트워크 오류) ② 전제 성립 ③ 의미 판정 순서로 본다. ①에 걸린 런은 원인을 보완(권한·사전 준비·과제 축소)하고 다시 돌리며, 보완하지 못하면 "미검증"이다. 유효한 런만 합격·회귀 판정에 쓴다. 단, 환경 실패로 빼는 것은 **외부 실행 장애가 확인된 경우뿐**이다(권한 거부, 하네스·uv 준비 실패, 원인을 확인한 네트워크 장애). 시간 초과·네트워크 오류도 발생 사실만으로 빼지 않고 원인을 본다. 모델이 CLI를 부르지 않았거나 잘못 불렀거나 회복에 실패한 것은 판단 실패이고, CLI가 정상적으로 돌려준 오류 응답(invalid·upstream 등)도 자동으로 빼지 않는다.
  - 하네스의 한계: `--tools "Bash,Read,Write"`로 Bash를 되살린 실행은 플래그와 임시 디렉터리만으로 격리되지 않는다(skill-maker). 그래서 런은 스크래치 경로에서, 레포 밖 사본으로만 돌리고, 결과 해석에서 이 한계를 적는다.
  - 판정: 클로드가 답을 `expect`와 대조해 합격·불합격을 적는다.
  - 합격: "후"에서 전제가 성립한 모든 시나리오가 `expect` 충족 · 스킬 원인 실패 호출 런당 ≤ 1 · "전"에서 합격한 시나리오가 "후"에서 불합격하지 않음 · 발견 호출 수 중앙값이 "전"보다 작음 · 핵심 전제(예산 partial, id 있는 too_large, 다대상 too_large, 부족분 경고)마다 전후 각각 유효 표본 ≥ 1. 토큰·비용은 기록만 한다.
  - 판정 모델·조건·결과는 PR ③ 커밋 본문과 `# 구현 기록`에. 모델이 바뀌면 같은 세트로 재검토한다.

## 계약이 서로 물린 곳 (하나만 고치면 깨진다)

- **명령·데이터셋 결합**: cli `COMMANDS`의 `dataset` 키 ↔ `yahoo.dataset(key)` ↔ `Leaf` ↔ 그룹 문서의 kind별 의미 절(전부 렌더링하는 테스트) ↔ 저장 레코드의 `command` 경로(경로를 바꾸면 옛 관측이 읽히지 않음 — `tests/yfinance/fixtures/store`).
- **그룹 문서**: cli의 인자 선언·`epilog` + `describe`가 넘기는 의미 + `envelope`의 봉투 설명 ↔ 테스트가 파싱하는 고정 줄(kind 머리줄, `a limit keeps`, `units:` JSON, `exit codes`) ↔ SKILL.md의 한 문단.
- **저장 위치**: `store.py` 기본 경로 ↔ `YF_STORE` ↔ `conftest.py`·`test_live.py`·`test_discovery` ↔ 루트 `.gitignore` ↔ 구조 테스트 C4 ④ ↔ `test_portability`·시나리오 실행기의 복사 제외(`data`).
- **레코드 시각**: `yahoo`의 ISO `source_time` ↔ `store.load`의 옛 숫자 정규화 ↔ 숫자 시각 픽스처.
- **이어 읽기**: `budget.shrink`·`querying/read`·`selection`(양면·키 붙은 레코드, 키 정렬 순서) ↔ 첫 결과의 continuation에서 출발하는 테스트 ↔ 그룹 문서의 continuation 설명(재시작 표시).
- **실패**: `yahoo` 실패 타입 ↔ `querying`의 코드·처방 ↔ cli `EXIT_CODES`·`exit_code()` 우선순위.
- **종료 코드**: cli `EXIT_CODES` ↔ 루트 지도·그룹 문서·read 문서의 exit codes 절 ↔ `budget.emit`의 (status, codes).
- **요청 개수**(R7로 바뀜): cli `Command`의 기본 행 수 ↔ `querying`이 계산한 실효 개수 ↔ `yahoo.fetch(..., rows=N)` ↔ 어댑터의 원천 요청·`context["requested"]`·`next_offset`·조건 판정 ↔ `Dataset.shortfall` ↔ 레코드 최상위 `requested` ↔ `asked_for`(첫 호출·`--out`·read) ↔ `budget.shrink`의 보존.
- **예산 사다리·닫힌 선택지 리터럴·units 어휘**: 이전 기록의 물린 곳 그대로(`SECTOR_KEYS`의 대조 대상만 C13으로 바뀜).

## 하지 않는 것

- 지식만의 스킬로 재작성, 스킬 없음·지식만 조건의 대조(결정 2).
- yfinance 라이브러리 캐시 이동(결정 8), 옛 관측 이관, 제거 kind의 legacy 해석기(C2).
- screen run 쿼리 조건 판정, ADR EPS 단위(결정 9).
- twitter의 `tests/twitter/model/` 이동, 다른 세 스킬의 #5 이행(레거시 조항).
- in-process 테스트 seam, `csv/` 시스템 폴더, 산업 키·`--sort`·`--field`의 choices화, CI 재활성화, 텍스트 렌더러, 단일 모듈 단위의 폴더화(M9 "두 번째 이유가 생기기 전까지 모듈").

# 구현 기록 (2026-10-02)

## 결과

- PR #34 `refactor: yfinance 단위 입구와 Yahoo 경계를 정리한다` (f9cd7fb) — R1–R7, 구조 테스트 C4 ①②③.
- PR #35 `fix: yfinance 이어 읽기와 옵션 체인 계약을 바로잡는다` (d6d969e) — F1–F9.
- PR #36 `feat: yfinance help를 두 단계로 바꾸고 상태를 data로 옮긴다` (d27369d) — S1–S10, C4 ④, C17, C18.
- 마지막 검증(main d27369d 기준 브랜치 끝): 오프라인 스위트 + 구조 테스트 545 passed(3.13), yfinance 479 passed(3.12), CI offline 잡 1569 passed, ruff 통과, live 68 passed·5 skipped, `claude plugin validate --strict .claude/skills` exit 0, skill-doctor 충돌 보고 없음, graphify 로컬 리빌드(5,412 노드).
- 성진이 SKILL.md 전문을 승인했다(본문 한 문단만 바뀜, description·allowed-tools 그대로).

## 계획과 달라진 곳과 이유

- **`yahoo/catalog.py`를 더했다.** 계획의 트리에는 없다. 입구 `__init__`이 하위 모듈 객체를 바인딩하지 않고 DATASETS를 노출하지 않으려면 사전과 가져오기를 둘 모듈이 필요했고, `datasets.py`에 두면 순환 import가 된다. 구조 테스트가 catalog 내부 접근을 위반으로 잡는다.
- **PR ①의 행동 불변에 예외 하나를 두었다.** R4가 시각 변환을 저장 앞으로 옮기자 달력에 없는 epoch(1e30)가 저장 전에 실패해 id를 잃었다(코덱스 리뷰 ①). 변환을 전 함수로 만들어 그 값은 받은 그대로 두었다 — main은 exit 6(id 있음), 이후는 exit 0(id 있음). main의 "저장 후 실패"를 재현하려면 R4가 지운 변환을 envelope에 되살려야 했다. C1이 클로드의 결정이라 PR 본문에 명시하고 진행했다.
- **구조 검사기는 계획보다 훨씬 커졌다.** 리뷰 ①과 두 번의 재확인에서 스코프(지역 import·인자·대입의 가림, 기본값·데코레이터·컴프리헨션 첫 iterable의 평가 스코프), 재수출(다른 모듈을 거친 하위 모듈 바인딩), 속성 사슬의 기능 간선, patch 계열 문자열(모듈 우선 해석, 별칭 호출, `target=` 키워드), job의 전체 점 경로, 일반 문자열 오탐이 차례로 드러났고 모두 실패 픽스처를 먼저 두고 고쳤다. 동적 import·문자열 조립은 여전히 범위 밖이다.
- **F1–F4를 커밋 하나로 묶었다.** 네 수정이 `select_sides`·`following`·`shrink`·`continuation`에 걸쳐 항목별 커밋은 덩어리 수술이 필요했다. 커밋 본문에 항목마다 red 근거를 적었다.
- **market summary의 narrowing에 `--limit`을 더했다(F9의 귀결).** 거래소가 행이 되어 `--limit`이 실제로 줄이므로 회복 문장이 그것을 말해도 된다. 그에 맞춰 옛 단언 둘(narrowing에 --limit 없음, `--limit 1`의 --out이 SNP)을 바꿨다.
- **`--store` 제거로 도달할 수 없게 된 테스트 하나를 지웠다.** 단일 종목 earnings의 too_large 회복 테스트는 `--store`가 회복 문장을 늘려 만든 거절이었고, 그 없이는 한 행이 최소 예산 안에 들어간다. 모드별 금지 narrowing은 `search --type` 테스트가 계속 맡는다.
- **argparse 약어를 껐다.** 문서의 인자 태그를 파서와 대조하는 테스트가 `screen presets --field region`이 `--fields`의 약어로 받아들여지는 것을 찾았다.
- **그룹 문서에 계획에 없던 줄 둘을 두었다.** `narrow with:`(회복이 이름 붙일 인자, 모델이 미리 줄일 축이자 테스트 seam)와 `same as [kind]:`(같은 그룹의 같은 사실을 한 번만 쓰기 — 8천 자 지침에 따른 중복 제거). 단일 레코드 kind는 `--limit does not apply`를 쓴다.
- **그룹 문서 크기는 8천 자를 넘는 것이 많다**: search 7017 · prices 11982 · company 10952 · financials 9230 · analysts 10127 · holders 9062 · fund 9427 · options 7486 · screen 9970 · market 8815 · calendar 9116 · read 6714 · 루트 3233. 넘는 몫은 모든 문서에 실리는 공통 계약(공유 인자·출력·종료 코드 약 4.9천)과 kind 고유 사실(quote의 기본 필드 41개·units 23개 등)이고, 같은 문장의 두 번째 사본은 C18에서 지웠다.
- **시나리오 실행기**: restricted 모드의 Read는 작업 디렉터리만 보므로 cwd를 런 디렉터리(스킬 사본을 담은 곳)로 두었다. 모델이 한 Bash 명령에 CLI를 여러 번 체인하거나 셸 변수로 부르므로 발견 호출은 CLI 실행 단위로 센다(`discovery_invocations`), `--summarise`로 저장된 스트림에서 다시 집계한다.
- **골든**: main을 분리 워크트리로 두고 자정 이후 같은 날 캡처했다(달력 기본값이 오늘이라). basetemp는 공백 없는 `$TMPDIR`(레포 경로의 공백이 shlex 따옴표로 바뀐다), 비교에는 mkstemp 접미사 정규화를 더했고, `--out` 경로 길이를 고정하는 테스트 때문에 라벨 길이를 맞췄다.
- **live**: PR ②에서 intraday 탐침의 "limits에 구간별 키" 단언을 `intraday_range` 문장 확인으로 바꿨다(F7이 의도적으로 바꾼 계약). 탐침 자체(원천 거절과 fix의 일수)는 live로 통과.
- **코덱스 리뷰 횟수**: ①은 리뷰 + 재확인 2회, ②는 리뷰 + 재확인 1회, ③은 리뷰 + 재확인 2회. 마지막 확인의 NEW minor(market sector의 top-etfs·top-funds도 `--limit`이 자르지 않는 매핑)는 시나리오가 쓰지 않는 문장이라 후 시나리오 뒤에 고쳤다(7db9296).

## 모델 시나리오 전후 (C12, claude-opus-5-5)

전 = main d6d969e의 스킬, 후 = 브랜치 83dcac4의 스킬(이후 변경은 market 문장 하나). 실행기 `scenarios/yfinance/run.py`, 결과 `.tmp/yf-scenarios/2026-10-02/{before,before-retry,after-final,after-final-retry}`(커밋 안 함).

| 기준 | 전 | 후 |
|---|---|---|
| 유효 런의 expect 합격 | 22/22 | 18/18 |
| "전" 합격 → "후" 불합격 | – | 0 |
| 발견 실행(첫 데이터 실행 전 --help·schema) 중앙값 | 5 | 2 |
| 스킬 원인 실패 호출 런당 | 최대 2(schema 범위·크기 오류, 단일 레코드 --out) | ≤ 1 |
| 핵심 전제 유효 표본: 예산 partial / id 있는 too_large / 다대상 too_large / 부족분 경고 | 1 / 3 / 2 / 1 | 2 / 1 / 0 / 0 |
| 비용(초회 24건) | $3.95 | $4.86 |

- 전제 미성립(두 번 모두): 전 budget-spy-drops·budget-income-ten. 후 budget-spy-drops·budget-income-ten·budget-balance-five·budget-balance-other-five·budget-profile-officers(모델이 처음부터 --out으로 받거나 한 번에 들어옴), news-all(원천).
- **후의 다대상 too_large와 부족분 경고는 미검증이다.** 다대상 재무제표 시나리오는 후 런 여섯 번 모두 경로가 생기지 않았고, 부족분 경고는 Yahoo가 AAPL 뉴스를 0건 주는 외부 상태 때문이다(main 스킬·yfinance `get_news` 직접 호출 모두 0건, 2026-10-02 08시 KST). 성진 결정으로 미검증 기록 후 머지했다. 두 경로의 CLI 동작은 오프라인 테스트가 덮는다.
- 시나리오별 판정 표는 아래 두 절에 그대로 옮긴다.

### 전 판정

| id | 전제 | 판정 | 발견 실행 | 비고 |
|---|---|---|---|---|
| five-year-trend | – | 합격 | 5 | 2021-10-01~2026-10-01, 최신까지 |
| toyota-pe | – | 합격 | 5 | 통화 불일치 명시, USD·JPY 각각 일관 계산 |
| spy-pe | – | 합격 | 5 | 1/0.04035 = 24.78, 역수 명시 |
| earnings-surprise | – | 합격 | 4 | 0.0674 → 6.74% |
| one-day-calendar | – | 합격 | 5 | 그날 기업 나열, 날짜 조건 확인 |
| blackrock-position | – | 합격 | 4 | 6/30 보유 vs 현재가 평가액 구분 |
| screen-tech | – | 합격 | 5 | 실패 호출 1(screen run 필드 오류, 모델 인자 선택) |
| compare-three | – | 합격 | 5 | 세 종목 모두 |
| unplanned | – | 합격 | 5 | 단위·한계 명시 |
| mdd | – | 합격 | 5 | 1,254일, 기간 명시 |
| growth-screen | – | 합격 | 5 | 임계 20(퍼센트 포인트), 100억; 실패 호출 1(필드 오류) |
| ko-dividend | – | 합격 | 5 | 2.46%·62.5%, 필드 명시 |
| msft-pe-trend | – | 합격 | 5 | Current를 TTM 스냅샷으로 설명 |
| qqq-top10 | – | 합격 | 5 | 기간·가격 기준 명시 |
| correlation | – | 합격 | 5 | --out 전 행, 751 표본 |
| date-close | – | 합격 | 5 | 20행 |
| budget-five-year-close | 성립(partial) | 합격 | 5 | read로 나머지 읽음 |
| budget-spy-drops | 미성립 ×2 | 미검증(전제) | 5 | 두 번 다 바로 --out, 답은 맞음 |
| budget-balance-five | 성립(too_large+id, 다대상) | 합격 | 4 | 저장 id를 read --out; 실패 호출 1(schema read exit 2 — 스킬 원인) |
| budget-income-ten | 미성립 ×2 | 미검증(전제) | 5 | 두 번 다 바로 --out, 답은 맞음 |
| budget-balance-other-five | 성립(다대상 too_large) | 합격 | 6 | 실패 호출 3 중 스킬 원인 2(schema too_large, schema read exit 2), 1은 전제의 too_large |
| news-all | 성립(부족분 경고) | 합격 | 5 | 200건을 "전부"라 하지 않음 |
| budget-quote-every-field | 성립(단일 레코드 too_large+id) | 합격 | 4 | 실패 호출 4 중 스킬 원인 2(schema prices quote too_large, read --out 단일 레코드 exit 2) |
| budget-profile-officers | 성립 | 합격 | 6 | 임원 10명·요약 전문 |
- 전제가 성립했거나 전제가 없는 22건 모두 합격. 핵심 전제 유효 표본: 예산 partial 1(budget-five-year-close), id 있는 too_large 3, 다대상 too_large 2, 부족분 경고 1.
- 발견 실행(첫 데이터 실행 전 --help·schema 실행) 중앙값 5. 스킬 원인 실패 호출은 발견 단계(schema 범위 오류·schema 크기 초과)와 단일 레코드 --out.
- 비용 합계 $3.95(재실행 제외), 런당 20–137초.

### 후 판정

| id | 전제 | 판정 | 발견 실행 | 비고 |
|---|---|---|---|---|
| five-year-trend | – | 합격 | 2 | 2021-10-04~2026-10-01; 실패 1은 이전 런이 /tmp에 남긴 같은 --out 경로(환경, CLI가 덮어쓰기 거절) |
| toyota-pe | – | 합격 | 3 | 통화 불일치 명시, EPS를 달러로 환산 |
| spy-pe | – | 합격 | 3 | 1/0.04035, 역수 명시 |
| earnings-surprise | – | 합격 | 3 | 0.0674 → 6.74%, 달력 값과 환산 일치 |
| one-day-calendar | – | 합격 | 2 | 그날 행 확인 |
| blackrock-position | – | 합격 | 2 | 6/30 보유 vs 현재가 평가액 구분 |
| screen-tech | – | 합격 | 3 | 실패 1(필드 선택, 모델) |
| compare-three | – | 합격 | 2 | 세 종목 |
| unplanned | – | 합격 | 2 | 단위·한계 |
| mdd | – | 합격 | 3 | 1,254일 |
| growth-screen | – | 합격 | 3 | 임계 20·100억; 실패 2(스크린 필드 오류, prices quote --out — 둘 다 문서가 이미 막는 모델 선택) |
| ko-dividend | – | 합격 | 3 | 2.46%·62.46% |
| msft-pe-trend | – | 합격 | 2 | Current를 TTM 스냅샷으로 |
| qqq-top10 | – | 합격 | 3 | 기간·기준 명시 |
| correlation | – | 합격 | 3 | 752 표본, 파일로 전 행 |
| date-close | – | 합격 | 2 | 20행 |
| budget-five-year-close | 성립(partial) | 합격 | 2 | 1,254행을 read 조각으로 모두 읽음 |
| budget-quote-every-field | 성립(단일 레코드 too_large+id) | 합격 | 2 | 187개 필드 전부; 실패 2 중 1은 전제의 too_large, 1은 --list-fields에 --limit(모델) 뒤 fix대로 --filter |
| budget-spy-drops | 미성립 ×2 | 미검증(전제) | 3 | 바로 --out, 답은 맞음 |
| budget-income-ten | 미성립 ×2 | 미검증(전제) | 2 | 바로 --out, 답은 맞음 |
| budget-balance-five | 미성립 ×2 | 미검증(전제) | 2 | 바로 --out, 다섯 회사 모두 |
| budget-balance-other-five | 미성립 ×2 | 미검증(전제) | 2 | 바로 --out, 다섯 회사 모두 |
| budget-profile-officers | 미성립 ×2 | 미검증(전제) | 3 | 한 번에 들어옴, 임원 10명·요약 전문 |
| news-all | 미성립 ×2(원천) | 미검증(전제) | 2 | Yahoo가 AAPL 뉴스를 0건 반환(main·yfinance 직접 호출로 확인, 외부 상태); search news로 46건, "전부 아님" 명시 |
- 합격 기준: 유효 런 전부 합격, "전" 합격 → "후" 불합격 0, 발견 실행 중앙값 5 → 2, 스킬 원인 실패 호출 런당 ≤ 1 — 충족. 핵심 전제 유효 표본(후): 예산 partial 2(budget-five-year-close, news-all 재실행), id 있는 too_large 1 — 충족; 다대상 too_large 0, 부족분 경고 0 — 미충족, 성진 결정으로 미검증 기록 후 머지.
- 비용 $4.86(초회) + 재실행, 런당 18–166초.

## 원리 충돌의 해소가 구현에서 된 모습

- ① 사실의 소유와 배치: 입력 계약(인자·choices·기본값·모드·배타·쿼리 문법)은 cli의 인자 help와 `epilog`, Yahoo 사실(단위·해석·한계·함정)은 yahoo dataset, `describe`가 넘기고 cli가 배치한다. C18에서 같은 사실의 두 사본을 지울 때도 이 기준으로 남길 쪽을 골랐다(`--end` 배타 → 인자, 날짜의 거래소 시간대 → kind 의미).
- ② 닫힌 집합: 프리셋·섹터·지역·interval은 choices이고 `test_vocabulary`가 라이브러리 값과 대조한다(섹터 키는 `SECTOR_INDUSTY_MAPPING_LC`, C13). 산업 키·스크린 필드는 발견 kind와 fix.
- ③ 상태: 관측만 `data/observations`, yfinance 라이브러리 캐시는 기본값(결정 8). 구조 테스트 C4 ④는 스킬 코드만 본다.
- ④ 숫자와 실패: yfinance 1.7.0의 `period=max` 변환은 숫자로, Yahoo 서버의 intraday 한도는 거절과 fix로 쓴다(F7).
- ⑤ 단일 모듈 단위: `describe.py`·`store.py`·`export.py`.
- ⑥ 기본 창: cli `Command(rows, fields)`, 개수를 보내는 데이터셋(`counted`)은 querying이 실효 개수를 `rows`로 넘긴다.

## 남은 한계와 불확실성

- 시나리오는 런 한 번씩(전제 미성립만 한 번 더)이라 실사용 여러 세션의 성능을 증명하지 않는다. 성진의 SKILL.md 승인도 그 증거가 아니다.
- 후의 다대상 too_large·부족분 경고 경로는 모델 시나리오로 확인되지 않았다(위). 원천이 뉴스를 다시 주면 news-all을 다시 돌릴 수 있다.
- 그룹 문서가 최대 약 1.2만 자다. 길이가 모델의 주의를 흩는지는 함정 시나리오의 합격 유지로만 간접 확인했다(spy-pe·toyota-pe·earnings-surprise·ko-dividend·growth-screen·blackrock-position 모두 합격).
- Yahoo 서버 한도와 응답(뉴스 0건처럼)은 예고 없이 바뀐다. 문서는 한도를 거절과 fix로 쓴다.
- 구조 검사는 정적 접근만 본다(동적 import·조립된 문자열은 범위 밖).
- 시나리오 하네스는 `--tools Bash,Read,Write`로 Bash를 되살리므로 격리되지 않는다. 런은 레포 밖 임시 경로의 사본으로만 돌렸고, 모델이 `/tmp`에 남긴 파일이 다음 런과 부딪힌 경우가 한 번 있었다(five-year-trend의 --out 경로, CLI가 덮어쓰기를 거절해 무해).

## 기본값을 교정하는 문장의 기준 모델

그룹 문서의 kind별 의미(역수 배수, 퍼센트·비율 충돌, 통화 분리, 시각 혼합 등)와 회복 문장은 claude-opus-5-5 시나리오로 확인했고, 리뷰는 gpt-6-astra(high, read-only)가 했다. 모델이 바뀌면 같은 은행으로 다시 본다.

## `성진:` 장부 (yfinance 스킬·테스트)

`grep -rn "성진:" .claude/skills/yfinance scenarios/yfinance tests/yfinance tests/test_skill_layout.py` — 24곳, 모두 코드의 불변조건·한계 설명이다. 이번에 더한 것은 `store.py`의 옛 epoch 정규화와 `selection.py`의 "투영을 먼저 하고 자른다" 둘이다.

## 후속 과제

- twitter의 `tests/twitter/model/`을 레포의 하는 일 폴더로 옮기기, facebook·threads·twitter의 skill-maker #5 이행(UNITS 등록 포함).
- 원천이 뉴스를 다시 주면 news-all 시나리오 재실행.
