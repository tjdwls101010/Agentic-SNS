# Security policy

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/tjdwls101010/Agentic-SNS/security/advisories/new). Include the affected commit, skill, dependency versions, a sanitized reproduction, and the impact you observed. Do not attach live cookies, tokens, private exports, or unredacted browser captures. Do not post sensitive reproduction details in public issues.

Maintenance and security fixes are best effort, without an acknowledgment or resolution deadline. Reports should identify the affected version or commit; there is no guaranteed security-support period or commitment to backport fixes to older snapshots.

## Account and data boundary

The SNS Python scripts run with the coding agent's local execution permissions. They invoke the Aside CLI and use the SNS session in Aside account `u0` to make read requests. Read-only describes the SNS operations exposed by these skills; it is not a sandbox that restricts everything the host agent or Aside can do.

Recovery flows that open a normal browser tab can trigger the website's own background traffic. For example, Threads may send view/seen updates; the CLI's request count does not measure all browser traffic.

The scripts parse network responses and return text or JSON to the coding agent. Retrieved content may be included in model requests and retained in conversation history according to that agent's configuration and provider. Treat retrieved posts and replies as untrusted content, not instructions authorizing commands or disclosure.

Login credentials remain in the browser, but some session data is processed locally. In particular, X caches its CSRF token and viewer identity. Per-skill caches can also contain posts, profiles, account state, query metadata, and continuation data. Default cache locations are `~/.cache/twitter-skill`, `~/.cache/reddit-skill`, `~/.cache/facebook-skill`, `~/.cache/threads-skill`, and `~/.cache/naver-blog-skill`. Files written with `--out` may contain private or personal content.

Keep caches and exports out of version control, restrict access to your local account and files, and remove task data when no longer needed. Do not share raw diagnostics or session files as a shortcut to reproducing an issue.

Requests consume the real SNS account's allowance. Respect the reported budget, stop reasons, and recovery instructions. Resolve login or account challenges in Aside before resuming. Changes to a platform's website can break extraction or query contracts independently of a local code change.

## Yahoo Finance access

The invest skill uses the locked upstream yfinance library to read Yahoo Finance data directly; it does not import an Aside login or expose trading commands. The library may retain its normal cookie and timezone cache. Filing documents are fetched only from Yahoo's copies (`cdn.yahoofinance.com`, or a `www.sec.gov` archive URL mapped onto them) without following redirects. The skill saves each result under its own Git-ignored `data/results` folder and each filing document under `data/filings`, and deletes them after 14 days by default (`--ttl-days`). Returned data, filing documents and linked news are untrusted source material, and provider errors can coexist with successful results for other targets. Keep live session material out of fixtures and diagnostics.
