import pytest

from _errors import FacebookError


def test_tokens_are_extracted_with_unicode_jazoest_and_no_cache():
    from _session import extract_tokens
    html = '"USER_ID":"123" "DTSGInitialData",[],{"token":"a&+한"} "LSD",[],{"token":"l+&"} "__spin_r":456'
    tokens = extract_tokens(html)
    assert tokens == {'user_id': '123', 'fb_dtsg': 'a&+한', 'lsd': 'l+&', 'jazoest': '254798', '__spin_r': '456', '__rev': '456'}
    with pytest.raises(FacebookError) as error:
        extract_tokens('"USER_ID":"0"')
    assert error.value.code == 4
    with pytest.raises(FacebookError) as error:
        extract_tokens('"USER_ID":"123"')
    assert error.value.code == 6


@pytest.mark.parametrize('token', ['""', '"bad\\qsecret"'])
def test_invalid_token_data_is_a_safe_query_error(token):
    from _session import extract_tokens
    html = '"USER_ID":"123" "DTSGInitialData",[],{"token":' + token + '} "LSD",[],{"token":"lsd"} "__spin_r":1'
    with pytest.raises(FacebookError) as error:
        extract_tokens(html)
    assert error.value.code == 6
    assert 'secret' not in str(error.value)
