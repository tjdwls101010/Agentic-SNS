"""Run the invest model scenarios: a fresh Claude, given only a copy of a skill, answers requests from tests/invest/model-scenarios.json.

Conditions: `invest` (this repository's skill) and `L` (the baseline: one SKILL.md of field notes, with the model calling yfinance 1.7.0 itself; .tmp/invest-plan/proto/skillL). Each run copies the skill to a new path containing a space, replaces ${CLAUDE_SKILL_DIR} as Claude Code does, gives the run its own INVEST_DATA and works in the run's own directory, which holds the copy, since restricted mode lets Read see only the working directory. The child runs `claude -p --safe-mode --restricted` with the chosen tools restored, so it is not sandboxed: run it from scratch locations only. The prompt points the model at SKILL.md, so frontmatter permissions and automatic skill choice are not exercised here.

Phases: `tune` runs freely; `eval` refuses to run while the skill, the bank or the judge rules have uncommitted changes, records their committed hashes and refuses to mix results made under different ones; `holdout` runs only held-out scenarios. `--pairs N` with `--cond invest,L` runs N pairs, alternating which condition goes first per scenario, and saves Yahoo's current session before and after each pair so a pair can be counted as run in the US regular session.

Writes <out>/meta.json, <out>/results.jsonl and <out>/runs/<id>-<cond>-p<pair>-<n>/{prompt.txt, stream.jsonl, answer.md, summary.json, results/, expected.json}. Judging is separate: scenarios/invest/judge.md and judge-schema.json.
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
SKILL = REPO / ".claude/skills/invest"
BASELINE = REPO / ".tmp/invest-plan/proto/skillL"
PINNED = ["--exclude-newer", "2026-09-13T13:10:00Z", "--with", "yfinance[repair]==1.7.0"]
FROZEN = [".claude/skills/invest", "tests/invest/model-scenarios.json", "scenarios/invest/judge.md", "scenarios/invest/judge-schema.json"]
WARM = threading.Lock()  # cold uv environments built in parallel stalled past the Bash tool's timeout
CLI_RUN = re.compile(r"\buv run\b[^\n;|&]*cli\.py")
KINDED = {"company", "financials", "analysts", "holders", "fund", "options", "screen", "market", "calendar"}  # commands whose second word is a kind


def copy_skill(cond, run):
    source = SKILL if cond == "invest" else BASELINE
    skill = run / "skill copy" / ("invest" if cond == "invest" else "yfinance")
    shutil.copytree(source, skill, ignore=shutil.ignore_patterns("__pycache__", "data", ".DS_Store", ".ruff_cache"))
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    (skill / "SKILL.md").write_text(text.replace("${CLAUDE_SKILL_DIR}", str(skill)), encoding="utf-8")
    with WARM:
        warm = (["uv", "run", "--quiet", str(skill / "scripts/cli.py"), "--help"] if cond == "invest"
                else ["uv", "run", "--quiet", "--no-project", "--with", "yfinance[repair]==1.7.0", "python", "-c", "import yfinance"])
        subprocess.run(warm, stdin=subprocess.DEVNULL, capture_output=True, timeout=900)
    return skill


# ---- what a run did, from its stream ------------------------------------------------------------------------------------

def invocations(command):
    """The cli.py runs inside one Bash command, which often chains several."""
    return [part for part in re.split(r"\s*(?:;|&&|\|\||\n|\|)\s*", command) if CLI_RUN.search(part)]


def parse_stream(stream):
    tools, results, final, answer = [], {}, {}, ""
    for line in stream.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        for block in (message.get("content") if isinstance(message, dict) and isinstance(message.get("content"), list) else []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tools.append((block["id"], block["name"], block.get("input") or {}))
            elif block.get("type") == "tool_result":
                body = block.get("content")
                text = body if isinstance(body, str) else "".join(c.get("text", "") for c in body or [] if isinstance(c, dict))
                results[block.get("tool_use_id")] = (text, bool(block.get("is_error")))
        if event.get("type") == "result":
            final, answer = event, event.get("result") or ""
    return tools, results, final, answer


def summarise(stream, skill_md_chars):
    tools, results, final, answer = parse_stream(stream)
    m = {"bash_calls": 0, "cli_runs": 0, "help_runs": 0, "help_chars": 0, "receipt_chars": 0, "mixed_chars": 0, "file_reads": 0, "file_read_chars": 0,
         "python_runs": 0, "python_chars": 0, "other_tool_calls": 0, "failed_calls": [], "commands": set(), "observed_at": set(), "signals": {}}
    total = 0
    for ident, name, given in tools:
        text, error = results.get(ident, ("", False))
        total += len(text)
        if error:
            m["failed_calls"].append(f"{name}: {str(given)[:200]} => {text[:200]}")
        if name == "Read":
            path = str(given.get("file_path", ""))
            if "/data/results/" in path or path.endswith(("result.csv", "result.json", "receipt.json")):
                m["file_reads"] += 1
                m["file_read_chars"] += len(text)
            continue
        if name != "Bash":
            m["other_tool_calls"] += 1
            continue
        m["bash_calls"] += 1
        command = given.get("command", "")
        runs = invocations(command)
        m["cli_runs"] += len(runs)
        helps = [r for r in runs if re.search(r"(?:^|\s)(?:--help|-h)(?:\s|$)", r)]
        m["help_runs"] += len(helps)
        for run in runs:
            if run not in helps:
                words = re.split(r"\s+", run.split("cli.py", 1)[1].lstrip("\"' ").strip())
                words = [w for w in words if w and not w.startswith("-") and not re.fullmatch(r"\d+", w)]
                m["commands"].add(" ".join(words[:2] if words and words[0] in KINDED else words[:1]) or "?")
        if runs and len(helps) == len(runs):
            m["help_chars"] += len(text)
        elif runs and not helps:
            m["receipt_chars"] += len(text)
        elif runs:
            m["mixed_chars"] += len(text)
        if re.search(r"\bpython", command) and not runs:
            m["python_runs"] += 1
            m["python_chars"] += len(text)
        m["observed_at"] |= set(re.findall(r'"observed_at":"([^"]+)"', text))
        for signal, pattern in SIGNALS.items():
            if re.search(pattern, text):
                m["signals"][signal] = True
        for code in re.findall(r'"error":\{"code":"([a-z_]+)"', text):
            m["signals"].setdefault("error_codes", set()).add(code)
    usage = final.get("usage") or {}
    m["commands"], m["observed_at"] = sorted(m["commands"]), sorted(m["observed_at"])
    if "error_codes" in m["signals"]:
        m["signals"]["error_codes"] = sorted(m["signals"]["error_codes"])
    m.update(read_chars_total=total + skill_md_chars, tokens={k: usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")},
             cost_usd=final.get("total_cost_usd"), seconds=round((final.get("duration_ms") or 0) / 1000, 1), permission_denials=final.get("permission_denials") or [])
    return m, answer


SIGNALS = {"trimmed": r'"trimmed":true', "preview": r'"first":\[', "provisional": r'"last_bar_status":"provisional"', "unknown_bar": r'"last_bar_status":"unknown"',
           "shortfall": r'"shortfall"', "source_units": r'"source_units"', "over_budget": r'"over_budget":true'}


# ---- expected answers from the run's own files ------------------------------------------------------------------------

def expected_for(scenario, data):
    """For a 2025 bulk scenario, the answer the run's own history file implies (scenarios/invest/expected.py --from-run)."""
    if scenario["id"] not in ("bulk-corr-2025", "bulk-dist-2025") or not data.is_dir():
        return None
    proc = subprocess.run(["uv", "run", "--quiet", "--no-project", *PINNED, "python", str(Path(__file__).with_name("expected.py")), "--from-run", str(data),
                           "--scenario", scenario["id"]], capture_output=True, text=True, timeout=600)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"error": proc.stderr[-500:]}


