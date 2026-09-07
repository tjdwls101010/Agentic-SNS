"""Live reads spend the real account, so the whole suite shares one hard request ceiling."""
import json
from pathlib import Path

import pytest

BUDGET_FILE = Path(__file__).parent / '.live-requests'
CEILING = 30


@pytest.fixture(scope='session')
def live_budget():
    """Count every live request across the session and refuse to exceed the planned ceiling."""
    spent = {'n': 0}

    def spend(count, what):
        spent['n'] += count
        if spent['n'] > CEILING:
            pytest.fail(f'Live request ceiling {CEILING} exceeded at "{what}" ({spent["n"]}).')
        BUDGET_FILE.write_text(json.dumps(spent))
        return count
    yield spend
