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
UNITS = {
    'yfinance': {'edges': set(), 'jobs': []},
}
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


def violations(skill_dir, tests_dir, package, children, extra_scope=(), units=None, jobs=(), repo=None):
    """Every layout rule broken by one skill, as readable strings; empty when it conforms. `units` (a UNITS entry) adds the unit rules, with `jobs` the job folders it names inside the repository rooted at `repo`; an attribute chain then counts as an import of the module it lands in."""
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
    repository = [*(python_files(tests_dir) if tests_dir.is_dir() else ()),
                  *(path for job in jobs if job.is_dir() for path in python_files(job))]
    reached = {}
    if units is not None:
        unit_found, reached = unit_violations(package, modules, repository, repo)
        found += unit_found
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imports = imported_modules(tree, name, path.name == '__init__.py')
        edges[name] = {target for target in modules
                       if any(i == target or i.startswith(target + '.') for i in imports) and target != name}
        edges[name] = {t for t in edges[name]
                       if not any(o != t and o.startswith(t + '.') and o in edges[name] for o in edges[name])
                       or t == 'cli'} | {t for t in reached.get(name, ()) if t != package}
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


SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
# Calls whose first string argument names an import path; like pkgutil.resolve_name, they take each part as a module while one exists.
PATCHERS = {'patch', 'setattr', 'delattr', 'import_module', '__import__', 'resolve_name'}


def import_targets(node, current, is_package):
    """(bound name, target) for each name an import binds. A target is (dotted name, how many leading parts are an explicit module path)."""
    if isinstance(node, ast.Import):
        return [(a.asname, (a.name, len(a.name.split('.')))) if a.asname else (a.name.split('.')[0], (a.name.split('.')[0], 1))
                for a in node.names]
    base = imported_modules(ast.Module(body=[node], type_ignores=[]), current, is_package)[0]
    return [(a.asname or a.name, (base + '.' + a.name, len(base.split('.')))) for a in node.names if a.name != '*']


def scope_bindings(scope, current, is_package):
    """What one scope binds: {name: {import target, or None for an argument, assignment, def or class}}. A nested scope's body binds in that scope, not here."""
    found = {}
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = scope.args
        for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]:
            if arg is not None:
                found.setdefault(arg.arg, set()).add(None)
    if isinstance(scope, COMPREHENSIONS):
        for generator in scope.generators:
            for name in ast.walk(generator.target):
                if isinstance(name, ast.Name):
                    found.setdefault(name.id, set()).add(None)

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, SCOPES):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    found.setdefault(child.name, set()).add(None)
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for name, target in import_targets(child, current, is_package):
                    found.setdefault(name, set()).add(target)
            elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                found.setdefault(child.id, set()).add(None)
            visit(child)

    visit(scope)
    return found


