"""wiki and the community card's moderators and pinned posts through the real cli."""
import json

from tests.sns.reddit.shapes import listing

PAGE = {'kind': 'wikipage', 'data': {'content_md': '# Welcome\n\nRead the [FAQ](https://www.reddit.com/r/example/wiki/faq).',
                                     'content_html': '<h1>Welcome</h1>', 'revision_date': 1682115934,
                                     'revision_id': '6eb29c66-0000-11ed-8286-a2935fa5aba7', 'reason': 'add a page',
                                     'revision_by': {'kind': 't2', 'data': {'name': 'example_mod'}}, 'may_revise': False}}


def test_a_wiki_page_in_full_from_the_wiki_bucket(reddit, data_dir):
    reddit.json('/r/example/wiki/index.json', PAGE)
    code, out, _ = reddit.run('reddit', 'wiki', 'r/example')
    first = out.splitlines()[0]
    assert code == 0 and 'limit wiki 599 of 600 left' in first
    assert '[w1] r/example wiki index · revised' in out and 'by u/example_mod' in out and 'FAQ (https://' in out
    assert 'url: https://www.reddit.com/r/example/wiki/index' in out
    scopes = json.loads((data_dir / 'reddit/u0/protection/scopes.json').read_text())
    assert set(scopes) == {'wiki'}, 'the general bucket is not used'


def test_a_named_page_and_a_wiki_url(reddit):
    reddit.json('/r/example/wiki/faq/start.json', PAGE)
    code, out, _ = reddit.run('reddit', 'wiki', 'https://www.reddit.com/r/example/wiki/faq/start')
    assert code == 0 and 'wiki faq/start' in out


def test_the_page_list(reddit):
    reddit.json('/r/example/wiki/pages.json', {'kind': 'wikipagelisting', 'data': ['index', 'faq', 'config/sidebar']})
    code, out, _ = reddit.run('reddit', 'wiki', 'r/example', '--pages')
    assert code == 0 and 'pages: index, faq' in out and 'settings pages: config/sidebar' in out


def test_a_missing_page_and_a_closed_wiki_are_unavailable(reddit):
    reddit.respond({'status': 404, 'body': {'reason': 'PAGE_NOT_FOUND', 'message': 'Not Found'}},
                   path='/r/example/wiki/nope.json')
    code, out, _ = reddit.run('reddit', 'wiki', 'r/example', 'nope')
    assert code == 9
    reddit.respond({'status': 403, 'body': {'reason': 'WIKI_DISABLED'}}, path='/r/example/wiki/index.json')
    code, out, _ = reddit.run('reddit', 'wiki', 'r/example', '--json')
    assert code == 9 and 'WIKI_DISABLED' in json.loads(out)['message']


def test_wiki_takes_a_community_or_a_wiki_url_and_not_a_page_with_pages(reddit):
    assert reddit.run('reddit', 'wiki', 'u/example_user')[0] == 2
    assert reddit.run('reddit', 'wiki', 'r/example', 'faq', '--pages')[0] == 2
    assert reddit.fetches() == []


def test_about_a_community_adds_moderators_and_pinned_posts(reddit):
    reddit.json('/r/example/about.json', {'kind': 't5', 'data': {'id': 's1', 'name': 't5_s1', 'display_name': 'example'}})
    reddit.json('/r/example/about/rules.json', {'rules': []})
    reddit.json('/r/example/about/moderators.json', {'kind': 'UserList', 'data': {'children': [
        {'name': 'example_mod', 'author_flair_text': None, 'date': 1300000000.0, 'id': 't2_m1',
         'mod_permissions': ['all'], 'rel_id': 'rb_1'}]}})
    reddit.json('/r/example/hot.json', listing([
        {'kind': 't3', 'data': {'id': 'pin1', 'name': 't3_pin1', 'title': 'Weekly thread', 'is_self': True,
                                'stickied': True, 'distinguished': 'moderator', 'permalink': '/r/example/comments/pin1/w/'}},
        {'kind': 't3', 'data': {'id': 'n1', 'name': 't3_n1', 'title': 'Ordinary', 'is_self': True}}]),
        query={'limit': 10})
    code, out, _ = reddit.run('reddit', 'about', 'r/example')
    assert code == 0 and 'requests=4 ' in out.splitlines()[0]
    assert 'moderators: u/example_mod' in out and 'pinned: "Weekly thread"' in out and 'Ordinary' not in out


def test_schema_describes_the_new_records(reddit):
    for name in ('wiki_page', 'wiki_index', 'moderator'):
        code, out, _ = reddit.run('reddit', 'schema', name)
        assert code == 0 and json.loads(out)['results'][0]['object'] == name
