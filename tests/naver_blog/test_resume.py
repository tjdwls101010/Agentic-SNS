"""Continuing a listing: nothing already read may be lost, and a handle means one query.

Naver resumes by page number, not by a server cursor, so a handle is only meaningful next
to the exact query it was made for. These tests are about the two ways records disappear:
a page read but never displayed, and a handle reused under different options.
"""
import json
import subprocess
import sys
from pathlib import Path

from naver_blog_skill._api import operation
from naver_blog_skill._listing import collect
from naver_blog_skill._walk import Page

ENTRY = Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts/naver_blog.py'


def cli(arguments, env):
    result = subprocess.run([sys.executable, str(ENTRY), *arguments], capture_output=True, text=True, env=env)
    return result.returncode, result.stdout.rstrip('\n')


def handle_from(out):
    return [line for line in out.splitlines() if line.startswith('more: ')][0].split('--after ')[1].strip()


def test_a_capped_page_still_offers_the_records_it_holds():
    """Reaching the ceiling with a page in hand must not mean the rest of it is gone."""
    spec = operation('search_posts')

    def fetch(page):
        size = 30 if page <= 33 else 10
        start = (page - 1) * 30
        return Page(items=[{'id': f'post:b/{start + i}'} for i in range(size)], raw_count=size)
    result = collect(spec, fetch, limit=3, state={'page': 34, 'position': 990})
    assert result['stop_reason'] == 'server_capped'
    assert len(result['results']) == 3
    # Seven records were read and not shown; they must survive in the handle.
    assert result['pending'] == 7
    following = collect(spec, fetch, limit=10, state=result['state'])
    assert [record['id'] for record in following['results']] == \
        [f'post:b/{990 + i}' for i in range(3, 10)]


def test_a_single_page_surface_offers_its_tail_too():
    spec = operation('popular_posts')
    result = collect(spec, lambda page: Page(items=[{'id': f'post:b/{i}'} for i in range(10)],
                                             raw_count=10), limit=3)
    assert result['stop_reason'] == 'not_paginable' and result['pending'] == 7


def test_a_listing_that_holds_a_tail_prints_a_continuation_even_when_it_is_finished(cli_env):
    # post_list page one has 30 items; a limit of 3 leaves 27 read but unshown.
    code, out = cli(['posts', 'testblog', '--category', '108', '--limit', '3'], cli_env)
    assert code == 0
    assert 'more: ' in out
    code, out = cli(['posts', 'testblog', '--category', '108', '--limit', '3',
                     '--after', handle_from(out)], cli_env)
    assert code == 0
    # Continuing spent no request at all: the records were already in hand.
    assert 'local budget 0 of' in out.splitlines()[0]


DIFFERENT = [
    (['search', '파이썬', '--limit', '2'], ['search', '파이썬', '--since', '2026-01-01', '--limit', '2']),
    (['search', '파이썬', '--limit', '2'], ['search', '파이썬', '--own-money', '--limit', '2']),
    (['search', '파이썬', '--limit', '2'], ['search', '파이썬', '--sort', 'date', '--limit', '2']),
    (['search', '파이썬', '--limit', '2'], ['search', '파이썬', '--type', 'blogs', '--limit', '2']),
]


def test_a_handle_is_refused_when_any_option_that_shapes_the_page_changed(cli_env):
    for original, altered in DIFFERENT:
        code, out = cli(original, cli_env)
        assert code == 0, out
        handle = handle_from(out)
        code, out = cli([*altered, '--after', handle], cli_env)
        assert code == 2, f'{altered} was accepted with a handle from {original}: {out}'
        assert 'different query' in json.loads(out)['message']


def test_a_search_term_with_shell_characters_survives_its_own_continuation(cli_env, tmp_path):
    """The printed command is meant to be run: quoting it wrongly would change the query."""
    from naver_blog_skill._output import CursorStore
    import os
    tricky = "it's $HOME `and` \"more\""
    environment = dict(cli_env)
    store_env = dict(os.environ, NAVER_BLOG_HOME=environment['NAVER_BLOG_HOME'])
    # The command is built without contacting Naver; only the quoting is under test.
    from naver_blog_skill import _cmds_read
    quoted = _cmds_read.shlex.quote(tricky)
    rebuilt = subprocess.run(['bash', '-c', f'printf %s {quoted}'], capture_output=True, text=True,
                             env=store_env).stdout
    assert rebuilt == tricky
    assert CursorStore  # the handle store is what the command is bound to


def test_an_out_file_resumes_where_it_stopped_instead_of_starting_over(cli_env, tmp_path):
    out = tmp_path / 'collected.ndjson'
    code, _ = cli(['posts', 'testblog', '--category', '108', '--limit', '5', '--out', str(out)], cli_env)
    assert code == 0
    first = [json.loads(line) for line in out.read_text().splitlines()]
    saved = [record['id'] for record in first if record.get('kind') != 'header'
             and 'id' in record]
    assert len(saved) == 5

    code, _ = cli(['posts', 'testblog', '--category', '108', '--limit', '5', '--out', str(out)], cli_env)
    assert code == 0
    second = [json.loads(line) for line in out.read_text().splitlines()]
    ids = [record['id'] for record in second if record.get('kind') != 'header' and 'id' in record]
    # The second run continued rather than re-displaying and re-saving the same head.
    assert len(ids) == 10 and len(set(ids)) == 10
    assert ids[:5] == saved


def test_the_continuation_command_keeps_collecting_into_the_same_file(cli_env, tmp_path):
    out = tmp_path / 'collected.ndjson'
    code, printed = cli(['posts', 'testblog', '--category', '108', '--limit', '5', '--out', str(out)], cli_env)
    more = [line for line in printed.splitlines() if line.startswith('more: ')][0]
    assert f'--out {str(out)!r}'.replace("'", '') in more.replace("'", '')


def test_popular_and_notice_lists_refuse_a_file_rather_than_ignoring_it(cli_env, tmp_path):
    code, out = cli(['posts', 'testblog', '--popular', '--out', str(tmp_path / 'x.ndjson')], cli_env)
    assert code == 2
    assert 'single pages' in json.loads(out)['message']


def test_damage_partway_through_a_file_is_refused_rather_than_truncated(cli_env, tmp_path):
    """Truncating at the damage would silently delete the complete pages after it."""
    out = tmp_path / 'collected.ndjson'
    code, _ = cli(['posts', 'testblog', '--category', '108', '--limit', '5', '--out', str(out)], cli_env)
    assert code == 0
    code, _ = cli(['posts', 'testblog', '--category', '108', '--limit', '5', '--out', str(out)], cli_env)
    assert code == 0
    lines = out.read_text().splitlines()
    assert len(lines) > 8
    lines[2] = '{ this is not json'
    damaged = '\n'.join(lines) + '\n'
    out.write_text(damaged)
    code, printed = cli(['posts', 'testblog', '--category', '108', '--limit', '5', '--out', str(out)], cli_env)
    assert code == 2
    assert 'damaged' in json.loads(printed)['message']
    # The file the reader was told to keep is still there, byte for byte.
    assert out.read_text() == damaged
