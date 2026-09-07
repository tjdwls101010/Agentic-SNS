"""The CLI is run as a real process: --help, refused combinations, and exit codes."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts/naver_blog.py'
COMMANDS = ['search', 'blog', 'posts', 'post', 'comments', 'find', 'buddies', 'home', 'topic',
            'monthly', 'doctor', 'schema']


def run(arguments, env=None):
    return subprocess.run([sys.executable, str(ENTRY), *arguments], capture_output=True, text=True, env=env)


def help_of(command=None):
    return run([*( [command] if command else [] ), '--help']).stdout


def test_the_reader_offers_exactly_the_twelve_commands():
    listed = help_of()
    for command in COMMANDS:
        assert command in listed, command


def test_the_top_level_help_states_every_exit_code():
    listed = help_of()
    for code in range(2, 10):
        assert str(code) in listed
    assert 'budget' in listed.lower() or 'own count' in listed


@pytest.mark.parametrize('command', COMMANDS)
def test_each_command_help_describes_itself(command):
    assert len(help_of(command).strip()) > 80, command


@pytest.mark.parametrize('command,default', [('search', '10'), ('comments', '20'), ('buddies', '20')])
def test_a_listing_help_states_its_own_default_limit(command, default):
    assert f'default {default}' in help_of(command)


def test_only_the_commands_that_can_continue_offer_a_continuation():
    for command in ('search', 'posts', 'comments', 'find', 'buddies', 'topic'):
        assert '--after' in help_of(command), command
    # Naver serves the neighbour feed as one page, and a post or a card is not a listing.
    for command in ('home', 'post', 'blog', 'monthly'):
        assert '--after' not in help_of(command), command


def test_the_search_help_names_its_choices_and_where_each_applies():
    listed = help_of('search')
    for token in ('posts', 'blogs', 'tags', 'sim', 'date', '--own-money'):
        assert token in listed


def test_the_neighbour_feed_help_says_why_it_has_no_second_page():
    assert 'one page' in help_of('home')


REFUSED = [
    (['search', 'x', '--type', 'tags', '--sort', 'date'], 'ordering'),
    (['search', 'x', '--type', 'blogs', '--own-money'], 'posts only'),
    (['search', 'x', '--type', 'tags', '--since', '2026-09-01'], 'post search only'),
    (['posts', 'someone', '--popular', '--notices'], 'Choose one'),
    (['posts', 'https://blog.naver.com/PostList.naver?blogId=a&categoryNo=9', '--category', '3'], 'already names'),
    (['posts', 'someone', '--popular', '--after', '2'], 'single pages'),
    (['find', 'someone', 'x', '--tag', '--sort', 'date'], 'ignores ordering'),
    (['topic', '--after', '2'], 'one page'),
    (['monthly', '--month', '13'], '1 to 12'),
    (['post', 'someone'], 'id/logNo'),
    (['blog', 'https://naver.me/abc'], 'naver.me'),
    (['search', 'x', '--chars', '-1'], 'negative'),
]


@pytest.mark.parametrize('arguments,hint', REFUSED)
def test_a_refused_combination_costs_no_request_and_says_what_to_do(arguments, hint, cli_env, tmp_path):
    result = run(arguments, env=cli_env)
    assert result.returncode == 2, result.stdout
    payload = json.loads(result.stdout)
    assert hint in payload['message'] or hint in payload['fix']
    assert payload['fix']
    # The refusal happens before the browser is touched at all.
    assert not Path(cli_env['NAVER_BLOG_FAKE_LOG']).exists()


def test_doctor_reports_the_logged_in_account(cli_env):
    result = run(['doctor'], env=cli_env)
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload['viewer'] == 'testviewer' and payload['account'] == 'u0'
    assert payload['budget']['kind'] == 'local'


def test_an_unknown_command_is_an_argument_error_with_a_fix():
    result = run(['nonsense'])
    assert result.returncode == 2
    assert json.loads(result.stdout)['fix']
