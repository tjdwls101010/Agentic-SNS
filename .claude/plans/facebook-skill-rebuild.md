# facebook 스킬 재작성 계획

> 계획 모드가 경로를 고정해 이 이름으로 시작했다. **구현 세션의 첫 동작**: `mv ".claude/plans/claude-skills-facebook-transient-avalanche.md" ".claude/plans/facebook-skill-rebuild.md"`. `.claude/plans/`는 커밋하지 않는다(공개 레포 — `git add`는 언제나 경로를 지정한다).

## Context

`.claude/skills/facebook`은 Claude가 사용자의 로그인된 Aside 브라우저로 페이스북을 읽게 하는 스킬이다(읽기 전용). 목표인 "사람처럼"은 **판단이 사람 같다**는 뜻이다. 통신은 페이스북 내부 API로 빠르고 구조적으로 하고, 무엇을 열고 언제 멈출지, 피드→글→댓글→댓글 단 사람→소개→검색→그룹을 어떻게 잇는지는 SKILL.md의 판단이 맡는다. 예전에 만들어 `skill-maker` 프레임(트리·data/·테스트·구조 테스트·명령별 --help 계약·import 방향·SKILL.md 4속성)을 충분히 반영하지 못했다. 성진은 성공 기준을 품질 하나로 두고 **완전 재작성**을 택했다. 결과물은 프레임을 철저히 따르는 새 스킬이고, 검색·그룹·페이지 고도화와 댓글 스레드를 필요한 만큼 끝까지 펼쳐 읽는 역량이 더해진다.

## 결정 요약 (성진과 합의)

| # | 결정 | 계획에 미치는 영향 |
|---|---|---|
| D1 | 공개 배포, 대화형 | 개인 선호는 스킬에 넣지 않는다. 사실·계정 보호·도구 의미론만 싣는다. 무인 실행 규칙은 범위 밖. Aside 계정을 하드코딩하지 않는다(Aside 기본 계정, `FACEBOOK_ASIDE_ACCOUNT`로 지정 가능). |
| D3 | 완전 재작성 (Claude는 고정→이관을 권했음) | 기존 코드의 지식을 먼저 계약 종류별로 목록화(부록 A)하고 합성 픽스처로 옮긴 뒤 새로 쓴다. |
| D4 | 대표 과제: 피드 훑기·주제별 모으기 / 한 글의 댓글 여론 / 특정 인물·페이지 파악 / 검색·그룹 탐색과 대량 수집 | 대조 실행 과제 8개(부록 C)의 출처. |
| D5 | '사람처럼' = 판단 | 화면 조작 경로는 만들지 않는다. 통신 방식은 정찰(R1)로 결정. |
| D6 | 범위: 검색·그룹·페이지 고도화 + 댓글 스레드 끝까지(필요할 때 펼침) | `replies` 명령, 검색 필터·그룹 내 검색, 그룹/페이지 정보. 사진 다운로드·관계 탐색(친구·반응자)은 범위 밖. |
| D7 | 영어 | SKILL.md·references·help·오류 메시지. description에 한국어 트리거 유지. |
| D8 | 개발 기록은 커밋·PR 본문 | 실제 인물·피드 내용·토큰은 빼고 적는다. 별도 docs 파일을 만들지 않는다. |
| D9 | 검증 모델 Opus 5.5만 | 대조 실행 `--model claude-opus-5-5`. |
| D10 | 개발 중 실계정 하루 300요청, 여러 날 분산 | 코드 장부 없이 **구현 세션이 수동 집계**한다(D17). 차단 신호가 보이면 즉시 중단. |
| D11 | 일회용 계정 없음 → 정찰도 실계정, 최소 요청 | 대량 refresh 실험 금지. 정찰 총량 ≤ 80요청. |
| D12 | 사진 대체텍스트: 응답에 있으면 추가 요청 없이 싣기 | `media[].alt`. "자동 생성·틀릴 수 있음"을 스키마에 적는다. |
| D13 | 실제 응답 로컬 캡처 허용, 끝나면 삭제 | `tests/facebook/captures/`(gitignore). 머지 전 삭제. 커밋 픽스처는 합성만. |
| D14 | 기존 캐시 `~/.cache/facebook-skill`은 새 스킬 라이브 검증 후 통째 삭제 | 삭제 직전 성진에게 한 번 더 확인. P2 정찰까지는 옛 캐시가 권위 있는 보호 상태이고, 새 코드의 첫 라이브 요청 전에 일회용 스크립트로 `data/protection/`에 이관한다(P3). |
| D15 | 탭 안 호출이 유리하면 스킬 전용 facebook.com 탭 하나를 열어 두고 재사용 | 사용자가 연 탭은 건드리지 않는다. 전용 탭 targetId를 `data/`에 기록하고, 사라졌으면 다시 연다. |
| D16 | 같은 폴더에서 브랜치 작업(worktree 안 씀) | 재작성 기간에는 이 프로젝트에서 페이스북 스킬을 일상 사용하지 않는다. 롤백 = main은 머지 전까지 그대로. 컷오버 = P7 머지. |
| D17 | 하루 누적 상한을 스킬에 넣지 않음 | 호출당 상한(기본 25, 최대 400)만 둔다. 개발 중 300/일은 구현 세션이 각 출력의 `requests=`를 `$WORK/budget-ledger.tsv`(레포 밖)에 적어 지킨다. |
| D18 | 받은 결과를 보관해 다시 보여 주는 `show` 명령은 두지 않음 | 텍스트는 미리보기(`text[N of M chars shown]`)다. 전문은 글 URL 핸들(`post <url>`)로 연다. 공유 출력 파일을 두지 않아 나중 호출이 앞 결과를 덮어쓰지 않는다. |
| D19 | 페이싱 1–2초 무작위 유지 | 차단 신호가 한 번이라도 나오면 그때 늘린다. |
| D20 | 대조 대상: 9월 대상 재사용 + 새 역량은 Claude가 고름 | 옛 스킬 답과 같은 대상으로 회귀 비교(부록 C). |
| D21 | 배포 = 폴더 복사(프로젝트/사용자 스킬), 플러그인 아님 | 스킬은 자기 폴더만으로 완결된다(레포의 다른 파일을 참조하지 않음). 상태는 스킬 폴더 `data/`. 플러그인 매니페스트는 만들지 않는다. |

## 근거 원장 요약

- **사실**: 기존 코드 4,771줄, 테스트 0. 원 소스 레포는 사라졌다. 레포 `tjdwls101010/Agentic-SNS`는 PUBLIC이고 PR 템플릿이 없다. 번들 doc_id 7개 전부가 6주 안에 회전했다(번들 7/26 vs 캐시 오버라이드 9/5). 9월 대조 실행 실측은 다음과 같다.
  - 오늘 피드 ~90개 = 21–22요청, 프로필 60개 = 22요청, About = 9요청, post+첫 댓글 = 4요청
  - 매 호출 setup = 토큰용 홈 HTML 1 + 대상 id 해석 HTML 1
  - Aside REPL 타임아웃 1회
  - 9월 ablation으로 "Order decides…"·"Choosing whom to follow" 섹션이 빠졌다.
  - Node 22.14 있음. `claude`에 `--safe-mode`(스킬 끔)·`--restricted`(Bash 제거)·`--no-session-persistence`·`plugin validate --strict`가 있다.
  - pytest 9는 `pythonpath`를 설정 파일 기준 상대경로로 푼다(Codex 확인).
- **프레임 위반(현행)**:
  - 상태가 `~/.cache`에 있다.
  - 하위 명령 help에 출력·실패·종료코드가 없다.
  - system→store import가 있다.
  - `cli.py`에 도메인 로직이 있다.
  - 구조 테스트가 없다.
- **추론(정찰로 검증)**: 사진 대체텍스트가 응답에 실려 있다(R2). 탭 안 호출이면 토큰·doc_id를 살아 있는 페이지에서 얻을 수 있다(R1). 답글은 `repliesAfterCursor`로 다음 묶음을 받을 수 있다(R3).
- **수용한 가정**:
  - 9월 대조 실행의 모델 행동(Opus 계열)이 지금 Opus 5.5에서도 대체로 같다. P6의 A 실행이 다시 확인한다.
  - 페이스북 차단 기준은 비공개이고, 9월 실측(이틀 ~250요청, 1–2초 간격, 무차단)이 안전 범위의 유일한 근거다.
  - 9월 대상 글은 아직 존재한다.
- **열린 질문** (구현 중 해소, 해소 주체):
  - R1–R6 판정 — 정찰 증거
  - 탭 이동 요청 셈 단위 — R1 측정
  - references 필요 여부 — P6 증거
  - ultra-search와의 트리거 경계 — skill-doctor 보고 후 성진

## 접근

1. **지식 먼저, 코드 나중.** 기존 코드에 묻힌 지식을 계약 종류별(레코드 / 전송·분류 / 요청 직렬화 / 페이지네이션 / 영속화)로 부록 A에 목록화한다. 각 항목을 합성 픽스처(또는 입력 사례)와 **사실에서 도출한** 기대값으로 옮긴다.
   - 기존 파서(main)에 레코드 픽스처를 넣어 같은 결과가 나오는지 보는 것은 **차분 호환성 증거일 뿐**이다. 현실성 증거가 아니다(기존 파서는 넓은 모양을 받아들인다).
   - 불일치가 나도 픽스처를 기존 동작에 맞춰 "수리"하지 않는다. 원인을 판정해 기록한다.
   - P2 이후에는 실제 캡처를 사람이 직접 읽어 확인한 기대값으로 픽스처를 보정한다.
