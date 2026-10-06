"""The Yahoo boundary, read from the source: only invest/yahoo/ imports yfinance, pandas or numpy.

Everything outside it works on the skill's own values, so a pandas object cannot leak past the system that owns the library. An import elsewhere, even inside a function, is where that leak starts, so this reads every module's syntax tree rather than running anything.
"""
import ast
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / ".claude/skills/invest/scripts"
LIBRARIES = {"yfinance", "pandas", "numpy"}


def imported_roots(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.module.split(".")[0]


def test_only_the_yahoo_package_imports_the_data_libraries():
    yahoo = SCRIPTS / "invest" / "yahoo"
    outside = {}
    for path in sorted(SCRIPTS.rglob("*.py")):
        if yahoo in path.parents:
            continue
        found = LIBRARIES & set(imported_roots(ast.parse(path.read_text(encoding="utf-8"))))
        if found:
            outside[str(path.relative_to(SCRIPTS))] = sorted(found)
    assert outside == {}


def test_result_files_are_written_with_the_standard_library():
    """results.py writes csv and json itself, so the file format does not depend on pandas' writers."""
    tree = ast.parse((SCRIPTS / "invest" / "results.py").read_text(encoding="utf-8"))
    assert {"csv", "json"} <= set(imported_roots(tree))
