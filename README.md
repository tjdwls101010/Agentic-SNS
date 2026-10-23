# Agentic SNS

Claude Code가 사용자가 로그인한 Aside 브라우저로 X(Twitter), Threads, Reddit, Facebook, 네이버 블로그를 **읽게** 해 주는 스킬 `sns`를 담은 레포입니다. 글쓰기·답글·반응·팔로우·저장·DM은 하지 않습니다.

API 키 없이 사용자가 브라우저에서 보는 그대로 읽습니다. 그래서 모든 요청이 사용자의 실제 계정으로 나가며, 스킬은 계정을 지키는 쪽으로 설계되어 있습니다(아래 [계정 보호](#계정-보호)).

## 무엇을 읽나

| 플랫폼 | 명령 |
|---|---|
| `x` | feed profile about graph me list community post replies reposts quotes search trends images doctor schema |
| `threads` | feed profile about graph me activity search post replies quotes reposts images doctor schema |
| `reddit` | feed sub profile about wiki search related me post comments images doctor schema |
| `facebook` | feed profile group post comments replies search about images notifications doctor schema |
| `naver-blog` | search keywords post comments images resolve blog posts feed buddies topic monthly doctor schema |

피드, 글과 답글·댓글 트리, 인용·리포스트, 프로필과 팔로워, 검색, 서브레딧·위키, 페이스북 그룹·페이지, X 리스트·커뮤니티·트렌드, 네이버 블로그의 카테고리·이웃·주제, 글에 든 사진, 그리고 내 저장·좋아요·알림 목록을 읽습니다.

## 필요한 것

- [Claude Code](https://claude.com/claude-code)
- [uv](https://docs.astral.sh/uv/) — CLI는 의존성 없는 PEP 723 스크립트(Python 3.11 이상)라 `uv run`만으로 돕니다.
- Aside 브라우저와 `aside` CLI, 그리고 읽을 플랫폼에 로그인된 상태

## 설치

이 레포에서 Claude Code를 열면 프로젝트 스킬로 바로 쓰입니다. 다른 곳에서 쓰려면 스킬 폴더만 복사합니다. 폴더 하나로 완결되어 있고 상태도 그 안의 `data/`에만 씁니다.

```sh
cp -R .claude/skills/sns ~/.claude/skills/
```

## 쓰기

자연어로 부탁하면 됩니다. 플랫폼을 말하지 않아도 링크만으로 고릅니다.

- "레딧에서 무선 이어폰 후기에서 자주 나오는 불만 정리해줘"
- "https://x.com/… 이 글 답글에서 의견이 어떻게 갈리는지 봐줘"
- "네이버 블로그에서 로봇청소기 후기 찾아서 협찬 글이랑 직접 산 글 나눠줘"
- "이 제품 레딧이랑 네이버 블로그 반응 비교해줘"

CLI를 직접 부를 수도 있습니다.

```sh
uv run .claude/skills/sns/scripts/cli.py --help                    # 플랫폼과 명령 지도
uv run .claude/skills/sns/scripts/cli.py reddit post --help        # 명령 하나가 받는 것·돌려주는 것·드는 요청
uv run .claude/skills/sns/scripts/cli.py reddit schema             # 결과 필드의 뜻
uv run .claude/skills/sns/scripts/cli.py reddit sub r/apple --sort top --time week --limit 5
```

결과의 첫 줄은 무엇을 몇 건 보였는지, 왜 멈췄는지, 요청을 몇 번 썼는지, 남은 한도를 말합니다. 마지막 줄은 이어 읽을 명령(`more:`, `replies <handle>`, `post <url>`)입니다. `--json`은 같은 결과를 JSON으로, `--out FILE`은 긴 수집을 파일로 받습니다. 종료 코드의 뜻은 `--help` 끝에 있습니다.

## 계정 보호

- **차단은 사람이 풉니다.** 체크포인트·챌린지·잠금 같은 신호를 보면 그 플랫폼의 요청을 멈추고 기록합니다. 사용자가 브라우저에서 직접 푼 뒤 `<platform> doctor --unblock`으로 확인해야 다시 읽습니다.
- **한도와 간격을 지킵니다.** 플랫폼이 알려 주는 한도와 해제 시각을 따르고, 요청 사이 간격을 두며, 모든 요청을 계정별 기록에 남깁니다. `<platform> doctor`가 로그인·차단·한도·최근 요청 수를 보여 줍니다.
- **명령 하나는 2분 안에 끝납니다.** 기한에 닿으면 읽은 것까지 내놓고 이어 읽을 명령을 줍니다.
- **전용 탭만 씁니다.** 탭이 필요한 플랫폼은 스킬이 연 탭에서만 요청하고, 쓰지 않으면 비웁니다(`SNS_IDLE_SECONDS`, 기본 300초). 사용자의 다른 탭은 건드리지 않습니다.

Aside 계정이 여럿이면 `SNS_ASIDE_ACCOUNT`(플랫폼별로는 `SNS_ASIDE_ACCOUNT_<PLATFORM>`)로 고릅니다.

## 레포 구조

```
.claude/skills/sns/        설치되는 스킬 (이것만으로 완결)
├── SKILL.md               모델이 읽는 판단 원칙 — 읽은 범위, 읽는 분량, 계정 ≠ 사람, 계정 안전, 네이버 협찬 단서
├── data/                  실행 상태(보호 상태·세션·이어 읽기 핸들·저장 사진), git에 들어가지 않음
└── scripts/
    ├── cli.py             유일한 진입점(파서·디스패치·종료 코드)
    └── sns/               공용 코어(보호·쪽 넘김·기한·출력)와 플랫폼 패키지(x, threads, reddit, facebook, naver_blog)
tests/sns/                 가짜 Aside로 도는 테스트, 플랫폼별 합성 픽스처
contrast/sns/              SKILL.md를 다듬은 대조 실행 하네스, 채점표, 트리거 평가
```

## 개발

```sh
uv run --with 'pytest>=9,<10' pytest -c tests/sns/pytest.ini tests/sns
```

테스트는 실제 브라우저 대신 `tests/sns/fakes/fake_aside.py`로 돌고, 픽스처는 모두 합성 데이터입니다. 실제 계정으로 도는 스모크는 `SNS_LIVE=<platform>`(또는 `all`)과 `-m live`로만 돕니다.

`contrast/sns/`는 SKILL.md의 각 절이 실제로 모델의 답을 낫게 하는지 재는 하네스입니다. 같은 과제를 본문 없는 스킬(A)과 초안(B)으로 Opus·Sonnet에 돌리고, 채점자가 어느 쪽인지 모르게 `rubric.md` 기준으로 채점합니다. 과제의 실제 대상은 환경 변수(`SNS_TASK_*`)로만 받고 실행 산출물은 레포 밖에 둡니다. `contrast/sns/triggers/`는 `claude plugin eval`로 스킬이 언제 불리는지 잽니다.

플랫폼 사이트가 바뀌면 그 플랫폼의 `scripts/sns/<platform>/web/`만 고치면 되도록, 사이트 형식은 그 안에만 둡니다.
