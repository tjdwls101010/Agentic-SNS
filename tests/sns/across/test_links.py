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
                   ('https://m.blog.naver.com/exampleid', 'blog')],
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
