# Agentic SNS 런칭 문안 초안

보내는 건 성진이 직접 한다. 순서는 계획 4단계: Aside 쪽 → 디렉터리 → X 런칭 글 → 같은 주 Show HN·Reddit·Trendshift → 긱뉴스. 첨부 자산은 모두 `docs/media/`에 있다(`demo.mp4` 16:9, `demo-square.mp4` 1:1, `x-card.png`, `social-preview.png`).

먼저 할 일: GitHub Settings → Social preview에 `docs/media/social-preview.png` 업로드.

---

## 1. Aside 팀 (메일 또는 X DM, @asideai)

**Subject:** Open-source skill: Claude Code reads X/Reddit/Threads/Facebook/Naver through Aside

Hi Aside team,

I built an open-source Claude Code skill that runs entirely on Aside: it reads X, Threads, Reddit, Facebook and Naver Blog through the user's logged-in Aside browser, in a dedicated tab, read-only. It stops on any checkpoint and waits for the user, keeps to each platform's limits, and logs every request.

45-second demo (real run, 144 Reddit comments in 2 requests): https://github.com/tjdwls101010/Agentic-SNS

Install: `npx skills add tjdwls101010/Agentic-SNS`

If it fits, I'd love it if you shared it with your users or listed it anywhere you showcase what people build on Aside. Happy to adapt anything that makes it a better Aside citizen.

Thanks for building the `aside` CLI — it's what made this possible.

— Seongjin

---

## 2. Aside Discord (쇼케이스 채널) / asideskills.com 등록 설명

**Agentic SNS — read social networks from Claude Code through Aside**

Claude Code skill that reads X, Threads, Reddit, Facebook and Naver Blog through your logged-in Aside browser. Feeds, full comment trees, quotes, profiles, search, groups, subreddits — read-only, in its own tab, stops on checkpoints and waits for you.

`npx skills add tjdwls101010/Agentic-SNS` · https://github.com/tjdwls101010/Agentic-SNS

(데모 mp4 첨부)

---

## 3. X 런칭 글 (첫 글 + 답글 2개)

**첫 글** (영상 `demo.mp4` 첨부):

I made Claude Code read every comment in a Reddit thread for me.

144 comments, 2 requests, grouped into what people actually said.

It reads X, Threads, Reddit, Facebook and Naver Blog through your own logged-in browser. Read-only. No API keys.

npx skills add tjdwls101010/Agentic-SNS

**답글 1** (`x-card.png` 첨부):

How it stays safe for your account:
• runs in its own tab of @asideai, your other tabs untouched
• never posts, likes, follows or DMs
• hits a checkpoint → stops and waits for you to clear it
• respects rate limits, logs every request

**답글 2:**

Open source: https://github.com/tjdwls101010/Agentic-SNS

Works with Claude Code via the Aside browser. Ask in plain words — "how are the replies to this tweet split?" — or paste a bare link.

---

## 4. Show HN

**Title:** Show HN: Let Claude Code read social media through your own browser, read-only

**URL:** https://github.com/tjdwls101010/Agentic-SNS

**Text (첫 댓글):**

I wanted Claude Code to read Reddit threads, X replies and Korean Naver blogs the way I read them — logged in, seeing what I see — without handing it API keys or a copy of my cookies.

Agentic SNS is a Claude Code skill that drives the Aside browser (an AI browser with a CLI) and reads X, Threads, Reddit, Facebook and Naver Blog from a tab it opens for itself. The part I spent the most time on is account safety, since every request is the user's real account:

- It never writes: no posting, replying, reacting, following, saving or DMs.
- When a platform shows a checkpoint, challenge or lock, it stops reading that platform and records it. Only after the person clears it in the browser and confirms with `doctor --unblock` does it read again.
- It follows the limits and reset times the platform reports, paces requests and logs every one per account.
- Each command returns within two minutes with what it read and the command to continue.

The demo is a real run: one r/headphones thread, all 144 comments in 2 requests, grouped by Claude.

Limitations: it requires Aside, and site formats change — each platform's format lives in one folder so a fix lands in one place. Feedback on the safety model especially welcome.

---

## 5. r/ClaudeAI (또는 r/ClaudeCode)

**Title:** I made a skill that lets Claude Code read Reddit, X, Threads, Facebook and Naver Blog through your own browser (read-only)

**Body:** (영상 첨부)

Ask "what do people in this thread actually think?" and Claude reads the whole comment tree, then groups it. The demo is a real r/headphones thread: 144 comments, 2 requests.

- Runs in your logged-in Aside browser, in its own tab — no API keys, no copied cookies
- Read-only: never posts, votes, follows or DMs
- Stops on any checkpoint and waits for you; respects rate limits
- Install: `npx skills add tjdwls101010/Agentic-SNS`

Repo: https://github.com/tjdwls101010/Agentic-SNS — happy to answer questions about how the account protection works.

(서브레딧 자기 홍보 규칙을 올리기 전에 확인한다. 일부는 요일 제한이나 플레어를 요구한다.)

---

## 6. Trendshift

https://trendshift.io 상단 "Submit repository"에 레포 URL 제출.

---

## 7. 긱뉴스 (news.hada.io, 같은 주)

**제목:** Agentic SNS - Claude Code가 내 브라우저로 X·Threads·Reddit·페이스북·네이버 블로그를 읽게 해주는 스킬

**본문:**

- Claude Code 스킬로, 로그인된 Aside 브라우저의 전용 탭에서 다섯 SNS를 **읽기만** 함 (글쓰기·좋아요·팔로우·DM 없음)
- API 키나 쿠키 복사 없이 사용자가 브라우저에서 보는 그대로 읽음
- 체크포인트·잠금을 만나면 멈추고 사람이 풀 때까지 기다림. 플랫폼 한도와 요청 간격을 지키고 모든 요청을 기록
- 네이버 블로그는 협찬 표기 위치·체험단 링크 같은 단서를 구분해 읽도록 판단 규칙이 들어 있음
- 데모: r/headphones 스레드 댓글 144개를 요청 2번으로 끝까지 읽고 반응 유형별로 정리
- 설치: `npx skills add tjdwls101010/Agentic-SNS`
