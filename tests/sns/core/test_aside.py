"""The Aside system (sns.aside) against the scripted fake: account resolution, the one output protocol, the deadline
clamp, and both ways of opening a tab."""
import json

import pytest

from sns.aside import Aside, active_account, parse
from sns.clock import Deadline
from sns.errors import SnsError
from tests.sns.support.browser import Browser


@pytest.fixture
def browser(tmp_path, monkeypatch, data_dir):
    return Browser(tmp_path)


def test_the_active_account_is_resolved_each_invocation_and_overrides_win(browser, monkeypatch):
    browser.flag(account_status='  u1  other@example.com\n* u2  me@example.com  signed in\n').install(monkeypatch)
    assert Aside('threads', Deadline(30)).account == 'u2'
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT', 'u7')
    assert Aside('threads', Deadline(30)).account == 'u7'
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT_THREADS', 'u9')
    assert Aside('threads', Deadline(30)).account == 'u9' and Aside('reddit', Deadline(30)).account == 'u7'
    assert browser.ops().count('account_status') == 1


def test_no_single_active_account_is_an_aside_failure(browser, monkeypatch):
    browser.flag(account_status='  u0\n  u1\n').install(monkeypatch)
    with pytest.raises(SnsError) as caught:
        Aside('x', Deadline(30))
    assert caught.value.kind == 'aside'
    assert active_account('* u0 a\n* u1 b\n') is None and active_account('\x1b[1m* u3\x1b[0m x') == 'u3'


def test_an_unsafe_account_name_is_an_argument_error(browser, monkeypatch):
    browser.install(monkeypatch)
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT', '../u0')
    with pytest.raises(SnsError) as caught:
        Aside('x', Deadline(30))
    assert caught.value.kind == 'argument'


def test_evaluate_run_and_tabs_go_through_one_protocol(browser, monkeypatch):
    browser.tab('T1', 'https://www.threads.com/search')
    browser.respond('threads.state', {'ok': True, 'big': 'x' * 6000})
    browser.respond('reddit.fetch', {'status': 200, 'body': '{}'}, path='/r/a.json')
    browser.install(monkeypatch)
    aside = Aside('threads', Deadline(30))
    assert aside.tabs() == [{'target_id': 'T1', 'url': 'https://www.threads.com/search'}]
    answer = aside.evaluate('T1', '() => 1 // sns-snippet: threads.state', {'a': 1})
    assert answer['ok'] is True and len(answer['big']) == 6000  # read back from chunk lines
    fetched = aside.run('async (args) => { // sns-snippet: reddit.fetch\n }', {'path': '/r/a.json'})
    assert fetched == {'status': 200, 'body': '{}'}
    calls = browser.calls()
    assert [c['op'] for c in calls[-3:]] == ['tabs', 'threads.state', 'reddit.fetch']
    assert all(c['account'] == 'u0' for c in calls if c['op'] != 'account_status')


def test_a_missing_tab_is_told_apart(browser, monkeypatch):
    browser.install(monkeypatch)
    with pytest.raises(SnsError) as caught:
        Aside('x', Deadline(30)).evaluate('GONE', '() => 1 // sns-snippet: x.state', {})
    assert caught.value.reason == 'tab_missing'


def test_a_call_cut_short_by_the_deadline_is_the_time_limit(browser, monkeypatch):
    browser.tab('T1').respond('x.state', {'__sleep': 5, 'ok': True}).install(monkeypatch)
    aside = Aside('x', Deadline(1.5))
    with pytest.raises(SnsError) as caught:
        aside.evaluate('T1', '() => 1 // sns-snippet: x.state', {})
    assert caught.value.kind == 'failed' and caught.value.reason == 'time_limit'


def test_a_call_that_times_out_with_time_to_spare_is_an_aside_failure(browser, monkeypatch):
    browser.tab('T1').respond('x.state', {'__sleep': 5, 'ok': True}).install(monkeypatch)
    aside = Aside('x', Deadline(60))
    with pytest.raises(SnsError) as caught:
        aside.evaluate('T1', '() => 1 // sns-snippet: x.state', {}, seconds=1)
    assert caught.value.kind == 'aside' and caught.value.reason == 'timeout'


