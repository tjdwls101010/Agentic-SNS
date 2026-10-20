"""The skill's tree and import rules: what every later change must keep.

Shared units sit directly in the `sns` package (helpers as modules; stores, the aside system and the shared features as
subpackages). Each platform is one folder `sns/<platform>/` holding its feature modules, its system `web/` and, for
reddit, its own store `snapshots/`. Imports run one way: cli → platform interfaces, shared features, helpers; platform
features → their own web and store, reading, helpers; web, stores, aside → helpers; helpers → helpers; reading and
maintenance → stores, aside, helpers. Platforms never import each other.
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / '.claude/skills/sns'
SCRIPTS = SKILL / 'scripts'
PACKAGE = SCRIPTS / 'sns'
TESTS = REPO / 'tests/sns'
CONTRAST = REPO / 'contrast/sns'

HELPERS = {'errors', 'limits', 'redact', 'atomic', 'paths', 'clock', 'page', 'paging', 'window', 'results', 'text',
           'render', 'cmdline'}
STORES = {'protection', 'handles', 'session', 'outfile', 'images'}
SYSTEMS = {'aside'}
FEATURES = {'reading', 'maintenance'}
SHARED = HELPERS | STORES | SYSTEMS | FEATURES
PLATFORMS = {'x', 'threads', 'reddit', 'facebook', 'naver_blog'}
PLATFORM_STORES = {'reddit': {'snapshots'}}  # a platform's own stores, beside its system web/
# Platforms whose package exists so far; the last slice makes this all five (P4).
PRESENT = {p.name for p in PACKAGE.iterdir() if p.name in PLATFORMS} if PACKAGE.exists() else set()


def python_files(root):
    return [p for p in root.rglob('*.py') if '__pycache__' not in p.parts]


def unit_of(path):
    """(platform or None, unit) of a skill source file: ('x', 'web'), ('x', 'feature') for a platform's interface and
    feature modules, (None, 'protection'), or (None, 'cli')."""
    if path == SCRIPTS / 'cli.py':
        return None, 'cli'
    parts = path.relative_to(PACKAGE).parts
    head = parts[0][:-3] if parts[0].endswith('.py') else parts[0]
    if head in PLATFORMS:
        if len(parts) > 2 and parts[1] in {'web'} | PLATFORM_STORES.get(head, set()):
            return head, parts[1]
        return head, 'feature'
    return None, head


def _exists(dotted):
    path = SCRIPTS.joinpath(*dotted.split('.'))
    return path.with_suffix('.py').is_file() or (path / '__init__.py').is_file()


def imports(path):
    """(module, names) for every import in a file; relative imports resolved against the file."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, []) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if node.level:
                base = path.relative_to(SCRIPTS).with_suffix('').parts[:-node.level]
                module = '.'.join([*base, module] if module else base)
            found.append((module, [a.name for a in node.names]))
    return found


def targets(module, names):
    """The sns.* modules an import reaches, each with the names it takes from it: `from sns.x import web` reaches the
    module sns.x.web, `from sns.x import PLATFORM` takes PLATFORM from sns.x."""
    if module != 'sns' and not module.startswith('sns.'):
        return []
    found = []
    for name in names:
        if _exists(f'{module}.{name}'):
            found.append((f'{module}.{name}', []))
        else:
            found.append((module, [name]))
    return found or [(module, [])]


def classify(dotted):
    """((platform or None, unit), past): which unit an imported module belongs to, and whether it reaches past that
    unit's interface (a platform's own interface is sns.<platform>, its system's is sns.<platform>.web)."""
    parts = dotted.split('.')[1:]
    if parts and parts[0] in PLATFORMS:
        platform = parts[0]
        if len(parts) == 1:
            return (platform, 'interface'), False
        if parts[1] in {'web'} | PLATFORM_STORES.get(platform, set()):
            return (platform, parts[1]), len(parts) > 2
        return (platform, 'feature'), True
    return (None, parts[0] if parts else 'sns'), len(parts) > 1


def test_skill_top_level_is_fixed():
    allowed = {'SKILL.md', 'references', 'data', 'scripts'}
    present = {p.name for p in SKILL.iterdir() if p.name != '.DS_Store'}
    assert present <= allowed, present - allowed
    assert {'SKILL.md', 'data', 'scripts'} <= present
    scripts = {p.name for p in SCRIPTS.iterdir() if p.name not in ('__pycache__', '.DS_Store')}
    assert scripts == {'cli.py', 'sns'}


def test_package_name_does_not_shadow_stdlib():
    assert 'sns' not in sys.stdlib_module_names


def test_package_holds_only_known_units():
    found = {p.name[:-3] if p.suffix == '.py' else p.name for p in PACKAGE.iterdir()
             if p.name not in ('__pycache__', '__init__.py', '.DS_Store')}
    assert found <= SHARED | PLATFORMS, found - SHARED - PLATFORMS
    assert SHARED <= found, SHARED - found
    for name in STORES | SYSTEMS | FEATURES:
        assert (PACKAGE / name / '__init__.py').is_file(), name


