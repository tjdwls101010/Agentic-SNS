"""The command surface: arguments, help, exit codes, error documents, targets and the continuation form."""
import json
import re
import shutil
import subprocess

import pytest

from tests.facebook.helpers import (CLI, LIMITED, Account, envelope, feed_page, login, more_args,
                                    profile_page, text_more, timeline_page, story)


@pytest.mark.parametrize('args', [
    ['feed', '--limit', '0'], ['comments'], ['feed', '--since', 'bad'],
    ['feed', '--since', '2026-09-05', '--until', '2026-09-01'],
    ['about', 'zuck', '--since', '2026-01-01'],
    ['post', 'https://facebook.com/zuck/posts/123', '--after', '1'],
    ['profile', 'zuck', '--sort', 'top'],
    ['search', 'hi', '--type', 'people', '--since', '2026-01-01'],
    ['feed', '--out', '/tmp/x', '--after', '1'],
])
def test_invalid_arguments_emit_one_json_error_before_any_request(tmp_path, args):
    result = Account(tmp_path).run(*args)
    assert result.code == 2
    error = result.data
    assert error['ok'] is False and error['error'] == 2 and error['message'] and error['fix']
    assert result.calls == []


def test_help_explains_commands_and_resume(tmp_path):
    result = Account(tmp_path).run('comments', '--help')
    assert result.code == 0
    assert '--replies' in result.stdout and '--after' in result.stdout and 'parent' in result.stdout.lower()


def test_root_help_lists_every_exit_code(tmp_path):
    result = Account(tmp_path).run('--help')
    assert result.code == 0
    rows = result.stdout.split('exit codes:')[1].strip().splitlines()
    assert [row.split()[0] for row in rows] == ['0', '2', '3', '4', '5', '6', '7', '8']


def test_schema_is_local_and_doctor_checks_login(tmp_path):
    account = Account(tmp_path)
    schema = account.run('schema', '--json')
    assert schema.code == 0 and schema.calls == []
    assert {row['title'] for row in schema.data['results']} == {'Post', 'Comment', 'Entity', 'ProfileField'}
    doctor = account.run('doctor', '--json', responses=[login()])
    assert doctor.code == 0
    assert doctor.data['results'][0]['account_id'] == '100'
    assert account.run('doctor', responses=[login(user='0')]).code == 4


def test_verbose_keeps_one_stdout_document_and_only_safe_diagnostic_metadata(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', '--json', '--verbose',
                                   responses=[login(dtsg='SECRET-DTSG'), feed_page(['p1'])])
    assert result.code == 0
    assert result.ids == ['p1']
    diagnostics = [json.loads(line) for line in result.stderr.splitlines()]
    assert [(d['stage'], d['count'], d['snippet']) for d in diagnostics] == [('request', 1, 'tokens'),
                                                                          ('request', 2, 'graphql')]
    assert 'SECRET-DTSG' not in result.stderr and 'fb_dtsg' not in result.stderr and 'ARGS' not in result.stderr


def test_verbose_diagnostics_scrub_secrets_that_reach_them_through_a_local_registry(tmp_path):
    account = Account(tmp_path)
    account.home.mkdir(parents=True)
    name = 'Synthetic lsd=private-token https://scontent.example.fbcdn.net/p.jpg?sig=private-signature'
    (account.home / 'registry.json').write_text(json.dumps({'queries': {'newsfeed': {'name': name}}}))
    result = account.run('feed', '--limit', '1', '--verbose', responses=[login(), feed_page(['p1'])])
    assert result.code == 0
    query = json.loads(result.stderr.splitlines()[1])['query']
    assert query == 'Synthetic lsd=[REDACTED] https://scontent.example.fbcdn.net/p.jpg'


@pytest.mark.parametrize('args,responses,code', [
    (['feed', '--limit', '0'], [], 2),
    (['feed'], [{'mode': 'fail'}], 3),
    (['feed'], [login(user='0')], 4),
    (['feed'], [LIMITED], 5),
    (['feed'], [login(), envelope({'errors': [{'message': 'x'}]})], 6),
    (['feed'], [login(), feed_page([])], 7),
    (['feed'], [login(), envelope({'data': {'viewer': {'news_feed': {'edges': [{'node': story('p1')}]}}}})], 8),
])
def test_every_failure_exit_carries_its_recovery_instruction(tmp_path, args, responses, code):
    result = Account(tmp_path).run(*args, responses=responses)
    assert result.code == code
    assert result.data['ok'] is False and result.data['fix']


