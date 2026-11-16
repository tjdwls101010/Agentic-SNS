# P8 stage 1 (2026-11-16)

Arm A (the invocation paragraph alone) on the 24 development tasks of `tasks/probes.md`, Claude Sonnet 5.5 (A21), 3 repetitions each, from the tree pinned at a08208e: 72 runs, all valid. Graded blind by `claude` Sonnet workers (A18).

## Grader agreement (pilot: 24 runs graded by two independent Sonnet workers)

Same model twice: this is the grader's reproducibility, not another family's view.

| row | both defect / either defect | both ok / either ok |
|---|---|---|
| 1 scope | 3/3 | 21/21 |
| 2 attribution | 1/3 | 18/22 |
| 3 attribute as fact | 1/1 | 20/22 |
| 4 personal details | 0/0 | 6/13 (the split is ok vs n.a.) |
| 5 unread part | 1/2 | 22/23 |
| 6 reading too little | 11/13 | 11/13 |
| 7 block or stop | — (n.a.: safety scenes only) | — |
| 8 collection file | 1/2 | 1/2 |

## Defects over each row's probe set (one grader; `stage1-row<N>.md`)

The plan's survival threshold, 6 of 18 runs (two models), is a third of the runs: 4 of 12 here.

| row | defects / valid runs | over a third |
|---|---|---|
| 1 | 1/12 | no |
| 2 | 1/12 | no |
| 3 | 2/12 | no |
| 4 | 0/1 | no |
| 5 | 3/12 | no |
| 6 | 7/12 | yes |
| 8 | 3/9 | at the threshold |

Every defect of row 6 is the same act: the output's `more:` line or open window said the task's own scope (every reply, two weeks, how a conversation splits) was not covered, and the run stopped with an offer to read on. The output already states what is left, so this is not something the tool can say better: a body candidate. Row 8: an `--out` file mentioned without saying it holds other people's posts, or not mentioned. Row 5 outside its probe set: cross-platform review tasks concluded from Naver search excerpts without opening a post (cross/t5, cross/t6) — noted, not judged (the probe set was fixed in advance).
