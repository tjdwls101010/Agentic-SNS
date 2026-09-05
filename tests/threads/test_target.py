import pytest

from threads_skill._target import parse_target
from threads_skill._errors import ThreadsError


@pytest.mark.parametrize('text', ['@alice', 'alice', '/@alice/',
    'https://threads.net/@alice?x=1', 'https://www.threads.com/@alice/replies',
    'threads.com/@alice/media', '/@alice/reposts'])
def test_user_handles_and_tab_urls_are_composable(text):
    target = parse_target(text, 'user')
    assert (target.kind, target.username, target.path) == ('user', 'alice', '/@alice')


@pytest.mark.parametrize('text', ['https://evil.test/@alice', '//evil.test/@alice',
    '/activity', '/settings', '/@alice/../../activity', 'https://www.threads.com:444/@alice',
    'https://name@www.threads.com/@alice', '/@alice/post/ABC'])
def test_user_command_rejects_other_surfaces(text):
    with pytest.raises(ThreadsError) as error:
        parse_target(text, 'user')
    assert error.value.code == 2


def test_short_post_code_uses_budgeted_redirect_and_numeric_user_stays_a_name():
    assert parse_target('ABC_12-z', 'post').path == '/t/ABC_12-z'
    assert parse_target('https://threads.net/@alice/post/ABC/?x=1', 'post').code == 'ABC'
    assert parse_target('123', 'user').username == '123'
