"""The skill's tree and import rules: what every later change must keep."""
import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / '.claude/skills/threads'
SCRIPTS = SKILL / 'scripts'
PACKAGE = SCRIPTS / 'threads'
TESTS = Path(__file__).resolve().parent

FEATURES = {'listing', 'thread', 'search', 'about', 'maintenance', 'connect'}
SYSTEMS = {'aside', 'threads_web'}
STORES = {'guard', 'handles', 'collection', 'session'}
HELPERS = {'paging', 'results', 'render', 'errors', 'paths'}
UNITS = FEATURES | SYSTEMS | STORES | HELPERS
PACKAGES = SYSTEMS  # units that are packages; their interface is what __init__.py exports
FEATURE_EDGES = {(f, 'connect') for f in FEATURES - {'connect'}}


def python_files(root):
    return [p for p in root.rglob('*.py') if '__pycache__' not in p.parts]


def unit_of(path):
    """The unit a skill source file belongs to, or 'cli'."""
    if path == SCRIPTS / 'cli.py':
        return 'cli'
    part = path.relative_to(PACKAGE).parts[0]
    return part[:-3] if part.endswith('.py') else part


def imports(path):
    """(module, names, level) for every import in a file; relative imports resolved against the file."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, [], 0))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if node.level:
                base = path.relative_to(SCRIPTS).with_suffix('').parts[:-node.level]
                module = '.'.join([*base, module] if module else base)
            found.append((module, [a.name for a in node.names], node.level))
    return found


def targets(module, names):
    """The threads.* modules an import statement reaches, each with the names it takes from it."""
    if module == 'threads':
        return [(f'threads.{name}', []) for name in names]
    if module.startswith('threads.'):
        return [(module, names)]
    return []


def test_skill_top_level_is_fixed():
    allowed = {'SKILL.md', 'references', 'data', 'scripts'}
    present = {p.name for p in SKILL.iterdir() if p.name != '.DS_Store'}
    assert present <= allowed, present - allowed
    assert {'SKILL.md', 'data', 'scripts'} <= present
    scripts = {p.name for p in SCRIPTS.iterdir() if p.name not in ('__pycache__', '.DS_Store')}
    assert scripts == {'cli.py', 'threads'}


def test_package_name_does_not_shadow_stdlib():
    assert 'threads' not in sys.stdlib_module_names


def test_package_holds_only_known_units():
    found = {p.name[:-3] if p.suffix == '.py' else p.name for p in PACKAGE.iterdir()
             if p.name not in ('__pycache__', '__init__.py', '.DS_Store')}
    assert found == UNITS, (found - UNITS, UNITS - found)
    for name in PACKAGES:
        assert (PACKAGE / name / '__init__.py').is_file()


def test_only_gitignore_is_committed_in_data():
    tracked = subprocess.run(['git', 'ls-files', str(SKILL / 'data')], cwd=REPO, capture_output=True, text=True,
                             check=True).stdout.split()
    assert tracked == ['.claude/skills/threads/data/.gitignore']
    assert (SKILL / 'data/.gitignore').read_text().split() == ['*', '!.gitignore']


def test_nothing_edits_sys_path():
    for path in python_files(SCRIPTS):
        source = path.read_text(encoding='utf-8')
        assert 'sys.path' not in source, path


def test_cli_has_a_pep723_header():
    head = (SCRIPTS / 'cli.py').read_text(encoding='utf-8').splitlines()[:6]
    assert '# /// script' in head and '# ///' in head
    assert any(line.startswith('# requires-python') for line in head)
    assert any(line.startswith('# dependencies') for line in head)


def test_import_direction():
    problems = []
    for path in python_files(SCRIPTS):
        source = unit_of(path)
        for module, names, _ in imports(path):
            for target, _names in targets(module, names):
                unit = target.split('.')[1]
                if unit == source:
                    continue
                if unit not in UNITS:
                    problems.append(f'{path.name}: unknown unit {target}')
                    continue
                if source == 'cli':
                    ok = unit in FEATURES or unit in HELPERS
                elif source in FEATURES:
                    ok = unit in SYSTEMS | STORES | HELPERS or (source, unit) in FEATURE_EDGES
                elif source in SYSTEMS | STORES:
                    ok = unit in HELPERS
                else:
                    ok = unit in HELPERS
                if not ok:
                    problems.append(f'{path.relative_to(SCRIPTS)} ({source}) imports {target}')
    assert not problems, '\n'.join(problems)


def interface_violations(path, own_unit):
    problems = []
    for module, names, _ in imports(path):
        for target, taken in targets(module, names):
            parts = target.split('.')
            unit = parts[1]
            if unit == own_unit:
                continue
            if len(parts) > 2:
                problems.append(f'{path}: reaches past {unit} into {target}')
            problems += [f'{path}: takes private {name} from {target}' for name in taken if name.startswith('_')]
    return problems


def test_no_unit_reaches_past_another_units_interface():
    problems = []
    for path in python_files(SCRIPTS):
        problems += interface_violations(path, unit_of(path))
    assert not problems, '\n'.join(problems)


def test_tests_use_unit_interfaces_only():
    problems = []
    for path in python_files(TESTS):
        problems += interface_violations(path, None)
    assert not problems, '\n'.join(problems)


def test_package_interfaces_do_not_reexport_private_names():
    for name in PACKAGES:
        tree = ast.parse((PACKAGE / name / '__init__.py').read_text(encoding='utf-8'))
        exported = [alias.asname or alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    for alias in node.names]
        assert not [e for e in exported if e.startswith('_') and e != '__all__'], name


def test_skill_does_not_import_test_or_maintenance_code():
    for path in python_files(SCRIPTS):
        for module, _, _ in imports(path):
            assert not module.startswith(('tests', 'conftest', 'fake_aside', 'contrast')), (path, module)
