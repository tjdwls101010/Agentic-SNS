"""Tests reach the skill through three seams only: the CLI process, the records public API, and the JS snippets.

Of the Python package, a test may import nothing but the public names of `facebook.graphql.records`; everything
else is exercised through `cli.py` in a subprocess, so moving or rewriting internals never breaks a test by itself.
"""
import ast
from pathlib import Path

from tests.facebook.helpers import SKILL

TESTS = Path(__file__).resolve().parent
RECORDS = SKILL / 'scripts/facebook/graphql/records/__init__.py'


def public_records_names():
    names = set()
    for node in ast.parse(RECORDS.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return {name for name in names if not name.startswith('_')}


def production_imports(path):
    """(line, module, names) for every import of the skill package in one test file."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name, None) for alias in node.names
                      if alias.name == 'facebook' or alias.name.startswith('facebook.')]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module and (
                node.module == 'facebook' or node.module.startswith('facebook.')):
            found.append((node.lineno, node.module, [alias.name for alias in node.names]))
    return found


def test_tests_import_only_the_public_records_api():
    public = public_records_names()
    assert {'post_page', 'post_story', 'post_record', 'comment_page', 'reply_page', 'search_page',
            'about_collections', 'about_fields', 'SCHEMAS', 'Page'} <= public
    violations = []
    for path in sorted(TESTS.rglob('*.py')):
        for line, module, names in production_imports(path):
            if module != 'facebook.graphql.records' or names is None or not set(names) <= public:
                violations.append(f'{path.relative_to(TESTS)}:{line} imports {module} {names or ""}')
    assert violations == []


def test_the_seam_check_notices_a_private_import(tmp_path):
    sample = tmp_path / 'test_sample.py'
    sample.write_text('from facebook.graphql.records.post import build_post\nimport facebook.reading.paging\n'
                      'from facebook.graphql.records import _post, post_page\n')
    assert [(module, names) for _, module, names in production_imports(sample)] == [
        ('facebook.graphql.records.post', ['build_post']), ('facebook.reading.paging', None),
        ('facebook.graphql.records', ['_post', 'post_page'])]
    assert '_post' not in public_records_names()


def declared_stop_reasons():
    outcome = ast.parse((SKILL / 'scripts/facebook/outcome.py').read_text())
    declared = next(node.value for node in outcome.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'STOP_REASONS' for t in node.targets))
    return {key.value for key in declared.keys}


def _is_reason_target(node):
    return (isinstance(node, ast.Name) and node.id in ('reason', 'stop_reason')
            or isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
            and node.slice.value == 'stop_reason')


def stop_reason_problems(source, reasons):
    """Literals outside the declared vocabulary, and any code that turns one reason into another."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        values = []
        if isinstance(node, ast.keyword) and node.arg == 'stop_reason':
            values = [node.value]
        elif isinstance(node, ast.Dict):
            values = [v for k, v in zip(node.keys, node.values)
                      if isinstance(k, ast.Constant) and k.value == 'stop_reason']
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            mapped = [v.value for v in node.values if isinstance(v, ast.Constant)]
            if keys and set(keys) <= reasons | {'already_complete', 'reply_batch_limit'} and set(mapped) <= reasons:
                problems.append(f'{node.lineno}: maps stop reasons')
        elif isinstance(node, ast.Assign) and any(_is_reason_target(t) for t in node.targets):
            values = [node.value]
        elif isinstance(node, ast.If):
            tested = any(_is_reason_target(n) or isinstance(n, ast.Constant) and n.value in reasons
                         for n in ast.walk(node.test))
            reassigned = any(isinstance(n, ast.Assign) and any(_is_reason_target(t) for t in n.targets)
                             and isinstance(n.value, ast.Constant) for stmt in node.body for n in ast.walk(stmt))
            if tested and reassigned:
                problems.append(f'{node.lineno}: rewrites a stop reason under a condition on it')
        for value in values:
            if isinstance(value, ast.Constant) and value.value not in reasons | {None}:
                problems.append(f'{node.lineno}: sets stop_reason {value.value!r}')
    return problems


def test_only_outcome_names_or_maps_stop_reasons():
    """Production code may set a stop_reason only to a declared value, and only outcome.py maps one onto another."""
    reasons = declared_stop_reasons()
    package = SKILL / 'scripts/facebook'
    problems = [f'{path.name}:{line}' for path in sorted(package.rglob('*.py')) if path.name != 'outcome.py'
                for line in stop_reason_problems(path.read_text(), reasons)]
    assert problems == []


def test_the_stop_reason_guard_notices_remaps():
    reasons = declared_stop_reasons()
    for source in ("result['stop_reason'] = {'already_complete': 'exhausted'}.get(r, r)\n",
                   "if result['stop_reason'] == 'exhausted':\n    result['stop_reason'] = 'limit_reached'\n",
                   "if end == END and reason in ('limit_reached', 'exhausted', None):\n    reason = 'exhausted'\n",
                   "result = {'stop_reason': 'reply_batch_limit'}\n"):
        assert stop_reason_problems(source, reasons), source
