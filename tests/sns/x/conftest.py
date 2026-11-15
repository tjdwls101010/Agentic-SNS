import time

import pytest

from tests.sns.support.browser import Browser


@pytest.fixture
def browser(tmp_path, data_dir):
    return Browser(tmp_path)


@pytest.fixture(autouse=True)
def fresh_rate_window(request):
    """A module's RATE headers (x-rate-limit-*) describe a window that resets RATE_AHEAD seconds from now (default 900)
    — set here before each test, because a reset computed at import has passed by the time a long suite reaches the
    test, and an expired window is no longer a fact the guard keeps."""
    rate = getattr(request.module, 'RATE', None)
    if isinstance(rate, dict) and 'x-rate-limit-reset' in rate:
        rate['x-rate-limit-reset'] = str(int(time.time()) + getattr(request.module, 'RATE_AHEAD', 900))
