# Agentic SNS 마케팅 계획

## Context

`tjdwls101010/Agentic-SNS`는 2026-10-15 공개 후 스타 0개다. `gh repo view` 기준 description 빈칸, topics 없음, homepage 없음, README는 한국어뿐이고 데모가 없다. 성진은 **처음부터 글로벌**을 원하고, **홍보에 쓸 본인 채널은 없다**.

조사로 확인한 지형(2026-10-29):

- **랭킹판은 스킬 레포가 휩쓰는 중.** GitHub 일간 트렌딩에 obra/superpowers, pbakaus/impeccable, Nutlope/hallmark, expo/skills, elayadesign/ai-design-skills가, Trendshift 일간에 impeccable, taste-skill, baoyu-design이 있다. Trendshift는 `#AI skills` 토픽을 따로 두고, 순위 옆 "Live mentions"는 **레포 링크가 담긴 X 글**을 실시간으로 모은다. 즉 X 언급이 Trendshift 노출의 입력이다. Korean 언어 필터 트렌딩은 일간이 비어 있고 주간은 1개(이번 주 스타 1개)뿐이다.
- **같은 니치에 거인이 있다.** Panniantong/Agent-Reach(~106k, 쿠키를 복사한 백그라운드 브라우저, 읽기 전용, 다플랫폼), mvanhorn/last30days-skill(~66k, 슬래시 명령 하나로 리서치 요약), jackwener/opencli(~31k, 로그인된 Chrome을 구동). X·Reddit 단일 도구는 수백~수천 스타가 흔하다. 반면 **Threads, Facebook, Naver Blog를 로그인 브라우저로 읽는 도구는 사실상 없다**(최고가 Threads 6, Facebook 15, Naver는 공식 API 키 기반 87). 2026년 5월 Reddit이 비인증 `.json` 접근을 막아 키 없는 Reddit 스크래퍼 다수가 깨졌다(PyPI `mcp-reddit` 설명).
- **Aside라는 하드 의존성.** Aside는 YC F25, 팀 8명, 2026-06-23 런칭, 자사 주장으로 사용자 5만+·주간 25% 성장, X 팔로워 ~1.2만. 공식 스킬 마켓은 없고, 서드파티 디렉터리 asideskills.com은 등록 스킬이 1개, GitHub의 서드파티 Aside 스킬 레포는 1스타짜리 하나뿐이다.

- **최근 뜬 스킬 레포 6개의 첫 불꽃.** 4개(impeccable, taste-skill, hallmark, baoyu-design)는 작성자의 X 글 한 편, superpowers는 블로그 글 → Simon Willison 링크 → HN 435점, elayadesign은 두 번째 X 글(835K 조회)에서 터졌다. Product Hunt나 뉴스레터로 시작한 곳은 없다. taste-skill은 팔로워 거의 없는 고등학생의 첫 X 글이 122K 조회를 찍었고, elayadesign은 첫 글(173K 조회)로 스타 2.8k에 그쳤다가 석 달 뒤 두 번째 글로 하루 +2k가 됐다. 즉 **조회수를 만드는 건 팔로워가 아니라 "결과물이 한눈에 보이는" 글**이고, **한 번의 런칭이 아니라 버전마다 다시 쏘는 것**이 공통이다. 설치 표준은 `npx skills add owner/repo`(skills.sh)로 굳었고, hallmark·baoyu-design은 런칭 글에 이 한 줄을 넣었다. superpowers의 두 번째 급등은 Anthropic 공식 플러그인 마켓 등재 시점과 겹친다.

결론: Claude Code 전체 사용자에게 퍼뜨리면 대부분 "Aside 필요"에서 이탈한다. 그래서 현실적인 목표는 **"Aside + Claude Code 사용자를 위한 표준 SNS 리더"**가 되어 Aside의 성장에 올라타는 것이고, 전체 트렌딩 진입은 그 결과로 노린다. Agent-Reach와 범위로 싸우지 않고, 아래 세 가지로 차별화한다.

1. 쿠키 복사가 아니라 **사용자의 실제 브라우저 탭**에서 읽는다(전용 탭, 다른 탭 불간섭).
2. **읽기 전용 + 명시적 계정 보호**: 체크포인트에서 멈추고 사람이 풀 때까지 대기, 한도·간격 준수, 요청 기록.
3. **아무도 없는 플랫폼**: Threads, Facebook, Naver Blog. 그리고 Reddit `.json` 차단 이후에도 동작한다.

