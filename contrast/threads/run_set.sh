#!/bin/zsh
# usage: run_set.sh RUNPREFIX VARIANT t1 t2 …  — runs tasks in order; stops before a task whose reservation no longer fits today's ledger
cd "$(dirname "$0")"
work=${THREADS_WORK:-$HOME/.claude/projects/-Users-seongjin-Coding-Agentic-SNS/threads-rebuild}
prefix=$1 variant=$2; shift 2
for t in "$@"; do
  if ! python3 ledger.py check "$work/budget-ledger.tsv" tab_open --stage P6 > /dev/null; then
    echo "STOP before $t: $(python3 ledger.py check "$work/budget-ledger.tsv" tab_open --stage P6)"; break
  fi
  python3 contrast.py "$prefix-$t" "$variant" "$t" > "$work/runs/$prefix-$t.log" 2>&1
  echo "$t: $(tail -1 "$work/runs/$prefix-$t.log" | cut -c1-200)"
done
