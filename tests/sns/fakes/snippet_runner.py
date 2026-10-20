"""Run a platform's composed page functions in the Node snippet harness (snippet_harness.mjs) and read what they did."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).with_name('snippet_harness.mjs')
needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


def run(tmp_path, model, calls, page, sources):
    """Run `calls` ({snippet, args, …} — see the harness) against the page model `model` with `page`'s keys; `sources`
    maps a snippet name to its composed page function text. Returns the harness's one JSON object."""
    prepared = []
    for index, call in enumerate(calls):
        call = dict(call)
        file = tmp_path / f'call{index}.js'
        file.write_text(sources[call.pop('snippet')])
        call['source'] = str(file)
        prepared.append(call)
    case = tmp_path / 'case.json'
    case.write_text(json.dumps({'model': model, 'calls': prepared, 'page': page}))
    done = subprocess.run(['node', str(HARNESS), str(case)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)