## 단계와 완료 판정

실행 시 `TaskCreate` 트래커를 열고 아래 판정을 그대로 description에 넣는다. 레포 변경은 `docs/readme-global-launch` 브랜치 → PR → 스쿼시 머지. **외부 게시(HN, Reddit, X, 이메일, 디렉터리 등록)는 Claude가 초안만 쓰고 성진이 직접 보낸다.**

### 0. 주장 검증 (선행, 읽기 전용)
- 다섯 플랫폼 `doctor`와 대표 명령 한 번씩을 실제 계정으로 돌려 README가 약속할 기능이 지금 동작하는지 확인한다. 특히 Naver Blog(자동화 적대적).
- 작업 트리의 `SKILL.md`에 커밋 안 된 `disable-model-invocation: true`가 있다. 이 상태로는 "자연어로 부탁하면 된다"는 README 주장과 데모가 성립하지 않으므로, 성진의 로컬 의도인지 확인하고 **이번 PR에는 넣지 않는다**.
- 판정: 플랫폼별 동작 여부 표가 나오고, README에는 동작 확인된 것만 쓴다.

### 1. 레포 메타데이터 — GitHub 검색 노출 (Claude, `gh repo edit`)
GitHub 저장소 검색은 이름, description, topics, README를 맞춰 보고, topic 페이지(`github.com/topics/<t>`)는 스타순으로 줄 세운다. 그래서 큰 topic은 검색에 걸리게 하는 용도로, 작은 topic은 그 페이지 상위를 차지하는 용도로 쓴다(`gh api search/repositories?q=topic:…` 기준 2026-10-29 저장소 수).
- **description** (검색어가 실제로 들어가게, 350자 이내): "Claude Code skill that reads X/Twitter, Threads, Reddit, Facebook and Naver Blog through your own logged-in Aside browser. Read-only, account-safe, no API keys." Agent-Reach는 "Read & search Twitter, Reddit … zero API fees"처럼 사람들이 치는 단어를 그대로 쓴다.
- **topics** (최대 20개):
  - 검색 매칭용(큰 것): `claude-code`(10.5만) `agent-skills`(3.9만) `claude-skills`(1.3만) `mcp`(10.8만) `ai-agent` `social-media`(1.1만) `twitter`(1.3만) `reddit`(5.2k) `browser-automation`(5.5k)
  - 검색어 그대로: `twitter-scraper` `reddit-scraper` `social-media-scraper` `claude-code-skills`(2.4k)
  - 상위 차지용(작은 것): `aside`(27) `naver`(255) `naver-blog` `threads`(3.3k) `facebook` `read-only`
- **social preview 이미지**(Settings → Social preview, API 없음 → 성진이 업로드): X·Discord·HN에 링크를 붙였을 때 뜨는 카드. 런칭 채널이 X라 기본 카드(레포 이름만 나옴)와 결과 캡처 카드는 클릭률 차이가 크다. Claude가 1280×640 이미지를 만들어 준다.
- **homepage**: 데모 영상이나 README 앵커를 넣는다.
- 판정: `gh repo view --json description,repositoryTopics,homepageUrl`에 값이 들어 있고, 비로그인 창에서 `github.com/topics/aside` 첫 화면에 레포가 보인다.

### 1.5. 한 줄 설치 지원 (Claude, PR)
- `npx skills add tjdwls101010/Agentic-SNS`가 `.claude/skills/sns/`를 찾아 설치하는지 스크래치 디렉터리에서 실제로 돌려 본다. 안 되면 skills.sh가 요구하는 위치·형식에 맞추는 최소 변경(예: 루트에서 스킬 경로를 가리키는 설정)을 조사해 적용한다. Claude 플러그인 마켓 형식(`.claude-plugin/`)도 같은 PR에서 검토한다.
- 판정: 빈 디렉터리에서 그 한 줄로 설치한 뒤 `~/.claude/skills/sns/SKILL.md`가 생긴다.

