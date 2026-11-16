"""Grading through `claude` skill Sonnet workers (plan P8, decision A18): one worker per blinded copy, each answering
grader.md's JSON (grader.schema.json), turned into the lines aggregate.py counts.

  python3 grade.py tasks COPIES_DIR > TASKS.jsonl
      one worker task per copy (blind.py's OUT); then, from the repository:
      uv run "<claude skill>/scripts/cli.py" batch --group NAME --tasks-file TASKS.jsonl --profile read-only \
          --model sonnet --schema contrast/sns/grader.schema.json
  python3 grade.py collect RESULT GRADER >> GRADES.jsonl
      RESULT is what `result --group NAME --wait` printed; each copy's eight row verdicts become
      {"id", "row", "verdict", "grader"} lines. A member that gave no usable answer is named on stderr and left out
      (grade it again), never guessed.

The copies hold other people's posts: COPIES_DIR, RESULT and GRADES belong outside the repository, like the runs.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROWS = [str(n) for n in range(1, 9)]
VERDICTS = ('defect', 'ok', 'n.a.')
LABEL = 'g-'


def tasks(copies):
    """One worker task per blinded copy, labelled with the copy's id."""
    lines = []
    for copy in sorted(Path(copies).glob('*.md')):
        prompt = (f'Grade one blinded run. Read {HERE}/grader.md and follow it exactly. The rubric is {HERE}/rubric.md; '
                  f'platform notes are in {HERE}/rubric/ (x.md, threads.md, reddit.md, facebook.md, naver-blog.md) — '
                  f'read the notes of every platform the run used. The run is {copy}. Read it in full (in parts if it '
                  f'is long). Do not open any other file in {copy.parent}. Answer with the JSON object grader.md '
                  f'describes.')
        lines.append(json.dumps({'prompt': prompt, 'label': LABEL + copy.stem}, ensure_ascii=False))
    return lines


def collect(text, grader):
    """(grade lines, the copy ids without a usable answer) from a `result --group` print."""
    found, missing = [], []
    for header, body in re.findall(r'^--- \[\d+:([^\]]+)\][^\n]*\n(.*?)(?=^--- \[|\Z)', text, re.M | re.S):
        if not header.startswith(LABEL):
            continue
        copy = header[len(LABEL):]
        try:
            rows = json.JSONDecoder().raw_decode(body.strip())[0]['rows']  # what follows the answer is not ours
            given = {row: rows[row]['verdict'] for row in ROWS}
        except (ValueError, KeyError, TypeError):
            missing.append(copy)
            continue
        if any(verdict not in VERDICTS for verdict in given.values()):
            missing.append(copy)
            continue
        found += [{'id': copy, 'row': row, 'verdict': verdict, 'grader': grader} for row, verdict in given.items()]
    return found, missing


def main(argv):
    if argv[:1] == ['tasks'] and len(argv) == 2:
        print('\n'.join(tasks(argv[1])))
        return 0
    if argv[:1] == ['collect'] and len(argv) == 3:
        found, missing = collect(Path(argv[1]).read_text(), argv[2])
        print('\n'.join(json.dumps(line) for line in found))
        if missing:
            print('no usable answer for: ' + ' '.join(missing), file=sys.stderr)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
