"""Shared layout contract for migrated skills: one cli.py, one package, one-way imports.

A skill is registered here once it has moved to `scripts/cli.py` + `scripts/<package>/`. Unregistered skills keep
their legacy layout and are out of scope. Each registration names the package and classifies every top-level
child as common, system, store or feature; the checks below read that declaration and the code, nothing else.
"""
import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CALL = 'uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py"'
INVOCATION = f'Bash({CALL} *)'
SKILLS = {
    'facebook': ('facebook', {
        'errors': 'common', 'outcome': 'common',
        'aside': 'system', 'graphql': 'system',
        'account': 'store', 'cursors': 'store', 'collect': 'store',
        'reading': 'feature', 'render': 'feature',
    }),
    'yfinance': ('yfinance_skill', {
        'envelope': 'common', 'shape': 'common', 'display': 'common', 'selection': 'common', 'budget': 'common',
        'leaf': 'common',
        'yahoo': 'system',
        'store': 'store', 'export': 'store',
        'querying': 'feature', 'schema': 'feature',
    }),
}
# What each kind of top-level child may import; features also import themselves, never another feature.
ALLOWED = {
    'common': {'common'},
    'system': {'common', 'system', 'store'},
    'store': {'common', 'system', 'store'},
    'feature': {'common', 'system', 'store'},
    'cli': {'common', 'feature'},
}
IGNORED = {'__pycache__', '.DS_Store'}


def python_files(directory):
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        if path.suffix == '.py':
            yield path
        elif path.suffix == '':
            first = path.read_bytes()[:64]
            if first.startswith(b'#!') and b'python' in first:
                yield path


def module_name(path, scripts):
    parts = list(path.relative_to(scripts).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def imported_modules(tree, current, is_package):
    """Absolute dotted names a module imports, with relative imports resolved against `current`."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = current.split('.') if is_package else current.split('.')[:-1]
                base = base[:len(base) - node.level + 1]
                prefix = '.'.join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module
            names.append(prefix)
            names += [prefix + '.' + alias.name for alias in node.names]
    return names


def path_edits(tree):
    """sys.path mutation, site.addsitedir and spec_from_file_location, as code rather than text."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ('addsitedir', 'spec_from_file_location'):
            found.append(node.attr)
        elif isinstance(node, ast.Name) and node.id == 'spec_from_file_location':
            found.append(node.id)
        elif isinstance(node, ast.ImportFrom) and any(a.name in ('addsitedir', 'spec_from_file_location')
                                                      for a in node.names):
            found.append(node.module)
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
              and node.value.attr == 'path' and isinstance(node.value.value, ast.Name)
              and node.value.value.id == 'sys'):
            found.append('sys.path.' + node.attr)
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript):
                    target = target.value
                if (isinstance(target, ast.Attribute) and target.attr == 'path'
                        and isinstance(target.value, ast.Name) and target.value.id == 'sys'):
                    found.append('sys.path =')
    return found


def pep723(source):
    """The `# /// script` block parsed as TOML, following the PEP 723 reference regex."""
    blocks = [m for m in re.finditer(r'(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$', source)
              if m['type'] == 'script']
    if len(blocks) != 1:
        return None
    content = ''.join(line[2:] if line.startswith('# ') else line[1:]
                      for line in blocks[0]['content'].splitlines(keepends=True))
    return tomllib.loads(content)


def allowed_tools(skill_md):
    text = skill_md.read_text(encoding='utf-8')
    front = re.match(r'---\n(.*?)\n---\n', text, re.S)
    if not front:
        return None
    line = re.search(r'(?m)^allowed-tools:\s*(.+)$', front[1])
    return line[1].strip() if line else None


