"""Counts of graded contrast runs (plan P8): per rubric row, per model and arm, defects over valid runs — the numbers
results/<round>.md keeps (numbers only: no names, posts or answers).

  python3 aggregate.py ROUND GRADES.jsonl [--cells CELLS.jsonl] [--key KEY.json …] [--tasks PLATFORM/TASK …]

GRADES.jsonl: one line per graded copy and row, {"id": <blind id>, "row": <rubric row>, "verdict": "defect" | "ok" |
"n.a.", "grader": <name>} — or {"run": <run name>, …} when a grade was made without blinding. --key maps blind ids back
to runs (blind.py writes it). CELLS.jsonl ($SNS_WORK/cells.jsonl by default) says which runs are valid, and each run's
model, arm and task (a run stopped by a block signal is never valid). --tasks limits the count to a task group (a
probe set agreed before the runs). A verdict counts when every grader (--graders, default codex and claude) gave the
same one, or a line with grader "settled" decides it; a disagreement or a missing grade is counted apart and not used.
A task with fewer than --minimum valid runs (default 3) for a model and arm — counted from the run index, so a task
whose runs were all invalid shows too — is left out for that model and arm and listed.

Writes contrast/sns/results/ROUND.md and prints the same table as JSON.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ledger import work_dir  # noqa: E402


def load_lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def verdicts(grades, keys, graders):
    """{(run, row): verdict} for the cells every grader agreed on or a settled line decides; and the cells that are not
    decided (graders disagree, or one has not graded)."""
    by = defaultdict(dict)
    for grade in grades:
        run = grade.get('run') or keys.get(grade.get('id'))
        if run is None:
            raise SystemExit(f'grade for unknown copy {grade.get("id")}')
        by[(run, str(grade['row']))][grade.get('grader', 'grader')] = grade['verdict']
    decided, open_cells = {}, []
    for cell, given in by.items():
        if 'settled' in given:
            decided[cell] = given['settled']
        elif set(graders) <= set(given) and len({given[g] for g in graders}) == 1:
            decided[cell] = given[graders[0]]
        else:
            open_cells.append(cell)
    return decided, open_cells


def task_of(cell):
    """A run's task as probes.md names it: platform/task (task files are per platform, so t3 alone is ambiguous); a
    cell recorded without a platform keeps its bare name."""
    return f"{cell['platform']}/{cell['task_name']}" if cell.get('platform') else cell.get('task_name')


def table(decided, cells, tasks=None, minimum=3):
    """({row: {model: {arm: {"defects": d, "valid": v}}}}, the (model, arm, task) left out) over the valid runs of the
    chosen tasks. A task counts in a cell (model, arm) only with at least `minimum` valid runs there, counted from the
    run index whatever the grades say; a row's denominator is then the runs whose verdict for it was decided and
    applicable (n.a. is not a run of that row)."""
    info = {c['run']: c for c in cells if c.get('valid') and not c.get('block_signal')}
    chosen = [c for c in cells if not tasks or task_of(c) in tasks]
    valid_runs = defaultdict(int)
    for c in chosen:
        valid_runs[(c['model'], c['arm'], task_of(c))] += c['run'] in info
    short = sorted(cell for cell, count in valid_runs.items() if count < minimum)
    counts = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'defects': 0, 'valid': 0})))
    for (run, row), verdict in decided.items():
        cell = info.get(run)
        if cell is None or verdict == 'n.a.' or (tasks and task_of(cell) not in tasks):
            continue
        if (cell['model'], cell['arm'], task_of(cell)) in short:
            continue
        slot = counts[row][cell['model']][cell['arm']]
        slot['valid'] += 1
        slot['defects'] += verdict == 'defect'
    return json.loads(json.dumps(counts)), short


def markdown(round_name, counts, split, tasks, short=()):
    lines = [f'# Contrast round {round_name}', '',
             f'Task group: {", ".join(tasks) if tasks else "all graded tasks"}. Cells: defects / valid runs. '
             f'Unsettled grader disagreements: {len(split)}. '
             f'Left out for too few valid runs: {len(short)}.', '']
    arms = sorted({arm for row in counts.values() for model in row.values() for arm in model})
    models = sorted({model for row in counts.values() for model in row})
    lines.append('| row | model | ' + ' | '.join(arms) + ' |')
    lines.append('|---|---|' + '---|' * len(arms))
    for row in sorted(counts, key=lambda r: (len(r), r)):
        for model in models:
            given = counts[row].get(model, {})
            lines.append(f'| {row} | {model} | ' + ' | '.join(
                f'{given[a]["defects"]}/{given[a]["valid"]}' if a in given else '—' for a in arms) + ' |')
    if short:
        lines += ['', 'Left out (model, arm, task): ' + '; '.join(', '.join(s) for s in short)]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('round')
    parser.add_argument('grades')
    parser.add_argument('--cells', default=None)
    parser.add_argument('--key', action='append', default=[])
    parser.add_argument('--tasks', nargs='*')
    parser.add_argument('--graders', nargs='+', default=['codex', 'claude'])
    parser.add_argument('--minimum', type=int, default=3)
    args = parser.parse_args(argv)
    keys = {}
    for path in args.key:
        keys.update(json.loads(Path(path).read_text()))
    decided, split = verdicts(load_lines(args.grades), keys, args.graders)
    cells = load_lines(args.cells or work_dir() / 'cells.jsonl')
    counts, short = table(decided, cells, args.tasks, args.minimum)
    out = HERE / 'results' / f'{args.round}.md'
    out.parent.mkdir(exist_ok=True)
    out.write_text(markdown(args.round, counts, split, args.tasks, short))
    print(json.dumps({'round': args.round, 'counts': counts, 'disagreements': len(split), 'left_out': short,
                      'out': str(out)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
