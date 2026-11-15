"""Regression checks for the shared author, advertisement and command contracts."""
from dataclasses import fields
import ast
import subprocess
import sys
from pathlib import Path

import pytest

from sns.x import PLATFORM as x_platform, web as x_web
from sns.threads import PLATFORM as threads_platform
from sns.reddit import PLATFORM as reddit_platform
from sns.naver_blog import web as naver_web
from tests.sns.support.cli import CLI
from tests.sns.facebook.data import fixture


@pytest.mark.parametrize('render', [x_platform.render, threads_platform.render])
def test_unknown_author_object_renders_unavailable(render):
    [text] = render({'results': [{'kind': 'post', 'author': {'name': None, 'id': None, 'url': None}}]}, 0, 'feed')
    assert 'unavailable' in text.splitlines()[0] and '@?' not in text


def test_reddit_unknown_author_does_not_render_a_fake_username():
    record = {'kind': 'post', 'subreddit': 'example', 'author': {'name': None, 'id': None, 'url': None}}
    [text] = reddit_platform.render({'results': [record]}, 0, 'feed')
    assert 'unavailable' in text and 'u/None' not in text


@pytest.mark.parametrize('kind', ['account', 'list', 'community', 'notification', 'space'])
def test_any_promoted_x_record_is_marked(kind):
    [line] = x_platform.render({'results': [{'kind': kind, 'id': '1', 'name': 'Example', 'promoted': True}]}, 0, 'feed')
    assert line.startswith('[ad] ')


def test_obsolete_ad_counters_and_feed_flags_are_removed():
    assert 'promoted' not in {f.name for f in fields(x_web.walk([]))}
    assert 'promoted' not in {f.name for f in fields(x_web.list_page([]))}
    assert 'author' not in {f.name for f in fields(naver_web.PostDoc)}
    for platform in ('x', 'threads'):
        source = Path(CLI).parent / 'sns' / platform / 'listing.py'
        function = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'flags')
        assert ast.literal_eval(function.args.defaults[-1]) == ('tab', 'sort')


def test_facebook_paging_fixture_describes_included_ads():
    scenario = next(s for s in fixture('paging.json')['scenarios'] if s['name'] == 'sponsored-skipped-once')
    assert scenario['expected']['shown'] == ['AD1']
    assert scenario['then']['expected']['shown'] == ['A', 'B', 'C']
    assert 'skipped' not in scenario['fact'].lower()


def test_naver_me_help_describes_groups_and_only_supported_options():
    result = subprocess.run([sys.executable, str(CLI), 'naver-blog', 'me', '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    body = ' '.join(result.stdout.split('exit codes:')[0].split())
    assert 'neighbor groups' in body and 'one page' in body
    assert '--group' not in body and 'followers' not in body and '--limit' not in body
    assert '--after' not in body and '--out' not in body
