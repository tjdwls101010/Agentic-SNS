import json
from pathlib import Path
import subprocess
import sys

import pytest

TOOLS = Path(__file__).parent / 'tools'


@pytest.mark.parametrize('payload', [
    {'body': json.dumps({'csrf_token': 'not-a-synthetic-secret'})},
    {'user': {'username': 'real_person', 'pk': '123456789012'}},
    {'caption': {'text': 'A personal message with a real name'}},
    {'url': 'https://scontent.cdninstagram.com/picture?signature=secret'},
])
def test_fixture_gate_rejects_identifying_values_even_inside_envelope_strings(tmp_path, payload):
    path = tmp_path / 'bad.ndjson'
    path.write_text(json.dumps(payload) + '\n')
    result = subprocess.run([sys.executable, str(TOOLS / 'check_fixtures_pii.py'), str(path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'not-a-synthetic-secret' not in result.stdout + result.stderr


def test_derivation_replaces_values_preserves_relationships_and_refuses_overwrite(tmp_path):
    source, dest = tmp_path / 'source.ndjson', tmp_path / 'derived.ndjson'
    source.write_text(json.dumps({'pk': '999999999', 'caption': {'text': 'Private original'},
                                 'child': {'pk': '888888888', 'reply_to_id': '999999999'}}) + '\n')
    command = [sys.executable, str(TOOLS / 'derive_fixture.py'), str(source), str(dest)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    body = json.loads(dest.read_text())
    assert body['pk'] == body['child']['reply_to_id'] == '1001'
    assert 'Private original' not in dest.read_text()
    assert subprocess.run(command, capture_output=True).returncode == 2