2. **통신 방식은 정찰로 고른다(R1).** 기준은 우선순위 순으로 ① 계정 안전(요청 수, 실제 앱과 같은 요청) ② 구조화된 결과 ③ 쿼리 id 회전 자동 대응 ④ 속도다. 어느 쪽이든 `graphql` 시스템 패키지의 인터페이스는 같다.
3. **TDD는 수직 슬라이스로 한다.** CLI 골격과 구조 테스트를 먼저 세운다. 그다음 명령 하나씩, 가짜 Aside를 통한 CLI 프로토콜에서 행동 red를 보고 구현한다. 레코드·페이징·저장소·스니펫처럼 안정 계약인 단위 인터페이스는 그 자리에서 테스트한다.
4. **SKILL.md는 새 CLI 위에서 대조 실행 증거로 쓴다.** CLI만 / 초안 / 섹션 제거 ablation을 돌리고, 4속성 검토와 보류 사례 확인을 따로 한다.
5. **Codex(gpt-6.1-sol, medium) 독립 검토**를 다음 시점에 받는다.
   - 이 계획(완료, 아래 '검토 반영' 참조)
   - 공유 계약(보호 상태·수집 파일·CLI 출력 계약·스니펫 프로토콜)이 녹색이 된 직후
   - SKILL.md 초안
   - 머지 전 최종

## 목표 트리

```
.claude/skills/facebook/
├── SKILL.md
├── references/              # 대조 증거가 '한 갈래에서만 필요한 판단'을 보여줄 때만 (P6 게이트). 없으면 폴더도 없음
├── data/
│   └── .gitignore           # "*" + "!.gitignore" — 런타임 상태는 절대 커밋 안 됨
└── scripts/
    ├── cli.py               # PEP 723(requires-python>=3.11, deps 없음). parser·help·dispatch·exit code·출력 형식 선택만
    └── facebook/
        ├── __init__.py
        ├── aside/           # system: Aside CLI. `aside repl` 1회 실행 → envelope, 청크 재조립, 타임아웃·연결 끊김 분류
        ├── graphql/         # system: Facebook 웹 클라이언트. URL 형식·대상 id 해석·세션 토큰·쿼리 id(번들 스냅숏+발견)·요청 직렬화·응답 분류(차단/로그인/빈 결과/stale)·@defer 디코드·병합·레코드 변환·JS 스니펫
        ├── guard.py         # store: 계정 보호(차단·페이싱·프로세스 간 잠금). 요청 단위 임계구역 `request()`를 제공한다. data/protection/
        ├── handles.py       # store: 번호 핸들(more:·replies), 쿼리 문맥 결속, 포맷 버전, TTL 만료. data/handles/
        ├── collection.py    # store: --out NDJSON(페이지 단위 커밋·재개·무결성·포맷 버전)
        ├── listing.py       # feature: feed·profile·group 글 목록(정렬·날짜 창 정책·광고 처리)
        ├── thread.py        # feature: post·comments·replies(필요할 때 펼침)
        ├── search.py        # feature: 검색 수직·필터·그룹 내 검색
        ├── about.py         # feature: 프로필 About·페이지 정보·그룹 정보 카드
        ├── maintenance.py   # feature: doctor·refresh
        ├── connect.py       # feature 공용 배선: guard + aside + graphql.Client를 묶어 예산 있는 세션을 연다
        ├── paging.py        # helper: 범용 커서 페이지네이션(서버 순서·중복 제거·미표시 꼬리·커서 반복 감지·경계 콜백). 페이스북 고유 정책 없음
        ├── results.py       # helper: 결과 어휘(kind·stop_reason·coverage·exit kind)
        ├── render.py        # helper: 조밀한 텍스트 페이지
        ├── errors.py        # helper: FacebookError + 진단 scrub
        └── paths.py         # helper: data/ 경로(테스트·대조 실행용 env `FACEBOOK_DATA_DIR` 덮어쓰기)

Agentic SNS/ (소스 레포)
└── tests/facebook/
    ├── pytest.ini           # [pytest] pythonpath = ../../.claude/skills/facebook/scripts  (pytest 9.x, 설정 파일 기준 상대경로)
    ├── test_structure.py
    ├── fixtures/            # 합성 응답만(실존 인물·피드 없음)
    ├── fake_aside.py        # FACEBOOK_ASIDE_BIN으로 주입하는 가짜 aside(합성 envelope 반환 + 받은 snippet 기록)
    ├── snippet_harness.mjs  # Node로 실제 JS 스니펫을 가짜 fetch/openTab/page로 실행해 나가는 요청을 기록
    ├── captures/            # gitignore. 정찰 때 받은 실제 응답(로컬 전용, 머지 전 삭제)
    └── test_*.py
```

**단위 경계와 import 규칙** (구조 테스트가 그대로 검사한다):
- 단위는 `aside/`·`graphql/`(패키지 — 공개 인터페이스는 `__init__.py`가 내보내는 이름)과 나머지 모듈(공개 인터페이스는 밑줄 없는 최상위 이름)이다.
- 방향은 features(`listing` `thread` `search` `about` `maintenance` `connect`) → systems(`aside` `graphql`)·stores(`guard` `handles` `collection`) → helpers(`paging` `results` `render` `errors` `paths`)다.
- system↔store, system↔system, store↔store import는 없다. `graphql.Client`는 `guard`(요청 임계구역을 여는 객체)와 snippet 실행기를 **생성자 인자로 받는다**. 그래서 `graphql`은 `guard`·`aside`를 import하지 않는다.
- 허용하는 feature 간 간선은 `listing|thread|search|about|maintenance → connect` 하나뿐이다.
- 단위 밖(테스트 포함)에서 `facebook.graphql.<하위모듈>`이나 `_밑줄` 이름을 import하지 않는다. 절대·상대 import와 재내보내기를 모두 검사한다.
- 스킬 코드는 `sys.path`를 건드리지 않는다. `data/`에 커밋된 파일은 `.gitignore`뿐이다. 최상위 이름은 `cli.py` + 패키지 `facebook/`이다.

## CLI 인터페이스 계약 (정찰 결과로 세부 조정)

호출은 언제나 `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` 한 줄이다. `allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)`.

| 명령 | 하는 일 | 비고 |
|---|---|---|
| `feed [--sort top\|recent] [--since/--until] [--include-sponsored]` | 홈 피드 | 최신순 + since면 창이 닫힘 |
| `profile <profile\|page> [--since/--until]` | 타임라인(서버 필터 창) | 페이지 타임라인 동작은 R6 |
| `group <group> [--sort top\|recent\|activity] [--since/--until]` | 그룹 피드 | |
| `about <profile\|page\|group>` | 정체 카드: 프로필 About / 페이지 정보 / 그룹 정보 | 페이지·그룹은 R5 |
| `post <post-url>` | 글 전문 + 첫 부모 댓글 묶음, 각 부모의 답글 핸들 | 전문을 여는 핸들 |
| `comments <post-url> [--sort …]` | 부모 댓글 페이지 단위 | 정렬 종류·의미는 R3 |
| `replies <handle>` | 한 댓글 아래 답글 한 묶음, `more:`·답글의 답글 핸들 | 신규 (R3) |
| `search <text> [--type top\|posts\|people\|pages\|groups] [필터…] [--in-group <group>]` | 검색 | 필터는 R4 |
| `doctor [--unblock]` | Aside·로그인·차단·쿼리 상태, 사용 중인 페이스북 계정 id | 항상 JSON |
| `refresh` | 쿼리 id 갱신 | R1 결과로 자동화되면 축소/제거 |
| `schema [object]` | 결과·파일·레코드 필드 설명, 요청 0 | 항상 JSON |

공통 옵션: `--limit` `--chars` `--after` `--out` `--json` `--max-requests`(기본 25, 상한 400 — `성진:` 주석 유지).

**출력 계약** (각 `<command> --help` epilog에 그 명령 기준으로 전부 적는다):
- **텍스트(기본)**:
  - 첫 줄은 싼 신호다. `<command> · <정렬/유형> · N shown · stopped=<reason> · requests=<used>/<budget>`.
  - 날짜 창이 있으면 `window <since>..<until> · <coverage>`.
  - 레코드(`[p1]`/`[c1]`/`[e1]`)마다 다음 명령의 인자(글 url·author url·`replies <n>`)를 붙이고, 본문은 `text[N of M chars shown, complete|truncated]`로 표시한다.
  - 그 뒤에 `coverage:` 줄, 마지막에 실행 가능한 `more: <command>`.
- **`--json`**: envelope JSON 하나(ok·command·options·stop_reason·request_count·max_requests·coverage·next·error·message·fix·results).
- **`--out`**: 요약 한 줄(`--json`과 함께면 같은 내용을 JSON 객체 하나로). `--out`과 `--after`는 함께 쓸 수 없다(종료 2).
- **실패**: 언제나 envelope JSON 하나(error·message·fix). 부분 결과가 있으면 results 포함.
- **비싼 상세** (잘린 레코드마다 경로가 있어야 한다, D18):
  - 글은 `post <url>`(그 글만 가리키는 핸들)로 연다.
  - 댓글·답글이 `--chars`로 잘렸으면, 페이지 끝에 `detail: <이 페이지를 만든 명령 그대로 + --chars 0>`를 찍는다. 이어 읽기 페이지라면 같은 `--after n`이다. 핸들은 소비되지 않고 같은 커서를 다시 읽으므로 그 페이지를 겨냥한다.
  - About 필드는 자르지 않는다.
  - 모든 상세 경로는 **라이브 재요청**이라 앞 응답의 재현을 보장하지 않는다. help와 `schema result`에 그렇게 적는다.
  - 공유 출력 파일을 두지 않아 나중 호출이 앞 결과를 덮어쓰지 않는다.
