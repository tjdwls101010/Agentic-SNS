# Contributing

New SNS skills, features, bug fixes, and documentation improvements are welcome. Maintenance is best effort; there are no guaranteed response or merge times. For a large feature or a new platform, opening an issue first helps establish scope and avoid duplicate work.

Keep the project focused on reading and exploring SNS through the user's logged-in Aside browser and original EDGAR company filings through the SEC skill's identified HTTPS transport. Posting, reactions, following actions, credential collection, and bypassing account access controls are outside this project's scope. Do not include real-account captures, credentials, private posts, or personal datasets in issues or pull requests.

## Development setup

SNS runtime scripts require Python 3.11+ and Aside. The SEC skill uses Python 3.11+ and its `uv.lock` environment. Offline checks do not need Aside or SNS accounts. CI uses Python 3.12 and Node.js 22; pytest and Ruff are development dependencies.

```bash
python3 -m venv .tmp/dev-venv
source .tmp/dev-venv/bin/activate
python -m pip install pytest==8.4.2 ruff
python -m pytest tests/ --ignore=tests/sec
```

The default pytest configuration excludes tests marked `live`. This command does not read your logged-in accounts.

## Verification

For a changed skill, run its Python tests, JavaScript snippet tests, fixture privacy check, and lint checks. For example, for X:

```bash
python -m pytest tests/twitter/
node --test tests/twitter/js/*.js
python tests/twitter/tools/check_fixtures_pii.py
ruff check --config pyproject.toml .claude/skills/twitter/scripts tests/twitter
```

The [CI workflow](.github/workflows/test.yml) contains the corresponding commands for the SNS skills and a separate locked SEC job. Naver Blog uses `naver-blog` for its skill directory and `naver_blog` for its test directory. Run the complete offline suite when shared behavior or documentation examples change.

For the SEC skill, run its locked development environment:

```bash
uv run --isolated --frozen --group dev --project .claude/skills/sec python -m pytest tests/sec
uv run --isolated --frozen --group dev --project .claude/skills/sec ruff check --config pyproject.toml .claude/skills/sec/Scripts tests/sec
```

Its fixture provenance distinguishes recorded public SEC responses from constructed edge cases. Live checks require the local requester identity; never record that identity in a fixture or diagnostic. The SEC skill's whole directory, including `Scripts/`, `pyproject.toml` and `uv.lock`, must work independently of this repository.

For bugs, add a failing reproduction at the public behavior boundary before changing the implementation. Keep assertions focused on observable results, failures, privacy, and continuation behavior rather than private helper structure. For documentation-only changes, execute the changed commands, check links and output claims, and avoid tests that merely repeat the prose.

Live checks are opt-in, use your real account, and can spend its request budget. Review the chosen suite and its guard before running it. For example:

```bash
python -m pytest -m live tests/reddit/live/
```

The Reddit, Threads, and Naver Blog live suites include a cumulative 30-request guard. A passing offline suite does not establish that live endpoints or a logged-in account still work. Record which live commands you actually ran, and never claim unrun checks passed.

## Pull requests

Keep changes focused on the requested behavior and match the existing style. Each skill must remain independently runnable with its own `scripts/` directory; preserve input validation, account protection, bounded requests, and explicit partial-result reporting. New fixtures must use synthetic or sanitized data and pass the privacy check.

Use a title such as `fix: 댓글 이어읽기 오류 수정`. Commit messages and PR text use Korean; code and identifiers retain their original language. In the PR body, use `## 무엇을 바꿨나`, `## 왜`, `## 영향` when relevant, and `## 검증`. Include the exact commands and results you ran, along with any checks not run.

Contributions are distributed under the project's [MIT license](LICENSE). Include the provenance and required notices for any third-party material you add. Report vulnerabilities through the [private security channel](SECURITY.md), not a public issue.
