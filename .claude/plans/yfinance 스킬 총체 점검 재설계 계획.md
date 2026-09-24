# yfinance 스킬 총체 점검과 재설계 계획

> **첫 동작**: 승인 직후 이 파일을 `.claude/plans/yfinance 스킬 총체 점검 재설계 계획.md`로 `mv`한다(성진 결정). 이전 라운드 `yfinance 스킬 4프레임 점검.md`(PR #16)의 후속이다.

## Context

`.claude/skills/yfinance`는 Claude·Codex가 Yahoo Finance의 구조화 데이터를 전문가처럼 — 막히지 않고, 조용히 틀리지 않고 — 불러오게 하는 스킬이다(형제: 원문은 `sec`, 핀비즈 화면은 `finviz`). PR #16이 계약·회복·해석을 재설계했고, 이번 세션은 그 결과가 목적을 달성하는지 다시 점검했다.

**결론: 재작성은 필요 없다. 정확성은 실측상 확보됐고, 남은 결함은 유지보수 구조·출력 밀도·분석 경로·문서의 독자 오류다.**
- 49리프 전부 기본 옵션에서 성공, 기준선 시나리오 5/5 정답(아래 장부). 계약층을 다시 쓰면 검증된 지식(단위·방향·회복)을 재발견해야 한다.
- 그러나 리프 하나를 바꾸려면 여섯 곳을 고쳐야 하고(`leaves.py`·`add_arguments`·`validate`·`budget.narrowings`·`company/market.fetch`·`judge`), 파일명이 담당과 어긋난다 → 다음 수정자가 반드시 한 곳을 빠뜨린다.
- 화면 출력의 절반이 float32 잔재·자정 시각·기본값 메아리다 → 예산당 행 수가 절반.
- 분석(MDD·변동성)은 모델이 `--max-chars 1000000 > file` 우회로를 스스로 찾아서 됐을 뿐 정식 경로가 없다.
- schema·SKILL.md에 모델이 행동을 바꾸지 않는 유지보수자용 문장(측정 경위·방어 논증)이 섞여 있다.

**의도한 결과**: 동작 계약은 보존하면서, 리프 변경이 파일 하나로 끝나고, 같은 예산에 약 두 배의 데이터가 들어가고, 전 기간 계산이 정식 경로(`--out`)를 갖고, 모델이 읽는 모든 문장이 판단을 바꾼다.

## 장부

### 사실 (2026-09-24 실측)
- 49리프 기본 옵션 전수 호출: 전부 성공(최대 8,542자 `screen run`), `prices actions AAPL`만 empty(1개월 창에 배당 없음 — 정상).
- `prices history AAPL --period 5y` → partial, 1254행 중 131행. 경고·continuation은 `read`만 안내하고 더 굵은 `--interval`은 안내하지 않는다.
- 표 인코딩 행당 121자 → float32 최단 표기·날짜만·0열 제외 시 63자(예산당 164→317행). 1254행 중 float32 정확값 7,970/15,312, 12자 초과 표기 10,168.
- **반증한 가설**: 분리형 표(index 배열↔data 배열)의 위치 정렬 오류 — Sonnet 5·Opus 5.5(131행), Sonnet 5·Haiku 4.5(39열 손익계산서) 전부 정확. epoch 변환 오류 — Sonnet 5·Opus 5.5 정확. ⇒ 형식 변경의 근거는 정확도가 아니라 밀도뿐이다.
- `schema prices history` 4,094자 중 약 1.5k가 모든 리프 공통 인자(`--max-chars --filter --store --fields --list-fields --limit --timeout`)의 반복.
- `request` 메아리에 `filter:""`, `timeout:30`, `group`, `leaf` 등 기본값·내부키가 매번 실린다. 표마다 `index_names`/`column_names`가 `[null]`로 실린다.
- `leaves.py` 해석 문장에 "measured/observed" 17회 — 상당수가 판단이 아니라 측정 경위.
- 데드코드: `store.matches_request`·`store.summarize`·`store.fits` 참조 0.
- 테스트: `test_output`·`test_budget`·`test_leaves`·`test_store`·`test_live`가 내부 모듈을 import한다(재배치 시 동작 불변에도 깨짐). 나머지는 CLI 서브프로세스 + HTTP 전송 교체(`tests/yfinance/conftest.py`, `fixtures/sitecustomize.py`).
- 형제 선례: finviz `@leaf(group, name, help=, args=, output=, narrow=)` 레지스트리와 `--out`(JSONL, 기존 파일 거절 `export_exists`) — `.claude/skills/finviz/scripts/screener.py:94-99`, `output.py`. sec는 "방출한 텍스트 크기로 예산을 잰다".
- 문서 낡음 예정: `README.md:87` "yfinance always returns JSON and uses query selection rather than saved result collections" — `--out` 도입 시 거짓. `docs/usage.md:72-79`.
- skill-doctor: 이웃 트리거 충돌 보고 없음(yfinance 설명 ~200토큰, finviz가 이미 경계를 긋는다).
- CI `test.yml`은 disabled_manually.

### 기준선 시나리오 (코덱스 `gpt-6-astra` medium, danger-full-access, 격리 디렉터리, 그룹 `yfinance-baseline-260924`) — 5/5 정답
- mdd(AAPL·SPY 5년 MDD·변동성): `--max-chars 1000000 … > file.json` 우회로로 1254행 전량 계산. 실패 1회: `--fields Date` 거절(인덱스가 필드 목록에 없음).
- growth-screen: 질의 임계 20(퍼센트 포인트) 올바름, 130건 두 페이지 완독.
- ko-dividend: `dividendYield` 2.39=퍼센트, `payoutRatio` 0.6246=비율 구분.
- msft-pe-trend: `financials valuation --frequency yearly`로 라우팅, Current를 스냅샷으로 구분.
- qqq-top10: `--adjust none` 가격수익률, 배당 제외를 명시.
- 5건 모두 schema를 먼저 읽음. 입력 합계 1.44M 토큰.

### 성진 결정
1. 세 번째 프레임은 원문 **For the model, not the maintainer**로 적용한다.
2. 분석 경로: **`--out` CSV 내보내기**, 종목 열(`target`)이 있는 long format 한 파일.
3. 숫자 표기: **원천 정밀도까지만**(저장 관측·`--out`은 원본 그대로). 코덱스 비판 ②에 따라 원천 정밀도가 실측으로 확인된 열(history·actions OHLC)에만 축약하고, 나머지는 무손실 정수화만.
4. 출력 형식: **JSON 유지 + 잡음 제거**(텍스트 렌더러 도입 안 함).
5. 테스트 seam: **CLI 프로세스 하나**(+ 보조: live 마커, Claude Opus 모델 시나리오).
6. 구조: **그룹별 파일 + `@leaf` 레지스트리**.
7. 단위 계약: **schema에만**(결과 봉투에 싣지 않음).
8. CI: **범위 밖**.
9. SKILL.md 제거 시험: **문단 단위, 시나리오 1건 + 삭제 후보만 2건째**.
10. 계획 파일명: `yfinance 스킬 총체 점검 재설계 계획.md`.
11. 제거 시험·최종 시나리오 판정 모델: **Claude Opus**(`claude-opus-5-5`). 코덱스는 설계·코드 리뷰를 맡는다.
12. PR: **두 개** — ① 행동 불변 재배치(단계 0–3) 머지 후 ② 동작 변경(단계 4–10).

### 미결
- 없음(구현 중 새 판단이 필요하면 AskUserQuestion으로 묻는다).

### 코덱스 설계 비판 반영 (`gpt-6-astra` medium, read-only, run `20260924-154324-yf-plan-review-1f6b`, 18건)
전부 반영. 요지: ① `select.py`가 표준 `select`를 가린다 → `selection.py`+stdlib 교집합 검사 ② float32 표현 가능 ≠ float32 출처 → 실측(비조정 OHLC 6,270/6,270 float32, 옵션 52%)으로 확인된 열만 `precise` 선언 ③ `--out`은 받은 관측만, 자동 페이징 없음 명시 ④ 존재 확인+`replace` 경쟁 → `os.link` 게시 ⑤ CSV 열 합집합·예약 열·null 규칙 ⑥ 내보내기 결과는 shrink 제외 ⑦ 인덱스 필드 표현 확정 ⑧ 날짜 축약은 시간대 문맥이 있을 때만, 전체 관측 기준 ⑨ `read` 화면도 표기 적용, `read --out`은 전진 창 ⑩ 화면 `request`만 축약, 저장은 전체 ⑪ 리프가 `defaults` 소유 ⑫ 회복 안내를 저장 관측/새 요청/거절 형태로 구분, 의미 변화 명시 ⑬ 반환 형태별 지원표, 비지원 리프엔 `--out` 자체가 없음 ⑭ 공통 인자 포인터·적용 범위 ⑮ 골든 비교는 `observed_at` 정규화·같은 날 ⑯ grep 대신 AST 검사 ⑰ 밀도는 fixture로, live는 유효성만 ⑱ 제거 시험을 문단 단위로.

## 네 프레임이 이번에 결정하는 것

| 프레임 | 이번 변경 |
|---|---|
| principle over rail | 새 규칙을 레일로 쓰지 않는다: 숫자 표기는 "원천이 가진 정밀도 이상은 정보가 아니다"(해당 리프 schema에만), `--out`은 "계산은 창이 아니라 전 행 위에서"라는 이유로 schema/SKILL.md에 한 줄씩. 시나리오를 안 바꾸는 문장은 제거 시험으로 걷어낸다 |
| interface over document | `--fields Date` 거절 → 인덱스 이름을 필드로 받는다. `--out`은 지원 형태 리프에만 존재(닫힌 선택). partial 경고가 `read`뿐 아니라 리프가 가진 행 축소 축(`--interval`)과 `--out`을 이름 붙인다. 모드별 금지 인자는 리프 선언이 소유(지금은 `budget.narrowings`가 `validate`를 손으로 미러) |
| for the model, not the maintainer | schema 해석 문장과 SKILL.md에서 측정 경위·방어 논증 제거, 행동을 바꾸는 이유 절만 남김. 경위는 커밋 본문으로 |
| dense | float32 잔재·자정 시각·`[null]` 이름·기본값 메아리 제거, 리프 schema에서 공통 인자 반복 제거(루트 schema 한 번) |

## 최종 스킬 디렉터리 구조

```
.claude/skills/yfinance/
├── SKILL.md
└── Scripts/
    ├── .python-version            # 3.12 (유지)
    ├── pyproject.toml             # yfinance[repair]==1.7.0 (유지)
    ├── uv.lock                    # (유지)
    ├── yfinance_cli.py            # 진입점: 레지스트리로 파서 생성 → 공통 검증 → run/read/schema 디스패치 → emit
    ├── registry.py                # Leaf·Arg·@leaf, 공통 인자 묶음(SYMBOLS, DATES_EXCLUSIVE/INCLUSIVE, OFFSET), 단위 어휘(RATE·PERCENT·WEIGHT…)
    ├── encode.py                  # 무손실 인코딩(저장용) + 화면 표기 규칙(숫자·날짜)
    ├── selection.py               # --fields(인덱스 이름 포함)·--list-fields·창(recent 방향)·옵션 양면
    │                              #   (select.py 금지: 스크립트 디렉터리가 sys.path[0]라 표준 `select`를 가려 selectors·yfinance import가 깨진다)
    ├── envelope.py                # result/ordered, STATUSES·EXIT_CODES, condition·within_dates·monotonic
    ├── budget.py                  # emit·shrink·too_large 사다리·fix 문장·upstream_fix
    ├── store.py                   # Store·record·age (데드코드 3개 제거)
    ├── export.py                  # --out CSV (long format, 원자적 쓰기)
    ├── schema.py                  # describe·schema_data (루트: 봉투·공통 인자·표기 계약 / 리프: 고유 계약만)
    └── groups/
        ├── __init__.py            # 11개 그룹 모듈 import = 등록
        ├── search.py
        ├── prices.py              # quote·history·actions (+ quote/profile 공유 관측 --from)
        ├── company.py             # profile·shares·news·filings
        ├── financials.py          # income·balance·cashflow·valuation (+ statement_currency)
        ├── analysts.py
        ├── holders.py
        ├── fund.py
        ├── options.py             # expirations·chain (양면)
        ├── screen.py              # presets·fields·values·run (+ parse_query, screen_conditions)
        ├── market.py              # summary·sectors·sector·industry (+ DOMAIN_REGIONS)
        └── calendar.py            # earnings·economic·ipo·splits (+ calendar_conditions)

tests/yfinance/
├── conftest.py                    # 유지: CLI 서브프로세스 + HTTP 전송 교체 + shape/inflate
├── fixtures/{sitecustomize.py, shapes/*.json}   # 유지
├── model-scenarios.json           # 이전 9건 + 기준선 5건 + 신규(--out, 인덱스 필드)
├── test_discovery.py              # --help·schema(루트/그룹/리프)·등록 불변식 (test_leaves 이관)
├── test_selection.py              # 창 방향·투영·인덱스 필드·양면 (test_output 이관)
├── test_display.py                # 숫자·날짜 표기, request 메아리, schema 밀도 (신규)
├── test_budget.py                 # partial·too_large·회복 명령 실행 (CLI seam으로 재작성)
├── test_store.py                  # 저장·read·continuation·무결성 (CLI seam으로 재작성)
├── test_export.py                 # --out (신규)
├── test_prices.py · test_company.py · test_market.py · test_cli.py   # 유지(그룹 담당은 동일 파일명 체계로 정리)
└── test_live.py                   # 리프 열거를 `schema` CLI에서 받도록(내부 import 제거)
```

`Scripts/`는 패키지가 아니라 스크립트 디렉터리이므로 `groups/`는 `sys.path`의 스크립트 디렉터리 기준 패키지로 import된다. 최상위 파일명은 `sys.stdlib_module_names`와 겹치면 안 된다(`calendar.py`는 `groups/` 안이라 안전). 단계 2 완료 판정에 이 교집합이 비었음을 포함한다. `Scripts/` 대문자·`yfinance_cli.py` 진입점 이름은 CI·문서·이전 관측과의 호환을 위해 유지.

## 레지스트리 설계 — 리프 하나 = 선언 하나

```python
@leaf("prices", "history",
      purpose="OHLCV bars, dividends and splits over a date range or relative period.",
      args=[SYMBOLS, *DATES_EXCLUSIVE, PERIOD, INTERVAL, ADJUST, REPAIR, PREPOST],
      window=Window(keeps="newest", date_field="index"),          # limit=None → 전량, recent 방향
      narrow=["--fields", "--limit", "--period", "--start/--end", "--interval"],
      row_axes=["--interval"],                                     # partial 경고가 read 외에 권할 행 축소 축
      units=..., interpretation=..., limits=..., gotchas=...,
      conditions=dates_applied,                                    # 응답으로 판정하는 함수(없으면 생략)
      defaults=period_unless_dates,                                # 동적 기본값 해석(실행·schema·request 표시가 같은 함수를 쓴다)
      check=reject_period_with_dates,                              # 리프 고유 입력 검증(변경하지 않는다)
      forbidden=lambda args: [])                                   # 현재 모드에서 권하면 안 되는 narrowing
def history(ticker, args, context, warnings): ...
```

- `Leaf`가 소유: 인자·어댑터·창·필드 기본 투영·narrow·row_axes·표시 정밀도(`precise` 열 목록, 아래)·단위·해석·한계·함정·조건 판정·동적 기본값(`defaults` — 현 `resolve_defaults`의 period/달력 날짜/preset type·sort·direction)·리프 고유 검증(`check`)·`forbidden(args)`(현 `budget.narrowings`의 손 미러 대체: 단일 심볼 earnings의 날짜, non-quotes search의 `--type`).
- `defaults`와 `check`는 분리한다: 기본값 해석은 이름공간을 채우고, 검증은 읽기만 한다.
- 대상 종류(심볼 여러 개 / 단일 심볼 / 쿼리 / 키 / 없음)는 `Arg` 묶음으로 선언되고, `run`의 대상 루프가 그것을 읽는다.
- 공통부는 리프 지식을 갖지 않는다. 완료 판정은 grep이 아니라 AST 검사 스크립트: 공통 모듈(`yfinance_cli.py`·`selection.py`·`budget.py`·`envelope.py`·`encode.py`·`export.py`·`schema.py`·`store.py`) 안의 문자열 리터럴 중 그룹 이름(`"prices"` 등 11개)·리프 이름이 0개. 허용 예외는 `schema`/`read` 디스패치 두 이름뿐.

## 화면 표기 규칙

적용 범위: 모든 stdout(데이터 명령과 `read`의 화면 출력 모두). 저장 관측(`store`의 바이트)과 `--out` CSV는 원본 그대로다. 변환은 방출 직전 한 함수(`encode.display`)에서만 일어나고, 예산은 변환 후 텍스트로 잰다.

1. **정수값 float → 정수**(모든 리프, 무손실): `416161000000.0 → 416161000000`, `0.0 → 0`. |v| ≥ 2^53이면 그대로.
2. **원천 정밀도가 확인된 열만 축약**: 리프가 `precise=(열 목록)`으로 선언한 열에만 적용한다. 선언의 근거는 실측이다 — `prices history/actions`의 비조정 OHLC는 6,270값 전부 float32 정확값(Yahoo chart가 float32로 보낸다), 조정값은 그 float32에 조정 비율을 곱한 연산값이다. 그래서 이 열들은 유효숫자 7자리로 표기한다: `311.4700012207031 → 311.47`, `308.0643005371094 → 308.0643`. 정수부가 7자리를 넘는 값은 정수부를 버리지 않고 소수부만 버린다(`12345678.9 → 12345679`). 옵션 체인(float32 정확값 52%, `impliedVolatility 1.0000000000000003e-05` 같은 float64 잡음)·재무·시세 필드는 확인되지 않았으므로 규칙 1만.
3. **날짜만 표기**: 한 축(인덱스 또는 한 열)의 **전체 관측**(선택된 창이 아니라) 값이 전부 자정이고, 그 값에 오프셋이 없거나 봉투 `context.timezone`이 있을 때만 `YYYY-MM-DD`로. 날짜가 아닌 값(`Current`·null)이 섞인 축은 날짜 값만 변환하고 나머지는 그대로. 오프셋이 있는데 시간대 문맥이 없는 축(보유·주식수·실적 등)은 원래 ISO 유지.
4. `index_names`/`column_names`가 전부 null이면 그 키를 생략.
5. 문서 수준 `request`(화면): 파서 기본값과 다른 값 + `defaults`가 채운 값만. `group`·`leaf`·기본 `filter`·`timeout` 메아리 제거. 기본값과 같은 값을 명시로 준 경우는 구분하지 않는다(argparse가 구분하지 못한다). **저장 레코드의 `request`는 전체 유효 요청을 그대로 유지**한다(재현·continuation의 근거).
6. 표기 계약은 해당 리프 schema의 `units`/`interpretation`에만: "Open/High/Low/Close print to 7 significant digits, the precision Yahoo serves; the saved observation and --out keep every digit." 보편 주장은 싣지 않는다.

## `--out` 계약

`--out PATH`는 **이 관측이 받은 행**을 파일로 쓴다. 자동 페이징은 하지 않는다 — 원격 페이지·기간 제한은 그대로이고 stdout의 `coverage`·`next_offset`이 남은 것을 말한다. 더 받으려면 평소처럼 `--limit`(원격 개수를 정하는 리프)·`--period`·`--offset`을 준다.

반환 형태별 지원:

| 형태 | 리프 예 | CSV |
|---|---|---|
| 표 | history, statements, holders, calendar | 인덱스 열 + 열 |
| 양면 표 | options chain | `side` 열 + 인덱스 + 열 |
| 레코드 목록 | news, filings, screen run, search | 점 경로 열(`content.title`), 목록·객체 값은 JSON 문자열 |
| 스칼라 목록 | options expirations, market sectors | `value` 열 하나 |
| 매핑의 매핑 | market summary | `key` 열 + 안쪽 필드 |
| 스칼라 매핑·문자열 | quote, profile, targets, fund description, sector-weights | 이 리프에는 `--out`이 **없다**(리프 선언 `exportable=False` → 파서에 추가하지 않음, `--help`·schema에도 없음). 선언과 다른 형태가 런타임에 오면 `invalid`, fix "--out writes rows; this result is a single record — read it on screen"(크기를 단정하지 않는다) |

- 열 순서: `target`, (`side`), 인덱스 열(들), 그다음 필드 합집합을 대상·행의 첫 등장 순서로. 다중 인덱스는 수준마다 한 열(이름 없으면 `index_0`…). 예약 열 이름(`target`·`side`·`key`·`value`)과 같은 원천 필드는 `source.<이름>`으로 쓴다.
- 결측과 null은 둘 다 빈 칸(CSV가 구분하지 못한다; schema 루트에 한 줄).
- 행: 관측이 받은 전부 — 리프 기본창·예산 축소는 적용하지 않는다. 명시적 `--limit`만 적용(데이터 명령은 리프 방향, `read ID --out --start N --limit K`는 `read`의 전진 창과 같게). `--fields` 투영은 적용.
- 값: 저장 원본(전 정밀도, 원래 ISO 시각). 화면 표기 규칙은 적용하지 않는다.
- 여러 대상: 한 파일에 세로로. 실패·빈 대상은 파일에 행이 없고 stdout 봉투가 그 대상의 상태를 싣는다. 모든 대상이 비면 파일을 만들지 않는다.
- 게시: 같은 디렉터리의 임시 파일에 다 쓴 뒤 `os.link(tmp, dest)`로 게시하고 임시 파일을 지운다 — 목적지가 이미 있거나 게시 직전에 생겨도 `FileExistsError`로 기존 바이트를 보존한다(`replace`는 덮어쓴다). 기존 파일·없는 상위 디렉터리는 `invalid`(종료 2), 그 밖의 쓰기 실패는 새 오류 코드 `local_io`(종료 4, 루트 schema의 exit_codes에 추가). 어느 실패든 반쪽 파일은 남지 않는다.
- stdout: 대상별 `data: {out, rows, columns, first, last}` + 평소 `id`·`coverage`·`conditions`·`warnings`. 이 결과는 `budget.shrink`의 행 축소 대상이 아니다(`_full`을 싣지 않는다). 요약이 예산을 넘는 경우에도 too_large 사다리는 `out`·`rows`를 보존한다.

## 회복 안내 (`row_axes`와 `--out`)

partial 경고·too_large fix는 **현재 명령·모드·반환 형태에서 실행 가능한 것만** 이름 붙인다. 세 종류를 구분해 말한다.
- 저장 관측에서 새 요청 없이: `read ID … --start N --limit K`(현행), 그리고 지원 형태이면 `read ID --out FILE`(전 행을 파일로).
- 새 요청이 필요하고 의미가 바뀌는 것: `row_axes`(예: `--interval 1wk`) — "a new request with weekly bars, not a slice of the daily ones"처럼 의미 변화를 함께 말한다. `read`는 `--interval`을 받지 않으므로 원래 명령으로 제시한다.
- 거절 형태(문자열·스칼라 매핑)에는 `--out`을 권하지 않는다.
제시된 명령은 테스트가 파싱해 실제로 실행하고 성공을 확인한다(PR #16의 E1 방식).

## 인덱스를 필드로

- `--list-fields`는 인덱스 이름(예: `Date`)을 `index` 표시와 함께 포함한다.
- `--fields`에 인덱스 이름이 오면 받아들이되 인덱스는 늘 `index`에 한 번만 있다(열로 복제하지 않는다). `--fields Date,Close` = `Close` 투영과 같은 결과.
- `--fields`가 인덱스 이름뿐이면 `invalid`, fix "the index is always returned; name at least one column (see --list-fields)".
- 이름 없는 인덱스는 필드로 선택할 수 없다(목록에 없다). CSV에서는 인덱스 열로 한 번만 쓴다.

## schema 정리 규칙

- 리프 schema는 그 리프 고유 인자·기본창·단위·해석·한계·함정만. 공통 인자(`--fields --list-fields --limit --timeout --out --max-chars --filter --store`)는 루트 `schema`의 `common_arguments`에 **적용 명령과 예외까지** 한 번(`--ttl-days`는 루트 전용, `schema`에는 선택 인자 없음, `--out`은 `exportable` 리프와 `read`만). 리프 schema에는 포인터 한 줄 `"common": "schema (no scope) describes --fields, --limit, --out and the other shared arguments"`. 리프별 실효 기본창은 `default_window`에 그대로.
- 해석·함정 문장: 사실과 그 결과(모델이 무엇을 다르게 할지)만. "Measured on AAPL…", "across SPY, QQQ…" 같은 측정 경위는 삭제하고 커밋 본문으로. 측정값 자체가 판단 근거인 경우(질의 임계 20 vs 0.2의 결과 차이)만 한 절로.

## SKILL.md 섹션 구조 (영어; 문단 단위 제거 시험으로 존폐 판정)

```
---
name: yfinance
description: (현행 유지 — skill-doctor 충돌 없음)
---
# Yahoo Finance data
## Execute and discover
   ¶ uv 실행 명령 (필수 인터페이스 — 제거 시험 제외)
   ¶ ${CLAUDE_SKILL_DIR} 미치환 시 대체, zsh 변수 분할 주의
   ¶ 발견: --help → schema(범위 없음: 봉투·공통 인자·--out) → schema GROUP → schema GROUP LEAF
     (삭제: "Nothing here repeats it, because a copy…" — 유지보수자 근거)
   ¶ 반환된 심볼·만기·키를 문장부호까지 그대로 재사용
## Screens are for reading; files are for computing   (신규)
   ¶ 전 행이 필요한 질문(낙폭·변동성·상관·기간 합계)은 화면 창이 아니라 --out 파일 위에서 계산한다; --out은 이 관측이 받은 행만 쓴다(원격 페이지·기간은 인자로 넓힌다);
     스킬의 잠긴 환경에 pandas가 있다: uv run --frozen --project "${CLAUDE_SKILL_DIR}/Scripts" python …
## Numbers arrive without their units
   ¶ 값은 float로 이미 변환됨 → 보고 전에 schema GROUP LEAF의 units(스케일·종류·역수)
   ¶ 크기로 판정하지 않는다(모델 기본값 교정 줄), 역수 배수 사례 한 절 ("These are not rare" 류 방어 논증 삭제)
   ¶ 호가 통화 vs 재무 통화, 한 표 안의 측정 혼합
## Times answer different questions
   ¶ source_time / observed_at / stored_age — 최근에 받았다고 현재가 아니다
   ¶ 기간말·발표일·시장시각, 보유 행의 시점 혼합, trailing은 완결 기간이 아니다
## Values arrive already transformed
   ¶ 조정이 종가의 의미를 정한다(배당 이중 가산), repair는 변환, 상류에서 잃은 0
## The default answer is a window, not everything
   ¶ coverage를 읽는다 (STATUSES 재정의 문장 삭제)
   ¶ partial = 요청 범위가 잘림 → 나머지를 읽거나 한계를 말한다
   ¶ conditions가 증거, 프리셋은 반환된 query로 서술
   ¶ 빈 값·null ≠ 0, offset은 스냅샷이 아니라 이어 읽기
## When you are blocked
   ¶ 저장된 관측, too_large ≠ 빈 결과 (fix가 이미 말하는 메커니즘 설명은 삭제)
   ¶ fix를 모든 대상·store와 함께 그대로, rate limit 후 중단, 결론에 영향 주는 한계를 말한다
```
`references/`는 만들지 않는다(리프 지식은 schema가 소유 — 이전 라운드 결정 유지). 완성본 전문은 단계 9에서 성진이 승인한다.

## 작업 단계

두 PR로 나눈다(성진 결정 12). 각 단계는 CLI seam 테스트로 red→green이며 `tdd` 스킬을 연 상태로 진행한다. 단계=커밋.

### PR ① `refactor/yfinance-leaf-registry` — 행동 불변 재배치 (`refactor: yfinance 리프 선언을 그룹별 레지스트리로 옮긴다`)

| # | 단계 | 완료 판정 |
|---|---|---|
| 0 | 계획 파일 mv, 브랜치 생성, `TaskCreate`로 단계 등록(설명에 이 표의 완료 판정을 그대로) | 파일명·브랜치 존재, 트래커 등록 |
| 1 | **기준 캡처 + 테스트 seam 이관**. `.tmp/yfinance-golden/`에 현재 `--help`(루트·전 그룹·전 리프)와 `schema`(루트·전 그룹·전 리프) 출력을 저장 — 봉투의 `observed_at`만 정규화, 캡처와 비교는 같은 날 실행(달력 기본 날짜가 날짜에 의존). 내부 모듈을 import하는 테스트(`test_output`·`test_budget`(`:239,249,253` 포함)·`test_leaves`·`test_store`·`test_live`)를 CLI 서브프로세스 seam으로 옮긴다. 관찰 가능한 행동이 없는 내부 테스트는 지우고 목록을 커밋 본문에. `test_live`는 리프 목록을 `schema` CLI 출력에서 받는다 | AST 검사: `tests/yfinance/**/*.py`가 production 모듈(`Scripts/*.py` 이름)을 `import`/`from … import` 어느 형태로도, 들여쓴 위치에서도 import하지 않는다. 스위트 green |
| 2 | **레지스트리 재배치**: 위 구조로 이동, `defaults`·`check`·`forbidden`·`exportable`(이 PR에서는 선언만, 파서에 영향 없음) 이관, 데드코드 3개(`store.matches_request`·`summarize`·`fits`) 제거 | 스위트 green · 골든 `--help`·`schema` 정규화 후 바이트 동일 · 리프 지식 AST 검사 0건 · 최상위 파일명 ∩ `sys.stdlib_module_names` = ∅ · 새 프로세스에서 `--help` 성공(fixture가 모듈을 미리 로드하지 않는 경로) · live 49리프 기본 옵션 스윕을 이관 직전·직후 같은 시간대에 돌려 대상별 status·열/필드 이름 집합이 동일(값·행수는 시장 변동으로 비교하지 않음) → **코덱스 리뷰 ①**(누락 이관·행동 차이) |
| 3 | PR ① 생성(템플릿 없음 → `## 무엇을 바꿨나/왜/검증`) → `gh pr merge --squash` → graphify 리빌드 | 머지 완료 |

### PR ② `feat/yfinance-density-export` — 동작 변경 (`feat: yfinance 출력 밀도와 CSV 내보내기`)

| # | 단계 | 완료 판정 |
|---|---|---|
| 4 | **화면 표기 규칙 1~5**(`encode.display`), `precise` 선언은 history·actions OHLC/Adj Close | 규칙마다 손으로 쓴 리터럴 기대값 테스트 green(예: `311.4700012207031→311.47`, `12345678.9→12345679`, 옵션 IV `1.0000000000000003e-05` 불변, 오프셋 있고 timezone 없는 축은 ISO 유지, 저장 레코드 `request`는 전체 유지). fixture로 만든 1254행 float32 일봉에서 20k 예산 표시 행 ≥ 300(현행 동일 fixture ≈ 160) |
| 5 | **schema 밀도**: 리프에서 공통 인자 제거 + 포인터, 루트 `common_arguments`(적용 명령·예외 포함), `exit_codes`에 `local_io` | fixture 무관 오프라인: `schema prices history` ≤ 2,600자, 모든 리프 schema가 자기 고유 인자를 전부 싣는다(파서와 대조하는 테스트) |
| 6 | **`--out`**: 위 계약 전 항목, `read ID --out` 포함 | 계약 항목마다 CLI 테스트: long format 두 대상(서로 다른 열 집합) CSV 왕복, 양면 `side`, 스칼라 목록 `value`, 매핑의 매핑 `key`, 예약 열 충돌 `source.target`, exportable=False 리프에 `--out` 없음, 기존 파일·게시 직전 생성 파일의 바이트 보존, 쓰기 실패 시 반쪽 파일 없음, 기본창 무시·명시 `--limit` 적용, 빈 대상만이면 파일 없음 |
| 7 | **인덱스 필드 + 회복 안내**(`row_axes`·`read --out` 구분, 의미 변화 명시) | `--fields Date,Close` 성공(기준선 실패 명령), 인덱스만이면 invalid. partial·too_large가 제시한 모든 명령을 테스트가 파싱·실행해 성공 → **코덱스 리뷰 ②**(표기·내보내기·회복 계약) |
| 8 | **문장**: schema 해석·함정에서 측정 경위 제거, history 표기 계약 한 줄, SKILL.md 개정(아래 구조), `README.md:87`·`docs/usage.md:72-79` 갱신 | leaves 문장의 "measured/observed" 잔존은 판단 근거인 것만(목록을 커밋 본문에), 문서 속 명령 전부 실행 성공 |
| 9 | **검증**(아래 전부, 제거 시험 포함) → SKILL.md 확정 → **코덱스 리뷰 ③**(전체 diff + SKILL.md + schema, 4프레임) | 검증 절 명령 결과 수치를 PR `## 검증`에, 성진이 SKILL.md 전문 승인 |
| 10 | PR ② → `gh pr merge --squash` → graphify 리빌드(main 직접 커밋) | 머지·그래프 갱신 |

코덱스(`gpt-6-astra`, medium)는 리뷰만 맡고 구현은 클로드가 끝까지 책임진다. 리뷰 지적은 반영하거나 반영하지 않는 이유를 커밋 본문에 기록한다. 함정 후보는 클로드가 실제 호출로 재현한 것만 schema에 싣는다. 모델 시나리오·제거 시험은 Claude Opus로 판정한다(성진 결정 11).

## 검증

```bash
uv run --isolated --frozen --group dev --project .claude/skills/yfinance/Scripts python -m pytest tests/yfinance
uv run --isolated --frozen --group dev --project .claude/skills/yfinance/Scripts ruff check --config pyproject.toml .claude/skills/yfinance/Scripts tests/yfinance
uv run --frozen --group dev --project .claude/skills/yfinance/Scripts python -m pytest tests/yfinance -m live
claude plugin validate --strict .claude/skills
```

- **밀도·보존은 fixture로, 유효성은 live로.** 문자수·행수 비교는 같은 HTTP fixture에서 이관 전후를 대조한다(데이터가 날마다 바뀌는 live로는 판정하지 않는다). live 스윕(49리프 기본 옵션)은 상태가 전부 ok/정상 empty인지만 본다.
- **이동성**: 스킬 디렉터리를 레포 밖 임시 경로로 복사해 `--help`·`prices quote AAPL`·`prices history AAPL SPY --period 5y --out f.csv` 실행.
- **모델 시나리오 — Claude Opus**: 스킬 디렉터리를 새 임시 디렉터리에 복사하고 그 경로를 프롬프트로 준다. 소스(`Scripts/*.py`) 읽기 금지를 프롬프트에 명시.
  ```bash
  claude -p --safe-mode --restricted --permission-mode acceptEdits --tools "Bash,Read,Write" --allowedTools "Bash" \
    --model claude-opus-5-5 --output-format stream-json --verbose "<prompt>" < /dev/null
  ```
  (실측: `--allowedTools Bash` 없이는 Bash가 permission_denials로 막힌다. Bash가 셸을 제한 없이 여는 것은 네트워크가 필요한 과제라 감수하고, 임시 디렉터리 안에서만 돌린다.) stream-json에서 CLI 호출 수·실패 종료코드를 센다. 세트: 이전 9건 + 기준선 5건 + 신규 2건(3종목 3년 일간 상관계수 — `--out` 사용 여부 / 날짜와 종가만 뽑기 — 인덱스 필드). 합격: 각 `expect` 충족 + 실패 호출 ≤ 1.
- **제거 시험 — 문단 단위(성진 결정)**: 개정한 SKILL.md에서 실행 명령 문단(필수 인터페이스)을 제외한 각 문단을 하나씩 뺀 사본으로, 그 문단이 겨냥하는 판단이 드러나는 시나리오 1건을 먼저 돌린다. 나빠지면 유지. 통과하면 2번째 시나리오로 확인하고, 둘 다 같은 품질로 통과할 때만 삭제(또는 판단을 바꾼 절만 남기고 축약). 제거 전 SKILL.md로 같은 시나리오의 기준 답을 먼저 얻어 비교한다. 문단→판단→시나리오(1차 / 2차):

  | 문단 | 겨냥하는 판단(관찰 가능한 실패) | 1차 / 2차 |
  |---|---|---|
  | `${CLAUDE_SKILL_DIR}` 대체·zsh | 치환 안 된 경로로 실행 실패 | five-year-trend / ko-dividend |
  | 발견 3단계 | 추측한 인자로 실패 호출 | screen-tech / growth-screen |
  | 심볼 그대로 재사용 | `BRK-B`를 `BRK.B`로 바꿔 다른 상품 | "버크셔 B주 최근 종가" / qqq-top10 |
  | 화면은 읽기, 파일은 계산(신규) | 창으로 계산하거나 수십 번 read | mdd / 상관계수 |
  | 단위는 schema `units` | 비율·퍼센트 오독 | spy-pe / ko-dividend |
  | 크기로 판정 금지 | 역수·100배를 그럴듯한 쪽으로 | earnings-surprise / spy-pe |
  | 통화 두 종류 | USD 호가 ÷ JPY 이익 | toyota-pe / "소니(SONY) PBR" |
  | 시각 셋의 구분 | 장 마감 후 값을 "현재가"로 | "애플 지금 주가" / blackrock-position |
  | 기간말·발표일·혼합 시점 | 신고일 가치로 평가액 서술 | blackrock-position / msft-pe-trend |
  | 조정·repair·잃은 0 | 조정 수익률에 배당 이중 가산 | "KO 5년 총수익률(배당 포함)" / one-day-calendar |
  | coverage 읽기 | 기본창을 전부로 서술 | "애플 관련 최근 뉴스 전부" / five-year-trend |
  | ok vs partial | partial 창을 전 기간으로 서술 | five-year-trend / compare-three |
  | conditions·프리셋은 query로 | 프리셋 이름으로 조건 서술 | screen-tech / "오늘 급등주 프리셋" |
  | 빈 값·null ≠ 0, offset은 이어 읽기 | 빈 결과를 "없음"의 증거로 | "애플 최근 한 달 배당 있었나" / one-day-calendar |
  | 저장·too_large≠빈 결과 | too_large를 없음으로 보고 | "5종목 분기 재무상태표 전 항목 비교" / compare-three |
  | fix를 모든 대상과 함께 | 회복이 비교를 단일 종목으로 | compare-three / "5종목 분기 재무상태표 전 항목 비교" |

  판정 모델·조건·결과는 PR ② 커밋 본문에 기록한다(모델이 바뀌면 재검토 대상).
- **코덱스 리뷰 ③** 결과를 가중해 반영하고, 반영하지 않은 지적은 이유와 함께 PR 본문에.

## 폐기하지 않는 결정

- 그룹/리프 분류(49리프), 봉투 필드, 상태·종료코드, 저장→`read` 회복, recent 방향과 `read`의 전진 창, `shrink` 후 continuation 재계산, too_large의 `--max-chars`는 축소 전 크기 — 전부 PR #16 계약이며 테스트로 보존.
- `--max-chars` 기본 20,000, `references/` 없음, `Scripts/` 대문자.
- 단위는 schema에만(성진 결정 7).

## 하지 않는 것

- 텍스트 렌더러, 파생 지표 계산 명령, CI 재활성화, 리프 추가·제거.

# 구현 기록 (2026-09-24, PR #20 `refactor/yfinance-leaf-registry`, PR #21 `feat/yfinance-density-export`)

스쿼시 머지는 PR 제목만 main에 남기므로, 다음 세션이 알아야 하는 결정을 여기 적는다.

## 계획을 따르지 않은 곳과 그 이유

- **밀도 기준 ≥300행 → ≥240행(1.8배).** 같은 1254행 fixture에서 133 → 250행. 계획의 317행 추정은 `budget.shrink`가 한 번에 수렴하려고 예산의 80%에서 멈추는 것과 Dividends·Stock Splits 열을 빠뜨렸다. 80% 여유는 PR #16의 수렴 계약이라 건드리지 않았다.
- **`local_io`는 단계 5가 아니라 `--out`과 함께(단계 6) 넣었다** — 쓰는 곳이 생길 때 계약을 싣는 편이 낫다.
- **`--out`에서 기본 투영도 적용하지 않는다.** 계획은 기본창만 뺐는데, 기본 투영(뉴스의 thumbnail 제외 등)도 화면 예산을 위한 것이라 파일에는 모든 필드를 쓴다. 명시한 `--fields`·`--limit`만 따른다.
- **`--list-fields --out`은 거절한다**(코덱스 리뷰 ③) — 이름 목록이 데이터처럼 읽힌다.
- **SKILL.md는 계획의 7절 구조가 아니라 2절 4문단이 됐다.** 문단 제거 시험(성진 결정 9) 결과이며 성진이 전문을 승인했다.

## 문단 제거 시험 결과 (판정 모델 Claude Opus 5.5, 각 1런)

전체본 24시나리오 22/24 통과. 16문단 × 2시나리오 32런 전부 전체본과 같은 판정. 상황이 실제로 재현된 12문단(발견 단계·심볼 재사용·파일 계산·단위 3·시각 2·변환·coverage·conditions/프리셋·빈 값)을 지웠고, 재현되지 않은 4문단(`${CLAUDE_SKILL_DIR}` 대체 — 하네스가 절대경로를 줬다, partial·too_large·회복 — Opus가 처음부터 `--out`이나 큰 예산을 써서 예산 초과가 한 번도 안 났다)은 남겼다. 확정본은 Codex `gpt-6-astra` medium 7건 7/7.

**재검토 조건**: 모델이 바뀌면 지운 문단 중 "크기로 단위를 판정하지 말라"(모델 기본값 교정 줄)가 다시 필요할 수 있다. 남긴 4문단은 예산 초과를 강제로 만드는 시나리오(`--max-chars` 고정 등)로 한 번 더 시험할 가치가 있다. 하네스는 격리 디렉터리 + `claude -p --safe-mode --restricted --permission-mode acceptEdits --tools "Bash,Read,Write" --allowedTools "Bash"` — `--allowedTools Bash` 없이는 Bash가 permission_denials로 막힌다.

## 남은 실패와 알려진 한계

- 시나리오 aapl-news-all: `--limit 300`으로 196건을 받고 "전체"라고 말했다(원천이 준 것 전부이지 모든 뉴스가 아니다). coverage 문단이 있어도 없어도 같았다 — 문장이 아니라 인터페이스(예: news 결과에 "source returned fewer than asked" 경고)로 풀 후보.
- 시나리오 screen-tech: 사용자 쿼리의 필터 조건은 결과에 증거가 없어(`conditions`는 offset·limit·sort만) 보낸 쿼리를 서술할 수밖에 없다. 채점이 엄격했다고 판단.
- fixture로 재현할 경로가 없어 코드로만 고친 것: 임시 파일 이름 충돌, "index"라는 이름의 열, 다단 인덱스 이름 충돌.
- CI(`test.yml`)는 여전히 disabled — 범위 밖(성진 결정 8).

## 계약이 서로 물린 곳 (하나만 고치면 깨진다)

- 화면 표기(`encode.display`)는 `budget.strip`에서만 일어난다. `shrink`·continuation 계산은 표기 전 데이터로 하고, 예산은 표기 후 텍스트로 잰다.
- 날짜 축약은 `_full`(전체 관측)의 축으로 판정한다. 창만 보고 판정하면 read 페이지마다 같은 축이 다르게 찍힌다.
- `--out` 결과는 `_full`을 지워 `shrink` 대상에서 빠진다. 요약이 예산을 넘으면 열 목록만 개수로 줄인다 — 파일은 이미 쓰였으므로 경로·행 수를 잃으면 안 된다.
- `read`의 `--limit`은 앞으로 걷고 첫 호출은 리프의 끝을 남긴다. `--out` 재시도 안내(`retry`)는 이 차이를 `--start`로 보정한다.