def violations(skill_dir, tests_dir, package, children, extra_scope=()):
    """Every layout rule broken by one skill, as readable strings; empty when it conforms."""
    found = []
    scripts = skill_dir / 'scripts'
    entries = {p.name for p in scripts.iterdir()} - IGNORED
    if entries != {'cli.py', package}:
        found.append(f'scripts/ holds {sorted(entries)}, expected cli.py and {package}/')
    if package in sys.stdlib_module_names:
        found.append(f'package {package} shadows a standard-library module')
    root = scripts / package
    if not (root / '__init__.py').is_file():
        return found + [f'{package}/__init__.py is missing']
    if (root / '__init__.py').read_text().strip():
        found.append(f'{package}/__init__.py is not empty')
    actual = {p.stem if p.suffix == '.py' else p.name for p in root.iterdir()
              if p.name not in IGNORED and p.name != '__init__.py'
              and (p.suffix == '.py' or p.is_dir())}
    for name in sorted(actual - children.keys()):
        found.append(f'top-level child {name} has no declared kind')

    modules, edges = {}, {}
    for path in python_files(root):
        name = module_name(path, scripts)
        modules[name] = path
    modules['cli'] = scripts / 'cli.py'
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imports = imported_modules(tree, name, path.name == '__init__.py')
        edges[name] = {target for target in modules
                       if any(i == target or i.startswith(target + '.') for i in imports) and target != name}
        edges[name] = {t for t in edges[name]
                       if not any(o != t and o.startswith(t + '.') and o in edges[name] for o in edges[name])
                       or t == 'cli'}
        for edit in path_edits(tree):
            found.append(f'{name} edits the import path ({edit})')

    def kind(module):
        if module == 'cli':
            return 'cli', None
        parts = module.split('.')
        if len(parts) == 1:
            return 'package', None
        return children.get(parts[1], 'undeclared'), parts[1]

    for source, targets in edges.items():
        source_kind, source_child = kind(source)
        for target in targets:
            target_kind, target_child = kind(target)
            if target == 'cli':
                found.append(f'{source} imports cli')
                continue
            if source_kind == 'package' or target_kind == 'package':
                continue
            if source_kind == 'feature' and target_kind == 'feature' and source_child == target_child:
                continue
            if target_kind not in ALLOWED.get(source_kind, set()):
                found.append(f'{source} ({source_kind}) imports {target} ({target_kind})')

    state = {}

    def visit(module, stack):
        state[module] = 'active'
        for target in sorted(edges.get(module, ())):
            if state.get(target) == 'active':
                found.append('import cycle: ' + ' -> '.join(stack[stack.index(target):] + [target]))
            elif target not in state:
                visit(target, stack + [target])
        state[module] = 'done'

    for module in sorted(edges):
        if module not in state:
            visit(module, [module])

    if not tests_dir.is_dir():
        found.append(f'tests/{tests_dir.name} is missing')
    for path in [*(python_files(tests_dir) if tests_dir.is_dir() else ()), *extra_scope]:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for edit in path_edits(tree):
            found.append(f'{path.name} edits the import path ({edit})')
        if any(name == 'cli' or name.startswith('cli.') for name in imported_modules(tree, 'tests', False)):
            found.append(f'{path.name} imports cli')

    metadata = pep723((scripts / 'cli.py').read_text(encoding='utf-8')) if (scripts / 'cli.py').is_file() else None
    if not metadata or 'requires-python' not in metadata or 'dependencies' not in metadata:
        found.append('cli.py lacks a PEP 723 block with requires-python and dependencies')
    if allowed_tools(skill_dir / 'SKILL.md') != INVOCATION:
        found.append('SKILL.md allowed-tools is not ' + INVOCATION)
    body = re.sub(r'\A---\n.*?\n---\n', '', (skill_dir / 'SKILL.md').read_text(encoding='utf-8'), count=1, flags=re.S)
    if CALL not in body:
        found.append('SKILL.md body does not run ' + CALL)
    return found


def check_skill(root, skill, package, children, extra_scope=()):
    """One registered skill checked where it lives in a repository rooted at `root`. Its tests are named for the skill
    (a hyphen becomes an underscore), not for the package, which may carry a suffix to avoid shadowing a library."""
    tests = root / 'tests' / skill.replace('-', '_')
    return violations(root / '.claude/skills' / skill, tests, package, children, extra_scope)


@pytest.mark.parametrize('skill', sorted(SKILLS))
def test_registered_skill_follows_the_layout(skill):
    package, children = SKILLS[skill]
    scope = [Path(__file__)] if skill == sorted(SKILLS)[0] else []
    assert check_skill(ROOT, skill, package, children, scope) == []


# --- the checker itself, against small synthetic trees ---------------------------------------------------------

KINDS = {'errors': 'common', 'web': 'system', 'state': 'store', 'reading': 'feature', 'render': 'feature'}
CLI = '# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\nfrom demo.reading import run\n'


BASE = {
    'SKILL.md': f'---\nname: demo\nallowed-tools: {INVOCATION}\n---\nRun `{CALL} <command>`.\n',
        'scripts/cli.py': CLI,
        'scripts/demo/__init__.py': '',
        'scripts/demo/errors.py': '',
        'scripts/demo/web/__init__.py': '',
        'scripts/demo/web/client.py': 'from demo.errors import Failure\nfrom demo.state import Store\n',
        'scripts/demo/state.py': 'from demo import errors\n',
        'scripts/demo/reading/__init__.py': '',
        'scripts/demo/reading/run.py': 'from demo.web.client import x\nfrom . import helpers\n',
        'scripts/demo/reading/helpers.py': '',
        'scripts/demo/render.py': 'import demo.errors\n',
    'tests/test_demo.py': 'from demo.web import client\n',
}


