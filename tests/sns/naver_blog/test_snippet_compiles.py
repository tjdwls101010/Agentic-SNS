"""The fake Aside never runs JavaScript, so a page function that breaks the program (a trailing // comment swallowing the
rest of the call it is pasted into) passes every other test; node checks the real text of fetch.js inside the program.
(Running it against a fake fetch is the shared snippet harness, left for after X.)"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sns.aside import PROGRAM
from sns.naver_blog import web

FETCH = Path(web.__file__).with_name('fetch.js').read_text(encoding='utf-8')


@pytest.mark.skipif(not shutil.which('node'), reason='node is not installed')
def test_fetch_js_compiles_inside_the_program(tmp_path):
    program = ('const ASIDE = ' + json.dumps({'op': 'run'}) + ';\nconst ARGS = {};\n'
               + PROGRAM.replace('PAGE_FUNCTION', FETCH.rstrip()))   # the worst case: nothing after it
    path = tmp_path / 'program.mjs'
    path.write_text(program)
    done = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-500:]


def test_fetch_js_has_its_marker_on_a_line_of_its_own_and_no_trailing_comment():
    lines = FETCH.rstrip('\n').split('\n')
    assert lines[0] == '// sns-snippet: naver_blog.fetch' and lines[-1] == '}'
