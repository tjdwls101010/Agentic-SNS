"""Yahoo Finance through the yfinance library: every dataset this skill reads, and the call that fetches one.

A command (cli.py) names its dataset by key; the two are joined into a Leaf here, where both sides are known.
"""
import yfinance as yf

from yfinance_skill.leaf import Leaf
from yfinance_skill.yahoo import analysts, calendar, company, financials, fund, holders, market, options, prices, screen, search
from yfinance_skill.yahoo.encode import encode

DATASETS = {**search.DATASETS, **prices.DATASETS, **company.DATASETS, **financials.DATASETS, **analysts.DATASETS,
            **holders.DATASETS, **fund.DATASETS, **options.DATASETS, **screen.DATASETS, **market.DATASETS,
            **calendar.DATASETS}


def bind(command):
    """The command joined to the dataset it reads. A key with no dataset fails here, on the command's first use."""
    if command.dataset not in DATASETS:
        raise LookupError(f"{command.path} reads dataset {command.dataset!r}, which yfinance_skill.yahoo does not define")
    return Leaf(command, DATASETS[command.dataset])


def fetch(key, target, args, context, warnings):
    """One target's response, encoded before anything is selected from it."""
    dataset = DATASETS[key]
    yf.config.debug.hide_exceptions = False
    return encode(dataset.fetch(yf.Ticker(target) if dataset.ticker else target, args, context, warnings))
