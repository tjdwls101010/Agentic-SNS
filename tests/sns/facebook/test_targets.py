"""What a typed target is, decided without any request (fixtures/targets.json), the id a fetched page names, the About
screen's path, and which links are Facebook's for the other platforms' refusals."""
import pytest

from sns.errors import SnsError
from sns.facebook import web
from tests.sns.facebook.data import fixture

TARGETS = fixture('targets.json')
NORMALIZE = {'profile': web.normalize_profile, 'group': web.normalize_group, 'post': web.normalize_post}


@pytest.mark.parametrize('case', [pytest.param(c, id=c['command'] + ' ' + c['input']) for c in TARGETS['targets']])
def test_target_forms(case):
    if case.get('refused'):
        with pytest.raises(SnsError) as error:
            NORMALIZE[case['command']](case['input'])
        assert error.value.kind == 'argument' and error.value.fix
    else:
        assert NORMALIZE[case['command']](case['input']) == case['normalized']


@pytest.mark.parametrize('case', [pytest.param(c, id=c['url']) for c in TARGETS['url_checks']])
def test_only_facebook_urls_without_credentials_or_ports_are_accepted(case):
    """The fixture's url_checks (appendix C: no consumer before): the target normalizer's gate, with a profile
    path appended where the URL has none to judge."""
    try:
        web.normalize_profile(case['url'])
        accepted = True
    except SnsError:
        accepted = False
    assert accepted is case['allowed'], case.get('why')


@pytest.mark.parametrize('case', TARGETS['resolve'])
def test_ids_found_in_pages(case):
    assert web.find_id(case['kind'], case['html']) == case['id']


def test_direct_ids_need_no_page():
    group = next(c for c in TARGETS['targets'] if c.get('direct_id'))
    assert web.normalize_group(group['input']).split('/')[4] == group['direct_id']


@pytest.mark.parametrize('url,path', [
    ('https://www.facebook.com/some.person', '/some.person/about'),
    ('https://www.facebook.com/groups/example/', '/groups/example/about'),
    ('https://www.facebook.com/profile.php?id=1000123', '/profile.php?id=1000123&sk=about')])
def test_the_about_screen_of_a_numeric_profile_is_a_query_not_a_path_under_it(url, path):
    """Appendix C: the numeric profile's About path was profile.php?id=N/about, which is no screen at all."""
    assert web.about_path(url) == path


@pytest.mark.parametrize('url,command', [
    ('https://www.facebook.com/some.person', 'profile'),
    ('https://m.facebook.com/profile.php?id=7', 'profile'),
    ('https://www.facebook.com/people/Some-One/1000456/', 'profile'),
    ('https://www.facebook.com/groups/example.group/', 'group'),
    ('https://www.facebook.com/some.page/posts/pfbid02abc', 'post'),
    ('https://www.facebook.com/groups/g1/permalink/123/', 'post'),
    ('https://www.facebook.com/story.php?story_fbid=1&id=2', 'post'),
    # Facebook's, though not read: the command named is the one whose error explains why
    ('https://www.facebook.com/share/p/1AbCdEf/', 'post'),
    ('https://www.facebook.com/reel/123456', 'post'),
    ('https://www.facebook.com/watch/?v=123', 'post'),
    ('https://fb.watch/abc123/', 'post')])
def test_a_facebook_link_names_the_command_that_reads_it(url, command):
    assert web.locate(url) == (command, url)


@pytest.mark.parametrize('url', ['https://x.com/jack/status/20', 'https://www.facebookish.com/x', 'not a url', '',
                                 'https://www.facebook.com/', 'https://www.facebook.com/settings'])
def test_other_links_are_not_facebooks(url):
    assert web.locate(url) is None


def test_the_refused_forms_say_what_to_pass():
    for command, value in (('post', 'https://www.facebook.com/some.page'), ('post', 'https://www.facebook.com/reel/1'),
                           ('profile', 'groups'), ('group', 'https://www.facebook.com/some.page/posts/1')):
        with pytest.raises(SnsError) as error:
            NORMALIZE[command](value)
        assert error.value.kind == 'argument' and error.value.fix
