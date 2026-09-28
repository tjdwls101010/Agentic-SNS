"""Profile cards through the CLI."""

from .fixtures.builders import null_profile
from .helpers import calls, data, run_cli


def test_about_reports_zero_following_as_a_count(fake_aside):
    about = run_cli('about', '@fixture_user', '--json')
    assert about.returncode == 0, about.stdout + about.stderr
    assert data(about)['results'][0]['counts'] == {'followers': 1000, 'following': 0, 'mutuals': 0}


def test_null_ssr_profile_uses_the_profile_query(routes):
    null_profile(routes).write()
    result = run_cli('about', '@fixture_user', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data(result)['results'][0]['username'] == 'fixture_user'
    assert [c['key'] for c in calls(routes.path.parent / 'requests.ndjson')] == \
        ['/@fixture_user', 'BarcelonaProfilePageDirectQuery', 'BarcelonaFriendshipsFollowingTabQuery']
