"""The page functions the browser runs, composed: every one gets the kit (the tab's shared state: the request ledger,
the signal store and cached access to the app) built around it; arm installs it first."""
from pathlib import Path

_HERE = Path(__file__).parent
_KIT = (_HERE / 'kit.js').read_text(encoding='utf-8').strip()


def _compose(name):
    body = (_HERE / f'{name}.js').read_text(encoding='utf-8')
    if name == 'arm':  # it decides first whether there is a document to install the kit on
        return 'async (args) => {\n  const KIT = (' + _KIT + ');\n' + body + '}'
    return 'async (args) => {\n  const kit = (' + _KIT + ')(args);\n' + body + '}'


NAMES = ('state', 'arm', 'query', 'modules')
SNIPPETS = {name: _compose(name) for name in NAMES}


def snippet(name):
    """The page function the browser runs for `name` (state, arm, query, modules)."""
    return SNIPPETS[name]
