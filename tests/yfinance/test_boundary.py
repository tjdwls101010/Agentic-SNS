"""The Yahoo boundary, read from the source: only yfinance_skill/yahoo/ imports yfinance, pandas or numpy.

Everything outside it works on the skill's own encoded representation, which is what lets `read` reuse the selection
that printed an observation. An import of the library elsewhere, even inside a function, is where a pandas object
would start leaking past the adapter, so this reads every module's syntax tree rather than running anything.
"""
import ast
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / ".claude/skills/yfinance/scripts"
LIBRARIES = {"yfinance", "pandas", "numpy"}


def imported_roots(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.module.split(".")[0]


def test_only_the_yahoo_package_imports_the_data_libraries():
    yahoo = SCRIPTS / "yfinance_skill" / "yahoo"
    outside = {}
    for path in sorted(SCRIPTS.rglob("*.py")):
        if yahoo in path.parents:
            continue
        found = LIBRARIES & set(imported_roots(ast.parse(path.read_text(encoding="utf-8"))))
        if found:
            outside[str(path.relative_to(SCRIPTS))] = sorted(found)
    assert outside == {}