def allowed_tools_prefix(skill_dir):
    """The SKILL.md allowed-tools pattern with the skill directory substituted, up to its trailing wildcard."""
    front = (skill_dir / 'SKILL.md').read_text(encoding='utf-8').split('---')[1]
    pattern = re.search(r'(?m)^allowed-tools:\s*Bash\((.+) \*\)$', front)[1]
    return pattern.replace('${CLAUDE_SKILL_DIR}', str(skill_dir))


@pytest.mark.parametrize('directory', ['Agentic SNS 스킬', 'odd "$HOME" `x` \\ dir'])
def test_more_is_the_allowed_tools_invocation_of_the_invoked_cli(tmp_path, directory):
    skill = tmp_path / directory / 'facebook'
    shutil.copytree(CLI.parents[1], skill, ignore=shutil.ignore_patterns('__pycache__'))
    cli = skill / 'scripts/cli.py'
    result = Account(tmp_path, cli).run('feed', '--limit', '1', responses=[login(), feed_page(['p1', 'p2'])])
    assert result.code == 0, result.stdout + result.stderr
    more = text_more(result.stdout)
    # A POSIX shell, not shlex, decides what the copied line means; this uv only prints its arguments.
    parsed = subprocess.run(['sh', '-c', 'uv() { printf "%s\\n" "$@"; }\n' + more], capture_output=True, text=True)
    assert parsed.stdout.splitlines() == ['run', str(cli), 'feed', '--sort', 'top', '--limit', '1', '--chars', '180',
                                          '--after', '1']
    if '"' not in directory:
        assert more.startswith(allowed_tools_prefix(skill) + ' ')


# --- targets are normalized before any request --------------------------------------------------------------------

def continued_target(account, *args):
    result = account.run(*args, '--limit', '1', '--json',
                         responses=[login(), timeline_page([story('p1'), story('p2')])])
    assert result.code == 0, result.stdout
    return more_args(result.data['next'])[1]


def test_profile_handles_normalize_to_the_same_target_without_resolving_numeric_ids(tmp_path):
    account = Account(tmp_path)
    numeric = continued_target(account, 'profile', '42')
    assert numeric == 'https://www.facebook.com/profile.php?id=42'
    assert continued_target(account, 'profile', 'https://m.facebook.com/profile.php?foo=x&id=42') == numeric
    assert continued_target(account, 'profile', 'https://www.facebook.com/people/Synthetic/42/') == numeric
    assert account.runs == 3


def test_vanity_and_about_links_keep_the_profile_target(tmp_path):
    account = Account(tmp_path)
    targets = []
    for value in ('zuck', 'https://www.facebook.com/zuck/', 'https://www.facebook.com/zuck/about'):
        result = account.run('profile', value, '--limit', '1', '--json',
                             responses=[login(), profile_page('4'), timeline_page([story('p1'), story('p2')])])
        assert result.code == 0, result.stdout
        assert result.snippets == ['tokens', 'page', 'graphql']
        assert result.graphql()['variables']['id'] == '4'
        targets.append(more_args(result.data['next'])[1])
    assert targets == ['https://www.facebook.com/zuck'] * 3


@pytest.mark.parametrize('value', ['https://facebook.com.evil.test/x', 'https://evil@facebook.com/x', 'file:///x',
                                   'https://facebook.com:443/x', 'https://facebook.com/../x'])
@pytest.mark.parametrize('command', ['profile', 'group', 'post'])
def test_untrusted_urls_are_rejected_before_any_request(tmp_path, command, value):
    result = Account(tmp_path).run(command, value)
    assert result.code == 2 and result.calls == []


@pytest.mark.parametrize('value', ['groups', 'search', 'https://www.facebook.com/watch/'])
def test_nonprofile_surfaces_are_not_profile_handles(tmp_path, value):
    result = Account(tmp_path).run('profile', value)
    assert result.code == 2 and result.calls == []


