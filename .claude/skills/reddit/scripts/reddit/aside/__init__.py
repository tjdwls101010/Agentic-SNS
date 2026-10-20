"""System: the Aside CLI. Resolve the Aside account and run the fetch snippet in its REPL."""
from reddit.aside.repl import SNIPPET, Aside, active_account, parse

__all__ = ['Aside', 'SNIPPET', 'active_account', 'parse']
