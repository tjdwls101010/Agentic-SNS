# Reddit 구현 진행

TaskCreate 도구가 노출되지 않아 이 파일을 지속 트래커로 사용한다. 승인된 완료 기준은 아래와 같다.

| 단계 | 내용 | 완료 판정 |
|---|---|---|
| P0 | 스캐폴드: `reddit/` 생성, `tests/reddit/`, `.gitignore`에 이 계획 파일 예외, `harness-spec.md` 인벤토리 `approved` 행, 심볼릭 링크 | `audit_harness.py --path .`가 skill 2개·드리프트 0. `pytest tests/reddit`이 0개 수집 exit 5. `ls -l ~/.claude/skills/reddit`이 레포를 가리킴 |
| P1 | `_errors`·`_aside`·`_budget`·`_transport`·`_target` + `fetch.js`·`resolve.js` + `doctor` | fake aside 단위 테스트 통과. classify 픽스처: 429→5+만료 차단, HTML 403+표식→5+무만료, HTML 403 무표식→6, 502→6(차단 파일 없음), `remaining==0`인 200→정상 출력 후 파일 차단, 다음 호출 요청 없이 5, 404→9, `gold_only`/`quarantined`→9, 모르는 reason→6, `morechildren.json.errors` 비어있지 않음→6, 빈 children→7. `_budget`: 두 프로세스 동시 예약이 합쳐 1회만 차감, 만료 뒤 0 폐기, 시계 역행 무시, 헤더 없음 시 로컬 차감. `_target`: URL 14형을 Target으로, share만 resolve 경로. node: `fetch.js`가 URL을 받지 못하고 `raw_json=1`을 붙이며 3xx를 봉투로 돌려주고, `resolve.js`가 잘못된 호스트·4홉째를 거부. 라이브: `doctor` exit 0, 예산 파일에 `expires_at` |
| P2 | `_models`·`_entities`·`_schema`·`_listing`·`_render`·`_output(목록)` + `home`·`sub`·`user`·`me` | 합성 픽스처로 유형 6종(F9) 빌드·render 골든(본문 정규화: 공백 접기·제로폭 제거·마크다운 벗기기·링크 축약·빈 필드 줄 생략), 혼합 목록에서 `t3_x`·`t1_x` 공존. 라이브: `home --limit 3`, `sub r/python --sort new --limit 3` → `more:` 실행이 캐시 소진 후 **실제 `after` 요청**을 내고 fullname 중복 0, `user u/spez --type overview --limit 3`, `me subs --limit 3`, `--json` 단일 문서, 성진이 준 공유 링크 1건 해석(A3) |
| P3 | `_tree`·`_thread` + `post`·`comments`·`related` | 단위(합성 500노드 트리): 표시 25/깊이 2 분리, 보인 부모 아래 새 노드의 문맥 줄, `--depth` 상향으로 깊은 답글 열기, morechildren 평탄 응답 병합(형제 위치·고아 재연결·요청 미반환 id `missing`), 새 노드·포인터 없는 배치→`stalled`, 빈 children 포인터→서브트리 경로, 포인터 키에 children 포함, 앵커 검증(없는 댓글 id→9), 24h 정리·200MB 상한. 라이브: 2,000+댓글 스레드에서 `post` 요청 1회, `comments --after` 첫 회 요청 0, 저장분 소진 뒤 `morechildren` 1회의 **반환 id가 모두 요청 id의 부분집합이고 부모 연결이 `nodes`에 존재**, `comments <댓글 permalink> --context 2`가 조상부터 렌더하고 요청 댓글을 강조 |
| P4 | `search`·`about` + `--since/--until`·`--out` | 단위: 창 테스트가 포함·제외·고정글 제외·`window_reached`/`exhausted` 구분을 단언, 검색 0건 재시도(예산 있음→재시도, 없음→8), `about`의 r/·u/ 분기와 접두어 없는 단어 거절, 댓글 `--out` 평탄 레코드+진행 마커 복구. 라이브: `search "type hints" --in r/python --limit 3`, `search seoul --type subs --limit 3`→첫 결과로 `sub`, `about r/python`(t5 + rules 배열, 개수 미단언), `about u/spez`, `sub r/python --sort new --since <2일 전> --limit 20 --out <레포 밖>` 재실행 "already complete" |
| P5 | `SKILL.md`, `harness-spec.md`, README, CI, `validate_harness.py` exit 0, description 대조(facebook·ultra-search와 나란히) | 검증 절 참조 |


## 상태

- P0: 완료 — audit skill 2개·drift 0, pytest 0개 exit 5, 사용자 링크 확인. 독립 리뷰 대기
- P1: 진행 중
- P2: 대기
- P3: 대기
- P4: 대기
- P5: 대기
