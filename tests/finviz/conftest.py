"""Exercise the real CLI as a subprocess; replace only the external curl process."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / ".claude/skills/finviz/scripts/finviz.py"

FAKE_CURL = """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if '--version' in args:
    print('curl 8.7.1 test'); sys.exit(0)
url = args[-1]
rows = json.loads(pathlib.Path(os.environ['FINVIZ_TEST_RESPONSES']).read_text())
entry = rows.get(url)
if entry is None:
    print('Unrecorded URL: ' + url, file=sys.stderr); sys.exit(7)
body = entry.get('body', '')
if not isinstance(body, str):
    body = json.dumps(body)
pathlib.Path(args[args.index('--output') + 1]).write_text(body)
headers = 'HTTP/1.1 ' + str(entry.get('status', 200)) + ' OK\\r\\n'
headers += ''.join(k + ': ' + v + '\\r\\n' for k, v in entry.get('headers', {}).items())
pathlib.Path(args[args.index('--dump-header') + 1]).write_text(headers + '\\r\\n')
print(entry.get('status', 200), end='')
sys.exit(entry.get('exit', 0))
"""


@pytest.fixture
def client(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    curl = binary / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    mapping = tmp_path / "responses.json"
    env = dict(
        os.environ,
        PATH=str(binary) + os.pathsep + os.environ["PATH"],
        FINVIZ_TEST_RESPONSES=str(mapping),
        FINVIZ_STORE=str(tmp_path / "store.sqlite3"),
    )

    class Client:
        responses = {}
        store = tmp_path / "store.sqlite3"
        home = tmp_path

        def add(self, url, body, **kwargs):
            self.responses[url] = dict(body=body, **kwargs)

        def raw(self, *args, code=None, extra_env=None):
            mapping.write_text(json.dumps(self.responses))
            proc = subprocess.run([sys.executable, str(CLI), *args], env=dict(env, **(extra_env or {})), cwd=tmp_path, text=True, capture_output=True)
            if code is not None:
                assert proc.returncode == code, proc.stdout + proc.stderr
            return proc

        def run(self, *args, code=0, extra_env=None):
            proc = self.raw(*args, code=code, extra_env=extra_env)
            return json.loads(proc.stdout)

        def one(self, *args, code=0, extra_env=None):
            doc = self.run(*args, code=code, extra_env=extra_env)
            assert len(doc["results"]) == 1, doc
            return doc["results"][0]

    return Client()
