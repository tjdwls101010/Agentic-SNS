"""The real cli.py as a subprocess, as the model runs it: a command reads through the fake Aside, and a more: line names
the cli.py path the caller invoked (a symlinked skill included), so it runs as written and matches the permission rule."""
import json
import os
import subprocess
import sys
import time

from tests.sns.naver_blog.scene import M, response
from tests.sns.naver_blog.shapes import post_items, search_page
from tests.sns.support.browser import Browser
from tests.sns.support.cli import CLI, REPO, more_line, run_cli

SKILL = REPO / '.claude/skills/sns'


def scripted(tmp_path, envelope, **match):
    root = tmp_path / 'browser'
    root.mkdir()
    browser = Browser(root)
    browser.respond('naver_blog.fetch', {'status': 200, 'url': 'x', 'location': None, 'content_type': 'application/json',
                                         'b64': None, **envelope}, **match)
    return browser


def test_a_command_reads_through_the_real_entry_point(tmp_path, data_dir):
    browser = scripted(tmp_path, {'body': json.dumps(response('test_cli_new-26'))}, host=M, path='/api/related-keywords')
    done = run_cli('naver-blog', 'keywords', '성수', '카페', browser=browser,
                   env={'SNS_DATA_DIR': str(data_dir), 'SNS_IDLE_SECONDS': 'off'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith('naver-blog keywords · kind=related · target=성수 카페 · 15 shown') and '[k15] 연관14' in done.stdout


def test_more_uses_the_path_the_cli_was_invoked_with(tmp_path, data_dir):
    link = tmp_path / 'linked-skill'
    os.symlink(SKILL, link)
    browser = scripted(tmp_path, {'body': json.dumps(search_page(post_items(30)))}, host=M, path='/api/search/v1/post')
    browser.write()
    viewer = data_dir / 'naver_blog' / 'u0' / 'session'
    viewer.mkdir(parents=True)
    (viewer / 'viewer.json').write_text(json.dumps({'viewer': 'viewer_blog', 'seen_at': time.time()}))
    done = subprocess.run([sys.executable, str(link / 'scripts/cli.py'), 'naver-blog', 'search', '카페'],
                          capture_output=True, text=True, env={**os.environ, **browser.env(), 'SNS_DATA_DIR': str(data_dir),
                                                                'SNS_IDLE_SECONDS': 'off'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert f'uv run "{link}/scripts/cli.py"' in more_line(done.stdout) and str(CLI) not in more_line(done.stdout)
