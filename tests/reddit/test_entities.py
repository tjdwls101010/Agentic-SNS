from reddit_skill._entities import build_subreddit, build_user, build_rule


def test_entities_keep_profile_handles_nullable_counts_and_rule_text():
    sub = build_subreddit({'id': 'abc', 'display_name': 'example', 'public_description': 'Community'}).to_dict()
    user = build_user({'id': 'abc', 'name': 'reader', 'is_employee': True}).to_dict()
    assert sub['fullname'] == 't5_abc'
    assert sub['url'] == 'https://www.reddit.com/r/example/'
    assert sub['subscribers'] is None
    assert user['fullname'] == 't2_abc'
    assert user['url'] == 'https://www.reddit.com/user/reader/'
    assert user['admin'] is True
    assert build_rule({'short_name': 'Be civil', 'description': 'Respect people'}).to_dict()['text'] == 'Respect people'


def test_username_resembling_a_fullname_is_still_a_username():
    assert build_user({'id': 'ab12', 'name': 't2_cd34'}).fullname == 't2_ab12'
