"""What is X's own in the skill's tree (the tree, the import directions, interface-only access and snippet ownership are
tests/sns/core/test_structure.py's, which run over every platform package that exists): the x package's folders and
modules, the page functions of its system, and the names of the old skill that must not come back."""
import re
from pathlib import Path

from sns import x
from sns.x import web

PACKAGE = Path(x.__file__).resolve().parent
WEB = PACKAGE / 'web'
FEATURES = {'listing', 'thread', 'search', 'about', 'explore', 'render'}


def sources(root=PACKAGE):
    return [p for p in root.rglob('*.py') if '__pycache__' not in p.parts]


def test_the_x_package_is_its_interface_its_feature_modules_and_the_system_web():
    modules = {p.stem for p in PACKAGE.glob('*.py')} - {'__init__'}
    folders = {p.name for p in PACKAGE.iterdir() if p.is_dir() and p.name != '__pycache__'}
    assert FEATURES <= modules and folders == {'web'}  # web is the only folder; X has no store of its own


def test_the_interface_is_platform_commands_and_choices():
    assert x.PLATFORM.key == 'x' and x.PLATFORM.word == 'x' and x.PLATFORM.transport == 'tab'
    assert list(x.COMMANDS) == ['feed', 'profile', 'about', 'graph', 'me', 'list', 'community', 'post', 'replies',
                                'reposts', 'quotes', 'search', 'trends']
    assert set(x.CHOICES) and all(key.split('.')[0] in x.COMMANDS for key in x.CHOICES)


def test_the_systems_page_functions_are_exactly_the_snippets_and_the_kit():
    files = {p.name for p in WEB.glob('*.js')}
    assert files == {'kit.js', *(f'{name}.js' for name in web.SNIPPET_NAMES)}


def test_every_page_function_starts_by_naming_itself_x_dot_its_file():
    for path in WEB.glob('*.js'):
        assert path.read_text(encoding='utf-8').splitlines()[0] == f'// sns-snippet: x.{path.stem}', path.name


def test_no_page_function_spells_the_word_the_repl_refuses():
    for path in WEB.glob('*.js'):
        assert 'require(' not in path.read_text(encoding='utf-8'), path.name
    for name in web.SNIPPET_NAMES:
        assert 'require(' not in web.snippet(name), name


def test_the_old_skills_names_are_gone_from_the_package():
    """Environment variables are SNS_*, there is no request budget, and no state lives in a cache directory."""
    old = re.compile(r'(?<![A-Z_])TWITTER_[A-Z]|max-requests|max_requests|\.cache/|TwitterError|from twitter\b')
    problems = [f'{p.relative_to(PACKAGE)}: {m[0]}' for p in [*sources(), *WEB.glob('*.js'), WEB / 'operations.json']
                for m in old.finditer(p.read_text(encoding='utf-8'))]
    assert not problems, problems


def test_the_system_never_imports_a_feature_module_or_the_pipeline():
    """web is what the platform's features stand on: it knows helpers and itself only (the core test checks the unit
    rule over all platforms; this names the modules for X)."""
    for path in sources(WEB):
        for module in re.findall(r'^(?:from|import) (sns[\w.]*)', path.read_text(encoding='utf-8'), re.M):
            assert module.split('.')[1:2] != ['reading'] and not re.match(
                r'sns\.x\.(listing|thread|search|about|explore|render)\b', module), (path.name, module)
