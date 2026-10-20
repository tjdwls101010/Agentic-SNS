"""Help sentences that must match what the commands do, checked against the real `cli.py facebook <command> --help`
(the shape of every help is core/test_cli_contract.py's)."""
import subprocess
import sys

import pytest

from sns.facebook import COMMANDS
from tests.sns.support.cli import CLI


def help_of(*words):
    done = subprocess.run([sys.executable, str(CLI), 'facebook', *words, '--help'], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def option_line(text, flag):
    """The help lines of one option (its line and the indented lines that continue it)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(flag))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith(' ' * 10) or line.strip().startswith('-'):
            break
        block.append(line)
    return ' '.join(part.strip() for part in block)


def test_no_help_speaks_of_a_request_budget():
    for name in (*COMMANDS, 'doctor', 'schema'):
        text = help_of(name)
        assert 'max-requests' not in text and 'budget is spent' not in text, name
        if name in COMMANDS:
            assert 'there is no request budget' in text, name


def test_the_default_read_is_one_page_and_the_help_says_so():
    for name in ('feed', 'profile', 'group', 'comments', 'search'):
        body = help_of(name).split('exit codes:')[0]
        assert 'Without --limit or --out it reads one page' in body, name
    assert 'until the source ends' not in help_of('feed')


def test_the_feeds_help_says_out_needs_a_limit_for_the_ranked_feed_only():
    text = help_of('feed')
    assert 'The top feed never ends by itself, so --out needs --limit' in text


def test_post_and_replies_say_what_their_limit_counts():
    assert 'Parent comments' in option_line(help_of('post'), '--limit')
    assert 'Replies to show' in option_line(help_of('replies'), '--limit')
    assert 'Parent comments to show' in option_line(help_of('comments'), '--limit')


def test_the_tab_cost_is_explained_without_a_budget():
    text = help_of('feed')
    assert 'costs about 30 requests' in text and 'about 10 more' in text and 'not charged' in text


def test_the_windows_are_explained_with_the_core_wording():
    text = help_of('feed')
    assert 'left out and counted' in text and 'sample' in text
    assert 'closes at the first page with a dated, unpinned post older than --since' in text
    assert 'is partial, because Facebook shows no older posts here' in text


def test_the_doctor_help_says_the_unblock_asks_facebook():
    body = help_of('doctor')
    assert 'make one check and lift a saved block if the answer is normal' in body
    assert 'verification_reason' in body


def test_a_share_link_is_refused_by_the_help_before_the_command():
    assert 'Share links' in help_of('post') and 'fb.watch' in help_of('post')


@pytest.mark.parametrize('name', [name for name in COMMANDS if name != 'images'])
def test_every_command_names_its_records_and_its_tab(name):
    text = help_of(name)
    assert 'records: one block per record' in text and 'the dedicated tab' in text


def test_images_names_the_tab_and_how_its_numbers_match_the_post():
    text = help_of('images')
    assert 'the dedicated tab' in text and '[image N]' in text


def test_replies_says_a_deeper_branch_is_one_batch():
    assert 'stopped=server_capped' in help_of('replies')
