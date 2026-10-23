#!/bin/zsh
# usage: run_set.sh RUNPREFIX PLATFORM VARIANT MODEL t1 t2 …
# Runs tasks in order (one platform's runs share an account lock, so never in parallel); stops after a run a block
# signal stopped.
cd "$(dirname "$0")"
work=$(python3 -c "import contrast; print(contrast.work_dir())")
prefix=$1 platform=$2 variant=$3 model=$4; shift 4
mkdir -p "$work/runs"
for t in "$@"; do
  python3 contrast.py "$prefix-$t" "$platform" "$variant" "$t" --model "$model" > "$work/runs/$prefix-$t.log" 2>&1
  last=$(tail -1 "$work/runs/$prefix-$t.log")
  echo "$t: $(print -r -- "$last" | cut -c1-200)"
  if [[ "$last" == *'"watch": "block_stop"'* || "$last" != '{'* ]]; then
    echo "STOP after $t"; break
  fi
done