### 2. README 영어화와 첫 화면 재구성 (Claude, PR)
- `README.md`를 영어로 다시 쓰고, 지금 한국어 본문은 `README.ko.md`로 옮겨 상호 링크한다.
- 첫 화면 순서: 한 줄 피치 → 데모 GIF → **"Requires Aside browser"**를 맨 위에 명시(현재 23행) → 한 줄 설치(`npx skills add …`, 대안으로 `cp -R`) → 자연어 예시 3개(영어권에서 와닿는 것: "Summarize complaints about X in r/headphones", "How are replies split on this tweet?").
- 세 차별점을 비교표로 정리한다(Agent-Reach·last30days·opencli 대비: 읽는 방식, 쓰기 여부, 계정 보호, Threads/Facebook/Naver 지원). 상대 수치는 쓰지 않고 방식만 비교한다.
- 판정: GitHub 렌더링에서 스크롤 없이 피치·데모·요구사항·설치가 보이고, `README.ko.md` 링크가 동작한다.

### 3. 데모 자산 — Vox 스타일 설명 영상 (Claude가 전부 제작, 성진은 검토만)
성진이 직접 녹화하지 않는다. Vox 설명 영상의 시각 언어(종이 질감 배경, 형광펜으로 긋는 문장, 오려 붙인 스크린샷 콜라주, 굵은 산세리프 자막, 줌인되는 데이터 차트)로 **45초 내외 모션그래픽**을 코드로 만든다. Vox 로고·이름·브랜드 색은 쓰지 않고 스타일만 빌린다. X는 소리 없이 자동 재생되므로 내레이션 없이 자막만으로 이해되게 만든다(TTS 내레이션은 반응을 보고 다음 버전에서).
- **도구**: Remotion(React로 영상 구성 → `npx remotion render`로 mp4). 장면이 코드라 데이터만 바꿔 버전마다 다시 뽑을 수 있다. 소스는 `docs/video/`에 두고 커밋한다. `node_modules`와 렌더 캐시는 `.gitignore`에 넣는다.
- **재료**: Claude가 성진의 Aside로 공개 서브레딧 하나(예: r/headphones의 특정 제품 불만)를 실제로 읽는다(`reddit sub`·`reddit comments`). 영상 속 숫자·인용·차트는 전부 이 실제 출력에서 온다.
- **장면 구성(초안)**:
  1. 0–6초, 문제: 종이 위로 레딧 댓글 카드 수백 장이 쌓인다. 자막 "300 comments. Nobody reads them all."
  2. 6–14초, 요청: 터미널에 자연어 한 문장이 타이핑된다. "What do people actually hate about the XM6?"
  3. 14–24초, 방식: Aside 전용 탭이 열리고 댓글을 넘긴다. 형광펜이 "your own browser", "read-only"를 긋는다.
  4. 24–36초, 결과: 불만 유형 막대 차트가 그려지고, 막대마다 실제 인용 한 줄이 오려 붙는다(핸들은 지움).
  5. 36–41초, 안전: 체크포인트 경고 → "stops and waits for you" 자막. 계정 보호 차별점을 보여 준다.
  6. 41–45초, 엔드 카드: `npx skills add tjdwls101010/Agentic-SNS` + "X · Threads · Reddit · Facebook · Naver Blog".
- **산출물**: 16:9 mp4(X·README용), 1:1 mp4(X 피드용), README용 무음 GIF 또는 GitHub 첨부 mp4, 4장면 정지 프레임 → X 첫 이미지(1200×675)와 social preview(1280×640).
- **개인정보**: 타인 핸들은 지우고 인용은 짧게, 집계 위주로 쓴다. 성진 계정 정보(알림, 저장 목록 등)는 화면에 넣지 않는다.
- 성진이 할 일: 장면 초안(정지 프레임)과 최종 영상 OK, social preview 업로드(API 없음).
- 판정: `npx remotion render`로 16:9·1:1 mp4가 다시 만들어지고, 영상 속 모든 숫자가 저장된 실제 CLI 출력과 일치하며, 타인 핸들과 성진 계정 정보가 없다.

### 4. 런칭 순서 (성진 실행, Claude가 각 문안 초안)
채널이 없으므로 이미 사람이 모인 곳을 빌린다. 순서가 중요하다 — 앞 단계의 첫 스타·언급이 뒤 단계의 사회적 증거가 된다.

