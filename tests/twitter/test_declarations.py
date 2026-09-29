"""A command is defined once, in cli.py's SURFACES: nothing in the package branches or validates on the command.

Branching means comparing, testing membership, matching or indexing by `.command`, or comparing against command-name literals. Storing the command in a query context or showing it in a header is allowed. The names user, post, list and community are also record and target kinds, so a literal of only those names is left to the `.command` check; a literal set is flagged only when every member is a command name, so X's reserved URL paths (home, search, i, …) are not.
"""
import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / '.claude/skills/twitter/scripts'
KINDS = {'user', 'post', 'list', 'community'}


def commands(cli=SCRIPTS / 'cli.py'):
    for node in ast.walk(ast.parse(cli.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SURFACES' for t in node.targets):
            return {key.value for key in node.value.keys}
    raise AssertionError('cli.py declares no SURFACES dict')


def is_command(node):
    return (isinstance(node, ast.Attribute) and node.attr == 'command' or isinstance(node, ast.Name) and node.id == 'command'
            or isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'getattr'
            and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 'command')


def literals(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and node.elts and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return {e.value for e in node.elts}
    return set()


def branches(source, names):
    """Lines of `source` that branch or validate on the command."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            named = [literals(o) for o in operands]
            if any(is_command(o) for o in operands) or any(
                    values and values <= names and values - KINDS for values in named):
                found.append(node.lineno)
        elif isinstance(node, ast.Subscript) and is_command(node.slice):
            found.append(node.lineno)
        elif isinstance(node, ast.Match) and (is_command(node.subject) or any(
                isinstance(case.pattern, ast.MatchValue) and literals(case.pattern.value) & (names - KINDS)
                for case in node.cases)):
            found.append(node.lineno)
    return found


def test_no_package_module_branches_on_the_command():
    names = commands()
    found = {str(path.relative_to(SCRIPTS)): lines for path in sorted((SCRIPTS / 'twitter').rglob('*.py'))
             if (lines := branches(path.read_text(encoding='utf-8'), names))}
    assert found == {}


@pytest.mark.parametrize('source', [
    "if args.command == 'home':\n    pass\n",
    "x = args.command in ('home', 'me')\n",
    "x = name == 'trends'\n",
    "x = getattr(args, 'command') != 'x'\n",
    "x = TABLE[args.command]\n",
    "match args.command:\n    case 'home':\n        pass\n",
    "match name:\n    case 'refresh':\n        pass\n",
    "x = args.command == 'user'\n",
])
def test_the_check_catches_command_branching(source):
    assert branches(source, {'home', 'me', 'trends', 'refresh', 'user'})


@pytest.mark.parametrize('source', [
    "x = kind == 'user'\n",
    "x = value.lower() in {'home', 'i', 'messages'}\n",
    "header = [args.command, 'shown']\n",
    "context = dict(command=args.command)\n",
    "x = rows == 'trend'\n",
])
def test_the_check_allows_kinds_reserved_paths_and_display(source):
    assert branches(source, {'home', 'me', 'trends', 'refresh', 'user'}) == []