def dotted(node):
    """`a.b.c` as its parts when the chain starts at a name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return [node.id, *reversed(parts)] if isinstance(node, ast.Name) else None


def name_uses(tree, current, is_package):
    """Every name a module reaches statically, as (target, whether it is an attribute chain); a target is as in import_targets. The names are its imports, each attribute chain that starts at an imported name, and each patch-style string.

    A name is looked up through the scopes enclosing its use, so a local import, an argument or an assignment hides an outer import of the same name; a class body's names are not seen from its methods.
    """
    found = []

    def lookup(name, chain):
        for depth, (bindings, is_class) in enumerate(reversed(chain)):
            if is_class and depth:
                continue
            if name in bindings:
                return bindings[name]
        return set()

    def walk(node, chain):
        if isinstance(node, ast.Import):
            found.extend(((a.name, len(a.name.split('.'))), False) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.extend((target, False) for _, target in import_targets(node, current, is_package))
            base = imported_modules(ast.Module(body=[node], type_ignores=[]), current, is_package)[0]
            found.append(((base, len(base.split('.'))), False))
        elif isinstance(node, ast.Attribute) and not isinstance(getattr(node, 'parent', None), ast.Attribute):
            parts = dotted(node)
            if parts:
                found.extend((('.'.join([target, *parts[1:]]), explicit), True) for target, explicit in filter(None, lookup(parts[0], chain)))
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            if isinstance(node.func, ast.Attribute):
                patcher = node.func.attr in PATCHERS
            elif isinstance(node.func, ast.Name):
                bound = lookup(node.func.id, chain)  # a local def or argument named patch is not the patch API
                patcher = any(t and t[0].split('.')[-1] in PATCHERS for t in bound) if bound else node.func.id in PATCHERS
            else:
                patcher = False
            if patcher:
                found.append(((node.args[0].value, len(node.args[0].value.split('.'))), False))
        for child in ast.iter_child_nodes(node):
            child.parent = node
        if isinstance(node, SCOPES):
            # Decorators, bases, defaults, annotations and a comprehension's first iterable are evaluated where the scope is defined; the rest runs inside it.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                arguments = node.args
                every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
                outer = [*getattr(node, 'decorator_list', ()), *arguments.defaults, *filter(None, arguments.kw_defaults),
                         *(a.annotation for a in every if a is not None and a.annotation is not None), *filter(None, [getattr(node, 'returns', None)])]
                body = node.body if isinstance(node.body, list) else [node.body]
            elif isinstance(node, ast.ClassDef):
                outer, body = [*node.decorator_list, *node.bases, *node.keywords], node.body
            else:
                outer = [node.generators[0].iter]
                body = [child for child in ast.iter_child_nodes(node) if child is not node.generators[0]]
                body += [part for part in ast.iter_child_nodes(node.generators[0]) if part is not node.generators[0].iter]
            inner = chain + [(scope_bindings(node, current, is_package), isinstance(node, ast.ClassDef))]
            for child in outer:
                walk(child, chain)
            for child in body:
                walk(child, inner)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, chain)

    walk(tree, [(scope_bindings(tree, current, is_package), False)])
    return found


def resolve(target, modules, exports, seen=frozenset()):
    """(the modules a target passes through, the parts left unresolved). Its leading explicit parts are module paths; after them a module's own binding of a name wins over its submodule of that name, as attribute lookup does, and a binding to a module continues into it. A binding that names itself (`from . import client` in its own package) is the submodule."""
    seen = seen | {target}
    name, explicit = target
    parts = name.split('.')
    if parts[0] not in modules:
        return [], parts
    path = [parts[0]]
    for index, part in enumerate(parts[1:], 1):
        current = path[-1]
        bound = exports(current).get(part, set()) - seen if index >= explicit else set()
        if bound:
            into = [t for t in bound if t and not resolve(t, modules, exports, seen)[1]]
            if not into:
                return path, parts[index:]  # a value: the name stops in this module
            path.append(resolve(into[0], modules, exports, seen)[0][-1])
        elif current + '.' + part in modules:
            path.append(current + '.' + part)
        else:
            return path, parts[index:]
    return path, []


def unit_violations(package, modules, repository, repo):
    """The unit rules. Returns (violations, {module: the skill modules its attribute chains land in}).

    Outside a subpackage, code reaches it only through the names its `__init__.py` binds as values: an entry that binds one of its own modules, directly or through another module, is a violation, and so is any use that steps from a subpackage into one of its modules from outside. The skill never imports the repository's tests or jobs (`repository`, named by stem and by dotted path from `repo`).
    """
    found = []
    units = sorted(name for name, path in modules.items() if path.name == '__init__.py' and name != package)
    trees = {name: ast.parse(path.read_text(encoding='utf-8')) for name, path in modules.items()}
    exported = {name: scope_bindings(tree, name, modules[name].name == '__init__.py') for name, tree in trees.items()}

    def exports(module):
        return exported.get(module, {})

    for unit in units:
        for target in set().union(*exports(unit).values()) - {None}:
            path, rest = resolve(target, modules, exports)
            if not rest and path[-1].startswith(unit + '.'):
                found.append(f'{unit} binds its module {path[-1][len(unit) + 1:]} in its __init__')

    names = set()
    for path in repository:
        parts = path.relative_to(repo).with_suffix('').parts
        names |= {path.stem} | {'.'.join(parts[:i]) for i in range(1, len(parts) + 1)}
    reached = {}
    sources = [(name, name, path) for name, path in modules.items()] + [(path.name, '', path) for path in repository]
    for where, owner, path in sources:
        tree = trees[owner] if owner else ast.parse(path.read_text(encoding='utf-8'))
        for target, chained in name_uses(tree, owner or 'tests', path.name == '__init__.py'):
            passed = resolve(target, modules, exports)[0]
            for before, after in zip(passed, passed[1:]):
                if before in units and after.startswith(before + '.') and not (owner == before or owner.startswith(before + '.')):
                    found.append(f'{where} reaches past {before} into {after[len(before) + 1:].split(".")[0]}')
            if chained and owner and passed and passed[-1] != owner:
                reached.setdefault(owner, set()).add(passed[-1])
            if owner and any(target[0] == n or target[0].startswith(n + '.') for n in names):
                found.append(f'{where} imports repository code {target[0]}')
    return list(dict.fromkeys(found)), reached


