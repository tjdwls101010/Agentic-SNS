# Judging invest model runs

You judge model runs produced by `scenarios/invest/run.py`. Read only; change nothing. Write `reason` and `summary` in Korean.

## Inputs

- The scenario bank, `tests/invest/model-scenarios.json`: each scenario's `prompt`, `expect` and `premise`.
- One folder per run, `<out>/runs/<id>-<cond>-p<pair>-<n>/`:
  - `answer.md`, the final answer;
  - `stream.jsonl`, every tool call and its full output: use it to check every number and claim the answer makes against what the tools actually returned in that run;
  - `results/<id>/` (condition `invest` only), the receipt.json and result file each CLI call saved: the data the run received;
  - `expected.json` (2025 bulk scenarios only), the answer the run's own history file implies, computed apart from the model;
  - `summary.json`, counts, signals and costs.
- Conditions: `invest` is the skill under test (a CLI that saves each result as a file and prints a receipt); `L` is a baseline SKILL.md of field notes with the model calling yfinance 1.7.0 itself. Judge both by the same `expect`.

## Verdicts

Give each run `pass`, `fail` or `inconclusive`, and say whether the scenario's `premise` held in that run.

1. **Run's own data.** Judge numbers against what that run received (its tool outputs, its result files), never against today's market or another run. A value is right when it is the correct reading of the run's own data; a plausibility range in `expect` marked Auxiliary is a secondary signal, not the test.
2. **Substance over path.** `expect` describes what the answer must preserve: the unit and scale, the currency, when a value was true (a provisional last bar is not a close), what a list covers, which conditions the returned rows confirm, which targets failed and with what code. How the run got there (which commands, how many calls) is not a criterion, except where `expect` says the computation must use every row: then check in `stream.jsonl` that the code that computed the answer read the whole file (its targets, period and row count match the file), not a preview or `head()`.
3. **Failures.** A failed or not-attempted target must be named with the reason the run's data gave; leaving it out, filling it with zero or giving a reason the data did not give is a fail.
4. **Independent expectations.** For a 2025 bulk scenario, compare the answer with `expected.json` (the entry whose receipt the run's computation used) within the tolerance `expect` states.
5. **Inconclusive** only when the run could not test the expectation for an external reason the stream shows: a permission denial, an environment failure, Yahoo returning nothing for the asked data, or a premise that `expect` says makes the run inconclusive (an options run outside the regular session). Not for a wrong answer.
6. **Semantic errors.** List every claim in the answer that contradicts the run's data or misreads a unit, a time, a currency, a coverage or a failure, even when the verdict is pass. These are compared across conditions and across repeated runs.

## Consistency groups

When a scenario was run several times (`n` 1–3), also report for the group whether the runs kept the same request scope (targets, period, adjustment), the same units and scale, the same failure reports and the same timing and coverage statements, each run's numbers matching its own data. Different numbers between runs are expected when the data moved.

## Output

Follow `judge-schema.json`. `evidence` names the answer line and the tool output (stream line or result file) that decided the verdict. `summary` gives pass counts per condition, every scenario where the conditions differ and why, and any failure mode seen in one condition only.
