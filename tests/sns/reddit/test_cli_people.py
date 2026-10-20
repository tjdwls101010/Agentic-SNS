"""profile and about through the real cli: a redditor's history, a history that is not visible (empty although the
account has karma for it), and the community and user cards."""
import json

from tests.sns.reddit.shapes import about_user, listing, profile_comment


def test_a_visible_history(reddit):
    reddit.me().json('/user/example_user/comments.json', listing([profile_comment('c1'), profile_comment('c2')]),
                     query={'sort': 'new', 'limit': 100})
    code, out, _ = reddit.run('reddit', 'profile', 'u/example_user', '--type', 'comments')
    assert code == 0 and out.startswith('reddit profile · sort=new · type=comments · 2 shown') and 'said c1' in out


def test_an_empty_history_with_karma_is_not_visible(reddit):
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(28, 55636))
    code, out, _ = reddit.run('reddit', 'profile', 'u/example_user', '--json')
    envelope = json.loads(out)
    assert code == 9 and envelope['error'] == 'unavailable'
    assert 'no visible activity although karma is 55664' in envelope['message'] and 'about u/' in envelope['fix']
    assert envelope['results'] == [] and envelope['request_count'] == 3


def test_karma_of_the_kind_asked_decides(reddit):
    reddit.me().json('/user/example_user/submitted.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(0, 500))
    code, out, _ = reddit.run('reddit', 'profile', 'u/example_user', '--type', 'posts', '--json')
    envelope = json.loads(out)
    assert code == 7 and envelope['message'] == 'no visible posts; post karma is 0', 'observed, not proven absent'


def test_a_filtered_empty_result_is_not_judged(reddit):
    reddit.me().json('/user/example_user/overview.json', listing([]), query={'t': 'week'})
    code, out, _ = reddit.run('reddit', 'profile', 'u/example_user', '--sort', 'top', '--time', 'week')
    assert code == 7 and reddit.paths() == ['/api/me.json', '/user/example_user/overview.json']


def test_a_failing_karma_check_keeps_its_own_meaning(reddit):
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.respond({'status': 403, 'body': {'reason': 'suspended'}}, path='/user/example_user/about.json')
    code, out, _ = reddit.run('reddit', 'profile', 'u/example_user', '--json')
    envelope = json.loads(out)
    assert code == 9 and 'suspended' in envelope['message']


def test_a_karma_check_the_time_limit_cut_off_is_a_time_limit_not_an_empty_history(reddit, monkeypatch):
    monkeypatch.setenv('SNS_DEADLINE_SECONDS', '4.5')  # the account check and the page fit; the karma request does not
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(28, 55636))
    code, out, _ = reddit.run('reddit', 'profile', 'u/example_user', '--json')
    envelope = json.loads(out)
    assert code != 7 and envelope.get('stop_reason') == 'time_limit'


def test_about_a_community_reads_its_card_and_rules_without_an_account_check(reddit):
    reddit.json('/r/example/about.json', {'kind': 't5', 'data': {'id': 's1', 'name': 't5_s1', 'display_name': 'example',
                                                                'subscribers': 1234, 'public_description': 'Short.',
                                                                'description': 'Sidebar.', 'subreddit_type': 'public'}})
    reddit.json('/r/example/about/rules.json', {'rules': [{'short_name': 'Be kind', 'description': 'No insults.',
                                                            'kind': 'all'}]})
    reddit.json('/r/example/about/moderators.json', {'kind': 'UserList', 'data': {'children': []}})
    reddit.json('/r/example/hot.json', listing([]))
    code, out, _ = reddit.run('reddit', 'about', 'r/example')
    assert code == 0 and 'requests=4 ' in out.splitlines()[0]
    assert '[s1] r/example · 1234 subscribers' in out and 'rule 1: "Be kind"' in out
    assert reddit.paths() == ['/r/example/about.json', '/r/example/about/rules.json', '/r/example/about/moderators.json',
                              '/r/example/hot.json']


def test_about_a_user(reddit):
    reddit.json('/user/example_user/about.json', about_user(1200, 24000))
    code, out, _ = reddit.run('reddit', 'about', 'u/example_user', '--json')
    record = json.loads(out)['results'][0]
    assert code == 0 and record['kind'] == 'user' and record['comment_karma'] == 24000


def test_about_needs_an_explicit_r_or_u(reddit):
    code, out, _ = reddit.run('reddit', 'about', 'example')
    assert code == 2 and reddit.fetches() == []


def test_a_missing_community(reddit):
    reddit.respond({'status': 404, 'body': {'message': 'Not Found', 'error': 404}}, path='/r/nope/about.json')
    code, out, _ = reddit.run('reddit', 'about', 'r/nope', '--json')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'