- **핸들**: `data/handles/`에 단조 증가 번호와 포맷 버전으로 둔다. 쿼리 문맥(명령·대상·정렬·필터·페이스북 계정)에 결속하고 TTL이 지나면 만료한다. 만료·문맥 불일치·옛 포맷이면 종료 2와 함께 "원 쿼리를 다시 실행하라"는 fix를 준다.
  - **번호는 절대 재사용하지 않는다.** 카운터는 `data/handles/counter`에 두고, 정리(TTL·P7)는 핸들 파일만 지우고 카운터는 지우지 않는다.
  - 성진의 환경에서는 P3의 일회용 이관 스크립트가 옛 캐시 카운터(`~/.cache/facebook-skill/cursors/counter`) + 1000으로 카운터를 심는다. 그러면 9월 기록 등에 남은 옛 `--after n`이 새 결과를 가리킬 수 없고, 파일 없음으로 거부된다. 스킬 코드는 옛 경로를 모른다.
- **종료코드**: 0 성공(재개 가능한 예산 정지 포함) · 2 인자 오류/다른 쿼리의 핸들·파일 · 3 Aside 불가 · 4 로그인 필요 · 5 차단(체크포인트·rate limit·보호 상태 읽기 불가) · 6 레코드 전 요청 실패 · 7 명시적 빈 결과 · 8 부분 결과. 각 명령 help는 그 명령에서 날 수 있는 코드만 적는다.
- **stdout**에는 결과만 쓰고, 진행·진단은 stderr로 보낸다(`--verbose`는 scrub된 요청 메타데이터).

**요청 집계 (호출당 `requests=`의 정의)**: 스킬이 명시적으로 시작한 네트워크 동작을 1로 센다. 대상은 GraphQL 요청, HTML 페이지 요청, 정적 번들 요청, 재시도다. 시간 초과로 결과를 모르는 동작은 예산에서 빼지 않는다(기존 `capture`의 예약 규칙). **탭 열기·이동의 셈 단위**(이동 1회로 셀지, 페이지가 스스로 일으키는 GraphQL까지 셀지)는 R1에서 측정해 정하고, 그 전에는 예산 주장이나 통신 방식 채택을 하지 않는다. 확정된 정의를 `--help`와 `schema result`에 적는다.

**계정 보호 의미론 (기존 동작 유지)**:
- `guard.request()`는 프로세스 간 잠금을 쥔 임계구역(slot)을 연다. 그 안에서 다음을 한 덩어리로 처리한다.
  1. guard가 차단 확인 → 예산 확인 → 페이싱 대기를 한다.
  2. `graphql.Client`가 요청 실행 → 응답 분류(페이스북 코드 해석은 graphql만 안다)를 한다.
  3. 차단이면 `slot.block(reason)`으로 기록한다.
  4. guard가 다음 허용 시각을 기록한다.
- 잠금을 놓으면 다른 호출이 차단을 보기 전에 요청하는 틈이 생기므로, 이 순서를 한 임계구역에 둔다. guard는 페이스북 코드를 모르고, graphql은 상태 파일을 모른다.
- 체크포인트는 무기한 차단이다. 사람이 브라우저에서 확인한 뒤 `doctor --unblock`으로 푼다.
- rate limit(429·1357004)은 30분 차단이다. 1357054는 페이싱 후 1회 재시도하고, 다시 나면 rate limit으로 본다.
- 요청 간격은 1–2초 무작위다. 보호 상태를 읽을 수 없으면 차단으로 취급한다(fail closed).

## SKILL.md 구조 (영어, 잠정 — 각 섹션은 P6 증거 게이트를 통과해야 남는다)

```
---
name: facebook
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: >-  표면 목록(feed·post·comments·replies·profiles·pages·groups·About·search) + 한국어 트리거
                 + 경계(Threads·Instagram·X·Reddit·Naver Blog·일반 웹·페이스북 회사 뉴스·쓰기 동작 아님)
---
# Facebook through the person's own browser
  호출 한 줄 규칙 · --help 두 단계(루트 지도 → 명령) · schema · 오류의 fix
## Every request spends the person's account
  체크포인트는 그 사람 계정에 걸리고 그 사람만 푼다 · 팬아웃은 요청을 곱한다 → 몇 명/몇 그룹이 필요한지 먼저 정한다
  · 답이 나오면 멈추고 안 읽은 것을 말한다 · 복구(refresh)도 같은 계정 활동이라 동의를 받고 한다 · 차단 해제는 사람의 몫
## What Facebook chose to show
  피드는 페이스북이 고른 것 · 최신순만 날짜 창을 닫는다, 랭킹은 표본 · 프로필 창은 서버 필터
  · 타임라인의 글이 모두 주인이 쓴 것은 아니다(작성자로 귀속) · 공유 글은 원작자의 말
## Comments are a tree opened branch by branch
  부모 먼저 → 질문에 필요한 가지만 펼친다 · 정렬(관련도는 걸러진 순위)을 보고에 적는다 · 읽은 만큼만 주장한다
## Who someone is before what they say
  동명이인 · 사람/페이지/그룹 구분 · 인증 배지 · About은 보는 계정에 따라 다르다
## What a partial result can support
  잘린 본문 · 미리보기는 전문이 아니다 → 결론을 바꿀 수 있으면 post로 연다 · coverage 줄은 한계로 보고하고 "없음"으로 바꾸지 않는다
  · unavailable 핸들 · 대체텍스트는 기계 생성
## Collections hold other people's data
  --out은 대화에 다 못 읽을 때만 · data/와 수집 파일엔 타인 정보 → 레포 밖·작업 후 삭제 · 보호 상태는 지우지 않는다
```

**모든 섹션에 걸치는 두 가지** (프레임 "Writing judgment down"). 어느 섹션에 둘지는 P6 증거로 정한다.
- **되돌리기 어렵거나 큰 비용을 미리 묶는 선택은 동의를 받고 한다.** 대상: `refresh`(같은 계정으로 많은 요청), `doctor --unblock`(사람이 브라우저에서 확인해야만 의미가 있음), `--max-requests`를 크게 올린 대량 수집, 여러 사람·그룹으로의 팬아웃. 사람이 이미 정했거나 모델에 맡겼으면 묻지 않는다.
- **답을 넘기기 전에 성립해야 할 것**(모델이 확인할 수 있는 말로):
  - 읽은 범위와 순서(랭킹/최신)를 밝혔다.
  - 안 읽은 것(coverage, 펼치지 않은 가지, 잘린 본문)을 "없음"으로 바꾸지 않았다.
  - 인용·주장은 작성자에게 귀속했다.
  - 보존할 것(이 세 가지)과 자유롭게 달라도 되는 것(요약 형식·길이·말투 — 사람의 몫)을 구분한다.

각 섹션은 다음 조건을 모두 만족해야 남긴다.
1. **증거**: CLI만(A) 실행에서 결함이 관찰됐거나, 섹션 제거(C) 실행에서 회귀가 관찰됐다.
2. **4속성**: 원칙+이유+성립 조건+뒤집히는 조건이 있고(레일이 아님), 인터페이스가 이미 말하는 것의 복사가 아니고, 모델용이며(출처·측정 경위는 PR로), 조밀하다. 모델 기본값을 고치는 줄은 피할 구체 행동과 이유를 쓴다("generic하게 하지 말라" 식 금지).
3. **권위 종류 표시**(작성 노트에서, 본문에는 결과만): 줄마다 확인 가능한 사실 / 플랫폼 제약(이유 필수) / 취향 중 무엇인지 분류한다. 공개 스킬이므로 **취향은 싣지 않고** 그 사람이 대화에서 정하게 둔다.
4. **경계 판정 주체**: 원칙이 가까운 사례를 가르는 경계가 애매하면, 추출에 쓰지 않은 보류 사례(부록 C)에 원칙을 적용해 본다.
   - 판정이 **확인 가능한 사실**에 달렸으면 라이브 증거나 코드로 정한다.
   - **취향**에 달렸으면 스킬에서 정하지 않는다(공개 스킬 — 사용자의 몫).
   - 성진은 도메인 판정자가 아니라 목표·요구사항의 주인이다. 보류 사례 결과는 성진에게 보여 목표와 어긋나는지만 확인받는다.

"추가할 판단 없음"도 정당한 결과다. 숫자 한도·기본값은 쓰지 않고 그 한도가 일으키는 실패를 쓴다. 출처·측정 경위·어느 모델을 보고 쓴 줄인지는 PR 본문으로 보낸다.

## references 구조 (조건부)

P6에서 **한 갈래에서만 필요하고 길이가 큰 판단**이 확인될 때만 만들고, SKILL.md의 그 갈래에 "언제 읽을지" 포인터를 둔다. 후보는 둘이다.
- `references/search.md`
  - Search verticals and what each returns
  - Filters and what they can prove
  - Finding the right person/page/group
  - Searching inside a group
- `references/collecting.md`
  - When a file beats reading
  - Resume and integrity
  - Analysing a collection without re-reading
  - Deleting what was gathered

레코드 필드·파일 포맷은 `schema`(인터페이스)가 맡고 references에 복사하지 않는다.

## 테스트 (합의할 이음새)