def check_skill(root, skill, package, children, extra_scope=(), units=None):
    """One registered skill checked where it lives in a repository rooted at `root`. Its tests are named for the skill
    (a hyphen becomes an underscore), not for the package, which may carry a suffix to avoid shadowing a library."""
    tests = root / 'tests' / skill.replace('-', '_')
    jobs = (units or {}).get('jobs', ())
    missing = [f'{job} is missing' for job in jobs if not (root / job).is_dir()]
    return violations(root / '.claude/skills' / skill, tests, package, children, extra_scope, units, [root / job for job in jobs], root) + missing


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
    'tests/demo/test_demo.py': 'from unittest.mock import patch\n\nfrom demo.reading import read\nimport demo.web as web\n\nPATCH = patch("demo.web.fetch")\nVALUE = web.fetch, read\n',
    'jobs/demo/run.py': 'import subprocess\n\nfrom demo.web import fetch\n',
}
UNIT_RULES = {'edges': {('render', 'reading')}, 'jobs': ['jobs/demo']}


def unit_tree(tmp_path, files=None, units=UNIT_RULES):
    root = tmp_path / 'repo'
    write(root, {**UNIT_TREE, **(files or {})})
    return check_skill(root, 'demo', 'demo', KINDS, units=units)


SKILL = '.claude/skills/demo/scripts/demo/'


@pytest.mark.parametrize('files', [
    {},
    {SKILL + 'web/__init__.py': 'from demo.web.client import Failure, fetch\n\nTIMEOUT = 30\n\n\ndef lazy():\n    from . import client\n    return client\n'},
    {SKILL + 'render.py': 'from demo import reading\n\n\ndef show(reading):\n    return reading.helpers\n'},
    {'tests/demo/test_demo.py': 'MESSAGE = "the client lives in demo.web.client"\n'},
    {'tests/demo/test_demo.py': 'def patch(message):\n    return message\n\n\nPROBE = patch("demo.web.client")\n'},
], ids=['tree', 'local import inside an entry', 'parameter shadowing an import', 'a module path as plain text', 'a local function named patch'])
def test_a_conforming_unit_tree_has_no_violations(tmp_path, files):
    assert unit_tree(tmp_path, files) == []


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
    ({'tests/demo/test_demo.py': 'from unittest.mock import patch\n\nPATCH = patch("demo.web.client.fetch")\n'}, 'test_demo.py reaches past demo.web into client'),
    ({'tests/demo/test_demo.py': 'import pytest\n\n\ndef test_x(monkeypatch):\n    monkeypatch.setattr("demo.reading.read.helpers", None)\n'}, 'test_demo.py reaches past demo.reading into read'),
    ({SKILL + 'render.py': 'from demo import reading as x\n\nLEAK = x.helpers\n\n\ndef other():\n    import json as x\n    return x\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'reading/__init__.py': 'from demo.reading.read import read\nfrom .read import run\nfrom .bridge import public\n', SKILL + 'reading/bridge.py': 'from . import helpers as public\n'}, 'demo.reading binds its module helpers'),
    ({SKILL + 'reading/read.py': 'import demo as pkg\n\n\ndef read():\n    return pkg.render.VALUE\n\n\ndef run():\n    pass\n'}, 'demo.reading.read (feature) imports demo.render (feature)'),
    ({SKILL + 'state.py': 'from jobs.demo.run import fetch\n'}, 'demo.state imports repository code jobs.demo.run'),
    ({SKILL + 'render.py': 'from demo import reading as source\n\n\ndef probe(source=source.helpers):\n    return source\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({SKILL + 'render.py': 'from demo import reading as source\n\nPROBE = [source for source in source.helpers.items]\n'}, 'demo.render reaches past demo.reading into helpers'),
    ({'tests/demo/test_demo.py': 'from unittest.mock import patch as replace\n\nPROBE = replace("demo.web.client.fetch")\n'}, 'test_demo.py reaches past demo.web into client'),
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
