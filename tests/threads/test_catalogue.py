"""One declaration per operation: the skill's code names Meta's operations only in the catalogue and its registry."""
import re

from .helpers import SKILL

NAME = re.compile(r'\b(?:use)?Barcelona[A-Za-z]*(?:Query|Mutation)\b')
CATALOGUE = {'threads/graphql/operations.py', 'threads/graphql/registry.json'}


def test_meta_operation_names_appear_only_in_the_catalogue():
    scripts = SKILL / 'scripts'
    found = {}
    for path in sorted(scripts.rglob('*')):
        if path.suffix not in ('.py', '.js', '.json') or '__pycache__' in path.parts:
            continue
        relative = path.relative_to(scripts).as_posix()
        names = NAME.findall(path.read_text(encoding='utf-8'))
        if names and relative not in CATALOGUE:
            found[relative] = sorted(set(names))
    assert found == {}
