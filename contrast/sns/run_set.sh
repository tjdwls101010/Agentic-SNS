#!/bin/zsh
# usage: run_set.sh RUNPREFIX PLATFORM ARM BODY MODEL t1 t2 …
# Runs one arm's tasks in order (one platform's runs share an account lock, so never in parallel), each with the
# default repetitions; stops after a run a block signal stopped or that ended in an error (a usage limit: wait, then
# rerun the rest under new run names).
cd "$(dirname "$0")"
work=$(python3 -c "import contrast; print(contrast.work_dir())")
prefix=$1 platform=$2 arm=$3 body=$4 model=$5; shift 5
mkdir -p "$work/runs"
for t in "$@"; do
  python3 contrast.py "$prefix-$arm-$t" "$platform" "$t" --body "$body" --arm "$arm" --model "$model" \
    > "$work/runs/$prefix-$arm-$t.log" 2>&1
  last=$(tail -1 "$work/runs/$prefix-$arm-$t.log")
  echo "$t: $(print -r -- "$last" | cut -c1-200)"
  if [[ "$last" == *'"block_signal": "'* || "$last" == *'"error": "'* || "$last" != '{'* ]]; then
    echo "STOP after $t"; break
  fi
done
