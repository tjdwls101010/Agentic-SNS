"""The Threads web client: requests made from the skill's own www.threads.com tab, the way the app makes them."""
from pathlib import Path

_SNIPPETS = Path(__file__).with_name('snippets')
_KIT = (_SNIPPETS / 'kit.js').read_text(encoding='utf-8').strip()
# Every page function is the shared kit (the tab's ledger and signal store) followed by its own body.
SNIPPETS = {path.stem: 'async (args) => {\n  const kit = (' + _KIT + ')(args);\n' + path.read_text(encoding='utf-8') + '}'
            for path in _SNIPPETS.glob('*.js') if path.stem != 'kit'}


def snippet(name):
    """The page function the browser runs for `name` (state, query, page, modules, blank, navigate)."""
    return SNIPPETS[name]


class Client:
    """One invocation's connection to Threads. browser: the Aside system; guard: account protection; memory: the
    session store."""

    def __init__(self, browser, guard, memory, verbose=False):
        self.browser, self.guard, self.memory, self.verbose = browser, guard, memory, verbose

    def start(self):
        raise NotImplementedError
