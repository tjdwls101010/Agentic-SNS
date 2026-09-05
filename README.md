# Agentic SNS

로그인된 브라우저로 소셜 네트워크를 읽고 탐색하는 독립 스킬 모음입니다.

| 스킬 | 하는 일 |
|---|---|
| [reddit](.claude/skills/reddit/SKILL.md) | Aside에 로그인된 Reddit 계정으로 홈·커뮤니티·글·댓글·사용자·검색·구독·저장·추천을 읽고, 댓글 캐시와 재개 가능한 파일 수집을 제공합니다. |
| [facebook](.claude/skills/facebook/SKILL.md) | Aside에 로그인된 Facebook 계정으로 피드·글·댓글·프로필·그룹을 읽고, 페이지 단위 수집과 쿼리 복구를 수행합니다. |

각 스킬은 자신의 `scripts/`만으로 실행됩니다. `.codex`는 `.claude`를 가리키므로 두 환경에서 같은 원본을 사용합니다. 하네스 결정과 검증 기록은 [.claude/harness-spec.md](.claude/harness-spec.md)에 있습니다.

Facebook CLI는 `python3 .claude/skills/facebook/scripts/facebook.py --help`로 시작합니다. 런타임은 Python 3.11+ 표준 라이브러리와 Aside만 사용합니다. 테스트는 `python3 -m pytest tests/`, 실제 브라우저를 읽는 검증은 `python3 -m pytest -m live tests/facebook/live/`로 구분합니다. 수집 파일과 브라우저 캡처는 커밋하지 않습니다.

Reddit CLI는 `python3 .claude/skills/reddit/scripts/reddit.py --help`로 시작합니다. 테스트는 `python3 -m pytest tests/reddit/`, 실계정 검증은 누적 30요청 가드를 둔 `python3 -m pytest -m live tests/reddit/live/`입니다. 구현 결정과 단계별 검증은 [.claude/plans/reddit 스킬 구현 계획.md](.claude/plans/reddit%20스킬%20구현%20계획.md)에 기록합니다.
