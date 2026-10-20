"""What is Threads' own in the skill's tree (the tree, the import directions, interface-only access and snippet ownership
are tests/sns/core/test_structure.py's, which run over every platform package that exists): the threads package's folders
and modules, its adapter, the page functions of its system, and the names of the old skill that must not come back."""
import re
from pathlib import Path

from sns import threads
from sns.threads import web
from tests.sns.support.policies import POLICIES

PACKAGE = Path(threads.__file__).resolve().parent
WEB = PACKAGE / 'web'
FEATURES = {'listing', 'thread', 'search', 'about', 'images', 'render'}


def sources(root=PACKAGE):
    return [p for p in root.rglob('*.py') if '__pycache__' not in p.parts]


def test_the_threads_package_is_its_interface_its_feature_modules_and_the_system_web():
    modules = {p.stem for p in PACKAGE.glob('*.py')} - {'__init__'}
    folders = {p.name for p in PACKAGE.iterdir() if p.is_dir() and p.name != '__pycache__'}
    assert modules == FEATURES and folders == {'web'}  # web is the only folder; Threads has no store of its own


def test_the_interface_is_platform_commands_and_choices():
    assert threads.PLATFORM.key == 'threads' and threads.PLATFORM.word == 'threads' and threads.PLATFORM.transport == 'tab'
    assert threads.PLATFORM.title == 'Threads' and threads.PLATFORM.site == 'threads.com'
    assert list(threads.COMMANDS) == ['feed', 'profile', 'about', 'graph', 'me', 'search', 'post', 'replies', 'quotes',
                                      'reposts', 'images']
    assert set(threads.CHOICES) and all(key.split('.')[0] in threads.COMMANDS for key in threads.CHOICES)


def test_the_adapters_policy_is_the_plans_threads_row():
    assert threads.PLATFORM.policy == POLICIES['threads']
    assert threads.PLATFORM.unblock_scope is None and threads.PLATFORM.idle_action == 'blank'
    assert threads.PLATFORM.window.unit_key == 'unit' and threads.PLATFORM.window.tz is None
    assert threads.PLATFORM.window.pinned_key == 'pinned'


def test_the_query_snapshot_names_twenty_one_reads_none_of_them_a_mutation():
    assert len(web.QUERIES) == 21
    assert not [k for k, q in web.QUERIES.items() if q['name'] and 'Mutation' in q['name']]


def test_the_systems_page_functions_are_exactly_the_snippets_and_the_kit():
    files = {p.name for p in WEB.glob('*.js')}
    assert files == {'kit.js', *(f'{name}.js' for name in web.SNIPPET_NAMES)}


def test_every_page_function_starts_by_naming_itself_threads_dot_its_file():
    for path in WEB.glob('*.js'):
        assert path.read_text(encoding='utf-8').splitlines()[0] == f'// sns-snippet: threads.{path.stem}', path.name


def test_no_page_function_spells_the_word_the_repl_refuses():
    for path in WEB.glob('*.js'):
        assert 'require(' not in path.read_text(encoding='utf-8'), path.name
    for name in web.SNIPPET_NAMES:
        assert 'require(' not in web.snippet(name), name


def test_the_old_skills_names_are_gone_from_the_package():
    """Environment variables are SNS_*, there is no request budget, no state lives in a cache directory, and the records
    carry the shared names (pinned, parent_id), not the old ones."""
    old = re.compile(r'(?<![A-Z_])THREADS_[A-Z]|max-requests|max_requests|\.cache/|ThreadsError|from threads\b'
                     r"|'is_pinned'|'reply_to_id'")
    problems = [f'{p.relative_to(PACKAGE)}: {m[0]}' for p in [*sources(), *WEB.glob('*.js')]
                for m in old.finditer(p.read_text(encoding='utf-8'))
                # reply_to_id is the wire name of the field Threads sends; the record's own key is parent_id
                if not (m[0] == "'reply_to_id'" and p.name in ('posts.py',))]
    assert not problems, problems


def test_the_system_never_imports_a_feature_module_or_the_pipeline():
    """web is what the platform's features stand on: it knows helpers and itself only (the core test checks the unit
    rule over all platforms; this names the modules for Threads)."""
    for path in sources(WEB):
        for module in re.findall(r'^(?:from|import) (sns[\w.]*)', path.read_text(encoding='utf-8'), re.M):
            assert module.split('.')[1:2] != ['reading'] and not re.match(
                r'sns\.threads\.(listing|thread|search|about|render)\b', module), (path.name, module)


def test_the_page_functions_hold_no_path_list_of_their_own():
    """The readable paths are targets.ROUTE_SOURCE, passed to page.js: no page function spells a route."""
    for name in web.SNIPPET_NAMES:
        text = web.snippet(name)
        assert 'post\\/' not in text and 'replies|reposts' not in text, name
