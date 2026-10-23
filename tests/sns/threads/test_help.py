"""Help sentences that must match what the commands do (appendix C), checked against the real `cli.py threads <command>
--help`; the contract every platform's help keeps (every argument explained, only reachable exit codes, no budget) is
core/test_cli_contract.py's."""
import subprocess
import sys

import pytest

from sns.threads import COMMANDS
from tests.sns.support.cli import CLI


def help_of(*words):
    done = subprocess.run([sys.executable, str(CLI), 'threads', *words, '--help'], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def body(text):
    return ' '.join(text.split('exit codes:')[0].split())


def test_the_feeds_help_says_out_needs_a_limit():
    assert 'needs --limit' in help_of('feed')


def test_the_feeds_help_says_what_a_window_does_on_each_feed():
    text = body(help_of('feed'))
    assert 'Only --feed following can close a --since window' in text and 'foryou is a sample of the window' in text


def test_the_profile_help_says_the_dateless_tabs_need_the_end_to_cover_a_window():
    text = body(help_of('profile'))
    assert 'reposts and media are in no date order: a window covers them only when read to the end' in text


def test_nothing_speaks_of_a_budget_or_the_old_environment():
    for name in [*COMMANDS, 'doctor', 'schema']:
        text = help_of(name)
        for word in ('--max-requests', 'budget', 'THREADS_', 'prepaid at 40'):
            assert word not in body(text).replace('there is no request budget', ''), (name, word)


def test_post_and_replies_say_what_their_limit_counts():
    for name, phrase in (('post', 'Direct replies to show'), ('replies', 'Replies to show')):
        assert phrase in ' '.join(help_of(name).split())


@pytest.mark.parametrize('name', sorted(COMMANDS))
def test_every_reading_command_says_how_the_tab_is_counted(name):
    assert 'the dedicated tab:' in help_of(name)


def test_search_help_names_the_filters_threads_applies_itself():
    text = body(help_of('search'))
    assert '--since, --until and --from are filters Threads applies itself' in text and 'closed (server-filtered)' in text
