"""classify is a pure function over (operation, envelope); its step order is what is tested."""
import json

import pytest

from naver_blog_skill._api import operation
from naver_blog_skill._errors import NaverBlogError
from naver_blog_skill._transport import Transport, classify, safe_location


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


# When two signals could each decide the answer, the earlier step must win. One signal at a
# time cannot show that, so each of these carries both.
ORDERING = [
    ('a block outranks a login redirect', dict(status=429, location='https://nid.naver.com/nidlogin.login'), 5),
    ('a login redirect outranks a server fault', dict(status=302, location='https://nid.naver.com/nidlogin.login'), 4),
    ('a login redirect outranks a missing target',
     dict(status=404, location='https://nid.naver.com/nidlogin.login',
          body=mblog({'isSuccess': False, 'error': {'code': 'not_exist_blog'}})), 4),
    ('a login redirect outranks a rejected parameter',
     dict(status=200, location='https://nid.naver.com/nidlogin.login',
          body=mblog({'isSuccess': False, 'error': {'code': 'param_is_invalidate'}})), 4),
    ('a missing target outranks a rejected parameter is not claimed; the codes are distinct',
     dict(status=404, body=mblog({'isSuccess': False, 'error': {'code': 'not_exist_blog'}})), 9),
]


@pytest.mark.parametrize('name,response,expected', ORDERING)
def test_the_step_order_decides_which_reading_wins(name, response, expected):
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(**response))
    assert caught.value.code == expected, name


def test_a_contract_error_outranks_a_policy_restriction():
    # A restricted label on an answer this reader cannot read would describe the wrong thing.
    payload = {'isSuccess': True, 'result': {'blogId': 'naverofficial'}, 'blockedByBifrostShield': True}
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(body=mblog(payload)),
                 expect={'result.blogId': 'someoneelse'})
    assert caught.value.code == 6


def test_a_restricted_answer_carries_whatever_did_arrive():
    payload = {'isSuccess': True, 'result': {'list': [{'logNo': '1'}], 'isBlockedByBifrostShield': True}}
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('search_posts'), envelope(body=mblog(payload)))
    assert caught.value.code == 8
    assert caught.value.payload['result']['list'][0]['logNo'] == '1'


def test_valid_json_that_is_not_an_envelope_is_a_transport_error_not_a_crash():
    for body in ('[]', 'null', '"a string"', '42'):
        with pytest.raises(NaverBlogError) as caught:
            classify(operation('blog_card'), envelope(body=body))
        assert caught.value.code == 6, body


def test_a_lookalike_login_host_is_not_a_login():
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('blog_card'), envelope(status=302, location='https://nid.naver.com.evil.example/'))
    # It left the reading surface, which is a contract error; calling it a login would invite a re-login.
    assert caught.value.code == 6


def test_naver_names_its_own_reason_so_an_unfamiliar_one_can_be_reported():
    body = 'location.href="/MobileErrorView.naver?errorType=closedBlog";'
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('post_html'), envelope(status=404, body=body))
    assert caught.value.reason == 'closedBlog'
    assert caught.value.as_dict()['reason'] == 'closedBlog'


def test_the_comment_box_answer_must_be_about_the_requested_post():
    payload = {'success': True, 'code': '1000',
               'result': {'commentList': [{'commentNo': '1', 'objectId': '142_201_999'}],
                          'pageModel': {'totalPages': 1}}}
    with pytest.raises(NaverBlogError) as caught:
        classify(operation('comments'), envelope(body=mblog(payload)),
                 expect={'result.commentList[].objectId': '123'})
    assert caught.value.code == 6
    # The matching post passes through the same check.
    assert classify(operation('comments'), envelope(body=mblog(payload)),
                    expect={'result.commentList[].objectId': '999'})


def test_a_post_body_that_talks_about_restrictions_is_still_a_successful_read():
    # Naver's own help posts discuss 제한 and 차단; only declared fields decide, and HTML has none.
    html = '<html><body><div class="se-main-container">이용이 제한되었습니다 안내 글</div></body></html>'
    assert classify(operation('post_html'), envelope(body=html)) == html


class FakeTransport:
    """Only redirect_of is exercised; the budget and the browser are replaced by a canned reply."""
    def __init__(self, response):
        self.response = response
        self.fetch = lambda spec, path, query, **kwargs: response

    redirect_of = Transport.redirect_of


def test_a_domain_address_resolves_to_the_canonical_blog_id():
    transport = FakeTransport(envelope(status=302, url='https://blog.naver.com/naver_diary',
                                       location='/NBlogTop.naver?blogId=naverofficial'))
    assert transport.redirect_of('domain_redirect', blogId='naver_diary') == 'naverofficial'


def test_a_lookalike_parameter_is_not_read_as_the_blog_id():
    transport = FakeTransport(envelope(status=302, url='https://blog.naver.com/x',
                                       location='/NBlogTop.naver?otherblogId=sneaky'))
    with pytest.raises(NaverBlogError) as caught:
        transport.redirect_of('domain_redirect', blogId='x')
    assert caught.value.code == 6


def test_a_block_while_resolving_a_domain_address_is_a_block_not_a_missing_blog():
    transport = FakeTransport(envelope(status=429, url='https://blog.naver.com/x'))
    with pytest.raises(NaverBlogError) as caught:
        transport.redirect_of('domain_redirect', blogId='x')
    assert caught.value.code == 5


def test_a_login_wall_while_resolving_a_domain_address_is_a_login_error():
    transport = FakeTransport(envelope(status=302, url='https://blog.naver.com/x',
                                       location='https://nid.naver.com/nidlogin.login'))
    with pytest.raises(NaverBlogError) as caught:
        transport.redirect_of('domain_redirect', blogId='x')
    assert caught.value.code == 4


def test_a_plain_200_for_a_domain_address_means_there_is_no_such_blog():
    transport = FakeTransport(envelope(status=200, url='https://blog.naver.com/x', body='<html></html>'))
    with pytest.raises(NaverBlogError) as caught:
        transport.redirect_of('domain_redirect', blogId='x')
    assert caught.value.code == 9
