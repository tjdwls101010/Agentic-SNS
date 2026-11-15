"""Links across the five platforms, through the real cli.py and a fake Aside: a link of one platform given to another
platform's command is refused (exit 2) before the browser is touched, with the command that reads it as the fix. The
expected readers are the platforms' own URL forms, written here by hand."""
import json

import pytest

from tests.sns.support.browser import Browser
from tests.sns.support.cli import run_cli

LINKS = {
    'x': [('https://x.com/example_user/status/1850000000000000001', 'post'),
          ('https://twitter.com/example_user', 'profile')],
    'threads': [('https://www.threads.com/@example.user/post/DAbcdefGHij', 'post'),
                ('https://www.threads.net/@example.user', 'profile')],
    'reddit': [('https://www.reddit.com/r/example/comments/aaa1/a_title/', 'post'),
               ('https://www.reddit.com/r/example/', 'sub')],
    'facebook': [('https://www.facebook.com/example.page/posts/pfbid0abc', 'post'),
                 ('https://www.facebook.com/groups/examplegroup/', 'group')],
    'naver-blog': [('https://blog.naver.com/exampleid/223000000001', 'post'),
                   ('https://m.blog.naver.com/exampleid', 'about')],
}
CASES = [(asked, owner, link, command) for owner, links in LINKS.items() for link, command in links
         for asked in LINKS if asked != owner]


@pytest.mark.parametrize('asked, owner, link, command', CASES,
                         ids=[f'{a}<-{o}:{c}' for a, o, _, c in CASES])
def test_a_link_of_another_platform_names_the_command_that_reads_it(tmp_path, data_dir, asked, owner, link, command):
    browser = Browser(tmp_path)
    done = run_cli(asked, 'post', link, browser=browser)
    envelope = json.loads(done.stdout)
    assert done.returncode == 2, envelope
    assert envelope['fix'] == f'Read it with: {owner} {command} {link}'
    assert browser.calls() == [], 'refused before the browser is touched'


# A link of the same platform but of another kind than the command reads: (platform, command run, link, the reader).
SAME = [('x', 'post', 'https://x.com/example_user', 'profile'),
        ('x', 'profile', 'https://x.com/example_user/status/1850000000000000001', 'post'),
        ('x', 'list', 'https://x.com/i/communities/1500000000000000001', 'community'),
        ('threads', 'post', 'https://www.threads.com/@example.user', 'profile'),
        ('threads', 'about', 'https://www.threads.com/@example.user/post/DAbcdefGHij', 'post'),
        ('reddit', 'sub', 'https://www.reddit.com/r/example/comments/aaa1/a_title/', 'post'),
        ('reddit', 'comments', 'https://www.reddit.com/r/example/', 'sub'),
        ('facebook', 'group', 'https://www.facebook.com/example.page/posts/pfbid0abc', 'post'),
        ('facebook', 'post', 'https://www.facebook.com/groups/examplegroup/', 'group'),
        ('naver-blog', 'post', 'https://blog.naver.com/exampleid', 'about'),
        ('naver-blog', 'profile', 'https://blog.naver.com/exampleid/223000000001', 'post'),
        ('naver-blog', 'comments', 'https://blog.naver.com/exampleid', 'about')]


@pytest.mark.parametrize('platform, command, link, reader', SAME, ids=[f'{p}:{c}<-{r}' for p, c, _, r in SAME])
def test_a_link_of_another_kind_names_the_command_that_reads_it(tmp_path, data_dir, platform, command, link, reader):
    """P5: a profile link given to post (and the like) ends before the browser with the command that reads it."""
    browser = Browser(tmp_path)
    done = run_cli(platform, command, link, browser=browser)
    envelope = json.loads(done.stdout)
    assert done.returncode == 2, envelope
    assert envelope['fix'] == f'Read it with: {platform} {reader} {link}'
    assert browser.calls() == [] or {c['op'] for c in browser.calls()} <= {'account_status', 'version'}


# Links each command takes as they are (a reader of several kinds, a naver.me link whose kind shows only later).
ACCEPTED = [('x', 'about', 'https://x.com/example_user'), ('x', 'about', 'https://x.com/i/spaces/1ABCDEFGHIJKL'),
            ('reddit', 'about', 'https://www.reddit.com/user/example_user/'),
            ('reddit', 'wiki', 'https://www.reddit.com/r/example/'),
            ('facebook', 'about', 'https://www.facebook.com/groups/examplegroup/'),
            ('naver-blog', 'about', 'https://blog.naver.com/exampleid/223000000001'),
            ('naver-blog', 'post', 'https://naver.me/abcdefgh')]


@pytest.mark.parametrize('platform, command, link', ACCEPTED, ids=[f'{p}:{c}' for p, c, _ in ACCEPTED])
def test_a_link_a_command_reads_is_not_refused_for_its_kind(tmp_path, data_dir, platform, command, link):
    done = run_cli(platform, command, link, browser=Browser(tmp_path))
    envelope = json.loads(done.stdout)
    assert not (done.returncode == 2 and (envelope.get('fix') or '').startswith('Read it with:')), envelope


@pytest.mark.parametrize('link', ['https://blog.naver.com/exampleid', 'https://blog.naver.com/PostList.naver?blogId=exampleid',
                                  'https://blog.naver.com/exampleid/223000000001'])
def test_naver_graph_accepts_any_blog_link(tmp_path, data_dir, link):
    done = run_cli('naver-blog', 'graph', link, 'buddies', browser=Browser(tmp_path))
    envelope = json.loads(done.stdout)
    assert not (done.returncode == 2 and (envelope.get('fix') or '').startswith('Read it with:')), envelope
