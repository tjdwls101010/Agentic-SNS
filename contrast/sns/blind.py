"""Blind copies of contrast runs for graders (plan P8): the task, every tool call with its whole output, and the final
answer — without the run's name, its arm, its model or the SKILL.md body it was given, so a grader cannot tell which
arm a run belongs to.

  python3 blind.py OUT KEY RUN [RUN …]      (RUN: a directory under $SNS_WORK/runs/, or its name)

Writes OUT/<id>.md for each run, in a shuffled order, and KEY (a file outside OUT: graders get OUT alone) mapping ids
back to runs. Removed from what a grader reads: the run's name, model and arm, its paths, and every sentence of the
SKILL.md body it was given (as it was given, from the run's summary): any run of six or more of its words, wherever it
is quoted, except what every arm shares (arms/A.md). A paraphrase or a sentence shorter than that can still remain,
which is why graders are told not to guess; text of a post that happens to repeat six words of the body is removed
too. The copies hold other people's posts: OUT belongs outside the
repository, like the runs.
"""
import json
import random
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ledger import work_dir  # noqa: E402

REPO = HERE.parents[1]

REMOVED = '[the skill text this run was given is removed for grading]'


def transcript(events_path):
    """(tool calls in order as {tool, input, output}, the final answer) from a run's stream-json events."""
    calls, outputs, final = [], {}, None
    for line in Path(events_path).read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'assistant':
            for block in event.get('message', {}).get('content', []):
                if block.get('type') == 'tool_use':
                    calls.append({'id': block['id'], 'tool': block['name'], 'input': block['input']})
        elif event.get('type') == 'user':
            for block in event.get('message', {}).get('content', []):
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    content = block.get('content')
                    outputs[block.get('tool_use_id')] = content if isinstance(content, str) else ''.join(
                        c.get('text', '') for c in content or [] if isinstance(c, dict))
        elif event.get('type') == 'result':
            final = event.get('result')
    return [{'tool': c['tool'], 'input': c['input'], 'output': outputs.get(c['id'], '')} for c in calls], final


WINDOW = 6  # a run of this many words of the body, quoted anywhere, is taken as the body


def _words(text):
    """(normalized word, start, end) for each whitespace-separated word of `text`; a grep prefix in front of a word
    (`12:`, `SKILL.md:12:`) is not part of it."""
    found = []
    for m in re.finditer(r'\S+', text):
        word = re.sub(r'^(?:\S*?:)?\d+[:-]', '', m.group())
        found.append((re.sub(r'[^\w<>/.$-]', '', word.lower()).strip('.'), m.start(), m.end()))
    return found


SHARED = HERE / 'arms' / 'A.md'  # every arm carries this paragraph: it names no arm, and the CLI's own text overlaps it


def strip_body(text, body):
    """Replace every run of WINDOW or more consecutive words that also stand together in the body (as the run saw
    it: the CLI path shown as <skill>) — a whole sentence or part of one, in an output or in the answer."""
    if not body:
        return text
    def grams_of(source):
        seen = [w for w, _, _ in _words(source.replace('${CLAUDE_SKILL_DIR}', '<skill>')) if w]
        return {tuple(seen[i:i + WINDOW]) for i in range(len(seen) - WINDOW + 1)}
    grams = grams_of(body) - (grams_of(SHARED.read_text()) if SHARED.exists() else set())
    words = [w for w in _words(text) if w[0]]
    covered = [False] * len(words)
    for i in range(len(words) - WINDOW + 1):
        if tuple(w for w, _, _ in words[i:i + WINDOW]) in grams:
            for j in range(i, i + WINDOW):
                covered[j] = True
    spans, i = [], 0
    while i < len(words):
        if covered[i]:
            j = i
            while j + 1 < len(words) and covered[j + 1]:
                j += 1
            spans.append((words[i][1], words[j][2]))
            i = j + 1
        else:
            i += 1
    for start, end in reversed(spans):
        text = text[:start] + '[skill text removed]' + text[end:]
    return text


def scrub(text, summary, body):
    """Remove what names the run's cell: its run name, model and arm, the run's own paths, the body's words."""
    text = text or ''
    text = re.sub(r'/[^\s"\']*/sns-contrast-[^/\s"\']+/skill', '<skill>', text)
    text = re.sub(r'/[^\s"\']*/sns-contrast-[^/\s"\']+', '<run>', text)
    text = strip_body(text, body)
    for word in filter(None, (summary.get('run'), summary.get('model'))):
        text = text.replace(word, '[hidden]')
    arm = summary.get('arm') or ''
    if len(arm) >= 3:  # a one- or two-letter arm (A, F) would erase ordinary words; the child never sees it anyway
        text = text.replace(arm, '[hidden]')
    return text


def render(run_dir):
    run_dir = Path(run_dir)
    summary = json.loads((run_dir / 'summary.json').read_text())
    body = summary.get('body_text') or ''  # the body as the run was given it, not the file as it is now
    calls, final = transcript(run_dir / 'events.jsonl')
    parts = [f"# Task\n\n{summary['task']}\n"]
    for number, call in enumerate(calls, 1):
        given = call['input'].get('command') or call['input'].get('file_path') or json.dumps(call['input'])
        output = call['output']
        if call['tool'] == 'Read' and str(given).endswith('SKILL.md'):
            output = REMOVED
        parts.append(f"## Call {number}: {call['tool']}\n\n```\n{scrub(str(given), summary, body)}\n```\n\n"
                     f"Output:\n\n```\n{scrub(output, summary, body)}\n```\n")
    parts.append(f"# Final answer\n\n{scrub(final, summary, body)}\n")
    return '\n'.join(parts)


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    out, key_path = Path(argv[0]).resolve(), Path(argv[1]).resolve()
    runs = [Path(r) if Path(r).is_dir() else work_dir() / 'runs' / r for r in argv[2:]]
    for place in (out, key_path):
        if place == REPO or REPO in place.parents:
            sys.exit(f'{place} is inside the repository; the copies hold other people\'s posts')
    if out == key_path.parent or out in key_path.parents:
        sys.exit('the key must not sit inside OUT: graders get OUT')
    out.mkdir(parents=True, exist_ok=True)
    random.shuffle(runs)
    key = {}
    for run in runs:
        ident = secrets.token_hex(4)
        (out / f'{ident}.md').write_text(render(run))
        key[ident] = run.name
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps(key, indent=1))
    print(json.dumps({'copies': len(key), 'out': str(out), 'key': str(key_path)}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