def test_opening_a_tab_both_ways(browser, monkeypatch):
    browser.flag(open_ids=['NEW1']).respond('opener', {'tabs': ['OPENED9']}).install(monkeypatch)
    aside = Aside('threads', Deadline(30))
    aside.open('https://www.threads.com/search')
    assert {'target_id': 'NEW1', 'url': 'https://www.threads.com/search'} in aside.tabs()
    with aside.opener() as tab:
        assert tab == 'OPENED9'
    opener = [c for c in browser.calls() if c['op'] == 'opener'][0]
    assert opener['marked'] is True


def test_output_that_cannot_be_read_is_an_aside_failure():
    with pytest.raises(SnsError) as caught:
        parse('nothing here')
    assert caught.value.reason == 'invalid'
    lines = [json.dumps({'kind': 'chunk', 'index': 1, 'body': '1'}), json.dumps({'kind': 'result', 'chunks': 1,
                                                                                 'body': ''})]
    with pytest.raises(SnsError):
        parse('\n'.join(lines))
    assert parse('\x1b[2mlog\x1b[0m\n' + json.dumps({'kind': 'result', 'chunks': 0, 'body': '[1]'})) == [1]


@pytest.mark.skipif(not __import__('shutil').which('node'), reason='node is not installed')
@pytest.mark.parametrize('header', [{'op': 'evaluate', 'tab': 'T'}, {'op': 'load', 'tab': 'T', 'url': 'u', 'seconds': 5},
                                    {'op': 'run'}])
def test_the_cores_own_page_functions_compile_inside_the_program(header, tmp_path):
    """The fake Aside never runs JavaScript, so a page function that breaks the program (a trailing // comment
    swallowing the rest of the call) passes every other test; node checks the real text."""
    import subprocess
    from sns import reading
    from sns.aside import program
    for action, snippet in reading.EMPTY_SNIPPETS.items():
        path = tmp_path / f'{action}.mjs'
        path.write_text(program(header, snippet.replace('{platform}', 'x'), {}))
        done = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
        assert done.returncode == 0, (action, done.stderr[-500:])


@pytest.mark.skipif(not __import__('shutil').which('node'), reason='node is not installed')
def test_the_picture_download_compiles_inside_the_program(tmp_path):
    import subprocess
    from sns.aside import MEDIA, program
    path = tmp_path / 'media.mjs'
    path.write_text(program({'op': 'run'}, MEDIA, {'url': 'u', 'max': 1}))
    done = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-500:]


@pytest.mark.skipif(not __import__('shutil').which('node'), reason='node is not installed')
def test_the_opener_names_its_own_tab_when_another_command_opens_one_meanwhile(tmp_path):
    """Observed live (D10, 2026-10-21): five platforms started together, and while X's opener opened its about:blank
    tab, Threads and Facebook opened theirs; a before/after diff of the tab list then shows two new tabs and X could not
    tell its own (exit 3). The opener runs here under node with Aside's openTab and listBrowserTabs stubbed."""
    import subprocess
    from sns import aside as aside_module
    script = tmp_path / 'opener.mjs'
    script.write_text(
        "const tabs = [{targetId: 'USER1', url: 'https://example.org/'}];\n"
        "const listBrowserTabs = async () => tabs.map(t => ({...t}));\n"
        "const openTab = async (url) => {\n"
        "  tabs.push({targetId: 'OTHER', url: 'https://www.threads.com/'});  // another command, meanwhile\n"
        "  tabs.push({targetId: 'MINE', url});\n"
        "  return {targetId: 'MINE'};\n"
        "};\n"
        "(async () => {\n" + aside_module._OPENER + "})();\n")
    done = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {'kind': 'opened', 'tabs': ['MINE']}
