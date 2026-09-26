# yfinance 스킬 레이아웃 이행과 재설계 계획

> 계획 세션 2026-09-26. 승인 직후 이 파일을 `.claude/plans/yfinance 스킬 레이아웃 이행 재설계 계획.md`로 `mv`한다(계획 모드 도구가 이 경로를 읽으므로 승인 전에는 옮기지 않는다). 이전 라운드는 `yfinance 스킬 총체 점검 재설계 계획.md`(PR #20·#21)이고, 새 레이아웃의 선례는 `facebook 스킬 총체 점검 재설계 계획.md`(PR #23·#24)다. 작업 트리의 무관한 변경(`.gitignore`, `.claude/harness-spec.md` 삭제, 다른 계획 파일, `.ultra-search/`)은 건드리지 않는다.

## Context

`.claude/skills/yfinance`는 Claude가 Yahoo Finance의 구조화 데이터(시세·재무·추정·보유·옵션·스크리닝·달력)를 전문가처럼 가져오게 하는 스킬이다. 막히지 않고(자기설명 CLI·schema·fix), 조용히 틀리지 않고(단위·스케일·시각·창을 계약으로), 예산을 넘어도 잃지 않는다(저장 관측·`read`·`--out`). PR #16·#20·#21로 동작 계약은 실측 검증까지 끝났다.

skill-maker가 개정되면서(`## Code the skill bundles`) 디렉터리 트리도 `--help`보다 먼저 읽히는 인터페이스가 됐다. 요구는 다섯 가지다. ① `scripts/cli.py` 하나와 스킬 패키지 하나. ② 기능·외부 시스템·저장소별 하위 패키지. ③ 단방향 import. ④ `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`와 PEP 723. ⑤ cli.py가 명령 표면 전부를 들고 도메인 로직은 없음. 지금 yfinance는 이 가운데 어느 것도 따르지 않는다(대문자 `Scripts/`, `yfinance_cli.py`, 평면 모듈 8개, `groups/`, pyproject·uv.lock, allowed-tools 없음, 종료 코드가 `--help`에 없음). 코덱스 감사는 여기에 더해 저장 관측을 지우거나 JSON 계약 밖으로 새는 결함 5건과, 모델이 읽는 신호가 사실과 어긋나는 곳 4건을 찾았다.

**결론: 재작성하지 않는다. 옮기고 층을 나눈 뒤 결함을 고친다.** 동작 계약(단위·방향·회복·예산·`--out`)은 실측으로 검증된 지식이고, CLI seam 테스트 352개가 그 행동을 지킨다. 다시 쓰면 그 지식을 재발견해야 한다. 바뀌는 것은 코드가 어디에 사느냐(트리·선언 분리·import 방향), 모델이 무엇을 먼저 보느냐(allowed-tools·종료 코드), 그리고 확인된 결함이다.

**의도한 결과**
- 트리만 보고도 무엇이 어디 있는지 안다: 입력은 `cli.py`, Yahoo는 `yahoo/`, 저장은 `store`·`export`, 조회는 `querying/`.
- pandas·numpy·yfinance import는 `yahoo/` 안에만 있다.
- 호출이 사전 승인된다.
- `--help`가 종료 코드를 말한다.
- 저장 관측이 인자 하나로 지워지지 않고, 모든 실패가 JSON 계약 안에 있다.
- 모델이 '전부'라고 말할 근거가 사실과 맞는다.

## 장부

### 사실 (2026-09-26 실측)
- 오프라인 기준선: `uv run --isolated --frozen --group dev --project .claude/skills/yfinance/Scripts python -m pytest tests/yfinance -q` → 352 passed, 74 deselected(live), 192.8s. 테스트는 전부 CLI 서브프로세스 + HTTP 전송 교체(`tests/yfinance/fixtures/sitecustomize.py`)이고, production 모듈을 import하지 않는다.
- 현 트리: `Scripts/`에 `yfinance_cli.py`(327줄)와 평면 모듈 8개(`registry` `envelope` `encode` `selection` `schema` `budget` `store` `export`), `groups/` 11개, `pyproject.toml`·`uv.lock`·`.python-version`(3.12). 추적되지 않는 `.venv/`·`.ruff_cache/`·`__pycache__/`도 있다. SKILL.md(25줄)에 `allowed-tools`가 없다.
- 패키지 이름을 `yfinance`로 하면 라이브러리가 가려진다. `scripts/`가 `sys.path[0]`이라 `import yfinance as yf`가 스킬 패키지를 돌려준다(`hasattr(yf, "Ticker")` False).
- uv 0.8.0 기준으로 다음을 확인했다.
  - PEP 723 헤더(`dependencies = ["yfinance[repair]==1.7.0"]` + `[tool.uv] exclude-newer = "2026-09-13T13:10:00Z"`)의 `uv export --script` 결과가 현 `uv.lock`의 `--no-dev` 내보내기와 완전히 같다.
  - `uv lock --script`는 `cli.py.lock`을 `cli.py` 옆에 만든다.
  - 따뜻한 `uv run cli.py`는 약 0.33s다.
  - `PYTHONPATH`의 `sitecustomize.py`는 `uv run <script>`에서도 로드된다.
  - `uv run --with-requirements cli.py`는 PEP 723을 읽지 않는다.
  - `bash -c 'uv run --isolated --no-project --with-requirements <(uv export --quiet --script <cli.py> --no-hashes) --with pytest==8.4.2 python …'`는 스크립트와 같은 해석의 환경을 만든다.
- 같은 잠금 버전으로 Python 3.13.5에서도 스위트가 통과했다: 352 passed, 150.7s. 3.11은 잠금상 numpy 2.4.6·scipy 1.17.1로 갈리고, 돌린 적이 없다.
- 루트 `--help`에 종료 코드표가 없다. 4~9는 `schema` 출력(`envelope.EXIT_CODES`)에만 있다.
- `coverage.exhaustive`(`selection.py:150`, `shown == received`)는 schema `ENVELOPE`의 coverage 설명에 없다. 이전 기록의 aapl-news-all 실패(`--limit 300` → 196건을 "전체"라고 답함)에서도 이 값이 `true`였다. 요청 개수는 `context.upstream_requested`(`company.py:42`, `calendar.py:55,73`)에만 있다.
- 선택지 중 동적인 것은 `market summary --region`(`yf.MarketRegion`, 1.7.0: US GB ASIA EUROPE RATES COMMODITIES CURRENCIES CRYPTOCURRENCIES) 하나이고, 나머지는 이미 리터럴이다.
- 공통 구조 테스트 `tests/test_skill_layout.py:210`은 테스트 폴더를 `tests/<패키지>`로 찾고, 없으면 조용히 건너뛴다(`:192`). 그래서 패키지가 `yfinance_skill`이면 `tests/yfinance`가 검사에서 빠진다.
- `graphify-out/`은 `.git/info/exclude`로 추적되지 않는다. 머지 뒤 리빌드는 로컬 작업이고 커밋이 없다.
- 문서의 옛 경로·환경 문장: `README.md:22,52`, `docs/usage.md:27,72-76`, `CONTRIBUTING.md:9,31,42-49`, `.github/workflows/test.yml:43-52`.

### 코덱스 감사 (`gpt-6-astra` high, read-only, run `20260926-225505-yf-layout-audit-5d0b`, 스레드 `01a0ddff-8530-7200-a63d-0c97ecfc4261`)
- **A. 프레임 이탈**
  - 트리·진입점과 호출이 다르고 allowed-tools가 없다.
  - PEP 723이 없다.
  - 명령 표면이 `registry`·`groups/*`·`schema`·`budget`에 흩어져 있다.
  - 진입점에 도메인 로직이 있다(`observe`·`run`·`write_out`·`read`, `yfinance_cli.py:134-285`).
  - 종료 코드가 `--help`에 없다.
  - pyproject의 pytest·ruff는 유지보수자만 쓴다.
- **B. 결정 권고**
  - 패키지 `yfinance_skill`.
  - `exclude-newer`를 쓰고 pandas·numpy를 직접 선언.
  - cli.py에 리프당 입력 선언을 두고 Yahoo 데이터 계약을 참조.
  - `encode.encode`는 pandas 경계에 두고, 형태 판별·표시는 공용.
  - `upstream_fix`의 Yahoo 문구 해석은 시스템.
  - 테스트는 스크립트에서 파생한 환경에서 `[sys.executable, cli.py]` + 실제 `uv run` 이동성 검사.
  - 구조 테스트는 테스트 폴더 부재를 잡아야 한다.
- **C. 결함** — ✓는 클로드가 코드로 재확인한 것이다.
  - ✓1 `--ttl-days` 음수가 저장 관측을 전부 지운다(`store.py:61-70`). 검증보다 먼저 돈다(`yfinance_cli.py:305`).
  - ✓2 `read`가 `validate`를 건너뛴다(`:308-310`).
  - ✓3 `statement_currency`가 레이트리밋을 경고로 삼킨다(`financials.py:25-30`).
  - ✓4 `mkstemp`·저장소 `mkdir`·읽기의 `OSError`가 트레이스백으로 샌다(`export.py:131`, `store.py:31`, `main`은 `InputError`만 잡음).
  - ✓5 `--out` 요약이 열 축약 뒤에도 넘치면 경로·행 수를 잃는다(`budget.py:192-218`).
  - ✓6 뉴스 부족분 신호가 없다.
  - ✓7 `market summary --fields`가 `--out`에서 뜻이 바뀐다(`yfinance_cli.py:196-207`).
  - ✓8 저장되지 않은 결과를 저장됐다고 말한다(SKILL.md, `budget.py:161-172`).
  - ✓9 상류 제약 두 종류를 한 처방으로 묶는다(`budget.py:246-267`).
  - ✓10 날짜 범위 검증이 기본값 적용 전에 돈다(`yfinance_cli.py:103-118`).
  - ✓11 도움말 오기 3건.

### 코덱스 계획 리뷰 (같은 스레드, run `20260926-232128-yf-plan-review-77d9`, 11건 — 전부 반영)
- blocking 1: 긴 경로 + 10대상이면 `out`·`rows`만으로도 1000자를 넘는다 → B6 사다리 재설계(마지막 단은 문서 수준 영수증).
- major 9, 각각 반영한 곳:
  - 뉴스 부족분이 피드 끝을 증명하지 않는다: yfinance가 `snippetCount`로 청한 뒤 광고를 뺀다(`yfinance/base.py:609-630`) → B7 문구와 광고 픽스처.
  - 실효 기본값과 request 스냅샷의 인계 → `## 실행 순서`.
  - 저장 관측의 명령 경로 조회 → `## 실행 순서`, 옛 관측 읽기 테스트.
  - 사전 검사 순서 → `## 실행 순서`, 다중 오류 골든.
  - 테스트 환경의 Python 선택과 export 실패 은폐 → `## 테스트 환경`.
  - `requested`의 모드·보존·전파 → B7.
  - B5 읽기 실패 테스트 → B5.
  - grep 판정 → AST 경계 테스트, `exhaustive`는 출력 키로 판정.
  - 제거 시험 전제 → 문단별 전제와 예산 조건.
- minor 1: 달력의 기존 zero-loss 경고는 남긴다 → B7.
- 판정 (a) import 방향 위반·순환: 없음.
- 재검증(run `20260926-232939-yf-plan-reverify-4b94`): 10건 RESOLVED, 1건 PARTIAL. PARTIAL은 `given`이 별칭이면 `chosen()`이 달라지는 문제로, 복사본으로 명시했다. 새 major 2건을 반영했다: 그 별칭 문제, 그리고 B6 영수증이 파일에 없는 대상의 상태를 잃는 문제(`missing` 추가). 최종 확인(run `20260926-233241-yf-plan-final-efb2`): 두 건 RESOLVED, 새 문제 없음 — blocking·major 0.
- 성진의 "프레임을 철저히 반영했나" 질문에 따라 클로드가 조항별로 다시 대조했다. 빠진 곳 6개를 찾았다: 닫힌 집합의 choices, 싼 신호 먼저, `SHARED`의 소유, help·행동 대조의 완료 조건, 기본값 대조, skill-doctor. 결정 13–15와 `## skill-maker 조항 대조표`로 반영했다.
- 코덱스 조항 대조(run `20260926-233907-yf-frame-coverage-0207`): 자리 없는 조항은 없음. 두 건을 반영했다: 구조 테스트가 본문 호출문을 보지 않는다(→ 단계 1ⓒ 검사 추가), B12 순서가 `shrink` 뒤에 새로 붙는 경고에서 깨진다(→ `strip`에서 정렬 + 축소 경로 테스트). 확인(run `20260926-234205-yf-frame-final-d8da`): 두 건 RESOLVED, 새 문제 없음.
- 클로드 실측으로 확인: `--python '>=3.12,<3.14'`가 받아들여진다(3.13.5 선택). `set -euo pipefail` + `uv export -o` 실패는 exit 2로 멈춘다. 최종 PEP 723 헤더(pandas·numpy 포함)의 해석은 옛 잠금의 Python ≥3.12 집합과 같고, 구조 테스트의 PEP 723 정규식으로 파싱된다.

### 성진 결정 (2026-09-26)
1. 의도 이해 확인(위 Context). 설계 기준은 **yfinance 자체**다. sec·finviz 선례는 고려하지 않는다.
2. **Claude Code 전용.** `allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)`, 실행 문장은 한 줄. `${CLAUDE_SKILL_DIR}` 대체 문단과 zsh 문단은 지운다.
3. 패키지 이름 **`yfinance_skill`**. 테스트 폴더는 `tests/yfinance`를 유지한다.
4. 선언 위치는 **입력은 `cli.py`, 출력은 `yahoo/`**. 두 쪽은 데이터셋 키로 결합한다(`## 선언 분리`).
5. 의존성은 **`exclude-newer` + `requires-python = ">=3.12,<3.14"`**. `yfinance[repair]==1.7.0`, `pandas`, `numpy`를 직접 선언하고, 잠금 날짜는 `2026-09-13T13:10:00Z`다. 해시는 고정하지 않는다(이 한계는 커밋 본문에 적는다).
6. 테스트 seam: **CLI 프로세스 seam 유지 + 파생 환경.** pytest 환경은 `uv export --script`에서 만들고, 자식 프로세스는 `[sys.executable, cli.py]`다. 실제 `uv run`은 이동성 테스트가 따로 확인한다. in-process seam은 두지 않는다. 주변 seam은 구조 테스트(AST), live(`-m live`), Claude Opus 시나리오다.
7. 결함 범위: **저장·오류 계약 5건(✓1–5) + 모델이 읽는 신호의 진실성 4건(✓6·8·9·11).** 가장자리 2건(✓7·10)은 `## 하지 않는 것`에 둔다.
8. **`coverage.exhaustive` 제거 + `coverage.requested`.** 원천에 개수를 청하는 리프가 싣는다.
9. 회복 명령은 **하위 명령만**(`read ID …`)이다. 최소 예산 1000자를 지키기 위해서다.
10. SKILL.md 검증: **예산을 강제한 문단 제거 시험 + 회귀 표본**(Opus 약 15~20런).
11. PR **두 개**: ① 행동 불변 이행 ② 동작 변경.
12. 부족분 경고는 **리프별**이다. `requested`는 모든 개수 리프에 공통으로 싣고, 부족분이 무엇을 뜻하는지는 데이터셋 계약이 선언한다. 지금 경고를 내는 곳은 뉴스와 search 둘뿐이다. screen·달력은 `requested`와 `received`만 싣고, 완결 여부는 기존 `total`·`next_offset`·`conditions`가 말한다.
13. (프레임 재대조 뒤) **작은 닫힌 집합만 choices**: `screen run --preset`(19)과 `market sector KEY`(11). `--sort`·`--field`(equity만 93개이고 `--type`마다 다름)와 산업 키(약 145개)는 `--help`를 덮으므로 발견 명령 + fix를 유지한다(B11).
14. (프레임 재대조 뒤) **결과 봉투에서 `warnings`를 `data` 앞으로** 옮긴다: 싼 신호를 먼저 싣는다(B12).
15. (프레임 재대조 뒤) **새 기본값 대조는 하지 않는다.** 이유: 이번에 SKILL.md의 지식 내용은 사실 교정 하나 말고는 바뀌지 않는다. "문장이 모델 행동을 바꾸는가"는 문단 제거 시험이 더 직접 잰다. 지난 라운드 대조에서 남은 실패는 각각 자리가 있다(news-all → B7, screen-tech → `## 하지 않는 것`).

### Claude가 정한 것 (묻지 않음, 근거와 함께)
- **구조 테스트 수정.** 세 가지를 고친다.
  - 테스트 폴더를 패키지가 아니라 스킬 이름(`-` → `_`)에서 파생한다. facebook(`facebook`)과 naver-blog(`naver_blog`) 규칙과 맞는다.
  - 등록된 스킬의 테스트 폴더가 없으면 위반으로 본다. 등록 항목만 추가하면 yfinance 테스트가 조용히 빠지므로 필요하다.
  - SKILL.md 본문에도 호출문이 있는지 본다. skill-maker는 호출과 allowed-tools 양쪽에 같은 글자를 요구하는데, 지금은 프론트매터만 본다. facebook은 이미 본문에 같은 호출문이 있다.
- **의존성 섀도잉 검사는 추가하지 않는다.** 첫 import에서 바로 드러나는 결함이라 모든 테스트가 잡는다.
- **`pandas/`·`csv/` 시스템 폴더를 두자는 코덱스 권고는 기각한다.**
  - pandas → 스킬 표현 변환은 yahoo 어댑터가 pandas를 돌려주는 경계이므로 `yahoo/encode.py`에 둔다. 그래서 pandas·numpy·yfinance import는 `yahoo/` 안에만 있다.
  - CSV는 스킬이 정한 파일 형식이고 바뀔 이유가 하나다. 그래서 `export.py` 하나(저장소)로 둔다.
- **`budget.py`는 공용이다.** 모든 명령이 쓰는 출력 계약이다(facebook `outcome.py` 선례). 종료 코드 번호와 결과→종료 코드 매핑만 cli.py로 간다. 기능끼리는 import할 수 없어서, `read`의 continuation과 `shrink`가 함께 쓰는 회복 문장은 공용에 있어야 한다.
- **닫힌 입력 집합(choices)은 cli.py가 리터럴로 소유한다.** yahoo 어댑터는 같은 문자열을 키로 받는다. `yf.MarketRegion`은 1.7.0 값 8개를 리터럴로 옮기고, `test_vocabulary.py`가 라이브러리 enum과 대조한다(PR①에서 추가). `DOMAIN_REGIONS`(실측 목록)도 cli.py로 옮기고 `# 성진:` 주석을 보존한다.
- 저장소 `prune`과 `--out` 경로 사전 검사는 기능(`querying/`·`schema`) 쪽으로 옮긴다. cli는 저장소를 import할 수 없기 때문이다. 둘 다 요청 전에 실행된다.
- CI 워크플로의 yfinance 잡 명령은 새 환경으로 갱신한다. 재활성화는 범위 밖이다(이전 결정 8).
- 판정 모델은 Claude Opus 5.5(`claude-opus-5-5`)다. 코덱스(`gpt-6-astra`, high, `--priority`)는 설계·코드 리뷰를 맡고, 구현은 클로드가 끝까지 책임진다.
- 개발 기록(측정 경위, 기각한 대안, 기본값 교정 줄의 대상 모델)은 커밋 본문과 이 파일 끝 `# 구현 기록`에 둔다.
- `references/`는 만들지 않는다. 리프 지식은 schema가 소유하고, 분기별로 읽을 문서가 없다(이전 라운드 결정 유지).

### 추론과 수용된 가정 (사실과 구분)
- **추론**: aapl-news-all의 "전체" 오답이 `coverage.exhaustive: true` 때문이라는 인과는 증명되지 않았다. 이전 기록은 문단이 있든 없든 같은 오답이었다는 것만 말한다. B7은 이 플래그를 지우고 `requested`를 넣는다. 효과는 news-all 시나리오로 판정한다.
- **수용된 가정**: `exclude-newer`는 해시를 고정하지 않는다. 같은 날짜로 같은 버전이 풀린다는 것은 인덱스가 과거 릴리스를 지우거나 바꾸지 않는다는 가정 위에 있다(결정 5).
- **수용된 가정**: `yahoo/`라는 이름은 "Yahoo의 데이터 의미 + yfinance 라이브러리 API" 둘을 한 시스템으로 본다. 둘은 함께 바뀌고, 어댑터가 둘을 동시에 다루기 때문이다.

### 미결
- 없음. 구현 중 새 판단이 필요하면 AskUserQuestion으로 묻는다.

## 네 프레임이 이번에 결정하는 것

| 프레임 | 이번 변경 |
|---|---|
| principle over rail | SKILL.md는 새 규칙을 늘리지 않는다. too_large 문단의 "항상 저장돼 있다"는 사실 오류를 "id가 있을 때만 새 요청 없이 회복된다"로 고친다. 이 문단들이 행동을 바꾸는지는 예산을 강제한 제거 시험으로 판정한다. |
| interface over document | 종료 코드는 `--help`가, 작은 닫힌 집합은 choices가, 부족분은 `coverage.requested`와 데이터셋별 경고가, 트리는 구조 테스트가 소유한다. 치환 대체·zsh 설명은 문서에서 지우고 allowed-tools 한 줄로 대체한다. |
| for the model, not the maintainer | 출처 경위 주석(`# 성진:`)은 코드에 남기고, 모델이 읽는 schema·help에는 싣지 않는다. 오기 3건을 바로잡는다. |
| dense | `coverage.exhaustive`는 shown과 received로 계산되는 값인데 이름이 전수 주장을 부르므로 지운다. `context.upstream_requested`는 `coverage.requested`로 옮겨 중복을 없앤다. |

## skill-maker 조항 대조표

`/Users/seongjin/.claude/skills/skill-maker/SKILL.md`의 조항을 하나씩 이 계획에 맞댄 표다. 구현 세션과 코덱스 리뷰 ③이 이 표를 체크리스트로 쓴다.

| 조항 | 이 계획의 자리 |
|---|---|
| Principle over rail | SKILL.md 세 문단은 이유와 함께 쓴 원리이고, 사실 오류를 고친다(B8). 존폐는 제거 시험으로 정한다(결정 10). |
| Interface over document | 종료 코드는 `--help`(B1), 닫힌 집합은 choices(B11, 큰 집합은 이유를 적고 제외), 부족분은 `coverage.requested`(B7)가 맡는다. 치환·zsh 설명은 문서에서 지운다(결정 2). |
| For the model, not the maintainer | help·schema 문자열에 측정 경위 문구가 없다(2026-09-26 grep: 의미 문장만 걸림). 경위는 `# 성진:` 주석과 `# 구현 기록`에만 있고, 오기 3건은 B10이 고친다. |
| Dense | `exhaustive` 제거, `upstream_requested` 중복 제거(B7). SKILL.md는 제거 시험 결과 첫 문단만 남아도 합격이다. |
| 대조로 기본값과의 차이 찾기 | 이번에는 하지 않는다(결정 15, 이유 기록). |
| 권위 종류 구분·장부(사실·추론·결정·가정·미결) | `## 장부`의 다섯 절. |
| 증거로 못 정하는 것은 합의 | AskUserQuestion으로 결정 15개. 위치(프로젝트 스킬)와 언어(영어)는 기존 사실이라 유지한다. |
| 완료를 확인 가능하게 | 모든 단계의 완료 판정은 명령·테스트·수치다. |
| 필요한 때에 따라 파일 분리, references | 분기별로 읽을 문서가 없으므로 `references/` 없음. |
| 트리: `scripts/cli.py` + 패키지 하나, 폴더 이름이 내용을 말함 | `## 최종 스킬 디렉터리 구조`. 구조 테스트가 강제한다. |
| 도메인 모양이 틀과 안 맞으면 사용자에게 | 패키지 이름 충돌 → 결정 3. 선언 위치 충돌 → 결정 4. |
| `sys.path`를 건드리지 않음, stdlib 가림 없음 | 구조 테스트(`path_edits`, `stdlib_module_names`). 서드파티 가림은 결정 3으로 피한다. |
| `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`, 호출과 allowed-tools가 같은 글자 | 결정 2. 지금 구조 테스트는 프론트매터 allowed-tools만 대조한다(`test_skill_layout.py:110-116,202-203`). 단계 1ⓒ에서 "SKILL.md 본문에 같은 호출문이 있다" 검사를 더한다. |
| PEP 723이 `requires-python`과 모든 의존성을 말함 | 결정 5(pandas·numpy 직접 선언). 구조 테스트가 헤더를 파싱한다. |
| cli.py = 표면 전부(파서·도움말·디스패치·종료 코드), 도메인 로직 없음 | 결정 4, `## cli.py 계약`(`SHARED`·`POINTER`까지 cli로). |
| 모든 인자 설명, 닫힌 집합은 choices | B11, 코덱스 리뷰 ③의 help 대조. |
| 하위 패키지: 기능·외부 시스템·저장소, 둘째 이유가 생길 때 분리 | `yahoo/`(시스템), `store`·`export`(저장소), `querying/`·`schema`(기능), 공용 6. `querying/`은 모듈 셋이라 폴더다(M7 관례). |
| import는 한 방향 | `ALLOWED` + 구조 테스트, `test_boundary.py`. |
| stdout = 모델이 쓸 결과 한 문서, 싼 신호 먼저, 비싼 상세는 핸들 | JSON 한 문서(현행), `warnings`를 `data` 앞으로(B12). 핸들은 저장 id·`continuation`·`--out`. |
| stderr = 진행·진단 | 현행(`redirect_stdout(sys.stderr)`)을 `querying/observe.py`로 옮긴다. |
| 0 성공, 2 잘못된 인자, 나머지는 `--help`가 정의 | B1. |
| 테스트·유지보수 도구는 스킬 밖, 구조 테스트 | `tests/yfinance`, `tests/test_skill_layout.py`(등록과 검사기 수정). 골든 도구는 `.tmp/`. |
| 기존 코드의 이행은 따로 합의 | 성진의 요청 자체가 이행이다(Context). |
| 완료: 전문 승인 · `validate --strict` · 계약 대조와 help 일치 · 다른 모델 계열 검토 · 개발 기록은 밖 | 단계 9(승인·validate·help 대조·코덱스 SKILL.md 검토), 단계 10(`# 구현 기록`). |
| 새 스킬은 이웃과 경계(skill-doctor) | 설명은 바꾸지 않지만 단계 9에서 한 번 돌린다. |

## 최종 스킬 디렉터리 구조

```
.claude/skills/yfinance/
├── SKILL.md
└── scripts/
    ├── cli.py                     # PEP 723 헤더 + 명령 표면 전부(아래 `## cli.py 계약`)
    └── yfinance_skill/            # 유일한 패키지 (__init__.py 비어 있음)
        ├── envelope.py            # 공용 ← envelope: 결과 봉투·ordered·error_info·now·as_time, STATUSES, InputError, condition·within_dates·monotonic (EXIT_CODES는 cli.py로)
        ├── shape.py               # 공용 ← encode의 TABLE_KEYS·is_table·is_sided·is_empty·row_count·column: 스킬 표현이 무엇인지
        ├── display.py             # 공용 ← encode의 STAMP·MIDNIGHT·number·dated·day·deep·display_table·display·dump: stdout이 어떻게 찍는지
        ├── selection.py           # 공용 ← selection: 투영·필드 목록·행 창·옵션 양면
        ├── budget.py              # 공용 ← budget: document·overall·shrink·too_large 사다리·회복 문장·read_command·strip·emit(결과 종류를 돌려줌) (code → cli.py, upstream_fix → yahoo)
        ├── leaf.py                # 공용(신설): Leaf = cli 입력 선언 + yahoo 데이터셋의 결합. 기존 코드가 읽는 속성(path·limit·fields·recent·precise·sliceable·exportable·narrow·forbidden·coarser·shares_info …)을 그대로 노출
        ├── yahoo/                 # 시스템: Yahoo Finance(yfinance 라이브러리). 바뀔 이유: Yahoo·yfinance가 필드·스케일·순서·게터를 바꿈
        │   ├── __init__.py        # DATASETS(그룹 모듈의 DATASETS를 명시적으로 병합) + fetch(key, target, args, context, warnings) → 인코딩된 값. yf.Ticker 생성·hide_exceptions 설정 소유
        │   ├── datasets.py        # Dataset(fetch·ticker·window rows/fields·recent·precise·sliceable·shares_info·source_time·conditions·prepare·shortfall·units·interpretation·limits·gotchas), 단위 어휘(RATE·PERCENT·WEIGHT…), asked(args, dataset)
        │   ├── encode.py          # ← encode.encode: pandas·numpy → 스킬 표현(무손실)
        │   ├── refusals.py        # ← budget.CONSTRAINTS·upstream_fix + is_rate_limited(observe·bars·statement_currency가 공유)
        │   ├── info.py            # ← prices.info·info_time·SOURCE_TIME_FIELDS·INFO_UNITS·CURRENCY_SPLIT·QUOTE_TIME: quote·profile이 공유하는 조립 응답
        │   ├── prices.py          # quote·history·actions (bars, dates_applied, PRICE_COLUMNS)
        │   ├── company.py         # profile·shares·news·filings
        │   ├── financials.py      # income·balance·cashflow·valuation (statement_currency)
        │   ├── analysts.py  holders.py  fund.py  options.py
        │   ├── screen.py          # presets·fields·values·run (query_catalog·parse_query·프리셋 기본값 prepare·screen_conditions)
        │   ├── market.py          # summary·sectors·sector·industry (SECTORS·DOMAIN_DATA)
        │   ├── calendar.py        # earnings·economic·ipo·splits (market_wide·one_company·dates_applied)
        │   └── search.py
        ├── store.py               # 저장소 ← store: 내용 주소 관측 저장·load·prune·record·age_seconds
        ├── export.py              # 저장소 ← export: --out CSV 형태 변환·원자적 게시·check_path·Unpublished·summary
        ├── querying/              # 기능: 데이터 명령에 답한다 (바뀔 이유: 대상 루프·저장·재독·내보내기 정책)
        │   ├── observe.py         # ← yfinance_cli.observe·run·DeadlineExpired·timed_out + open(저장소 생성·prune) + prepare(--out 사전 검사 → command.check → command.defaults → dataset.prepare, `## 실행 순서`)
        │   ├── read.py            # ← yfinance_cli.read
        │   └── out.py             # ← yfinance_cli.exported·retry·write_out
        └── schema.py              # 기능 ← schema: 오프라인 발견. cli가 넘긴 파서·명령·종료 코드표와 yahoo 데이터셋 계약으로 조립
```

- **분류(구조 테스트 등록 항목)**
  - 공용: `envelope` `shape` `display` `selection` `budget` `leaf`
  - 시스템: `yahoo`
  - 저장소: `store` `export`
  - 기능: `querying` `schema`
  - 방향은 `tests/test_skill_layout.py`의 `ALLOWED`를 따른다: 공용은 공용만, 시스템·저장소는 공용·시스템·저장소, 기능은 공용·시스템·저장소(다른 기능 금지), cli는 공용·기능만.
- **이동으로 풀리는 위반 간선**(코덱스 감사 B4 + 클로드 확인)
  - cli → store·export·groups·encode: 저장·내보내기·가져오기를 `querying`으로 옮겨 없앤다.
  - envelope·selection → encode(시스템이 될 pandas 변환): 형태 판별을 `shape`로 빼서 없앤다.
  - company → prices: 공유 조립을 `yahoo/info.py`로 옮긴다. 어차피 같은 시스템 안이지만, 이 간선은 이유가 드러나게 한다.
  - 어댑터가 레지스트리를 역조회하던 것(`company.py:42`, `search.py:28`, `calendar.py:54,70`, `screen.py:140,171`의 `get(...)`)은 자기 데이터셋의 `asked(args, DATASET)`로 바꾼다.
  - `budget.py`와 `schema.py`는 종료 코드를 cli에서 import하지 않고 인자로 받는다.
- **import 경계**: `yfinance`·`pandas`·`numpy` import는 `yahoo/` 아래에만 있다(`test_boundary.py`가 AST로 강제).

```
tests/
├── __init__.py                    # 유지(빈 파일)
├── test_skill_layout.py           # 수정: 테스트 폴더를 스킬 이름에서 파생 + 부재 위반, yfinance 등록
└── yfinance/
    ├── conftest.py                # CLI = .claude/skills/yfinance/scripts/cli.py, [sys.executable, CLI] (그 밖은 유지)
    ├── fixtures/{sitecustomize.py, shapes/*.json}   # 유지
    ├── model-scenarios.json       # + 예산 조건 시나리오 5건(P1 P2 T1 T2 M1, 전제 포함), news-all
    ├── test_cli.py  test_discovery.py  test_selection.py  test_display.py  test_budget.py
    ├── test_store.py  test_export.py  test_prices.py  test_company.py  test_market.py   # 파일명 유지, 새 동작은 해당 파일에
    ├── test_portability.py        # 신규: 실제 uv run "<사본>/scripts/cli.py" (공백·한국어·$·따옴표 경로, 무관한 cwd, sitecustomize 주입, 실행 뒤 scripts/ 항목 불변)
    ├── test_vocabulary.py         # 신규: --help의 리터럴 choices(MarketRegion·프리셋)가 라이브러리 값과 같은지(라이브러리만 import, production은 CLI로)
    ├── test_boundary.py           # 신규(AST, 구조 seam): yfinance·pandas·numpy를 import하는 모듈이 yfinance_skill/yahoo/ 아래뿐(함수 안 import 포함). production을 import하지 않고 소스만 읽는다
    ├── fixtures/store/*.json      # 신규: 이행 전 CLI로 만든 관측(quote·history·read 대상) — 옛 관측이 이행 뒤에도 read·--from으로 읽히는지
    └── test_live.py               # -m live: CLI 실행을 uv run "<CLI>"로(옛 --project 제거)
```

## cli.py 계약

첫머리 PEP 723:

```python
# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["yfinance[repair]==1.7.0", "pandas", "numpy"]
#
# [tool.uv]
# exclude-newer = "2026-09-13T13:10:00Z"
# ///
```

cli.py가 드는 것(도메인 로직 없음, 섹션 순서대로):
1. `EXIT_CODES`. 설명이 붙은 선언 하나다. PR①에서는 schema로만 넘기고, PR②에서 루트 `--help` epilog에도 싣는다.
2. 공통 인자(`GLOBAL_DEFAULTS`·`OUT_HELP`·`add_common`)와 선언 도구(`Arg`·`OneOf`·`dates`·`Command`). 공통 인자의 적용 범위 문구(`schema.py`의 `SHARED`·`POINTER`)도 인자 텍스트이므로 cli.py가 소유하고 schema에 넘긴다. schema 기능은 출력의 뜻(`ENVELOPE`)만 소유한다.
3. 공유 인자 묶음(`SYMBOLS`·`FROM`·`BAR_ARGS`·`RANGE`·`TYPE`·`FIELD`…)과 닫힌 입력 집합의 리터럴(interval·region·`DOMAIN_REGIONS`·search type·frequency…).
4. CLI 정책 함수: `period_unless_dates`·`week_from_today`·커스텀 쿼리 정렬 기본값·조합 검사(screen 250·calendar 100 상한, 단일 심볼 earnings, search `--type`)·`coarser_bars`의 문구.
5. `GROUPS`(11개 목적)와 `COMMANDS`(리프 49개). 명령 경로(`"prices history"`, 그룹만인 `"search"`)를 키로 하고, 각 선언은 목적·`dataset` 키·인자·기본값 함수·검사·narrow·forbidden·coarser·end_exclusive·epilog·exportable을 담는다. **선언 순서 = 옛 등록 순서**다: 그룹은 search, prices, company, financials, analysts, holders, fund, options, screen, market, calendar 순이고, 그룹 안에서는 옛 모듈의 등록 순서(루프 포함)를 따른다. `--help`·schema의 나열 순서가 이것으로 정해진다.
6. `build_parser`, `validate`, `chosen`(request 메아리), 디스패치, 결과 종류 → 종료 코드. 순서는 아래 `## 실행 순서`를 따른다.

## 실행 순서 (PR ①은 현행 순서를 그대로 보존한다)

현행(`yfinance_cli.py:297-323`)을 층만 옮긴 순서다. 기능끼리 import할 수 없으므로, 명령 카탈로그와 전역 기본값은 cli가 인자로 넘긴다.

1. 파싱(argparse 오류 → invalid) → `--max-chars` 하한 검사.
2. `saved = querying.open(args)`: 저장소 생성과 `prune`. 현행처럼 **검증보다 먼저** 돈다. PR②의 B2가 `--ttl-days` 검증을 이 앞으로 옮긴다.
3. `schema`는 `schema.run(args, parsers, root_parser, GROUPS, COMMANDS, GLOBAL_DEFAULTS, EXIT_CODES)`로 간다.
   - 합성 네임스페이스에 명령의 CLI 기본값 함수와 `yahoo` 데이터셋의 `prepare`를 적용한다. `prepare`는 **부작용 없는 순수 함수**여야 한다.
   - `querying.prepare`는 부르지 않는다: 저장소·`--out` 검사가 없다.
4. `read`는 `querying.read(args, saved, COMMANDS)`로 간다. 저장 레코드의 `command`(공백 구분 경로)를 `COMMANDS`에서 찾고, `Command.dataset`으로 `yahoo.DATASETS`와 합쳐 `leaf.Leaf`를 만든다. 순서는 현행과 같다: load → 선택 → `--out` 검사.
5. 데이터 명령은 다음 순서로 간다.
   - `given = dict(vars(args))` 스냅샷. 반드시 **복사본**이어야 한다(현행 `yfinance_cli.py:312`). 별칭이면 뒤의 `prepare`가 바꾼 값이 함께 바뀐다. 그러면 `chosen()`이 "기본값이 채운 값"을 가려내지 못한다(예: `--type etf` + equity 프리셋 → `type: equity`가 사라짐).
   - cli `validate`의 문법 구간: 대상 공백 → timeout → 최소값 → offset → start → 날짜 형식 → 범위 → period → `--list-fields`/`--out` 충돌.
   - `querying.prepare(command, args)`가 현행 순서 그대로 네임스페이스를 실효값으로 바꾼다: `--out` 사전 검사 → `command.check` → `command.defaults` → `dataset.prepare`.
   - cli의 `--fields` 빈 이름 검사.
   - 그다음 저장용 전체 `request`와 화면용 `chosen(request, given, parser)`을 만든다.
   - `querying.observe(args, command, COMMANDS, saved, request)`. `--from` 호환 명령 집합은 `COMMANDS`와 데이터셋의 `shares_info`로 계산한다.
6. 기능은 `budget.emit`으로 문서를 찍고 결과 종류를 돌려준다. cli가 그것을 `EXIT_CODES`의 번호로 바꾼다. `InputError`는 cli가 `budget.emit`으로 오류 문서를 찍는다(현행 `main`의 except).

PR ①의 골든에는 다중 오류 조합을 넣어 위 순서를 고정한다. 예: `screen run --preset unknown --limit 251 --out <있는 파일>`(현행: 파일 오류가 먼저), `read <없는 id> --start -1`, `prices history AAPL --period 1mo --start 2024-01-01 --out <없는 디렉터리>/x.csv`.

## 선언 분리 (성진 결정 4)

| 지금 `Leaf` 필드 | 새 소유자 | 이유 |
|---|---|---|
| group·name·purpose·args(help·choices·default·minimum)·epilog | cli `Command` | 명령 표면 |
| defaults: `period_unless_dates`·`week_from_today`·커스텀 쿼리 정렬 | cli | 인자 기본값 정책 |
| defaults: 프리셋의 type·sort·방향 | yahoo `screen.prepare` | `yf.PREDEFINED_SCREENER_QUERIES`가 필요 |
| check: 조합·상한(250·100) | cli | 인자 검증(상한의 근거는 Yahoo지만 표현은 입력 제약) |
| check: 쿼리 파싱·알려지지 않은 필드·목록에 없는 만기 | yahoo(가져오기 시점, 지금처럼) | Yahoo 카탈로그가 필요 |
| narrow·forbidden·coarser·end_exclusive·exportable | cli | 인자를 이름 붙이는 회복·검증·`--out` 제공 여부 |
| fetch·ticker·shares_info·source_time·conditions | yahoo `Dataset` | 가져오기와 응답 판정 |
| limit(창 rows)·fields(기본 투영)·recent | yahoo `Dataset.window` | 한 화면에 무엇이 오나 — 원천의 크기·순서 |
| precise·sliceable | yahoo | 원천 정밀도·형태 |
| units·interpretation·limits·gotchas·shortfall | yahoo | 값의 뜻 |

- 결합 키는 `Command.dataset`(예: `"prices.history"`)이고, `querying`·`schema`가 `yahoo.DATASETS`에서 찾아 `leaf.Leaf`로 합친다. 명령 자체는 cli가 넘긴 `COMMANDS`에서 명령 경로(`"prices history"`)로 찾는다. 저장 레코드의 `command`도 이 경로라서 옛 관측이 그대로 읽힌다. 키가 없으면 그 명령의 첫 사용에서 명시적 오류가 난다. `test_discovery`가 49리프 전부의 `schema GROUP LEAF`를 부르므로 결합 누락은 CLI seam에서 잡힌다.
- 리프 하나를 바꿀 때 여는 곳: 인자·도움말·검증은 cli.py, Yahoo 동작·뜻은 `yahoo/<그룹>.py`. 상류로 넘기는 새 인자는 두 곳이다.

## 테스트 환경 (성진 결정 6)

```bash
# 오프라인 스위트 + 구조 테스트 (CONTRIBUTING·CI의 yfinance 잡). export 실패가 조용히 빈 환경이 되지 않도록 파일로 받고 set -e로 멈춘다.
bash -c 'set -euo pipefail; mkdir -p .tmp; uv export --quiet --script .claude/skills/yfinance/scripts/cli.py --no-hashes -o .tmp/yf-test-req.txt; uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/yf-test-req.txt --with pytest==8.4.2 python -m pytest tests/yfinance tests/test_skill_layout.py'
uvx ruff check --config pyproject.toml .claude/skills/yfinance/scripts tests/yfinance
```

- `--python ">=3.12,<3.14"`는 스크립트의 `requires-python`과 같은 범위다. 바깥 `uv run`은 PEP 723을 읽지 않으므로 따로 준다. 두 곳이 어긋나면 `test_portability`가 실제 `uv run` 경로로 잡는다.
- 루트 `pyproject.toml`의 pytest 설정(`addopts = "-m 'not live'"`)이 그대로 적용된다. `tests/yfinance`에는 `__init__.py`가 없어 `from conftest import …`가 유지된다.
- 루트 `pythonpath`에 yfinance `scripts/`는 추가하지 않는다. in-process import가 없기 때문이다.
- CI offline 잡(`python -m pytest tests/ --ignore=tests/yfinance …`)은 `tests/test_skill_layout.py`로 yfinance 트리를 AST로만 검사하므로 의존성이 필요 없다.

## 동작 변경 명세 (PR ②)

각 항목은 CLI seam에서 손으로 쓴 리터럴 기대값의 재현 테스트가 먼저 red여야 한다. 빨간 이유가 import·환경 오류이면 무효다.

- **B1 종료 코드표.** 루트 `--help` epilog에 `EXIT_CODES` 전부를 한 줄씩 싣는다(0 2 4 5 6 7 8 9). 루트 `schema`의 `exit_codes`와 같은 선언에서 나온다. 테스트는 기대 집합을 리터럴로 쓰고, help와 schema 양쪽이 그 집합과 같은지 본다.
- **B2 `--ttl-days`**(✓1). 음수는 `invalid`(exit 2)로 거절하고, 0은 정리를 끈다(현행). 검증은 모든 저장소 변경보다 먼저 한다. 테스트: 관측 하나를 저장 → `--ttl-days -1 schema` → exit 2 → `read ID`가 여전히 성공.
- **B3 공통 검증**(✓2). `read`를 포함한 모든 명령이 디스패치 전에 같은 검증을 거친다. 테스트: `read ID --start -1`·`read ID --limit 0` → invalid, 파일·저장소 불변.
- **B4 레이트리밋 전파**(✓3). `yahoo/refusals.is_rate_limited` 하나를 `observe`·`bars`·`statement_currency`가 공유한다. 통화 조회에서 난 레이트리밋은 `context.rate_limited`를 세우고, 다음 대상은 `not_attempted`가 된다. 테스트: `financials income AAPL MSFT`에서 AAPL info 경로가 429 → AAPL은 경고와 함께 결과를 내고, MSFT는 요청 0으로 `not_attempted`.
- **B5 로컬 파일 실패**(✓4). `--out` 게시의 임시 파일 생성까지 보호 경계 안에 넣고, 저장소 생성·읽기의 `OSError`도 `local_io`(exit 4) JSON으로 낸다. 트레이스백과 빈 stdout은 없어야 한다. 테스트 세 가지:
  - 쓰기 불가 디렉터리의 `--out`.
  - 일반 파일 아래 경로를 가리키는 `YF_STORE`.
  - 관측 파일 자리에 디렉터리가 있는 `read ID`(`Store.load`의 `FileNotFoundError` 밖 실패).
  - 셋 다 JSON 한 문서·exit 4·트레이스백 없음을 본다. 없는 id는 지금처럼 exit 2다.
- **B6 `--out` 경로 보존**(✓5). 파일은 예산 판단보다 먼저 쓰이므로, 문서가 그 사실을 잃으면 안 된다. 게시된 결과가 있는 문서의 사다리는 다음과 같다.
  - ① 대상별 요약.
  - ② 열 목록 → 개수(현행).
  - ③ 대상별 `{target, status, rows}` + 경로는 한 번만.
  - ④ 문서 수준 영수증 `{out, rows(합계), in_file(파일에 행이 있는 대상 수), missing: {상태: [대상…]}}` + "대상별 행 수는 파일의 target 열" 한 문장. 파일에는 empty·error·not_attempted 대상의 행이 없다(PR #21 `--out` 계약). 그래서 **파일에 없는 대상과 그 상태는 영수증이 반드시 말한다.** 문서의 `status`는 현행대로 전체 상태다.
  - ⑤ `missing`의 대상 목록도 넘치면 상태별 개수(`{상태: n}`)로 줄이고, "ask for fewer targets to see which"를 덧붙인다.
  - ⑤도 예산을 넘는 경우는 경로 자체가 예산에 비해 너무 긴 경우뿐이다(⑤의 나머지는 고정 크기). 이 경우는 요청 전에 `--out` 사전 검사가 invalid로 거절한다("the receipt for this path does not fit --max-chars N; use a shorter path or raise it"). 그래서 "stdout은 `--max-chars`를 넘지 않는다"는 계약이 예외 없이 유지된다.
  - 테스트
    - 132자 경로 + 10대상(전부 성공) + `--max-chars 1000` → exit 0, 경로와 행 합계가 있음.
    - 성공·empty·error·not_attempted가 섞인 다대상 + 예산 초과 → 문서 status partial, 영수증의 `missing`이 실패·빈·미시도 대상을 상태별로 정확히 말함.
    - 영수증이 들어가지 않는 긴 경로 → 요청 0으로 exit 2.
- **B7 요청 대비 수신**(✓6, 결정 8·12).
  - `coverage.exhaustive`를 지운다.
  - `requested`는 **원천에 실제로 개수를 보낸 모드만** 싣는다: company news, screen run, calendar 4종(시장 전체·단일 심볼), search의 `quotes`·`news`·`lists`. search `research`는 개수를 보내지 않으므로 싣지 않는다.
  - 관측 시점의 요청 개수는 저장 레코드의 최상위 `requested`에 보존하고, 첫 호출·`shrink`·`--out`·`read` 모든 경로의 coverage가 그 값을 싣는다. 그래서 `read ID --limit 5`는 원래의 300을 5로 바꾸지 않는다.
  - `context.upstream_requested`는 지운다. `native_batch_size`는 유지한다. 이전 버전의 레코드(`requested` 없음)는 `requested` 없이 읽힌다.
  - 경고는 데이터셋이 `shortfall`을 선언했고 `received < requested`일 때만 관측 시점에 한 줄 붙는다. 경고는 저장되므로 `read`에도 남는다.
    - news가 말할 것: 쓸 수 있는 항목이 요청보다 적게 왔다. yfinance가 광고를 빼므로 피드가 끝났는지는 확인되지 않는다. 회사의 모든 기사도 아니다.
    - search가 말할 것: Lookup 첫 페이지만 읽었다.
  - schema `ENVELOPE`의 coverage 설명에 `requested`를 넣는다.
  - 테스트
    - news: `--limit 300`에 196건 픽스처(광고 1건 포함) → `requested` 300·`received`는 광고를 뺀 수·부족분 경고.
    - 같은 관측을 예산으로 축소한 결과, `--out` 결과, `read ID --limit 5`가 모두 `requested` 300을 싣는다.
    - 행이 적은 calendar → 부족분 경고 없음(기존 zero-loss 경고는 남음).
    - search `research` → `requested` 없음.
    - 어떤 출력에도 `exhaustive` 키가 없음.
- **B8 저장 약속은 실제 핸들에서**(✓8). too_large 사다리는 "all N targets were saved"를 id가 있는 결과 수로만 말한다. 저장이 없는 결과(schema, 실패 대상)에는 저장을 약속하지 않는다. SKILL.md too_large 문단도 같은 사실로 고친다. 테스트: 한 대상이 실패한 다대상 too_large → 저장된 수와 id 목록이 실제와 같다.
- **B9 상류 제약 두 종류**(✓9). "Only N days worth of X granularity"(창 길이)와 "must be within the last N days"(과거 도달 범위)를 구분해 처방한다. `1h and 1d have no such limit` 단정은 schema의 "no range limit known"과 같은 수준으로 낮춘다. 테스트: 두 메시지 각각의 fix 문장이 자기 제약만 말한다(기존 `test_an_upstream_constraint_names_the_argument_to_change` 확장).
- **B10 도움말·해석 오기**(✓11).
  - 재무제표 `--periods` 도움말에서 valuation 문구를 뺀다.
  - search gotcha를 "ignore" → "rejected"로 고친다.
  - 재무제표 날짜는 "row labels (the index)"라고 쓴다.
  - 문장 반복 테스트는 쓰지 않는다(CONTRIBUTING). 완료 판정은 해당 schema 출력 확인과 `--type etf --dataset news` → invalid(현행 행동)다.
- **B11 작은 닫힌 집합은 choices**(결정 13).
  - `screen run --preset`: cli.py에 리터럴 19개를 `yf.PREDEFINED_SCREENER_QUERIES` 순서대로 둔다.
  - `market sector KEY`: 섹터 키 11개를 리터럴로 둔다.
  - 틀린 값은 argparse가 후보와 함께 요청 전에 거절한다(invalid, exit 2). 옛 `Unknown --preset` 검사는 지운다.
  - 섹터 목록은 `market sectors`의 출력(yahoo)과 choices(cli) 두 곳에 있다. CLI seam 테스트가 `market sectors` 출력과 `market sector --help`의 choices가 같은지 본다.
  - 프리셋 리터럴은 `test_vocabulary.py`가 라이브러리 값(`yf.PREDEFINED_SCREENER_QUERIES`, 그리고 `yf.MarketRegion`)과 대조한다.
  - `--sort`·`--field`·산업 키를 choices로 하지 않는 이유(크기, `--type` 의존)는 cli.py 해당 인자 옆 `# 성진:` 주석에 적는다.
  - 테스트: `--preset nope`·`market sector nope` → exit 2, 요청 0. 오류 메시지에 올바른 후보가 들어 있다.
- **B12 싼 신호 먼저**(결정 14).
  - 결과 봉투 키 순서: `target, id, observed_at, source_time, stored_age_seconds, status, context, conditions, coverage, continuation, warnings, data, error`.
  - schema `ENVELOPE` 설명의 순서도 같게 맞춘다. 예산은 문서 전체 길이로 재므로 사다리는 영향받지 않는다.
  - 순서는 **찍기 직전에** 보장한다. `budget.strip`(출력 사본)이 모든 결과에 `ordered`를 적용한다. 그러지 않으면 `shrink`가 나중에 붙이는 partial 경고(`budget.py:53-54`)가 `data` 뒤에 남는다.
  - 테스트
    - 처음부터 경고가 있는 결과의 키 순서가 위 리터럴 목록과 같다.
    - 경고 없이 시작해 예산 때문에 partial이 된 결과에서도 최종 stdout의 `warnings`가 `data`보다 앞이다.
    - `read`의 continuation 결과도 같다.

## SKILL.md 섹션 구조 (영어, 문단 제거 시험으로 존폐 판정)

```
---
name: yfinance
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: (현행 유지 — 트리거 문구가 안 바뀌므로 skill-doctor 재확인 불요)
---
# Yahoo Finance data
   ¶ Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` on one line. `--help` gives the commands, their arguments and the exit codes; `schema` what results, fields and units mean; each error's `fix` how to recover. (필수 인터페이스, 제거 시험 제외. PR①은 호출 한 줄로 바꾸고 치환 대체·zsh 문단을 지운다. PR②는 "exit codes"를 넣는다)
## When a result is short                       (문단마다 제거 시험)
   ¶ partial: 요청한 것의 일부가 빠졌다(예산이 자른 행, 일부 대상 실패). 잘린 행은 저장돼 닿고 실패 대상은 아니다 → 완성하거나 한계를 말하고, 부분을 전체로 서술하지 않는다.
   ¶ too_large: 크기 조건이지 빈 결과가 아니고, 요약할 부분 표가 없다. 결과에 id가 있을 때만 이미 저장돼 새 요청 없이 회복된다. (B8 사실 교정)
   ¶ 회복은 질문을 보존한다: 같은 대상·필드·범위를, fix가 이름 붙인 store에서. 대상을 빼면 비교가 단일 종목 질문이 되고, 좁히면 다른 질문이 된다 — 그렇게 한다면 말한다. 레이트리밋 뒤에는 멈춘다. 결론에 영향을 주는 커버리지와 한계를 말한다.
```

- `references/`: 없음(`### Claude가 정한 것`). 완성본 전문은 단계 9에서 성진이 승인한다.
- 제거 시험 결과 모든 문단이 행동을 바꾸지 않으면, SKILL.md는 첫 문단만 남는다. 그것도 합격이다.

## 작업 단계

두 PR로 나눈다(결정 11). 단계는 곧 커밋이다. 구현 세션은 먼저 `ToolSearch("select:TaskCreate,TaskUpdate,TaskList")`로 트래커를 불러 단계마다 `TaskCreate`하고, description에는 아래 완료 판정을 그대로 적는다. 테스트를 쓰는 단계는 `tdd` 스킬을 연 상태에서 합의된 seam(결정 6)에서만 red→green으로 간다. 코덱스 리뷰는 `codex` 스킬(`gpt-6-astra`, high, `--priority`, read-only)을 쓰고, 이 계획의 감사 스레드 `01a0ddff-8530-7200-a63d-0c97ecfc4261`을 resume한다. 지적은 반영하거나, 반영하지 않는 이유를 커밋 본문에 남긴다. 결정 1–15와 충돌하는 지적은 AskUserQuestion으로 올린다. 코덱스 리뷰 ①·③은 `## skill-maker 조항 대조표`를 체크리스트로 받는다.

### PR ① `refactor/yfinance-cli-package` — 행동 불변 이행 (`refactor: yfinance를 cli.py와 패키지 하나로 옮긴다`)

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | `main`에서 브랜치, 트래커 등록(계획 파일 이름은 계획 세션에서 변경됨) | 브랜치·트래커 존재 |
| 1 | **골든 캡처 + 옛 관측 픽스처 + 구조 검사기 수정.** ⓐ `.tmp/yf-golden/`(커밋 안 함)에 기록한다: 루트·11그룹·49리프의 `--help`와 `schema`, 오프라인 스위트의 모든 CLI 호출(argv, stdout, exit, `--out` 파일 바이트), `## 실행 순서`의 다중 오류 조합. 스위트 호출은 테스트 프로세스의 `subprocess.run`을 감싸는 pytest 플러그인을 `-p`로 불러 기록한다. 정규화는 휘발 값만 한다: `observed_at`·`stored_age_seconds`·16hex id·임시 경로·CLI 경로. 캡처와 비교는 같은 날 실행한다(달력 기본 날짜). ⓑ 이행 전 CLI로 픽스처 경로의 관측을 만들어 `tests/yfinance/fixtures/store/`에 커밋하고, `test_store.py`에 테스트를 더한다: 그 사본을 `YF_STORE`로 `read ID`·`--from`(quote → profile)이 읽는다. 이 테스트는 이행 전에 green이어야 한다. ⓒ `tdd`로 `tests/test_skill_layout.py`를 고친다. 먼저 합성 트리 셋이 red인지 확인한다: 패키지와 테스트 폴더 이름이 다른 트리, 테스트 폴더가 없는 등록 스킬, 본문에 호출문 `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"`가 없는 SKILL.md. 그다음 파생 규칙·부재 위반·본문 호출문 검사로 green을 만든다 | 캡처 두 번 실행이 바이트 동일 · 옛 관측 테스트 green · 새 검사기 테스트가 수정 전 red 기록 · `python3 -m pytest tests/test_skill_layout.py` green(facebook 불변) |
| 2 | **기계적 이동 + 호출.** 대소문자 무시 FS라 `git mv`를 두 단계로 한다(`Scripts` → `scripts_tmp` → `scripts`). `yfinance_cli.py` → `scripts/cli.py`에 PEP 723 헤더를 붙인다. 평면 모듈 → `scripts/yfinance_skill/`(패키지 import로), `groups/` → `yfinance_skill/yahoo/`. `pyproject.toml`·`uv.lock`·`.python-version`을 삭제하고, 추적되지 않는 `.venv/`·`.ruff_cache/`·`__pycache__/`를 지운다. 테스트의 CLI 경로(`conftest.py:16,30`, `test_discovery.py:22`, `test_live.py:19-45` → `uv run "<CLI>"`), SKILL.md 프론트매터·호출문(치환·zsh 문단 삭제), `README.md:22,52`·`docs/usage.md:27,72-76`·`CONTRIBUTING.md:9,31,42-49`의 경로·환경 문장, CI yfinance 잡을 갱신한다 | `uv export --script scripts/cli.py --no-hashes`의 패키지 집합이 옛 `uv.lock`의 Python ≥3.12 집합과 같음 · 새 환경 명령으로 스위트 352 green · 골든 동일(허용 차이: `usage: cli.py` prog뿐) · `/tmp`에서 `uv run "<abs>/scripts/cli.py" --help` exit 0 · `ls -A scripts` = `cli.py`, `yfinance_skill`(+`__pycache__`) |
| 3 | **선언 분리와 층.** 시작할 때 `tests/test_skill_layout.py`에 yfinance를 위 분류로 등록한다(red). 3a 공용: `shape`·`display` 분리, `yahoo/encode`, `EXIT_CODES`·`code` → cli. 3b 시스템: `yahoo/datasets`·`info`·`refusals`와 그룹별 `Dataset`, `DATASETS` 명시 병합, 등록 부수 효과 제거. 3c 표면: cli.py의 `Command`·`GROUPS`·`COMMANDS`·공통 인자·CLI 정책 함수·닫힌 집합 리터럴, `leaf.Leaf` 결합. 3d 기능: `querying/`(observe·read·out·prepare), `schema`가 파서·명령·종료 코드표를 인자로 받음. 3e `test_boundary.py`(AST)를 더한다. 하위 단계마다 스위트와 골든을 확인한다 | 구조 테스트 green(yfinance 등록) · 스위트 green(352 + 옛 관측 테스트) · 골든 동일(허용 차이 동일, 다중 오류 조합 포함) · `test_boundary.py` green(`yahoo/` 밖 yfinance·pandas·numpy import 0) · `groups`·`registry` 이름이 트리에 없음 |
| 4 | **이동성·live·리뷰.** `test_portability.py`(실제 `uv run`, 경로 네 종류, 무관한 cwd, 픽스처 주입, 실행 뒤 `scripts/` 항목 불변), `test_vocabulary.py`(MarketRegion 대조; 프리셋 대조는 B11에서 추가). live 49리프 스윕은 이행 직전(`main`)과 직후를 같은 시간대에 돌린다 → **코덱스 리뷰 ①**(빠진 이동, 행동 차이, import 방향, skill-maker `## Code the skill bundles`와 `tests/test_skill_layout.py` 준수) | 이동성 green · 대상별 status와 열·필드 이름 집합이 이행 전후 동일(값·행 수는 비교 안 함) · 리뷰 blocking·major 0 |
| 5 | PR ①(템플릿 없음 → `## 무엇을 바꿨나/왜/영향/검증`, 계획 파일 포함), `gh pr merge --squash`, graphify 리빌드(로컬) | 머지·그래프 갱신 |

### PR ② `fix/yfinance-contracts-signals` — 동작 변경 (`fix: yfinance 저장·오류 계약과 신호를 바로잡는다`)

| # | 단계 | 완료 판정 |
|---|---|---|
| 6 | **표면: B1** 종료 코드표, **B11** 작은 닫힌 집합 choices, **B12** 봉투 순서 | 세 항목의 테스트 red → green · 루트 `--help`에 8개 코드 · `test_vocabulary.py` green |
| 7 | **B2–B6** 저장·오류 계약. 항목마다 red → green 커밋 | B2–B6의 재현 테스트 전부가 수정 전 red 기록(빨간 이유가 의도한 결함) · 스위트 green |
| 8 | **B7–B10** 신호. B7–B9는 red → green, B10은 문장 수정 → **코덱스 리뷰 ②**(저장·오류·부족분·회복 계약) | 재현 테스트 green · `grep -rn exhaustive .claude/skills/yfinance/scripts`가 0(테스트는 출력 키 부재를 단언하므로 대상에서 뺀다) · 리뷰 blocking·major 0 |
| 9 | **SKILL.md와 문서.** B8 사실 교정과 "exit codes"를 넣고, `docs/usage.md:81`의 coverage 설명을 필요한 만큼 갱신한다. 그다음 `## 검증`의 시나리오·제거 시험을 돌리고 SKILL.md를 확정한다. 코덱스(다른 모델 계열)가 네 프로퍼티로 SKILL.md를 검토한 뒤 성진이 전문을 승인한다 → **코덱스 리뷰 ③**(전체 diff + SKILL.md + `--help` + schema, 네 프레임 + **`--help`·schema의 모든 문장이 실제 행동과 맞는지**: 49리프 help의 각 주장에 대응하는 테스트나 실행 근거) → `claude -p "/skill-doctor"`로 이웃 스킬(finviz·sec)과의 경계를 확인한다 | 문서 속 명령 전부 실행 성공 · `claude plugin validate --strict .claude/skills` exit 0 · 시나리오 합격 기준 충족 · 성진 전문 승인(부분 승인·침묵은 승인 아님) · 리뷰 blocking·major 0 · help 주장 중 근거 없는 것 0 · skill-doctor 충돌 보고 0 |
| 10 | PR ②, `gh pr merge --squash`, graphify 리빌드, 이 파일 끝에 `# 구현 기록`을 쓰고 main에 직접 커밋(`docs: yfinance 레이아웃 이행 구현 기록`) | 머지·그래프·기록 |

## 검증

```bash
bash -c 'set -euo pipefail; mkdir -p .tmp; uv export --quiet --script .claude/skills/yfinance/scripts/cli.py --no-hashes -o .tmp/yf-test-req.txt; uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/yf-test-req.txt --with pytest==8.4.2 python -m pytest tests/yfinance tests/test_skill_layout.py -q'
uv run --isolated --no-project --python 3.12 --with-requirements .tmp/yf-test-req.txt --with pytest==8.4.2 python -m pytest tests/yfinance -q   # 선언한 범위의 하한(위 명령은 로컬에서 3.13을 고른다)
uvx ruff check --config pyproject.toml .claude/skills/yfinance/scripts tests/yfinance
python3 -m pytest tests/ --ignore=tests/sec --ignore=tests/finviz --ignore=tests/yfinance -q   # CI offline 잡과 같은 명령(구조 테스트 포함)
uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/yf-test-req.txt --with pytest==8.4.2 python -m pytest tests/yfinance -m live -q
claude plugin validate --strict .claude/skills
```

- **밀도·보존은 픽스처와 골든으로, 유효성은 live로.** live는 데이터가 매일 바뀌므로 status와 이름 집합만 비교한다.
- **이동성**(`test_portability.py` + 수동 1회): 스킬 디렉터리를 레포 밖의 네 종류 경로(공백, 한국어, `$`, 따옴표)에 복사한다. 무관한 cwd에서 `uv run "<사본>/scripts/cli.py"`로 `--help`, `schema prices history`, 픽스처 기반 `prices history AAPL --period 5y --out <f.csv>`를 실행한다. 실행 뒤 사본의 `scripts/`에 `cli.py`·`yfinance_skill`(+`__pycache__`) 말고는 없어야 한다. 수동 1회는 live로 `prices quote AAPL`이다.
- **모델 시나리오(Claude Opus 5.5)**
  - 하네스: 스킬을 새 임시 디렉터리(공백 포함 경로)에 복사하고, 사본 SKILL.md의 `${CLAUDE_SKILL_DIR}`를 사본 절대경로로 치환한다(Claude Code가 로드할 때 하는 일과 같다). 그 SKILL.md 경로를 프롬프트로 주고, `scripts/` 소스 읽기는 금지한다. 런마다 `YF_STORE`를 새 임시 디렉터리로 둔다.
  - 실행: `claude -p --safe-mode --restricted --permission-mode acceptEdits --tools "Bash,Read,Write" --allowedTools "Bash" --model claude-opus-5-5 --output-format stream-json --verbose "<prompt>" < /dev/null`. `--allowedTools Bash` 없이는 Bash가 permission_denials로 막힌다(이전 실측).
  - 집계: stream-json에서 CLI 호출 수, 실패 종료 코드, 하위 명령에 호출 앞부분을 잘못 붙인 실패(결정 9 확인)를 센다.
  - 세트
    - **예산 조건 시나리오.** 프롬프트에 호스트 조건 한 문장을 넣는다: "이 환경의 출력 한도는 작다 — 모든 호출에 `--max-chars 3000`을 붙이고 올리지 않는다." 기본 예산에서는 Opus가 처음부터 `--out`이나 큰 예산을 골라 이 상황이 한 번도 나지 않았다(이전 기록). 전제는 **문단별**로 stream-json에서 확인한다. partial과 too_large는 사다리상 서로 다른 조건이므로(`budget.py`는 거절 전에 축소부터 시도한다) 한쪽으로 다른 쪽을 대신하지 않는다. 전제가 성립하지 않은 런은 판정 불가로 적고, 대상이나 과제를 바꿔 다시 돈다.
      - P1(전제: 데이터 호출 하나가 `partial`): "애플 최근 5년 일간 종가 흐름을 파일 저장 없이 대화 안에서, 기간과 함께".
      - P2(전제: `partial`): "SPY 최근 3년 일간 종가로 가장 크게 떨어진 날 다섯 개".
      - T1(전제: id가 있는 `too_large`): "AAPL·MSFT·GOOGL·AMZN·META 최근 분기 재무상태표 전 항목 비교".
      - T2(전제: id가 있는 `too_large`): "10종목 연간 손익계산서 전 항목 비교".
      - M1(전제: 둘 이상의 대상이 회복을 요구함): T1과 같은 과제를 다른 5종목으로.
    - news-all 1건: "애플 관련 최근 뉴스를 전부 모아 몇 건인지". 기대: 받은 N건이라고 말하고, 피드가 끝났다거나 모든 기사라고 하지 않는다.
    - 회귀 표본 6건: five-year-trend·toyota-pe·spy-pe·blackrock-position·mdd·date-close(`model-scenarios.json`의 `expect` 그대로, 예산 조건 없음).
  - 합격: 각 기대 충족, 스킬 원인 실패 호출 ≤ 1. 새 시나리오는 `model-scenarios.json`에 `expect`·전제와 함께 넣는다.
- **문단 제거 시험**(결정 10)
  - 절차: 먼저 전체본으로 같은 시나리오의 기준 답을 얻는다. 문단 하나를 뺀 사본으로 1차를 돌려 판정이 나빠지면 유지한다. 같으면 삭제 후보로 보고 2차를 돌리고, 둘 다 같을 때만 삭제한다. 그 문단의 전제가 성립하지 않은 런은 판정에 쓰지 않는다.

  | 문단 | 겨냥하는 판단(관찰 가능한 실패) | 1차 / 2차 |
  |---|---|---|
  | partial | 예산이 자른 창을 전 기간으로 서술 | P1 / P2 |
  | too_large | too_large를 빈 결과로 보고하거나, 저장된 id를 두고 새 요청 | T1 / T2 |
  | 회복이 질문을 보존 | 회복하며 대상을 빼거나 범위를 좁히고도 말하지 않음 | T1 / M1 |

  판정 모델·조건·결과는 PR ② 커밋 본문과 `# 구현 기록`에 둔다. 모델이 바뀌면 재검토 대상이다.

## 폐기하지 않는 결정

- 그룹/리프 분류(49리프), 봉투 필드(단 `coverage.exhaustive` 제거·`requested` 추가), 상태와 종료 코드 번호.
- 저장→`read` 회복, recent 방향과 `read`의 전진 창, `shrink` 뒤 continuation 재계산, too_large의 `--max-chars`는 축소 전 크기.
- 화면 표기 규칙(원천 정밀도·날짜만 표기)과 `--out` 계약(PR #21).
- 단위는 schema에만, `--max-chars` 기본 20,000, `references/` 없음, 판정 모델 Claude Opus.
- `# 성진:` 주석은 옮길 때 내용 그대로 따라간다.

## 하지 않는 것

- 가장자리 결함 2건(결정 7): ✓7 `market summary --fields`의 `--out` 의미 변화, ✓10 기본값 적용 뒤 날짜 범위 재검증. `# 구현 기록`의 알려진 한계에 남긴다.
- screen run의 쿼리 필터 조건을 결과로 판정하는 것. 이전 기록(screen-tech)의 알려진 한계이고, `conditions`는 계속 offset·limit·sort만 판정한다. 쿼리 필드(`intradaymarketcap`)와 결과 필드(`marketCap`)의 이름이 달라 대응표가 먼저 필요하다.
- in-process 테스트 seam, 회복 명령의 완전한 호출 형태, 의존성 섀도잉 검사, `pandas/`·`csv/` 시스템 폴더.
- 새 기본값 대조(결정 15), `--sort`·`--field`·산업 키의 choices화(결정 13).
- CI 재활성화, 텍스트 렌더러, 리프 추가·제거, sec·finviz 이행, Codex 호스트 지원.
