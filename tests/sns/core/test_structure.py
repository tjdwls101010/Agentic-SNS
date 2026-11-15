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

from tests.sns.support import tree

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / '.claude/skills/sns'
SCRIPTS = SKILL / 'scripts'
PACKAGE = SCRIPTS / 'sns'
TESTS = REPO / 'tests/sns'
CONTRAST = REPO / 'contrast/sns'

HELPERS = {'errors', 'limits', 'redact', 'atomic', 'paths', 'clock', 'page', 'paging', 'window', 'results', 'text',
           'render', 'cmdline', 'platforms'}
STORES = {'protection', 'handles', 'session', 'outfile', 'images', 'saved'}
SYSTEMS = {'aside'}
FEATURES = {'reading', 'maintenance'}
FEATURE_EDGES = set()  # reading and maintenance currently do not import one another
SHARED = HELPERS | STORES | SYSTEMS | FEATURES
PLATFORMS = {'x', 'threads', 'reddit', 'facebook', 'naver_blog'}
PLATFORM_STORES = {'reddit': {'snapshots'}}  # a platform's own stores, beside its system web/


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
    allowed = {'SKILL.md', 'references', 'scripts'}  # state lives outside the skill folder (decision A5)
    present = set(tree.children(SKILL))
    assert present <= allowed, present - allowed
    assert {'SKILL.md', 'scripts'} <= present
    scripts = set(tree.children(SCRIPTS))
    assert scripts == {'cli.py', 'sns'}


def test_package_name_does_not_shadow_stdlib():
    assert 'sns' not in sys.stdlib_module_names


def test_package_holds_only_known_units():
    found = {name[:-3] if name.endswith('.py') else name for name in tree.children(PACKAGE) if name != '__init__.py'}
    assert found <= SHARED | PLATFORMS, found - SHARED - PLATFORMS
    assert SHARED | PLATFORMS <= found, (SHARED | PLATFORMS) - found
    for name in STORES | SYSTEMS | FEATURES:
        assert (PACKAGE / name / '__init__.py').is_file(), name


def test_platform_folders_hold_features_web_and_their_own_store_only():
    for platform in PLATFORMS:
        root = PACKAGE / platform
        assert (root / '__init__.py').is_file()
        assert (root / 'web' / '__init__.py').is_file(), platform
        folders = tree.folders(root)
        assert folders <= {'web'} | PLATFORM_STORES.get(platform, set()), (platform, folders)
        for store in PLATFORM_STORES.get(platform, set()) & folders:
            assert (root / store / '__init__.py').is_file()


def test_cli_registry_matches_platform_packages():
    parsed = ast.parse((PACKAGE / 'platforms.py').read_text(encoding='utf-8'))
    registry = next(ast.literal_eval(node.value) for node in parsed.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'PLATFORM_PACKAGES' for target in node.targets))
    cli = ast.parse((SCRIPTS / 'cli.py').read_text(encoding='utf-8'))
    assert any(isinstance(node, ast.ImportFrom) and node.module == 'sns.platforms' and any(alias.name == 'PLATFORM_PACKAGES' and alias.asname is None for alias in node.names) for node in cli.body)
    assert any(isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == 'PLATFORM_PACKAGES' for node in ast.walk(cli))
    packages = {name for name in tree.folders(PACKAGE) if name not in SHARED and (PACKAGE / name / '__init__.py').is_file()}
    assert len(registry) == len(set(registry)) and set(registry) == packages, (registry, packages)


def test_an_old_data_folder_is_never_committed():
    """An install from before the state moved keeps data/ beside SKILL.md (handles, sessions, request logs: other people's
    content and the account's history); the repository is public, so it is ignored and nothing in it is tracked."""
    tracked = subprocess.run(['git', 'ls-files', str(SKILL / 'data')], cwd=REPO, capture_output=True, text=True,
                             check=True).stdout.split()
    assert tracked == []
    ignored = subprocess.run(['git', 'check-ignore', '-q', str(SKILL / 'data' / 'x' / 'u0' / 'protection' / 'blocks.json')],
                             cwd=REPO)
    assert ignored.returncode == 0


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
        return t_unit in HELPERS | STORES | SYSTEMS or (s_unit, t_unit) in FEATURE_EDGES
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


def test_platform_interfaces_do_not_define_command_surfaces():
    for platform in PLATFORMS:
        path = PACKAGE / platform / '__init__.py'
        source = path.read_text(encoding='utf-8')
        parsed = ast.parse(source)
        assigned = {node.id for node in ast.walk(parsed) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        assert not {'COMMANDS', 'CHOICES'} & assigned, platform
        top_level = {target.id for node in parsed.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
        assert top_level <= {'PLATFORM', 'POLICY', 'RECORDS', 'TREE'}, (platform, top_level)
        assert {node.name for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))} <= {'connect'}, platform
        assert not any(isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in ('help', 'epilog', 'arguments') for node in ast.walk(parsed)), platform


