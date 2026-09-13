# Agentic SNS

**Skills that let Claude Code and Codex explore social networks freely.**

Give your agent a question. It can search, open posts and replies, inspect profiles, and follow the next useful link across X, Reddit, Facebook, Threads, and Naver Blog. The skills use your logged-in [Aside](https://aside.com/) browser through CLI commands and text results, so exploration does not require interpreting screenshots and clicking through each page.

Try asking: **“Explore NASA's recent X posts. Open a post that interests you, read its replies, and summarize what you found with links.”** The agent chooses its next command from the results. For example, a profile lookup returns this real output row:

```text
$ python3 .claude/skills/twitter/scripts/twitter.py about @NASA
@NASA (NASA ✓gov) · followers 92.4M · following 117 · posts 74.3K · joined 2007-12 · bio: "Making the seemingly impossible, possible. ✨" · url: "https://x.com/NASA"
```

Captured September 8, 2026; request-budget header omitted. Live content and counts change. [See the profile → posts → replies commands](docs/usage.md#follow-a-result).

**For the SNS skills:** macOS 15+, Python 3.11+, Aside with an account and the relevant SNS login, and a locally running Claude Code or Codex. These are **read-only** skills; they do not publish, reply, like, or follow. Your agent's usual subscription/API costs still apply. Maintenance is best effort; no numerical speed or token-savings claims are made.

**[Start with Aside installation](#get-started)** → clone this repo → make your first request.

The [SEC skill](.claude/skills/sec/SKILL.md) also reads original EDGAR company filings and exhibits through direct HTTPS. It requires Python 3.11+, `uv`, and your SEC requester identity; Aside and an SNS account are unnecessary. [Set up SEC access](docs/usage.md#sec-edgar).

## Get started

### 1. Prepare Aside and your accounts

1. [Download Aside](https://aside.com/download), open it, and sign in or create an Aside account. Aside's [setup guide](https://docs.aside.com/help/get-started) requires macOS 15 or later.
2. Open the SNS you want to explore in Aside and log in. Start with [X](https://x.com/) to follow the example below; you do not need accounts on all five platforms.
3. Install the Aside CLI from **Aside Settings → Developer**. The official [CLI instructions](https://docs.aside.com/help/developers) also provide a terminal installer.
4. Check the CLI and Python in the terminal that will run your agent:

```bash
aside --version
aside account status u0
python3 --version
```

Expected: a CLI version, a signed-in Aside account at `u0`, and Python 3.11 or later. The bundled skills explicitly use **Aside account `u0`**; changing the CLI's default account does not change this. Log into your SNS accounts in that Aside account's browser.

Aside lists a [Free plan and paid plans](https://aside.com/pricing). Its public pricing page does not specify REPL access by tier; check your account's developer access before relying on the Free plan. The skills do not require an SNS developer API key. Claude Code or Codex must already be installed and authenticated on the same Mac.

### 2. Get the skills

```bash
git clone https://github.com/tjdwls101010/Agentic-SNS.git
cd Agentic-SNS
```

The SNS skills bundle their own scripts and use the Python standard library at runtime. The SEC skill has a separate locked Python environment managed by `uv`; see [SEC setup](docs/usage.md#sec-edgar). Git is needed for the clone command.

Start `claude` or `codex` from this directory. Claude Code discovers `.claude/skills`; Codex discovers `.agents/skills`. This repository's `.agents` and `.codex` symlinks both point to `.claude`, so the two hosts share one source without copying skills. See the official [Claude Code](https://code.claude.com/docs/en/skills#where-skills-live) and [Codex](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) skill documentation. To use the skills from other working directories, see [individual skill installation](docs/usage.md#use-the-skills-in-other-projects).

### 3. Make your first request

In Claude Code or Codex, ask:

```text
Read @NASA's X profile using the twitter skill and give me its bio and profile link.
```

Expected: the agent invokes the Twitter CLI and answers with NASA's bio and `https://x.com/NASA`. If automatic skill selection does not occur, use `/twitter` in Claude Code or `$twitter` in Codex with the same request.

You can check the browser connection independently of the agent:

```bash
python3 .claude/skills/twitter/scripts/twitter.py about @NASA
```

A successful read prints the profile row shown above, preceded by request and budget information. Then try the longer exploration request at the top of this README. If a command fails, follow its `fix`; [connection and login troubleshooting](docs/usage.md#troubleshooting) covers the common cases.

## What your agent can explore

| Skill | Available reading and navigation |
|---|---|
| [sec](.claude/skills/sec/SKILL.md) | Company and filing lookup, filing/exhibit search, saved source documents, text and table navigation, and original image links; distinguishes filing dates, report periods, amendments and incomplete reads. |
| [twitter](.claude/skills/twitter/SKILL.md) | X feeds, posts and replies, profiles, search, followers/following, bookmarks/likes, trends, lists, and communities; continuation handles and query recovery. |
| [reddit](.claude/skills/reddit/SKILL.md) | Feeds, subreddits, posts, comment threads, users, search, subscriptions, saved/upvoted posts; cached comment continuation and resumable exports. |
| [facebook](.claude/skills/facebook/SKILL.md) | Feeds, posts, comments, profiles and About fields, search, and groups; paginated collection and query recovery. |
| [threads](.claude/skills/threads/SKILL.md) | Feeds, posts with parent chains and replies, profiles, search, relationships, liked/saved posts; reports reply coverage and local request budgets. |
| [naver-blog](.claude/skills/naver-blog/SKILL.md) | Search, blog profiles and categories, full posts, comments, neighbor feeds/lists, topic directories, and blogs of the month; reports extraction coverage and distinguishes observed counts from server totals. |

Each skill includes instructions for interpreting that platform's output. URLs and handles let the agent open the next relevant target; continuation commands let it read further when the question calls for it. `--json` supplies structured output, and `--out` supports larger local collections where available. [CLI reference and platform notes](docs/usage.md) cover the details.

“Explore freely” means choosing a path through the implemented read operations. It does not mean every page or every reply is accessible. For example, X does not expand “More replies” branches or article bodies; Threads post reads do not paginate further sibling replies; Naver's neighbor feed has no further page. Commands report their stopping conditions so the agent can describe what it actually read.

## Why CLI and text?

The agent works with named operations and reusable URLs instead of repeatedly interpreting visual controls. The CLI handles fetching, parsing, pagination, and output formatting; the agent decides what to investigate next. This is the basis for the intended efficiency benefit. There is no published benchmark comparing latency or token use with computer-use.

| Approach | How you use it | Tradeoff |
|---|---|---|
| Agentic SNS | Claude Code/Codex skills with CLI and text access to five platforms through Aside. | Requires Aside on a Mac and a supported read operation; no posting actions. |
| Screenshot/click computer-use | An agent navigates visible pages and controls. | Can reach UI workflows outside these CLIs; must interpret the page and operate its controls. |
| [twitter-cli](https://github.com/public-clis/twitter-cli) | X CLI with an agent skill; browser-cookie or environment-variable authentication. | Focuses on X and also supports write actions; supports browsers other than Aside. |
| [agent-twitter-client](https://github.com/JacobFV/agent-twitter-client) | JavaScript library for integrating X reads and writes into an application. | Requires application code and credential/cookie setup. |

The two X projects also work without an official Twitter API key. That is not a unique advantage of Agentic SNS. Comparisons reflect their READMEs checked September 8, 2026.

## Accounts, data, and maintenance

These scripts run with your coding agent's local execution permissions. They make network requests through Aside using the logged-in SNS session, then return content to your agent. What the agent reads can enter its model context and conversation history under your agent provider's settings.

Login credentials stay in Aside, but this is **not a promise that all session data stays in the browser**: the X skill caches a CSRF token and viewer identity locally. Other caches and exports can hold posts, profiles, private saved items, and continuation state. Keep them out of Git and delete task data when it is no longer needed. [Security and data handling](SECURITY.md) explains the boundary.

Requests count against your real SNS account. Platform rate limits, login challenges, and changes to website endpoints can interrupt reads. Check the reported budget and stop reason, and resolve a challenge in Aside before trying again.

Maintenance is **best effort**, without response or fix deadlines. The first X profile → posts → replies path was checked on macOS 26.5 (Apple Silicon), Python 3.12.8, and Aside CLI 1.26.810.1915 on September 8, 2026. This is a tested environment, not a guarantee for every platform or dependency version. The [verification workflow](.github/workflows/test.yml) defines the offline checks; live account checks are separate.

New SNS skills, features, bug fixes, and documentation improvements are welcome. See [Contributing](CONTRIBUTING.md) for the development setup and verification commands. Report sensitive issues through [GitHub private vulnerability reporting](https://github.com/tjdwls101010/Agentic-SNS/security/advisories/new).

## License

[MIT](LICENSE). The license covers this project's code and documentation; it does not grant rights to third-party content retrieved by the tools.
