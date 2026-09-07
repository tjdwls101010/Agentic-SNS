"""Naver spells one post seven ways; all of them must land on the same handle."""
import pytest

from naver_blog_skill._errors import NaverBlogError
from naver_blog_skill._target import parse_target

POST_FORMS = [
    'https://blog.naver.com/naverofficial/224400531915',
    'https://m.blog.naver.com/naverofficial/224400531915',
    'blog.naver.com/naverofficial/224400531915',
    'https://blog.naver.com/naverofficial/224400531915/',
    'https://m.blog.naver.com/PostView.naver?blogId=naverofficial&logNo=224400531915',
    'https://blog.naver.com/PostView.naver?blogId=naverofficial&logNo=224400531915&redirect=Dlog',
    'https://blog.naver.com/naverofficial?Redirect=Log&logNo=224400531915',
    'naverofficial/224400531915',
]


@pytest.mark.parametrize('value', POST_FORMS)
def test_every_post_url_form_resolves_to_the_same_handle(value):
    target = parse_target(value, 'post')
    assert target.kind == 'post'
    assert target.handle == 'naverofficial/224400531915'
    assert target.url == 'https://blog.naver.com/naverofficial/224400531915'


BLOG_FORMS = [
    'naverofficial',
    'https://blog.naver.com/naverofficial',
    'https://m.blog.naver.com/naverofficial/',
    'https://blog.naver.com/NBlogTop.naver?blogId=naverofficial',
    'https://blog.naver.com/PostList.naver?blogId=naverofficial&from=postList',
]


@pytest.mark.parametrize('value', BLOG_FORMS)
def test_every_blog_url_form_resolves_to_the_blog_id(value):
    assert parse_target(value, 'blog').handle == 'naverofficial'


def test_a_post_url_read_as_a_blog_keeps_only_the_blog():
    # Widening a post request into a whole-blog request silently would be worse than refusing.
    target = parse_target('https://blog.naver.com/naverofficial/224400531915', 'blog')
    assert target.kind == 'blog' and target.log_no == ''


def test_a_numeric_blog_id_is_a_real_blog_id():
    assert parse_target('12345678', 'blog').blog_id == '12345678'


def test_post_numbers_are_not_forced_to_one_length():
    # Log numbers have varied in length across Naver's history; a fixed width would reject real posts.
    for log_no in ('220108382928', '2240053', '90019283746501'):
        assert parse_target(f'someone/{log_no}', 'post').log_no == log_no


def test_a_url_that_names_a_category_carries_it():
    target = parse_target('https://blog.naver.com/PostList.naver?blogId=naverofficial&categoryNo=108', 'blog')
    assert target.category_no == '108'


def test_a_blog_command_needs_no_post_but_a_post_command_does():
    with pytest.raises(NaverBlogError) as caught:
        parse_target('naverofficial', 'post')
    assert caught.value.code == 2 and 'id/logNo' in caught.value.message


def test_a_short_link_says_what_to_do_instead_of_guessing():
    with pytest.raises(NaverBlogError) as caught:
        parse_target('https://naver.me/xAbC12', 'post')
    assert caught.value.code == 2 and 'naver.me' in caught.value.message


def test_routes_outside_the_reading_surface_are_refused():
    for value in ('https://blog.naver.com/naverofficial/224400531915/edit',
                  'https://cafe.naver.com/something',
                  'https://blog.naver.com/a/b/c/d'):
        with pytest.raises(NaverBlogError) as caught:
            parse_target(value, 'blog')
        assert caught.value.code == 2, value


def test_a_post_number_that_is_not_digits_is_refused():
    with pytest.raises(NaverBlogError):
        parse_target('https://m.blog.naver.com/PostView.naver?blogId=x&logNo=abc', 'post')


def test_a_valid_blog_id_in_the_query_does_not_license_a_forbidden_route():
    # The query is not permission to visit a route this reader cannot read.
    for value in ('https://blog.naver.com/PostWrite.naver?blogId=x&logNo=123',
                  'https://m.blog.naver.com/BuddyList.naver?blogId=x',
                  'https://blog.naver.com/a/123/edit?blogId=b&logNo=456'):
        with pytest.raises(NaverBlogError) as caught:
            parse_target(value, 'blog')
        assert caught.value.code == 2, value


def test_a_url_naming_two_different_blogs_is_refused_rather_than_guessed():
    with pytest.raises(NaverBlogError) as caught:
        parse_target('https://blog.naver.com/someone?blogId=someoneelse', 'blog')
    assert caught.value.code == 2 and 'two different' in caught.value.message


def test_a_category_that_is_not_a_number_is_refused():
    with pytest.raises(NaverBlogError) as caught:
        parse_target('https://blog.naver.com/PostList.naver?blogId=x&categoryNo=all', 'blog')
    assert caught.value.code == 2 and 'digits' in caught.value.message


def test_a_very_long_post_number_is_accepted_because_naver_never_fixed_the_width():
    assert parse_target('someone/' + '9' * 30, 'post').log_no == '9' * 30