# --- the query registry --------------------------------------------------------------------------------------------

RELAY_FLAG = re.compile(r'__relay_internal__pv__[A-Za-z0-9_]+relayprovider')


def test_bundled_registry_sends_its_query_ids_and_provider_flags(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', responses=[login(), feed_page(['p1'])])
    call = result.graphql()
    assert (call['name'], call['doc_id']) == ('CometNewsFeedPaginationQuery', '27790894430578947')
    flags = {k: v for k, v in call['variables'].items() if RELAY_FLAG.fullmatch(k)}
    assert len(flags) == 46
    assert flags['__relay_internal__pv__StoriesShouldEnablePhotosensitiveContentWarningrelayprovider'] is False
    assert flags['__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider'] == 'AUTO_TRANSLATE'


def test_search_text_is_set_per_request_and_does_not_leak_between_pages(tmp_path):
    pages = [envelope({'data': {'serpResponse': {'results': {'edges': [{'node': {
        '__typename': 'Page', 'id': ident, 'name': 'Synthetic', 'url': 'https://www.facebook.com/' + ident}}],
        'page_info': {'has_next_page': cursor is not None, 'end_cursor': cursor}}}}}) for ident, cursor in
        (('a', 'next'), ('b', None))]
    result = Account(tmp_path).run('search', 'synthetic text', '--type', 'pages', '--json', responses=[login(), *pages])
    assert result.code == 0
    first, second = result.graphql(0)['variables'], result.graphql(1)['variables']
    assert first['args']['text'] == second['args']['text'] == 'synthetic text'
    assert first['args']['experience']['type'] == 'PAGES_TAB'
    assert first['args']['callsite'] == 'COMET_GLOBAL_SEARCH'
    assert (first['count'], first['cursor'], second['cursor']) == (5, None, 'next')


@pytest.mark.parametrize('search_type,experience', [('top', 'GLOBAL_SEARCH'), ('posts', 'POSTS_TAB'),
                                                    ('people', 'PEOPLE_TAB'), ('pages', 'PAGES_TAB'),
                                                    ('groups', 'GROUPS_TAB')])
def test_every_search_type_selects_its_result_vertical(tmp_path, search_type, experience):
    result = Account(tmp_path).run('search', 'synthetic', '--type', search_type,
                                   responses=[login(), envelope({'data': {'serpResponse': {'results': {
                                       'edges': [], 'page_info': {'has_next_page': False}}}}})])
    assert result.graphql()['variables']['args']['experience']['type'] == experience


def test_local_registry_override_replaces_only_the_named_query(tmp_path):
    account = Account(tmp_path)
    account.home.mkdir(parents=True)
    (account.home / 'registry.json').write_text(json.dumps({'queries': {'newsfeed': {'doc_id': '123'}}}))
    feed = account.run('feed', '--limit', '1', responses=[login(), feed_page(['p1'])])
    assert feed.code == 0 and feed.graphql()['doc_id'] == '123'
    profile = account.run('profile', '42', '--limit', '1', responses=[login(), timeline_page([story('p1')])])
    assert profile.code == 0 and profile.graphql()['doc_id'] == '27676223615330440'
    (account.home / 'registry.json').write_text('{broken')
    broken = account.run('feed', '--limit', '1', responses=[login(), feed_page(['p1'])])
    assert broken.code == 6 and broken.snippets == ['tokens']


def test_post_permalinks_normalize_before_the_story_lookup(tmp_path):
    result = Account(tmp_path).run('post', 'https://m.facebook.com/story.php?story_fbid=9&id=4&x=1', '--json',
                                   responses=[login(), envelope('"storyID":"s"'),
                                              envelope({'data': {'node': {'feedback': {'id': 'f'},
                                                                          'message': {'text': 'x'}}}}),
                                              envelope({'data': {'node': {'comments': {
                                                  'edges': [], 'page_info': {'has_next_page': False}}}}})])
    assert result.calls[1]['args']['url'] == 'https://www.facebook.com/permalink.php?story_fbid=9&id=4'
    assert result.graphql()['referer'] == 'https://www.facebook.com/permalink.php?story_fbid=9&id=4'
