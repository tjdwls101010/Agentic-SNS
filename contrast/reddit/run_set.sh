#!/bin/zsh
# usage: run_set.sh RUNPREFIX VARIANT t1 t2 …  — runs tasks in order; stops after a run that a block signal stopped
cd "$(dirname "$0")"
work=$(python3 -c "import contrast; print(contrast.WORK)")
prefix=$1 variant=$2; shift 2
for t in "$@"; do
  python3 contrast.py "$prefix-$t" "$variant" "$t" > "$work/runs/$prefix-$t.log" 2>&1
  last=$(tail -1 "$work/runs/$prefix-$t.log")
  echo "$t: $(print -r -- "$last" | cut -c1-200)"
  if [[ "$last" == *'"watch": "block_stop"'* || "$last" != '{'* ]]; then
    echo "STOP after $t"; break
  fi
done
