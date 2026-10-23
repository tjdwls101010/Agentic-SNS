"""Help sentences that must match what the commands do (appendix C): checked against the real `cli.py x <command> --help`."""
import subprocess
import sys

from tests.sns.support.cli import CLI


def help_of(*words):
    done = subprocess.run([sys.executable, str(CLI), 'x', *words, '--help'], capture_output=True, text=True)
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


def test_me_has_no_window_so_its_help_does_not_speak_of_one():
    text = help_of('me')
    body = text.split('exit codes:')[0]
    assert '--since' not in body and 'a window' not in body.replace('There is no date window', '')
    assert 'There is no date window' in body


def test_the_profile_help_gives_the_lists_tabs_page_size_as_it_is():
    """CombinedLists asks for 100 lists per page (operations.json); every other timeline asks for 20."""
    assert 'the lists tab: about 100 lists' in help_of('profile')


def test_trends_chars_does_not_mention_an_out_file_trends_cannot_write():
    text = help_of('trends')
    assert '--out' not in option_line(text, '--chars') and '--out' not in text.split('exit codes:')[0]


def test_post_and_replies_say_what_their_limit_counts():
    assert 'Reply threads' in option_line(help_of('post'), '--limit')
    assert 'Replies to show' in option_line(help_of('replies'), '--limit')
    assert 'Trends and events' in option_line(help_of('trends'), '--limit')


def test_the_feeds_help_says_out_needs_a_limit():
    assert 'needs --limit' in help_of('feed')
