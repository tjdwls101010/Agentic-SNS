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
    assert error['ok'] is False and error['error'] == 'argument' and error['message'] and error['fix']
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
    schema = account.run('schema')
    assert schema.code == 0 and schema.calls == []
    assert {row['title'] for row in schema.data['results']} == {'Post', 'Comment', 'Entity', 'ProfileField'}
    doctor = account.run('doctor', responses=[login()])
    assert doctor.code == 0
    assert doctor.data['results'][0]['account_id'] == '100'
    assert account.run('doctor', responses=[login(user='0')]).code == 4


def test_verbose_keeps_one_stdout_document_and_only_safe_diagnostic_metadata(tmp_path):
    result = Account(tmp_path).run('--verbose', 'feed', '--limit', '1', '--json',
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
    result = account.run('--verbose', 'feed', '--limit', '1', responses=[login(), feed_page(['p1'])])
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
    result = Account(tmp_path).run(*args, '--json', responses=responses)
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
    assert parsed.stdout.splitlines() == ['run', str(cli), 'feed', '--sort', 'top', '--limit', '1', '--after', '1']
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


# --- each command shows only its own arguments ---------------------------------------------------------------------

READ = {'--limit', '--since', '--until', '--chars', '--after', '--out', '--json', '--max-requests'}
OPTION_SETS = {
    'feed': READ | {'--sort', '--include-sponsored'},
    'profile': READ,
    'group': READ | {'--sort'},
    'post': {'--limit', '--json', '--max-requests'},
    'comments': {'--sort', '--limit', '--replies', '--chars', '--after', '--out', '--json', '--max-requests'},
    'search': {'--type', '--limit', '--chars', '--after', '--out', '--json', '--max-requests'},
    'about': {'--section', '--json', '--max-requests'},
    'doctor': {'--unblock'},
    'refresh': {'--capture'},
    'schema': set(),
}


@pytest.mark.parametrize('command', sorted(OPTION_SETS))
def test_each_command_offers_exactly_its_own_options(tmp_path, command):
    result = Account(tmp_path).run(command, '--help')
    assert result.code == 0
    offered = set(re.findall(r'^  (--[a-z-]+)', result.stdout, re.M)) - {'--help'}
    assert offered == OPTION_SETS[command]


def test_verbose_is_a_root_option(tmp_path):
    assert '--verbose' in Account(tmp_path).run('--help').stdout
    assert Account(tmp_path).run('feed', '--verbose').code == 2


@pytest.mark.parametrize('args', [['about', 'zuck', '--since', '2026-01-01'], ['post', 'https://www.facebook.com/zuck/posts/1', '--out', 'x'],
                                  ['doctor', '--json'], ['search', 'x', '--since', '2026-01-01'], ['profile', '42', '--sort', 'recent']])
def test_an_option_a_command_does_not_declare_is_an_argument_error(tmp_path, args):
    result = Account(tmp_path).run(*args)
    assert result.code == 2 and result.data['error'] == 'argument' and result.calls == []


def test_schema_and_help_work_without_touching_a_blocked_or_damaged_account(tmp_path):
    account = Account(tmp_path)
    account.home.mkdir(parents=True)
    (account.home / 'blocked.json').write_text('{broken')
    (account.home / 'pace.json').write_text('{broken')
    for args in (['schema'], ['schema', 'post'], ['--help'], ['feed', '--help']):
        result = account.run(*args)
        assert result.code == 0 and result.calls == [], args
    assert account.run('feed').code == 5


# --- one result generator: the result and exit matrix --------------------------------------------------------------

def test_matrix_success_with_records(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['p1', 'p2'])])
    assert (result.code, result.data['ok'], result.data['stop_reason']) == (0, True, 'limit_reached')
    assert (result.data['request_count'], result.data['max_requests']) == (2, 25)


def test_matrix_argument_error(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '0')
    assert (result.code, result.data['ok'], result.data['error']) == (2, False, 'argument')


def test_matrix_aside_unavailable(tmp_path):
    result = Account(tmp_path).run('feed', responses=[{'mode': 'fail'}])
    assert (result.code, result.data['error']) == (3, 'aside')


def test_matrix_login_required(tmp_path):
    result = Account(tmp_path).run('feed', responses=[login(user='0')])
    assert (result.code, result.data['error']) == (4, 'login')


