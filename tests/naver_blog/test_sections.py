"""A composite command's failed section is still an answer beside the ones that worked."""
import pytest

from naver_blog_skill._errors import NaverBlogError
from naver_blog_skill._sections import Sections


def failing(code, error='transient'):
    def produce():
        raise NaverBlogError(code, 'it failed', error=error)
    return produce


def test_all_sections_succeeding_is_a_plain_success():
    sections = Sections()
    sections.add('a', lambda: [1])
    sections.add('b', lambda: [2])
    assert sections.exit_code() == 0
    assert [entry['ok'] for entry in sections.as_list()] == [True, True]


def test_a_secondary_failure_keeps_the_sections_that_worked_and_reports_partial():
    sections = Sections()
    sections.add('card', lambda: [1])
    sections.add('notices', failing(6))
    assert sections.exit_code() == 8
    entries = sections.as_list()
    assert entries[0]['data'] == [1]
    assert entries[1]['error']['code'] == 6 and entries[1]['error']['fix']


def test_an_empty_section_is_not_a_failure():
    sections = Sections()
    sections.add('notices', lambda: [])
    assert sections.exit_code() == 0


def test_a_primary_failure_is_the_commands_failure():
    sections = Sections()
    with pytest.raises(NaverBlogError) as caught:
        sections.add('card', failing(9, 'not_exist_blog'), primary=True)
    assert caught.value.code == 9


def test_the_worst_of_several_failures_decides_the_exit_code():
    sections = Sections()
    sections.add('a', lambda: [1])
    sections.add('b', failing(8, 'partial'))
    sections.add('c', failing(9, 'owner_only'))
    sections.add('d', failing(6))
    # Gone-or-private is something the caller must act on, so it is not flattened to "partial".
    assert sections.exit_code() == 9


def test_a_shape_change_or_a_budget_stop_really_is_partial():
    for code in (6, 8):
        sections = Sections()
        sections.add('a', lambda: [1])
        sections.add('b', failing(code))
        assert sections.exit_code() == 8


def test_a_login_wall_outranks_a_gone_target():
    sections = Sections()
    sections.add('a', failing(9, 'not_exist_blog'))
    sections.add('b', failing(4, 'login'))
    assert sections.exit_code() == 4


def test_a_blocked_or_logged_out_account_is_reported_as_itself_not_as_partial():
    # The next command will fail the same way, so calling it "partial" would mislead.
    for code in (4, 5):
        sections = Sections()
        sections.add('a', lambda: [1])
        sections.add('b', failing(code))
        assert sections.exit_code() == code
