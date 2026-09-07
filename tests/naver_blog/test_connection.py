"""The wired path, not the pure function: what doctor and Transport.get actually do."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


from naver_blog_skill._budget import cache_dir, history, set_blocked

ENTRY = Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts/naver_blog.py'
FIXTURES = Path(__file__).parent / 'fixtures'


def run(arguments, env):
    result = subprocess.run([sys.executable, str(ENTRY), *arguments], capture_output=True, text=True, env=env)
    return result.returncode, json.loads(result.stdout or '{}')


FIXTURES = Path(__file__).parent / 'fixtures'


def using(cli_env, folder):
    return dict(cli_env, NAVER_BLOG_FIXTURES=str(FIXTURES / folder))


def test_a_login_redirect_reaches_the_caller_as_a_login_error(cli_env):
    """The pure classifier says 4; this proves the wiring does not turn it into a redirect error."""
    code, payload = run(['doctor'], using(cli_env, 'login'))
    assert code == 4, payload
    assert payload['error'] == 'login' and 'Aside' in payload['fix']


def test_a_maintenance_page_is_a_shape_change_rather_than_a_logout(cli_env):
    code, payload = run(['doctor'], using(cli_env, 'maintenance'))
    assert code == 6 and payload['error'] == 'envelope_drift'


def test_a_rate_limited_response_writes_the_block_file_for_the_next_command(cli_env, monkeypatch):
    monkeypatch.setenv('NAVER_BLOG_HOME', cli_env['NAVER_BLOG_HOME'])
    code, payload = run(['doctor'], using(cli_env, 'ratelimited'))
    assert code == 5 and payload['error'] == 'rate_limit'
    record = json.loads((cache_dir() / 'blocked.json').read_text())
    assert record['reason'] == 'rate_limit' and record['expires_at'] > time.time()
    # A second command is refused without spending a request at all.
    before = len(history())
    code, payload = run(['doctor'], using(cli_env, 'ratelimited'))
    assert code == 5 and len(history()) == before


def test_unblock_keeps_the_block_when_the_probe_cannot_identify_the_account(cli_env, monkeypatch):
    """An HTTP 200 maintenance page is not proof the account is fine."""
    monkeypatch.setenv('NAVER_BLOG_HOME', cli_env['NAVER_BLOG_HOME'])
    set_blocked()
    before = len(history())
    code, _ = run(['doctor', '--unblock'], using(cli_env, 'maintenance'))
    assert code == 6
    assert (cache_dir() / 'blocked.json').exists()
    # The probe still spent a request, and clearing a block never resets the window.
    assert len(history()) == before + 1


def test_unblock_clears_the_block_once_the_probe_identifies_the_account(cli_env, monkeypatch):
    monkeypatch.setenv('NAVER_BLOG_HOME', cli_env['NAVER_BLOG_HOME'])
    set_blocked()
    code, payload = run(['doctor', '--unblock'], cli_env)
    assert code == 0 and payload['viewer'] == 'testviewer'
    assert not (cache_dir() / 'blocked.json').exists()
    assert len(history()) == 1


def test_a_block_recorded_after_the_probe_is_not_cleared_by_it(monkeypatch, tmp_path):
    """Another process's fresh 429 belongs to a later request than the one being verified."""
    from naver_blog_skill._budget import blocked_since, clear_blocked
    monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'home'))
    set_blocked()
    recorded_at = blocked_since()
    time.sleep(0.01)
    set_blocked()
    assert clear_blocked(only_if_recorded_at=recorded_at) is False
    assert (cache_dir() / 'blocked.json').exists()


def test_an_aside_failure_still_spends_the_slot_it_reserved(cli_env, monkeypatch):
    monkeypatch.setenv('NAVER_BLOG_HOME', cli_env['NAVER_BLOG_HOME'])
    broken = dict(cli_env, NAVER_BLOG_ASIDE_BIN='/nonexistent/aside')
    code, payload = run(['doctor'], broken)
    assert code == 3 and payload['error'] == 'aside'
    # Naver may or may not have seen it; the local count assumes it did.
    assert len(history()) == 1


CONTENDER = '''
import os, sys, time, json
sys.path.insert(0, {scripts!r})
from scripts._budget import Budget, history
from scripts._errors import NaverBlogError
# Start together so both processes reach the lock at the same moment.
target = float(os.environ["START_AT"])
while time.time() < target:
    pass
try:
    with Budget(5).request():
        pass
    print("sent")
except NaverBlogError as error:
    print("refused", error.code)
'''


def test_two_processes_racing_for_the_last_slot_do_not_both_get_it(tmp_path):
    scripts = str(Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts/..')
    home = tmp_path / 'home'
    home.mkdir()
    from naver_blog_skill import _budget
    now = time.time()
    (home / 'budget.json').write_text(json.dumps({'requests': [now] * (_budget.WINDOW_LIMIT - 1)}))
    environment = dict(os.environ, NAVER_BLOG_HOME=str(home), NAVER_BLOG_NO_PACING='1',
                       START_AT=str(time.time() + 0.4))
    program = CONTENDER.format(scripts=scripts)
    processes = [subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE, text=True,
                                  env=environment) for _ in range(2)]
    outputs = [process.communicate()[0].strip() for process in processes]
    assert sorted(outputs) == ['refused 5', 'sent'], outputs
    remaining = json.loads((home / 'budget.json').read_text())['requests']
    assert len(remaining) == _budget.WINDOW_LIMIT


def using_fixtures(cli_env, folder):
    return dict(cli_env, NAVER_BLOG_FIXTURES=str(FIXTURES / folder))


def test_a_page_about_a_different_post_is_refused_before_anything_is_built(cli_env):
    """Another post's body next to this post's counts is worse than no answer at all."""
    code, payload = run(['post', 'testblog/99900000101'], using_fixtures(cli_env, 'wrongpost'))
    assert code == 6 and payload['error'] == 'envelope_drift'
    assert '99900000999' in payload['message']
    # It never went on to ask for recommendations.
    requests = [json.loads(line)['path'] for line in
                Path(cli_env['NAVER_BLOG_FAKE_LOG']).read_text().splitlines()]
    assert not any('related' in path for path in requests)


def test_a_blocked_comment_read_does_not_become_a_post_with_no_comments(cli_env):
    code, payload = run(['post', 'testblog/99900000101', '--comments', '--json'],
                        using_fixtures(cli_env, 'blockedcomments'))
    sections = {section['name']: section for section in payload['sections']}
    assert sections['post']['ok'] is True
    assert sections['comments']['ok'] is False
    assert sections['comments']['error']['code'] == 5
    # A block is not "partial": the next command will fail the same way.
    assert code == 5


def test_a_post_written_to_a_file_actually_reaches_it(cli_env, tmp_path):
    out = tmp_path / 'one-post.ndjson'
    code, payload = run(['post', 'testblog/99900000101', '--out', str(out), '--json'], cli_env)
    assert code == 0, payload
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert lines[0]['kind'] == 'header'
    saved = [line for line in lines if line.get('id', '').startswith('post:')]
    assert any(record['id'] == 'post:testblog/99900000101' for record in saved)
    assert saved[0]['body']['text']
