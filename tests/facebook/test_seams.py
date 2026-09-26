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
