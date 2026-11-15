"""The Aside system (sns.aside) against the scripted fake: account resolution, the one output protocol, the deadline
clamp, opening a tab, and the cause each Aside failure names."""
import json

import pytest

import sns.aside
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


def test_opening_a_tab(browser, monkeypatch):
    browser.flag(open_ids=['NEW1']).install(monkeypatch)
    aside = Aside('threads', Deadline(30))
    aside.open('https://www.threads.com/search')
    assert {'target_id': 'NEW1', 'url': 'https://www.threads.com/search'} in aside.tabs()
    assert [c['op'] for c in browser.calls()] == ['account_status', 'open', 'tabs']


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


def _run_media(tmp_path, fetch_body):
    import subprocess
    from sns.aside import MEDIA
    script = tmp_path / 'media.mjs'
    script.write_text("const requests = [];\nglobalThis.fetch = async (url, options) => {\n  requests.push({url, redirect: "
                      "options.redirect});\n" + fetch_body + "\n};\nconst download = " + MEDIA + ";\n"
                      "const answer = await download({url: 'https://pbs.twimg.com/media/P1.jpg', max: 1024});\n"
                      "console.log(JSON.stringify({requests, answer}));\n")
    done = subprocess.run(['node', str(script)], text=True, capture_output=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(not __import__('shutil').which('node'), reason='node is not installed')
def test_a_picture_that_redirects_is_not_followed_to_another_host(tmp_path):
    """Found by review (2026-10-21): with redirect 'follow' the browser fetched a second address after the host check,
    off the platform's image hosts and outside the one request a picture is. A redirect is that picture's failure."""
    out = _run_media(tmp_path, "  return {type: 'opaqueredirect', status: 0, headers: new Headers(), "
                               "arrayBuffer: async () => new ArrayBuffer(0)};")
    assert [r['redirect'] for r in out['requests']] == ['manual'] and out['answer']['redirect'] is True


@pytest.mark.skipif(not __import__('shutil').which('node'), reason='node is not installed')
def test_a_picture_the_browser_cannot_reach_is_that_pictures_failure(tmp_path):
    out = _run_media(tmp_path, "  throw new TypeError('fetch failed');")
    assert out['answer']['status'] == 0 and 'fetch failed' in out['answer']['network']


@pytest.mark.parametrize('answer, reason', [({'status': 0, 'redirect': True}, 'redirect'),
                                            ({'status': 0, 'network': 'TypeError: fetch failed'}, 'network')])
def test_a_redirect_or_an_unreachable_host_is_a_partial_failure_of_that_picture(browser, monkeypatch, answer, reason):
    browser.respond('aside.media', answer, url='https://pbs.twimg.com/media/P1.jpg').install(monkeypatch)
    with pytest.raises(SnsError) as caught:
        Aside('x', Deadline(30)).download('https://pbs.twimg.com/media/P1.jpg', 1024)
    assert caught.value.kind == 'partial' and caught.value.reason == reason


@pytest.mark.skipif(not __import__('shutil').which('node'), reason='node is not installed')
def test_a_picture_whose_body_breaks_off_is_that_pictures_failure(tmp_path):
    """Found by the second review: an error while the body arrived escaped the catch and failed the whole command."""
    out = _run_media(tmp_path, "  return {status: 200, type: 'basic', headers: new Headers({'content-type': 'image/jpeg'}), "
                               "arrayBuffer: async () => { throw new TypeError('terminated'); }};")
    assert out['answer']['status'] == 0 and 'terminated' in out['answer']['network']


def test_each_cause_of_an_aside_failure_names_its_own_remedy(browser, monkeypatch, tmp_path):
    """Every Aside failure used to say 'Check that Aside is running', also when Aside was running and had changed how
    it answers (live, 2026-11-15: x doctor after an Aside update). Each cause now has its own fix."""
    causes = {}
    with monkeypatch.context() as patched:  # no `aside` command at all
        patched.setenv('SNS_ASIDE_BIN', '')
        patched.setenv('PATH', str(tmp_path / 'empty'))
        with pytest.raises(SnsError) as caught:
            Aside('reddit', Deadline(30))
        causes['missing'] = caught.value
    with monkeypatch.context() as patched:  # the account cannot be told
        browser.flag(account_status_exit=1).install(patched)
        with pytest.raises(SnsError) as caught:
            Aside('reddit', Deadline(30))
        causes['account'] = caught.value
    with monkeypatch.context() as patched:  # Aside is closed: the `aside` command starts it, slower than the wait
        patched.setattr(sns.aside, 'STATUS_SECONDS', 0.5)
        browser.flag(account_status_exit=0, account_status_sleep=2).install(patched)
        with pytest.raises(SnsError) as caught:
            Aside('reddit', Deadline(30))
        causes['starting'] = caught.value
    browser.flag(account_status_sleep=0, version='9.9.9').install(monkeypatch)
    browser.respond('reddit.fetch', {'__raw_stdout': 'aside: daemon is not reachable\n', '__exit': 1})
    browser.respond('reddit.fetch', {'__raw_stdout': 'nothing this skill can read\n'}).install(monkeypatch)
    aside = Aside('reddit', Deadline(30))
    for name in ('unreachable', 'unexpected'):
        with pytest.raises(SnsError) as caught:
            aside.run('async (args) => { // sns-snippet: reddit.fetch\n }', {})
        causes[name] = caught.value
    assert {name: error.reason for name, error in causes.items()} == {
        'missing': 'missing', 'account': 'account', 'starting': 'unreachable', 'unreachable': 'lost',
        'unexpected': 'invalid'}
    assert all(error.kind == 'aside' for error in causes.values())
    assert 'Install Aside' in causes['missing'].fix and 'SNS_ASIDE_ACCOUNT' in causes['account'].fix
    assert causes['starting'].fix == causes['unreachable'].fix and 'Start the Aside app' in causes['unreachable'].fix
    assert 'Aside 9.9.9' in causes['unexpected'].message and 'may not match Aside 9.9.9' in causes['unexpected'].fix
    assert len({causes[name].fix for name in ('missing', 'account', 'unreachable', 'unexpected')}) == 4
    assert not any('Check that Aside is running' in error.fix for error in causes.values())
