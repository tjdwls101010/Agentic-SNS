"""classify is a pure function over (operation, envelope); its step order is what is tested."""
import json

import pytest

from naver_blog_skill._api import operation
from naver_blog_skill._errors import NaverBlogError
from naver_blog_skill._transport import classify, safe_location


def envelope(status=200, body='', url='https://m.blog.naver.com/api/x', location=None):
    return {'status': status, 'body': body, 'url': url, 'location': location}


def mblog(payload):
    return json.dumps(payload, ensure_ascii=False)


def section(payload):
    return ")]}',\n" + json.dumps(payload, ensure_ascii=False)


def failure(code, message='', status=200, op='blog_card', **kwargs):
    spec = operation(op)
    with pytest.raises(NaverBlogError) as caught:
        classify(spec, envelope(status=status, body=mblog(
            {'isSuccess': False, 'error': {'code': code, 'message': message}}), **kwargs))
    return caught.value


CARD = {'isSuccess': True, 'result': {'blogId': 'naverofficial', 'blogName': '네이버 블로그'}}


def test_a_healthy_card_is_returned_untouched():
    assert classify(operation('blog_card'), envelope(body=mblog(CARD)))['result']['blogId'] == 'naverofficial'


def test_the_section_hosts_xssi_prefix_is_stripped_before_parsing():
    payload = classify(operation('directories'), envelope(body=section({'result': [{'name': '문학·책'}]})))
    assert payload['result'][0]['name'] == '문학·책'


def test_only_http_429_becomes_a_block():
    error = None
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(status=429, body=''))
    error = caught.value
    assert error.code == 5 and error.error == 'rate_limit'


def test_a_comment_box_code_3300_is_a_contract_error_not_a_block():
    # 3300 also comes from a wrong pool or ticket, so treating it as a block would strand the account.
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('comments'), envelope(body=mblog(
            {'success': False, 'code': '3300', 'message': 'error'})))
    assert caught.value.code == 6 and caught.value.error == 'envelope_drift'


def test_a_hop_to_the_login_host_is_a_login_error_for_every_command():
    for op in ('blog_card', 'search_posts', 'buddy_feed'):
        with pytest.raises(NaverBlogError) as caught:
            classify(operation(op), envelope(status=302, location='https://nid.naver.com/nidlogin.login'))
        assert caught.value.code == 4, op


def test_a_logged_in_surface_reporting_notlogined_is_a_login_error():
    assert failure('notlogined', op='my_buddies').code == 4


def test_a_public_surface_reporting_notlogined_is_not_promoted_to_a_login_error():
    # Only the surfaces that genuinely need login may read a code this way.
    assert failure('notlogined', op='blog_card').code == 6


def test_a_missing_blog_is_reported_as_a_missing_target_in_both_shapes():
    assert failure('not_exist_blog', status=404).code == 9
    assert failure('blog_id_invalidate', status=400).code == 9


def test_someone_elses_buddy_list_is_owner_only():
    error = failure('not_blog_owner', status=403, op='my_buddies')
    assert error.code == 9 and error.error == 'owner_only'


def test_a_bare_403_is_the_referer_contract_not_a_missing_target():
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(status=403, body=''))
    assert caught.value.code == 6 and caught.value.error == 'envelope_drift'


def test_a_deleted_post_page_is_a_missing_target():
    body = 'location.href="/MobileErrorView.naver?errorType=noPost&blogId=x";'
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('post_html'), envelope(status=404, body=body))
    assert caught.value.code == 9 and caught.value.error == 'not_exist_post'


def test_an_unrecognized_error_page_names_its_type_rather_than_guessing():
    body = 'location.href="/MobileErrorView.naver?errorType=closedBlog";'
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('post_html'), envelope(status=404, body=body))
    assert caught.value.code == 6 and 'closedBlog' in caught.value.message


def test_a_rejected_parameter_is_an_argument_bug_the_cli_should_have_caught():
    error = failure('param_is_invalidate', op='post_list')
    assert error.code == 2 and 'skill' in error.fix


def test_a_shielded_query_is_a_restriction_and_never_an_empty_result():
    payload = {'isSuccess': True, 'result': {'list': [], 'blockedByBifrostShield': True}}
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('search_posts'), envelope(body=mblog(payload)))
    assert caught.value.code == 8 and caught.value.error == 'query_restricted'


def test_a_forbidden_query_control_is_also_a_restriction():
    payload = {'isSuccess': True, 'result': {'list': [], 'queryControlInfo': {'isAdult': False, 'isForbidden': True}}}
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('search_posts'), envelope(body=mblog(payload)))
    assert caught.value.code == 8


def test_the_ordinary_query_control_object_does_not_restrict_anything():
    payload = {'isSuccess': True, 'result': {'list': [], 'queryControlInfo': {'isAdult': False, 'isForbidden': False}}}
    assert classify(operation('search_posts'), envelope(body=mblog(payload)))['result']['list'] == []


def test_an_answer_about_a_different_target_is_a_contract_error():
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(body=mblog(CARD)),
                 expect={'result.blogId': 'someoneelse'})
    assert caught.value.code == 6 and caught.value.error == 'envelope_drift'


def test_a_wrong_leaf_type_is_a_contract_error():
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('search_posts'), envelope(body=mblog({'isSuccess': True, 'result': {'list': {}}})))
    assert caught.value.code == 6


def test_a_missing_success_flag_is_a_contract_error():
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(body=mblog({'result': {'blogId': 'x'}})))
    assert caught.value.code == 6


def test_truncated_json_is_transient_rather_than_a_shape_change():
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(body='{"isSuccess": true, "resu'))
    assert caught.value.code == 6 and caught.value.error == 'transient'


def test_ordinary_korean_prose_about_restrictions_does_not_restrict_the_command():
    # A post body may discuss 제한 or 차단; only the declared boolean fields decide.
    payload = {'isSuccess': True, 'result': {'list': [{'title': '이용이 제한되었습니다 안내'}]}}
    assert len(classify(operation('search_posts'), envelope(body=mblog(payload)))['result']['list']) == 1


def test_an_explicitly_empty_list_is_returned_and_not_raised():
    payload = {'isSuccess': True, 'result': {'list': []}}
    assert classify(operation('search_posts'), envelope(body=mblog(payload)))['result']['list'] == []


def test_a_server_error_is_transient_and_not_retried_here():
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_search'), envelope(status=500, body=''))
    assert caught.value.code == 6 and caught.value.error == 'transient'


def test_a_redirect_may_not_leave_the_allowed_hosts_or_paths():
    with pytest.raises(NaverBlogError):
        safe_location('blog.naver.com', '/naver_diary', 'https://example.com/NBlogTop.naver?blogId=x')
    with pytest.raises(NaverBlogError):
        safe_location('blog.naver.com', '/naver_diary', 'https://m.blog.naver.com/PostWrite.naver')
    url = safe_location('blog.naver.com', '/naver_diary', '/NBlogTop.naver?blogId=naverofficial')
    assert url.hostname == 'blog.naver.com' and 'blogId=naverofficial' in url.query