def test_web_interfaces_are_the_only_external_access():
    exports = {}
    for platform in PLATFORMS:
        root = PACKAGE / platform / 'web'
        parsed = ast.parse((root / '__init__.py').read_text(encoding='utf-8'))
        exports[platform] = set(next(ast.literal_eval(node.value) for node in parsed.body
                                     if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__all__' for t in node.targets)))
        modules = {alias.asname or alias.name for node in parsed.body if isinstance(node, ast.ImportFrom)
                   and node.module == f'sns.{platform}.web' for alias in node.names}
        assert not exports[platform] & modules, (platform, exports[platform] & modules)

    problems = []
    for root in (SCRIPTS, TESTS, CONTRAST):
        for path in python_files(root):
            parsed = ast.parse(path.read_text(encoding='utf-8'))
            aliases = {}
            dotted = set()
            platform_aliases = {}
            sns_aliases = set()
            for node in ast.walk(parsed):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    if node.level and path.is_relative_to(SCRIPTS):
                        base = path.relative_to(SCRIPTS).with_suffix('').parts[:-node.level]
                        module = '.'.join([*base, module] if module else base)
                    if module == 'sns':
                        for alias in node.names:
                            if alias.name in PLATFORMS:
                                platform_aliases[alias.asname or alias.name] = alias.name
                    for platform in PLATFORMS:
                        web = f'sns.{platform}.web'
                        if path.is_relative_to(PACKAGE / platform / 'web'):
                            continue
                        if module.startswith(web + '.'):
                            problems.append(f'{path}:{node.lineno}: reaches past {web}: {module}')
                        elif module == web:
                            for alias in node.names:
                                if alias.name not in exports[platform]:
                                    problems.append(f'{path}:{node.lineno}: {web}.{alias.name} is not exported')
                        elif module == f'sns.{platform}':
                            for alias in node.names:
                                if alias.name == 'web':
                                    aliases[alias.asname or alias.name] = platform
                else:
                    for alias in node.names:
                        if alias.name == 'sns':
                            sns_aliases.add(alias.asname or 'sns')
                        for platform in PLATFORMS:
                            if alias.name == f'sns.{platform}' and alias.asname:
                                platform_aliases[alias.asname] = platform
                            elif alias.name == f'sns.{platform}':
                                sns_aliases.add('sns')
                            web = f'sns.{platform}.web'
                            if path.is_relative_to(PACKAGE / platform / 'web'):
                                continue
                            if alias.name.startswith(web + '.'):
                                problems.append(f'{path}:{node.lineno}: reaches past {web}: {alias.name}')
                            elif alias.name == web:
                                if alias.asname:
                                    aliases[alias.asname] = platform
                                else:
                                    dotted.add(platform)
            for node in ast.walk(parsed):
                if isinstance(node, ast.Attribute):
                    parts = []
                    value = node.value
                    while isinstance(value, ast.Attribute):
                        parts.append(value.attr)
                        value = value.value
                    if isinstance(value, ast.Name):
                        parts.append(value.id)
                        parts.reverse()
                        platform = None
                        if len(parts) == 3 and parts[0] in sns_aliases | {'sns'} and parts[1] in PLATFORMS and parts[2] == 'web' and (parts[0] in sns_aliases or parts[1] in dotted):
                            platform = parts[1]
                        elif len(parts) == 2 and parts[0] in platform_aliases and parts[1] == 'web':
                            platform = platform_aliases[parts[0]]
                        if platform and not path.is_relative_to(PACKAGE / platform / 'web') and node.attr not in exports[platform]:
                            problems.append(f'{path}:{node.lineno}: sns.{platform}.web.{node.attr} is not exported')
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                    platform = aliases[node.value.id]
                    if node.attr not in exports[platform]:
                        problems.append(f'{path}:{node.lineno}: sns.{platform}.web.{node.attr} is not exported')
    assert not problems, '\n'.join(problems)


def test_result_descriptions_do_not_list_platforms():
    parsed = ast.parse((PACKAGE / 'results.py').read_text(encoding='utf-8'))
    descriptions = [node.value for node in ast.walk(parsed) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    names = '|'.join(re.escape(p).replace('_', '[-_]') for p in PLATFORMS)
    pattern = re.compile(r'(?<![A-Za-z])(?:' + names + r')(?![A-Za-z])', re.I)
    found = [value for value in descriptions if pattern.search(value)]
    assert not found, found


def test_redact_defines_only_shared_secret_fields():
    parsed = ast.parse((PACKAGE / 'redact.py').read_text(encoding='utf-8'))
    shared = next(ast.literal_eval(node.value) for node in parsed.body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'SENSITIVE' for t in node.targets))
    assert shared == {'token', 'access_token', 'cookie', 'cookies', 'authorization', 'csrf', 'sessionid', 'bearer'}, shared
    platform_values = set()
    for platform in PLATFORMS:
        adapter = ast.parse((PACKAGE / platform / '__init__.py').read_text(encoding='utf-8'))
        for node in ast.walk(adapter):
            if isinstance(node, ast.keyword) and node.arg in {'secret_fields', 'signed_image_hosts'}:
                platform_values.update(ast.literal_eval(node.value))
    literals = {node.value for node in ast.walk(parsed) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not literals & platform_values, literals & platform_values