| 이음새 | 무엇을 검증 | 남는 미검증 |
|---|---|---|
| **CLI 프로토콜** — 진짜 `cli.py`를 하위 프로세스로, `FACEBOOK_ASIDE_BIN=fake_aside.py`, `FACEBOOK_DATA_DIR=<tmp>` | 인자·help·stdout 형식·종료코드·핸들·`--out` 파일·보호 상태 파일, 부분 결과 우선순위, 재시도, 이어 읽기 | 실제 브라우저·페이스북 응답 형식 |
| **스니펫 프로토콜** — `snippet_harness.mjs`가 실제 JS 스니펫을 Node 22에서 가짜 `fetch`/`openTab`/`page`/`console`로 실행 | 나가는 요청(호스트·경로·메서드·헤더·폼 필드)이 독립 명세와 일치, 읽기 전용(허용 friendly name만 POST), 큰 본문 청크·서러게이트 경계, 인자 검증 실패 | 실제 Aside REPL 환경 차이 |
| **graphql 레코드 인터페이스** — 원응답 바이트 → 레코드(순수) | 부록 A의 레코드·분류 항목, P2 이후 캡처로 보정한 픽스처 | 아직 못 본 응답 변형 |
| **paging 코어** | 서버 순서, 중복, 경계 콜백 정지, 미표시 꼬리, 커서 반복 | — |
| **stores** — 실제 파일시스템 | `guard`: 임계구역(두 프로세스 경쟁), 차단 기록·만료, fail closed. `handles`: 문맥 불일치·TTL·옛 포맷 거부·번호 재사용 없음. `collection`: 페이지 커밋·중단 꼬리 재생·다른 쿼리/옛 포맷 파일을 **한 바이트도 바꾸지 않고** 거부·무결성 | — |
| **구조 테스트** | 위 '단위 경계와 import 규칙' 전부 | — |
| **로컬 캡처 검사**(커밋 안 함, 없으면 skip) | 새 파서가 실제 응답에서 예상 밖 issue 없이 레코드를 만든다 | 캡처 이후 형식 변화 |
| **라이브 스모크**(opt-in `FACEBOOK_LIVE=1`) | feed·post·replies·about·search 각 ≤5요청. 성공 조건은 실행 성공이 아니라 단언이다: 레코드 ≥1, 필수 필드(id·url·author_url·created_at 또는 undated 표시·text) 존재, stop_reason이 기대값, `requests=`가 상한 이하, 핸들이 다음 명령으로 실제 이어짐 | 시간 초과·체크포인트·동시 실행·처음 보는 응답 변형은 스모크로 검증되지 않는다(분류 로직은 픽스처·CLI 프로토콜 테스트가 맡고, 실제 발생 여부는 미검증으로 PR에 적는다) |

- 실행은 `uv run --with 'pytest>=9,<10' pytest -c tests/facebook/pytest.ini tests/facebook`이다. 종료코드를 그대로 보고하고 `| tail`로 가리지 않는다.
- 진입점 배선을 바꾼 슬라이스는 마지막에 진짜 `cli.py`를 한 번 실행해 본다.
- 구조 커밋과 행동 커밋을 나눈다. 재작성 슬라이스는 각자 red → green 커밋을 남긴다.

## 단계 (각 단계의 완료 판정)

파일을 바꾸는 단계가 3개 이상이므로 구현 세션 시작 시 `TaskCreate`로 아래 단계마다 트래커를 열고, description에 완료 판정을 그대로 적는다.

**P0 준비** — 페이스북 요청 0
- **`$WORK` 정의**: `/Users/seongjin/.claude/projects/-Users-seongjin-Coding-Agentic-SNS/facebook-rebuild/`. 레포 밖이고 비공개이며 세션이 바뀌어도 남는다(세션별 scratchpad는 여러 날에 걸친 장부·하네스를 잃는다). 장부·정찰 하네스·이관 스크립트·대조 실행 디렉터리, 그리고 단계마다 쌓는 **PR 본문 초안 `$WORK/pr-body.md`**(P1 매핑표·P2 판정·P6 대조 결과표가 여기 모인다)가 모두 여기 있다. P7에서 PR 본문으로 옮길 때 익명화하고 실데이터를 지운다.
- 계획 파일 이름을 바꾼다.
- `main`에서 `feat/facebook-skill-rebuild` 브랜치를 판다.
- 트래커를 연다.
- 루트 `.gitignore`에 `tests/facebook/captures/`를 추가한다.
- 레포 밖 `$WORK/budget-ledger.tsv`(날짜·명령·requests)를 만든다.
- **이웃 스킬 확인**(프레임: 쓰기 전에): 프로젝트 루트에서 `claude -p "/skill-doctor"`(읽기 전용 보고)를 실행한다. facebook과 트리거를 공유하는 스킬(threads·twitter·reddit·naver-blog·ultra-search 등)과 그 경계를 `$WORK/pr-body.md`에 적는다. P6 description 재작성의 입력이 된다.
- 완료: 브랜치·트래커·장부·skill-doctor 보고가 있고 `git status`에 계획 파일이 추적되지 않는다.

**P1 지식 목록 → 합성 픽스처** — 요청 0
- 부록 A 항목마다 계약 종류에 맞는 합성 입력(응답 픽스처, 요청 기대값, 저장소 시나리오)과 사실에서 도출한 기대값을 만든다(데이터만 만들고, 테스트 코드는 P3 슬라이스에서 쓴다).
- 레코드 항목은 기존 파서(`git show main:` → 임시 디렉터리)에 넣어 차분 호환성을 기록한다.
- 완료: 부록 A 전 항목 ↔ 입력·기대값 매핑표(PR 본문 초안)가 있고, 레코드 항목은 기존 파서와 일치하거나 불일치마다 판정(픽스처 문제 / 기존 동작이 사실과 다름)이 기록돼 있다.

**P2 라이브 정찰** — 실계정, 총 ≤ 80요청(장부 기록). 응답은 `tests/facebook/captures/`에만 저장한다.
- **보호된 실행**: 새 코드가 아직 없으므로, 정찰의 모든 요청은 `$WORK/recon/`의 작은 하네스를 거친다. 하네스는 `git show main:`으로 꺼낸 옛 보호 코드(`account.py`의 `account_lock`·`check_blocked`·`set_blocked`, `transport.py`의 `classify`·`_pace` 의미)를 감싼다.
  - 상태는 **권위 있는 단일 보호 상태**인 옛 캐시(`~/.cache/facebook-skill`)를 쓴다.
  - 요청마다 잠금 → 차단 확인 → 페이싱 → `aside repl` → 분류 → 새 차단 기록 순서로 처리한다.
  - 시작 전에 활성 차단이 있으면 중단하고 성진에게 알린다.
- R1 통신 방식: 세 방식을 비교한다.
  - (a) 탭 밖: 현행 REPL fetch + 홈 HTML 토큰 + 레지스트리
  - (b) 매번 여는 탭: `openTab` + `page.evaluate` fetch, 페이지 런타임의 토큰, 로드된 `*_facebookRelayOperation` 모듈의 doc_id
  - (c) 전용 탭 재사용(D15): `listBrowserTabs`/`attachBrowserTab`
  - 측정 항목은 호출당 setup 요청 수, 탭 이동이 일으키는 배경 요청을 우리가 셀 수 있는지, doc_id 자동 획득(지연 로드 모듈 포함), 120초 한도 안 안정성, 응답 모양 동일성이다.
- R2 사진 대체텍스트(`accessibility_caption` 등) 위치·존재율.
- R3 댓글: 정렬 종류와 의미(관련도·최신·전체), `repliesAfterCursor`로 두 번째 답글 묶음, 답글의 답글(depth 2) 펼침, `focusCommentID`로 댓글 단위 재진입 가능 여부.
- R4 검색 필터(최신 글·날짜·출처)와 그룹 내 검색 쿼리.
- R5 그룹 정보(공개 범위·멤버 수·설명·규칙)와 페이지 정보(분류·팔로워·소개) 쿼리.
- R6 페이지 타임라인이 프로필 타임라인 쿼리로 읽히는지.
- 판정은 "가능 / **불가로 입증됨**(근거) / **미확정**(예산 안에서 못 밝힘)" 셋으로 나눈다. 합의된 역량(D6)을 빼는 것은 범위 결정이므로 근거·대안과 함께 **성진의 동의를 받는다**. 미확정을 불가로 처리하지 않는다.
- 완료: R1–R6 판정과 근거가 PR 본문 초안에 있고, R1의 통신 방식이 결정돼 있으며, 빠지는 역량은 성진의 동의를 받았다.

**P3 코어 재작성 (수직 TDD)** — 요청은 스모크만
- (구조) CLI 골격 + 구조 테스트 + 빈 단위 경계(import 가능한 stub).
- (보호) `guard` 임계구역·차단·페이싱 + 옛 캐시 보호 상태 이관.
  - 이관 시점부터 권위 있는 보호 상태는 스킬의 `.claude/skills/facebook/data/protection/` 하나다.
  - 이관은 스킬 코드가 아니라 **일회용 스크립트**(`$WORK/migrate_state.py`, 커밋 안 함)로 첫 라이브 요청 전에 한 번 한다. 옛 상태가 있는 사람은 성진뿐이므로, 공개 스킬에 옛 경로 지식을 남기지 않는다.
    - 옛 `blocked.json`·`pace.json`이 있으면 활성 차단과 다음 허용 시각을 보존해 복사한다.
    - 옛 핸들 카운터 + 1000으로 `data/handles/counter`를 만든다.
  - 그 뒤 정찰 하네스와 옛 코드는 실행하지 않는다.
- 슬라이스 순서:
  1. `doctor`(aside 계약·토큰/세션·분류)
  2. `feed`(listing·paging·records·render·핸들·`--after`)
  3. `post`→`comments`
  4. `profile`·`group`(창 정책)
  5. `search`
  6. `about`
  7. `--out`(collection)
  8. 실패 경로(로그인·차단·stale·빈 결과·부분 결과 우선순위)
