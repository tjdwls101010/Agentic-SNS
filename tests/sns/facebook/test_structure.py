"""What is Facebook's own in the skill's tree (the tree, the import directions, interface-only access and snippet
ownership are tests/sns/core/test_structure.py's, which run over every platform package that exists): the facebook
package's folders and modules, the page functions of its system, and the names of the old skill that must not come
back."""
import json
import re
from pathlib import Path

from sns import facebook
from sns.facebook import web
from tests.sns.support.policies import POLICIES

PACKAGE = Path(facebook.__file__).resolve().parent
WEB = PACKAGE / 'web'
FEATURES = {'listing', 'thread', 'search', 'about', 'images', 'notifications', 'render'}


def sources(root=PACKAGE):
    return [p for p in root.rglob('*.py') if '__pycache__' not in p.parts]


def test_the_facebook_package_is_its_interface_its_feature_modules_and_the_system_web():
    modules = {p.stem for p in PACKAGE.glob('*.py')} - {'__init__'}
    folders = {p.name for p in PACKAGE.iterdir() if p.is_dir() and p.name != '__pycache__'}
    assert modules == FEATURES and folders == {'web'}  # web is the only folder; Facebook has no store of its own


def test_the_interface_is_platform_commands_and_choices():
    assert facebook.PLATFORM.key == 'facebook' and facebook.PLATFORM.word == 'facebook'
    assert facebook.PLATFORM.transport == 'tab' and facebook.PLATFORM.site == 'facebook.com'
    assert list(facebook.COMMANDS) == ['feed', 'profile', 'group', 'post', 'comments', 'replies', 'search', 'about',
                                       'images', 'notifications']
    assert set(facebook.CHOICES) and all(key.split('.')[0] in facebook.COMMANDS for key in facebook.CHOICES)


def test_the_platform_adapter_says_how_this_tab_behaves():
    platform = facebook.PLATFORM
    assert platform.idle_action == 'blank'  # window.close() does not take on Facebook's tab (measured)
    assert platform.unblock_scope is None   # an account-wide platform: the check is counted in no named scope
    assert platform.window.tz is None and platform.window.unit_key is None  # the local zone; every post is its own unit
    assert callable(platform.locate) and platform.schemas.keys() == {'post', 'entity', 'about', 'group', 'comment', 'notification', 'doctor', 'image'}


def test_the_adapters_policy_is_the_facebook_row_of_the_plans_table():
    """No announced limits (the account is the scope), a 429 holds it 30 minutes, a checkpoint is the one block a person
    clears, requests are paced 1-2 s apart."""
    assert facebook.PLATFORM.policy == POLICIES['facebook']


def test_the_systems_page_functions_are_exactly_the_snippets_and_the_kit():
    files = {p.name for p in WEB.glob('*.js')}
    assert files == {'kit.js', *(f'{name}.js' for name in web.SNIPPET_NAMES)}


def test_every_page_function_starts_by_naming_itself_facebook_dot_its_file():
    for path in WEB.glob('*.js'):
        assert path.read_text(encoding='utf-8').splitlines()[0] == f'// sns-snippet: facebook.{path.stem}', path.name


def test_the_request_ledger_is_written_once_not_once_per_page_function():
    """The old skill pasted the same ledger block into four snippets; now only the kit has it."""
    holders = [p.name for p in WEB.glob('*.js') if 'PerformanceObserver' in p.read_text(encoding='utf-8')]
    assert holders == ['kit.js']


def test_the_old_skills_names_are_gone_from_the_package():
    """Environment variables are SNS_*, there is no request budget, and no state lives in a cache directory."""
    old = re.compile(r'(?<![A-Z_])FACEBOOK_[A-Z]|max-requests|max_requests|\.cache/|FacebookError|from facebook\b|'
                     r'facebook-snippet|MAX_BUDGET|ROUTE_RESERVE\b.*budget')
    files = [*sources(), *WEB.glob('*.js'), WEB / 'queries.json']
    problems = [f'{p.relative_to(PACKAGE)}: {m[0]}' for p in files for m in old.finditer(p.read_text(encoding='utf-8'))]
    assert not problems, problems


def test_the_system_never_imports_a_feature_module_or_the_pipeline():
    """web is what the platform's features stand on: it knows helpers and itself only (the core test checks the unit
    rule over all platforms; this names the modules for Facebook)."""
    for path in sources(WEB):
        for module in re.findall(r'^(?:from|import) (sns[\w.]*)', path.read_text(encoding='utf-8'), re.M):
            assert module.split('.')[1:2] != ['reading'] and not re.match(
                r'sns\.facebook\.(listing|thread|search|about|notifications|render)\b', module), (path.name, module)


def test_no_platform_unit_reaches_the_stores_directly():
    """Handles, sessions and protection come through the connection the pipeline hands the platform."""
    for path in sources():
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'^(?:from|import) sns\.(handles|protection|session|outfile|images|aside|paths)\b', text,
                             re.M), path.name


def test_queries_json_is_well_formed_and_has_no_secret_looking_value():
    data = json.loads((WEB / 'queries.json').read_text(encoding='utf-8'))
    assert set(data['queries']) == set(web.QUERIES) and len(data['queries']) == 14
    for spec in data['queries'].values():
        assert spec['doc_id'] is None or re.fullmatch(r'\d+', spec['doc_id'])