# ---- running -----------------------------------------------------------------------------------------------------------

def session_evidence():
    """Yahoo's current US regular session and whether now falls inside it, from yfinance's own history metadata for SPY."""
    code = ("import json, datetime as dt, yfinance as yf; m = yf.Ticker('SPY').get_history_metadata(); r = m['currentTradingPeriod']['regular']; "
            "now = dt.datetime.now(dt.timezone.utc); s, e = r['start'].to_pydatetime(), r['end'].to_pydatetime(); "
            "print(json.dumps({'now': now.isoformat(), 'start': s.isoformat(), 'end': e.isoformat(), 'regular': s <= now < e, 'timezone': m.get('exchangeTimezoneName')}))")
    proc = subprocess.run(["uv", "run", "--quiet", "--no-project", *PINNED, "python", "-c", code], capture_output=True, text=True, timeout=300)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"error": proc.stderr[-300:]}


def run_one(scenario, cond, pair, n, args, work, out):
    name = f"{scenario['id']}-{cond}-p{pair}-{n}"
    run = work / name
    shutil.rmtree(run, ignore_errors=True)
    run.mkdir(parents=True)
    skill = copy_skill(cond, run)
    hidden = skill / "scripts"
    prompt = f"{skill / 'SKILL.md'} 스킬을 읽고 그 지침대로 요청을 처리해줘. {hidden} 아래 소스 코드는 읽지 마.\n\n요청: {scenario['prompt']}"
    record = out / "runs" / name
    record.mkdir(parents=True, exist_ok=True)
    (record / "prompt.txt").write_text(prompt, encoding="utf-8")
    env = dict(os.environ, INVEST_DATA=str(run / "data"))
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(record / "stream.jsonl", "w", encoding="utf-8") as stream:
        proc = subprocess.run(["claude", "-p", "--safe-mode", "--restricted", "--permission-mode", "acceptEdits", "--tools", args.tools, "--allowedTools", args.tools,
                               "--model", args.model, "--output-format", "stream-json", "--verbose", prompt],
                              stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.PIPE, text=True, cwd=run, env=env, timeout=args.timeout)
    finished = dt.datetime.now(dt.timezone.utc).isoformat()
    summary, answer = summarise(record / "stream.jsonl", len((skill / "SKILL.md").read_text(encoding="utf-8")))
    (record / "answer.md").write_text(answer, encoding="utf-8")
    if (run / "data" / "results").is_dir():
        shutil.copytree(run / "data" / "results", record / "results", dirs_exist_ok=True)
    found = expected_for(scenario, run / "data")
    if found is not None:
        (record / "expected.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    row = {"id": scenario["id"], "kind": scenario["kind"], "cond": cond, "pair": pair, "n": n, "premise_wanted": scenario.get("premise"), "exit": proc.returncode,
           "stderr": proc.stderr[-300:], "started": started, "finished": finished, **summary}
    (record / "summary.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return row


def frozen_hashes(phase):
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *FROZEN], capture_output=True, text=True, cwd=REPO).stdout.strip()
    if phase == "eval" and dirty:
        raise SystemExit(f"eval refuses to run while these have uncommitted changes:\n{dirty}")
    return {path: subprocess.run(["git", "rev-parse", f"HEAD:{path}"], capture_output=True, text=True, cwd=REPO).stdout.strip() for path in FROZEN} | {"dirty": bool(dirty)}