- 각 슬라이스는 CLI 프로토콜 테스트의 행동 red에서 시작한다. 그 슬라이스가 새로 만드는 안정 단위(레코드·스니펫·저장소)는 단위 이음새에서도 테스트한다. 사례는 부록 A에서 꺼낸다.
- 공유 계약(`guard`·`collection`·CLI 출력 계약·스니펫 프로토콜)이 녹색이 되면 Codex 검토를 받고, 재현해서 발견사항을 처리한다.
- 완료:
  - 스위트가 종료코드 0이다.
  - 구조 테스트가 통과한다.
  - 일부러 동작을 한 번 깨면 해당 테스트가 실패하는 것을 확인했다.
  - 모든 `<command> --help`가 인자·출력·실패·종료코드·요청 집계를 혼자 설명한다(실행해서 눈으로 확인). 닫힌 집합은 choices다.
  - 루트 `--help`는 한 화면(≤ 40줄)이다. 넘치면 명령을 줄인다. 세 번째 help 단계를 만들지 않는다.
  - 각 명령이 자리를 얻은 이유(매번 같은 방식으로 가는 일을 숨기거나, 모델이 안정적으로 못 하는 일)를 PR 본문에 한 줄씩 적는다. 모델이 직접 할 수 있는 일(예: `--out` 파일 분석)을 감싸는 명령은 만들지 않는다.
  - 로컬 캡처 검사에 예상 밖 issue가 없다.
  - 라이브 스모크(doctor·feed·post)가 ≤15요청으로 통과한다.

**P4 신규 역량 (D6, D12)** — P2 판정이 '가능'인 것만, 같은 수직 TDD
- `replies` 핸들 펼침과 다음 묶음·답글의 답글, 검색 필터·`--in-group`, `about`의 페이지·그룹 카드, `media[].alt`.
- 완료: 역량마다 테스트가 녹색이고, 라이브 스모크가 각 ≤5요청으로 통과하며, `schema`와 `--help`에 새 필드·옵션이 설명돼 있다.

**P5 기존 코드 제거·호환 정리**
- 옛 모듈을 삭제한다. 옛 핸들(`~/.cache/facebook-skill/cursors`)은 지원하지 않는다(D14로 삭제). 옛 `--out` 파일은 새 포맷 버전에서 바이트 변경 없이 거부한다(테스트로 고정). 옛 레지스트리 오버라이드는 가져오지 않는다(R1 방식으로 다시 얻음).
- 완료: `grep -rn "\.cache/facebook-skill\|FACEBOOK_HOME" .claude/skills/facebook`가 0건이고, 새 스킬로 doctor·feed가 라이브로 동작한다.

**P6 SKILL.md를 증거로 쓰기** — 실계정, 하루 ≤300요청(장부), 여러 날
- **무네트워크 리허설**: 부록 C의 하네스를 가짜 aside로 한 번 돌려 권한·격리·SKILL.md 전달·`permission_denials`를 확인한다.
- **A(CLI만)** 로 8과제를 실행하고 루브릭으로 결함을 기록한다. 성진에게 결함 사례를 원문과 함께 보여 반론·이유를 받는다.
- **B(초안)**: 결함마다 원칙 한 줄(이유·성립 조건·뒤집히는 조건, 비슷한 두 경우를 가르는 예는 필요할 때만)을 쓴다. B로 8과제를 재실행한다.
- **C(섹션 제거)**: 필요성이 애매한 섹션만 돌린다.
- **해석 규칙**:
  - 라이브 피드가 바뀌므로 A/B는 같은 날 연달아 돌린다. 차이가 애매하면 순서를 바꿔 한 번 더 돌린다.
  - 허용 잔여 실패를 미리 정한다. 루브릭 3(coverage 정직)·4(귀속)는 B에서 0건이어야 하고, 나머지는 A 대비 악화가 없어야 한다.
- **4속성 검토**: Claude 자신이 먼저 하고, 이어서 Codex가 한다. 보류 사례로 경계를 확인하고, references 게이트를 판정하고, description을 재작성한다.
- SKILL.md 전문(+references)을 성진에게 보여 **전체 승인**을 받는다(한국어 요약 병기).
- 완료: 전체 승인을 받았고, 대조에서 나온 차이가 전부 SKILL.md에 자리를 얻었거나 뺀 이유가 PR 본문에 있으며, 남은 불확실성이 PR 본문에 적혀 있다.

**P7 검증·머지·정리**
- `claude plugin validate --strict "/Users/seongjin/Coding/Agentic SNS/.claude/skills"` 종료 0.
- `claude -p "/skill-doctor"`로 트리거 충돌을 확인한다(ultra-search의 URL 읽기와 겹치면 양쪽 description 경계를 제안한다. ultra-search는 레포 밖이라 성진 확인 후).
- 스위트 녹색, Codex 최종 검토 처리.
- **개인정보 점검**(push마다):
  - `git diff --cached`를 직접 읽는다.
  - 스테이징된 내용에서 `fb_dtsg|lsd|c_user|xs=|datr|token`과 실존 인물 이름·프로필 URL을 검색한다.
  - 개발 기록(커밋·PR 본문)을 익명화한다.
- **실데이터 산출물 정리**:
  - `tests/facebook/captures/`와 `$WORK`의 대조 실행 디렉터리·JSON 출력을 삭제한다(대조 실행은 `--no-session-persistence`라 세션 기록이 없다).
  - 로컬 `data/handles/`의 핸들 파일을 지운다(`counter`와 `data/protection/`은 남긴다).
- PR 본문(`## 무엇을 바꿨나` / `## 왜` / `## 영향` / `## 검증`, 개발 기록 포함)을 쓰고 `gh pr merge --squash`.
- 머지 후 성진 확인을 받아 `~/.cache/facebook-skill`을 삭제한다.
- 완료: 위 명령들의 종료코드·수치가 PR `## 검증`에 그대로 있다.

## 검증 (end-to-end)

- `uv run --with 'pytest>=9,<10' pytest -c tests/facebook/pytest.ini tests/facebook` → 종료 0(구조·CLI 프로토콜·스니펫 프로토콜·레코드·paging·stores).
- `uv run ".claude/skills/facebook/scripts/cli.py" --help` 및 명령별 `--help` 출력 확인. `schema` 각 객체.
- 라이브: `doctor` → `feed --sort recent --limit 5` → 그 결과의 `post` → `replies <n>` → 작성자 `about` → `search … --type people`. 각 단계의 `requests=`·`stopped=`를 장부와 PR에 기록한다.
- 대조 실행 A/B/C 결과표(과제 × 루브릭)를 PR 본문에 둔다.
- `claude plugin validate --strict …/.claude/skills` 종료 0, skill-doctor 보고.

## skill-maker 프레임 준수 대조표

구현 세션은 단계를 닫을 때마다 이 표에서 해당 행을 확인한다. 머지 전에는 전 행의 "검증"이 실제로 수행됐는지 PR `## 검증`에 적는다.

| 프레임 요구 (skill-maker 절) | 계획 위치 | 검증 |
|---|---|---|
| 스킬은 기본값과 전문가의 차이와 이유만 싣는다 / 모델이 이미 잘하는 줄은 뺀다 (도입) | SKILL.md 구조, P6 | A/B/C 대조 결과표 |
| 원칙 vs 레일 · 인터페이스 vs 문서 · 모델용 · 조밀함 (What earns a place) | SKILL.md 섹션 조건 1–2 | Claude 자체 검토 → Codex 검토(4속성) |
| 기본값을 고치는 줄은 구체 행동과 이유, 모델·조건은 개발 기록으로 | 섹션 조건 2, D8 | PR 본문에 "어느 모델을 보고 쓴 줄" 기록 |
| 값·기본값 대신 그것이 일으키는 실패를 쓴다 | 섹션 조건 말미 | 본문 grep(숫자 한도 0건) |
| 대조에서 모자람이 없으면 스킬 없음/한 줄이 정답 | "추가할 판단 없음도 정당" | P6 판정 |
| 새 스킬 전에 skill-doctor로 이웃 확인·양쪽 description 경계 | P0, P7 | 보고서, description 경계 문장 |
| 묻기 전에 읽는다 | 근거 원장(코드·9월 실행 18건·캐시) | 원장 |
| 기본값과의 대조: 실제 과제, 결과를 보여 주고 반론을 이유까지, 격리 플래그, 재료는 주고 판단만 뺌, 권한 거부 실행은 무효 | 부록 C(과제·하네스·차이점 이유), P6 | 무네트워크 리허설, `permission_denials` 확인 |
| 권위 종류 구분(선호·사실·관례·제약), 공개 스킬은 선호를 싣지 않음 | D1, 섹션 조건 3 | 작성 노트의 줄별 분류 |
| 사용자가 도메인 비전문가일 때 판단은 확인 가능한 것에서, 취향 경계는 사용자 몫 | 섹션 조건 4 | 보류 사례 판정 기록 |
| 다듬은 문장 ≠ 사용자 지식: 보류 사례로 경계 확인 | 부록 C 보류 사례, 섹션 조건 4 | P6 기록 |
| 증거로 못 정하는 것은 AskUserQuestion으로 하나씩 / 원장(사실·추론·결정·가정·열린 질문) / 사용자·동석 여부(D1)·위치(D21)·언어(D7) 합의 | 결정 D1–D21, 근거 원장 | 이 계획 |
| 기존 스킬: 지식 부족 vs 실행 실패 구분, 보존할 행동 먼저, 삭제·통합도 개선 | 부록 A, D20(9월 대상 회귀 비교) | P1 매핑표, P6 회귀 비교 |
| 원칙 = 이유·조건·뒤집히는 조건·가르는 사례 / "use judgment" 금지 | 섹션 조건 2 | 4속성 검토 |
| 되돌리기 어려운 선택은 동의 후 | "모든 섹션에 걸치는 두 가지" | 대조 B에서 refresh·unblock 상황 확인 |
| 예시는 두 비슷한 경우를 가를 때만 | P6 B 작성 규칙 | 4속성 검토 |
| 넘기기 전에 성립해야 할 것을 확인 가능한 말로, 보존 vs 자유 구분 | "모든 섹션에 걸치는 두 가지" | 루브릭 3·4·6 |
| 지식은 작동하는 곳에: 계산은 스크립트, 모델이 직접 할 일을 감싸지 않음 | CLI 계약, P3 완료(명령별 존재 이유) | PR 본문 |
| 파일은 필요한 시점으로 나눔, 포인터 없는 reference 금지 | references 조건부 | P6 게이트 |
| 고정 트리(SKILL.md·references/·data/·scripts/cli.py·패키지 하나) | 목표 트리 | 구조 테스트 |
| sys.path 무수정, 표준 라이브러리 이름 충돌 없음 | 단위 경계 규칙 | 구조 테스트 |
| `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"` + 같은 allowed-tools, PEP 723 | CLI 계약, 목표 트리 | `plugin validate`, 실행 |
| 명령은 매번 같은 일이나 모델이 못 하는 일을 숨길 때만 | P3 완료 | PR 본문 |
| cli.py = parser·help·dispatch·종료코드, 도메인 로직 없음 | 목표 트리, 부록 B 마지막 행 | 코드 리뷰(Codex), 구조 테스트 |
| --help 두 단계, 명령 help가 인자·출력·실패를 혼자 설명, 닫힌 집합은 choices, 루트는 한 화면 | 출력 계약, P3 완료 | 실행해서 확인 |
| stdout은 결과만, 싼 신호 먼저, 비싼 상세는 그 결과만 가리키는 핸들, 덮어쓰기 없음, stderr는 진단, 0/2 + help 정의 코드 | 출력 계약(비싼 상세·핸들) | CLI 프로토콜 테스트 |
| 깊은 모듈, 두 번째 변경 이유가 생길 때 분할 | 목표 트리 | Codex 코드 리뷰 |
| 남이 소유한 시스템은 이름 붙인 하위 패키지 하나, 결과는 스킬 용어로 넘김 | `aside/`, `graphql/` | 구조 테스트, 레코드 테스트 |
| import 한 방향, feature 간 간선은 구조 테스트가 이름으로 | 단위 경계 규칙 | 구조 테스트 |
| 상태는 `data/` | `data/`, `paths.py` | 구조 테스트(`.gitignore`만 커밋), P5 grep |
| 테스트·유지보수 코드는 스킬 밖, 스킬은 그것을 import하지 않음 | `tests/facebook/`, `$WORK` | 구조 테스트 |
| 구조 테스트: 최상위 두 이름, import 방향, 인터페이스 너머 접근 금지(테스트 포함), sys.path | 단위 경계 규칙 | `test_structure.py` |
| 완료: 사용자 전체 승인 | P6 | 승인 기록 |
| 완료: 판단·경계·충돌 해소·불확실성 기록 | P6 완료 | PR 본문 |
| 완료: 대조 차이마다 자리 또는 뺀 이유 | P6 완료 | PR 본문 |
| 완료: `plugin validate --strict`(심볼릭 링크면 대상의 부모 = `.claude/skills`) 종료 0 | P7 | 종료코드 |
| 완료: 코드가 자기 계약대로 검증, --help 일치, 구조 테스트 통과 | P3–P5 완료 | 스위트 종료코드 |
| 완료: 사용자에게 보이기 전 다른 계열 검토(4속성), 저울질 | P6(Codex → 성진 순서) | 처리 기록 |
| 완료: 개발 기록은 스킬 밖 | D8 | 본문에 출처·경위 0건 |

