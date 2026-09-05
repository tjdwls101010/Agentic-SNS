import json
import time

import pytest

from _errors import FacebookError


def test_checkpoint_persists_until_explicit_unblock(tmp_path, monkeypatch):
    monkeypatch.setenv('FACEBOOK_HOME', str(tmp_path))
    from _blocked import cache_dir, check_blocked, set_blocked, unblock
    assert cache_dir() == tmp_path
    assert check_blocked() is None
    set_blocked('checkpoint')
    with pytest.raises(FacebookError) as error:
        check_blocked()
    assert error.value.code == 5
    assert json.loads((tmp_path / 'blocked.json').read_text())['expires_at'] is None
    unblock()
    assert check_blocked() is None


def test_rate_limit_expires_but_corrupt_state_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('FACEBOOK_HOME', str(tmp_path))
    from _blocked import check_blocked, set_blocked
    set_blocked('rate_limit')
    record = json.loads((tmp_path / 'blocked.json').read_text())
    assert 1795 < record['expires_at'] - time.time() <= 1800
    record['expires_at'] = time.time() - 1
    (tmp_path / 'blocked.json').write_text(json.dumps(record))
    assert check_blocked() is None
    (tmp_path / 'blocked.json').write_text('{broken')
    with pytest.raises(FacebookError) as error:
        check_blocked()
    assert error.value.code == 5
