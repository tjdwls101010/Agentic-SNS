"""Links across platforms, through the real cli.main with Reddit and the two made-up platforms side by side: a Reddit link
given to another platform's command is refused with the command that reads it, and the other way round."""
import json

import pytest

import sns.reddit as reddit_platform
from tests.sns.reddit.shapes import listing, post
from tests.sns.support.stub_platform import STUBS

PLATFORMS = {'reddit': reddit_platform, **STUBS}


@pytest.mark.parametrize('link, command', [
    ('https://www.reddit.com/r/example/comments/aaa1/t/', 'post'), ('https://redd.it/aaa1', 'post'),
    ('https://www.reddit.com/r/example/', 'sub'), ('https://www.reddit.com/user/example_user/', 'profile'),
    ('https://www.reddit.com/r/example/wiki/faq', 'wiki'), ('https://www.reddit.com/r/example/s/AbC123', 'post')])
def test_a_reddit_link_given_to_another_platform_names_the_command_that_reads_it(reddit, link, command):
    code, out, _ = reddit.run('alpha', 'post', link, platforms=PLATFORMS)
    envelope = json.loads(out)
    assert code == 2 and envelope['fix'] == f'Read it with: reddit {command} {link}'
    assert reddit.calls() == [], 'refused before the browser is touched'


def test_another_platforms_link_given_to_a_reddit_command_names_that_platforms_command(reddit):
    code, out, _ = reddit.run('reddit', 'post', 'https://alpha.test/p/i1', platforms=PLATFORMS)
    assert code == 2 and json.loads(out)['fix'] == 'Read it with: alpha post https://alpha.test/p/i1'
    assert reddit.calls() == []


def test_a_reddit_command_still_reads_its_own_links(reddit):
    reddit.me().json('/r/example/hot.json', listing([post('a')]))
    code, out, _ = reddit.run('reddit', 'sub', 'https://www.reddit.com/r/example/', platforms=PLATFORMS)
    assert code == 0 and 'title a' in out
