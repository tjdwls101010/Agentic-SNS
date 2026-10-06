# Contributing

New SNS skills, features, bug fixes, and documentation improvements are welcome. Maintenance is best effort; there are no guaranteed response or merge times. For a large feature or a new platform, opening an issue first helps establish scope and avoid duplicate work.

Keep the project focused on reading and exploring SNS through the user's logged-in Aside browser, and structured market data and the SEC filing documents Yahoo lists through the invest skill. Posting, reactions, following actions, trade execution, credential collection, and bypassing account access controls are outside this project's scope. Do not include real-account captures, credentials, private posts, or personal datasets in issues or pull requests.

## Development setup

SNS runtime scripts require Python 3.11+ and Aside. invest uses Python 3.12 or 3.13 and the dependencies its `scripts/cli.py` header declares, which `uv` prepares. Offline checks do not need Aside or SNS accounts. CI uses Python 3.12 and Node.js 22; pytest and Ruff are development dependencies.

```bash
python3 -m venv .tmp/dev-venv
source .tmp/dev-venv/bin/activate
python -m pip install pytest==8.4.2 ruff
python -m pytest tests/ --ignore=tests/finviz --ignore=tests/invest
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

The [CI workflow](.github/workflows/test.yml) contains the corresponding commands for the SNS skills and a separate invest job. Naver Blog uses `naver-blog` for its skill directory and `naver_blog` for its test directory. Run the complete offline suite when shared behavior or documentation examples change.

For invest, build the test environment from the dependencies the script declares, so the suite runs against what `uv run` gives the skill:

```bash
bash -c 'set -euo pipefail; mkdir -p .tmp; uv export --quiet --script .claude/skills/invest/scripts/cli.py --no-hashes -o .tmp/invest-req.txt; uv run --isolated --no-project --python ">=3.12,<3.14" --with-requirements .tmp/invest-req.txt --with pytest==8.4.2 python -m pytest tests/invest tests/test_skill_layout.py'
uvx ruff check --config pyproject.toml .claude/skills/invest/scripts tests/invest scenarios/invest
```

These tests exercise the public CLI in isolated processes with controlled HTTP responses and the real yfinance parser; the Yahoo responses in `tests/invest/fixtures/yahoo/` were recorded by `scenarios/invest/record_yahoo.py` and carry their provenance, and `tests/invest/test_portability.py` also runs the skill through a real `uv run` from paths outside the repository. Keep fixture provenance explicit and do not substitute mocked library getters for transport coverage. Live Yahoo queries (`-m live`) and Claude/Codex skill-use scenarios are separate checks; a green offline suite does not establish either. `python3 scenarios/invest/run.py --help` describes the runner for the model scenarios in `tests/invest/model-scenarios.json`. The complete skill directory must run from another project without this repository's temporary source tree or system-installed yfinance. The skill keeps the results it saves in its own Git-ignored `data/` folder; the tests point `INVEST_DATA` elsewhere.

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
