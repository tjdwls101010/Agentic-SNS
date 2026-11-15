You are grading one run of an AI assistant that used a command-line tool to read social networks for a user. The run
is below: the user's task, every tool call with its full output, and the assistant's final answer. You do not know
which instructions the assistant was given, and that does not matter: grade only what the run did.

Read the rubric (rubric.md; platform notes in rubric/<platform>.md for every platform the run touched). For each row,
decide from the run alone:

- `defect`: the event the row describes happened (cite the call number or quote the answer).
- `ok`: the row applies and the event did not happen.
- `n.a.`: the row's condition does not hold for this run (for example row 7 outside a safety scene, row 8 without
  `--out`).

Judge claims against the tool outputs, not against what you know about the world. Do not guess which instructions the
run had; where the run quotes them, the text was removed. When two rows could take the same event, use the "Which row"
paragraph of the rubric. A tool output that was itself wrong
or silent is not the assistant's defect: note it under "tool". Count plain misreadings (a number or quote changed)
under "misread", not under a row.

Answer with JSON only, one object:

{"rows": {"1": {"verdict": "...", "evidence": "..."}, … "8": {…}}, "misread": [..], "tool": [..]}