def test_platform_folders_hold_features_web_and_their_own_store_only():
    for platform in PRESENT:
        root = PACKAGE / platform
        assert (root / '__init__.py').is_file()
        assert (root / 'web' / '__init__.py').is_file(), platform
        folders = {p.name for p in root.iterdir() if p.is_dir() and p.name != '__pycache__'}
        assert folders <= {'web'} | PLATFORM_STORES.get(platform, set()), (platform, folders)
        for store in PLATFORM_STORES.get(platform, set()) & folders:
            assert (root / store / '__init__.py').is_file()


def test_only_gitignore_is_committed_in_data():
    tracked = subprocess.run(['git', 'ls-files', str(SKILL / 'data')], cwd=REPO, capture_output=True, text=True,
                             check=True).stdout.split()
    assert tracked == ['.claude/skills/sns/data/.gitignore']
    assert (SKILL / 'data/.gitignore').read_text().split() == ['*', '!.gitignore']


def test_nothing_edits_sys_path():
    for path in python_files(SCRIPTS):
        assert 'sys.path' not in path.read_text(encoding='utf-8'), path


def test_cli_has_a_pep723_header():
    head = (SCRIPTS / 'cli.py').read_text(encoding='utf-8').splitlines()[:6]
    assert '# /// script' in head and '# ///' in head
    assert any(line.startswith('# requires-python') for line in head)
    assert any(line.startswith('# dependencies') for line in head)


def allowed(source, target):
    """Whether unit `source` may import unit `target` (both (platform or None, unit))."""
    (s_platform, s_unit), (t_platform, t_unit) = source, target
    if t_platform is not None:  # a platform's unit
        if s_unit == 'cli':
            return t_unit == 'interface'
        if s_platform != t_platform or s_unit != 'feature':
            return False  # platforms never import each other; web and a platform store never import its features
        return t_unit in {'interface', 'feature', 'web'} | PLATFORM_STORES.get(s_platform, set())
    if s_platform is not None:  # a platform's unit importing a shared one: features may use reading
        return t_unit in HELPERS or (s_unit == 'feature' and t_unit == 'reading')
    if s_unit == 'cli':
        return t_unit in HELPERS | FEATURES
    if s_unit in FEATURES:
        return t_unit in HELPERS | STORES | SYSTEMS | FEATURES
    return t_unit in HELPERS  # stores, the aside system and helpers


def same_unit(source, target):
    """A unit imports itself freely; a platform's interface and feature modules are one feature layer."""
    if source == target:
        return True
    return source[0] is not None and source[0] == target[0] and source[1] == 'feature' \
        and target[1] in ('interface', 'feature')


def test_import_direction():
    problems = []
    for path in python_files(SCRIPTS):
        source = unit_of(path)
        for module, names in imports(path):
            for target, _ in targets(module, names):
                unit, _ = classify(target)
                if unit[0] is None and unit[1] not in SHARED:
                    problems.append(f'{path.relative_to(SCRIPTS)}: unknown unit {target}')
                elif not same_unit(source, unit) and not allowed(source, unit):
                    problems.append(f'{path.relative_to(SCRIPTS)} {source} imports {target}')
    assert not problems, '\n'.join(problems)


def interface_violations(path, own):
    """Imports in `path` that reach past another unit's interface, or take a private name from it."""
    problems = []
    for module, names in imports(path):
        for target, taken in targets(module, names):
            unit, past = classify(target)
            if own is not None and same_unit(own, unit):
                continue
            if past:
                problems.append(f'{path}: reaches past {unit} into {target}')
            problems += [f'{path}: takes private {name} from {target}' for name in taken if name.startswith('_')]
    return problems


def test_no_unit_reaches_past_another_units_interface():
    problems = []
    for path in python_files(SCRIPTS):
        problems += interface_violations(path, unit_of(path))
    assert not problems, '\n'.join(problems)


def test_tests_and_contrast_use_unit_interfaces_only():
    problems = []
    for root in (TESTS, CONTRAST):
        for path in python_files(root):
            problems += interface_violations(path, None)
    assert not problems, '\n'.join(problems)


def test_skill_does_not_import_tests_or_contrast():
    for path in python_files(SCRIPTS):
        for module, _ in imports(path):
            assert not module.startswith(('tests', 'conftest', 'contrast', 'support')), (path, module)


def test_snippets_are_marked_and_owned():
    """A platform snippet lives in its own web/ and starts `// sns-snippet: <platform>.<name>`; the shared Aside
    protocol lives in aside/ and starts `// sns-snippet: aside.<name>`."""
    problems = []
    for path in PACKAGE.rglob('*.js'):
        first = path.read_text(encoding='utf-8').splitlines()[0] if path.stat().st_size else ''
        match = re.fullmatch(r'// sns-snippet: ([a-z_]+)\.([a-z_]+)', first)
        parts = path.relative_to(PACKAGE).parts
        owner = parts[0]
        if owner == 'aside':
            ok = match is not None and match.group(1) == 'aside'
        elif owner in PLATFORMS and len(parts) >= 3 and parts[1] == 'web':
            ok = match is not None and match.group(1) == owner
        else:
            ok = False
        if not ok:
            problems.append(str(path.relative_to(PACKAGE)))
    assert not problems, problems


def test_package_interfaces_do_not_reexport_private_names():
    for init in PACKAGE.rglob('__init__.py'):
        tree = ast.parse(init.read_text(encoding='utf-8'))
        exported = [alias.asname or alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    for alias in node.names]
        assert not [e for e in exported if e.startswith('_') and e != '__all__'], init
