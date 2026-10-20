"""The page functions the browser runs, composed: every one gets the kit (the tab's shared state: the request ledger and
the memory of a rate limit) built around it, so the ledger is written once."""
from pathlib import Path

_HERE = Path(__file__).parent
_KIT = (_HERE / 'kit.js').read_text(encoding='utf-8').strip()

NAMES = ('state', 'query', 'page', 'route', 'modules')


def _compose(name):
    body = (_HERE / f'{name}.js').read_text(encoding='utf-8')
    return 'async (args) => {\n  const kit = (' + _KIT + ')(args);\n' + body + '}'


SNIPPETS = {name: _compose(name) for name in NAMES}


def snippet(name):
    """The page function the browser runs for `name` (state, query, page, route, modules)."""
    return SNIPPETS[name]
