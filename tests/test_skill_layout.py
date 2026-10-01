"""Shared layout contract for migrated skills: one cli.py, one package, one-way imports.

A skill is registered here once it has moved to `scripts/cli.py` + `scripts/<package>/`. Unregistered skills keep
their legacy layout and are out of scope. Each registration names the package and classifies every top-level
child as common, system, store or feature; the checks below read that declaration and the code, nothing else.

A skill also registered in UNITS is held to the unit rules as well: code outside a subpackage reaches it only through the names its `__init__.py` binds, a feature imports another feature only along a named edge, and the skill never imports the repository's tests or maintenance jobs. Only static access is judged — an import, an attribute chain from an imported name, or a dotted string such as a patch target; a dynamic import or a name assembled at runtime is out of scope.
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
    'threads': ('threads', {
        'model': 'common', 'errors': 'common',
        'aside': 'system', 'graphql': 'system',
        'guard': 'store', 'store': 'store',
        'reading': 'feature', 'output': 'feature',
    }),
    'twitter': ('twitter', {
        'errors': 'common', 'dates': 'common',
        'aside': 'system', 'graphql': 'system',
        'account': 'store', 'continuation': 'store', 'export': 'store',
        'browse': 'feature', 'output': 'feature',
    }),
    'yfinance': ('yfinance_skill', {
        'envelope': 'common', 'shape': 'common', 'display': 'common', 'selection': 'common', 'budget': 'common',
        'leaf': 'common',
        'yahoo': 'system',
        'store': 'store', 'export': 'store',
        'querying': 'feature', 'schema': 'feature',
    }),
}
# Skills held to the unit rules: `edges` are the (from, to) feature imports allowed, `jobs` the repository folders whose maintenance code runs the skill. The other registered skills keep the contract above until their own migration.
UNITS = {}
# What each kind of top-level child may import; features also import themselves, and another feature only along an edge UNITS names.
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


def violations(skill_dir, tests_dir, package, children, extra_scope=(), units=None, jobs=()):
    """Every layout rule broken by one skill, as readable strings; empty when it conforms. `units` (a UNITS entry) adds the unit rules, with `jobs` the job folders it names."""
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
            if source_kind == 'feature' and target_kind == 'feature' and (
                    source_child == target_child or (source_child, target_child) in (units or {}).get('edges', ())):
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
    repository = [*(python_files(tests_dir) if tests_dir.is_dir() else ()),
                  *(path for job in jobs if job.is_dir() for path in python_files(job))]
    if units is not None:
        found += unit_violations(scripts, package, modules, repository)
    for path in [*repository, *extra_scope]:
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


def bound_names(tree, current, is_package, modules):
    """What a module's imports bind: {local name: (dotted target, whether that target is a module)}. A plain `import a.b` binds `a` to `a`."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = (alias.name, alias.name in modules)
                else:
                    root = alias.name.split('.')[0]
                    names[root] = (root, root in modules)
        elif isinstance(node, ast.ImportFrom):
            base = imported_modules(ast.Module(body=[node], type_ignores=[]), current, is_package)[0]
            for alias in node.names:
                target = base + '.' + alias.name
                names[alias.asname or alias.name] = (target, target in modules)
    return names


