"""profile and about through the real cli.py: a redditor's history, a history that is not visible (empty although the
account has karma for it), and the community and user cards."""
import json

from conftest import run_cli


def listing(children, after=None):
    return {'kind': 'Listing', 'data': {'after': after, 'modhash': 'm', 'children': children}}


def comment(identity):
    return {'kind': 't1', 'data': {'id': identity, 'name': f't1_{identity}', 'parent_id': 't3_p', 'link_id': 't3_p',
                                   'body': f'said {identity}', 'author': 'example_user', 'subreddit': 'example',
                                   'permalink': f'/r/example/comments/p/t/{identity}/', 'created_utc': 1760000000}}


def about_user(link_karma, comment_karma):
    return {'kind': 't2', 'data': {'id': 'u1', 'name': 'example_user', 'link_karma': link_karma,
                                   'comment_karma': comment_karma, 'created_utc': 1500000000}}


def test_a_visible_history(reddit):
    reddit.me().json('/user/example_user/comments.json', listing([comment('c1'), comment('c2')]),
                     query={'sort': 'new', 'limit': '100'})
    code, out, _ = run_cli(reddit, 'profile', 'u/example_user', '--type', 'comments')
    assert code == 0 and out.startswith('profile · sort=new · type=comments · 2 shown') and 'said c1' in out


def test_an_empty_history_with_karma_is_not_visible(reddit):
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(28, 55636))
    code, out, _ = run_cli(reddit, 'profile', 'u/example_user')
    envelope = json.loads(out)
    assert code == 9 and envelope['error'] == 'unavailable' and envelope['reason'] == 'history_not_visible'
    assert 'no visible activity although karma is 55664' in envelope['message'] and 'about u/' in envelope['fix']
    assert envelope['results'] == [] and envelope['request_count'] == 3


def test_karma_of_the_kind_asked_decides(reddit):
    reddit.me().json('/user/example_user/submitted.json', listing([]))
    reddit.json('/user/example_user/about.json', about_user(0, 500))
    code, out, _ = run_cli(reddit, 'profile', 'u/example_user', '--type', 'posts')
    envelope = json.loads(out)
    assert code == 7 and envelope['message'] == 'no visible posts; post karma is 0', 'observed, not proven absent'


def test_a_filtered_empty_result_is_not_judged(reddit):
    reddit.me().json('/user/example_user/overview.json', listing([]), query={'t': 'week'})
    code, out, _ = run_cli(reddit, 'profile', 'u/example_user', '--sort', 'top', '--time', 'week')
    assert code == 7 and reddit.paths() == ['/api/me.json', '/user/example_user/overview.json']


def test_a_failing_karma_check_keeps_its_own_meaning(reddit):
    reddit.me().json('/user/example_user/overview.json', listing([]))
    reddit.respond({'status': 403, 'body': {'reason': 'suspended'}}, path='/user/example_user/about.json')
    code, out, _ = run_cli(reddit, 'profile', 'u/example_user')
    assert code == 9 and json.loads(out)['reason'] == 'suspended'


def test_no_budget_left_for_the_karma_check(reddit):
    reddit.me().json('/user/example_user/overview.json', listing([]))
    code, out, _ = run_cli(reddit, 'profile', 'u/example_user', '--max-requests', '2')
    envelope = json.loads(out)
    assert code == 8 and 'karma could not be checked' in envelope['message']


def test_about_a_community_reads_its_card_and_rules_without_an_account_check(reddit):
    reddit.json('/r/example/about.json', {'kind': 't5', 'data': {'id': 's1', 'name': 't5_s1', 'display_name': 'example',
                                                                'subscribers': 1234, 'public_description': 'Short.',
                                                                'description': 'Sidebar.', 'subreddit_type': 'public'}})
    reddit.json('/r/example/about/rules.json', {'rules': [{'short_name': 'Be kind', 'description': 'No insults.',
                                                            'kind': 'all'}]})
    code, out, _ = run_cli(reddit, 'about', 'r/example')
    assert code == 0 and 'account not checked' in out.splitlines()[0] and 'requests=2/25' in out.splitlines()[0]
    assert '[s1] r/example · 1234 subscribers' in out and 'rule 1: "Be kind"' in out
    assert reddit.paths() == ['/r/example/about.json', '/r/example/about/rules.json']


def test_about_a_user(reddit):
    reddit.json('/user/example_user/about.json', about_user(1200, 24000))
    code, out, _ = run_cli(reddit, 'about', 'u/example_user', '--json')
    record = json.loads(out)['results'][0]
    assert code == 0 and record['kind'] == 'user' and record['comment_karma'] == 24000


def test_about_needs_an_explicit_r_or_u(reddit):
    code, out, _ = run_cli(reddit, 'about', 'example')
    assert code == 2 and reddit.fetches() == []


def test_a_missing_community(reddit):
    reddit.respond({'status': 404, 'body': {'message': 'Not Found', 'error': 404}}, path='/r/nope/about.json')
    code, out, _ = run_cli(reddit, 'about', 'r/nope')
    assert code == 9 and json.loads(out)['reason'] == 'not_found'
