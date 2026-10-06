"""Run the yfinance model scenarios: a fresh Claude, given only a copy of the skill, answers each request from tests/yfinance/model-scenarios.json.

Each run copies the skill (without its saved observations) to a new path containing a space, replaces ${CLAUDE_SKILL_DIR} in the copy's SKILL.md with that path as Claude Code does when it loads a skill, gives the run its own store, works in the run's own directory (which holds the copy, since restricted mode lets Read see only the working directory), and builds the copy's uv environment before the run starts. The child runs `claude -p --safe-mode --restricted` with Bash restored, so it is not sandboxed: run it only from scratch locations, never inside the repository. Judging an answer against its `expect` is left to the reader of the results.

Writes <out>/results.jsonl (one line per run: CLI runs counted inside chained Bash commands, discovery runs before the first data run, failed tool calls with their output, premise signals, permission denials, tokens, cost, time) and <out>/runs/<id>-<n>/{prompt.txt, stream.jsonl, answer.md}.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

REPO = Path(__file__).resolve().parents[2]
BANK = REPO / "tests/invest/model-scenarios.json"
BUDGET = "이 환경의 출력 한도는 작다 — 모든 CLI 호출에 `--max-chars 3000`을 붙이고 이 값을 올리지 않는다."
WARM = threading.Lock()  # cold uv environments built in parallel stalled past the Bash tool's timeout


def copy_skill(source, run):
    skill = run / "skill copy" / "invest"
    shutil.copytree(source, skill, ignore=shutil.ignore_patterns("__pycache__", "data"))
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    (skill / "SKILL.md").write_text(text.replace("${CLAUDE_SKILL_DIR}", str(skill)), encoding="utf-8")
    return skill


INVOCATION = re.compile(r"\buv run\b.*(?:cli\.py|\"?\$\{?\w+)")  # the CLI by path, or through a shell variable holding it


def invocations(command):
    """The CLI runs inside one Bash command, which often chains several (`… --help; … schema prices`) or names the CLI through a variable."""
    return [part for part in re.split(r"\s*(?:;|&&|\|\||\n|\|)\s*", command) if INVOCATION.search(part)]


def is_discovery(invocation):
    """A run that reads the CLI's own description rather than data: --help, or schema while it exists."""
    return bool(re.search(r"(?:^|\s)(?:--help|schema)(?:\s|$)", invocation))


