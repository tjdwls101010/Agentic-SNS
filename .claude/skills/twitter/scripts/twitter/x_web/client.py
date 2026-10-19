"""The X web client: requests made from the skill's own x.com tab, the way the app makes them. (Being written.)"""
import json
from pathlib import Path

_SNIPPETS = Path(__file__).with_name('snippets')
_KIT = (_SNIPPETS / 'kit.js').read_text(encoding='utf-8').strip()


def _compose(path):
    body = path.read_text(encoding='utf-8')
    if path.stem == 'arm':  # it decides first whether there is a document to install the kit on
        return 'async (args) => {\n  const KIT = (' + _KIT + ');\n' + body + '}'
    return 'async (args) => {\n  const kit = (' + _KIT + ')(args);\n' + body + '}'


SNIPPETS = {path.stem: _compose(path) for path in _SNIPPETS.glob('*.js') if path.stem != 'kit'}
OPERATIONS = json.loads(Path(__file__).with_name('operations.json').read_text(encoding='utf-8'))


def snippet(name):
    """The page function the browser runs for `name` (state, arm, query, modules, close, blank)."""
    return SNIPPETS[name]
