"""The reddit fetch page function (web/fetch.js) run for real under node with a recording fetch: what it sends for a
path, a query and a share link, and what it refuses in the browser (fixture aside_output.json snippet.cases). The two
large-body cases of that fixture belong to the core program (tests/sns/core/test_aside.py)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.sns.reddit.scene import FIXTURES

SNIPPET = Path(__file__).resolve().parents[3] / '.claude/skills/sns/scripts/sns/reddit/web/fetch.js'
CASES = [c for c in json.loads((FIXTURES / 'aside_output.json').read_text())['snippet']['cases']
         if c['name'] not in ('large-body-chunked', 'surrogate-pair-not-split')]
RUNNER = '''
const sent = [];
globalThis.fetch = async (url, init) => {
  sent.push({url, method: init.method, credentials: init.credentials, redirect: init.redirect,
             accept: (init.headers || {}).accept});
  return {status: 200, url, text: async () => '{}', headers: {get: () => null}};
};
const fn = (%s);
fn(%s).then(() => console.log(JSON.stringify({sent})), e => console.log(JSON.stringify({sent, threw: String(e)})));
'''


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_the_fetch_snippet_sends_what_the_fixture_says(case, tmp_path):
    script = tmp_path / 'run.js'
    script.write_text(RUNNER % (SNIPPET.read_text(), json.dumps(case['args'])))
    done = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    if case.get('throws'):
        assert 'threw' in result and result['sent'] == [], result
        return
    [sent] = result['sent']
    for key, value in case['sends'].items():
        assert sent[key] == value, (key, sent)