def write(base, files):
    for name, text in files.items():
        if text is None:
            (base / name).unlink(missing_ok=True)
            continue
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def tree(tmp_path, files):
    skill = tmp_path / 'skill'
    write(skill, {**BASE, **files})
    return violations(skill, skill / 'tests', 'demo', KINDS)


def repository(tmp_path, skill, files=None, tests=True):
    """A repository holding one skill whose package (demo) is not named after the skill."""
    root = tmp_path / 'repo'
    write(root / '.claude/skills' / skill, {k: v for k, v in BASE.items() if not k.startswith('tests/')})
    if tests:
        write(root / 'tests' / skill.replace('-', '_'), {'test_demo.py': BASE['tests/test_demo.py']})
    write(root, files or {})
    return check_skill(root, skill, 'demo', KINDS)


def test_conforming_tree_has_no_violations(tmp_path):
    assert tree(tmp_path, {}) == []


@pytest.mark.parametrize('files,expected', [
    ({'scripts/helper.py': ''}, 'scripts/ holds'),
    ({'scripts/demo/extra.py': ''}, 'extra has no declared kind'),
    ({'scripts/demo/__init__.py': 'X = 1\n'}, 'is not empty'),
    ({'scripts/demo/errors.py': 'from demo.state import Store\n'}, 'demo.errors (common) imports demo.state (store)'),
    ({'scripts/demo/state.py': 'from demo.render import x\n'}, 'demo.state (store) imports demo.render (feature)'),
    ({'scripts/demo/web/client.py': 'from ..reading import run\n'}, 'demo.web.client (system) imports demo.reading'),
    ({'scripts/demo/render.py': 'from demo.reading.run import x\n'}, 'demo.render (feature) imports demo.reading.run'),
    ({'scripts/cli.py': CLI + 'from demo.web import client\n'}, 'cli (cli) imports demo.web.client (system)'),
    ({'scripts/demo/render.py': 'import cli\n'}, 'demo.render imports cli'),
    ({'scripts/demo/reading/helpers.py': 'from demo.reading.run import x\n'}, 'import cycle'),
    ({'scripts/demo/state.py': 'import sys\nsys.path.insert(0, "x")\n'}, 'edits the import path'),
    ({'tests/test_demo.py': 'import importlib.util\nimportlib.util.spec_from_file_location("x", "y")\n'},
     'edits the import path'),
    ({'tests/test_demo.py': 'import site\nsite.addsitedir("x")\n'}, 'edits the import path'),
    ({'tests/test_demo.py': 'import sys\nsys.path[:0] = ["x"]\n'}, 'edits the import path'),
    ({'tests/test_demo.py': 'from cli import main\n'}, 'test_demo.py imports cli'),
    ({'scripts/cli.py': 'from demo.reading import run\n'}, 'PEP 723'),
    ({'scripts/cli.py': '# /// script\n# requires-python = ">=3.11"\n# ///\n'}, 'PEP 723'),
    ({'SKILL.md': '---\nname: demo\nallowed-tools: Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/demo.py" *)\n---\n'},
     'allowed-tools'),
])
def test_each_rule_reports_its_violation(tmp_path, files, expected):
    found = tree(tmp_path, files)
    assert any(expected in line for line in found), found


def test_standard_library_package_name_is_rejected(tmp_path):
    skill = tmp_path / 'skill'
    (skill / 'scripts/json').mkdir(parents=True)
    (skill / 'scripts/json/__init__.py').write_text('')
    (skill / 'scripts/cli.py').write_text(CLI)
    (skill / 'SKILL.md').write_text(f'---\nallowed-tools: {INVOCATION}\n---\n')
    assert any('shadows a standard-library module' in line for line in violations(skill, skill / 'tests', 'json', {}))


def test_the_tests_folder_is_named_for_the_skill_not_its_package(tmp_path):
    """A package renamed so it does not shadow a library it imports keeps its tests under the skill's own name."""
    found = repository(tmp_path, 'demo-kit', {'tests/demo_kit/test_demo.py': 'import sys\nsys.path.insert(0, "x")\n'})
    assert any('test_demo.py edits the import path' in line for line in found), found


def test_a_registered_skill_without_its_tests_folder_is_a_violation(tmp_path):
    """Registering a skill must not quietly take its tests out of the checks."""
    found = repository(tmp_path, 'demo-kit', tests=False)
    assert any('tests/demo_kit is missing' in line for line in found), found


def test_the_skill_body_runs_the_same_invocation_allowed_tools_approves(tmp_path):
    found = tree(tmp_path, {'SKILL.md': f'---\nname: demo\nallowed-tools: {INVOCATION}\n---\nRun python3 scripts/cli.py.\n'})
    assert any('SKILL.md body does not run' in line for line in found), found
