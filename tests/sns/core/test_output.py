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


def test_a_more_line_a_day_old_fails_with_the_command_that_starts_the_reading_again(capsys, browser, monkeypatch, data_dir):
    """L1: the next day a more: line's handle has expired; its error gives, word for word, the command that reads the
    same thing from the start (the more: line without --after)."""
    import json
    import re
    me(browser)
    feed(browser, None, [item(1), item(2)], 'C2')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '1')
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    number = re.search(r'--after (\d+)', more).group(1)
    path = data_dir / 'handles' / f'{number}.json'
    record = json.loads(path.read_text())
    record['created_at'] -= 25 * 3600
    path.write_text(json.dumps(record))
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '1', '--after', number)
    envelope = json.loads(out)
    assert code == 2 and 'expired' in envelope['message']
    assert envelope['fix'].endswith(more[len('more: '):].replace(f' --after {number}', ''))


# --- the whole result kept as a file (A10) ---------------------------------------------------------------------------

def test_a_read_keeps_its_whole_result_in_a_private_file_the_first_line_names(capsys, browser, monkeypatch, data_dir):
    import json
    import os
    me(browser)
    feed(browser, None, [item(1), item(2)], 'C2')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '1', '--json')
    envelope = json.loads(out)
    path = envelope['saved']
    assert code == 0 and os.path.isabs(path) and path.startswith(str(data_dir / 'results'))
    assert json.loads(open(path).read()) == envelope  # the file is the --json envelope, saved field included
    assert os.stat(path).st_mode & 0o077 == 0
    me(browser)
    feed(browser, None, [item(1), item(2)], 'C2')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '1')
    first = out.splitlines()[0]
    assert first.endswith(' · saved=' + first.rsplit('saved=', 1)[1]) and first.rsplit('saved=', 1)[1] != path


def test_no_file_for_a_read_without_records_or_one_collected_into_out(capsys, browser, monkeypatch, data_dir, tmp_path):
    import json
    browser.respond('alpha.get', {'status': 500, 'body': {}}, path='/me')
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--limit', '1', '--json')
    assert code != 0 and 'saved' not in json.loads(out)
    me(browser)
    feed(browser, None, [item(1)], None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--out', str(tmp_path / 'f.ndjson'), '--json')
    assert code == 0 and 'saved' not in json.loads(out)
    assert not (data_dir / 'results').exists() or not list((data_dir / 'results').glob('*.json'))


def test_files_a_day_old_go_at_the_next_read(capsys, browser, monkeypatch, data_dir):
    import json
    import os
    import time
    me(browser)
    feed(browser, None, [item(1)], None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--json')
    old = json.loads(out)['saved']
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    me(browser)
    feed(browser, None, [item(2)], None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--json')
    assert not os.path.exists(old) and os.path.exists(json.loads(out)['saved'])


def test_a_file_that_cannot_be_written_does_not_fail_the_read(capsys, browser, monkeypatch, data_dir):
    import json
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'results').write_text('a file where the directory goes')
    me(browser)
    feed(browser, None, [item(1)], None)
    code, out = run(capsys, browser, monkeypatch, 'alpha', 'feed', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['saved'] == 'unavailable'
    assert any('saved' in line or 'file' in line for line in envelope['coverage'])
