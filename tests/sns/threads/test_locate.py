"""What `threads` does with a link of its own and with a link of another platform (the pure rule, web.locate, is
test_web.py): its own is read, another platform's is refused with the command that reads it, before any request."""
import json

from tests.sns.threads.scenes import run
from tests.sns.threads.test_cli_thread import URL, scripted_post


def test_a_threads_link_given_to_post_is_read(browser):
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL, '--json')
    assert code == 0, out


def test_a_link_of_another_platform_names_the_command_that_reads_it(browser):
    for platform_link, word in (('https://x.com/example_user/status/1850000000000000001', 'x post'),
                                ('https://www.reddit.com/r/python/comments/abc/title/', 'reddit post')):
        code, out, _ = run(browser, 'post', platform_link)
        envelope = json.loads(out)
        assert code == 2 and envelope['error'] == 'argument' and word in envelope['fix'], out
    assert browser.calls() == []


def test_a_link_to_another_site_is_threads_own_argument_error_not_a_request(browser):
    code, out, _ = run(browser, 'post', 'https://example.com/@example.user/post/DAbc')
    envelope = json.loads(out)
    assert code == 2 and envelope['error'] == 'argument' and 'threads.com or threads.net' in envelope['message']
    assert browser.calls() == []
