"""An error's fix is read exactly when it matters, so every one has to say what to do."""
import json

import pytest

from naver_blog_skill._errors import NaverBlogError, scrub

RECOVERABLE = (2, 5, 6, 8)
ACTIONABLE = ('doctor', '--', 'run ', 'open ', 'check ', 'pass ', 'drop ', 'stop ', 'retry',
              'rerun', 'wait', 'restore', 'report', 'choose', 'reinstall', 'continue', 'log in',
              'search ', 'read ', 'name ', 'reduce', 'free ', 'use ', 'start ', 'no retry', 'try ')


@pytest.mark.parametrize('code', range(2, 10))
def test_every_exit_code_has_a_default_fix(code):
    error = NaverBlogError(code, 'something happened')
    assert error.fix and error.fix.strip()
    assert error.as_dict()['code'] == code


@pytest.mark.parametrize('code', RECOVERABLE)
def test_a_recoverable_error_names_a_command_or_a_concrete_condition(code):
    fix = NaverBlogError(code, 'something happened').fix.lower()
    assert any(token in fix for token in ACTIONABLE), fix


def test_an_error_serializes_to_one_json_object_with_its_fix():
    payload = json.loads(json.dumps(NaverBlogError(9, 'gone').as_dict(), ensure_ascii=False))
    assert set(payload) == {'ok', 'error', 'code', 'message', 'fix'}
    assert payload['ok'] is False and payload['error'] == 'unavailable'


def test_error_names_distinguish_the_kinds_a_caller_branches_on():
    names = {code: NaverBlogError(code, 'x').error for code in range(2, 10)}
    assert len(set(names.values())) == len(names)
    assert names[5] == 'blocked' and names[7] == 'empty' and names[9] == 'unavailable'


def test_naver_session_cookies_never_survive_a_scrub():
    payload = {'NID_AUT': 'secret-value', 'NID_SES': 'another', 'nested': {'userKey': 'u1'}}
    cleaned = scrub(payload)
    assert 'secret-value' not in json.dumps(cleaned)
    assert cleaned['nested']['userKey'] == '[REDACTED]'


def test_a_signed_image_url_keeps_its_path_and_loses_its_signature():
    text = 'see https://blogfiles.pstatic.net/2026/img.jpg?type=w966&x=SIGNATURE here'
    cleaned = scrub(text)
    assert 'blogfiles.pstatic.net/2026/img.jpg' in cleaned and 'SIGNATURE' not in cleaned


def test_ordinary_naver_urls_are_left_alone():
    text = 'https://blog.naver.com/naverofficial/224400531915?from=search'
    assert scrub(text) == text


def test_scrubbing_does_not_mutate_what_it_was_given():
    payload = {'NID_AUT': 'secret'}
    scrub(payload)
    assert payload['NID_AUT'] == 'secret'
