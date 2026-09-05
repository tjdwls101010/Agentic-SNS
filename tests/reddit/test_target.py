import pytest
from reddit_skill._errors import RedditError
from reddit_skill._target import parse_target


@pytest.mark.parametrize('value,kind,field,want', [
    ('r/python', 'subreddit', 'sub', 'python'),
    ('/r/python+learnpython/', 'subreddits', 'sub', 'python+learnpython'),
    ('u/example-user', 'user', 'user', 'example-user'),
    ('https://reddit.com/user/example/', 'user', 'user', 'example'),
    ('me', 'me', 'user', 'me'),
    ('t3_Ab12', 'post', 'post_id', 'ab12'),
    ('AB12', 'post', 'post_id', 'ab12'),
    ('https://redd.it/Ab12?utm_source=x', 'post', 'post_id', 'ab12'),
    ('https://old.reddit.com/r/python/comments/ab12/title/', 'post', 'post_id', 'ab12'),
    ('https://np.reddit.com/comments/ab12/', 'post', 'post_id', 'ab12'),
    ('https://sh.reddit.com/gallery/ab12/', 'post', 'post_id', 'ab12'),
    ('/r/python/comments/ab12/title/cd34/', 'comment', 'comment_id', 'cd34'),
    ('https://www.reddit.com/r/python/comments/ab12/comment/cd34/', 'comment', 'comment_id', 'cd34'),
    ('/r/python/s/AbCd123', 'share', 'name', 'https://www.reddit.com/r/python/s/AbCd123'),
])
def test_local_targets(value, kind, field, want):
    target = parse_target(value)
    assert target.kind == kind
    assert getattr(target, field) == want


@pytest.mark.parametrize('value', ['https://evil.com/comments/ab12', 'https://u@reddit.com/r/python',
    'https://reddit.com:443/r/python', '//evil.com/r/python', '/r/python/wiki/index',
    '/r/python/../comments/a', '/r/python%2fother', 'r/a++b', '', None,
    'https://reddit.com\\@evil.com/comments/ab12', '/comments/ab12/title/cd34/extra'])
def test_invalid_targets(value):
    with pytest.raises(RedditError) as caught:
        parse_target(value)
    assert caught.value.code == 2


@pytest.mark.parametrize('value', ['/user/me', 'https://reddit.com/user/me/'])
def test_user_me_alias(value):
    assert parse_target(value).kind == 'me'


def test_tracking_query_does_not_change_local_target():
    assert parse_target('https://old.reddit.com/comments/abc/?utm_source=a%20b').post_id == 'abc'


@pytest.mark.parametrize('value,kind', [
    ('https://reddit.com/r/python/comments/abc/%ED%95%9C%EA%B8%80/', 'post'),
    ('/r/python/comments/abc/hello%20world/def', 'comment'),
])
def test_encoded_ignored_title_slug(value, kind):
    target = parse_target(value)
    assert target.kind == kind
    assert target.post_id == 'abc'


@pytest.mark.parametrize('value', ['/comments/abc/%2e%2e/def', '/comments/abc/a%2fb/def',
    '/comments/%61bc/title', '/r/%70ython/comments/abc/title', '/comments/abc/a%5cb/def',
    '/comments/abc/%FF/def', '/comments/abc/bad%ZZ/def'])
def test_encoding_cannot_change_identity_or_path_structure(value):
    with pytest.raises(RedditError) as caught:
        parse_target(value)
    assert caught.value.code == 2
