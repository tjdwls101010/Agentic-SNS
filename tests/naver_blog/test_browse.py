"""buddies, home, topic and monthly: the surfaces where Naver's own limits show most."""
import json
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts/naver_blog.py'


def cli(arguments, env, json_output=True):
    command = [sys.executable, str(ENTRY), *arguments] + (['--json'] if json_output else [])
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    return result.returncode, (json.loads(result.stdout) if json_output else result.stdout.rstrip('\n'))


def test_your_own_neighbour_list_and_someone_elses_are_different_endpoints(cli_env):
    code, payload = cli(['buddies'], cli_env)
    assert code == 0
    assert [record['blog_id'] for record in payload['results']] == ['buddyone', 'buddytwo']
    assert payload['results'][0]['mutual'] is True
    requests = [json.loads(line)['path'] for line in
                Path(cli_env['NAVER_BLOG_FAKE_LOG']).read_text().splitlines()]
    assert any('my-buddies' in path for path in requests)


def test_an_empty_public_neighbour_list_says_why_it_is_empty(cli_env):
    """Private is the default, so an empty list is not evidence of having no neighbours."""
    code, payload = cli(['buddies', 'otherblog'], cli_env)
    assert code == 7
    assert payload['results'] == []
    assert any('publishes no neighbour list' in note for note in payload['warnings'])


def test_reading_your_own_list_identifies_the_account_first(cli_env):
    cli(['buddies'], cli_env)
    requests = [json.loads(line)['path'] for line in
                Path(cli_env['NAVER_BLOG_FAKE_LOG']).read_text().splitlines()]
    # It has to know whose list to ask for; a cached session makes this free next time.
    assert requests[0] == '/FeedList.naver'


def test_the_neighbour_feed_says_it_serves_one_page_rather_than_claiming_the_end(cli_env):
    code, payload = cli(['home', '--limit', '5'], cli_env)
    assert code == 0
    assert payload['stop_reason'] == 'not_paginable'
    assert payload['next'] is None


def test_the_neighbour_feed_offers_no_continuation_at_all(cli_env):
    result = subprocess.run([sys.executable, str(ENTRY), 'home', '--after', '1'],
                            capture_output=True, text=True, env=cli_env)
    assert result.returncode == 2
    assert 'unrecognized arguments' in json.loads(result.stdout)['message']


def test_the_topic_directory_lists_every_topic_with_its_number(cli_env):
    code, payload = cli(['topic'], cli_env)
    assert code == 0
    assert {record['seq'] for record in payload['results']} == {'5', '6', '30', '31', '32'}
    assert all(record['group'] for record in payload['results'])


def test_a_topic_name_resolves_to_its_number(cli_env):
    code, payload = cli(['topic', '문학', '--limit', '2'], cli_env)
    assert code == 0 and payload['context']['topic'] == '5'


def test_an_unknown_topic_name_says_where_to_look(cli_env):
    code, payload = cli(['topic', '없는주제'], cli_env)
    assert code == 9 and 'topic with no argument' in payload['fix']


def test_an_ambiguous_topic_name_lists_the_numbers_to_choose_from(cli_env):
    # "리" is inside both 요리 and 요리·레시피, and neither is an exact match.
    code, payload = cli(['topic', '리'], cli_env)
    assert code == 2 and 'more than one' in payload['message']
    assert '31' in payload['fix'] and '32' in payload['fix']


def test_an_exact_topic_name_wins_over_the_ones_that_merely_contain_it(cli_env):
    # 요리 is inside 요리·레시피 too, but naming it exactly is not ambiguous.
    code, payload = cli(['topic', '요리', '--limit', '1'], cli_env)
    assert code != 2, payload


def test_featured_topic_posts_are_a_single_page(cli_env):
    code, payload = cli(['topic', '5', '--top'], cli_env)
    assert code == 0 and payload['stop_reason'] == 'not_paginable'


def test_the_month_issue_points_at_the_previous_one(cli_env):
    code, payload = cli(['monthly', '--year', '2026', '--month', '9'], cli_env, json_output=False)
    assert code == 0
    assert 'monthly --year 2026 --month 8' in payload


def test_the_month_issue_answers_in_two_sections(cli_env):
    code, payload = cli(['monthly', '--year', '2026', '--month', '9'], cli_env)
    assert [section['name'] for section in payload['sections']] == \
        ['blogs of the month', 'editor picks']
    assert all(section['ok'] for section in payload['sections'])


def test_a_date_window_on_the_neighbour_feed_filters_what_is_shown(cli_env):
    code, payload = cli(['home', '--since', '2025-09-05'], cli_env)
    assert code in (0, 7)
    for record in payload['results']:
        assert record['created_at'] >= '2025-09-05'
