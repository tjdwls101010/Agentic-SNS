import pytest

from tests.sns.support.browser import Browser


@pytest.fixture
def browser(tmp_path, data_dir):
    return Browser(tmp_path)