def summarise(stream):
    """What the run did, from its stream: CLI calls, how many came before the first data call, failures, the premise signals and the cost."""
    calls, outputs, answer, final = {}, {}, "", {}
    for line in stream.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                calls[block["id"]] = block["input"].get("command", "")
            elif block.get("type") == "tool_result":
                body = block.get("content")
                text = body if isinstance(body, str) else "".join(c.get("text", "") for c in body or [] if isinstance(c, dict))
                outputs[block.get("tool_use_id")] = {"text": text, "error": bool(block.get("is_error"))}
        if event.get("type") == "result":
            final, answer = event, event.get("result") or ""
    cli = [(calls[i], outputs.get(i, {})) for i in calls if invocations(calls[i])]
    runs = [part for command, _ in cli for part in invocations(command)]
    first_data = next((n for n, part in enumerate(runs) if not is_discovery(part)), len(runs))
    texts = [o.get("text", "") for _, o in cli]
    usage = final.get("usage") or {}
    return {
        "cli_calls": len(cli),
        "cli_invocations": len(runs),
        "discovery_invocations": first_data,
        "failed_calls": [c[:240] + " => " + o.get("text", "")[:240] for c, o in cli if o.get("error")],
        "premise": {
            "partial_budget": any('"truncated_by":"budget"' in t for t in texts),
            "too_large_with_id": any('"code":"too_large"' in t and re.search(r'"id":"[0-9a-f]{16}"', t) for t in texts),
            "too_large_multi": any('"code":"too_large"' in t and "saved separately" in t for t in texts),
            "shortfall_warning": any("usable entries arrived of the" in t for t in texts),
        },
        "max_chars_raised": any(int(m) > 3000 for c, _ in cli for m in re.findall(r"--max-chars (\d+)", c)),
        "other_bash": [c[:160] for c in calls.values() if not invocations(c)][:10],
        "permission_denials": final.get("permission_denials") or [],
        "tokens": {k: usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")},
        "cost_usd": final.get("total_cost_usd"),
        "seconds": round((final.get("duration_ms") or 0) / 1000, 1),
    }, answer


def run_one(scenario, n, args, work, out):
    run = work / f"{scenario['id']}-{n}"
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    skill = copy_skill(args.skill_dir, run)
    with WARM:
        subprocess.run(["uv", "run", "--quiet", str(skill / "scripts/cli.py"), "--help"], stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
    budget = BUDGET + "\n\n" if scenario.get("budget") else ""
    prompt = (f"{skill / 'SKILL.md'} 스킬을 읽고 그 지침대로 요청을 처리해줘. {skill / 'scripts'} 아래 소스 코드는 읽지 마.\n\n"
              f"{budget}요청: {scenario['prompt']}")
    record = out / "runs" / f"{scenario['id']}-{n}"
    record.mkdir(parents=True, exist_ok=True)
    (record / "prompt.txt").write_text(prompt, encoding="utf-8")
    env = dict(os.environ, INVEST_DATA=str(run / "data"))
    with open(record / "stream.jsonl", "w", encoding="utf-8") as stream:
        proc = subprocess.run(["claude", "-p", "--safe-mode", "--restricted", "--permission-mode", "acceptEdits", "--tools", "Bash,Read,Write",
                               "--allowedTools", "Bash", "--model", args.model, "--output-format", "stream-json", "--verbose", prompt],
                              stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.PIPE, text=True, cwd=run, env=env, timeout=args.timeout)
    return result(scenario, n, record, proc.returncode, proc.stderr[-300:])


def result(scenario, n, record, code, stderr):
    summary, answer = summarise(record / "stream.jsonl")
    (record / "answer.md").write_text(answer, encoding="utf-8")
    return {"id": scenario["id"], "n": n, "budget": bool(scenario.get("budget")), "premise_wanted": scenario.get("premise"),
            "exit": code, "stderr": stderr, **summary}


def main():
    parser = argparse.ArgumentParser(description="Run yfinance model scenarios against a copy of the skill; see the module docstring for isolation and outputs.")
    parser.add_argument("--skill-dir", type=Path, default=REPO / ".claude/skills/invest", help="Skill folder to copy (default: this repository's).")
    parser.add_argument("--scenario", action="append", help="Scenario id to run; repeatable. Default: every scenario in the bank.")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per scenario (default 1).")
    parser.add_argument("--model", default="claude-opus-5-5", help="Model the child Claude runs (default claude-opus-5-5).")
    parser.add_argument("--out", type=Path, help="Results directory (default .tmp/yf-scenarios/<date>/<label> in this repository).")
    parser.add_argument("--label", default="run", help="Name of this set of runs inside the dated results directory (default run).")
    parser.add_argument("--work", type=Path, help="Where the skill copies and stores go (default a new temporary directory whose name has a space).")
    parser.add_argument("--workers", type=int, default=4, help="Runs at once (default 4).")
    parser.add_argument("--timeout", type=int, default=1500, help="Seconds one run may take (default 1500).")
    parser.add_argument("--summarise", action="store_true", help="Run nothing: rebuild --out's results.jsonl from the streams already in its runs/ folder.")
    args = parser.parse_args()
    bank = {s["id"]: s for s in json.loads(BANK.read_text(encoding="utf-8"))}
    unknown = sorted(set(args.scenario or ()) - set(bank))
    if unknown:
        parser.error(f"unknown scenario ids {unknown}")
    chosen = [bank[i] for i in args.scenario] if args.scenario else list(bank.values())
    out = args.out or REPO / ".tmp/yf-scenarios" / dt.date.today().isoformat() / args.label
    out.mkdir(parents=True, exist_ok=True)
    if args.summarise:
        rows = []
        for record in sorted((out / "runs").iterdir()):
            sid, n = record.name.rsplit("-", 1)
            rows.append(result(bank[sid], int(n), record, None, ""))
        (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return
    work = args.work or Path(tempfile.mkdtemp(prefix="yf scenarios "))
    lock = threading.Lock()

    def job(pair):
        found = run_one(*pair, args, work, out)
        with lock, open(out / "results.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(found, ensure_ascii=False) + "\n")
        print(json.dumps({k: found[k] for k in ("id", "n", "exit", "cli_invocations", "discovery_invocations", "premise", "cost_usd")}, ensure_ascii=False), flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(job, [(s, n) for s in chosen for n in range(1, args.repeat + 1)]))


if __name__ == "__main__":
    main()
