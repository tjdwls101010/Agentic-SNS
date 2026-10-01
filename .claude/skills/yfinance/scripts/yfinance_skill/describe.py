"""What each command's values mean, as Yahoo returns them: the facts a command's --help places beside its arguments.

cli.py owns the document and the input contract; these facts come from the command's Yahoo dataset, which cli.py cannot import.
"""
from yfinance_skill import yahoo
from yfinance_skill.leaf import Leaf


def describe(command):
    """{limit_keeps, units, interpretation, limits, gotchas} for one command; empty facts are left out."""
    item = Leaf(command, yahoo.dataset(command.dataset))
    facts = {"limit_keeps": item.limit_keeps(), "units": item.units, "interpretation": item.interpretation,
             "limits": item.limits, "gotchas": list(item.gotchas)}
    return {k: v for k, v in facts.items() if v}
