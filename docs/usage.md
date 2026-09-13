# Using the skills

[Back to the README](../README.md)

## Follow a result

An agent can choose where to go next from the handles, URLs, and continuation commands in each response. These commands were used to follow NASA's public X profile to its posts and one post's replies on September 8, 2026:

```bash
python3 .claude/skills/twitter/scripts/twitter.py about @NASA
python3 .claude/skills/twitter/scripts/twitter.py user @NASA --limit 2 --chars 220
python3 .claude/skills/twitter/scripts/twitter.py post https://x.com/NASA/status/2095890073031966734 --limit 2
```

The first command returns a profile card. The second returns post text, authors, timestamps, counts, and URLs; a `more:` command continues the listing. The third opens the chosen post with its full received text and a reply batch. In this run, it reported `2 direct shown of 139 reported`, so the result was a sample of the replies. The post was found in the second command's output; your next result may be different. Copy the URL relevant to your question rather than relying on a fixed post remaining available.

These are available operations, not a fixed workflow. Ask the agent to investigate a question and it can choose the order. For example:

```text
Find discussions of Python packaging on Reddit. Open a relevant thread, read contrasting replies, and summarize the arguments with comment links.
```

Keep the requested scope bounded. A displayed item limit is not necessarily a limit on fetched items or network requests. A cached continuation may need no new request; fetching another server page can return more items than the display limit.

## Use the skills in other projects

Each skill is self-contained: copy its complete directory. For SEC this includes `Scripts/`, `pyproject.toml` and `uv.lock`; for SNS skills it includes `scripts/`. Keep the cloned repository if you link to it.

From the clone's root, install the Twitter skill for all your projects in the host you use. Before running a link command, check whether the destination already exists; keep any existing installation rather than creating a link inside it.

| Host | Personal skill directory |
|---|---|
| Claude Code | `~/.claude/skills` |
| Codex | `~/.agents/skills` |

Claude Code:

```bash
mkdir -p "$HOME/.claude/skills"
ln -s "$PWD/.claude/skills/twitter" "$HOME/.claude/skills/twitter"
```

Codex:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/.claude/skills/twitter" "$HOME/.agents/skills/twitter"
```

For another skill, replace both occurrences of `twitter` in the selected command with `reddit`, `facebook`, `threads`, `naver-blog`, or `sec`. Alternatively, copy the complete skill directory into a destination that does not already exist. Restart your agent if it does not discover the installation.

For project-only installation, use that project's `.claude/skills` or `.agents/skills` directory instead. After installation outside the clone, resolve CLI commands relative to the installed `SKILL.md`, rather than to your current working directory. `${CLAUDE_SKILL_DIR}` in a skill denotes that skill directory; hosts that do not substitute it must use the actual absolute path.

To update a linked installation, run `git pull --ff-only` in the clone after reviewing incoming changes. A copied installation must be updated separately. Deleting a symlink removes that installation without deleting the source skill.

## SEC EDGAR

Install `uv` and Python 3.11+ and copy the complete SEC skill directory if using it outside this clone. Create the local configuration from the example, then replace its placeholder with your own requester identity:

```bash
cp .claude/skills/sec/Scripts/.env.example .claude/skills/sec/Scripts/.env
uv run --isolated --frozen --project .claude/skills/sec python .claude/skills/sec/Scripts/sec.py --help
uv run --isolated --frozen --project .claude/skills/sec python .claude/skills/sec/Scripts/sec.py doctor
```

Preserve an existing `.env` instead of overwriting it. The file is Git-ignored and its identity is sent to SEC for request identification; it is not an API key or SEC login. Help and `schema` work without it. Use command-specific help for settings diagnosis, connection checks and recovery.

For example, ask: “Find Microsoft's latest annual filing and read the end of its risk factors, citing the original source.” The skill chooses company, filing and document navigation from the question. [SEC guidance](../.claude/skills/sec/SKILL.md) explains how to interpret periods, amendments, tables and incomplete reads. Arguments and output contracts live in the CLI's help and `schema`.

## CLI reference

Run these from the clone's root. Every CLI provides `--help`, command-specific help, and `schema`; `--help` and `schema` do not read your browser.

| Platform | Entry point |
|---|---|
| X | `python3 .claude/skills/twitter/scripts/twitter.py --help` |
| Reddit | `python3 .claude/skills/reddit/scripts/reddit.py --help` |
| Facebook | `python3 .claude/skills/facebook/scripts/facebook.py --help` |
| Threads | `python3 .claude/skills/threads/scripts/threads.py --help` |
| Naver Blog | `python3 .claude/skills/naver-blog/scripts/naver_blog.py --help` |

For example:

```bash
python3 .claude/skills/twitter/scripts/twitter.py post --help
python3 .claude/skills/twitter/scripts/twitter.py schema
```

The schema describes normalized fields and stopping conditions. Use ordinary text for exploration, `--json` when a downstream program needs structured objects, and a supported command's `--out` option for resumable file collection. Keep output files outside the repository. The printed continuation command carries the original query context; copy it instead of guessing cursor arguments.

## Platform notes

| Platform | Interpretation and implementation notes |
|---|---|
| X | [Skill guidance](../.claude/skills/twitter/SKILL.md) explains repost authors, query signatures, reply limits, and account budgets. [Implementation record](../.claude/plans/twitter%20스킬%20구현%20계획.md). |
| Reddit | [Skill guidance](../.claude/skills/reddit/SKILL.md) explains comment trees, cached observations, ranked results, and shared budgets. [Implementation record](../.claude/plans/reddit%20스킬%20구현%20계획.md). |
| Facebook | [Skill guidance](../.claude/skills/facebook/SKILL.md) explains ranked feeds, truncated text, coverage, and pagination. [Implementation record](../.claude/plans/facebook%20스킬%20구현%20계획.md). |
| Threads | [Skill guidance](../.claude/skills/threads/SKILL.md) explains relationship samples, reply coverage, and local request counts. [Implementation record](../.claude/plans/threads%20스킬%20구현%20계획.md). |
| Naver Blog | [Skill guidance](../.claude/skills/naver-blog/SKILL.md) explains unreliable totals, extraction coverage, reviews, and neighbor visibility. [Implementation record](../.claude/plans/naver-blog%20스킬%20구현%20계획.md). |

## Troubleshooting

| Symptom | Next step |
|---|---|
| `aside` is not found | Install the CLI in Aside's Developer settings and ensure the terminal running your agent has it on `PATH`. Reopen that terminal if its environment changed. |
| Login error | Open the relevant SNS in Aside under account `u0`, sign in, then run that skill's `doctor` command. |
| Account works in another browser | Sign into the site in Aside; these skills do not read your separate Chrome, Safari, or Firefox session. |
| Rate limit or challenge | Read the returned recovery instruction. Resolve any challenge in Aside and wait for the stated rate-limit window; repeated retries do not repair a blocked account. |
| Query or response changed | Follow the command's `fix`. X, Facebook, and Threads have `refresh` commands for supported query recovery. If recovery fails, file a sanitized bug report. |
| Partial or empty output | Inspect the stop reason and completeness fields before concluding there is no content. A partial collection is not an exhaustive search. |
| Agent does not find the skill | Check its installation directory and `SKILL.md`, then restart the agent. Try `/twitter` in Claude Code or `$twitter` in Codex. |

For an X connection check:

```bash
python3 .claude/skills/twitter/scripts/twitter.py doctor
```

`doctor` reads the real account and can display account information. Review its output before sharing it in an issue. [Report security-sensitive failures privately](../SECURITY.md).
