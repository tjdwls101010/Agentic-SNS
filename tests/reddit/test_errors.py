from reddit_skill._errors import RedditError, scrub


def test_error_contract_and_secret_scrubbing():
    error = RedditError(4, 'Login required.')
    assert error.as_dict() == {'ok': False, 'error': 4, 'message': 'Login required.',
                               'fix': 'Log in to Reddit in Aside, then run doctor.'}
    assert scrub({'modhash': 'private', 'cookie': 'secret', 'name': 'public'}) == {
        'modhash': '[REDACTED]', 'cookie': '[REDACTED]', 'name': 'public'}
    assert 'secret' not in scrub('modhash=secret cookie=secret')
