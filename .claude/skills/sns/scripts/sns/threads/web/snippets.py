"""The page functions the browser runs, composed: every one gets the kit (the tab's shared state: the request ledger and
the signal store) built around it."""
from pathlib import Path

_HERE = Path(__file__).parent
_KIT = (_HERE / 'kit.js').read_text(encoding='utf-8').strip()

NAMES = ('state', 'query', 'page', 'modules', 'navigate')
SNIPPETS = {name: 'async (args) => {\n  const kit = (' + _KIT + ')(args);\n'
            + (_HERE / f'{name}.js').read_text(encoding='utf-8') + '}' for name in NAMES}


def snippet(name):
    """The page function the browser runs for `name` (state, query, page, modules, navigate)."""
    return SNIPPETS[name]
