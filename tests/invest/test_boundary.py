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


def test_only_the_sec_package_imports_the_document_libraries_and_only_fetch_imports_requests():
    sec = SCRIPTS / "invest" / "sec"
    outside = {}
    for path in sorted(SCRIPTS.rglob("*.py")):
        found = set(imported_roots(ast.parse(path.read_text(encoding="utf-8"))))
        wrong = (found & {"lxml", "bs4"} if sec not in path.parents else set()) | (found & {"requests"} if path != sec / "fetch.py" else set())
        if wrong:
            outside[str(path.relative_to(SCRIPTS))] = sorted(wrong)
    assert outside == {}


# Inside sec, each module imports only from a lower layer, so the reader has no cycle and the plain-text rule sits at the bottom.
SEC_LAYERS = {"text": 0, "failures": 0, "decode": 1, "emphasis": 1, "grid": 1, "locate": 1, "markup": 2, "document": 3, "fetch": 4}


def sec_imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module == "invest.sec":
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("invest.sec."):
            yield node.module.split(".")[2]


def test_the_sec_modules_import_downward_only():
    sec = SCRIPTS / "invest" / "sec"
    assert {p.stem for p in sec.glob("*.py")} - {"__init__"} == set(SEC_LAYERS)
    upward = {p.stem: sorted(m for m in sec_imports(p) if SEC_LAYERS[m] >= SEC_LAYERS[p.stem])
              for p in sec.glob("*.py") if p.stem != "__init__"}
    assert {name: found for name, found in upward.items() if found} == {}