def dotted(node):
    """`a.b.c` as its parts when the chain starts at a name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return [node.id, *reversed(parts)] if isinstance(node, ast.Name) else None


def docstrings(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def unit_violations(scripts, package, modules, repository):
    """The unit rules: outside a subpackage, only the names its `__init__.py` binds as values are reachable; the entry never binds one of its own modules; the skill never imports the repository's tests or jobs.

    `modules` maps every dotted module name in the skill to its file, `repository` lists the test and job files.
    """
    found = []
    units = sorted(name for name, path in modules.items() if path.name == '__init__.py' and name != package)
    children = {unit: {name[len(unit) + 1:].split('.')[0] for name in modules if name.startswith(unit + '.')} for unit in units}
    public = {}
    for unit in units:
        tree = ast.parse(modules[unit].read_text(encoding='utf-8'))
        values = set()
        for name, (target, is_module) in bound_names(tree, unit, True, modules).items():
            if is_module and target.startswith(unit + '.'):
                found.append(f'{unit} binds its module {target[len(unit) + 1:]} in its __init__')
            elif not is_module:
                values.add(name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                values.add(node.name)
            elif isinstance(node, ast.Assign):
                values.update(t.id for t in node.targets if isinstance(t, ast.Name))
        public[unit] = values

    def past(where, owner, dotted_name, through_entry):
        """A dotted name that lands inside a unit `owner` is not part of, past what its entry binds."""
        for unit in units:
            if owner == unit or owner.startswith(unit + '.') or not dotted_name.startswith(unit + '.'):
                continue
            child = dotted_name[len(unit) + 1:].split('.')[0]
            if child in children[unit] and not (through_entry and child in public[unit]):
                found.append(f'{where} reaches past {unit} into {child}')

    sources = [(name, name, path) for name, path in modules.items()] + [(path.name, '', path) for path in repository]
    test_modules = {path.stem for path in repository} | {'tests'}
    for where, owner, path in sources:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        is_package = path.name == '__init__.py'
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    past(where, owner, alias.name, False)
                    if owner and alias.name.split('.')[0] in test_modules:
                        found.append(f'{where} imports repository code {alias.name}')
            elif isinstance(node, ast.ImportFrom):
                base = imported_modules(ast.Module(body=[node], type_ignores=[]), owner or 'tests', is_package)[0]
                past(where, owner, base, False)
                for alias in node.names:
                    if base in units:
                        past(where, owner, base + '.' + alias.name, True)
                if owner and not node.level and base.split('.')[0] in test_modules:
                    found.append(f'{where} imports repository code {base}')
        bound = bound_names(tree, owner or 'tests', is_package, modules)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                parts = dotted(node)
                if parts and parts[0] in bound:
                    past(where, owner, '.'.join([bound[parts[0]][0], *parts[1:]]), True)
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                for text in re.findall(r'[A-Za-z_][\w.]*', node.value):
                    past(where, owner, text, True)
    return list(dict.fromkeys(found))


def check_skill(root, skill, package, children, extra_scope=(), units=None):
    """One registered skill checked where it lives in a repository rooted at `root`. Its tests are named for the skill
    (a hyphen becomes an underscore), not for the package, which may carry a suffix to avoid shadowing a library."""
    tests = root / 'tests' / skill.replace('-', '_')
    jobs = (units or {}).get('jobs', ())
    missing = [f'{job} is missing' for job in jobs if not (root / job).is_dir()]
    return violations(root / '.claude/skills' / skill, tests, package, children, extra_scope, units, [root / job for job in jobs]) + missing


@pytest.mark.parametrize('skill', sorted(SKILLS))
def test_registered_skill_follows_the_layout(skill):
    package, children = SKILLS[skill]
    scope = [Path(__file__)] if skill == sorted(SKILLS)[0] else []
    assert check_skill(ROOT, skill, package, children, scope, UNITS.get(skill)) == []


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


# --- the unit rules, against a repository whose skill declares them ----------------------------------------------

# A conforming tree: reading's entry binds a public function named like its own module read.py, render imports reading along the one named edge, and the tests and the job reach the units only through their entries.
UNIT_TREE = {
    '.claude/skills/demo/SKILL.md': BASE['SKILL.md'],
    '.claude/skills/demo/scripts/cli.py': CLI + 'from demo import render\n',
    '.claude/skills/demo/scripts/demo/__init__.py': '',
    '.claude/skills/demo/scripts/demo/errors.py': 'class Failure(Exception):\n    pass\n',
    '.claude/skills/demo/scripts/demo/web/__init__.py': 'from demo.web.client import Failure, fetch\n\nTIMEOUT = 30\n',
    '.claude/skills/demo/scripts/demo/web/client.py': 'from demo.errors import Failure\n\n\ndef fetch():\n    return Failure\n',
    '.claude/skills/demo/scripts/demo/state.py': 'from demo import errors\n',
    '.claude/skills/demo/scripts/demo/reading/__init__.py': 'from demo.reading.read import read\nfrom .read import run\n',
    '.claude/skills/demo/scripts/demo/reading/read.py': 'from demo import web\nfrom demo.web import fetch\nfrom . import helpers\nfrom .helpers import tidy\n\n\ndef read():\n    return web.fetch(), web.TIMEOUT, fetch, helpers, tidy\n\n\ndef run():\n    pass\n',
    '.claude/skills/demo/scripts/demo/reading/helpers.py': 'def tidy():\n    pass\n',
    '.claude/skills/demo/scripts/demo/render.py': 'import demo.reading\nfrom demo import reading\nfrom demo.reading import read\n\nVALUE = reading.read, demo.reading.run, read\n',
    'tests/demo/test_demo.py': 'from demo.reading import read\nimport demo.web as web\n\nPATCH = "demo.web.fetch"\nVALUE = web.fetch, read\n',
    'jobs/demo/run.py': 'import subprocess\n\nfrom demo.web import fetch\n',
}
UNIT_RULES = {'edges': {('render', 'reading')}, 'jobs': ['jobs/demo']}


def unit_tree(tmp_path, files=None, units=UNIT_RULES):
    root = tmp_path / 'repo'
    write(root, {**UNIT_TREE, **(files or {})})
    return check_skill(root, 'demo', 'demo', KINDS, units=units)


SKILL = '.claude/skills/demo/scripts/demo/'


def test_a_conforming_unit_tree_has_no_violations(tmp_path):
    assert unit_tree(tmp_path) == []


@pytest.mark.parametrize('files,expected', [
    ({SKILL + 'render.py': 'from demo.reading.helpers import tidy\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'render.py': 'from .reading.helpers import tidy\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'render.py': 'import demo.reading.helpers as h\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'render.py': 'from demo.reading import helpers as h\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'render.py': 'from demo import reading\n\nVALUE = reading.helpers.tidy\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'render.py': 'import demo.reading\n\nVALUE = demo.reading.helpers\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'state.py': 'from demo.web.client import fetch\n'}, 'demo.state reaches past demo.web into client'),
    ({'.claude/skills/demo/scripts/cli.py': CLI + 'from demo.reading.read import read\n'}, 'cli reaches past demo.reading into read'),
    ({SKILL + 'reading/__init__.py': 'from demo.reading.read import read\nfrom demo.reading import helpers\n'}, 'demo.reading binds its module helpers'),
    ({SKILL + 'web/__init__.py': 'from . import client\n'}, 'demo.web binds its module client'),
    ({'tests/demo/test_demo.py': 'from demo.web.client import fetch\n'}, 'test_demo.py reaches past demo.web into client'),
    ({'tests/demo/test_demo.py': 'PATCH = "demo.web.client.fetch"\n'}, 'test_demo.py reaches past demo.web into client'),
    ({'jobs/demo/run.py': 'from demo.reading.helpers import tidy\n'}, 'run.py reaches past demo.reading into helpers'),
    ({'jobs/demo/run.py': 'import sys\nsys.path.insert(0, "x")\n'}, 'run.py edits the import path'),
    ({'jobs/demo/run.py': 'from cli import main\n'}, 'run.py imports cli'),
    ({SKILL + 'state.py': 'from test_demo import PATCH\n'}, 'demo.state imports repository code test_demo'),
    ({SKILL + 'state.py': 'import run\n'}, 'demo.state imports repository code run'),
    ({SKILL + 'reading/read.py': 'from demo import render\n\n\ndef read():\n    pass\n\n\ndef run():\n    pass\n'}, 'demo.reading.read (feature) imports demo.render (feature)'),
])
def test_each_unit_rule_reports_its_violation(tmp_path, files, expected):
    found = unit_tree(tmp_path, files)
    assert any(expected in line for line in found), found


def test_a_named_edge_still_counts_toward_an_import_cycle(tmp_path):
    files = {SKILL + 'reading/read.py': 'from demo import render\n\n\ndef read():\n    pass\n\n\ndef run():\n    pass\n'}
    found = unit_tree(tmp_path, files, {'edges': {('render', 'reading'), ('reading', 'render')}, 'jobs': ['jobs/demo']})
    assert any('import cycle' in line for line in found), found


def test_a_named_job_folder_that_is_missing_is_a_violation(tmp_path):
    """Naming a job folder must not quietly take a missing one out of the checks."""
    found = unit_tree(tmp_path, units={'edges': {('render', 'reading')}, 'jobs': ['jobs/elsewhere']})
    assert any('jobs/elsewhere is missing' in line for line in found), found


def test_the_unit_rules_apply_only_to_skills_that_declare_them(tmp_path):
    """The legacy contract tolerates a test that imports a unit's inside; registering the unit rules is what makes it a violation."""
    files = {'tests/demo/test_demo.py': 'from demo.web.client import fetch\n'}
    assert not [line for line in unit_tree(tmp_path, files, units=None) if 'reaches past' in line]
