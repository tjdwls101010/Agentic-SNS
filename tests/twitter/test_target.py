import pytest
from twitter_skill._target import parse
from twitter_skill._errors import TwitterError

@pytest.mark.parametrize('value', ['@example', 'example', 'https://x.com/example?s=20', 'mobile.twitter.com/example/'])
def test_user(value):
    assert parse(value, 'user').handle == 'example'

@pytest.mark.parametrize('value', ['123', 'https://x.com/example/status/123/photo/1', '/i/web/status/123', 'm.twitter.com/example/status/123/analytics#x'])
def test_post(value):
    assert parse(value, 'post').tweet_id == '123'

@pytest.mark.parametrize('value', ['123', 'https://evil.com/example', 'https://x.com/messages', 'https://t.co/foo', 'https://x.com@evil.com/example'])
def test_invalid_user(value):
    with pytest.raises(TwitterError) as exc:
        parse(value, 'user')
    assert exc.value.code == 2

@pytest.mark.parametrize('value', ['https://x.com:abc/example', 'https://x.com:99999/example', 'https://[x.com/example'])
def test_malformed_url_is_an_argument_error(value):
    with pytest.raises(TwitterError) as exc:
        parse(value, 'user')
    assert exc.value.code == 2
