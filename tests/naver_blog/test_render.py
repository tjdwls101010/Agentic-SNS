"""Density is a contract, not a preference: what the reader pays for is tokens.

An item is a few lines, a field Naver did not supply has no line at all, and the last
lines of a listing are always the next command. These are asserted rather than described
because prose about brevity does not stay true through the next feature.
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from naver_blog_skill._render import comment_lines, post_lines, quote, render, text

ENTRY = Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts/naver_blog.py'


def cli(arguments, env):
    result = subprocess.run([sys.executable, str(ENTRY), *arguments], capture_output=True, text=True, env=env)
    return result.returncode, result.stdout.rstrip('\n')


FULL_POST = {'id': 'post:testblog/999001', 'blog_id': 'testblog', 'log_no': '999001',
             'url': 'https://blog.naver.com/testblog/999001', 'title': '제목', 'summary': '요약',
             'created_at': '2026-09-04T09:30+09:00', 'nickname': '테스터', 'category_name': '카테고리',
             'like_count': 99, 'comment_count': 8, 'view_count': 500, 'labels': []}


def test_a_post_never_takes_more_than_four_lines():
    assert len(post_lines(FULL_POST, 'p1', 180)) == 4


def test_a_comment_never_takes_more_than_three_lines():
    comment = {'id': 'comment:1', 'comment_no': '1', 'author': '사람', 'text': '댓글',
               'created_at': '2026-08-05T22:47+09:00', 'like_count': 0, 'reply_level': 1, 'labels': []}
    assert len(comment_lines(comment, 'c1', 180)) == 2
    assert len(comment_lines(dict(comment, text='줄1\n줄2\n줄3'), 'c1', 180)) == 2


def test_a_field_naver_did_not_supply_produces_no_line_and_no_null():
    bare = {'id': 'post:testblog/999001', 'blog_id': 'testblog', 'log_no': '999001',
            'title': '제목', 'summary': '', 'labels': []}
    rendered = '\n'.join(post_lines(bare, 'p1', 180))
    assert 'None' not in rendered and 'null' not in rendered and 'unknown' not in rendered
    assert 'likes=' not in rendered and 'views=' not in rendered
    assert len(post_lines(bare, 'p1', 180)) == 2


def test_a_zero_count_is_shown_because_zero_is_an_answer():
    rendered = '\n'.join(post_lines(dict(FULL_POST, like_count=0), 'p1', 180))
    assert 'likes=0' in rendered


def test_a_folded_newline_stays_visible_instead_of_disappearing():
    assert text('첫 줄\n둘째 줄') == '첫 줄⏎둘째 줄'
    assert text('여러\n\n\n\n빈 줄') == '여러⏎빈 줄'


def test_clipping_marks_itself_and_zero_means_no_clipping():
    assert text('가' * 300, 10).endswith('…') and len(text('가' * 300, 10)) == 11
    assert len(text('가' * 300, 0)) == 300


def test_a_url_is_quoted_so_it_can_be_copied_whole():
    assert quote('https://blog.naver.com/a/1?b=2') == '"https://blog.naver.com/a/1?b=2"'


def test_a_listing_ends_with_the_next_command_and_the_next_hops(cli_env):
    code, out = cli(['search', '파이썬', '--limit', '3'], cli_env)
    assert code == 0
    lines = out.splitlines()
    assert lines[-2].startswith('more: ') and '--after' in lines[-2]
    assert lines[-1].startswith('open: ') and '`post' in lines[-1]


def test_the_header_is_one_line_and_says_what_stopped_the_walk(cli_env):
    code, out = cli(['search', '파이썬', '--limit', '3'], cli_env)
    header = out.splitlines()[0]
    assert header.startswith('search · ')
    assert 'stopped=limit_reached' in header and 'local budget' in header


def test_navers_own_total_is_labelled_as_a_figure_that_drifts(cli_env):
    _, out = cli(['search', '파이썬', '--limit', '3'], cli_env)
    assert 'reported≈27,295 (server figure, drifts)' in out.splitlines()[0]


def test_a_whole_blog_card_stays_under_forty_lines(cli_env):
    code, out = cli(['blog', 'testblog'], cli_env)
    assert code == 0
    assert len(out.splitlines()) <= 40, out


def test_a_continuation_command_rebuilds_the_query_it_continues(cli_env):
    code, out = cli(['posts', 'testblog', '--category', '108', '--limit', '2'], cli_env)
    more = [line for line in out.splitlines() if line.startswith('more: ')][0]
    assert '--category 108' in more
    # The printed command must actually run: a handle is bound to its exact query.
    arguments = ['posts', 'testblog', '--category', '108', '--after',
                 more.split('--after ')[1].strip(), '--limit', '2']
    code, out = cli(arguments, cli_env)
    assert code == 0, out


def test_a_continuation_handle_from_another_query_is_refused(cli_env):
    _, out = cli(['search', '파이썬', '--limit', '2'], cli_env)
    handle = [line for line in out.splitlines() if line.startswith('more: ')][0].split('--after ')[1].strip()
    code, out = cli(['posts', 'testblog', '--after', handle], cli_env)
    assert code == 2 and 'different query' in json.loads(out)['message']


def test_the_json_document_carries_namespaced_ids_and_the_stop_reason(cli_env):
    code, out = cli(['search', '파이썬', '--limit', '2', '--json'], cli_env)
    payload = json.loads(out)
    assert payload['command'] == 'search' and payload['stop_reason'] == 'limit_reached'
    assert all(record['id'].startswith('post:') for record in payload['results'])
    assert payload['budget']['kind'] == 'local' and isinstance(payload['fetched_bytes'], int)
    assert payload['next'] and '--after' in payload['next']


def test_a_composite_command_answers_in_sections_in_json_too(cli_env):
    code, out = cli(['blog', 'testblog', '--json'], cli_env)
    payload = json.loads(out)
    assert [section['name'] for section in payload['sections']] == \
        ['blog', 'categories', 'notices', 'popular']
    assert all(section['ok'] for section in payload['sections'])


def test_a_failed_section_is_shown_beside_the_ones_that_worked():
    sections = [{'name': 'blog', 'ok': True, 'prefix': 'b',
                 'data': [{'id': 'blog:testblog', 'blog_id': 'testblog', 'name': '테스트'}]},
                {'name': 'notices', 'ok': False, 'prefix': 'n',
                 'error': {'code': 6, 'message': 'Naver returned HTTP 500.'}}]
    result = {'sections': sections, 'results': [], 'stop_reason': 'not_paginable', 'budget': {}}
    rendered = render(result, SimpleNamespace(command='blog', chars=180))
    assert 'testblog' in rendered
    assert 'notices: unavailable — Naver returned HTTP 500.' in rendered


def test_an_empty_section_reads_as_empty_rather_than_as_a_failure():
    sections = [{'name': 'notices', 'ok': True, 'prefix': 'n', 'data': []}]
    rendered = render({'sections': sections, 'results': [], 'stop_reason': 'not_paginable', 'budget': {}},
                      SimpleNamespace(command='blog', chars=180))
    assert 'notices: none' in rendered
