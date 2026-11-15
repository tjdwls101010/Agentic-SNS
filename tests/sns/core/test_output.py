"""What a reading leaves the model, through cli.main with the stub platforms and the fake Aside: the text page's first
block (what was read, what is missing, the next command) before the records, so output cut off by a tool limit keeps
it."""
import pytest

import cli
from tests.sns.support.browser import Browser
from tests.sns.support.stub_platform import STUBS, STUB_COMMANDS


@pytest.fixture
def browser(tmp_path, monkeypatch, data_dir):
    monkeypatch.setenv('SNS_IDLE_SECONDS', 'off')
    return Browser(tmp_path)


def run(capsys, browser, monkeypatch, *argv):
    browser.install(monkeypatch)
    code = cli.main([str(a) for a in argv], platforms=STUBS, commands=STUB_COMMANDS)
    return code, capsys.readouterr().out


def item(n, day='2026-10-10', hour=12):
    return {'id': f'i{n}', 'text': f'post {n}', 'url': f'https://alpha.test/p/i{n}',
            'created_at': f'{day}T{hour:02d}:00:00+09:00'}


def feed(browser, cursor, items, following=None, **extra):
    browser.respond('alpha.get', {'status': 200, 'body': {'items': items, 'next': following, **extra}},
                    path='/feed', cursor=cursor)


def me(browser, viewer='ann'):
    browser.respond('alpha.get', {'status': 200, 'body': {'viewer': viewer}}, path='/me')


def test_the_first_block_comes_before_the_records(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1, '2026-10-11'), item(2, '2026-10-11')], 'C2', promoted=1)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--since', '2026-10-01', '--limit', '2')
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith('alpha feed · 2 shown · stopped=limit_reached')
    assert lines[1].startswith('window 2026-10-01.. KST · open')
    assert lines[2] == 'coverage: 1 promoted entries (ads) left out'
    assert lines[3].startswith('more: uv run "')
    assert lines[4].startswith('[p1] i1 ') and lines[5].startswith('[p2] i2 ') and len(lines) == 6


def test_an_incomplete_read_says_so_before_the_records(capsys, browser, monkeypatch):
    me(browser)
    feed(browser, None, [item(1)], 'C2')
    browser.respond('alpha.get', {'status': 500, 'body': {}}, path='/feed', cursor='C2')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '5')
    assert code == 8
    lines = out.splitlines()
    assert lines[1] == 'coverage: incomplete — Alpha answered 500. fix: Retry later.'
    assert lines[-1].startswith('[p1] i1 ')