def test_matrix_blocked_now_and_blocked_from_saved_state(tmp_path):
    account = Account(tmp_path)
    now = account.run('feed', '--json', responses=[login(), LIMITED])
    assert (now.code, now.data['error'], now.data['stop_reason']) == (5, 'blocked', 'blocked')
    saved = account.run('feed')
    assert (saved.code, saved.data['error']) == (5, 'blocked') and saved.calls == []


def test_matrix_query_failure_without_records(tmp_path):
    result = Account(tmp_path).run('feed', responses=[login(), envelope({'errors': [{'message': 'x'}]})])
    assert (result.code, result.data['error'], result.data['stop_reason']) == (6, 'failed', 'query_failure')
    assert result.data['fix'] == 'Run refresh, then retry the read command.'


def test_matrix_explicitly_empty(tmp_path):
    result = Account(tmp_path).run('feed', responses=[login(), feed_page([])])
    assert (result.code, result.data['ok'], result.data['error'], result.data['stop_reason']) == (
        7, False, 'empty', 'exhausted')


def test_matrix_partial_result(tmp_path):
    result = Account(tmp_path).run('feed', '--json', responses=[login(), feed_page(['p1'], 'next'),
                                                                envelope({'errors': [{'message': 'x'}]})])
    assert (result.code, result.data['ok'], result.data['error'], result.data['stop_reason']) == (
        8, False, 'partial', 'query_failure')
    assert result.ids == ['p1']


def test_matrix_already_complete_output_file(tmp_path):
    account = Account(tmp_path)
    path = str(tmp_path / 'done.ndjson')
    assert account.run('feed', '--out', path, responses=[login(), feed_page(['p1'])]).code == 0
    result = account.run('feed', '--out', path, '--json', responses=[login()])
    assert (result.code, result.data['ok'], result.data['stop_reason'], result.data['already_complete']) == (
        0, True, 'exhausted', True)


def test_matrix_maintenance(tmp_path):
    doctor = Account(tmp_path).run('doctor', responses=[login()])
    assert (doctor.code, doctor.data['ok'], doctor.data['stop_reason']) == (0, True, 'ready')
    schema = Account(tmp_path).run('schema')
    assert (schema.code, schema.data['stop_reason']) == (0, 'complete')


@pytest.mark.parametrize('pages,message', [
    ([feed_page(['p1'], 'same'), feed_page(['p2'], 'same')], 'Facebook repeated a page cursor.'),
    ([envelope({'data': {'viewer': {'news_feed': {'edges': [{'node': story('p1')}]}}}})],
     'Facebook sent a page without pagination metadata.'),
])
def test_pagination_failures_do_not_send_the_model_to_refresh(tmp_path, pages, message):
    result = Account(tmp_path).run('feed', '--json', responses=[login(), *pages])
    assert result.code == 8 and result.data['message'] == message
    assert 'refresh' in result.data['fix'] and result.data['fix'].startswith('Retry later with the more: command')


def test_text_header_names_scope_and_cost(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', responses=[login(), feed_page(['p1', 'p2'])])
    assert result.stdout.splitlines()[0] == 'feed · sort=top · 1 shown · sponsored_skipped=0 · stopped=limit_reached · requests=2/25'


def test_a_partial_text_page_ends_with_its_failure_before_more(tmp_path):
    result = Account(tmp_path).run('feed', responses=[login(), feed_page(['p1'], 'next'),
                                                      envelope({'errors': [{'message': 'x'}]})])
    assert result.code == 8
    assert result.stdout.splitlines()[-2] == ('coverage: incomplete — Facebook query failed or its expected structure '
                                             'changed. fix: Run refresh, then retry the read command.')
    assert result.stdout.splitlines()[-1].startswith('more: ')


def test_output_failure_is_one_summary_line(tmp_path):
    path = tmp_path / 'fail.ndjson'
    result = Account(tmp_path).run('feed', '--out', str(path), responses=[
        login(), feed_page(['p1'], 'next'), envelope({'errors': [{'message': 'x'}]})])
    assert result.code == 8
    assert len(result.stdout.splitlines()) == 1
    assert result.stdout.startswith(f'feed · 1 saved to {json.dumps(str(path))} · stopped=query_failure · requests=3/25'
                                    ' · resume: uv run ')
    assert result.stdout.rstrip().endswith('error=partial fix=Run refresh, then retry the read command.')