1. **Aside 쪽(가장 큰 레버)**: Aside 팀에 데모와 함께 짧은 메일/DM — "Aside 위에서 도는 오픈소스 SNS 리더 스킬을 만들었다". 팀 8명 스타트업은 생태계 쇼케이스를 리트윗할 동기가 크고, @asideai 리트윗 한 번이 Trendshift Live mentions의 입력이 된다. 같은 날 Aside Discord 쇼케이스 채널과 asideskills.com에 등록한다.
2. **스킬 디렉터리**: skills.sh 등록, awesome-claude-skills 류 리스트에 PR, Anthropic 공식 플러그인 마켓 등재 신청(superpowers의 2차 급등과 겹친 경로).
3. **X 런칭 글(성진 계정, 팔로워 없어도 됨)**: 데모 영상 + 결과 캡처 + `npx skills add` 한 줄 + "read-only, runs in your own browser" 한 줄. @asideai와 @AnthropicAI·Claude Code 쪽 계정을 태그한다. 6개 사례 중 4개가 이 형식으로 시작했다.
4. **집중 1주(같은 주 안에 몰아서)**: Show HN(각도: "SNS 도구 또 하나"가 아니라 "AI 에이전트가 내 실제 계정으로 SNS를 읽을 때 계정을 지키는 법"), r/ClaudeAI·r/ClaudeCode, Trendshift "Submit repository". GitHub 트렌딩은 짧은 기간의 스타 속도로 오르므로 분산하지 않는다.
5. **한국 보조 채널**: 글로벌이 우선이지만 비용이 거의 없으니 같은 주에 긱뉴스 한 건. Korean 필터 트렌딩은 비어 있어 소량 스타로도 1위가 된다(README 언어 감지 기준이라 영어 README로 바꾸면 해당 안 될 수 있음 — 기대하지 않는다).
- 판정: 각 채널 문안 초안이 `docs/` 밖(스크래치패드)에 있고, 성진이 보낸 채널과 날짜가 기록된다.

### 5. 지속 루프
- 첫 런칭이 조용해도 실패가 아니다. impeccable은 첫 X 글이 좋아요 14개였고 v1.1에서, elayadesign은 석 달 뒤 두 번째 글에서 터졌다. 새 플랫폼(예: Instagram, LinkedIn)이나 큰 표면을 추가할 때마다 결과 캡처를 담은 X 글 하나를 성진이 올린다. Trendshift는 X 언급을 모으므로 반복 노출이 누적된다.
- 판정: 릴리스마다 changelog 한 줄 + 게시 링크.

## 바꿀 파일

- 레포 이름 `Agentic-SNS`는 그대로 둔다(성진 결정). 검색 보완은 description과 topics로만 한다.
- `README.md` (영어로 재작성), 신규 `README.ko.md`(현 본문 이동), 신규 `docs/video/`(Remotion 소스, 장면 데이터 JSON), 렌더된 mp4·GIF·정지 프레임, `.gitignore`에 `node_modules`·렌더 캐시 추가
- skills.sh·플러그인 마켓 설치에 필요한 최소 파일(1.5단계에서 확인 후 결정)
- 레포 메타데이터(`gh repo edit`, 파일 아님)
- `.claude/skills/sns/SKILL.md`는 건드리지 않는다(로컬 미커밋 변경은 PR에서 제외).

## 검증

- `uv run .claude/skills/sns/scripts/cli.py <platform> doctor` 다섯 번 + 플랫폼별 대표 읽기 1회 → 0단계 표.
- `uv run --with 'pytest>=9,<10' pytest -c tests/sns/pytest.ini tests/sns` 통과(README 변경이지만 회귀 없음 확인).
- 스크래치 디렉터리에서 `npx skills add tjdwls101010/Agentic-SNS` 설치 확인.
- `npx remotion render`로 16:9·1:1 재렌더링 확인, 정지 프레임 PNG 크기(1200×675, 1280×640) 확인, 영상 속 숫자를 저장된 CLI 출력과 대조.
- `gh repo view --json description,repositoryTopics,stargazerCount`로 메타데이터 확인, 런칭 후 1주간 스타 추이와 Trendshift 등재 여부 기록.
- PR 미리보기에서 README 첫 화면·데모·한국어 링크 렌더링 확인.