## 검토 반영 (Codex gpt-6.1-sol, 2026-10-15)

| # | 지적 | 처리 |
|---|---|---|
| 1 | (차단급) 보호 상태 이관 없이 새 경로로 옮김, 임계구역 | 반영: `guard.request()` 단일 임계구역, 첫 라이브 전 옛 보호 상태 이관, 정찰 전 활성 차단 확인 |
| 2 | 하루 300 집계 수단 없음 | 일부: 스킬 내 누적 상한은 성진이 거절(D17) → 개발 중 수동 장부. 호출당 요청 집계 정의는 반영 |
| 3 | 대조 하네스 불완전 | 반영: 부록 C에 정확한 플래그·전달 방식, 무네트워크 리허설 |
| 4 | 기존 파서 = 현실성 증거는 과장 | 반영: 계약 종류별 분리, 차분 호환성으로 격하, 캡처로 보정 |
| 5 | 가짜 aside가 JS 요청 경계를 안 봄 | 반영: Node 스니펫 하네스 이음새 |
| 6 | 테스트 이음새가 구현 끝에야 생김 | 반영: CLI 골격 먼저, 수직 슬라이스 |
| 7 | 격리·컷오버 없음 | 성진 결정(D16)으로 같은 폴더. 롤백·컷오버 정의만 추가 |
| 8 | 핸들·수집 파일 호환 미정 | 반영: P5에 명시, 포맷 버전·바이트 무변경 거부 테스트 |
| 9 | 개인정보 산출물이 캡처 밖에도 있음 | 반영: `--no-session-persistence`, 산출물 목록, push 전 점검 |
| 10 | 정찰 실패가 범위 삭제로 이어짐 | 반영: 가능/불가 입증/미확정, 삭제는 성진 동의 |
| 11 | 구조 규칙 모순 | 반영: paging은 범용 helper, 창 정책은 listing, aside도 패키지, 공개 인터페이스 정의 |
| 12 | 출력 옵션 조합 모호 | 반영: `--json --out`·`--out --after`·실패 출력 규칙. 비싼 상세는 `post <url>` 핸들(D18) |
| 13 | ablation만으로 4속성 보장 못 함 | 반영: 4속성 검토·보류 사례·"판단 없음" 결과·허용 잔여 실패·순서 바꿔 반복 |
| 14 | pytest pythonpath | 반영: `../../.claude/skills/facebook/scripts`, pytest 9.x |
| 15 | 댓글 판별 두 술어 혼동 | 반영: 부록 A 24/24b 분리 |
| 재1 | P2 정찰이 보호 경로를 안 거침, 대조 실행이 별도 보호 상태 | 반영: P2 하네스가 옛 보호 코드로 감싸고 옛 캐시를 권위 상태로 씀 → P3에서 스킬 `data/protection/`로 단일 이관, 대조 실행도 그 data를 씀 |
| 재8 | 핸들 번호 재사용 위험 | 반영: 카운터는 지우지 않음, 옛 카운터+1000에서 시작 |
| 재12 | 잘린 댓글·답글의 상세 경로 없음 | 반영: `detail:` 줄(같은 커서 재요청 + `--chars 0`), About 비절단, 상세는 라이브 재요청임을 명시 |
| 재신규 | 탭 이동 셈 단위 미정 / 스모크 완료 기준 과장 | 반영: R1에서 셈 단위 확정 전 예산 주장·채택 금지 / 스모크는 단언 기반, 잔여 불확실성 명시 |

---

## 부록 A. 기존 코드의 지식 (재작성에서 보존할 것, 파일은 main 기준)

**[전송·분류]** (`graphql/transport.py`, `aside/repl.py`)
1. 응답 앞에 `for (;;);`가 붙을 수 있다. 본문은 JSON 객체 여러 개가 이어진 NDJSON(Relay 증분 전달)이다.
2. 체크포인트: 경로 `/checkpoint` 또는 키 `checkpoint_url`/`challenge_url` → 무기한 차단.
3. 로그인 필요: 코드 1357001, 키 `caa_login_form_data`, 경로 `/login`·`/recover`, `"USER_ID":"0"`, 홈 200인데 USER_ID 없음.
4. rate limit: HTTP 429·코드 1357004 → 30분 차단. 1357054 → 일시 거부라 페이싱 후 1회 재시도. 정적 자산(fbcdn) 429도 rate limit이다(자산 본문의 인증 오류 문자열은 계정 응답이 아니므로 무시).
5. 실패: `errors`만 있고 `data`가 없는 청크, `severity: CRITICAL`, 청크의 `error` 키.
6. 기대 연결 키에 edges/nodes/page_info가 있어야 한다. 개수만 있는 미리보기는 같은 이름이라도 페이지네이션 대상이 아니다. 객체형 기대(`post`)는 id·`__typename`·comet_sections·feedback·story 중 하나가 있어야 한다.
7. 명시적 빈 결과 = 항목 0 + `has_next_page: false` → empty(오래된 쿼리가 아님).
8. `page_info.has_next_page`는 bool, `end_cursor`는 str|null. 항목은 있는데 페이지 정보가 없으면 페이지네이션 손상이다. 같은 커서가 반복되면 손상이다.
9. Aside REPL 출력: ANSI 색 코드를 제거하고 `{`로 시작하는 줄만 JSON으로 본다. 마지막 줄이 envelope(status 100–599 int·url str·body str)다. `body_chunks` 개수와 index 순서가 맞아야 하고, `body_file` 키는 거부한다. 종료코드≠0이면 "other side closed"·"daemon is not reachable"을 연결 끊김/시간 한도로 분류한다. 하위 프로세스 타임아웃은 125초(REPL 120초)다.
10. URL 검증: https만, 사용자 정보·포트(443 외) 금지, 호스트는 facebook.com·fbcdn.net 하위만. 대상 입력은 공백·제어문자·`\\`·`.`/`..` 경로를 거부한다.

**[요청 직렬화]** (`graphql/session.py`, `snippets/*.js`)

