import json

import pytest

from threads_skill._session import Session, preloaders
from threads_skill._errors import ThreadsError


def route(user_id='42'):
    loader = {'preloaderID': 'adp_BarcelonaProfilePageDirectQueryRelayPreloader_hash',
              'queryID': '1001', 'variables': {'userID': user_id, 'flag': {'nested': 'a}b'}}}
    return ('<html><script type="application/json">' + json.dumps({'DTSGInitialData': [],
        'csrf_token': 'synthetic-csrf', 'NON_FACEBOOK_USER_ID': '100', 'username': 'fixture_viewer',
        'userID': 'wrong-viewer', 'preload': loader}) + '</script></html>')


def test_identity_comes_from_the_matching_preloader_not_the_first_userid():
    session = Session.from_html(route())
    assert (session.viewer, session.actor, session.csrf) == ('fixture_viewer', '100', 'synthetic-csrf')
    assert session.identity('BarcelonaProfilePageDirectQuery', 'userID') == '42'
    assert preloaders(route())[0]['variables']['flag'] == {'nested': 'a}b'}


def test_shell_is_unknown_while_authenticated_missing_profile_is_unavailable():
    with pytest.raises(ThreadsError) as error:
        Session.from_html('<html><title>Threads</title></html>')
    assert (error.value.code, error.value.error) == (6, 'transient')
    with pytest.raises(ThreadsError) as error:
        Session.from_html('<script>"DTSGInitialData",[],{}</script>')
    assert error.value.code == 4


def test_full_session_without_relay_structure_is_drift():
    with pytest.raises(ThreadsError) as error:
        Session.from_html('<script>"DTSGInitialData",[],{"csrf_token":"fixture",'
                          '"NON_FACEBOOK_USER_ID":"42","username":"fixture"}</script>')
    assert error.value.error == 'envelope_drift'