def choose(bank, args):
    chosen = [s for s in bank if (not args.scenario or s["id"] in args.scenario) and (not args.kind or s["kind"] in args.kind)]
    if args.phase == "holdout":
        chosen = [s for s in chosen if s["heldout"]]
    elif not args.scenario:
        chosen = [s for s in chosen if not s["heldout"]]
    elif any(s["heldout"] for s in chosen):
        raise SystemExit("held-out scenarios run only with --phase holdout")
    return chosen


def main():
    parser = argparse.ArgumentParser(description="Run the invest model scenarios against copies of a skill; see the module docstring for isolation, phases and outputs.")
    parser.add_argument("--phase", choices=["tune", "eval", "holdout"], default="tune", help="tune runs freely; eval requires the skill, bank and judge rules committed; holdout runs held-out scenarios only.")
    parser.add_argument("--cond", default="invest", help="Comma-separated conditions: invest, L (default invest).")
    parser.add_argument("--pairs", type=int, default=1, help="Pairs to run; with two conditions, the first condition alternates per scenario (default 1).")
    parser.add_argument("--repeat", type=int, default=None, help="Runs per scenario and condition (default: the scenario's own repeat, else 1).")
    parser.add_argument("--scenario", action="append", help="Scenario id; repeatable. Default: every scenario the phase allows.")
    parser.add_argument("--kind", action="append", choices=["yahoo", "large", "failure", "rare-unit", "filing", "boundary"], help="Scenario kind; repeatable.")
    parser.add_argument("--tools", default="Bash,Read,Write,WebFetch,WebSearch", help="Tools the child gets, also passed to --allowedTools (default Bash,Read,Write,WebFetch,WebSearch; the Yahoo bank uses Bash,Read,Write).")
    parser.add_argument("--model", default="claude-opus-5-5", help="Model the child runs (default claude-opus-5-5).")
    parser.add_argument("--out", type=Path, help="Results directory (default .tmp/invest-scenarios/<date>/<phase>-<time>).")
    parser.add_argument("--workers", type=int, default=4, help="Scenarios at once (default 4); a pair's two runs of one scenario stay together.")
    parser.add_argument("--timeout", type=int, default=1800, help="Seconds one run may take (default 1800).")
    parser.add_argument("--summarise", type=Path, metavar="OUT", help="Run nothing: rebuild OUT/results.jsonl from the streams in OUT/runs.")
    args = parser.parse_args()
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    if args.summarise:
        rows = [json.loads((r / "summary.json").read_text()) for r in sorted((args.summarise / "runs").iterdir()) if (r / "summary.json").exists()]
        (args.summarise / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return
    conds = [c.strip() for c in args.cond.split(",")]
    unknown = sorted(set(conds) - {"invest", "L"}) + sorted(set(args.scenario or ()) - {s["id"] for s in bank})
    if unknown:
        parser.error(f"unknown conditions or scenarios {unknown}")
    if "L" in conds and not (BASELINE / "SKILL.md").exists():
        parser.error(f"the L baseline is missing: {BASELINE / 'SKILL.md'}")
    chosen = choose(bank, args)
    out = args.out or REPO / ".tmp/invest-scenarios" / dt.date.today().isoformat() / f"{args.phase}-{dt.datetime.now():%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    hashes = frozen_hashes(args.phase)
    meta_path = out / "meta.json"
    if meta_path.exists() and args.phase == "eval":
        earlier = json.loads(meta_path.read_text())
        if earlier.get("hashes") != hashes:
            raise SystemExit("this results directory holds eval runs made under different committed files; use a new --out")
    meta_path.write_text(json.dumps({"phase": args.phase, "conds": conds, "tools": args.tools, "model": args.model, "hashes": hashes,
                                     "scenarios": [s["id"] for s in chosen]}, ensure_ascii=False, indent=1), encoding="utf-8")
    work = Path(tempfile.mkdtemp(prefix="invest scenarios "))
    lock = threading.Lock()

    def job(task):
        scenario, pair, index = task
        order = conds if (pair + index) % 2 == 0 else list(reversed(conds))
        found = []
        for n in range(1, (args.repeat or scenario.get("repeat") or 1) + 1):
            for cond in order:
                row = run_one(scenario, cond, pair, n, args, work, out)
                with lock, open(out / "results.jsonl", "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(json.dumps({k: row[k] for k in ("id", "cond", "pair", "n", "exit", "cli_runs", "help_chars", "cost_usd")}, ensure_ascii=False), flush=True)
                found.append(row)
        return found

    for pair in range(1, args.pairs + 1):
        evidence = {"before": session_evidence()}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(job, [(s, pair, i) for i, s in enumerate(chosen)]))
        evidence["after"] = session_evidence()
        evidence["regular_session_pair"] = bool(evidence["before"].get("regular") and evidence["after"].get("regular"))
        (out / f"session-pair{pair}.json").write_text(json.dumps(evidence, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