11. 토큰(홈 HTML): `"USER_ID":"(\d+)"`, `"DTSGInitialData",[],{"token":…}`, `"LSD",[],{"token":…}`, `"__spin_r":(\d+)`. `jazoest = "2" + sum(ord(c) for c in fb_dtsg)`, `__rev = __spin_r`. 토큰은 디스크에 저장하지 않는다.
12. GraphQL 폼 필드: `av __user __a=1 __comet_req=15 fb_dtsg jazoest lsd __spin_r __rev server_timestamps=true fb_api_caller_class=RelayModern fb_api_req_friendly_name variables doc_id`. 헤더는 `x-fb-friendly-name`·`x-fb-lsd`·`content-type: application/x-www-form-urlencoded`·`origin`·`referer`(대상 페이지). POST 대상은 `https://www.facebook.com/api/graphql/`이다.
13. `__relay_internal__pv__*relayprovider` 플래그를 변수에 합쳐야 한다(값은 bool/int/대문자 문자열). 페이지의 JSON script 태그에서 얻는다.
14. 큰 응답: REPL 로그 한 줄 상한(~12MiB 실측) → envelope JSON이 8MiB를 넘으면 512KiB `body_chunk` 레코드로 나누고, 서러게이트 쌍이 갈라지지 않게 자른다.
15. doc_id 발견 패턴: `__d("<Name>_facebookRelayOperation",[],(function(…){e.exports="<digits>"})`. 대상은 `static.*.fbcdn.net/rsrc.php/…js` 즉시 로드 스크립트다. 후보는 실제 재생 요청으로 검증한 뒤에만 저장한다.
16. 쿼리 이름: about=`ProfileCometAboutAppSectionQuery`, timeline=`ProfileCometTimelineFeedRefetchQuery`, newsfeed=`CometNewsFeedPaginationQuery`, group=`GroupsCometFeedRegularStoriesPaginationQuery`, search=`SearchCometResultsPaginatedResultsQuery`, post=`CometSinglePostDialogContentQuery`, comments=`CommentListComponentsRootQuery`, comments_page=`CommentsListComponentsPaginationQuery`, replies=`Depth1CommentsListPaginationQuery`. 변수 기본값은 `graphql/registry.json`(main)을 보존 자료로 쓴다.
17. 정렬 토큰:
    - 피드: top `{orderby:[TOP_STORIES], feedStyle:DEFAULT}` / recent `{orderby:[MOST_RECENT], feedStyle:MOST_RECENT_FEED_DEFAULT}`
    - 그룹: `TOP_POSTS` / `CHRONOLOGICAL` / `RECENT_ACTIVITY`
    - 댓글: `RANKED_UNFILTERED_INTENT_V1` / `REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1`
18. 검색 수직 `args.experience.type`: top `GLOBAL_SEARCH`, posts `POSTS_TAB`, people `PEOPLE_TAB`, pages `PAGES_TAB`, groups `GROUPS_TAB`. doc_id는 다섯 수직이 같다.
19. About:
    - `sectionToken = base64("app_section:{id}:2327158227")`. `pageID`·`userID` 모두 대상 id다.
    - 개요(`collectionToken=null`)가 `all_collections.nodes[{name,id}]`를 준다. 컬렉션마다 1요청이다.
20. 프로필 창: `afterTime`/`beforeTime`(현지 날짜 시작·끝의 unix 초)이고 서버가 거른다.
21. 대상 해석:
    - 프로필 HTML `"userID":"(\d+)"`, `/people/<이름>/<id>`, `profile.php?id=`.
    - 그룹 HTML `"groupID"|"group_id"`. 숫자 슬러그는 직접 쓴다.
    - 글 HTML `"storyID":"…"`.
22. 글 URL 형식:
    - `/<user>/posts/<id>`, `/groups/<g>/(posts|permalink)/<id>`, `/<user>/videos/<id>`
    - `permalink.php|story.php?story_fbid&id`, `photo.php|photo?fbid`
    - 프로필이 아닌 예약 경로: groups reel watch hashtag events marketplace stories … (`resolve.py` `_RESERVED`)

**[레코드]** (`graphql/records/*`)

23. 글 정체성은 `feedback.id`다. 이야기는 @defer 조각으로 나뉘어 오므로 feedback id로 깊은 병합한다. 규칙: null이 아닌 값 우선, dict는 재귀, id 있는 리스트는 합집합, 그 외 리스트는 연결 후 내용 중복 제거.
24. **글 걷기에서 댓글 제외**: `__typename == "Comment"` 또는 (`depth`와 `author`가 함께 있음)이면 그 아래로 내려가지 않는다.
    - 24b. **댓글 추출**: `depth` 있음 + `author`는 dict|null + `body`는 dict|null + `id` 있음(typename 대안 없음). `comment_direct_parent` 아래로는 내려가지 않는다.
25. `attached_story` 아래 이야기는 공유된 글이다. 그 밖에서 한 번이라도 보이면 최상위다. 공유 사슬은 중첩되고 순환할 수 있다(순환은 끊고 issue로 남긴다). 식별 불가한 attached_story는 글을 incomplete로 만든다.
26. `interesting_top_level_comments` 아래 미리보기는 댓글이지 글이 아니다.
27. `creation_time`은 루트 직속 int 키만 쓴다(재귀 탐색은 수정 시각 등 미끼를 잡는다). 수정 시각은 "edit"과 "time"을 포함한 int 키다.
28. permalink: 루트 `permalink_url` → 루트 `wwwURL` → 하위 `wwwURL`.
29. 본문은 루트에서 닿는 첫 비어 있지 않은 `message.text`다(공유·댓글 제외).
30. 작성자는 첫 `actors` 리스트(dict들)다.
31. 미디어: `image.uri`(+width/height)는 image, `playable_url`/`_quality_hd`는 video. 영상의 포스터는 image다. URL로 중복 제거한다. 사진 유형 판정 때 링크 썸네일(`url`+title/description, `uri` 없음 하위)은 뺀다.
32. 링크: `url` + (`title`|`description`)이 있고 `uri`가 없는 dict.
33. 유형 우선순위: 키에 "reel" → reel / "life_event"·"lifeevent" → life_event / 공유 → shared / video / photo / link / 본문 있으면 status / unknown.
34. 고정: `is_pinned`·`is_pinned_story`·`is_featured`가 true.
35. 광고: `is_sponsored` true, `sponsored_data` dict, 또는 `ad_id`가 참. 광고는 날짜가 없을 수 있다.
36. 반응 `feedback.reaction_count.count`, 공유 `feedback.share_count.count`, 댓글 `feedback.comment_rendering_instance.comments.total_count`(키 `comment_count`는 실제로 없다). 음수·비정수는 null.
37. 잘림: "truncat"·"preferred_body"·"see_more"를 포함한 키가 참이면 잘린 것이다(`message_truncation_line_limit`는 제외, 공유·댓글 하위 제외).
38. 레코드가 읽는 필드를 담은 경로 전용 패치나 오류는 그 이야기를 incomplete로 표시한다. 귀속할 곳이 없으면 응답 수준 issue다. 아무 레코드도 읽지 않는 필드의 패치·오류는 무시한다. issue 종류: unsupported_path_patch·graphql_errors·cyclic_shared_story·invalid_utf8·malformed_json·non_object_json.
39. 퍼머링크 응답의 대상 글은 경로 없는 청크의 `data.node_v2|node|story` 루트의 feedback id다(응답 안 다른 이야기는 미끼).
40. 댓글은 id로 병합한다. 반응 수 위치 우선순위:
    1. `feedback.reactors.count` → `unified_reactors.count` → `reaction_count.count`
    2. `comment_action_links[].comment.feedback.reactors.count`
    3. 마지막 수단: `count_reduced`가 순수 숫자일 때만 쓴다("1.2K"는 추정하지 않음).
41. 답글 수는 `feedback.replies_fields.total_count`다. 답글은 인라인으로 오지 않는다(edges 비어 있음). 펼치려면 `feedback.id` + `feedback.expansion_info.expansion_token`이 필요하다. 부모는 `comment_direct_parent.id`이고, 부모 링크 없는 답글은 펼친 부모의 것이다. 답글 수 0이면 펼치지 않고, null이면 토큰 유무로 판단한다.
42. 댓글 첨부 종류는 `style_list[0]` 매핑으로 정한다(photo/album→photo, animated_image_share→gif, sticker, video/video_inline→video, share/link→link, 그 외 other).
43. 검색 엔티티: `__typename` User/Page/Group + id·name(str)·url(str).
    - pages 수직에서는 페이지도 "User"로 오므로 수직이 종류를 정한다. Group은 언제나 확정이고, groups 수직은 Group 외를 버린다.
    - 결과 루트 래퍼(node·result·entity·profile·group·page·user·rendering_strategy·view_model)만 따라간다. Story·Comment·feedback 아래로는 안 내려간다.
    - top 검색 순서는 연결 인덱스 순서다(지연 도착 순서가 아님). 인증 여부는 `is_verified`(bool 아니면 null).
44. About 필드: `field_section_type`(로케일 무관) 노드의 `profile_fields.nodes[].title.text`·`field_type`·`link_url`. (section, text)로 중복 제거한다. 컬렉션 이름은 로케일 의존이다. About 응답은 모든 부분을 읽으므로 오류·경로 패치 하나라도 issue다.

**[페이지네이션·창]** (`reading/paging.py`, `posts.py`, `comments.py`)

45. 최신순 피드·그룹은 시간순이었다(실측 9/9, 15/15). since보다 오래된, 날짜 있고 고정·광고 아닌 글이 나온 페이지에서 창을 닫는다. 고정·날짜 없는 글은 어느 창이든 통과한다. 날짜 비교는 현지 날짜다.
46. 서버 순서를 보존한다. id로 중복 제거하고, `--limit`을 넘는 페이지 꼬리는 다음 핸들의 pending으로 남긴다. 광고는 기본 제외하되 개수를 센다(제외 id도 seen에 넣어 재개 때 다시 세지 않음). 내용 있는 연결인데 읽을 레코드가 0이면 stale 쿼리다.
47. 댓글: 부모를 페이지 단위로 읽고, 답글 펼치기 실패는 부모별로 `replies_incomplete`(retryable 여부)에 남긴다. 재시도 가능한 실패는 다음 이어 읽기에서 먼저 재시도한다. 차단·로그인·예산(4·5·8)이면 그 뒤의 펼치기를 멈춘다. 실패 우선순위: 차단·로그인 > 실제 답글 실패 > 예산 정지.

