import json
import os
import time

import pytest

from .helpers import FAKE_ASIDE, PROCESS_DOUBLES


@pytest.fixture
def fake_env(tmp_path):
    home = tmp_path / 'cache'
    home.mkdir()
    (home / 'session.json').write_text(json.dumps({'ct0': 'synthetic', 'viewer_id': '100', 'read_at': time.time()}))
    (home / 'txid.json').write_text(json.dumps({'key_bytes': [1] * 48, 'animation_key': 'synthetic',
                                                'fetched_at': time.time()}))
    (tmp_path / 'script.json').write_text('[]')
    return {
        **{key: value for key, value in os.environ.items() if not key.startswith(('TWITTER_', 'FAKE_'))},
        'TWITTER_HOME': str(home),
        'TWITTER_ASIDE_BIN': str(FAKE_ASIDE),
        'TWITTER_FAKE_LOG': str(tmp_path / 'calls.ndjson'),
        'TWITTER_FAKE_TRACE': str(tmp_path / 'trace.ndjson'),
        'TWITTER_FAKE_SCRIPT': str(tmp_path / 'script.json'),
        'PYTHONPATH': str(PROCESS_DOUBLES),
        'FAKE_NO_SLEEP': '1',
        'TZ': 'UTC',
    }
