"""x_web target rules (fixtures/targets.json): what a typed target normalizes to, or that it is refused before any
request with an argument error."""
import pytest

from conftest import fixture
from twitter import x_web
from twitter.errors import TwitterError

TARGETS = fixture('targets.json')
PARSERS = {'account': x_web.parse_account, 'post': x_web.parse_post, 'list': x_web.parse_list,
           'community': x_web.parse_community, 'space': x_web.parse_space}
FIELDS = {'handle': 'handle', 'post_id': 'post_id', 'list_id': 'list_id', 'community_id': 'community_id',
          'space_id': 'space_id'}


def cases():
    for section, default in (('hosts', None), ('accounts', 'account'), ('posts', 'post'), ('places', None)):
        for case in TARGETS[section]['cases']:
            yield pytest.param(case.get('kind') or default, case, id=f'{section}:{case["input"]}')


@pytest.mark.parametrize('kind, case', list(cases()))
def test_target(kind, case):
    parse = PARSERS[kind]
    if 'refused' in case:
        with pytest.raises(TwitterError) as error:
            parse(case['input'])
        assert error.value.code == 2 and error.value.fix
        return
    target = parse(case['input'])
    for key, value in case['expected'].items():
        assert getattr(target, FIELDS[key]) == value


def test_a_post_target_names_its_own_url():
    target = x_web.parse_post('https://twitter.com/Example_User/status/1850000000000000001?s=46')
    assert target.url == 'https://x.com/Example_User/status/1850000000000000001'
    assert x_web.parse_post('1850000000000000004').url == 'https://x.com/i/web/status/1850000000000000004'


def test_an_account_target_names_its_profile_url_and_the_tab_its_url_pointed_at():
    target = x_web.parse_account('https://x.com/example_user/with_replies')
    assert target.url == 'https://x.com/example_user' and target.tab == 'replies'
    assert x_web.parse_account('@example_user').tab is None


@pytest.mark.parametrize('value', ['line\nbreak', 'tab\there', '@ex\x00ample'])
def test_control_characters_are_refused(value):
    with pytest.raises(TwitterError) as error:
        x_web.parse_account(value)
    assert error.value.code == 2