**[영속화·결과 어휘]** (`collect.py`, `cursors.py`, `outcome.py`, `account.py`)

48. `--out`: 헤더 줄(쿼리 문맥·포맷 버전·started_at) → 레코드 → 페이지마다 `kind:"page"` 표지(cursor·ids·n·stop_reason·skipped·coverage). 재개 시 마지막 표지 뒤를 버리고 다시 읽는다. 다른 쿼리·옛 포맷 파일은 한 바이트도 건드리기 전에 거부하고, 표지의 ids·n이 위 레코드와 다르면 무결성 오류다. 파일 잠금(LOCK_NB), fsync, `--limit`은 저장된 수(댓글은 부모 수)를 센다.
49. 핸들은 단조 증가 번호이고 쿼리 문맥(+계정)에 결속한다. 번호 예약을 먼저 fsync해 재사용을 막는다. 파일 권한은 0o600, 디렉터리는 0o700이다.
50. 보호 상태는 원자적 쓰기(임시 파일 + fsync + replace)로 하고, 읽을 수 없으면 차단으로 본다. 요청 시작 전에도 다음 허용 시각을 기록해, 죽은 프로세스가 타임스탬프를 지우지 못하게 한다.
51. 창 coverage 어휘: 실패 시 `open — <실패>` / 랭킹이면 `sample (ranked order)` / 한도·예산 정지면 `open — more: continues` / 최신순이 경계나 끝에 닿으면 `closed (as served)` / 서버 필터가 끝에 닿으면 `closed (server-filtered)`.
52. 기존 코드가 남긴 `성진:` 보류 사항(재작성에서 다시 판단): 경로 전용 패치 미지원, 결과 래퍼는 아는 것만 따라감, capture 클릭 라벨은 영/한만, 최신순 정지는 시간순 가정 위에 있음, 400 상한은 실계정 보호용, 잠금은 계정 하나 가정.

## 부록 B. 기존 → 새 단위 대응

| 기존 (main) | 새 위치 |
|---|---|
| `aside/repl.py` | `aside/` (계정 플래그는 Aside 기본값/`FACEBOOK_ASIDE_ACCOUNT`, `FACEBOOK_ASIDE_BIN` 유지) |
| `graphql/transport.py` 분류·`session.py`·`resolve.py`·`registry*`·`snippets/`·`records/*` | `graphql/` (guard·snippet 실행기는 주입) |
| `graphql/refresh.py` | `graphql/`(발견 로직) + `maintenance.py`(명령) — R1 결과로 축소 가능 |
| `account.py`, `transport.py`의 `_request`·`_pace` | `guard.py` (`request()` 임계구역, 경로는 `paths.py` → `data/protection/`) |
| `cursors.py` | `handles.py` (+TTL·포맷 버전) |
| `collect.py` | `collection.py` (새 포맷 버전) |
| `reading/posts.py` | `listing.py` |
| `reading/comments.py` | `thread.py` |
| `reading/search.py` | `search.py` |
| `reading/about.py` | `about.py` |
| `reading/maintenance.py` | `maintenance.py` |
| `reading/paging.py` | `paging.py`(범용) + `listing.py`(창 정책) |
| `outcome.py` | `results.py` |
| `render.py` / `errors.py` | 같은 이름 |
| `reading/dispatch.py`, `cli.py`의 `continuation_args`·`context_for`·`query_words` | 도메인 결정은 해당 feature로, 배선은 `connect.py`로. `cli.py`는 parser·help·dispatch·종료코드만 |

## 부록 C. 대조 실행 설계 (P6)

**대상 선택 (D20)**: 9월 과제와 겹치는 과제는 9월 대상을 재사용한다. 그래야 옛 스킬의 답과 나란히 비교해 회귀를 볼 수 있다.
- 3번은 `〈공개 페이지의 글 URL〉`(댓글 단 사람 두 명 파악 과제도 함께)
- 5번은 "Mark Zuckerberg"
- 6번 변형은 zuck의 특정 달 글
- 8번은 zuck

옛 답은 `~/.claude/projects/*fb-scn*/*.jsonl`에 있고, 9월 이후 삭제·편집으로 대상이 달라졌을 수 있음을 비교 때 감안한다. 답글·그룹·페이지 같은 새 역량 과제는 실행 시점에 Claude가 공인·공개 페이지 위주로 고른다.

**과제 8개** (한국어 지시, 실계정):
1. 오늘 내 피드에서 AI 관련 글만 모아줘 (최신순·창 닫힘·광고)
2. 내 피드 최근 글 10개 요약 (랭킹 vs 최신, 사진 글 대체텍스트)
3. 〈글 URL〉 댓글 여론이 어떻게 갈리는지 정리 (정렬·필요한 가지만 펼침·부분 스레드 주장 범위)
4. 〈글 URL〉에서 가장 논쟁적인 댓글 스레드를 답글 끝까지 읽어줘 (replies 핸들·다음 묶음)
5. 〈이름〉을 페이스북에서 찾아 어떤 사람인지 정리 (동명이인·인증·About·타임라인)
6. 〈페이지〉가 지난달 올린 글 전부 (서버 필터 창·페이지 vs 프로필·작성자 귀속)
7. 〈주제〉 그룹을 찾아 가장 활발한 그룹의 최근 흐름 (그룹 검색·그룹 카드·정렬)
8. 〈프로필〉 최근 글 100개를 파일로 모아 주제 분포 분석 (`--out`·재개·삭제 안내)

**보류 사례** (4속성 검토용, 대조 실행에 쓰지 않음):
- 공유 글의 원작자가 비공개라 unavailable인 경우
- 관련도 정렬에서 걸러진 댓글을 묻는 질문
- 같은 이름의 페이지와 개인 프로필이 둘 다 인증된 경우
- 날짜 창 질문인데 랭킹 그룹 정렬밖에 없는 경우

**조건**:
- A = CLI만(SKILL.md 본문을 호출 한 줄로 축소)
- B = 초안 전체
- C = B에서 섹션 하나 제거(필요성 애매한 섹션만)

**프레임 기본 명령과 다른 점과 이유**:
- 프레임은 "스킬도 지시도 없는 Claude"로 기본값을 보라고 한다. 이 스킬의 기본값 비교 대상은 **CLI는 있고 판단은 없는 Claude(A)**다. CLI 없이는 페이스북을 아예 읽을 수 없어 대조가 성립하지 않는다. 시험 대상인 판단(SKILL.md 본문)만 빼고, 과제에 필요한 재료(CLI·help·schema)는 준다.
- 프레임 명령의 `--permission-mode acceptEdits`는 쓰지 않는다. 이 과제는 셸이 필요하다. 프레임은 `--tools`로 셸을 되살리면 셸이 열린다고 경고하므로, 셸을 `--allowedTools`의 cli.py 패턴으로만 허용하고 나머지는 -p의 승인 부재로 거부되게 한다. 쓰기는 cli.py의 `--out`뿐이다.

**하네스** (플래그는 2026-10-15 `claude --help`로 확인):
- **사본 준비**: 실행마다 `$WORK/contrast/<run>/`(레포 밖) 새 빈 디렉터리에 스킬 사본(A/B/C 변형)을 둔다. 사본 SKILL.md의 `${CLAUDE_SKILL_DIR}`은 절대 경로로 치환한다.
- **공유 상태**: 모든 실행에 `FACEBOOK_DATA_DIR="/Users/seongjin/Coding/Agentic SNS/.claude/skills/facebook/data"`(권위 있는 단일 보호 상태가 있는 실제 스킬 data)를 준다. 그래서 대조 실행의 페이싱·차단 기록이 스모크·일상 사용과 하나로 이어진다. 핸들은 번호가 전역 고유이고 문맥에 결속돼 실행 간에 섞이지 않는다. 실행은 순차로 한다. 정리 때는 `data/handles/`의 핸들 파일만 지우고 `counter`와 `data/protection/`은 남긴다.
- **스킬 전달**: `--safe-mode`가 스킬·CLAUDE.md·훅을 끄므로, 프롬프트가 "사본 SKILL.md를 먼저 읽고 따르라, scripts/는 읽지 말고 `--help`·`schema`·출력만 쓰라"고 지시한다(9월 방식).
- **도구 제한**: `--restricted --tools Bash,Read,Grep,Glob --allowedTools 'Bash(uv run "<사본>/scripts/cli.py" *)'`로 두고 permission-mode는 default로 둔다. 그 밖의 Bash는 거부되어 `permission_denials`에 남는다.
- **명령 형태**: `claude -p --safe-mode --restricted --no-session-persistence --tools … --allowedTools … --model claude-opus-5-5 --output-format json "<프롬프트>"`.
- **무효 판정**: 필요한 도구가 거부됐으면(`permission_denials`) 그 실행은 전문성 증거가 아니다. 과제를 좁히거나(8번은 Read로 분석 가능한 크기) 최소 권한을 더해 재실행한다.
- **기록**: 실행마다 요청 수를 장부에 더한다.

**루브릭** (과제마다 A·B 비교):
1. 답할 수 있는 표면·정렬을 골랐나
2. 요청 수가 필요 최소에 가까운가
3. coverage 주장이 정직한가(부분을 "없음"으로, 랭킹 표본을 "전부"로 말하지 않음)
4. 작성자 귀속(공유 원작자, 타임라인의 타인 글)
5. 정체 확인이 필요할 때 했나
6. 답이 나오면 멈추고 안 읽은 것을 말했나
7. 수집 파일의 개인정보 안내

차이마다 SKILL.md의 한 줄 또는 "뺀 이유"를 PR 본문에 기록한다.
