import pytest

from _errors import FacebookError
from _resolve import normalize_profile, normalize_group, normalize_post


def test_profile_handles_normalize_to_same_target():
    assert normalize_profile('42') == 'https://www.facebook.com/profile.php?id=42'
    assert normalize_profile('https://m.facebook.com/profile.php?foo=x&id=42') == normalize_profile('42')
    assert normalize_profile('zuck') == normalize_profile('https://www.facebook.com/zuck/')


@pytest.mark.parametrize('value', ['https://facebook.com.evil.test/x', 'https://evil@facebook.com/x', 'file:///x', 'https://facebook.com:443/x', 'https://facebook.com/../x'])
def test_untrusted_urls_are_rejected(value):
    for normalize in (normalize_profile, normalize_group, normalize_post):
        with pytest.raises(FacebookError) as error:
            normalize(value)
        assert error.value.code == 2


def test_people_profile_and_about_links_keep_the_profile_target():
    assert normalize_profile('https://www.facebook.com/people/Synthetic/123/') == normalize_profile('123')
    assert normalize_profile('https://www.facebook.com/zuck/about') == normalize_profile('zuck')


@pytest.mark.parametrize('value', ['groups', 'search', 'https://www.facebook.com/watch/'])
def test_nonprofile_surfaces_are_not_profile_handles(value):
    with pytest.raises(FacebookError):
        normalize_profile(value)
